using System.Globalization;
using System.Runtime.ExceptionServices;
using System.Security.Cryptography;
using System.Text.Json;
using Dts.Core;
using Dts.TestEngine;
using Dts.Tests.S1.CT10;
using Dts.Tests.S1.CT27;

namespace Dts.Tests.S1;

/// <summary>
/// CT-27 measures the change of the calibrated gyro zero-rate output after a real,
/// encoder-observed turntable sweep. It is a diagnostic module, never an automatic PASS.
/// </summary>
public sealed class CT_27_Test : TestModuleBase
{
    public override string TestId => "CT-27";
    public override bool IsExecutable => true;
    public override string Name => "Gyro运动后零偏恢复专项";
    public override string Purpose => "通过真实2TD运动前零速基线与运动后分窗零速采样，观察三轴校正Gyro零偏台阶、方向依赖及恢复时间";
    public override string Procedure => "校验UID/常温ACC-Gyro JSON→复用CT-10真实动态桥→运动前180～300s零速基线→3.5/30°/s正反向真实编码器扫描→停稳后60～180s分窗零速采集→零偏变化与恢复时间报告";
    public override string Priority => "P0";
    public override string ImplementationNote => "复用CT-10真实动态适配器和主程序静态FIFO采集；必须通过profile限速/采集核验。只报告Gyro零速偏差诊断，不自动PASS。";

