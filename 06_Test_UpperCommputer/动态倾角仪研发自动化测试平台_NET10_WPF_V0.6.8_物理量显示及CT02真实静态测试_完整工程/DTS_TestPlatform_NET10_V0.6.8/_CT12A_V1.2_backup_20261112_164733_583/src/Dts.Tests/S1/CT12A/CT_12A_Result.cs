using Dts.Core;

namespace Dts.Tests.S1.CT12A;

/// <summary>All settings are frozen at start; no hidden test constants for the adjustable policy.</summary>
public sealed record Ct12aSettings(
    CalibrationRun Calibration, string ReportRoot, double DurationMinutes,
    double TauMinSeconds, double TauMaxSeconds, int PointsPerDecade,
    double MaxHostCadenceJitterPercent, double MaxMcuCadenceJitterPercent,
    double MaxFifoSpanErrorPercent, double MaxTemperatureRangeC, int MinimumBatches,
    bool StationaryConfirmed, bool ThermalEnvironmentConfirmed,
    bool TimebaseLimitAccepted);

public sealed record Ct12aSettingsSnapshot(
    double DurationMinutes, double TauMinSeconds, double TauMaxSeconds,
    int PointsPerDecade, double MaxHostCadenceJitterPercent,
    double MaxMcuCadenceJitterPercent, double MaxFifoSpanErrorPercent, double MaxTemperatureRangeC,
    int MinimumBatches, bool StationaryConfirmed,
    bool ThermalEnvironmentConfirmed, bool TimebaseLimitAccepted);

public sealed record Ct12aBatch(double HostUtcSeconds, uint McuTickMs,
    int OdrHz, int Frames, double GxDps, double GyDps, double GzDps,
    double TemperatureC, double AxG, double AyG, double AzG);

public sealed record Ct12aTimeQuality(
    string Classification, string Description, int Batches, long Frames,
    int SkippedUnchangedPolls, int GapsOrOverlaps, double MedianBatchPeriodSeconds,
    double MedianMcuPeriodSeconds, double HostCadenceJitterP95Percent,
    double McuCadenceJitterP95Percent, double FifoSpanErrorP95Percent,
    double DurationSeconds, int OdrHz, bool ContinuousSequenceQualified,
    IReadOnlyList<string> Warnings);

public sealed record Ct12aCurvePoint(double TauSeconds, int ClusterBatches,
    int OverlappingDifferences, double GxAllanDeviationDps,
    double GyAllanDeviationDps, double GzAllanDeviationDps, double AxAllanDeviationG,
    double AyAllanDeviationG, double AzAllanDeviationG);

public sealed record Ct12aAxisSummary(string Axis, string Unit, double Mean,
    double StandardDeviation, double? MinAllanDeviation, double? TauAtMinimumSeconds,
    double? WhiteNoiseCoefficient, string WhiteNoiseCoefficientUnit,
    double? BiasInstabilityProxy, string BiasInstabilityUnit,
    string QualificationNote);

public sealed record Ct12aAnalysis(Ct12aTimeQuality TimeQuality,
    IReadOnlyList<Ct12aCurvePoint> Curves,
    IReadOnlyList<Ct12aAxisSummary> Axes,
    double TemperatureMinC, double TemperatureMaxC,
    bool CoefficientsReleased, string MethodDescription);

public sealed record Ct12aReportData(
    string TestId, string TestName, string Stage, string DeviceNumber, string UidHex,
    string State, string FailureReason, string StartedUtc, string FinishedUtc,
    Ct12aSettingsSnapshot Settings, string CalibrationAccFile,
    string CalibrationAccSha256, string CalibrationGyroFile,
    string CalibrationGyroSha256, string AcquisitionFolder,
    string RawCsvPath, string SelectedCsvPath, string ManifestPath,
    Ct12aAnalysis? Analysis, string Conclusion, string ScientificCaveat);
