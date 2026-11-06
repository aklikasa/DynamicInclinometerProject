namespace Dts.Core;

/// <summary>
/// The input scale of a fitted calibration belongs to that calibration FILE.
/// A historical Gyro JSON fitted at 2000 dps MUST continue to use 70 mdps/LSB,
/// even if the STM32 reports 250 dps. This class never writes chip registers.
/// To switch to a newly fitted 250-dps calibration, generate a matching new JSON
/// with sensor_configuration.gyro_fs_dps=250; NEVER silently reinterpret old bias/matrix.
/// </summary>
public static class CalibrationInputScalePolicy
{
    // Historical reference profile ONLY; never overrides a valid per-UID calibration JSON.
    // These are the historical Python conversion settings, NOT actual hardware range claims.
    public const int HistoricalAccFullScaleG = 2;
    public const int HistoricalGyroFullScaleDps = 2000;

    /// <summary>
    /// Uncalibrated live display: original historical Python physical-unit scaling,
    /// independent of the MCU's unreported FS metadata or any calibration JSON.
    /// The active calibration model may instead specify its own fitted input scale.
    /// Change these constants only with an explicit unit/version migration.
    /// </summary>
    public static AmbientInputScale UncalibratedDisplayScale()
    {
        if (!Asm330Codec.TryAccMg(HistoricalAccFullScaleG, out double accMg) ||
            !Asm330Codec.TryGyroMdps(HistoricalGyroFullScaleDps, out double gyroMdps))
            throw new InvalidOperationException("未标定物理量显示的默认量程系数不受支持");
        return new AmbientInputScale(HistoricalAccFullScaleG, HistoricalGyroFullScaleDps,
            accMg / 1000d, gyroMdps / 1000d, false, false);
    }

    public static AmbientInputScale? Resolve(int? accFileFsG, int? gyroFileFsDps,
        int accMcuFsG, int gyroMcuFsDps)
    {
        // An explicit but invalid JSON scale must fail instead of silently switching units.
        if (accFileFsG is int af && !Asm330Codec.TryAccMg(af, out _)) return null;
        if (gyroFileFsDps is int gf && !Asm330Codec.TryGyroMdps(gf, out _)) return null;
        bool accFromFile = accFileFsG.HasValue;
        bool gyroFromFile = gyroFileFsDps.HasValue;
        int a = accFileFsG ?? accMcuFsG;
        int g = gyroFileFsDps ?? gyroMcuFsDps;
        if (!Asm330Codec.TryAccMg(a, out double mg) ||
            !Asm330Codec.TryGyroMdps(g, out double mdps)) return null;
        return new AmbientInputScale(a, g, mg / 1000d, mdps / 1000d,
            accFromFile, gyroFromFile);
    }
}

public sealed record AmbientInputScale(int AccFullScaleG, int GyroFullScaleDps,
    double AccGPerLsb, double GyroDpsPerLsb, bool AccFromJson, bool GyroFromJson)
{
    public bool UsesHistoricalCalibrationProfile =>
        AccFromJson && GyroFromJson &&
        AccFullScaleG == CalibrationInputScalePolicy.HistoricalAccFullScaleG &&
        GyroFullScaleDps == CalibrationInputScalePolicy.HistoricalGyroFullScaleDps;

    public string Display =>
        $"ACC ±{AccFullScaleG}g ×{AccGPerLsb:G9} g/LSB ({(AccFromJson ? "JSON" : "MCU")})；" +
        $"Gyro ±{GyroFullScaleDps}°/s ×{GyroDpsPerLsb:G9} °/s/LSB ({(GyroFromJson ? "JSON" : "MCU")})";
}
