using Dts.Core;

namespace Dts.Tests.S1.CT09;

public sealed record Ct09Pose(int Index, double InnerDeg, double OuterDeg);

public sealed record Ct09Settings(
    string OutputRoot, IReadOnlyList<Ct09Pose> Poses, int RepeatsPerPose,
    double MotionSpeedDps, double SettleSeconds, double SampleSeconds,
    double PositionToleranceDeg, double AllowedMinDeg, double AllowedMaxDeg,
    int MinValidSamples, double MaxOutlierFraction,
    bool DirectionAndCablingApproved, bool HardwareSafetyConfirmed,
    CalibrationRun Calibration);

public sealed record Ct09SettingsSnapshot(
    IReadOnlyList<Ct09Pose> Poses, int RepeatsPerPose, double MotionSpeedDps,
    double SettleSeconds, double SampleSeconds, double PositionToleranceDeg,
    double AllowedMinDeg, double AllowedMaxDeg, int MinValidSamples,
    double MaxOutlierFraction);

public sealed record Ct09Visit(
    int Index, int PoseIndex, int Repeat, double InnerTargetDeg, double OuterTargetDeg,
    double InnerActualDeg, double OuterActualDeg,
    double[] GyroCorrectedMeanDps, double[] GyroWithinStdDps,
    double ZeroRateNormDps, double? MeanTemperatureC,
    int TotalSamples, int AcceptedSamples, double RejectedFraction,
    string PhysicalCsv, string CorrectedCsv,
    DateTimeOffset StartedUtc, DateTimeOffset EndedUtc);

public sealed record Ct09PoseSummary(
    int PoseIndex, double InnerDeg, double OuterDeg, int Runs,
    double[] MeanGyroDps, double?[] BetweenRunStdDps,
    double ZeroRateNormDps, double? MeanTemperatureC);

public sealed record Ct09Metrics(
    int Poses, int Visits, int AcceptedFrames,
    double[] GrandMeanGyroDps, double[] PoseMeanRangeDps,
    double[] PooledWithinPoseStdDps,
    double MaxPoseMeanVectorDifferenceDps,
    double MaxPoseZeroRateNormDps,
    double? TemperatureMinC, double? TemperatureMaxC,
    IReadOnlyList<Ct09PoseSummary> PoseSummaries);

public sealed record Ct09ReportData(
    string TestId, string TestName, string DeviceNumber, string UidHex,
    DateTimeOffset StartedUtc, DateTimeOffset FinishedUtc,
    string State, string FailureReason,
    string GyroJsonFile, string GyroJsonSha256, int GyroFsHint,
    string InputScaleDescription, Ct09SettingsSnapshot Settings,
    IReadOnlyList<Ct09Visit> Visits, Ct09Metrics? Metrics,
    string MeasurementCaveat);
