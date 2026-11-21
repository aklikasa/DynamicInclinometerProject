// CT09_MODULE_V1.1 - checked against DTS TestPlatform NET10 WPF V0.6.8.
using System.Globalization;
using System.Security.Cryptography;
using System.Text.Json;
using Dts.Core;
using Dts.TestEngine;
using Dts.Tests.S1.CT09;

namespace Dts.Tests.S1;

/// <summary>CT-09: posture-dependent Gyro zero-rate residual, using real IMU FIFO and real 2TD feedback.</summary>
public sealed class CT_09_Test : TestModuleBase
{
    public override string TestId => "CT-09";
    public override string Name => "GYRO零速残差与姿态相关性";
    public override bool IsExecutable => true;
    public override bool RequiresStaticBench => true;
    public override string Purpose => "量化常温Gyro标定补偿后的零速残差，并比较不同静态转台姿态下的零偏变化。";
    public override string Procedure => "按姿态计划自动定位→到位/静止反馈确认→静置→真实FIFO采集→Gyro矩阵补偿→稳健统计→跨姿态比较。";
    public override string Priority => "P0";
    public override string ImplementationNote => "真实2TD+IMU诊断模块；使用当前设备UID匹配的常温Gyro矩阵；不重新拟合、不自动判产品PASS。";

