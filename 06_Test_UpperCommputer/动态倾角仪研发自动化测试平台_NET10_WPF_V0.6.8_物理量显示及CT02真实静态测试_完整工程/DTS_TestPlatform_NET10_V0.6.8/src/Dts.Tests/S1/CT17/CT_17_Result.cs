using Dts.Core;
using Dts.Tests.S1.CT10;

namespace Dts.Tests.S1.CT17;

/// <summary>
/// Optional timing instrumentation implemented by the real CT10 adapter.
/// Stopwatch ticks share the same process clock as Ct10Capture's gyro/encoder timestamps.
/// </summary>
public interface ICt17TimingTelemetry
{
    TimeSpan Ct17PreMotionDwell { get; set; }
    long Ct17CommandCallStartTicks { get; }
    long Ct17CommandCallReturnTicks { get; }
    long Ct17TimestampFrequency { get; }
}

public sealed record Ct17Settings(
    CalibrationRun Calibration, string OutputRoot,
    double StaticCaptureSeconds, double ExpectedHostBatchHz, double HostRateTolerancePercent,
    double PreMotionDwellSeconds, double SettleSeconds,
    bool TestInner, bool TestOuter, int Repetitions,
    double CenterDeg, double AmplitudeDeg, double CommandSpeedDps, double SetupSpeedDps,
    double ApprovedMinDeg, double ApprovedMaxDeg,
    double EncoderDerivativeWindowSeconds, double MaxLagSearchMs,
    int InnerGyroSign, int OuterGyroSign,
    bool MotionAndCablingApproved, bool EmergencyStopConfirmed, bool SensorMappingVerified);

public sealed record Ct17SettingsSnapshot(
    double StaticCaptureSeconds, double ExpectedHostBatchHz, double HostRateTolerancePercent,
    double PreMotionDwellSeconds, double SettleSeconds,
    bool TestInner, bool TestOuter, int Repetitions,
    double CenterDeg, double AmplitudeDeg, double CommandSpeedDps, double SetupSpeedDps,
    double ApprovedMinDeg, double ApprovedMaxDeg,
    double EncoderDerivativeWindowSeconds, double MaxLagSearchMs,
    int InnerGyroSign, int OuterGyroSign);

public sealed record Ct17StaticTiming(
    int Batches, long Frames, int OdrHz, double DurationSeconds,
    double HostBatchRateHz, double HostBatchPeriodMedianMs, double HostBatchJitterP95Ms,
    double McuTickPeriodMedianMs, double ExpectedMcuBatchPeriodMs,
    double McuTickPeriodErrorPercent, double EffectiveFrameRateFromHostHz,
    double HostVsMcuClockDriftPpm, double HostVsMcuResidualP95Ms,
    int CandidateMissingBatches, int UnclassifiedLongGaps,
    double? CandidateMissingFrameRatio, double ExpectedHostBatchHz,
    double HostBatchRateErrorPercent, bool FrameBlocksValid,
    IReadOnlyList<string> Warnings);

public sealed record Ct17SweepSample(
    long HostTimestampTicks, double TimeFromCommandMs, double HostTimeSeconds,
    double? EncoderPositionDeg, double? EncoderReferenceRateDps,
    double GyroMeasuredRateDps, double? ResidualDps, double TemperatureC,
    double? EncoderSampleAgeMs, bool HasReference, string Quality);

public sealed record Ct17SweepResult(
    int Index, string Axis, string Direction, int Repetition,
    double CommandSpeedDps, double StartDeg, double EndDeg,
    int GyroFrames, int EncoderFrames, int PreMotionGyroFrames, int PreMotionEncoderFrames,
    double? CommandCallDurationMs, double? CommandToEncoderOnsetMs,
    double? CommandToGyroOnsetMs, double? EncoderToGyroOnsetMs,
    double? CrossCorrelationLagMs, double? CrossCorrelationCoefficient,
    double? MedianReferenceRateDps, double? MedianGyroRateDps,
    double? MedianResidualDps, double? ResidualRmseDps,
    double? GyroBatchIntervalMedianMs, double? EncoderIntervalMedianMs,
    double TimingResolutionMs, long TimestampFrequency, long CommandCallStartTicks,
    long CommandCallReturnTicks, string DataSource, string HardwareNotes,
    string CsvPath, string Quality, IReadOnlyList<Ct17SweepSample> Samples);

public sealed record Ct17ReportData(
    string TestId, string TestName, string DeviceNumber, string UidHex,
    DateTimeOffset StartedUtc, DateTimeOffset FinishedUtc,
    string State, string FailureReason, Ct17SettingsSnapshot Settings,
    string AccJsonFile, string AccJsonSha256, string GyroJsonFile, string GyroJsonSha256,
    string StaticCaptureFolder, string StaticRawCsv, string StaticSelectedCsv, string StaticManifest,
    Ct17StaticTiming? StaticTiming, IReadOnlyList<Ct17SweepResult> Sweeps,
    string Conclusion, string Limitation);
