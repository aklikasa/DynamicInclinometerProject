using Dts.TestEngine;

namespace Dts.Tests.S1;

/// <summary>CT-09：真实 IMU 采集子项，当前不是完整产品级验收。</summary>
public sealed class CT_09_Test : TestModuleBase
{
    public override string TestId => "CT-09";
    public override bool IsExecutable => true;
    public override bool RequiresStaticBench => true;
    public override string ImplementationNote => "真实设备子项：GYRO 单姿态原始零速诊断子项；无产品 PASS 结论。";

    public override async Task<TestExecutionResult> ExecuteAsync(TestExecutionContext context, CancellationToken ct)
    {
        var capture = await context.Hardware.CaptureStaticImuAsync(
            TestId, context.Duration, true, context.Progress, ct);
        string[] files = capture.AnalysisFile is { } analysis
            ? [capture.CsvFile, capture.ManifestFile, analysis]
            : [capture.CsvFile, capture.ManifestFile];
        return new TestExecutionResult(TestId, TestOutcome.DiagnosticOnly,
            "已完成单姿态原始零速统计；尚未验证标定矩阵零偏残差与多姿态相关性。", capture, files);
    }
}
