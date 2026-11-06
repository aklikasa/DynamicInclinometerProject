using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Dts.Core;
using Dts.TestEngine;
using Dts.Tests.S1.CT03;

namespace Dts.Tests.S1;

/// <summary>
/// CT-03 ACC 三轴矢量独立验证。只通过 IStaticAngleHardware 控制真实2TD和采集真实IMU；
/// 一键完成整个计划，软件无法替代物理急停或证明夹具/电缆的实际可达行程。
/// </summary>
public sealed class CT_03_Test : TestModuleBase
{
    public override string TestId => "CT-03";
    public override bool IsExecutable => true;
    public override string Purpose => "在非标定姿态比较ACC校正三轴矢量与2TD实际姿态计算的重力矢量";
    public override string Procedure => "自动定位、连续确认到位、静置、逐帧采样、MAD剔除、计算方向/大小误差并输出逐点报告";
    public override string Priority => "P0";
    public override string ImplementationNote => "独立真实自动扫描模块；12点/24点预设或自定义双轴等分网格，HTML内置趋势图/CSV/JSON/XLSX；所有结论待验收，不伪造PASS。";

    public override async Task<TestExecutionResult> ExecuteAsync(TestExecutionContext context, CancellationToken ct)
    {
        if (context.Hardware is not IStaticAngleHardware hw)
            throw new InvalidOperationException("CT-03 需要支持真实2TD反馈和逐点FIFO采集的设备接口");
        if (context.Parameters is not Ct03Settings p)
            throw new InvalidOperationException("没有收到CT-03专用窗口的参数快照");
        if (!hw.IsTwoTdConnected)
            throw new InvalidOperationException("请先连接并使能真实2TD双轴转台");
        var id = hw.CurrentIdentity ?? throw new InvalidOperationException("真实IMU未连接或完整UID未获取");
        var run = p.Calibration;
        if (run.Mode != CalibrationMode.Ambient)
            throw new InvalidOperationException("CT-03当前只验证常温ACC校正，主窗口必须先选择常温标定");
        run.Validate(id);
        var acc = run.Files?.Acc ?? throw new InvalidDataException("缺少当前UID的ACC常温校准参数");
        var gyro = run.Files?.Gyro ?? throw new InvalidDataException("逐点硬件采集需要当前UID配套的Gyro常温校准参数");
        // Do not hardcode a hardware range inside CT-03: the fitted scale stored
        // in the UID-matched calibration JSON is the authoritative mathematical input.
        // With the user's existing JSON this resolves to ACC 2g and Gyro 2000dps.
        if (acc.FsHint is null || gyro.FsHint is null)
            throw new InvalidDataException("CT-03需要ACC/Gyro JSON明确记录标定拟合时的输入量程");
        var scale = CalibrationInputScalePolicy.Resolve(acc.FsHint, gyro.FsHint, 0, 0)
            ?? throw new InvalidDataException("当前JSON拟合输入量程不在ASM330灵敏度表中");
        int gravitySign = ReadGravitySignAndAxisModel(acc.FilePath);
        var plan = Ct03Algorithm.BuildPlan(p);
        int distinctGravityDirections = Ct03Algorithm.CountDistinctGravityDirections(plan, gravitySign);
        int? historicalOverlaps = Ct03Algorithm.CountHistoricalGravityOverlaps(plan, acc.FilePath, gravitySign);
        Ct03Algorithm.ValidatePlan(p, plan);
        ValidateCalibrationHashes(run);
        await hw.VerifyImuForPrecisionTestAsync(ct);
        var initial = await hw.ReadTwoTdAsync(ct);
        VerifyAxisState(initial, requireInPlace: false);
        // Do not issue any initial motion when outside explicitly approved range.
        if (!WithinApproved(initial.Inner.PositionDeg, p) || !WithinApproved(initial.Outer.PositionDeg, p))
            throw new InvalidOperationException("当前双轴位置不在声明的可运动区间内。请先在现场安全条件下检查初始位置和绝对运动方向，不能自动跨越未批准区域");
        string root = Path.GetFullPath(p.OutputRoot);
        if (!Directory.Exists(root)) throw new DirectoryNotFoundException("报告根目录不存在：" + root);
        string folder = Path.Combine(root, $"{id.DtsId}_{id.UidHex}",
            $"{DateTime.Now:yyyyMMdd_HHmmss_fff}_CT-03");
        Directory.CreateDirectory(folder);
        string started = DateTimeOffset.UtcNow.ToString("O");
        var points = new List<Ct03PointResult>();
        string state = "RUNNING", reason = "";
        string stopProblem = "", reportProblem = "";
        string[] reportFiles = [];
        bool motionMayHaveStarted = false;
        var frozenUid = id.UidHex;

        Ct03ReportData Snapshot() => new("CT-03", "ACC 三轴矢量独立验证", "S1", id.DtsId,
            frozenUid, started, DateTimeOffset.UtcNow.ToString("O"), state, reason,
            "实测统计/待验收：不自动宣称产品PASS；设备安装、转台量值溯源与系统不确定度仍须评估",
            "Python outer_x_inner_z; R=Rx(outer)Rz(inner); gravity_P=R^T[0,0,sign]g; 实际角反馈为参考",
            gravitySign, Path.GetFileName(acc.FilePath), acc.Sha256,
            Path.GetFileName(gyro.FilePath), gyro.Sha256,
            "使用匹配JSON的拟合输入比例：" + scale.Display + "；ACC仅补偿一次",
            new Ct03SettingsSnapshot(p.PlanKind, p.SpeedDps, p.SettleSeconds, p.SampleSeconds,
                p.PositionToleranceDeg, p.AllowedMinDeg, p.AllowedMaxDeg, p.MinValidSamples,
                p.MaxOutlierFraction, p.FullRangeApproved, p.DirectionAndCablingApproved,
                p.InnerDivisions, p.OuterDivisions, p.InnerStartDeg, p.OuterStartDeg),
            points.ToArray(), points.Count == 0 ? null : Ct03Algorithm.Summarize(points),
            "测试开始前已由现场人员确认急停/行程/方向和电缆；软件仅执行软停车，物理急停需现场可用；测试过程中不要使用主界面手动转台控制",
            distinctGravityDirections, historicalOverlaps);

        try
        {
            await File.WriteAllTextAsync(Path.Combine(folder, "calibration_identity.json"),
                JsonSerializer.Serialize(new { id.DtsId, id.UidHex, gravity_sign = gravitySign,
                    axis_model = "outer_x_inner_z",
                    acc = new { source = acc.FilePath, acc.Sha256, acc.RunId, acc.FsHint },
                    gyro = new { source = gyro.FilePath, gyro.Sha256, gyro.RunId, gyro.FsHint },
                    note = "两份JSON的SHA-256与UID在运行前和每点前检查，未修改任何旧标定参数" },
                    new JsonSerializerOptions { WriteIndented = true }), ct);
            motionMayHaveStarted = true; // For any failure after this point, attempt soft-stop.
            for (int i = 0; i < plan.Count; i++)
            {
                ct.ThrowIfCancellationRequested();
                if (hw.CurrentIdentity?.UidHex != frozenUid)
                    throw new InvalidDataException("采样中IMU UID发生变化，终止测试");
                ValidateCalibrationHashes(run);
                var pose = plan[i];
                context.Progress?.Report($"CT-03 [{i + 1}/{plan.Count}] 运动中：内轴{pose.InnerTargetDeg:0.#}° / 外轴{pose.OuterTargetDeg:0.#}°");
                await PositionForPoseAsync(hw, pose, p, ct);
                context.Progress?.Report($"CT-03 [{i + 1}/{plan.Count}] 到位，静置 {p.SettleSeconds:0.#}s");
                await Task.Delay(TimeSpan.FromSeconds(p.SettleSeconds), ct);
                var before = await hw.ReadTwoTdAsync(ct);
                VerifyPose(before, pose, p);
                string rawCsv = Path.Combine(folder, $"pose_{pose.Index:D3}_{pose.Label}_physical.csv");
                string correctedCsv = Path.Combine(folder, $"pose_{pose.Index:D3}_{pose.Label}_corrected.csv");
                context.Progress?.Report($"CT-03 [{i + 1}/{plan.Count}] 正在真实FIFO采集 {p.SampleSeconds:0.#}s");
                var capture = await hw.CaptureStaticPointAsync(rawCsv,
                    TimeSpan.FromSeconds(p.SampleSeconds), context.Progress, ct);
                var after = await hw.ReadTwoTdAsync(ct);
                VerifyPose(after, pose, p);
                if (Ct03Algorithm.Distance(before.Inner.PositionDeg, after.Inner.PositionDeg) > p.PositionToleranceDeg ||
                    Ct03Algorithm.Distance(before.Outer.PositionDeg, after.Outer.PositionDeg) > p.PositionToleranceDeg)
                    throw new InvalidDataException("采集期间转台实际反馈出现超容差变化；本姿态不能用于独立验证");
                ValidateCalibrationHashes(run);
                VerifyPhysicalCsvScale(rawCsv, scale.AccFullScaleG, scale.GyroFullScaleDps);
                var analyzed = Ct03Algorithm.Analyze(pose, before, after, capture,
                    xyz => acc.Apply(xyz[0], xyz[1], xyz[2]), p,
                    gravitySign, rawCsv, correctedCsv);
                await SaveCorrectedFramesAsync(correctedCsv, capture, analyzed.Accepted,
                    analyzed.Corrected, analyzed.Point.ReferenceG, ct);
                points.Add(analyzed.Point);
                context.Progress?.Report($"CT-03 [{i + 1}/{plan.Count}] 矢量误差 {analyzed.Point.VectorErrorG * 1000:F3}mg，" +
                    $"方向误差 {analyzed.Point.DirectionErrorDeg:F5}°，有效{analyzed.Point.AcceptedSamples}帧");
                await Ct03Report.SaveCheckpointAsync(folder, Snapshot(), ct);
            }
            state = "COMPLETED_PENDING_ACCEPTANCE";
            reason = p.PlanKind.StartsWith("局部", StringComparison.Ordinal)
                ? "局部12点完成；只覆盖有限象限，不代表全空间独立验证。"
                : $"完成{plan.Count}个机械工位，规划中仅{distinctGravityDirections}个不同重力方向；" +
                  (historicalOverlaps is > 0 ? $"其中{historicalOverlaps}个工位与既有ACC标定姿态的重力方向重合；" : "") +
                  "仍待参考量值溯源与验收标准审核。";
        }
        catch (OperationCanceledException)
        {
            state = "CANCELLED_PARTIAL"; reason = "操作员取消；部分真实数据已保留。";
            throw;
        }
        catch (Exception ex)
        {
            state = "FAILED_PARTIAL"; reason = ex.Message;
            throw;
        }
        finally
        {
            if (motionMayHaveStarted)
            {
                try { await hw.StopTwoTdBothAsync(CancellationToken.None); }
                catch (Exception ex)
                {
                    stopProblem = ex.Message;
                    state = "STOP_NOT_CONFIRMED";
                    reason += "；停车反馈未确认：" + stopProblem;
                    context.Progress?.Report("紧急提示：双轴软停车未确认！请现场立即检查，必要时使用物理急停，切勿直接断电或拔线");
                }
            }
            try { reportFiles = (await Ct03Report.ExportAsync(folder, Snapshot(), CancellationToken.None)).ToArray(); }
            catch (Exception ex)
            {
                reportProblem = ex.Message;
                context.Progress?.Report("报告写入失败：" + ex.Message + "；原始逐姿态CSV应仍在 " + folder);
            }
        }
        if (stopProblem.Length > 0) throw new IOException("软停车反馈未确认，禁止标记测试完成：" + stopProblem);
        if (reportProblem.Length > 0) throw new IOException("CT-03报告无法完整保存：" + reportProblem);
        var summary = Ct03Algorithm.Summarize(points);
        return new TestExecutionResult(TestId, TestOutcome.PendingAcceptance,
            $"CT-03 真实自动采集 {points.Count}/{plan.Count} 工位，计划覆盖{distinctGravityDirections}个不同重力方向，有效{summary.SampleCount}帧；" +
            $"三维矢量RMSE={summary.VectorRmseG * 1000:F3}mg、最大方向误差={summary.DirectionMaxDeg:F5}°；待验收。",
            null, reportFiles);
    }

