using System.Diagnostics;
using Dts.Core;

namespace Dts.Tests.S1.CT10;

public enum Ct10Axis { Inner = 0, Outer = 2 }
public enum Ct10Direction { Forward = 1, Reverse = -1 }

/// <summary>
/// Critical integration seam: the existing V0.6.8 IStaticAngleHardware is NOT a synchronized
/// in-motion data source. The host must supply a real, tested implementation of this contract.
/// All timestamps MUST come from Stopwatch.GetTimestamp in the SAME host process/timebase.
/// An adapter may NOT fabricate timestamped frames or feedback from commanded motion.
/// </summary>
public interface ICt10DynamicHardware
{
    bool IsRealDynamicCaptureReady { get; }
    string HardwareSourceDescription { get; }
    string CurrentUidHex { get; }
    double MaximumCertifiedSpeedDps(Ct10Axis axis);
    Task<Ct10StageStatus> ReadStageAsync(CancellationToken ct);
    /// <summary>Safe absolute approach: stationary second axis zeroed, never an implicit short-way wrap.</summary>
    Task MoveToSafeStartAsync(Ct10Axis axis, double startDeg, double speedDps,
        double allowedMinDeg, double allowedMaxDeg, CancellationToken ct);
    /// <summary>
    /// MUST subscribe to real IMU and encoder telemetry BEFORE dispatching the real motion command.
    /// Returns actual time-stamped raw/count + physical-input Gyro samples and raw encoder positions.
    /// Capture both start/stop transients for later rejection; don't trim inside the device adapter.
    /// </summary>
    Task<Ct10Capture> ExecuteSynchronizedSweepAsync(Ct10SweepRequest request,
        IProgress<string>? progress, CancellationToken ct);
    Task StopBothAxesAsync(CancellationToken ct);
}

public sealed record Ct10StageStatus(
    long TimestampTicks, double InnerPositionDeg, double OuterPositionDeg,
    bool InnerEnabled, bool OuterEnabled, bool InnerNormal, bool OuterNormal,
    bool InnerStationary, bool OuterStationary, string Detail);

public sealed record Ct10GyroFrame(
    long TimestampTicks, double InputX_Dps, double InputY_Dps, double InputZ_Dps,
    double TemperatureC, short? RawCountX, short? RawCountY, short? RawCountZ);
public sealed record Ct10EncoderFrame(
    long TimestampTicks, double InnerDeg, double OuterDeg, bool InnerNormal, bool OuterNormal,
    bool InnerEnabled, bool OuterEnabled);
public sealed record Ct10Capture(
    string FullUidHex, string DataSource, long TimestampFrequency,
    int GyroCalibrationInputFullScaleDps,
    IReadOnlyList<Ct10GyroFrame> GyroFrames,
    IReadOnlyList<Ct10EncoderFrame> EncoderFrames,
    bool MotionCompletedNormally,
    string HardwareNotes);

public sealed record Ct10SweepRequest(
    Ct10Axis Axis, Ct10Direction Direction, int Repetition, double CommandDps,
    double StartDeg, double EndDeg, double OtherAxisHoldDeg,
    double AllowedMinDeg, double AllowedMaxDeg, double SafetyTimeoutSeconds);

public sealed record Ct10Settings(
    string OutputRoot, string SpeedsCsv, bool TestInner, bool TestOuter,
    int Repetitions, double TravelMinDeg, double TravelMaxDeg,
    double ApprovedMinDeg, double ApprovedMaxDeg, double SetupSpeedDps, double SettleSeconds, double SpeedToleranceFraction,
    double EncoderDerivativeWindowSeconds, int MinAcceptedFrames,
    int InnerGyroSign, int OuterGyroSign, bool MotionAndCablingApproved,
    bool EmergencyStopConfirmed, bool SensorAxisMappingVerified,
    CalibrationRun Calibration);

public sealed record Ct10SettingsSnapshot(
    string SpeedsCsv, bool TestInner, bool TestOuter, int Repetitions,
    double TravelMinDeg, double TravelMaxDeg,
    double ApprovedMinDeg, double ApprovedMaxDeg, double SetupSpeedDps,
    double SettleSeconds, double SpeedToleranceFraction,
    double EncoderDerivativeWindowSeconds, int MinAcceptedFrames,
    int InnerGyroSign, int OuterGyroSign);

public sealed record Ct10MatchedFrame(
    long TimestampTicks, double TimeSeconds, double ReferenceRateDps,
    double CommandedRateDps, double GyroAxisMeasuredDps,
    double ResidualDps, double GyroXCorrectedDps,
    double GyroYCorrectedDps, double GyroZCorrectedDps,
    double TemperatureC, double AxisEncoderDeg,
    bool Accepted, string RejectionReason);

public sealed record Ct10SweepResult(
    Ct10Axis Axis, Ct10Direction Direction, int Repetition,
    double CommandSpeedDps, double StartDeg, double EndDeg,
    int TotalGyroFrames, int AcceptedFrames, int EncoderFrames,
    double MeanReferenceSignedDps, double MeanGyroSignedDps,
    double MeanResidualDps, double ResidualRmseDps, double ResidualStdDps,
    double ScaleRatioPercent, double MeanTemperatureC,
    string CsvFile, string EvidenceSource, IReadOnlyList<Ct10MatchedFrame> Samples);

public sealed record Ct10SpeedPairResult(
    Ct10Axis Axis, double SpeedDps, int PairCount,
    double ForwardMeanResidualDps, double ReverseMeanResidualDps,
    double SignedDirectionDifferenceDps, double ForwardMeanRatioPercent,
    double ReverseMeanRatioPercent,
    double MeanResidualRmseDps);

public sealed record Ct10ReportData(
    string TestId, string UidHex, string StartedUtc, string FinishedUtc,
    string State, string FailureReason, string Conclusion,
    Ct10SettingsSnapshot Settings, string GyroJsonPath, string GyroJsonSha256,
    string AccJsonPath, string AccJsonSha256,
    int GyroInputFullScaleDps, string DynamicAdapterDescription,
    IReadOnlyList<Ct10SweepResult> Sweeps,
    IReadOnlyList<Ct10SpeedPairResult> SpeedPairs,
    string SafetyAndUncertaintyNotes);
