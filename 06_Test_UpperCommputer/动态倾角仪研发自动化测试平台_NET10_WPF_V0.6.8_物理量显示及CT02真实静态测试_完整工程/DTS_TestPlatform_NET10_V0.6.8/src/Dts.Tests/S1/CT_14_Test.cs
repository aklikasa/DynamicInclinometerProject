using System.Globalization;
using System.Security.Cryptography;
using System.Text.Json;
using Dts.Core;
using Dts.TestEngine;
using Dts.Tests.S1.CT14;

namespace Dts.Tests.S1;

/// <summary>CT-14 V1.1: operator-assisted remount reproducibility using the existing V0.6.8 hardware session.</summary>
// CT14_MODULE_V1.1 - additive module; no shared hardware adapter changes.
public sealed class CT_14_Test : TestModuleBase
{
    public override string TestId => "CT-14";
    public override bool IsExecutable => true;
    public override bool RequiresStaticBench => true;
    public override string Name => "重复装夹与复测一致性";
    public override string Purpose => "通过多次人工拆卸/重新装夹，在相同转台姿态下重复采集ACC/Gyro，量化装夹引入的跨轮测量差异。";
    public override string Procedure => "人工重新装夹并核验UID→预热→转台按姿态计划定位→真实FIFO采集→常温矩阵补偿→跨装夹统计与报告。";
    public override string Priority => "P0";
    public override string ImplementationNote => "每次ExecuteAsync只执行一轮装夹；人工拆装由CT14窗口逐轮确认。需固定夹具基准、紧固方式、线缆及预热时间；不自动判PASS。";

