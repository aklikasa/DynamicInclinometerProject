using Dts.Core;

namespace Dts.Tests.S1.CT04;

/// <summary>CT-04 独立参数快照。窗口一次确认后自动执行，无逐点人工输入。</summary>
public sealed record Ct04Settings(
    string OutputRoot,
    string PlanKind,
    double SpeedDps,
    double SettleSeconds,
    double SampleSeconds,
    double PositionToleranceDeg,
    double AllowedMinDeg,
    double AllowedMaxDeg,
    int MinValidSamples,
    double MaxOutlierFraction,
    bool FullRangeApproved,
    bool DirectionAndCablingApproved,
    bool HardwareSafetyConfirmed,
    int InnerDivisions,
    int OuterDivisions,
    double InnerStartDeg,
    double OuterStartDeg,
    CalibrationRun Calibration);

public sealed record Ct04Pose(int Index, double InnerTargetDeg, double OuterTargetDeg, string Label);

public sealed record Ct04PointResult(
    int Index,
    string Label,
    double InnerCommandDeg,
    double OuterCommandDeg,
    double InnerActualDeg,
    double OuterActualDeg,
    double[] ReferenceG,
    double[] RawMeanG,
    double[] CorrectedMeanG,
    double[] AxisErrorG,
    double[] CorrectedStdG,
    double VectorErrorG,
    double DirectionErrorDeg,
    double NormG,
    double NormErrorG,
    int TotalSamples,
    int AcceptedSamples,
    double RejectedFraction,
    int Batches,
    int DuplicateBatches,
    double MeanTemperatureC,
    string RawCsv,
    string CorrectedCsv,
    DateTimeOffset StartedUtc,
    DateTimeOffset EndedUtc);

public sealed record Ct04Metrics(
    int CompletedPoints,
    int SampleCount,
    double[] AxisBiasG,
    double[] AxisRmseG,
    double[] AxisMaxAbsG,
    double VectorRmseG,
    double VectorMaxG,
    double DirectionRmseDeg,
    double DirectionMaxDeg,
    double NormRmseG,
    double NormMaxAbsG,
    double TemperatureMinC,
    double TemperatureMaxC);

public sealed record Ct04ReportData(
    string TestId,
    string TestName,
    string Stage,
    string DeviceNumber,
    string UidHex,
    string StartedUtc,
    string FinishedUtc,
    string State,
    string FailureReason,
    string Conclusion,
    string ReferenceModel,
    int GravitySign,
    string AccJsonFile,
    string AccJsonSha256,
    string GyroJsonFile,
    string GyroJsonSha256,
    string InputScaleDescription,
    Ct04SettingsSnapshot Settings,
    IReadOnlyList<Ct04PointResult> Points,
    Ct04Metrics? Metrics,
    string MotionSafetyNote,
    int PlannedUniqueGravityDirections,
    int? HistoricalGravityOverlaps,
    IReadOnlyList<Ct04PairResult> Pairs,
    IReadOnlyList<Ct04NonlinearityProxy> Nonlinearity);

/// <summary>报告配置不直接序列化 CalibrationRun 的复杂对象。</summary>
public sealed record Ct04SettingsSnapshot(
    string PlanKind,
    double SpeedDps,
    double SettleSeconds,
    double SampleSeconds,
    double PositionToleranceDeg,
    double AllowedMinDeg,
    double AllowedMaxDeg,
    int MinValidSamples,
    double MaxOutlierFraction,
    bool FullRangeApproved,
    bool DirectionAndCablingApproved,
    int InnerDivisions,
    int OuterDivisions,
    double InnerStartDeg,
    double OuterStartDeg);

/// <summary>对向 ±g 反对称/对称分量；偶分量可用于诊断零偏残差。</summary>
public sealed record Ct04PairResult(int PairNumber, int PositivePoint, int NegativePoint,
    double[] ReferencePositiveG, double[] EvenComponentG, double EvenNormMg,
    double[] OddResponseErrorG, double OddErrorNormMg, double TemperatureDifferenceC);

/// <summary>不同静态姿态的单轴分量二次拟合代理；非完整多幅值非线性检定。</summary>
public sealed record Ct04NonlinearityProxy(string Axis, int PointCount,
    double MinReferenceG, double MaxReferenceG, double QuadraticCoefficientGPerG2,
    double MaxDeviationFromLinearMg, double RmsDeviationFromLinearMg);