    public override async Task<TestExecutionResult> ExecuteAsync(TestExecutionContext context, CancellationToken ct)
    {
        if (context.Hardware is not IStaticAngleHardware hw)
            throw new InvalidOperationException("CT-09需要真实2TD反馈及静态FIFO采集接口。");
        if (context.Parameters is not Ct09Settings s)
            throw new InvalidOperationException("CT-09缺少专用参数快照。");
        if (!hw.IsTwoTdConnected)
            throw new InvalidOperationException("2TD双轴转台未连接。");

        var id = hw.CurrentIdentity ?? throw new InvalidOperationException("IMU未连接或未读取完整UID。");
        if (s.Calibration.Mode != CalibrationMode.Ambient)
            throw new InvalidOperationException("CT-09要求在主界面选择当前PCB的常温标定模式。");
        s.Calibration.Validate(id);
        var gyro = s.Calibration.Files?.Gyro ?? throw new InvalidDataException("缺少UID匹配的Gyro常温JSON。");
        var acc = s.Calibration.Files?.Acc ?? throw new InvalidDataException("缺少UID匹配的ACC常温JSON；平台要求常温标定组合完整。");
        if (gyro.FsHint is null || acc.FsHint is null)
            throw new InvalidDataException("常温标定JSON缺少拟合输入量程FsHint，拒绝猜测量程。");
        var scale = CalibrationInputScalePolicy.Resolve(acc.FsHint, gyro.FsHint, 0, 0)
            ?? throw new InvalidDataException("标定JSON输入量程不受支持。");

        Ct09Algorithm.Validate(s);
        ValidateCalibrationHashes(s.Calibration);
        await hw.VerifyImuForPrecisionTestAsync(ct);

        var initial = await hw.ReadTwoTdAsync(ct);
        VerifyAxisState(initial, requireInPlace: false);
        EnsureWithinRange(initial.Inner.PositionDeg, s);
        EnsureWithinRange(initial.Outer.PositionDeg, s);
        if (!Directory.Exists(s.OutputRoot))
            throw new DirectoryNotFoundException("CT-09报告根目录不存在：" + s.OutputRoot);
        string folder = Path.Combine(Path.GetFullPath(s.OutputRoot),
            $"{id.DtsId}_{id.UidHex}", $"{DateTime.Now:yyyyMMdd_HHmmss_fff}_CT-09");
        Directory.CreateDirectory(folder);

        var visits = new List<Ct09Visit>();
        var started = DateTimeOffset.UtcNow;
        string state = "RUNNING", reason = "";
        bool motionRequested = false;
        string? reportError = null;
        string? stopFailure = null;
        IReadOnlyList<string> reportFiles = Array.Empty<string>();

        var settingsSnapshot = new Ct09SettingsSnapshot(s.Poses, s.RepeatsPerPose,
            s.MotionSpeedDps, s.SettleSeconds, s.SampleSeconds, s.PositionToleranceDeg,
            s.AllowedMinDeg, s.AllowedMaxDeg, s.MinValidSamples, s.MaxOutlierFraction);
        var reportSeed = new Ct09ReportData("CT-09", "GYRO零速残差与姿态相关性",
            id.DtsId, id.UidHex, started, DateTimeOffset.UtcNow, state, reason,
            Path.GetFileName(gyro.FilePath), gyro.Sha256, gyro.FsHint.Value,
            scale.Display, settingsSnapshot, visits, null,
            "Gyro零速残差是应用常温Gyro偏置与矩阵后的静态输出；姿态间差异反映本次测试姿态范围内的残余姿态相关性。" +
            "结果还受温度、转台稳定性、安装、采样噪声和标定输入量程影响；本模块不自动判产品PASS。");

        Ct09ReportData Snapshot() => reportSeed with
        {
            FinishedUtc = DateTimeOffset.UtcNow,
            State = state,
            FailureReason = reason,
            Visits = visits.ToArray(),
            Metrics = Ct09Algorithm.Summarize(visits)
        };

        try
        {
            await File.WriteAllTextAsync(Path.Combine(folder, "CT-09_calibration_identity.json"),
                JsonSerializer.Serialize(new
                {
                    device = id.DtsId, uid = id.UidHex,
                    gyro_json = gyro.FilePath, gyro_sha256 = gyro.Sha256,
                    gyro_run_id = gyro.RunId, gyro_fs_hint = gyro.FsHint,
                    acc_json = acc.FilePath, acc_sha256 = acc.Sha256,
                    input_scale = scale.Display,
                    calibration_identity = s.Calibration.IdentityProof,
                    note = "只读当前UID匹配的常温标定矩阵；逐轮复核SHA256；不重新拟合、不额外除以8。"
                }, new JsonSerializerOptions { WriteIndented = true }), ct);

            int total = s.Poses.Count * s.RepeatsPerPose;
            int done = 0;
            for (int p = 0; p < s.Poses.Count; p++)
            {
                ct.ThrowIfCancellationRequested();
                EnsureSameDevice(hw, id);
                ValidateCalibrationHashes(s.Calibration);
                var pose = s.Poses[p];
                context.Progress?.Report($"CT-09 [{p + 1}/{s.Poses.Count}] 定位姿态：内轴{pose.InnerDeg:F1}° / 外轴{pose.OuterDeg:F1}°");
                motionRequested = true;
                await MoveToPoseAsync(hw, pose, s, context.Progress, ct);
                await Task.Delay(TimeSpan.FromSeconds(s.SettleSeconds), ct);

                for (int rep = 1; rep <= s.RepeatsPerPose; rep++)
                {
                    ct.ThrowIfCancellationRequested();
                    EnsureSameDevice(hw, id);
                    ValidateCalibrationHashes(s.Calibration);
                    var before = await hw.ReadTwoTdAsync(ct);
                    VerifyPose(before, pose, s);
                    string stem = $"pose_{pose.Index:D2}_inner_{pose.InnerDeg:000p0}_outer_{pose.OuterDeg:000p0}_rep_{rep:D2}";
                    string physical = Path.Combine(folder, stem + "_physical.csv");
                    string corrected = Path.Combine(folder, stem + "_corrected.csv");
                    context.Progress?.Report($"CT-09 [{done + 1}/{total}] 姿态{pose.Index} / 重复{rep}：真实静态采集{s.SampleSeconds:F1}s");

                    var capture = await hw.CaptureStaticPointAsync(physical,
                        TimeSpan.FromSeconds(s.SampleSeconds), context.Progress, ct);
                    var after = await hw.ReadTwoTdAsync(ct);
                    VerifyPose(after, pose, s);
                    if (Ct09Algorithm.Distance(before.Inner.PositionDeg, after.Inner.PositionDeg) > s.PositionToleranceDeg ||
                        Ct09Algorithm.Distance(before.Outer.PositionDeg, after.Outer.PositionDeg) > s.PositionToleranceDeg)
                        throw new InvalidDataException("采样期间转台实际姿态发生变化，拒绝该轮数据。");

                    ValidateCalibrationHashes(s.Calibration);
                    VerifyGyroCsvScale(physical, scale.GyroFullScaleDps);
                    var analyzed = Ct09Algorithm.Analyze(pose, rep, before, after, capture,
                        gyro.Apply, s, physical, corrected);
                    await Ct09Algorithm.SaveCorrectedCsvAsync(corrected, capture, analyzed.Accepted,
                        analyzed.CorrectedGyro, ct);
                    visits.Add(analyzed.Visit with { Index = visits.Count + 1 });
                    done++;

                    var checkpoint = Snapshot();
                    await Ct09Report.SaveCheckpointAsync(folder, checkpoint, ct);
                    context.Progress?.Report($"CT-09 [{done}/{total}] 完成：Gyro零速模={analyzed.Visit.ZeroRateNormDps:F6}°/s，温度={analyzed.Visit.MeanTemperatureC:F2}°C");
                }
            }

            state = "COMPLETED_PENDING_ACCEPTANCE";
            reason = $"完成{visits.Count}/{total}个姿态-重复采集单元；已计算静态零速残差和姿态间差异，研发待验收。";
        }
        catch (OperationCanceledException)
        {
            state = "CANCELLED_PARTIAL";
            reason = "用户取消；保留已完成姿态及原始数据。";
            throw;
        }
        catch (Exception ex)
        {
            state = "FAILED_PARTIAL";
            reason = ex.Message;
            throw;
        }
        finally
        {
            if (motionRequested)
            {
                try { await hw.StopTwoTdBothAsync(CancellationToken.None); }
                catch (Exception ex)
                {
                    state = "STOP_NOT_CONFIRMED";
                    stopFailure = ex.Message;
                    reason += "；双轴软停车未确认：" + ex.Message;
                }
            }
            try { reportFiles = await Ct09Report.ExportAsync(folder, Snapshot(), CancellationToken.None); }
            catch (Exception ex) { reportError = ex.Message; }
            if (stopFailure is not null)
                throw new IOException("CT-09结束时双轴软停车未确认；请现场检查并在必要时使用实体急停。", new InvalidOperationException(stopFailure));
        }

        if (state == "STOP_NOT_CONFIRMED")
            throw new IOException("CT-09结束时双轴软停车未确认；请现场检查并在必要时使用实体急停。");
        if (reportError is not null)
            throw new IOException("CT-09采集已结束，但报告导出失败：" + reportError);
        var metrics = Ct09Algorithm.Summarize(visits);
        return new TestExecutionResult(TestId, TestOutcome.PendingAcceptance,
            $"CT-09完成{visits.Count}个姿态-重复采集单元；最大姿态间零速均值差异={metrics?.MaxPoseMeanVectorDifferenceDps:F6}°/s；研发待验收。",
            null, reportFiles);
    }

