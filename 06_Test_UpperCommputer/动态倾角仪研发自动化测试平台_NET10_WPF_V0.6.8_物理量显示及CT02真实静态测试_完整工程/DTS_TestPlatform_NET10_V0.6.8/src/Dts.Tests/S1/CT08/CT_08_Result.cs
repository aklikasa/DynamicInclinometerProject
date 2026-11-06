using Dts.Core;

namespace Dts.Tests.S1.CT08;

// 外轴正反接近同一目标，内轴在一对测量内固定；不把相同机械目标误当成相同实际反馈。
public sealed record Ct08Settings(
    string OutputRoot, string InnerPositionsText, string OuterTargetsText,
    double ApproachOffsetDeg, int PairsPerTarget, double SpeedDps,
    double SettleSeconds, double SampleSeconds, double PositionToleranceDeg,
    double AllowedMinDeg, double AllowedMaxDeg, int MinValidSamples,
    double MaxOutlierFraction, bool DirectionAndCablingApproved,
    bool HardwareSafetyConfirmed, CalibrationRun Calibration);

public sealed record Ct08Pose(int Index, int PairIndex, int Cycle, string Side,
    double InnerTargetDeg, double OuterTargetDeg, double OuterDepartDeg);

public sealed record Ct08Visit(
    int Index, int PairIndex, int Cycle, string Side, double InnerTargetDeg,
    double OuterTargetDeg, double OuterDepartDeg, double InnerActualDeg,
    double OuterActualDeg, double[] ReferenceG, double[] AccCorrectedMeanG,
    double[] AccWithinStdG, double[] GyroCorrectedMeanDps,
    double[] GyroWithinStdDps, double[] AccErrorG,
    double ReferenceDirectionErrorDeg, double AccNormG, double MeanTemperatureC,
    int TotalSamples, int AcceptedSamples, double RejectedFraction,
    int Batches, int DuplicateBatches, string PhysicalCsv, string CorrectedCsv,
    DateTimeOffset StartedUtc, DateTimeOffset EndedUtc);

// “正”表示从目标下方的角度正向接近；“反”表示从上方角度反向接近。
public sealed record Ct08Pair(
    int PairIndex, int Cycle, double InnerTargetDeg, double OuterTargetDeg,
    int ForwardIndex, int ReverseIndex, double[] ForwardAccG, double[] ReverseAccG,
    double[] ForwardErrorG, double[] ReverseErrorG,
    double[] HysteresisErrorMg, double HysteresisMagnitudeMg,
    double DirectionHysteresisDeg, double OuterActualDifferenceDeg,
    double InnerActualDifferenceDeg, double TemperatureDifferenceC,
    double[] GyroZeroDifferenceDps);

public sealed record Ct08TargetSummary(double InnerDeg, double OuterDeg, int Pairs,
    double MeanMagnitudeMg, double RmsMagnitudeMg, double MaxMagnitudeMg,
    double MeanAngleHysteresisDeg, double MeanOuterFeedbackDeltaDeg);

public sealed record Ct08Metrics(int CompletedPairs, int CompletedVisits,
    int AcceptedFrames, double[] MeanSignedErrorDifferenceMg,
    double RmsHysteresisMg, double MaxHysteresisMg,
    double MeanDirectionHysteresisDeg, double MaxDirectionHysteresisDeg,
    double OuterFeedbackDifferenceRmsDeg, double InnerFeedbackDifferenceRmsDeg,
    double TemperatureMinC, double TemperatureMaxC,
    IReadOnlyList<Ct08TargetSummary> ByTarget);

public sealed record Ct08SettingsSnapshot(string InnerPositions, string OuterTargets,
    double ApproachOffsetDeg, int PairsPerTarget, double SpeedDps,
    double SettleSeconds, double SampleSeconds, double PositionToleranceDeg,
    double AllowedMinDeg, double AllowedMaxDeg, int MinValidSamples,
    double MaxOutlierFraction);

public sealed record Ct08ReportData(
    string TestId, string TestName, string Stage, string DeviceNumber, string UidHex,
    string StartedUtc, string FinishedUtc, string State, string FailureReason,
    string Conclusion, int GravitySign, string ReferenceModel,
    string AccJsonFile, string AccJsonSha256,
    string GyroJsonFile, string GyroJsonSha256, string InputScaleDescription,
    Ct08SettingsSnapshot Settings, IReadOnlyList<Ct08Pose> Plan,
    IReadOnlyList<Ct08Visit> Visits, IReadOnlyList<Ct08Pair> Pairs,
    Ct08Metrics? Metrics, string MeasurementCaveat);