    private static int ReadGravitySignAndAxisModel(string accFile)
    {
        using var doc = JsonDocument.Parse(File.ReadAllText(accFile));
        var root = doc.RootElement;
        if (!root.TryGetProperty("axis_model", out var model) || model.GetString() != "outer_x_inner_z")
            throw new InvalidDataException("CT-03只支持与Python一致的outer_x_inner_z机械坐标模型");
        if (!root.TryGetProperty("gravity_sign", out var sign) ||
            !sign.TryGetInt32(out var n) || n is not (1 or -1))
            throw new InvalidDataException("ACC标定文件缺少明确的gravity_sign=±1");
        return n;
    }

    private static void ValidateCalibrationHashes(CalibrationRun run)
    {
        foreach (var source in run.Sources)
        {
            if (!File.Exists(source.FilePath) ||
                !Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(source.FilePath)))
                    .Equals(source.Sha256, StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("标定文件在测试期间发生变化：" + source.FilePath);
        }
    }

    private static bool WithinApproved(double value, Ct03Settings s)
    {
        if (!double.IsFinite(value)) return false;
        // The 2TD encoder may report 359.999° at 0°. Only this small
        // tolerance neighborhood is equivalent; all other limits stay strict.
        double canonical = (value % 360 + 360) % 360;
        if (s.AllowedMinDeg <= 0 && canonical >= 360 - s.PositionToleranceDeg)
            canonical = 0;
        return canonical >= s.AllowedMinDeg - s.PositionToleranceDeg &&
               canonical <= s.AllowedMaxDeg + s.PositionToleranceDeg;
    }