    public override async Task<TestExecutionResult> ExecuteAsync(TestExecutionContext context, CancellationToken ct)
    {
        if (context.Hardware is not IStaticAngleHardware hw)
            throw new InvalidOperationException("CT-14需要真实IMU FIFO和2TD双轴反馈接口。");
        if (context.Parameters is not Ct14Settings s)
            throw new InvalidOperationException("CT-14缺少专用参数快照。");
        if (!hw.IsTwoTdConnected)
            throw new InvalidOperationException("真实2TD双轴转台未连接。");

        var id = hw.CurrentIdentity ?? throw new InvalidOperationException("IMU未连接或未读取完整UID。");
        var run = s.Calibration;
        if (run.Mode != CalibrationMode.Ambient)
            throw new InvalidOperationException("CT-14要求主程序选择当前PCB的常温标定模式。");
        run.Validate(id);
        var acc = run.Files?.Acc ?? throw new InvalidDataException("缺少UID匹配的ACC常温JSON。");
        var gyro = run.Files?.Gyro ?? throw new InvalidDataException("缺少UID匹配的Gyro常温JSON。");
        if (acc.FsHint is null || gyro.FsHint is null)
            throw new InvalidDataException("常温ACC/Gyro JSON缺少拟合输入量程FsHint，拒绝猜测量程。");
        var scale = CalibrationInputScalePolicy.Resolve(acc.FsHint, gyro.FsHint, 0, 0)
            ?? throw new InvalidDataException("标定JSON输入量程不受支持。");
        int gravitySign = ReadGravitySignAndAxisModel(acc.FilePath);
        Ct14Algorithm.Validate(s);
        ValidateCalibrationHashes(run);
        await hw.VerifyImuForPrecisionTestAsync(ct);

        var first = await hw.ReadTwoTdAsync(ct);
        VerifyAxisState(first, false);
        EnsureWithin(first.Inner.PositionDeg, s);
        EnsureWithin(first.Outer.PositionDeg, s);
        string root = Path.GetFullPath(s.OutputRoot);
        if (!Directory.Exists(root)) throw new DirectoryNotFoundException("CT-14报告根目录不存在：" + root);
        Directory.CreateDirectory(s.SessionFolder);
        string folder = Path.Combine(s.SessionFolder, $"mount_{s.MountIndex:D2}");
        Directory.CreateDirectory(folder);

        var visits = new List<Ct14Visit>();
        string state = "RUNNING", reason = "";
        bool motionRequested = false;
        string stopProblem = "", reportProblem = "";
        IReadOnlyList<string> reportFiles = Array.Empty<string>();
        var started = DateTimeOffset.UtcNow;
        var snapshot = new Ct14SettingsSnapshot(s.PlannedMounts, s.MountingProcedureNote, s.Poses, s.RepeatsPerPose,
            s.MotionSpeedDps, s.WarmupSeconds, s.SettleSeconds, s.SampleSeconds,
            s.PositionToleranceDeg, s.AllowedMinDeg, s.AllowedMaxDeg,
            s.MinValidSamples, s.MaxOutlierFraction);

        Ct14ReportData MakeReport() => new("CT-14", "重复装夹与复测一致性",
            id.DtsId, id.UidHex, s.MountIndex, started, DateTimeOffset.UtcNow, state, reason,
            "单轮装夹采集已完成不等于产品合格；最终结论需结合跨装夹差异、温度、夹具规范和产品指标独立验收。",
            Path.GetFileName(acc.FilePath), acc.Sha256, Path.GetFileName(gyro.FilePath), gyro.Sha256,
            gravitySign, "Python outer_x_inner_z；R=Rx(outer)Rz(inner)，重力参考由每次实际到位反馈计算",
            scale.Display, snapshot, visits.ToArray(), Ct14Algorithm.Summarize(visits));

        try
        {
            await File.WriteAllTextAsync(Path.Combine(folder, "CT-14_mount_identity.json"),
                JsonSerializer.Serialize(new
                {
                    TestId, MountIndex = s.MountIndex, PlannedMounts = s.PlannedMounts,
                    Device = id.DtsId, UID = id.UidHex, PowerOnAndRemount = "OPERATOR_CONFIRMED",
                    AccJson = acc.FilePath, AccSha256 = acc.Sha256, AccRunId = acc.RunId, AccFsHint = acc.FsHint,
                    GyroJson = gyro.FilePath, GyroSha256 = gyro.Sha256, GyroRunId = gyro.RunId, GyroFsHint = gyro.FsHint,
                    InputScale = scale.Display, GravitySign = gravitySign,
                    MountingProcedure = s.MountingProcedureNote,
                    Note = "每轮只记录人工确认，不把软件确认框当作机械装夹已正确的证据。"
                }, new JsonSerializerOptions { WriteIndented = true }), ct);

            if (s.WarmupSeconds > 0)
            {
                context.Progress?.Report($"CT-14 装夹{s.MountIndex}/{s.PlannedMounts}：等待重新上电后的统一预热 {s.WarmupSeconds:F0}s。");
                await Task.Delay(TimeSpan.FromSeconds(s.WarmupSeconds), ct);
            }
            EnsureSameDevice(hw, id);
            ValidateCalibrationHashes(run);

            int total = s.Poses.Count * s.RepeatsPerPose;
            int done = 0;
            motionRequested = true;
            foreach (var pose in s.Poses)
            {
                ct.ThrowIfCancellationRequested();
                EnsureSameDevice(hw, id);
                ValidateCalibrationHashes(run);
                context.Progress?.Report($"CT-14 装夹{s.MountIndex}/{s.PlannedMounts}：定位姿态{pose.Index}/{s.Poses.Count}，内轴{pose.InnerDeg:F1}°/外轴{pose.OuterDeg:F1}°。");
                await MoveToAsync(hw, pose.InnerDeg, pose.OuterDeg, s, ct);
                await Task.Delay(TimeSpan.FromSeconds(s.SettleSeconds), ct);

                for (int rep = 1; rep <= s.RepeatsPerPose; rep++)
                {
                    ct.ThrowIfCancellationRequested();
                    EnsureSameDevice(hw, id);
                    ValidateCalibrationHashes(run);
                    var before = await hw.ReadTwoTdAsync(ct);
                    VerifyPose(before, pose, s);
                    string stem = $"mount_{s.MountIndex:D2}_pose_{pose.Index:D2}_rep_{rep:D2}";
                    string physical = Path.Combine(folder, stem + "_physical.csv");
                    string corrected = Path.Combine(folder, stem + "_corrected.csv");
                    context.Progress?.Report($"CT-14 [{done + 1}/{total}] 装夹{s.MountIndex} / 姿态{pose.Index} / 重复{rep}：真实FIFO采集{ s.SampleSeconds:F1}s。");
                    var capture = await hw.CaptureStaticPointAsync(physical,
                        TimeSpan.FromSeconds(s.SampleSeconds), context.Progress, ct);
                    var after = await hw.ReadTwoTdAsync(ct);
                    VerifyPose(after, pose, s);
                    if (Ct14Algorithm.Distance(before.Inner.PositionDeg, after.Inner.PositionDeg) > s.PositionToleranceDeg ||
                        Ct14Algorithm.Distance(before.Outer.PositionDeg, after.Outer.PositionDeg) > s.PositionToleranceDeg)
                        throw new InvalidDataException("采样期间2TD实际位置发生变化，拒绝本次数据。");

                    ValidateCalibrationHashes(run);
                    VerifyPhysicalCsvScale(physical, scale.AccFullScaleG, scale.GyroFullScaleDps);
                    var analyzed = Ct14Algorithm.Analyze(s, pose, rep, before, after, capture,
                        acc.Apply, gyro.Apply, gravitySign, physical, corrected);
                    await Ct14Algorithm.SaveCorrectedCsvAsync(corrected, capture,
                        analyzed.Accepted, analyzed.Acc, analyzed.Gyro, ct);
                    visits.Add(analyzed.Visit with { VisitIndex = visits.Count + 1 });
                    await Ct14Report.SaveMountCheckpointAsync(folder, MakeReport(), ct);
                    done++;
                    context.Progress?.Report($"CT-14 [{done}/{total}] 完成：ACC参考误差{analyzed.Visit.VectorReferenceErrorMg:F3}mg，Gyro零速模{Ct14Algorithm.Norm(analyzed.Visit.GyroCorrectedMeanDps):F6}°/s。");
                }
            }
            context.Progress?.Report($"CT-14 装夹{s.MountIndex}完成，转台返回装夹基准姿态内轴0°/外轴0°。");
            await MoveToAsync(hw, 0, 0, s, ct);
            state = "MOUNT_CYCLE_COMPLETED";
            reason = $"第{s.MountIndex}/{s.PlannedMounts}次装夹完成，真实采集{visits.Count}段；等待后续装夹周期汇总。";
        }
        catch (OperationCanceledException)
        {
            state = "CANCELLED_PARTIAL"; reason = "本轮装夹测试被取消，保留已完成采集。"; throw;
        }
        catch (Exception ex)
        {
            state = "FAILED_PARTIAL"; reason = ex.Message; throw;
        }
        finally
        {
            if (motionRequested)
            {
                try { await hw.StopTwoTdBothAsync(CancellationToken.None); }
                catch (Exception ex)
                {
                    stopProblem = ex.Message;
                    state = "STOP_NOT_CONFIRMED";
                    reason += "；双轴软停车未确认：" + stopProblem;
                    context.Progress?.Report("警告：双轴软停车未确认，请现场检查，必要时使用实体急停。");
                }
            }
            try { reportFiles = await Ct14Report.ExportMountAsync(folder, MakeReport(), CancellationToken.None); }
            catch (Exception ex)
            {
                reportProblem = ex.Message;
                context.Progress?.Report("CT-14本轮报告生成失败：" + ex.Message);
            }
        }
        if (stopProblem.Length > 0) throw new IOException("CT-14结束时双轴软停车未确认；现场检查并必要时使用实体急停：" + stopProblem);
        if (reportProblem.Length > 0) throw new IOException("CT-14本轮采集结束，但报告生成失败：" + reportProblem);
        return new TestExecutionResult(TestId, TestOutcome.PendingAcceptance,
            $"CT-14第{s.MountIndex}/{s.PlannedMounts}次装夹完成，采集{visits.Count}段；尚需完成其他装夹周期并生成跨装夹汇总。",
            null, reportFiles);
    }

