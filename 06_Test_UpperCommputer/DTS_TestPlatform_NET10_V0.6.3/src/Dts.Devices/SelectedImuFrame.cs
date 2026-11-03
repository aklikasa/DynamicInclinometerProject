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
        CalibrationMode.Raw => "原始计数",
        CalibrationMode.Ambient => "常温补偿",
        CalibrationMode.Thermal => "全温补偿",
        _ => "未知模式"
    };
    public string Units => AccUnit + " / " + GyroUnit;
    public string TempText => TemperatureC.ToString("F2", CultureInfo.InvariantCulture);
    public bool HasValidCalibration => Mode != CalibrationMode.Raw && Status == "MCU_SCALE_VERIFIED_CALIBRATED";

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
            string status=sensorOk?"RAW_COUNTS_ONLY":"RAW_SENSOR_UNVERIFIED";
            return Make(sample.RawAx.ToString(CultureInfo.InvariantCulture),
                sample.RawAy.ToString(CultureInfo.InvariantCulture),
                sample.RawAz.ToString(CultureInfo.InvariantCulture),
                sample.RawGx.ToString(CultureInfo.InvariantCulture),
                sample.RawGy.ToString(CultureInfo.InvariantCulture),
                sample.RawGz.ToString(CultureInfo.InvariantCulture),
                "count","count",status);
        }
        if(!sensorOk)return Missing("SENSOR_OK_NOT_REPORTED");
        if(!batch.AllUnitsValid)return Missing("MCU_FS_UNKNOWN");

        var physicalAcc=new[]{sample.AxG,sample.AyG,sample.AzG};
        var physicalGyro=new[]{sample.GxDps,sample.GyDps,sample.GzDps};
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
        return new SelectedImuFrame(batch.HostTimeUtc,batch.McuTickMs,sampleIndex,run.Mode,batch.TemperatureC,
            F(correctedAcc[0]),F(correctedAcc[1]),F(correctedAcc[2]),
            F(correctedGyro[0]),F(correctedGyro[1]),F(correctedGyro[2]),
            "g","deg/s","MCU_SCALE_VERIFIED_CALIBRATED",
            sample.RawAx,sample.RawAy,sample.RawAz,sample.RawGx,sample.RawGy,sample.RawGz,
            physicalAcc,physicalGyro,correctedAcc,correctedGyro);

        SelectedImuFrame Missing(string status) => Make("--","--","--","--","--","--", "g","deg/s",status);
        SelectedImuFrame Make(string ax,string ay,string az,string gx,string gy,string gz,
            string au,string gu,string st) => new(batch.HostTimeUtc,batch.McuTickMs,sampleIndex,run.Mode,batch.TemperatureC,
                ax,ay,az,gx,gy,gz,au,gu,st,
                sample.RawAx,sample.RawAy,sample.RawAz,sample.RawGx,sample.RawGy,sample.RawGz);
    }
}
