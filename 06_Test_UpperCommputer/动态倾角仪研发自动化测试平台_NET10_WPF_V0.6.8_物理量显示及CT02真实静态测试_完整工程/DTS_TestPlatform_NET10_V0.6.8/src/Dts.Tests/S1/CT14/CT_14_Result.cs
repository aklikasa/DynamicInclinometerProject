using Dts.Core;

namespace Dts.Tests.S1.CT14;

public sealed record Ct14Pose(int Index, double InnerDeg, double OuterDeg);

public sealed record Ct14Settings(
    string OutputRoot, string SessionFolder, int MountIndex, int PlannedMounts, string MountingProcedureNote,
    IReadOnlyList<Ct14Pose> Poses, int RepeatsPerPose,
    double MotionSpeedDps, double WarmupSeconds, double SettleSeconds,
    double SampleSeconds, double PositionToleranceDeg,
    double AllowedMinDeg, double AllowedMaxDeg,
    int MinValidSamples, double MaxOutlierFraction,
    bool DirectionAndCablingApproved, bool HardwareSafetyConfirmed,
    CalibrationRun Calibration);

public sealed record Ct14SettingsSnapshot(
    int PlannedMounts, string MountingProcedureNote, IReadOnlyList<Ct14Pose> Poses, int RepeatsPerPose,
    double MotionSpeedDps, double WarmupSeconds, double SettleSeconds,
    double SampleSeconds, double PositionToleranceDeg,
    double AllowedMinDeg, double AllowedMaxDeg,
    int MinValidSamples, double MaxOutlierFraction);

public sealed record Ct14Visit(
    int MountIndex, int VisitIndex, int PoseIndex, int Repeat,
    double InnerTargetDeg, double OuterTargetDeg,
    double InnerActualDeg, double OuterActualDeg,
    double[] ReferenceG, double[] AccCorrectedMeanG, double[] AccWithinStdG,
    double[] GyroCorrectedMeanDps, double[] GyroWithinStdDps,
    double VectorReferenceErrorMg, double DirectionReferenceErrorDeg,
    double AccNormG, double MeanTemperatureC,
    int TotalSamples, int AcceptedSamples, double RejectedFraction,
    int Batches, int DuplicateBatches,
    string PhysicalCsv, string CorrectedCsv,
    DateTimeOffset StartedUtc, DateTimeOffset EndedUtc);

public sealed record Ct14MountPoseSummary(
    int MountIndex, int PoseIndex, double InnerDeg, double OuterDeg,
    int Repeats, double[] AccMeanG, double[] GyroMeanDps,
    double AccVectorNormG, double MeanTemperatureC);

public sealed record Ct14Metrics(
    int MountsWithData, int Poses, int Visits, int AcceptedFrames,
    double[] AccMountingStdMg, double AccMountingVectorRmsMg,
    double AccMountingVectorMaxMg, double AccMountingAngleRmsDeg,
    double[] GyroMountingStdDps,
    double[] AccWithinVisitPooledStdMg, double[] GyroWithinVisitPooledStdDps,
    double TemperatureMinC, double TemperatureMaxC,
    IReadOnlyList<Ct14MountPoseSummary> MountPoseSummaries);

public sealed record Ct14ReportData(
    string TestId, string TestName, string DeviceNumber, string UidHex, int MountIndex,
    DateTimeOffset StartedUtc, DateTimeOffset FinishedUtc,
    string State, string FailureReason, string Conclusion,
    string AccJsonFile, string AccJsonSha256,
    string GyroJsonFile, string GyroJsonSha256,
    int GravitySign, string ReferenceModel, string InputScaleDescription,
    Ct14SettingsSnapshot Settings, IReadOnlyList<Ct14Visit> Visits,
    Ct14Metrics? Metrics);
