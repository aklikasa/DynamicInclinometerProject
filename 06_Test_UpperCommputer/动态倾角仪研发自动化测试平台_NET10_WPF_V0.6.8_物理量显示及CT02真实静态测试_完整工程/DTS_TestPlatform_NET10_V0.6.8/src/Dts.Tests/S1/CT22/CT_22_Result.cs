using Dts.Core;

namespace Dts.Tests.S1.CT22;

/// <summary>CT-22 integrates calibrated-but-unfused Gyro, never subtracts a test-time offset.</summary>
public sealed record Ct22Settings(
    CalibrationRun Calibration, string ReportRoot, double DurationMinutes,
    int MinimumBatches, double MaxHostJitterPercent, double MaxMcuJitterPercent,
    double MaxFifoSpanErrorPercent, double MaxHostMcuSpanMismatchPercent,
    double MaxTemperatureRangeC, double MaxAccDirectionChangeDeg,
    double PlotIntervalSeconds, bool StationaryConfirmed,
    bool ThermalEnvironmentConfirmed, bool TimebaseLimitAccepted);

public sealed record Ct22SettingsSnapshot(
    double DurationMinutes, int MinimumBatches, double MaxHostJitterPercent,
    double MaxMcuJitterPercent, double MaxFifoSpanErrorPercent,
    double MaxHostMcuSpanMismatchPercent, double MaxTemperatureRangeC,
    double MaxAccDirectionChangeDeg, double PlotIntervalSeconds,
    bool StationaryConfirmed, bool ThermalEnvironmentConfirmed,
    bool TimebaseLimitAccepted);

public sealed record Ct22Batch(double HostUtcSeconds, uint McuTickMs,
    int OdrHz, int Frames, double GxDps, double GyDps, double GzDps,
    double TemperatureC, double AxG, double AyG, double AzG);

public sealed record Ct22DriftPoint(double ElapsedSeconds, double GxDeg,
    double GyDeg, double GzDeg, double GxRateDps, double GyRateDps,
    double GzRateDps, double TemperatureC, double AccAngleFromStartDeg);

public sealed record Ct22AxisMetric(string Axis, double MeanRateDps,
    double FinalAngleDeg, double MaxAbsoluteAngleDeg, double LeastSquaresSlopeDegPerMinute,
    double? DriftAt10MinutesDeg, double? DriftAt30MinutesDeg);

public sealed record Ct22TimeQuality(
    string Classification, bool Qualified, int Batches, long Frames,
    int UnchangedPolls, int GapOrOverlapIntervals, int OdrHz,
    double McuDurationSeconds, double HostDurationSeconds,
    double MedianMcuStepSeconds, double HostJitterP95Percent,
    double McuJitterP95Percent, double FifoSpanErrorP95Percent,
    double HostMcuDurationMismatchPercent,
    double TemperatureMinC, double TemperatureMaxC,
    double MaxAccDirectionChangeDeg,
    IReadOnlyList<string> Warnings);

public sealed record Ct22Analysis(Ct22TimeQuality TimeQuality,
    IReadOnlyList<Ct22AxisMetric> Axes, IReadOnlyList<Ct22DriftPoint> Curve,
    double? DriftVectorMagnitudeAt10MinutesDeg,
    double? DriftVectorMagnitudeAt30MinutesDeg,
    double FinalVectorMagnitudeDeg, bool MetricsReleased, string MethodDescription);

public sealed record Ct22ReportData(
    string TestId, string TestName, string Stage, string DeviceNumber, string UidHex,
    string State, string FailureReason, string StartedUtc, string FinishedUtc,
    Ct22SettingsSnapshot Settings, string AccJsonFile, string AccSha256,
    string GyroJsonFile, string GyroSha256, string AcquisitionFolder,
    string RawCsvPath, string SelectedCsvPath, string ManifestPath,
    Ct22Analysis? Analysis, string Conclusion, string ScientificCaveat);
