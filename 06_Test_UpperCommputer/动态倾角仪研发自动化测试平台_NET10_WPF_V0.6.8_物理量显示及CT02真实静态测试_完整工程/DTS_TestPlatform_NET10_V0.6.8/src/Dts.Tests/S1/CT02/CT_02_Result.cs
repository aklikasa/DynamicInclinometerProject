using Dts.Core;

namespace Dts.Tests.S1.CT02;

/// <summary>One operator-confirmed mechanical level/reference; not a product acceptance decision.</summary>
public sealed record Ct02Settings(
    CalibrationRun Calibration, int ReferenceGravityZSign,
    bool MechanicalZeroConfirmed, bool StationarityConfirmed);

public sealed record Ct02Measurement(
    double AxG, double AyG, double AzG,
    double GxDps, double GyDps, double GzDps, double TemperatureC, uint McuTickMs);

public sealed record Ct02Metrics(
    int Samples, int DistinctMcuTicks, double[] Means, double[] StandardDeviations,
    double RollZeroDeg, double PitchZeroDeg, double TotalGravityDirectionErrorDeg,
    double AccNormG, double AccNormResidualG, double GyroZeroVectorNormDps,
    double MeanTemperatureC);

public sealed record Ct02ReportData(
    string TestId, string Stage, string DtsId, string UidHex,
    string StartedUtc, string EndedUtc, string MeasurementStatus,
    string ReferenceDescription, string SamplingDescription,
    string CalibrationAccFile, string CalibrationAccSha256,
    string CalibrationGyroFile, string CalibrationGyroSha256,
    string InputScalePolicy, string RawCsv, string SelectedCsv, string ManifestFile,
    Ct02Metrics Metrics,
    string Conclusion = "真实静态测量完成，尚待依据参考设备及规格作验收判断；不自动输出 PASS");
