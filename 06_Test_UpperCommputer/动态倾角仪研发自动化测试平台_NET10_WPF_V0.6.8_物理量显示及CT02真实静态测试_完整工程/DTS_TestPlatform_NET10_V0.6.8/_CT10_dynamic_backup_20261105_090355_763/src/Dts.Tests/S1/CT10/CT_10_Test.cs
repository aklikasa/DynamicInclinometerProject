using System.Diagnostics;
using System.Security.Cryptography;
using System.Text.Json;
using Dts.Core;
using Dts.TestEngine;
using Dts.Tests.S1.CT10;

namespace Dts.Tests.S1;

/// <summary>
/// CT-10 must NEVER call static sampling while the table is moving. It requires a real
/// ICt10DynamicHardware adapter, otherwise it fails before any motion or report creation.
/// </summary>
public sealed class CT_10_Test : TestModuleBase
{
    public override string TestId => "CT-10";
    public override bool IsExecutable => true;
    public override string Purpose => "GYRO多档真实转速下的正反向动态残差与比例差诊断";
    public override string Procedure => "绑定UID及Gyro常温JSON→确认动态同步源→各速度先正向再反向扫描→实测编码器微分→匀速段残差→报告";
    public override string Priority => "P0";
    public override string ImplementationNote => "真实运动时须同步Gyro FIFO与2TD反馈；未注册动态采集桥接器禁止运行；报告仅研发待验收";

