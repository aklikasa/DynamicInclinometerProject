using Dts.TestEngine;

namespace Dts.Tests.S1;

/// <summary>CT-12：真实 IMU 采集子项，当前不是完整产品级验收。</summary>
public sealed class CT_12_Test : TestModuleBase
{
    public override string TestId => "CT-12";
    public override bool IsExecutable => true;
    public override bool RequiresStaticBench => true;
    public override string ImplementationNote => "真实设备子项：静态原始六轴短期噪声统计子项；无产品 PASS 结论。";

    public override async Task<TestExecutionResult> ExecuteAsync(TestExecutionContext context, CancellationToken ct)
    {
        var capture = await context.Hardware.CaptureStaticImuAsync(
            TestId, context.Duration, true, context.Progress, ct);
        string[] files = capture.AnalysisFile is { } analysis
            ? [capture.CsvFile, capture.ManifestFile, analysis]
            : [capture.CsvFile, capture.ManifestFile];
        return new TestExecutionResult(TestId, TestOutcome.DiagnosticOnly,
            "已完成原始六轴短期噪声统计；未计算完整倾角噪声、长期漂移或验收指标。", capture, files);
    }
}
