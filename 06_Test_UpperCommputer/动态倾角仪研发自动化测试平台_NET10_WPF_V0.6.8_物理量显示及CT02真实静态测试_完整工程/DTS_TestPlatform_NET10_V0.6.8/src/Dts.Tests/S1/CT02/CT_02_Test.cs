using Dts.Core;
using Dts.TestEngine;
using Dts.Tests.S1.CT02;

namespace Dts.Tests.S1;

/// <summary>
/// CT-02: real stationary calibrated six-axis acquisition and residual analysis.
/// No motor movement, no invented reference angle, no product PASS.
/// </summary>
public sealed class CT_02_Test : TestModuleBase
{
    public override string TestId => "CT-02";
    public override bool IsExecutable => true;
    public override bool RequiresStaticBench => true;
    public override string ImplementationNote =>
        "CT-02单姿态真实静态子项：现场确认已知P系±Z重力参考及静止；计算Roll/Pitch零位和三轴陀螺仪零速。未实现自动重复定位；不自动判PASS。";

    public override async Task<TestExecutionResult> ExecuteAsync(TestExecutionContext context, CancellationToken ct)
    {
        if (context.Parameters is not Ct02Settings settings)
            throw new InvalidOperationException("CT-02 必须通过专用设置窗口确认静止与机械零位参考");
        if (!settings.MechanicalZeroConfirmed || !settings.StationarityConfirmed)
            throw new InvalidOperationException("CT-02 缺少真实工装调平/转台静止确认");
        if (settings.ReferenceGravityZSign is not (1 or -1))
            throw new InvalidOperationException("必须选择已知的公共机械P系重力参考方向：+Z 或 -Z");
        if (context.Duration < TimeSpan.FromSeconds(5) || context.Duration > TimeSpan.FromMinutes(30))
            throw new ArgumentOutOfRangeException(nameof(context.Duration), "CT-02 采样时长为5～1800秒");
        var identity = context.Hardware.CurrentIdentity ??
            throw new InvalidOperationException("没有连接真实IMU或未读取完整UID");
        var run = settings.Calibration;
        if (run.Mode != CalibrationMode.Ambient)
            throw new InvalidOperationException("CT-02 是常温标定后验证，主界面必须勾选常温标定");
        run.Validate(identity);
        if (run.Files?.Acc is null || run.Files.Gyro is null)
            throw new InvalidDataException("CT-02 必须具备同一UID的ACC和Gyro常温校正参数");
        context.Progress?.Report("CT-02：已确认静态参考，开始真实IMU六轴数据采集；不发送转台运动命令");
        var capture = await context.Hardware.CaptureStaticImuAsync(
            TestId, context.Duration, false, context.Progress, ct);
        if (!capture.UidHex.Equals(identity.UidHex, StringComparison.OrdinalIgnoreCase) ||
            capture.DeviceNumber != identity.DtsId)
            throw new InvalidDataException("采集记录UID与测试开始时的设备身份不一致");
        string selectedCsv = Path.Combine(capture.Folder, "imu_selected.csv");
        // The public capture adapter must have used this EXACT UID-matched run,
        // not another mode/file selected while the child window was open.
        using var manifestDoc = System.Text.Json.JsonDocument.Parse(
            await File.ReadAllTextAsync(capture.ManifestFile, ct));
        var manifest = manifestDoc.RootElement;
        if (manifest.GetProperty("processing_mode").GetString() != "AMBIENT" ||
            manifest.GetProperty("calibration_files").GetArrayLength() != 2)
            throw new InvalidDataException("CT-02 采集过程未使用两份常温标定文件");
        var recordedHashes = manifest.GetProperty("calibration_files").EnumerateArray()
            .Select(x => x.GetProperty("sha256").GetString() ?? "")
            .ToHashSet(StringComparer.OrdinalIgnoreCase);
        if (!recordedHashes.SetEquals(run.Sources.Select(x => x.Sha256)))
            throw new InvalidDataException("CT-02 采样时的标定参数与窗口冻结的JSON不一致，拒绝出具结果");
        var actualStarted = manifest.GetProperty("started_utc").GetString()
            ?? throw new InvalidDataException("采集清单缺少起始时刻");
        var actualEnded = manifest.GetProperty("ended_utc").GetString()
            ?? throw new InvalidDataException("采集清单缺少结束时刻");
        var metrics = await Ct02Algorithm.AnalyzeSelectedCsvAsync(selectedCsv,
            settings.ReferenceGravityZSign, ct);
        if (metrics.Samples != capture.Samples)
            throw new InvalidDataException("选定的常温补偿数据帧数与原始硬件采集帧数不一致");
        var sourceAcc = run.Files.Acc;
        var sourceGyro = run.Files.Gyro;
        var reference = settings.ReferenceGravityZSign > 0 ? "P系[0,0,+1]g" : "P系[0,0,-1]g";
        var summary = new Ct02ReportData(TestId, "S1", identity.DtsId, identity.UidHex,
            actualStarted, actualEnded,
            "REAL_SINGLE_POSE_PENDING_ACCEPTANCE", reference,
            "静置条件由操作者现场确认；分析所选流中的全部真实已校正帧，样本标准差为n-1；" +
            "仅为已知参考处的单姿态静态子项；未执行多次重新定位；参考水平误差未包含进本次测量结果",
            Path.GetFileName(sourceAcc.FilePath), sourceAcc.Sha256,
            Path.GetFileName(sourceGyro.FilePath), sourceGyro.Sha256,
            $"ACC={run.Files.Acc.FsHint}g；Gyro={run.Files.Gyro.FsHint}dps（以已选JSON拟合输入为准）",
            capture.CsvFile, selectedCsv, capture.ManifestFile, metrics);
        var reports = await Ct02Report.ExportAsync(capture.Folder, summary, ct);
        string[] files = [capture.CsvFile, selectedCsv, capture.ManifestFile, .. reports];
        context.Progress?.Report($"CT-02 已实采{metrics.Samples}帧；Roll={metrics.RollZeroDeg:F5}°，Pitch={metrics.PitchZeroDeg:F5}°，零速矢量={metrics.GyroZeroVectorNormDps:F5}°/s；待验收");
        return new TestExecutionResult(TestId, TestOutcome.PendingAcceptance,
            $"CT-02 单姿态真实静态子项完成 {metrics.Samples}帧；Roll零位 {metrics.RollZeroDeg:F5}°、Pitch零位 {metrics.PitchZeroDeg:F5}°、Gyro零速矢量 {metrics.GyroZeroVectorNormDps:F5}°/s；待人工验收。",
            capture, files);
    }
}