    public override async Task<TestExecutionResult> ExecuteAsync(TestExecutionContext context, CancellationToken ct)
    {
        if (context.Hardware is not IStaticAngleHardware host)
            throw new InvalidOperationException("CT-27需要主程序真实IStaticAngleHardware");
        if (context.Parameters is not Ct27Settings settings)
            throw new InvalidOperationException("CT-27缺少专用窗口参数快照");
        if (!host.IsTwoTdConnected)
            throw new InvalidOperationException("CT-27需要真实2TD-600双轴连接并使能");

        ICt10DynamicHardware motion = Ct10DynamicBridge.Resolve(host)
            ?? throw new NotSupportedException("CT-27复用CT-10真实动态桥；当前未注册动态适配器，禁止使用命令速率或静态采样代替运动证据");
        if (!motion.IsRealDynamicCaptureReady)
            throw new NotSupportedException("CT-10动态适配器尚未通过ct10_machine_profile.json核验，CT-27禁止运动");

        DeviceIdentity id = host.CurrentIdentity ?? throw new InvalidOperationException("IMU未连接或完整UID不可用");
        if (!string.Equals(motion.CurrentUidHex, id.UidHex, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("CT-10动态适配器UID与主界面IMU UID不一致");
        settings.Calibration.Validate(id);
        if (settings.Calibration.Mode != CalibrationMode.Ambient)
            throw new InvalidDataException("CT-27仅使用当前设备UID匹配的常温标定文件");
        CalibrationMatrix acc = settings.Calibration.Files?.Acc
            ?? throw new InvalidDataException("CT-27缺少UID匹配的ACC常温JSON");
        CalibrationMatrix gyro = settings.Calibration.Files?.Gyro
            ?? throw new InvalidDataException("CT-27缺少UID匹配的Gyro常温JSON");
        if (acc.FsHint is null || gyro.FsHint is null)
            throw new InvalidDataException("ACC/Gyro常温JSON缺少历史拟合输入量程，禁止推测量程");

        Ct27Algorithm.ValidateSettings(settings, requireSafety: true);
        IReadOnlyList<Ct27PlanItem> plan = Ct27Algorithm.BuildPlan(settings, motion);
        VerifyFrozenHashes(settings.Calibration);
        await host.VerifyImuForPrecisionTestAsync(ct);
        Ct10StageStatus initial = await motion.ReadStageAsync(ct);
        VerifyStationary(initial, "初始状态");
        EnsureApproved(initial, settings);

        string root = Path.GetFullPath(settings.OutputRoot);
        if (!Directory.Exists(root)) throw new DirectoryNotFoundException("CT-27报告根目录不存在：" + root);
        string folder = Path.Combine(root, id.DtsId + "_" + id.UidHex,
            DateTime.Now.ToString("yyyyMMdd_HHmmss_fff", CultureInfo.InvariantCulture) + "_CT-27");
        Directory.CreateDirectory(folder);

        var cycles = new List<Ct27CycleResult>();
        var bins = new List<Ct27RecoveryBin>();
        DateTimeOffset started = DateTimeOffset.UtcNow;
        string state = "RUNNING";
        string reason = "真实运动及运动后零速恢复采集进行中";
        string stopFailure = string.Empty;
        string reportFailure = string.Empty;
        bool motionIssued = false;
        IReadOnlyList<string> outputs = Array.Empty<string>();
        var snapshot = new Ct27SettingsSnapshot(settings.SpeedsCsv, settings.TestInner,
            settings.TestOuter, settings.Repetitions, settings.TravelMinDeg, settings.TravelMaxDeg,
            settings.ApprovedMinDeg, settings.ApprovedMaxDeg, settings.SetupSpeedDps,
            settings.SettleSeconds, settings.BaselineSeconds, settings.RecoverySeconds,
            settings.BinSeconds, settings.RecoveryBandDps, settings.ConsecutiveStableBins,
            settings.MinSamplesPerBin);

        Ct27ReportData MakeReport() => new(
            "CT-27", "Gyro运动后零偏恢复专项", id.DtsId, id.UidHex,
            started.ToString("O"), DateTimeOffset.UtcNow.ToString("O"), state, reason,
            state == "COMPLETED_DIAGNOSTIC_ONLY"
                ? $"完成{cycles.Count}/{plan.Count}个运动工况；观察到{cycles.Count(x => x.RecoveredBySeconds.HasValue)}个工况在设定观察带内稳定恢复。结果仅为工程诊断，不代表产品PASS。"
                : $"工况完成{cycles.Count}/{plan.Count}；{reason}",
            settings.Calibration.Mode.ToString(), Path.GetFileName(acc.FilePath), acc.Sha256,
            Path.GetFileName(gyro.FilePath), gyro.Sha256, motion.HardwareSourceDescription,
            snapshot, plan, cycles.ToArray(), bins.ToArray(), Ct27Algorithm.Summarize(cycles),
            "零速基线和恢复窗口来自真实IMU FIFO，原始物理量按当前UID常温Gyro JSON的输入量程换算后，再将Gyro偏置/矩阵应用一次。" +
            "运动由CT-10真实动态适配器执行，编码器反馈用于确认真实起终点和估算中段实测速率；Gyro运动帧时标是主机接收时标，不是传感器硬件采样时刻。" +
            "每个方向/速率工况均在定位并静置后单独采集零速基线，运动后以离散时间窗观察三轴校正Gyro均值相对该基线的变化。" +
            "恢复时间是连续稳定窗口且后续窗口不反弹时的观测上界；观察带为用户分析参数，不是产品规格。Gyro Y作为交叉轴输出，不单独声称具有转台独立参考。" +
            "每个单向扫描的运动前基线位于起始姿态，运动后窗口位于终止姿态；地球自转投影、姿态相关交叉轴效应及温度变化也可能贡献表观零偏差，不能将差值解释为纯粹的器件偏置恢复。" +
            "不测量设备融合倾角，不重新拟合标定参数，不做额外1/8缩放；没有可溯源产品标准和参考不确定度时不输出PASS/FAIL。" +
            "取消或故障时请求双轴软停车；软件停车不能替代现场实体急停。");

        Exception? failure = null;
        try
        {
            await File.WriteAllTextAsync(Path.Combine(folder, "CT-27_calibration_identity.json"),
                JsonSerializer.Serialize(new
                {
                    id.DtsId,
                    id.UidHex,
                    CalibrationMode = settings.Calibration.Mode.ToString(),
                    AccFile = acc.FilePath,
                    AccSha256 = acc.Sha256,
                    AccInputFullScaleG = acc.FsHint,
                    GyroFile = gyro.FilePath,
                    GyroSha256 = gyro.Sha256,
                    GyroInputFullScaleDps = gyro.FsHint,
                    DynamicAdapter = motion.HardwareSourceDescription,
                    Mapping = new { InnerTurntable = "Gyro Z", OuterTurntable = "Gyro X", GyroY = "cross-axis observation" },
                    Note = "真实静态物理量使用JSON输入量程；Gyro校正矩阵只应用一次；不额外除以8。"
                }, new JsonSerializerOptions { WriteIndented = true }), ct);

            for (int i = 0; i < plan.Count; i++)
            {
                ct.ThrowIfCancellationRequested();
                VerifyIdentity(host, motion, id.UidHex, settings.Calibration);
                Ct27PlanItem item = plan[i];
                context.Progress?.Report($"CT-27 [{i + 1}/{plan.Count}] Gyro {item.GyroAxis} / {item.CommandDps:F2}°/s / {item.DirectionText}：准备起点");

                // This call may reposition either table axis; any cancellation after this point must request a stop.
                motionIssued = true;
                await motion.MoveToSafeStartAsync(item.Axis, item.StartDeg, settings.SetupSpeedDps,
                    settings.ApprovedMinDeg, settings.ApprovedMaxDeg, ct);
                await Task.Delay(TimeSpan.FromSeconds(settings.SettleSeconds), ct);
                Ct10StageStatus atStart = await motion.ReadStageAsync(ct);
                VerifyAtPosition(atStart, item, item.StartDeg, "运动前基线");
                VerifyIdentity(host, motion, id.UidHex, settings.Calibration);

                string baselineCsv = Path.Combine(folder, $"cycle_{item.Index:D2}_baseline.csv");
                context.Progress?.Report($"CT-27 [{i + 1}/{plan.Count}] 采集运动前零速基线 {settings.BaselineSeconds:F0}s");
                StaticPointSamples baselineCapture = await CaptureVerifiedStationaryWindowAsync(
                    host, motion, item, item.StartDeg, baselineCsv,
                    TimeSpan.FromSeconds(settings.BaselineSeconds), context.Progress, ct,
                    "运动前基线");
                VerifyIdentity(host, motion, id.UidHex, settings.Calibration);
                VerifyPhysicalCsvScale(baselineCsv, gyro.FsHint.Value);
                int minimumBaseline = Math.Max(100, settings.MinSamplesPerBin * 5);
                Ct27WindowStats baseline = Ct27Algorithm.Summarize(baselineCapture, gyro, minimumBaseline);

                context.Progress?.Report($"CT-27 [{i + 1}/{plan.Count}] 启动真实{item.CommandDps:F2}°/s {item.DirectionText}扫描");
                Ct10Capture motionCapture = await motion.ExecuteSynchronizedSweepAsync(
                    item.ToSweepRequest(), context.Progress, ct);
                Ct27Algorithm.ValidateMotionCapture(item, motionCapture, id.UidHex, gyro.FsHint.Value);
                VerifyIdentity(host, motion, id.UidHex, settings.Calibration);
                double measuredRate = Ct27Algorithm.EstimateMedianEncoderRate(item, motionCapture);
                (string motionGyroCsv, string motionEncoderCsv) = await Ct27Report.WriteMotionEvidenceAsync(
                    folder, item.Index, motionCapture, gyro, ct);

                Ct10StageStatus stopped = await motion.ReadStageAsync(ct);
                VerifyAtPosition(stopped, item, item.EndDeg, "运动后停稳确认");
                DateTimeOffset stopConfirmedUtc = DateTimeOffset.UtcNow;
                var cycleBins = new List<Ct27RecoveryBin>();
                int binCount = Ct27Algorithm.RecoveryBinCount(settings);
                for (int b = 1; b <= binCount; b++)
                {
                    ct.ThrowIfCancellationRequested();
                    VerifyIdentity(host, motion, id.UidHex, settings.Calibration);
                    string binCsv = Path.Combine(folder, $"cycle_{item.Index:D2}_recovery_{b:D3}.csv");
                    StaticPointSamples recoveryCapture = await CaptureVerifiedStationaryWindowAsync(
                        host, motion, item, item.EndDeg, binCsv,
                        TimeSpan.FromSeconds(settings.BinSeconds), context.Progress, ct,
                        $"运动后恢复窗口{b}");
                    VerifyIdentity(host, motion, id.UidHex, settings.Calibration);
                    VerifyPhysicalCsvScale(binCsv, gyro.FsHint.Value);
                    Ct27WindowStats value = Ct27Algorithm.Summarize(
                        recoveryCapture, gyro, settings.MinSamplesPerBin);
                    double deltaX = value.MeanX - baseline.MeanX;
                    double deltaY = value.MeanY - baseline.MeanY;
                    double deltaZ = value.MeanZ - baseline.MeanZ;
                    double maxAbs = Math.Max(Math.Abs(deltaX), Math.Max(Math.Abs(deltaY), Math.Abs(deltaZ)));
                    DateTimeOffset midpoint = recoveryCapture.StartedUtc +
                        TimeSpan.FromTicks((recoveryCapture.EndedUtc - recoveryCapture.StartedUtc).Ticks / 2);
                    var row = new Ct27RecoveryBin(item.Index, b,
                        (midpoint - stopConfirmedUtc).TotalSeconds,
                        (recoveryCapture.EndedUtc - stopConfirmedUtc).TotalSeconds,
                        recoveryCapture.StartedUtc.ToString("O"), recoveryCapture.EndedUtc.ToString("O"),
                        value.MeanX, value.MeanY, value.MeanZ, value.StdX, value.StdY, value.StdZ,
                        deltaX, deltaY, deltaZ, maxAbs, value.MeanTemperatureC,
                        value.Samples, value.Batches, value.DuplicateBatches, binCsv);
                    bins.Add(row);
                    cycleBins.Add(row);
                    await Ct27Report.SaveCheckpointAsync(folder, MakeReport(), ct);
                    context.Progress?.Report($"CT-27 [{i + 1}/{plan.Count}] 恢复窗口 {b}/{binCount}：max|Δbias|={maxAbs:F5}°/s");
                }

                double? recovered = Ct27Algorithm.FindRecoveryUpperBound(
                    cycleBins, settings.RecoveryBandDps, settings.ConsecutiveStableBins);
                double peak = cycleBins.Max(x => x.MaxAbsDeltaDps);
                Ct27RecoveryBin final = cycleBins[cycleBins.Count - 1];
                string quality = Math.Abs(measuredRate - item.CommandDps) / item.CommandDps > 0.35
                    ? "真实运动已完成，但编码器中段实测速率偏离命令值超过35%；解释时按实测速率报告"
                    : "真实运动与恢复窗口采集完整；工程诊断待验收";
                cycles.Add(new Ct27CycleResult(item.Index, item.GyroAxis,
                    item.Axis == Ct10Axis.Inner ? "2TD内轴" : "2TD外轴",
                    item.CommandDps, measuredRate, item.Repetition, item.DirectionText,
                    item.StartDeg, item.EndDeg,
                    baselineCapture.StartedUtc.ToString("O"), baselineCapture.EndedUtc.ToString("O"),
                    baseline.MeanX, baseline.MeanY, baseline.MeanZ,
                    baseline.StdX, baseline.StdY, baseline.StdZ, baseline.MeanTemperatureC,
                    baseline.Samples, stopConfirmedUtc.ToString("O"), peak,
                    final.DeltaX, final.DeltaY, final.DeltaZ, recovered, cycleBins.Count,
                    quality, baselineCsv, motionGyroCsv, motionEncoderCsv));
                await Ct27Report.SaveCheckpointAsync(folder, MakeReport(), ct);
            }
            state = "COMPLETED_DIAGNOSTIC_ONLY";
            reason = $"完成全部{cycles.Count}/{plan.Count}个工况；未执行产品PASS/FAIL判定";
        }
        catch (OperationCanceledException ex)
        {
            failure = ex;
            state = "CANCELLED_PARTIAL";
            reason = "用户取消；保留已完成的基线、运动和恢复窗口证据";
        }
        catch (Exception ex)
        {
            failure = ex;
            state = "FAILED_PARTIAL";
            reason = ex.Message;
        }
        finally
        {
            if (motionIssued)
            {
                try
                {
                    await motion.StopBothAxesAsync(CancellationToken.None);
                }
                catch (Exception ex)
                {
                    stopFailure = ex.Message;
                    state = "STOP_NOT_CONFIRMED";
                    reason += "；双轴软停车未确认：" + stopFailure;
                    context.Progress?.Report("警告：CT-27双轴软停车未确认，请现场检查或立即使用实体急停");
                }
            }
            try
            {
                outputs = await Ct27Report.ExportAsync(folder, MakeReport(), CancellationToken.None);
            }
            catch (Exception ex)
            {
                reportFailure = ex.Message;
                context.Progress?.Report("CT-27报告导出失败，请保留已采集CSV：" + folder + "；" + reportFailure);
            }
        }

        if (stopFailure.Length > 0)
        {
            var stopError = new IOException("CT-27双轴软停车未确认：" + stopFailure);
            if (failure is not null) throw new AggregateException(stopError, failure);
            throw stopError;
        }
        if (reportFailure.Length > 0)
        {
            var reportError = new IOException("CT-27报告导出失败：" + reportFailure);
            if (failure is not null) throw new AggregateException(reportError, failure);
            throw reportError;
        }
        if (failure is not null) ExceptionDispatchInfo.Capture(failure).Throw();

        Ct27Aggregate aggregate = Ct27Algorithm.Summarize(cycles)
            ?? throw new InvalidDataException("CT-27没有完成任何运动后恢复工况");
        return new TestExecutionResult(TestId, TestOutcome.DiagnosticOnly,
            $"CT-27完成{aggregate.CompletedCycles}个真实运动工况；{aggregate.RecoveryObservedCycles}个工况在观察带内达到持续恢复条件。" +
            "输出为Gyro零速偏差工程诊断，不代表产品PASS。",
            null, outputs);
    }

    private static async Task<StaticPointSamples> CaptureVerifiedStationaryWindowAsync(
        IStaticAngleHardware host, ICt10DynamicHardware motion, Ct27PlanItem item,
        double expectedPosition, string csvPath, TimeSpan duration,
        IProgress<string>? progress, CancellationToken ct, string label)
    {
        using var captureCts = CancellationTokenSource.CreateLinkedTokenSource(ct);
        Task<StaticPointSamples> captureTask = host.CaptureStaticPointAsync(
            csvPath, duration, progress, captureCts.Token);
        try
        {
            while (!captureTask.IsCompleted)
            {
                Task delay = Task.Delay(TimeSpan.FromSeconds(1), captureCts.Token);
                Task completed = await Task.WhenAny(captureTask, delay);
                if (completed == captureTask) break;
                captureCts.Token.ThrowIfCancellationRequested();
                VerifyAtPosition(await motion.ReadStageAsync(captureCts.Token), item,
                    expectedPosition, label + "采集中");
            }
            StaticPointSamples result = await captureTask;
            VerifyAtPosition(await motion.ReadStageAsync(ct), item, expectedPosition, label + "结束后");
            return result;
        }
        catch
        {
            captureCts.Cancel();
            try { await captureTask; } catch { /* preserve the first failure */ }
            throw;
        }
    }

    private static void VerifyIdentity(IStaticAngleHardware host, ICt10DynamicHardware motion,
        string uid, CalibrationRun calibration)
    {
        if (!string.Equals(host.CurrentIdentity?.UidHex, uid, StringComparison.OrdinalIgnoreCase) ||
            !string.Equals(motion.CurrentUidHex, uid, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("CT-27测试期间IMU完整UID发生变化");
        VerifyFrozenHashes(calibration);
    }

    private static void VerifyFrozenHashes(CalibrationRun calibration)
    {
        foreach (CalibrationSource source in calibration.Sources)
        {
            if (!File.Exists(source.FilePath) ||
                !Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(source.FilePath)))
                    .Equals(source.Sha256, StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("CT-27测试期间标定文件被修改或移动：" + source.FilePath);
        }
    }

    private static void VerifyStationary(Ct10StageStatus stage, string label)
    {
        if (!stage.InnerEnabled || !stage.OuterEnabled || !stage.InnerNormal || !stage.OuterNormal ||
            !stage.InnerStationary || !stage.OuterStationary ||
            !double.IsFinite(stage.InnerPositionDeg) || !double.IsFinite(stage.OuterPositionDeg))
            throw new IOException($"CT-27{label}：2TD双轴未使能、未静止或状态异常：{stage.Detail}");
    }

    private static void EnsureApproved(Ct10StageStatus stage, Ct27Settings settings)
    {
        if (stage.InnerPositionDeg < settings.ApprovedMinDeg || stage.InnerPositionDeg > settings.ApprovedMaxDeg ||
            stage.OuterPositionDeg < settings.ApprovedMinDeg || stage.OuterPositionDeg > settings.ApprovedMaxDeg)
            throw new IOException("CT-27初始转台位置超出已批准行程");
    }

    private static void VerifyAtPosition(Ct10StageStatus stage, Ct27PlanItem item,
        double expectedTarget, string label)
    {
        VerifyStationary(stage, label);
        double target = item.Axis == Ct10Axis.Inner ? stage.InnerPositionDeg : stage.OuterPositionDeg;
        double other = item.Axis == Ct10Axis.Inner ? stage.OuterPositionDeg : stage.InnerPositionDeg;
        if (Math.Abs(target - expectedTarget) > 0.5 || Math.Abs(other) > 0.5)
            throw new IOException($"CT-27{label}：目标轴未停在{expectedTarget:F2}°或非测试轴未保持0°");
    }

    private static void VerifyPhysicalCsvScale(string file, int expectedGyroFs)
    {
        if (!Asm330Codec.TryGyroMdps(expectedGyroFs, out double mdps))
            throw new InvalidDataException("CT-27当前Gyro JSON输入量程不受支持：" + expectedGyroFs);
        using var reader = new StreamReader(file);
        string[] columns = (reader.ReadLine()?.TrimStart('\uFEFF') ?? string.Empty).Split(',');
        foreach (string field in new[]
        {
            "gx_dps", "gy_dps", "gz_dps", "raw_gx", "raw_gy", "raw_gz",
            "gyro_input_fs_dps", "input_scale_source"
        })
            if (!columns.Contains(field, StringComparer.Ordinal))
                throw new InvalidDataException("CT-27静态物理量CSV缺少字段：" + field);
        int fsIndex = Array.IndexOf(columns, "gyro_input_fs_dps");
        int sourceIndex = Array.IndexOf(columns, "input_scale_source");
        string[] physicalFields = new[] { "gx_dps", "gy_dps", "gz_dps" };
        string[] rawFields = new[] { "raw_gx", "raw_gy", "raw_gz" };
        int[] physicalIndices = physicalFields.Select(x => Array.IndexOf(columns, x)).ToArray();
        int[] rawIndices = rawFields.Select(x => Array.IndexOf(columns, x)).ToArray();
        string? line;
        int count = 0;
        while ((line = reader.ReadLine()) is not null)
        {
            if (string.IsNullOrWhiteSpace(line)) continue;
            string[] cells = line.Split(',');
            if (cells.Length < columns.Length ||
                !int.TryParse(cells[fsIndex], NumberStyles.Integer, CultureInfo.InvariantCulture, out int fs) ||
                fs != expectedGyroFs || !string.Equals(cells[sourceIndex], "UID_JSON", StringComparison.Ordinal))
                throw new InvalidDataException("CT-27静态FIFO未严格使用当前UID常温Gyro JSON输入量程");
            for (int axis = 0; axis < 3; axis++)
            {
                if (!int.TryParse(cells[rawIndices[axis]], NumberStyles.Integer, CultureInfo.InvariantCulture, out int raw) ||
                    !double.TryParse(cells[physicalIndices[axis]], NumberStyles.Float, CultureInfo.InvariantCulture, out double physical) ||
                    Math.Abs(physical - raw * mdps / 1000d) > 1e-9)
                    throw new InvalidDataException("CT-27静态FIFO三轴物理量与Gyro JSON输入量程不一致；禁止继续分析");
            }
            count++;
        }
        if (count == 0) throw new InvalidDataException("CT-27静态物理量CSV没有有效采样行");
    }
}