    private static void VerifyAxisState(RealTableFeedback state, bool requireInPlace)
    {
        if (DateTimeOffset.UtcNow - state.CapturedUtc > TimeSpan.FromSeconds(3))
            throw new IOException("转台反馈超过3秒未更新");
        static void Check(RealAxisFeedback a, string label, bool inPlace)
        {
            if (!a.Normal || a.Enabled != true || !double.IsFinite(a.PositionDeg) ||
                !double.IsFinite(a.SpeedDps) || Math.Abs(a.SpeedDps) > 0.05 ||
                (inPlace && a.InPlace != true))
                throw new IOException($"{label}非正常/未使能/尚在运动/未到位：{a.Detail}");
        }
        Check(state.Inner, "内轴", requireInPlace);
        Check(state.Outer, "外轴", requireInPlace);
    }

    private static void VerifyPose(RealTableFeedback state, Ct03Pose pose, Ct03Settings p)
    {
        VerifyAxisState(state, requireInPlace: true);
        if (Ct03Algorithm.Distance(state.Inner.PositionDeg, pose.InnerTargetDeg) > p.PositionToleranceDeg ||
            Ct03Algorithm.Distance(state.Outer.PositionDeg, pose.OuterTargetDeg) > p.PositionToleranceDeg)
            throw new InvalidDataException("转台实际反馈与目标姿态不符，停止采样");
    }

