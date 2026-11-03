using Dts.Core;

namespace Dts.TestEngine;

/// <summary>一个测试编号对应一个实现 ITestModule 的 .cs 测试类。</summary>
public interface ITestModule
{
    string TestId { get; }
    string Stage { get; }
    string Name { get; }
    string Purpose { get; }
    string Procedure { get; }
    string Priority { get; }
    bool IsExecutable { get; }
    bool RequiresStaticBench { get; }
    string ImplementationNote { get; }
    Task<TestExecutionResult> ExecuteAsync(TestExecutionContext context, CancellationToken ct);
}

/// <summary>安全占位：未完成的测试无法被误认为已实现。</summary>
public abstract class TestModuleBase : ITestModule
{
    public abstract string TestId { get; }
    public virtual string Stage => TestId.StartsWith("CT-", StringComparison.OrdinalIgnoreCase)
        ? "S1" : TestId.Split('-')[0];
    public virtual string Name => TestId;
    public virtual string Purpose => "待完善测试目的";
    public virtual string Procedure => "待实现完整自动化测试流程";
    public virtual string Priority => "P1";
    public virtual bool IsExecutable => false;
    public virtual bool RequiresStaticBench => false;
    public virtual string ImplementationNote => "未实现。不得生成真实测试已完成或 PASS 结论。";
    public virtual Task<TestExecutionResult> ExecuteAsync(TestExecutionContext context, CancellationToken ct)
        => throw new NotSupportedException($"{TestId} 尚未实现完整或明确标注的实测子项目。请完善对应 .cs 文件后重新编译。");
}

/// <summary>统一由实际硬件层提供，不提供任何默认模拟实现。</summary>
public interface ITestHardware
{
    DeviceIdentity? CurrentIdentity { get; }
    Task<CaptureArtifacts> CaptureStaticImuAsync(string testId, TimeSpan duration,
        bool analyzeRawStatistics, IProgress<string>? progress, CancellationToken ct);
}

public sealed record CaptureArtifacts(
    string Folder, string CsvFile, string ManifestFile, string? AnalysisFile,
    int Samples, int Batches, string UidHex, string DeviceNumber);

public sealed record TestExecutionContext(
    TestDefinition Definition, TimeSpan Duration, ITestHardware Hardware,
    IProgress<string>? Progress, object? Parameters = null);

// Scientific test modules depend on interfaces, not the WPF window or vendor DLL.
public sealed record RealAxisFeedback(double PositionDeg, double SpeedDps,
    bool Normal, bool? Enabled, bool? InPlace, string Detail);
public sealed record RealTableFeedback(RealAxisFeedback Inner, RealAxisFeedback Outer, DateTimeOffset CapturedUtc);
public readonly record struct RealImuVector(double AxG,double AyG,double AzG,
    double GxDps,double GyDps,double GzDps,double TemperatureC=double.NaN);
public sealed record StaticPointSamples(string CsvPath, IReadOnlyList<RealImuVector> Samples,
    int Batches, DateTimeOffset StartedUtc, DateTimeOffset EndedUtc,
    int DuplicateBatches, double TemperatureC);

public interface IStaticAngleHardware : ITestHardware
{
    bool IsTwoTdConnected {get;}
    Task<RealTableFeedback> ReadTwoTdAsync(CancellationToken ct);
    Task SetTwoTdAbsoluteAsync(int axis, double targetDeg, double speedDps, CancellationToken ct);
    Task StopTwoTdBothAsync(CancellationToken ct);
    Task<StaticPointSamples> CaptureStaticPointAsync(string csvPath, TimeSpan duration,
        IProgress<string>? progress, CancellationToken ct);
}

public enum TestOutcome
{
    DiagnosticOnly,             // 原始数据/诊断子项完成，绝不等价于产品 PASS
    PendingAcceptance,          // 完整流程可能执行完，尚待判据评价
    Passed,
    Failed
}

/// <summary>产品级判定必须保留判据来源和参考设备信息；本版诊断子项均不会提供此证据。</summary>
public sealed record TestAcceptanceEvidence(
    string SpecificationId, string ReferenceInstrumentId, string MetricResultFile);

public sealed record TestExecutionResult(
    string TestId, TestOutcome Outcome, string Summary, CaptureArtifacts? Capture,
    IReadOnlyList<string> Files, TestAcceptanceEvidence? Acceptance = null);