    private static void EnsureSameDevice(IStaticAngleHardware hw, DeviceIdentity expected)
    {
        var current = hw.CurrentIdentity ?? throw new InvalidDataException("IMU连接丢失。");
        if (!string.Equals(current.UidHex, expected.UidHex, StringComparison.OrdinalIgnoreCase) ||
            !string.Equals(current.DtsId, expected.DtsId, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("测试期间IMU设备身份变化，停止测试。");
    }

    private static void ValidateCalibrationHashes(CalibrationRun run)
    {
        foreach (var f in run.Sources)
            if (!File.Exists(f.FilePath) ||
                !Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(f.FilePath)))
                    .Equals(f.Sha256, StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("标定JSON发生变化：" + f.FilePath);
    }

    private static void VerifyGyroCsvScale(string file, int gyroFs)
    {
        using var reader = new StreamReader(file);
        var columns = (reader.ReadLine()?.TrimStart('\uFEFF') ?? "").Split(',');
        var required = new[]
        {
            "gx_dps", "gy_dps", "gz_dps",
            "raw_gx", "raw_gy", "raw_gz", "gyro_input_fs_dps"
        };
        foreach (string name in required)
            if (!columns.Contains(name, StringComparer.Ordinal))
                throw new InvalidDataException("真实采集CSV缺少字段：" + name);
        int idx(string name) => Array.IndexOf(columns, name);
        if (!Asm330Codec.TryGyroMdps(gyroFs, out double mdps))
            throw new InvalidDataException("Gyro标定输入量程不受支持。");
        int rows = 0;
        string? line;
        while ((line = reader.ReadLine()) is not null)
        {
            if (string.IsNullOrWhiteSpace(line)) continue;
            var cells = line.Split(',');
            if (cells.Length < columns.Length ||
                !int.TryParse(cells[idx("gyro_input_fs_dps")], NumberStyles.Integer,
                    CultureInfo.InvariantCulture, out int fs) || fs != gyroFs)
                throw new InvalidDataException("真实采集CSV的Gyro量程与标定JSON不一致。");

            foreach (var axis in new[] { ("gx_dps", "raw_gx"), ("gy_dps", "raw_gy"), ("gz_dps", "raw_gz") })
            {
                if (!double.TryParse(cells[idx(axis.Item1)], NumberStyles.Float,
                        CultureInfo.InvariantCulture, out double physical) ||
                    !double.TryParse(cells[idx(axis.Item2)], NumberStyles.Float,
                        CultureInfo.InvariantCulture, out double raw) ||
                    !double.IsFinite(physical) || !double.IsFinite(raw) ||
                    Math.Abs(physical - raw * mdps / 1000d) > 1e-9)
                    throw new InvalidDataException($"Gyro {axis.Item1}物理量与原始计数换算不匹配。");
            }
            rows++;
        }
        if (rows == 0) throw new InvalidDataException("采集CSV无有效数据行。");
    }

    private static void VerifyAxisState(RealTableFeedback b, bool requireInPlace)
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
        Check(b.Inner, "内轴", requireInPlace);
        Check(b.Outer, "外轴", requireInPlace);
    }

    private static void EnsureWithinRange(double position, Ct09Settings s)
    {
        if (!double.IsFinite(position) || position < s.AllowedMinDeg - s.PositionToleranceDeg ||
            position > s.AllowedMaxDeg + s.PositionToleranceDeg)
            throw new IOException($"转台当前位置{position:F3}°超出声明的允许行程[{s.AllowedMinDeg:F1},{s.AllowedMaxDeg:F1}]°。");
    }

    private static void VerifyPose(RealTableFeedback b, Ct09Pose pose, Ct09Settings s)
    {
        VerifyAxisState(b, true);
        if (Ct09Algorithm.Distance(b.Inner.PositionDeg, pose.InnerDeg) > s.PositionToleranceDeg ||
            Ct09Algorithm.Distance(b.Outer.PositionDeg, pose.OuterDeg) > s.PositionToleranceDeg)
            throw new IOException("转台实际反馈与CT-09目标姿态不一致。");
    }

    private static async Task MoveToPoseAsync(IStaticAngleHardware hw, Ct09Pose pose,
        Ct09Settings s, IProgress<string>? progress, CancellationToken ct)
    {
        var initial = await hw.ReadTwoTdAsync(ct);
        VerifyAxisState(initial, false);
        if (pose.InnerDeg < s.AllowedMinDeg || pose.InnerDeg > s.AllowedMaxDeg ||
            pose.OuterDeg < s.AllowedMinDeg || pose.OuterDeg > s.AllowedMaxDeg)
            throw new InvalidOperationException("姿态目标超出声明的允许行程。");

        // Keep the same safe sequence as CT-07: park outer axis at 0° before moving inner.
        await MoveAxisAsync(hw, 2, 0, s, ct);
        await MoveAxisAsync(hw, 0, pose.InnerDeg, s, ct);
        await MoveAxisAsync(hw, 2, pose.OuterDeg, s, ct);
        var arrived = await hw.ReadTwoTdAsync(ct);
        VerifyPose(arrived, pose, s);
        progress?.Report($"CT-09姿态到位：内轴{arrived.Inner.PositionDeg:F3}° / 外轴{arrived.Outer.PositionDeg:F3}°");
    }

    private static async Task MoveAxisAsync(IStaticAngleHardware hw, int axis, double target,
        Ct09Settings s, CancellationToken ct)
    {
        if (target < s.AllowedMinDeg || target > s.AllowedMaxDeg)
            throw new InvalidOperationException("目标角超出允许行程。");
        var before = await hw.ReadTwoTdAsync(ct);
        VerifyAxisState(before, false);
        var current = axis == 0 ? before.Inner : before.Outer;
        if (Ct09Algorithm.Distance(current.PositionDeg, target) <= s.PositionToleranceDeg &&
            current.InPlace == true) return;

        await hw.SetTwoTdAbsoluteAsync(axis, target, s.MotionSpeedDps, ct);
        double distance = Ct09Algorithm.Distance(current.PositionDeg, target);
        double timeout = Math.Min(600, Math.Max(40, distance / s.MotionSpeedDps * 2.5 + 30));
        var watch = System.Diagnostics.Stopwatch.StartNew();
        int confirmed = 0;
        while (watch.Elapsed.TotalSeconds < timeout)
        {
            ct.ThrowIfCancellationRequested();
            await Task.Delay(200, ct);
            var feedback = await hw.ReadTwoTdAsync(ct);
            if (DateTimeOffset.UtcNow - feedback.CapturedUtc > TimeSpan.FromSeconds(3))
                throw new IOException("转台运动期间反馈中断。");
            var active = axis == 0 ? feedback.Inner : feedback.Outer;
            var partner = axis == 0 ? feedback.Outer : feedback.Inner;
            if (!active.Normal || active.Enabled != true || !partner.Normal ||
                partner.Enabled != true || Math.Abs(partner.SpeedDps) > 0.05)
                throw new IOException("转台运动轴异常或另一轴仍在运动：" + active.Detail);
            EnsureWithinRange(partner.PositionDeg, s);
            if (active.PositionDeg < s.AllowedMinDeg - s.PositionToleranceDeg ||
                active.PositionDeg > s.AllowedMaxDeg + s.PositionToleranceDeg)
                throw new IOException("转台位置超出声明的机械允许范围。");
            bool arrived = Ct09Algorithm.Distance(active.PositionDeg, target) <= s.PositionToleranceDeg &&
                Math.Abs(active.SpeedDps) <= 0.05 && active.InPlace == true;
            confirmed = arrived ? confirmed + 1 : 0;
            if (confirmed >= 3) return;
        }
        throw new TimeoutException($"转台轴{axis}到位超时，目标{target:F2}°。");
    }
}