    private static async Task PositionForPoseAsync(IStaticAngleHardware hw,
        Ct03Pose pose, Ct03Settings p, CancellationToken ct)
    {
        var feedback = await hw.ReadTwoTdAsync(ct);
        VerifyAxisState(feedback, requireInPlace: false);
        if (Ct03Algorithm.Distance(feedback.Inner.PositionDeg, pose.InnerTargetDeg) > p.PositionToleranceDeg)
        {
            // 复用CT-05经验证的保守路径：外轴先到0，内轴再移动，外轴最后到目标。
            await MoveAsync(hw, 2, 0, p, ct);
            await MoveAsync(hw, 0, pose.InnerTargetDeg, p, ct);
        }
        await MoveAsync(hw, 2, pose.OuterTargetDeg, p, ct);
    }

    private static async Task MoveAsync(IStaticAngleHardware hw, int axis,
        double target, Ct03Settings p, CancellationToken ct)
    {
        if (target < p.AllowedMinDeg || target > p.AllowedMaxDeg)
            throw new InvalidOperationException("运动目标超出现场批准的行程");
        var initial = await hw.ReadTwoTdAsync(ct);
        VerifyAxisState(initial, requireInPlace: false);
        var now = axis == 0 ? initial.Inner : initial.Outer;
        if (!WithinApproved(now.PositionDeg, p))
            throw new IOException("轴当前位置超出现场批准的可运动区间");
        if (Ct03Algorithm.Distance(now.PositionDeg, target) <= p.PositionToleranceDeg &&
            now.InPlace == true) return;
        await hw.SetTwoTdAbsoluteAsync(axis, target, p.SpeedDps, ct);
        // 超时依据最大可能的角行程估计，不假定实际控制器一定走最短转向。
        double timeoutSeconds = Math.Min(600, Math.Max(40,
            Math.Abs(target - now.PositionDeg) / p.SpeedDps * 2.5 + 30));
        var sw = System.Diagnostics.Stopwatch.StartNew();
        int confirmed = 0;
        while (sw.Elapsed.TotalSeconds < timeoutSeconds)
        {
            ct.ThrowIfCancellationRequested();
            await Task.Delay(200, ct);
            var feedback = await hw.ReadTwoTdAsync(ct);
            if (DateTimeOffset.UtcNow - feedback.CapturedUtc > TimeSpan.FromSeconds(3))
                throw new IOException("转台运动中反馈已过期");
            var actual = axis == 0 ? feedback.Inner : feedback.Outer;
            var partner = axis == 0 ? feedback.Outer : feedback.Inner;
            if (!actual.Normal || actual.Enabled != true || !double.IsFinite(actual.PositionDeg) ||
                !double.IsFinite(actual.SpeedDps) || !partner.Normal || partner.Enabled != true ||
                !double.IsFinite(partner.SpeedDps) || Math.Abs(partner.SpeedDps) > 0.05)
                throw new IOException("运动过程轴状态异常/另一轴非静止，禁止继续：" + actual.Detail);
            if (!WithinApproved(actual.PositionDeg, p))
                throw new IOException("运动过程中反馈位置越过已批准行程，立即终止并请求双轴停车");
            bool arrived = Ct03Algorithm.Distance(actual.PositionDeg, target) <= p.PositionToleranceDeg &&
                           Math.Abs(actual.SpeedDps) <= 0.05 && actual.InPlace == true;
            confirmed = arrived ? confirmed + 1 : 0;
            if (confirmed >= 3) return;
        }
        throw new TimeoutException($"轴{axis}到位超时：目标{target:F3}°，要求连续3次真实静止到位反馈");
    }