    public override async Task<TestExecutionResult> ExecuteAsync(TestExecutionContext context, CancellationToken ct)
    {
        if (context.Hardware is not IStaticAngleHardware host)
            throw new InvalidOperationException("CT-10找不到当前平台硬件对象");
        var motionHw = Ct10DynamicBridge.Resolve(host);
        if (motionHw is null || !motionHw.IsRealDynamicCaptureReady)
            throw new NotSupportedException("CT-10需要真实GYRO运动同步采集适配器。当前V0.6.8只有静态采样接口，请先接通ICt10DynamicHardware；禁止伪造动态结果");
        if (context.Parameters is not Ct10Settings s)
            throw new InvalidOperationException("CT-10缺少专用窗口的参数快照");
        var id = host.CurrentIdentity ?? throw new InvalidOperationException("IMU尚未读取完整UID");
        if (!host.IsTwoTdConnected) throw new InvalidOperationException("2TD双轴未连接和使能");
        if (!string.Equals(motionHw.CurrentUidHex, id.UidHex, StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("同步采集器与IMU主界面UID不同，禁止测试");
        // The window freezes UID-matched calibration into the execution parameter snapshot.
        var calibration = s.Calibration;
        if (calibration.Mode != CalibrationMode.Ambient)
            throw new InvalidOperationException("CT-10当前使用常温标定模型，先在主窗口选择常温标定");
        calibration.Validate(id);
        var gyro = calibration.Files?.Gyro ?? throw new InvalidDataException("UID匹配的Gyro常温JSON缺失");
        var acc = calibration.Files?.Acc ?? throw new InvalidDataException("UID匹配的ACC常温JSON缺失");
        if (gyro.FsHint is null)
            throw new InvalidDataException("历史Gyro JSON缺少拟合输入量程，不可进行多速率残差评估");
        var plan = Ct10Algorithm.BuildPlan(s, motionHw);
        VerifyFrozenHashes(calibration);
        await host.VerifyImuForPrecisionTestAsync(ct);
        Ct10StageStatus status = await motionHw.ReadStageAsync(ct);
        if (!status.InnerEnabled || !status.OuterEnabled || !status.InnerNormal ||
            !status.OuterNormal || !status.InnerStationary || !status.OuterStationary)
            throw new IOException("双轴不是已使能且静止的正常状态：" + status.Detail);
        if (status.InnerPositionDeg < s.ApprovedMinDeg || status.InnerPositionDeg > s.ApprovedMaxDeg ||
            status.OuterPositionDeg < s.ApprovedMinDeg || status.OuterPositionDeg > s.ApprovedMaxDeg)
            throw new IOException("转台反馈越界，禁止运动");
        string root = Path.GetFullPath(s.OutputRoot);
        if (!Directory.Exists(root)) throw new DirectoryNotFoundException("报告根目录不存在：" + root);
        string directory = Path.Combine(root, id.DtsId + "_" + id.UidHex,
            DateTime.Now.ToString("yyyyMMdd_HHmmss_fff") + "_CT-10");
        Directory.CreateDirectory(directory);
        var results = new List<Ct10SweepResult>();
        string started = DateTimeOffset.UtcNow.ToString("O"), state = "RUNNING", why = "";
        string stopFailure = "", reportFailure = "";
        IReadOnlyList<string> exported = Array.Empty<string>();
        bool motionIssued = false;
        int gyroFs = gyro.FsHint.Value;
        var snapshot = new Ct10SettingsSnapshot(s.SpeedsCsv, s.TestInner, s.TestOuter,
            s.Repetitions, s.TravelMinDeg, s.TravelMaxDeg,
            s.ApprovedMinDeg, s.ApprovedMaxDeg, s.SetupSpeedDps,
            s.SettleSeconds, s.SpeedToleranceFraction, s.EncoderDerivativeWindowSeconds,
            s.MinAcceptedFrames, s.InnerGyroSign, s.OuterGyroSign);
        Ct10ReportData Snapshot() => new("CT-10", id.UidHex, started,
            DateTimeOffset.UtcNow.ToString("O"), state, why,
            "研发待验收：比例/方向残差必须结合计量参考不确定度和设备规格解释，不自动PASS",
            snapshot, Path.GetFileName(gyro.FilePath), gyro.Sha256,
            Path.GetFileName(acc.FilePath), acc.Sha256, gyroFs,
            motionHw.HardwareSourceDescription, results.ToArray(), Ct10Algorithm.Pair(results),
            "Gyro与2TD编码器用同一Stopwatch时钟；以编码器位置时间微分为参考。"+
            "实际速度、轴对准、机械振动、UART延迟、校准范围及时间偏移影响误差；加减速段剔除。"+
            "软件软停车不等于硬件急停，测试必须有人现场监护。故障保留已完成真实运动数据。");
        try
        {
            await File.WriteAllTextAsync(Path.Combine(directory, "CT-10_calibration_identity.json"),
                JsonSerializer.Serialize(new { id.DtsId, id.UidHex, gyro.FilePath, gyro.Sha256,
                    GyroCalibrationInputFullScaleDps = gyroFs, acc.FilePath, acc.Sha256,
                    SynchronizedAdapter = motionHw.HardwareSourceDescription,
                    Note = "必须同一时基真实同步采集，JSON只读，每段重验" },
                    new JsonSerializerOptions { WriteIndented = true }), ct);
            for (int i = 0; i < plan.Count; i++)
            {
                ct.ThrowIfCancellationRequested();
                VerifyFrozenHashes(calibration);
                if (!string.Equals(motionHw.CurrentUidHex, id.UidHex, StringComparison.OrdinalIgnoreCase))
                    throw new InvalidDataException("测试中完整UID发生变化");
                var sweep = plan[i];
                context.Progress?.Report($"CT-10 [{i + 1}/{plan.Count}] {sweep.Axis} " +
                    $"{sweep.CommandDps:F3}°/s {sweep.Direction}：准备真实起点");
                motionIssued = true;
                await motionHw.MoveToSafeStartAsync(sweep.Axis, sweep.StartDeg,
                    s.SetupSpeedDps, s.ApprovedMinDeg, s.ApprovedMaxDeg, ct);
                await Task.Delay(TimeSpan.FromSeconds(s.SettleSeconds), ct);
                status = await motionHw.ReadStageAsync(ct);
                if (!status.InnerNormal || !status.OuterNormal || !status.InnerEnabled ||
                    !status.OuterEnabled || !status.InnerStationary || !status.OuterStationary)
                    throw new IOException("准备结束时转台状态异常：" + status.Detail);
                double position = sweep.Axis == Ct10Axis.Inner ? status.InnerPositionDeg : status.OuterPositionDeg;
                double other = sweep.Axis == Ct10Axis.Inner ? status.OuterPositionDeg : status.InnerPositionDeg;
                if (Math.Abs(position - sweep.StartDeg) > 0.5 || Math.Abs(other) > 0.5)
                    throw new IOException("真实反馈未到达起点或另一轴未在0°");
                context.Progress?.Report($"CT-10 [{i + 1}/{plan.Count}] 开始同步实测运动（非静态采样）");
                // Bridge must arm both telemetry streams BEFORE sending the sweep motion command.
                using var sweepTimeout = CancellationTokenSource.CreateLinkedTokenSource(ct);
                sweepTimeout.CancelAfter(TimeSpan.FromSeconds(sweep.SafetyTimeoutSeconds));
                Ct10Capture capture;
                try
                {
                    capture = await motionHw.ExecuteSynchronizedSweepAsync(sweep, context.Progress,
                        sweepTimeout.Token);
                }
                catch (OperationCanceledException) when (!ct.IsCancellationRequested)
                {
                    throw new TimeoutException($"动态运动超过安全超时 {sweep.SafetyTimeoutSeconds:F0}s；将请求双轴软停车");
                }
                if (!string.Equals(capture.FullUidHex, id.UidHex, StringComparison.OrdinalIgnoreCase))
                    throw new InvalidDataException("运动采集返回的UID不符");
                VerifyFrozenHashes(calibration);
                string csv = Path.Combine(directory,
                    $"sweep_{i + 1:D3}_{sweep.Axis}_{sweep.CommandDps.ToString("0.###",System.Globalization.CultureInfo.InvariantCulture)}_{sweep.Direction}.csv");
                Ct10SweepResult analyzed = Ct10Algorithm.Analyze(sweep, capture, s,
                    (x, y, z) => gyro.Apply(x, y, z), gyroFs, csv);
                await Ct10Report.WriteSweepCsvAsync(csv, analyzed, ct);
                results.Add(analyzed);
                await Ct10Report.SaveCheckpointAsync(directory, Snapshot(), ct);
                context.Progress?.Report($"CT-10 [{i + 1}/{plan.Count}] 有效{analyzed.AcceptedFrames}帧，"+
                    $"真实参考{analyzed.MeanReferenceSignedDps:F3}°/s，残差{analyzed.MeanResidualDps:F5}°/s");
            }
            state = "COMPLETED_PENDING_ACCEPTANCE";
            why = $"完成{results.Count}段真实动态运动，{Ct10Algorithm.Pair(results).Count}档位成对分析";
        }
        catch (OperationCanceledException)
        {
            state = "CANCELLED_PARTIAL";
            why = "用户取消，保留已完成的真实动态扫描段";
            throw;
        }
        catch (Exception ex)
        {
            state = "FAILED_PARTIAL";
            why = ex.Message;
            throw;
        }
        finally
        {
            if (motionIssued)
            {
                using var stopCts = new CancellationTokenSource(TimeSpan.FromSeconds(5));
                try { await motionHw.StopBothAxesAsync(stopCts.Token); }
                catch (Exception ex)
                {
                    stopFailure = ex.Message; state = "STOP_NOT_CONFIRMED";
                    why += "；双轴软停车未得到确认：" + stopFailure;
                    context.Progress?.Report("危险：双轴软停车未确认，请现场确认并使用实体急停");
                }
            }
            try { exported = await Ct10Report.ExportAsync(directory, Snapshot(), CancellationToken.None); }
            catch (Exception ex)
            {
                reportFailure = ex.Message;
                context.Progress?.Report("CT-10报告导出失败：" + ex.Message);
            }
        }
        if (stopFailure.Length > 0) throw new IOException("CT-10软停车未确认：" + stopFailure);
        if (reportFailure.Length > 0) throw new IOException("CT-10报告导出失败：" + reportFailure);
        return new TestExecutionResult(TestId, TestOutcome.PendingAcceptance,
            $"CT-10真实多速率正反向扫描完成，{results.Count}段，"+
            $"{Ct10Algorithm.Pair(results).Count}个轴/速度档，待验收；数据源：{motionHw.HardwareSourceDescription}",
            null, exported);
    }
    private static void VerifyFrozenHashes(CalibrationRun run)
    {
        foreach (var f in run.Sources)
        {
            if (!File.Exists(f.FilePath) ||
                !Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(f.FilePath)))
                    .Equals(f.Sha256, StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("测试期间标定文件变更：" + f.FilePath);
        }
    }
}
