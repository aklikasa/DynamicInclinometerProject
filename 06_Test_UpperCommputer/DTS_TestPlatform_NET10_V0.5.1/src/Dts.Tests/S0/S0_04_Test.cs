using Dts.TestEngine;

namespace Dts.Tests.S0;

/// <summary>S0-04：真实 IMU 采集子项，当前不是完整产品级验收。</summary>
public sealed class S0_04_Test : TestModuleBase
{
    public override string TestId => "S0-04";
    public override bool IsExecutable => true;
    public override bool RequiresStaticBench => true;
    public override string ImplementationNote => "真实设备子项：GYRO 原始零速数据实际采集；无产品 PASS 结论。";

    public override async Task<TestExecutionResult> ExecuteAsync(TestExecutionContext context, CancellationToken ct)
    {
        var capture = await context.Hardware.CaptureStaticImuAsync(
            TestId, context.Duration, false, context.Progress, ct);
        string[] files = capture.AnalysisFile is { } analysis
            ? [capture.CsvFile, capture.ManifestFile, analysis]
            : [capture.CsvFile, capture.ManifestFile];
        return new TestExecutionResult(TestId, TestOutcome.DiagnosticOnly,
            "仅完成真实采样；不等于陀螺仪零偏校准通过。", capture, files);
    }
}
