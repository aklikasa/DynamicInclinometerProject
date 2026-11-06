using System.Globalization;
using Dts.Core;

namespace Dts.Devices;

/// <summary>
/// ONE source of truth for the user-selected stream. Both the live DataGrid and
/// imu_selected.csv use the values/format produced here. Raw counts are also
/// retained separately for provenance and reprocessing.
/// </summary>
public sealed record SelectedImuFrame(
    DateTimeOffset HostUtc, uint McuTickMs, int SampleIndex,
    CalibrationMode Mode, double TemperatureC,
    string Ax, string Ay, string Az, string Gx, string Gy, string Gz,
    string AccUnit, string GyroUnit, string Status,
    short RawAx, short RawAy, short RawAz, short RawGx, short RawGy, short RawGz,
    double[]? PhysicalAcc = null, double[]? PhysicalGyro = null,
    double[]? CalibratedAcc = null, double[]? CalibratedGyro = null)
{
    public string LocalTime => HostUtc.ToLocalTime().ToString("HH:mm:ss.fff", CultureInfo.InvariantCulture);
    public string ModeLabel => Mode switch
    {
        CalibrationMode.Raw => "未标定物理量",
        CalibrationMode.Ambient => "常温补偿",
        CalibrationMode.Thermal => "全温补偿",
        _ => "未知模式"
    };
    public string Units => AccUnit + " / " + GyroUnit;
    public string TempText => TemperatureC.ToString("F2", CultureInfo.InvariantCulture);
    public bool HasValidCalibration => Mode != CalibrationMode.Raw && Status == "MCU_SCALE_VERIFIED_CALIBRATED";
    // A computed calibration is always displayed. Evidence/status is distinct from computation.
    public bool HasComputedCalibration => Mode != CalibrationMode.Raw &&
        CalibratedAcc is { Length: 3 } && CalibratedGyro is { Length: 3 };
    public bool IsDevelopmentTrial => HasComputedCalibration && !HasValidCalibration;

    public static string CsvHeader =>
        "host_utc,mcu_tick_ms,sample_index,mode,temp_c,ax,ay,az,gx,gy,gz,acc_unit,gyro_unit,source_status";

    public string ToSelectedCsvLine() => string.Join(",",
        HostUtc.ToString("O",CultureInfo.InvariantCulture),
        McuTickMs.ToString(CultureInfo.InvariantCulture),
        SampleIndex.ToString(CultureInfo.InvariantCulture),
        Mode.ToString().ToUpperInvariant(),TempText,
        Ax,Ay,Az,Gx,Gy,Gz,AccUnit,GyroUnit,Status);

    private static string F(double value) => value.ToString("F6",CultureInfo.InvariantCulture);

    public static SelectedImuFrame FromSample(ImuBatch batch, ImuSample sample,
        int sampleIndex, CalibrationRun? selectedRun)
    {
        var run=selectedRun ?? CalibrationRun.Raw;
        bool sensorOk=(batch.FifoFlags & 0x0001)!=0;
        if(run.Mode == CalibrationMode.Raw)
        {
            var displayScale=CalibrationInputScalePolicy.UncalibratedDisplayScale();
            // The user's "raw" view is physical units BEFORE calibration: x, not int16.
            // Immutable signed int16 counts remain in imu_raw.csv / the Raw* fields.
            double[] acc=[sample.RawAx*displayScale.AccGPerLsb,
                sample.RawAy*displayScale.AccGPerLsb,sample.RawAz*displayScale.AccGPerLsb];
            double[] gyro=[sample.RawGx*displayScale.GyroDpsPerLsb,
                sample.RawGy*displayScale.GyroDpsPerLsb,sample.RawGz*displayScale.GyroDpsPerLsb];
            string rawStatus=sensorOk?"PHYSICAL_UNCALIBRATED_HISTORICAL_FS" :
                "PHYSICAL_UNCALIBRATED_HISTORICAL_FS_SENSOR_UNVERIFIED";
            return new SelectedImuFrame(batch.HostTimeUtc,batch.McuTickMs,sampleIndex,run.Mode,batch.TemperatureC,
                F(acc[0]),F(acc[1]),F(acc[2]),F(gyro[0]),F(gyro[1]),F(gyro[2]),
                "g","deg/s",rawStatus,sample.RawAx,sample.RawAy,sample.RawAz,
                sample.RawGx,sample.RawGy,sample.RawGz,acc,gyro);
        }
        // A selected ambient JSON is a mathematical transformation, not a certification gate.
        // Always compute from real signed int16 samples if the calibration files provide
        // physical-unit sensitivities. Prefer the sensitivities in the *matching* JSON:
        // these were used when the stored bias/matrix was fitted, so switching to an
        // unrelated runtime fallback could silently change the mathematical result.
        // If an individual JSON omits FS, use its MCU-reported FS when valid.
        bool scaleVerified=batch.AllUnitsValid;
        bool accJsonScale=false,gyroJsonScale=false;
        bool jsonMcuMismatch=false;
        double[] physicalAcc,physicalGyro;
        if(run.Mode==CalibrationMode.Ambient)
        {
            // Conversion must use the same input units that produced the chosen JSON.
            // For DTS872028's original Gyro calibration this is ±2000 dps (0.070),
            // even if the IMU chip was actually initialized for ±250 dps.
            var scale = CalibrationInputScalePolicy.Resolve(
                run.Files?.Acc?.FsHint, run.Files?.Gyro?.FsHint,
                batch.AccFsG, batch.GyroFsDps);
            if (scale is null) return Missing("MCU_FS_UNKNOWN_NO_JSON_HINT");
            accJsonScale=scale.AccFromJson;
            gyroJsonScale=scale.GyroFromJson;
            int accEffectiveFs=scale.AccFullScaleG;
            int gyroEffectiveFs=scale.GyroFullScaleDps;
            physicalAcc=new[]{sample.RawAx*scale.AccGPerLsb,sample.RawAy*scale.AccGPerLsb,
                sample.RawAz*scale.AccGPerLsb};
            physicalGyro=new[]{sample.RawGx*scale.GyroDpsPerLsb,sample.RawGy*scale.GyroDpsPerLsb,
                sample.RawGz*scale.GyroDpsPerLsb};
            jsonMcuMismatch=(accJsonScale && batch.AccFsG>0 && batch.AccFsG!=accEffectiveFs) ||
                (gyroJsonScale && batch.GyroFsDps>0 && batch.GyroFsDps!=gyroEffectiveFs);
            scaleVerified=scaleVerified && !jsonMcuMismatch;
        }
        else
        {
            // Thermal files do not define a scale by themselves. Here the MCU must
            // provide it; missing mathematical inputs cannot be synthesized.
            if(!scaleVerified)return Missing("MCU_FS_UNKNOWN_NO_JSON_HINT");
            physicalAcc=new[]{sample.AxG,sample.AyG,sample.AzG};
            physicalGyro=new[]{sample.GxDps,sample.GyDps,sample.GzDps};
        }
        if(!physicalAcc.All(double.IsFinite) || !physicalGyro.All(double.IsFinite))
            return Missing("PHYSICAL_UNITS_INVALID");

        double[] correctedAcc,correctedGyro;
        try
        {
            if(run.Mode==CalibrationMode.Ambient)
            {
                correctedAcc=run.Files!.Acc!.Apply(physicalAcc[0],physicalAcc[1],physicalAcc[2]);
                correctedGyro=run.Files.Gyro!.Apply(physicalGyro[0],physicalGyro[1],physicalGyro[2]);
            }
            else
            {
                if(run.Files!.ThermalAcc is null || run.Files.ThermalGyro is null)
                    return Missing("THERMAL_MODEL_MISSING");
                if(batch.TemperatureC<run.Files.ThermalAcc.MinC || batch.TemperatureC>run.Files.ThermalAcc.MaxC ||
                   batch.TemperatureC<run.Files.ThermalGyro.MinC || batch.TemperatureC>run.Files.ThermalGyro.MaxC)
                    return Missing("TEMPERATURE_OUT_OF_MODEL_RANGE");
                correctedAcc=run.Files.ThermalAcc.Apply(physicalAcc[0],physicalAcc[1],physicalAcc[2],batch.TemperatureC);
                correctedGyro=run.Files.ThermalGyro.Apply(physicalGyro[0],physicalGyro[1],physicalGyro[2],batch.TemperatureC);
            }
        }
        catch(InvalidDataException) { return Missing("CALIBRATION_COEFFICIENT_INVALID"); }

        if(correctedAcc.Length!=3 || correctedGyro.Length!=3 ||
           !correctedAcc.All(double.IsFinite) || !correctedGyro.All(double.IsFinite))
            return Missing("CALIBRATION_RESULT_INVALID");
        // No SENSOR_OK / FS evidence suppresses a successfully calculated number.
        // Status is a provenance hint only; CT-05's motor safety checks are separate.
        string status=scaleVerified && sensorOk ? "MCU_SCALE_VERIFIED_CALIBRATED" :
            jsonMcuMismatch ? "CALIBRATED_JSON_FS_MCU_MISMATCH" :
            run.Mode==CalibrationMode.Ambient && (accJsonScale || gyroJsonScale) ?
                "CALIBRATED_JSON_FS_UNVERIFIED" : "CALIBRATED_MCU_STATUS_UNVERIFIED";
        return new SelectedImuFrame(batch.HostTimeUtc,batch.McuTickMs,sampleIndex,run.Mode,batch.TemperatureC,
            F(correctedAcc[0]),F(correctedAcc[1]),F(correctedAcc[2]),
            F(correctedGyro[0]),F(correctedGyro[1]),F(correctedGyro[2]),
            "g","deg/s",status,
            sample.RawAx,sample.RawAy,sample.RawAz,sample.RawGx,sample.RawGy,sample.RawGz,
            physicalAcc,physicalGyro,correctedAcc,correctedGyro);

        SelectedImuFrame Missing(string reason) => Make("--","--","--","--","--","--", "g","deg/s",reason);
        SelectedImuFrame Make(string ax,string ay,string az,string gx,string gy,string gz,
            string au,string gu,string st) => new(batch.HostTimeUtc,batch.McuTickMs,sampleIndex,run.Mode,batch.TemperatureC,
                ax,ay,az,gx,gy,gz,au,gu,st,
                sample.RawAx,sample.RawAy,sample.RawAz,sample.RawGx,sample.RawGy,sample.RawGz);
    }
}