    private static void VerifyPhysicalCsvScale(string file, int accFs, int gyroFs)
    {
        // CaptureStaticPointAsync写入的数据格式由 Dts.Devices/LiveTestHardware 保证。
        // 与本次冻结的历史校准输入量程必须一致，否则会发生隐性跨量程计算。
        using var reader = new StreamReader(file);
        string header = reader.ReadLine()?.TrimStart('\uFEFF') ?? "";
        string[] expected = ["ax_g", "raw_ax", "acc_input_fs_g", "gyro_input_fs_dps"];
        var columns = header.Split(',');
        if (expected.Any(x => !columns.Contains(x, StringComparer.Ordinal)))
            throw new InvalidDataException("采样CSV缺少真实物理量/量程追溯字段");
        int Find(string x) => Array.IndexOf(columns, x);
        var ci = CultureInfo.InvariantCulture;
        if (!Asm330Codec.TryAccMg(accFs, out var mg) ||
            !Asm330Codec.TryGyroMdps(gyroFs, out var mdps))
            throw new InvalidDataException("历史拟合量程换算表不支持");
        int count = 0;
        string? line;
        while ((line = reader.ReadLine()) is not null)
        {
            if (string.IsNullOrWhiteSpace(line)) continue;
            var values = line.Split(',');
            if (values.Length < columns.Length ||
                !int.TryParse(values[Find("acc_input_fs_g")], out int a) ||
                !int.TryParse(values[Find("gyro_input_fs_dps")], out int g) ||
                a != accFs || g != gyroFs)
                throw new InvalidDataException("真实采集期间出现与冻结JSON不同的输入量程");
            double ax = double.Parse(values[Find("ax_g")], ci);
            double rawAx = double.Parse(values[Find("raw_ax")], ci);
            double gx = double.Parse(values[Find("gx_dps")], ci);
            double rawGx = double.Parse(values[Find("raw_gx")], ci);
            if (Math.Abs(ax - rawAx * mg / 1000d) > 1e-9 ||
                Math.Abs(gx - rawGx * mdps / 1000d) > 1e-9)
                throw new InvalidDataException("真实帧的物理值与当前历史校准输入换算不一致");
            count++;
        }
        if (count == 0) throw new InvalidDataException("没有真实帧CSV");
    }

    private static async Task SaveCorrectedFramesAsync(string file, StaticPointSamples capture,
        bool[] accepted, double[][] corrected, double[] reference, CancellationToken ct)
    {
        await using var output = new FileStream(file, FileMode.CreateNew, FileAccess.Write,
            FileShare.Read, 32768, FileOptions.Asynchronous);
        await using var writer = new StreamWriter(output, new UTF8Encoding(true));
        await writer.WriteLineAsync("row_index,accepted,acc_x_cal_g,acc_y_cal_g,acc_z_cal_g,ref_x_g,ref_y_g,ref_z_g,vector_error_g,direction_error_deg,temp_c");
        var ci = CultureInfo.InvariantCulture;
        string F(double v) => v.ToString("G17", ci);
        for (int i = 0; i < corrected.Length; i++)
        {
            ct.ThrowIfCancellationRequested();
            var v = corrected[i];
            await writer.WriteLineAsync(string.Join(",", i, accepted[i] ? 1 : 0,
                F(v[0]), F(v[1]), F(v[2]), F(reference[0]), F(reference[1]), F(reference[2]),
                F(Ct03Algorithm.VectorError(v, reference)),
                accepted[i] ? F(Ct03Algorithm.DirectionError(v, reference)) : "",
                F(capture.Samples[i].TemperatureC)));
        }
        await writer.FlushAsync(ct);
    }
}