    private static int ReadGravitySignAndAxisModel(string file)
    {
        using var doc = JsonDocument.Parse(File.ReadAllText(file));
        var root = doc.RootElement;
        if (!root.TryGetProperty("axis_model", out var model) || model.GetString() != "outer_x_inner_z")
            throw new InvalidDataException("当前CT-14仅支持常温ACC JSON声明的Python outer_x_inner_z参考模型。");
        if (!root.TryGetProperty("gravity_sign", out var sign) || !sign.TryGetInt32(out int n) || n is not (1 or -1))
            throw new InvalidDataException("常温ACC JSON缺少有效gravity_sign=±1。");
        return n;
    }

    private static void ValidateCalibrationHashes(CalibrationRun run)
    {
        foreach (var f in run.Sources)
            if (!File.Exists(f.FilePath) ||
                !Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(f.FilePath)))
                    .Equals(f.Sha256, StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("标定JSON发生变化，停止测试：" + f.FilePath);
    }

    private static void EnsureSameDevice(IStaticAngleHardware hw, DeviceIdentity expected)
    {
        var current = hw.CurrentIdentity ?? throw new InvalidDataException("IMU连接丢失或UID不可读。");
        if (!current.UidHex.Equals(expected.UidHex, StringComparison.OrdinalIgnoreCase) ||
            !current.DtsId.Equals(expected.DtsId, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("测试期间IMU设备身份发生变化。");
    }

    private static void VerifyAxisState(RealTableFeedback b, bool inPlace)
    {
        if (DateTimeOffset.UtcNow - b.CapturedUtc > TimeSpan.FromSeconds(3))
            throw new IOException("2TD反馈超过3秒未更新。");
        static void Check(RealAxisFeedback a, string name, bool arrived)
        {
            if (!a.Normal || a.Enabled != true || !double.IsFinite(a.PositionDeg) ||
                !double.IsFinite(a.SpeedDps) || Math.Abs(a.SpeedDps) > 0.05 ||
                (arrived && a.InPlace != true))
                throw new IOException(name + "未处于正常使能且静止/到位状态：" + a.Detail);
        }
        Check(b.Inner, "内轴", inPlace); Check(b.Outer, "外轴", inPlace);
    }

    private static bool Within(double value, Ct14Settings s)
    {
        if (!double.IsFinite(value)) return false;
        double x = (value % 360 + 360) % 360;
        if (s.AllowedMinDeg <= 0 && x >= 360 - s.PositionToleranceDeg) x = 0;
        return x >= s.AllowedMinDeg - s.PositionToleranceDeg &&
            x <= s.AllowedMaxDeg + s.PositionToleranceDeg;
    }

    private static void EnsureWithin(double value, Ct14Settings s)
    {
        if (!Within(value, s))
            throw new IOException($"2TD当前位置{value:F3}°超出声明允许行程[{s.AllowedMinDeg:F1},{s.AllowedMaxDeg:F1}]°。");
    }

    private static void VerifyPose(RealTableFeedback b, Ct14Pose pose, Ct14Settings s)
    {
        VerifyAxisState(b, true);
        if (Ct14Algorithm.Distance(b.Inner.PositionDeg, pose.InnerDeg) > s.PositionToleranceDeg ||
            Ct14Algorithm.Distance(b.Outer.PositionDeg, pose.OuterDeg) > s.PositionToleranceDeg)
            throw new IOException("2TD实际反馈与CT-14目标姿态不一致。");
    }

    private static async Task MoveToAsync(IStaticAngleHardware hw, double inner, double outer,
        Ct14Settings s, CancellationToken ct)
    {
        var b = await hw.ReadTwoTdAsync(ct);
        VerifyAxisState(b, false);
        EnsureWithin(b.Inner.PositionDeg, s); EnsureWithin(b.Outer.PositionDeg, s);
        if (Ct14Algorithm.Distance(b.Inner.PositionDeg, inner) > s.PositionToleranceDeg)
        {
            await MoveAxisAsync(hw, 2, 0, s, ct);
            await MoveAxisAsync(hw, 0, inner, s, ct);
        }
        await MoveAxisAsync(hw, 2, outer, s, ct);
        VerifyPose(await hw.ReadTwoTdAsync(ct), new Ct14Pose(0, inner, outer), s);
    }

    private static async Task MoveAxisAsync(IStaticAngleHardware hw, int axis, double target,
        Ct14Settings s, CancellationToken ct)
    {
        if (target < s.AllowedMinDeg || target > s.AllowedMaxDeg)
            throw new InvalidOperationException("运动目标超出声明的允许行程。");
        var before = await hw.ReadTwoTdAsync(ct);
        VerifyAxisState(before, false);
        var current = axis == 0 ? before.Inner : before.Outer;
        EnsureWithin(current.PositionDeg, s);
        if (Ct14Algorithm.Distance(current.PositionDeg, target) <= s.PositionToleranceDeg &&
            current.InPlace == true) return;
        await hw.SetTwoTdAbsoluteAsync(axis, target, s.MotionSpeedDps, ct);
        double distance = Ct14Algorithm.Distance(current.PositionDeg, target);
        double timeout = Math.Min(600, Math.Max(40, distance / s.MotionSpeedDps * 2.5 + 30));
        var watch = System.Diagnostics.Stopwatch.StartNew();
        int confirmed = 0;
        while (watch.Elapsed.TotalSeconds < timeout)
        {
            ct.ThrowIfCancellationRequested();
            await Task.Delay(200, ct);
            var b = await hw.ReadTwoTdAsync(ct);
            if (DateTimeOffset.UtcNow - b.CapturedUtc > TimeSpan.FromSeconds(3))
                throw new IOException("2TD运动期间反馈中断。");
            var active = axis == 0 ? b.Inner : b.Outer;
            var partner = axis == 0 ? b.Outer : b.Inner;
            if (!active.Normal || active.Enabled != true || !double.IsFinite(active.SpeedDps) ||
                !partner.Normal || partner.Enabled != true || !double.IsFinite(partner.SpeedDps) ||
                Math.Abs(partner.SpeedDps) > 0.05)
                throw new IOException("转台运动轴异常或另一轴仍在运动：" + active.Detail);
            EnsureWithin(partner.PositionDeg, s);
            EnsureWithin(active.PositionDeg, s);
            bool arrived = Ct14Algorithm.Distance(active.PositionDeg, target) <= s.PositionToleranceDeg &&
                Math.Abs(active.SpeedDps) <= 0.05 && active.InPlace == true;
            confirmed = arrived ? confirmed + 1 : 0;
            if (confirmed >= 3) return;
        }
        throw new TimeoutException($"2TD轴{axis}到位超时，目标{target:F2}°。");
    }

    private static void VerifyPhysicalCsvScale(string file, int accFs, int gyroFs)
    {
        using var reader = new StreamReader(file);
        var columns = (reader.ReadLine()?.TrimStart('\uFEFF') ?? "").Split(',');
        foreach (string col in new[] { "ax_g", "gx_dps", "raw_ax", "raw_gx", "acc_input_fs_g", "gyro_input_fs_dps" })
            if (!columns.Contains(col, StringComparer.Ordinal))
                throw new InvalidDataException("真实采集CSV缺少字段：" + col);
        int I(string name) => Array.IndexOf(columns, name);
        if (!Asm330Codec.TryAccMg(accFs, out double mg) || !Asm330Codec.TryGyroMdps(gyroFs, out double mdps))
            throw new InvalidDataException("标定JSON输入量程不受支持。");
        int rows = 0; string? line; var ci = CultureInfo.InvariantCulture;
        while ((line = reader.ReadLine()) is not null)
        {
            if (string.IsNullOrWhiteSpace(line)) continue;
            var v = line.Split(',');
            if (v.Length < columns.Length ||
                !int.TryParse(v[I("acc_input_fs_g")], out int a) ||
                !int.TryParse(v[I("gyro_input_fs_dps")], out int g) || a != accFs || g != gyroFs)
                throw new InvalidDataException("真实CSV物理量输入量程与当前标定JSON不一致。");
            double ax = double.Parse(v[I("ax_g")], ci), rax = double.Parse(v[I("raw_ax")], ci);
            double gx = double.Parse(v[I("gx_dps")], ci), rgx = double.Parse(v[I("raw_gx")], ci);
            if (Math.Abs(ax - rax * mg / 1000d) > 1e-9 ||
                Math.Abs(gx - rgx * mdps / 1000d) > 1e-9)
                throw new InvalidDataException("真实原始计数与CSV物理量换算不匹配。");
            rows++;
        }
        if (rows == 0) throw new InvalidDataException("采集CSV没有有效数据行。");
    }
}
