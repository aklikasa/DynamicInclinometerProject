using Dts.Core;
using Dts.TestEngine;

namespace Dts.Tests.S1.CT25;

public enum Ct25Axis { OuterX = 2, InnerY = 0 }
public enum Ct25Phase { Baseline, Steady, Recovery }

/// <summary>All parameters are user editable, except certified hardware performance values supplied by the actual driver.</summary>
public sealed record Ct25Settings(
    string OutputRoot, string AmplitudesCsv, string FrequenciesCsv,
    bool TestX, bool TestY, int Cycles, int Repeats,
    double InnerCenterDeg, double OuterCenterDeg,
    double ApprovedMinDeg, double ApprovedMaxDeg, double SetupSpeedDps,
    double SettleSeconds, double RecoverySeconds, double PhaseClockToleranceMs,
    double MaximumGapSeconds, int MinimumSteadyFrames, double EncoderWaveformMinR2,
    double AmplitudeToleranceFraction, int AxisXSign, int AxisYSign,
    bool MechanicalSafetyApproved, bool PhysicalEstopConfirmed, bool FusionMappingVerified,
    CalibrationRun Calibration);

public sealed record Ct25Plan(int Index, Ct25Axis Axis, double AmplitudeDeg, double FrequencyHz,
    int Repeat, int Cycles, double CenterDeg, double PeakSpeedDps,
    double PeakAccelerationDps2, double DurationSeconds,
    bool Eligible, string ExclusionReason);

/// <summary>
/// Each frame must combine a true device FUSED tilt and both actual 2TD encoder angles
/// aligned to one verified clock; never create these values from only ACC/Gyro raw vectors.
/// </summary>
public sealed record Ct25MeasuredFrame(long Ticks, Ct25Phase Phase,
    double InnerEncoderDeg, double OuterEncoderDeg,
    double DeviceFusedTiltXDeg, double DeviceFusedTiltYDeg,
    double TemperatureC);

public sealed record Ct25SineRequest(Ct25Axis Axis, double CenterDeg, double AmplitudeDeg,
    double FrequencyHz, int Cycles, int Repeat, double SetupSpeedDps,
    double SettleSeconds, double RecoverySeconds,
    double ApprovedMinDeg, double ApprovedMaxDeg, double SafetyTimeoutSeconds);

public sealed record Ct25Capture(string FullUidHex, string Source,
    long ClockFrequency, double AlignmentBoundMs, bool TrueSinusoidalMotionVerified,
    bool MotionCompletedNormally, bool DeviceFusionOutputVerified,
    IReadOnlyList<Ct25MeasuredFrame> Frames, string HardwareNotes);

public interface ICt25DynamicTiltHardware
{
    bool IsReadyForTrueSineAndFusedTilt { get; }
    string SourceDescription { get; }
    string CurrentUidHex { get; }
    double MaximumCertifiedSpeedDps(Ct25Axis axis);
    double MaximumCertifiedAccelerationDps2(Ct25Axis axis);
    double MinimumCertifiedFrequencyHz(Ct25Axis axis);
    double MaximumCertifiedFrequencyHz(Ct25Axis axis);
    Task<Ct25Capture> ExecuteTrueSineAsync(Ct25SineRequest request,
        IProgress<string>? progress, CancellationToken cancellationToken);
    Task StopBothAxesAsync(CancellationToken cancellationToken);
}

public static class Ct25DynamicBridge
{
    private static readonly object Lock=new();
    private static readonly Dictionary<IStaticAngleHardware,ICt25DynamicTiltHardware> Providers=new();
    public static void Register(IStaticAngleHardware host,ICt25DynamicTiltHardware source)
    {
        ArgumentNullException.ThrowIfNull(host);
        ArgumentNullException.ThrowIfNull(source);
        lock(Lock) Providers[host]=source;
    }
    public static void Unregister(IStaticAngleHardware host)
    {
        lock(Lock) Providers.Remove(host);
    }
    public static ICt25DynamicTiltHardware? Resolve(IStaticAngleHardware host)
    {
        if(host is ICt25DynamicTiltHardware direct) return direct;
        lock(Lock) return Providers.TryGetValue(host,out var source)?source:null;
    }
}

public sealed record Ct25TraceRow(double TimeSeconds, string Phase,
    double ReferenceRelativeDeg, double DeviceRelativeDeg, double ErrorDeg,
    double InnerEncoderDeg,double OuterEncoderDeg,double TemperatureC);

public sealed record Ct25Result(int Index,string Axis,double AmplitudeCommandDeg,double FrequencyCommandHz,
    int Repeat,int CapturedSteadyFrames,int CapturedBaselineFrames,int CapturedRecoveryFrames,
    double ActualEncoderAmplitudeDeg,double EncoderWaveformR2,double DeviceAmplitudeDeg,
    double Gain,double GainErrorPercent,double PhaseLagDegrees,double DelaySeconds,
    double DynamicBiasDeg,double DynamicRmseDeg,double BeforeZeroBiasDeg,
    double AfterZeroDifferenceDeg,double FinalReturnResidualDeg,
    double MeanTemperatureC,double MaxSampleGapSeconds,string TraceCsv,
    string Source,double AlignmentBoundMs);

public sealed record Ct25ReportData(string TestId,string State,string Error,string UidHex,
    string DeviceNumber,string StartUtc,string EndUtc,string Source,
    string AccCalibrationName,string AccCalibrationSha256,
    string GyroCalibrationName,string GyroCalibrationSha256,
    string Notes, Ct25SettingsSnapshot Settings,
    IReadOnlyList<Ct25Plan> Plan,IReadOnlyList<Ct25Result> Results);

public sealed record Ct25SettingsSnapshot(string AmplitudesCsv,string FrequenciesCsv,
    bool TestX,bool TestY,int Cycles,int Repeats,double InnerCenterDeg,double OuterCenterDeg,
    double ApprovedMinDeg,double ApprovedMaxDeg,double SetupSpeedDps,double SettleSeconds,
    double RecoverySeconds,double PhaseClockToleranceMs,double MaximumGapSeconds,
    int MinimumSteadyFrames,double EncoderWaveformMinR2,double AmplitudeToleranceFraction,
    int AxisXSign,int AxisYSign);
