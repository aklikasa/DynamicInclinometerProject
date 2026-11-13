using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Dts.Core;
using Dts.TestEngine;
using Dts.Tests.S1.CT10;
using Dts.Tests.S1.CT19;

namespace Dts.Tests.S1;

/// <summary>
/// CT19_MODULE_V1.1 - CT19 uses the already-registered CT10 real dynamic bridge. It adds no vendor DLL,
/// COM session, guessed hardware contract, or second device connection.
/// </summary>
public sealed class CT_19_Test : TestModuleBase
{
    public override string TestId => "CT-19";
    public override bool IsExecutable => true;
    public override string Name => "Gyro独立运行短期重复性";
    public override string Purpose => "基于真实2TD编码器参考和Gyro动态采集，评价各速率/方向跨独立运行的输出与残差离散";
    public override string Procedure => "校验UID/常温JSON→复用CT10真实动态采集桥→各轴/速率正反向独立扫描→编码器微分参考→重复性统计与报告";
    public override string Priority => "P0";
    public override string ImplementationNote => "复用主程序CT10动态适配器；无硬件时标/限速证据时禁止运动；报告仅研发诊断，不自动PASS。";

    public override async Task<TestExecutionResult> ExecuteAsync(TestExecutionContext context, CancellationToken ct)
    {
        if (context.Hardware is not IStaticAngleHardware host)
            throw new InvalidOperationException("CT-19需要主程序真实IStaticAngleHardware");
        if (context.Parameters is not Ct19Settings s)
            throw new InvalidOperationException("CT-19缺少专用窗口参数");
        if (!host.IsTwoTdConnected)
            throw new InvalidOperationException("请先连接真实2TD-600");
        var motion = Ct10DynamicBridge.Resolve(host);
        if (motion is null || !motion.IsRealDynamicCaptureReady)
            throw new NotSupportedException(
                "CT-19复用CT-10真实动态采集桥。当前适配器未就绪；请先核验ct10_machine_profile.json中的固件FIFO槽位、时序不确定度和轴限速。禁止静态采样替代动态数据。");
        var id = host.CurrentIdentity ?? throw new InvalidOperationException("IMU未连接或UID不可用");
        if (!string.Equals(motion.CurrentUidHex, id.UidHex, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("CT-10动态适配器UID与主界面IMU UID不一致");
        s.Calibration.Validate(id);
        if (s.Calibration.Mode != CalibrationMode.Ambient)
            throw new InvalidDataException("CT-19仅使用当前UID匹配的常温ACC/Gyro JSON");
        var acc = s.Calibration.Files?.Acc ?? throw new InvalidDataException("ACC常温JSON缺失");
        var gyro = s.Calibration.Files?.Gyro ?? throw new InvalidDataException("Gyro常温JSON缺失");
        if (gyro.FsHint is null)
            throw new InvalidDataException("Gyro JSON缺少历史拟合输入量程，不能计算动态残差");
        Ct19Algorithm.Validate(s);
        var ct10 = s.ToCt10Settings();
        var plan = Ct19Algorithm.BuildPlan(s, motion);
        VerifyFrozenHashes(s.Calibration);
        await host.VerifyImuForPrecisionTestAsync(ct);
        var initial = await motion.ReadStageAsync(ct);
        VerifyStage(initial);
        EnsureApproved(initial, s);

        string root = Path.GetFullPath(s.OutputRoot);
        if (!Directory.Exists(root)) throw new DirectoryNotFoundException("报告目录不存在：" + root);
        string folder = Path.Combine(root, id.DtsId + "_" + id.UidHex,
            DateTime.Now.ToString("yyyyMMdd_HHmmss_fff", CultureInfo.InvariantCulture) + "_CT-19");
        Directory.CreateDirectory(folder);

        var rows = new List<Ct19RunRow>();
        var started = DateTimeOffset.UtcNow;
        string state = "RUNNING", conclusion = "真实动态采集进行中", failure = "";
        string stopFailure = "", reportFailure = "";
        bool motionIssued = false;
        IReadOnlyList<string> reportFiles = Array.Empty<string>();
        int gyroFs = gyro.FsHint.Value;
        var snapshot = new Ct19SettingsSnapshot(s.SpeedsCsv, s.TestInner, s.TestOuter,
            s.Repetitions, s.TravelMinDeg, s.TravelMaxDeg, s.ApprovedMinDeg, s.ApprovedMaxDeg,
            s.SetupSpeedDps, s.SettleSeconds, s.SpeedToleranceFraction,
            s.EncoderDerivativeWindowSeconds, s.MinAcceptedFrames, s.InnerGyroSign, s.OuterGyroSign);

        Ct19ReportData MakeReport() => new("CT-19", id.UidHex, id.DtsId,
            started, DateTimeOffset.UtcNow, state, conclusion, failure,
            Path.GetFileName(acc.FilePath), acc.Sha256, Path.GetFileName(gyro.FilePath), gyro.Sha256,
            motion.HardwareSourceDescription, snapshot, rows.ToArray(),
            Ct19Algorithm.Group(rows), Ct19Algorithm.Pair(rows),
            "仅测试2TD可提供真实编码器参考的两个旋转轴：内轴对应Gyro Z，外轴对应Gyro X；Gyro Y作为交叉轴输出保存在逐帧数据中，不单独宣称Y轴速率准确度。"+
            "动态时间戳为同一主机Stopwatch时基下的主机接收/反馈时标，不是传感器硬件采样时刻。"+
            "CT-19复用CT-10已核验动态适配器；profile未启用或限速证据缺失时禁止运动。"+
            "当前2TD绝对位置接口仅支持0～360°范围内有限行程扫描，不执行未经核验的多圈连续运动。"+
            "取消/故障后请求双轴软停车；软件软停车不能替代现场实体急停。");

        try
        {
            await File.WriteAllTextAsync(Path.Combine(folder, "CT-19_calibration_identity.json"),
                JsonSerializer.Serialize(new
                {
                    id.DtsId, id.UidHex,
                    CalibrationMode = s.Calibration.Mode.ToString(),
                    AccFile = acc.FilePath, AccSha256 = acc.Sha256,
                    GyroFile = gyro.FilePath, GyroSha256 = gyro.Sha256,
                    GyroInputFullScaleDps = gyroFs,
                    DynamicAdapter = motion.HardwareSourceDescription,
                    Mapping = new { InnerTurntable = "Gyro Z", OuterTurntable = "Gyro X", GyroY = "cross-axis only" },
                    Note = "只读取当前UID匹配常温JSON；每段运动前后重验SHA256；不重新拟合、不额外除以8。"
                }, new JsonSerializerOptions { WriteIndented = true }), ct);

            for (int i = 0; i < plan.Count; i++)
            {
                ct.ThrowIfCancellationRequested();
                if (!string.Equals(host.CurrentIdentity?.UidHex, id.UidHex, StringComparison.OrdinalIgnoreCase) ||
                    !string.Equals(motion.CurrentUidHex, id.UidHex, StringComparison.OrdinalIgnoreCase))
                    throw new InvalidDataException("测试期间IMU UID发生变化");
                VerifyFrozenHashes(s.Calibration);
                var sweep = plan[i];
                string gyroAxis = sweep.Axis == Ct10Axis.Inner ? "Z" : "X";
                context.Progress?.Report($"CT-19 [{i+1}/{plan.Count}] Gyro {gyroAxis} / {sweep.CommandDps:F2}°/s / {sweep.Direction} / R{sweep.Repetition}：准备起点");
                motionIssued = true;
                await motion.MoveToSafeStartAsync(sweep.Axis, sweep.StartDeg, s.SetupSpeedDps,
                    s.ApprovedMinDeg, s.ApprovedMaxDeg, ct);
                await Task.Delay(TimeSpan.FromSeconds(s.SettleSeconds), ct);
                var stage = await motion.ReadStageAsync(ct);
                VerifyStage(stage);
                double target = sweep.Axis == Ct10Axis.Inner ? stage.InnerPositionDeg : stage.OuterPositionDeg;
                double other = sweep.Axis == Ct10Axis.Inner ? stage.OuterPositionDeg : stage.InnerPositionDeg;
                if (Math.Abs(target - sweep.StartDeg) > 0.5 || Math.Abs(other) > 0.5)
                    throw new IOException("真实反馈未到达CT-19起点，或非测试轴未保持0°");

                context.Progress?.Report($"CT-19 [{i+1}/{plan.Count}] 已启动真实Gyro+编码器动态采集");
                using var timeout = CancellationTokenSource.CreateLinkedTokenSource(ct);
                timeout.CancelAfter(TimeSpan.FromSeconds(sweep.SafetyTimeoutSeconds));
                Ct10Capture capture;
                try
                {
                    capture = await motion.ExecuteSynchronizedSweepAsync(sweep, context.Progress, timeout.Token);
                }
                catch (OperationCanceledException) when (!ct.IsCancellationRequested)
                {
                    throw new TimeoutException($"动态扫描超过安全超时{sweep.SafetyTimeoutSeconds:F0}s");
                }
                if (!capture.MotionCompletedNormally ||
                    !string.Equals(capture.FullUidHex, id.UidHex, StringComparison.OrdinalIgnoreCase))
                    throw new InvalidDataException("动态采集未正常结束或采集UID不匹配");
                VerifyFrozenHashes(s.Calibration);

                string csv = Path.Combine(folder,
                    $"run_{i+1:D3}_{gyroAxis}_{sweep.CommandDps.ToString("0.###", CultureInfo.InvariantCulture)}_{sweep.Direction}_R{sweep.Repetition:D2}.csv");
                var analyzed = Ct10Algorithm.Analyze(sweep, capture, ct10,
                    (x, y, z) => gyro.Apply(x, y, z), gyroFs, csv);
                await Ct19Report.WriteSweepCsvAsync(csv, analyzed, ct);
                string quality = analyzed.AcceptedFrames >= s.MinAcceptedFrames
                    ? "有效匀速段满足最低帧数；研发待验收"
                    : "有效匀速段帧数不足";
                rows.Add(new Ct19RunRow(rows.Count + 1, gyroAxis,
                    sweep.Axis == Ct10Axis.Inner ? "内轴" : "外轴",
                    sweep.CommandDps, sweep.Repetition, sweep.Direction.ToString(),
                    analyzed.MeanReferenceSignedDps, analyzed.MeanGyroSignedDps,
                    analyzed.MeanResidualDps, analyzed.ResidualRmseDps, analyzed.ResidualStdDps,
                    analyzed.ScaleRatioPercent, analyzed.MeanTemperatureC,
                    analyzed.TotalGyroFrames, analyzed.AcceptedFrames, analyzed.EncoderFrames,
                    csv, analyzed.EvidenceSource, quality));

                state = "RUNNING";
                conclusion = $"已完成{rows.Count}/{plan.Count}段真实动态运行；阶段性结果，不代表产品PASS";
                await Ct19Report.SaveAsync(folder, MakeReport(), ct, checkpoint: true);
                context.Progress?.Report($"CT-19 [{i+1}/{plan.Count}] 完成：残差{analyzed.MeanResidualDps:F4}°/s，匀速有效帧{analyzed.AcceptedFrames}");
            }
            state = "COMPLETED_PENDING_ACCEPTANCE";
            conclusion = $"完成{rows.Count}/{plan.Count}段真实动态扫描；输出均值及残差跨运行标准差已分组统计，研发待验收";
        }
        catch (OperationCanceledException)
        {
            state = "CANCELLED_PARTIAL";
            conclusion = "用户取消；保留已完成动态运行及部分报告";
            throw;
        }
        catch (Exception ex)
        {
            state = "FAILED_PARTIAL";
            failure = ex.Message;
            conclusion = "测试中止；已完成的真实动态运行保留";
            throw;
        }
        finally
        {
            if (motionIssued)
            {
                using var stop = new CancellationTokenSource(TimeSpan.FromSeconds(8));
                try { await motion.StopBothAxesAsync(stop.Token); }
                catch (Exception ex)
                {
                    stopFailure = ex.Message;
                    state = "STOP_NOT_CONFIRMED";
                    failure = (failure + "；双轴软停车未确认：" + stopFailure).Trim('；');
                    context.Progress?.Report("危险：双轴软停车未确认，请现场核查并使用实体急停");
                }
            }
            try { reportFiles = await Ct19Report.SaveAsync(folder, MakeReport(), CancellationToken.None); }
            catch (Exception ex)
            {
                reportFailure = ex.Message;
                context.Progress?.Report("CT-19报告保存失败：" + ex.Message + "；原始逐段CSV仍保留：" + folder);
            }
        }
        if (stopFailure.Length > 0) throw new IOException("CT-19双轴软停车未确认，禁止继续运动；请现场检查并使用实体急停。", new IOException(stopFailure));
        if (reportFailure.Length > 0) throw new IOException("CT-19报告导出失败：" + reportFailure);
        return new TestExecutionResult(TestId, TestOutcome.PendingAcceptance,
            $"CT-19完成{rows.Count}段真实动态运行；按Gyro轴/速率/方向统计跨运行标准差；研发待验收。数据源：{motion.HardwareSourceDescription}",
            null, reportFiles);
    }

    private static void VerifyFrozenHashes(CalibrationRun run)
    {
        foreach (var f in run.Sources)
            if (!File.Exists(f.FilePath) ||
                !Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(f.FilePath)))
                    .Equals(f.Sha256, StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("常温标定JSON发生变化：" + f.FilePath);
    }

    private static void VerifyStage(Ct10StageStatus s)
    {
        if (!s.InnerEnabled || !s.OuterEnabled || !s.InnerNormal || !s.OuterNormal ||
            !s.InnerStationary || !s.OuterStationary ||
            !double.IsFinite(s.InnerPositionDeg) || !double.IsFinite(s.OuterPositionDeg))
            throw new IOException("2TD双轴未使能/报警/未静止：" + s.Detail);
    }

    private static void EnsureApproved(Ct10StageStatus s, Ct19Settings settings)
    {
        if (s.InnerPositionDeg < settings.ApprovedMinDeg || s.InnerPositionDeg > settings.ApprovedMaxDeg ||
            s.OuterPositionDeg < settings.ApprovedMinDeg || s.OuterPositionDeg > settings.ApprovedMaxDeg)
            throw new IOException("当前转台位置超出已批准行程，禁止开始CT-19");
    }
}
