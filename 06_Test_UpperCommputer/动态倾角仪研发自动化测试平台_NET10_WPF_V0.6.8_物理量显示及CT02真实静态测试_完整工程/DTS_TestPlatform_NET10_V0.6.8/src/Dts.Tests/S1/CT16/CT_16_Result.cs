using Dts.Core;

namespace Dts.Tests.S1.CT16;

/// <summary>Physical 2TD outer-axis excursion/return; real ACC-derived post-stop tilt proxy, not a fused-device output.</summary>
public sealed record Ct16Settings(
    string OutputRoot, double InnerFixedDeg, double OuterHomeDeg,
    double ExcursionDeg, string SpeedsDps, int Repeats,
    double PrepareSpeedDps, double BaselineSeconds, double RecoverySeconds,
    double BinSeconds, double RecoveryThresholdDeg, int ConsecutiveBins,
    double PositionToleranceDeg, double AllowedMinDeg, double AllowedMaxDeg,
    int MinValidSamplesPerBin, bool PathAndCablingApproved,
    bool EStopAndSupervisionApproved, CalibrationRun Calibration);

public sealed record Ct16PlanItem(int Index, double SpeedDps, int Repeat,
    string Direction, double InnerDeg, double HomeDeg, double ExcursionTargetDeg);

public sealed record Ct16Bin(
    int CycleIndex, int BinIndex, bool Baseline,
    double SinceStopSeconds, string StartedUtc, string FinishedUtc,
    double InnerFeedbackDeg, double OuterFeedbackDeg,
    double[] AccCorrectedMeanG, double[] GyroCorrectedMeanDps,
    double SignedTiltProxyDeg, double AngularDisplacementDeg,
    int Samples, int Batches, int DuplicateBatches,
    double TemperatureC, string PhysicalCsv);

public sealed record Ct16Cycle(
    int Index, double SpeedDps, string Direction,
    double HomeDeg, double ExcursionTargetDeg,
    string StopConfirmedUtc, double InnerStopFeedbackDeg, double OuterStopFeedbackDeg,
    double PeakObservedAfterStopDeg, double PeakSignedProxyDeg,
    double FinalSignedOffsetDeg, double FinalAngularOffsetDeg,
    double? RecoveredBySeconds, int RecoveryBins,
    string RecoveryInterpretation);

public sealed record Ct16Aggregate(int CompletedCycles,int RecoveryObservedCycles,
    double MaximumObservedPostStopPeakDeg,double MeanFinalAngularOffsetDeg,
    double? MeanObservedRecoveryUpperBoundSeconds);

public sealed record Ct16Snapshot(string SpeedsDps,int Repeats,
    double InnerFixedDeg,double OuterHomeDeg,double ExcursionDeg,
    double PrepareSpeedDps,double BaselineSeconds,double RecoverySeconds,
    double BinSeconds,double RecoveryThresholdDeg,int ConsecutiveBins,
    double PositionToleranceDeg,double AllowedMinDeg,double AllowedMaxDeg,
    int MinValidSamplesPerBin);

public sealed record Ct16ReportData(
    string TestId,string Name,string DeviceNumber,string UidHex,string StartedUtc,string FinishedUtc,
    string State,string Reason,string Conclusion,string AngleSignalType,
    string ModelDescription,string AccFile,string AccSha256,string GyroFile,string GyroSha256,
    string ScaleDescription,Ct16Snapshot Settings,IReadOnlyList<Ct16PlanItem> Plan,
    IReadOnlyList<Ct16Bin> Bins,IReadOnlyList<Ct16Cycle> Cycles,Ct16Aggregate? Aggregate,
    string Caveat);
