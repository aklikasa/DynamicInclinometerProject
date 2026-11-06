using Dts.Core;

namespace Dts.Tests.S1.CT06;

/// <summary>CT-06 参数快照：一次确认、自动双轴复合姿态扫描。</summary>
public sealed record Ct06Settings(
    string OutputRoot, string PlanKind, double SpeedDps,
    double SettleSeconds, double SampleSeconds, double PositionToleranceDeg,
    double AllowedMinDeg, double AllowedMaxDeg, int MinValidSamples,
    double MaxOutlierFraction, bool FullRangeApproved,
    bool DirectionAndCablingApproved, bool HardwareSafetyConfirmed,
    int InnerDivisions, int OuterDivisions,
    double InnerStartDeg, double OuterStartDeg, CalibrationRun Calibration);

public sealed record Ct06Pose(int Index, double InnerTargetDeg, double OuterTargetDeg, string Label);

public sealed record Ct06PointResult(
    int Index, string Label,
    double InnerCommandDeg, double OuterCommandDeg,
    double InnerActualDeg, double OuterActualDeg,
    double[] ReferenceG, double[] RawMeanG, double[] CorrectedMeanG,
    double[] AxisErrorG, double[] CorrectedStdG,
    double VectorErrorG, double DirectionErrorDeg, double NormG, double NormErrorG,
    int TotalSamples, int AcceptedSamples, double RejectedFraction,
    int Batches, int DuplicateBatches, double MeanTemperatureC,
    string RawCsv, string CorrectedCsv, DateTimeOffset StartedUtc, DateTimeOffset EndedUtc);

public sealed record Ct06Metrics(
    int CompletedPoints, int SampleCount,
    double[] AxisBiasG, double[] AxisRmseG, double[] AxisMaxAbsG,
    double VectorRmseG, double VectorMaxG,
    double DirectionRmseDeg, double DirectionMaxDeg,
    double NormRmseG, double NormMaxAbsG,
    double TemperatureMinC, double TemperatureMaxC,
    double TransverseRmseMg, double TransverseMaxMg,
    double ParallelRmseMg);

/// <summary>e = b + B*g_ref；B非对角为复合姿态残余轴间耦合代理，非单独芯片固有交叉轴标定。</summary>
public sealed record Ct06CouplingFit(
    int PointCount, double[] BiasG, double[][] ResidualMatrix,
    double FitRmseMg, double MaxOffDiagonalPercent,
    double[] OffDiagonalPercent, double[] AxisResidualRmseMg);

public sealed record Ct06ReportData(
    string TestId, string TestName, string Stage, string DeviceNumber,
    string UidHex, string StartedUtc, string FinishedUtc, string State,
    string FailureReason, string Conclusion, string ReferenceModel,
    int GravitySign, string AccJsonFile, string AccJsonSha256,
    string GyroJsonFile, string GyroJsonSha256, string InputScaleDescription,
    Ct06SettingsSnapshot Settings, IReadOnlyList<Ct06PointResult> Points,
    Ct06Metrics? Metrics, string MotionSafetyNote,
    int PlannedUniqueGravityDirections, int? HistoricalGravityOverlaps,
    Ct06CouplingFit? CouplingFit);

public sealed record Ct06SettingsSnapshot(
    string PlanKind, double SpeedDps, double SettleSeconds, double SampleSeconds,
    double PositionToleranceDeg, double AllowedMinDeg, double AllowedMaxDeg,
    int MinValidSamples, double MaxOutlierFraction, bool FullRangeApproved,
    bool DirectionAndCablingApproved, int InnerDivisions, int OuterDivisions,
    double InnerStartDeg, double OuterStartDeg);
