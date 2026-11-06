using System.IO;
using Dts.Core;
using Dts.Tests.S1.CT10;

namespace Dts.Tests.S1.CT23;

/// <summary>Frozen UI request. Only outer-axis sweeps are currently supported by the verified CT10 bridge.</summary>
public sealed record Ct23Settings(
    string OutputRoot, string TrajectoriesText, double MotionSpeedDps,
    double SetupSpeedDps, int Repetitions, double SettleSeconds,
    double StaticCaptureSeconds, int MinStaticFrames, int MinDynamicFrames,
    double MaxGyroGapSeconds, double MaxStartEndClockSkewSeconds,
    double AllowedMinDeg, double AllowedMaxDeg, double PositionToleranceDeg,
    double MaxEncoderGyroAngleDiscrepancyDeg,
    bool SafetyApproved, bool EmergencyStopConfirmed,
    bool AccGyroAxesVerified, CalibrationRun Calibration);

public sealed record Ct23Plan(int Index, int TrajectoryIndex, int Repetition,
    double OuterStartDeg, double OuterEndDeg, double SpeedDps);

public sealed record Ct23SettingsSnapshot(string Trajectories, double SpeedDps,
    double SetupSpeedDps, int Repetitions, double SettleSeconds,
    double StaticCaptureSeconds, int MinStaticFrames, int MinDynamicFrames,
    double MaxGyroGapSeconds, double MaxStartEndClockSkewSeconds,
    double AllowedMinDeg, double AllowedMaxDeg, double PositionToleranceDeg,
    double MaxEncoderGyroAngleDiscrepancyDeg);

public sealed record Ct23TracePoint(double TimeSeconds, long HostTicks,
    double GyroXCorrectedDps, double GyroYCorrectedDps, double GyroZCorrectedDps,
    double PredictedGravityX, double PredictedGravityY, double PredictedGravityZ,
    double TemperatureC, short? RawGyroX, short? RawGyroY, short? RawGyroZ);

public sealed record Ct23Trial(
    int Index, int TrajectoryIndex, int Repetition, double OuterStartCommandDeg,
    double OuterEndCommandDeg, double OuterStartActualDeg, double OuterEndActualDeg,
    double[] AccStartG, double[] AccEndG, double[] GyroPropagatedGravityG,
    double[] StartReferenceGravityG, double[] EndReferenceGravityG,
    double ClosureAngleDeg, double StartReferenceErrorDeg, double EndReferenceErrorDeg,
    double EncoderTravelDeg, double IntegratedGyroXDeg,
    double IntegratedGyroMagnitudeDeg, double XAxisVsEncoderDifferenceDeg,
    double DynamicDurationSeconds, double MaxGyroGapSeconds,
    int StaticStartFrames, int StaticEndFrames, int DynamicFrames,
    double MeanTemperatureC, double StartEncoderGravityNonParallelDeg,
    string StaticStartCsv, string StaticEndCsv, string GyroTraceCsv, string EncoderCsv,
    string DynamicSourceNotes, string TimeQualityNotes, string RawDynamicGyroCsv = "");

public sealed record Ct23Metrics(int CompletedTrajectories,int CompletedTrials,
    double ClosureRmsDeg, double ClosureMaxDeg, double ClosureMeanDeg,
    double MeanStartReferenceDeg, double MeanEndReferenceDeg,
    double GyroVsEncoderRmsDeg,
    string Observability, string Conclusion);

public sealed record Ct23ReportData(
    string TestId, string TestName, string DeviceNumber, string UidHex,
    string StartedUtc, string FinishedUtc, string State, string FailureReason,
    string Conclusion, int GravitySign, Ct23SettingsSnapshot Settings,
    string AccFile, string AccSha256, string GyroFile, string GyroSha256,
    string ReferenceModel, string DynamicAdapterDescription,
    IReadOnlyList<Ct23Plan> Plan, IReadOnlyList<Ct23Trial> Trials,
    Ct23Metrics? Metrics, string Limitations);
