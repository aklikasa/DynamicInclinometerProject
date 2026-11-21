using Dts.Core;
using Dts.Tests.S1.CT10;

namespace Dts.Tests.S1.CT27;

/// <summary>CT-27: motion followed by gyro zero-rate bias recovery observation.</summary>
public sealed record Ct27Settings(
    string OutputRoot,
    string SpeedsCsv,
    bool TestInner,
    bool TestOuter,
    int Repetitions,
    double TravelMinDeg,
    double TravelMaxDeg,
    double ApprovedMinDeg,
    double ApprovedMaxDeg,
    double SetupSpeedDps,
    double SettleSeconds,
    double BaselineSeconds,
    double RecoverySeconds,
    double BinSeconds,
    double RecoveryBandDps,
    int ConsecutiveStableBins,
    int MinSamplesPerBin,
    bool MotionAndCablingApproved,
    bool EmergencyStopConfirmed,
    bool SensorAxisMappingVerified,
    CalibrationRun Calibration);

public sealed record Ct27PlanItem(
    int Index,
    Ct10Axis Axis,
    string GyroAxis,
    double CommandDps,
    int Repetition,
    Ct10Direction Direction,
    double StartDeg,
    double EndDeg,
    double AllowedMinDeg,
    double AllowedMaxDeg,
    double SafetyTimeoutSeconds)
{
    public string DirectionText => Direction == Ct10Direction.Forward ? "正向" : "反向";
    public double TravelLow => Math.Min(StartDeg, EndDeg);
    public double TravelHigh => Math.Max(StartDeg, EndDeg);
    public double TravelLength => Math.Abs(EndDeg - StartDeg);
    public Ct10SweepRequest ToSweepRequest() => new(
        Axis, Direction, Repetition, CommandDps, StartDeg, EndDeg, 0,
        AllowedMinDeg, AllowedMaxDeg, SafetyTimeoutSeconds);
}

public sealed record Ct27SettingsSnapshot(
    string SpeedsCsv,
    bool TestInner,
    bool TestOuter,
    int Repetitions,
    double TravelMinDeg,
    double TravelMaxDeg,
    double ApprovedMinDeg,
    double ApprovedMaxDeg,
    double SetupSpeedDps,
    double SettleSeconds,
    double BaselineSeconds,
    double RecoverySeconds,
    double BinSeconds,
    double RecoveryBandDps,
    int ConsecutiveStableBins,
    int MinSamplesPerBin);

public sealed record Ct27WindowStats(
    double MeanX,
    double MeanY,
    double MeanZ,
    double StdX,
    double StdY,
    double StdZ,
    double MeanTemperatureC,
    int Samples,
    int Batches,
    int DuplicateBatches);

public sealed record Ct27RecoveryBin(
    int CycleIndex,
    int BinIndex,
    double SinceStopMidpointSeconds,
    double SinceStopEndSeconds,
    string StartedUtc,
    string FinishedUtc,
    double MeanX,
    double MeanY,
    double MeanZ,
    double StdX,
    double StdY,
    double StdZ,
    double DeltaX,
    double DeltaY,
    double DeltaZ,
    double MaxAbsDeltaDps,
    double MeanTemperatureC,
    int Samples,
    int Batches,
    int DuplicateBatches,
    string PhysicalCsv);

public sealed record Ct27CycleResult(
    int Index,
    string GyroAxis,
    string TurntableAxis,
    double CommandDps,
    double MeasuredMedianRateDps,
    int Repetition,
    string Direction,
    double StartDeg,
    double EndDeg,
    string BaselineStartedUtc,
    string BaselineEndedUtc,
    double BaselineMeanX,
    double BaselineMeanY,
    double BaselineMeanZ,
    double BaselineStdX,
    double BaselineStdY,
    double BaselineStdZ,
    double BaselineTemperatureC,
    int BaselineSamples,
    string StopConfirmedUtc,
    double PeakMaxAbsDeltaDps,
    double FinalDeltaX,
    double FinalDeltaY,
    double FinalDeltaZ,
    double? RecoveredBySeconds,
    int RecoveryBins,
    string Quality,
    string BaselineCsv,
    string MotionGyroCsv,
    string MotionEncoderCsv);

public sealed record Ct27Aggregate(
    int CompletedCycles,
    int RecoveryObservedCycles,
    double MaximumObservedBiasStepDps,
    double MeanFinalMaxAbsDeltaDps,
    double? MeanRecoveryUpperBoundSeconds);

public sealed record Ct27ReportData(
    string TestId,
    string Name,
    string DeviceNumber,
    string UidHex,
    string StartedUtc,
    string FinishedUtc,
    string State,
    string Reason,
    string Conclusion,
    string CalibrationMode,
    string AccFile,
    string AccSha256,
    string GyroFile,
    string GyroSha256,
    string DynamicAdapterDescription,
    Ct27SettingsSnapshot Settings,
    IReadOnlyList<Ct27PlanItem> Plan,
    IReadOnlyList<Ct27CycleResult> Cycles,
    IReadOnlyList<Ct27RecoveryBin> Bins,
    Ct27Aggregate? Aggregate,
    string MethodLimitations);
