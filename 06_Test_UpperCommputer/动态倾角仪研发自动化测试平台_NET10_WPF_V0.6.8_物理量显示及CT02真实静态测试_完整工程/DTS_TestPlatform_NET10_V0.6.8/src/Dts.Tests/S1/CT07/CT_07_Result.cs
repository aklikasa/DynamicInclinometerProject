using Dts.Core;

namespace Dts.Tests.S1.CT07;

/// <summary>Frozen before any movement. Every visit leaves and re-enters the SAME target posture.</summary>
public sealed record Ct07Settings(
    string OutputRoot, double InnerTargetDeg, double OuterTargetDeg,
    double InnerExcursionDeg, double OuterExcursionDeg, int RepeatCount,
    bool AlternateApproach, double SpeedDps, double SettleSeconds,
    double SampleSeconds, double PositionToleranceDeg,
    double AllowedMinDeg, double AllowedMaxDeg,
    int MinValidSamples, double MaxOutlierFraction,
    bool DirectionAndCablingApproved, bool HardwareSafetyConfirmed,
    CalibrationRun Calibration);

public sealed record Ct07Pose(int Index, double InnerDepartDeg, double OuterDepartDeg,
    double InnerReturnDeg, double OuterReturnDeg, string Approach);

public sealed record Ct07Visit(
    int Index, string Approach, double InnerDepartDeg, double OuterDepartDeg,
    double InnerTargetDeg, double OuterTargetDeg,
    double InnerActualDeg, double OuterActualDeg,
    double[] ReferenceG, double[] AccCorrectedMeanG, double[] AccWithinStdG,
    double[] GyroCorrectedMeanDps, double[] GyroWithinStdDps,
    double VectorReferenceErrorMg, double DirectionReferenceErrorDeg,
    double AccNormG, double MeanTemperatureC, int TotalSamples, int AcceptedSamples,
    double RejectedFraction, int Batches, int DuplicateBatches,
    string PhysicalCsv, string CorrectedCsv, DateTimeOffset StartedUtc, DateTimeOffset EndedUtc);

/// <summary>Between-visit repeatability is separated from within-visit noise and machine return spread.</summary>
public sealed record Ct07Metrics(
    int Visits, int AcceptedFrames, double[] AccBetweenStdMg,
    double AccBetweenVectorRmsMg, double AccBetweenMaxVectorMg,
    double DirectionBetweenRmsDeg, double DirectionBetweenMaxDeg,
    double[] AccPooledWithinStdMg,
    double[] GyroBetweenStdDps, double[] GyroPooledWithinStdDps,
    double InnerReturnStdDeg, double OuterReturnStdDeg,
    double InnerReturnMaxDeviationDeg, double OuterReturnMaxDeviationDeg,
    double MeanReferenceErrorMg, double MaxReferenceErrorMg,
    double TemperatureMinC, double TemperatureMaxC);

public sealed record Ct07SettingsSnapshot(
    double InnerTargetDeg, double OuterTargetDeg, double InnerExcursionDeg,
    double OuterExcursionDeg, int RepeatCount, bool AlternateApproach,
    double SpeedDps, double SettleSeconds, double SampleSeconds,
    double PositionToleranceDeg, double AllowedMinDeg, double AllowedMaxDeg,
    int MinValidSamples, double MaxOutlierFraction,
    bool DirectionAndCablingApproved);

public sealed record Ct07ReportData(
    string TestId, string TestName, string Stage, string DeviceNumber,
    string UidHex, string StartedUtc, string FinishedUtc, string State,
    string FailureReason, string Conclusion, int GravitySign,
    string ReferenceModel, string AccJsonFile, string AccJsonSha256,
    string GyroJsonFile, string GyroJsonSha256, string InputScaleDescription,
    Ct07SettingsSnapshot Settings, IReadOnlyList<Ct07Visit> Visits,
    Ct07Metrics? Metrics, string MeasurementCaveat);
