namespace Dts.Tests.S1.CT13;

public sealed record Ct13Settings(
    int CycleIndex, int TotalCycles, int CaptureSeconds,
    string ExpectedUidHex, string ExpectedDeviceNumber);

/// <summary>
/// PowerOnConfirmedUtc is the operator-confirmation timestamp after the device has been powered
/// back on and reconnected in the main application; it is not a hardware-edge timestamp.
/// </summary>
public sealed record Ct13Cycle(
    int Index, string UidHex, string DeviceNumber,
    string PowerOnConfirmedUtc, string CaptureStartedUtc, string CaptureEndedUtc,
    int Samples, int Batches, string CsvFile, string ManifestFile, string? AnalysisFile,
    double? TemperatureC, string OperatorNote);

public sealed record Ct13Summary(
    int CompletedCycles, double[]? AccMeanBetweenCycleStd,
    double[]? GyroMeanBetweenCycleStd, double? TemperatureMeanMinC,
    double? TemperatureMeanMaxC, string Interpretation);
