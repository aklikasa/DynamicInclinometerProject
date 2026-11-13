using Dts.Core;
namespace Dts.Tests.S1.CT19;

public sealed record Ct19Settings(
    string OutputRoot, string SpeedsCsv, bool TestInner, bool TestOuter,
    int Repetitions, double TravelMinDeg, double TravelMaxDeg,
    double ApprovedMinDeg, double ApprovedMaxDeg, double SetupSpeedDps,
    double SettleSeconds, double SpeedToleranceFraction,
    double EncoderDerivativeWindowSeconds, int MinAcceptedFrames,
    int InnerGyroSign, int OuterGyroSign,
    bool MotionAndCablingApproved, bool EmergencyStopConfirmed,
    bool SensorAxisMappingVerified, CalibrationRun Calibration)
{
    public Dts.Tests.S1.CT10.Ct10Settings ToCt10Settings() => new(
        OutputRoot, SpeedsCsv, TestInner, TestOuter, Repetitions,
        TravelMinDeg, TravelMaxDeg, ApprovedMinDeg, ApprovedMaxDeg,
        SetupSpeedDps, SettleSeconds, SpeedToleranceFraction,
        EncoderDerivativeWindowSeconds, MinAcceptedFrames,
        InnerGyroSign, OuterGyroSign,
        MotionAndCablingApproved, EmergencyStopConfirmed, SensorAxisMappingVerified,
        Calibration);
}

public sealed record Ct19RunRow(
    int Index, string GyroAxis, string TurntableAxis, double RateDps,
    int Repeat, string Direction, double MeanReferenceDps, double MeanGyroDps,
    double MeanResidualDps, double ResidualRmseDps, double ResidualStdDps,
    double ScaleRatioPercent, double MeanTemperatureC, int TotalGyroFrames,
    int AcceptedFrames, int EncoderFrames, string CsvFile, string EvidenceSource,
    string Quality);

public sealed record Ct19GroupRow(
    string GyroAxis, double RateDps, string Direction, int Repeats,
    double OutputMeanDps, double OutputBetweenRunStdDps,
    double ResidualMeanDps, double ResidualBetweenRunStdDps,
    double ReferenceMeanDps, double ReferenceBetweenRunStdDps,
    string Status);

public sealed record Ct19DirectionPairRow(
    string GyroAxis, double RateDps, int CompletePairs,
    double ForwardResidualDps, double ReverseResidualDps,
    double ForwardReverseDifferenceDps, double MeanResidualRmseDps);

public sealed record Ct19SettingsSnapshot(
    string SpeedsCsv, bool TestInner, bool TestOuter, int Repetitions,
    double TravelMinDeg, double TravelMaxDeg, double ApprovedMinDeg, double ApprovedMaxDeg,
    double SetupSpeedDps, double SettleSeconds, double SpeedToleranceFraction,
    double EncoderDerivativeWindowSeconds, int MinAcceptedFrames,
    int InnerGyroSign, int OuterGyroSign);

public sealed record Ct19ReportData(
    string TestId, string Uid, string DeviceNumber,
    DateTimeOffset StartedUtc, DateTimeOffset EndedUtc, string State,
    string Conclusion, string FailureReason,
    string CalibrationAccFile, string CalibrationAccSha256,
    string CalibrationGyroFile, string CalibrationGyroSha256,
    string HardwareSource, Ct19SettingsSnapshot Settings,
    IReadOnlyList<Ct19RunRow> Runs, IReadOnlyList<Ct19GroupRow> Groups,
    IReadOnlyList<Ct19DirectionPairRow> DirectionPairs,
    string MethodLimitations);
