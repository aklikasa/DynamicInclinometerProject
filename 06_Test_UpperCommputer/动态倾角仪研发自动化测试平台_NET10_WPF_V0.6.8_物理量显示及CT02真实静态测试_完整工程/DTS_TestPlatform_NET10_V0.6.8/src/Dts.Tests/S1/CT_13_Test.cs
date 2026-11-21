using Dts.TestEngine;
using Dts.Tests.S1.CT13;

namespace Dts.Tests.S1;

/// <summary>CT-13 V1.1: operator-assisted power-cycle repeatability using the existing V0.6.8 static hardware session.</summary>
// CT13_MODULE_V1.1 - compatible with the existing V0.6.8 static hardware session.
public sealed class CT_13_Test : TestModuleBase
{
    public override string TestId => "CT-13";
    public override bool IsExecutable => true;
    public override bool RequiresStaticBench => true;
    public override string Purpose => "在固定静态姿态下，通过人工断电/重新上电，评价多次启动后的六轴输出复现性。";
    public override string Procedure => "人工断电→重新上电并由主程序重新连接→核对完整UID→精度测试连接核验→按设定等待→真实FIFO采集→重复多轮→归档报告。";
    public override string Priority => "P0";
    public override string ImplementationNote => "复用主程序 IStaticAngleHardware / CaptureStaticImuAsync；供电由人工控制；每轮重新核验UID；仅输出研发诊断，不自动判PASS。";

    public override async Task<TestExecutionResult> ExecuteAsync(TestExecutionContext context, CancellationToken ct)
    {
        if (context.Parameters is not Ct13Settings settings)
            throw new InvalidOperationException("CT-13缺少专用窗口参数。");
        if (context.Hardware is not IStaticAngleHardware hardware)
            throw new InvalidOperationException("当前主程序硬件会话不支持CT-13所需的静态精度连接核验接口。");

        ValidateIdentity(hardware.CurrentIdentity, settings);
        if (settings.CaptureSeconds is < 5 or > 1800)
            throw new ArgumentOutOfRangeException(nameof(settings.CaptureSeconds), "采集时长须为5～1800秒。");

        // Use the already-connected main-program hardware session; do not open a second COM session.
        await hardware.VerifyImuForPrecisionTestAsync(ct);
        var verifiedIdentity = hardware.CurrentIdentity;
        ValidateIdentity(verifiedIdentity, settings);

        context.Progress?.Report($"CT-13：UID及精度测试连接已核验，开始第{settings.CycleIndex}/{settings.TotalCycles}次上电周期采集。");
        var capture = await hardware.CaptureStaticImuAsync(
            "CT13_BOOT" + settings.CycleIndex.ToString("D2"),
            TimeSpan.FromSeconds(settings.CaptureSeconds), true, context.Progress, ct);

        if (!string.Equals(capture.UidHex, settings.ExpectedUidHex, StringComparison.OrdinalIgnoreCase) ||
            !string.Equals(capture.DeviceNumber, settings.ExpectedDeviceNumber, StringComparison.Ordinal))
            throw new InvalidDataException("采集结果中的设备UID与测试基准不一致，拒绝纳入统计。");
        if (capture.Samples <= 0)
            throw new InvalidDataException("本轮真实采集没有有效样本，拒绝计入完成轮次。");

        string[] outputs = capture.AnalysisFile is { } analysis
            ? [capture.CsvFile, capture.ManifestFile, analysis]
            : [capture.CsvFile, capture.ManifestFile];
        return new TestExecutionResult(TestId, TestOutcome.DiagnosticOnly,
            $"第{settings.CycleIndex}/{settings.TotalCycles}次上电周期采集完成；本轮{capture.Samples}帧。完成采集不代表产品合格。", capture, outputs);
    }

    private static void ValidateIdentity(Dts.Core.DeviceIdentity? identity, Ct13Settings settings)
    {
        if (identity is null)
            throw new InvalidOperationException("IMU未连接或尚未读取完整UID。请先在主程序重新连接设备。");
        if (string.IsNullOrWhiteSpace(settings.ExpectedUidHex) ||
            string.IsNullOrWhiteSpace(settings.ExpectedDeviceNumber))
            throw new InvalidDataException("CT-13测试基准UID或设备编号为空。");
        if (!string.Equals(identity.UidHex, settings.ExpectedUidHex, StringComparison.OrdinalIgnoreCase) ||
            !string.Equals(identity.DtsId, settings.ExpectedDeviceNumber, StringComparison.Ordinal))
            throw new InvalidDataException("当前设备身份与CT-13测试基准不一致。");
    }
}
