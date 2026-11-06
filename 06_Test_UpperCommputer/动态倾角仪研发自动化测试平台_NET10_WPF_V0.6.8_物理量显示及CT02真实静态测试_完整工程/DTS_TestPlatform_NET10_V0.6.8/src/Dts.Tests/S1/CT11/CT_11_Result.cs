using Dts.Core;
using Dts.Tests.S1.CT10;

namespace Dts.Tests.S1.CT11;

/// <summary>CT-11 does not create another dynamic driver. It uses the existing CT-10 bridge.</summary>
public sealed record Ct11Settings(
    string OutputRoot, string LowSpeedsCsv, bool TestInner, bool TestOuter,
    int Repetitions, double TravelMinDeg, double TravelMaxDeg,
    double ApprovedMinDeg, double ApprovedMaxDeg, double SetupSpeedDps,
    double SettleSeconds, double SpeedToleranceFraction,
    double EncoderDerivativeWindowSeconds, int MinAcceptedFrames,
    int InnerGyroSign, int OuterGyroSign,
    bool MotionAndCablingApproved, bool EmergencyStopConfirmed,
    bool SensorAxisMappingVerified, CalibrationRun Calibration);

public sealed record Ct11SettingsSnapshot(
    string LowSpeedsCsv, bool TestInner, bool TestOuter,
    int Repetitions, double TravelMinDeg, double TravelMaxDeg,
    double ApprovedMinDeg, double ApprovedMaxDeg, double SetupSpeedDps,
    double SettleSeconds, double SpeedToleranceFraction,
    double EncoderDerivativeWindowSeconds, int MinAcceptedFrames,
    int InnerGyroSign, int OuterGyroSign);

/// <summary>Per-sweep three-axis evidence; frame details live in the CSV file.</summary>
public sealed record Ct11SweepResult(
    Ct10Axis Axis, Ct10Direction Direction, int Repetition,
    double CommandSpeedDps, double ReferenceSignedDps,
    double[] GyroMeanDps, double[] GyroWithinStdDps,
    double MainAxisSignedDps, double MainAxisResidualDps,
    double MeanTemperatureC, int AcceptedFrames, int TotalFrames,
    int EncoderFrames, string FrameCsv, string TimeQuality,
    string DataSource);

/// <summary>Fit y = intercept + slope * signed measured encoder rate.</summary>
public sealed record Ct11Fit(int GyroAxis, string GyroAxisLabel,
    int Points, double InterceptDps, double Slope,
    double ResidualRmsDps, double MaxAbsoluteResidualDps,
    double RSquared);

public sealed record Ct11AxisSummary(
    Ct10Axis DriveAxis, string MainGyroAxis, int Sweeps, int DistinctSpeedLevels,
    double MainGain, double MainGainErrorPercent,
    double MainInterceptDps, double LowSpeedNonlinearityRmsDps,
    double LowSpeedNonlinearityMaxDps,
    double NonlinearityMaxPercentOfMaxTestSpeed,
    IReadOnlyList<Ct11Fit> Fits,
    double MaximumCrossAxisCouplingPercent,
    string Interpretation);

public sealed record Ct11ReportData(
    string TestId, string TestName, string DeviceNumber, string UidHex,
    string StartedUtc, string FinishedUtc, string State, string FailureReason,
    string Conclusion, Ct11SettingsSnapshot Settings,
    string GyroJsonName, string GyroJsonSha256,
    string AccJsonName, string AccJsonSha256,
    string DynamicSource, int GyroInputScaleDps,
    IReadOnlyList<Ct11SweepResult> Sweeps,
    IReadOnlyList<Ct11AxisSummary> AxisSummaries,
    string EvidenceNotes);
