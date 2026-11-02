using System.Globalization;
using System.IO;
using System.Numerics;
using System.Text;
using System.Text.Json;
using System.Security.Cryptography;
using DynamicInclinometer.Core;

namespace DynamicInclinometer.Infrastructure;

public sealed class ExperimentRecorder : IDisposable
{
    private readonly StreamWriter _writer;
    private readonly StreamWriter _displayWriter;
    public string DirectoryPath {get;}
    public long Count {get;private set;}
    private ExperimentRecorder(string dir,string device,string calFile,string gyroFile,string mode,string sourceType)
    {
        DirectoryPath=dir;Directory.CreateDirectory(dir);
        string manifest=JsonSerializer.Serialize(new {
            device_serial=device,started_utc=DateTimeOffset.UtcNow,calibration_file=Path.GetFileName(calFile),
            gyro_file=Path.GetFileName(gyroFile),mode,source_type=sourceType,
            acc_sha256=Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(calFile))),
            gyro_sha256=File.Exists(gyroFile)?Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(gyroFile))):null,
            provenance="原始与计算结果; 本记录不等同于计量合格证",
            reference_time_basis="IMU MCU relative clock (if verified); turntable host monotonic not implicitly synchronized"},new JsonSerializerOptions{WriteIndented=true});
        File.WriteAllText(Path.Combine(dir,"manifest.json"),manifest,Encoding.UTF8);
        File.Copy(calFile,Path.Combine(dir,"acc_calibration_snapshot.json"),true);
        if(File.Exists(gyroFile))File.Copy(gyroFile,Path.Combine(dir,"gyro_calibration_snapshot.json"),true);
        _writer=new StreamWriter(new FileStream(Path.Combine(dir,"raw_processed.csv"),FileMode.CreateNew,FileAccess.Write,FileShare.Read,65536),new UTF8Encoding(false),65536);
        _writer.WriteLine("seq,time_s,acc_x_g,acc_y_g,acc_z_g,gyro_x_dps,gyro_y_dps,gyro_z_dps,temp_c,synthetic,scale_verified,timing_verified,roll_deg,pitch_deg,yaw_relative_deg,algorithm,quality,quaternion_x,quaternion_y,quaternion_z,quaternion_w,host_arrival_ticks");
        // A separate time-resolved record of what the operator actually saw. The original
        // raw_processed.csv remains stable and always reports the unmodified ABS estimate.
        _displayWriter=new StreamWriter(new FileStream(Path.Combine(dir,"display_processed.csv"),FileMode.CreateNew,FileAccess.Write,FileShare.Read,65536),new UTF8Encoding(false),65536);
        _displayWriter.WriteLine("seq,time_s,reference_mode,display_roll_deg,display_pitch_deg,display_yaw_relative_deg,abs_roll_deg,abs_pitch_deg,display_q_x,display_q_y,display_q_z,display_q_w,reference_q_x,reference_q_y,reference_q_z,reference_q_w,display_valid");
    }
    public static ExperimentRecorder Start(string root,string device,string accFile,string gyroFile,string mode,string sourceType)
    {
        if(string.IsNullOrWhiteSpace(accFile)||!File.Exists(accFile))throw new FileNotFoundException("需要已加载的校准文件",accFile);
        var dir=Path.Combine(root,$"RUN_{DateTime.Now:yyyyMMdd_HHmmss_fff}_{Guid.NewGuid():N}");
        return new ExperimentRecorder(dir,device,accFile,gyroFile,mode,sourceType);
    }
    public void Append(ImuSample sample, AttitudeState attitude,string algorithm)
    {
        var c=CultureInfo.InvariantCulture;
        string f(double x)=>x.ToString("R",c);
        string safeQuality=attitude.Quality.Replace(',',';').Replace('\n',' ');
        _writer.WriteLine(string.Join(",",new[]{
            sample.Sequence.ToString(c),f(sample.TimeSeconds),f(sample.AccG.X),f(sample.AccG.Y),f(sample.AccG.Z),
            f(sample.GyroDps.X),f(sample.GyroDps.Y),f(sample.GyroDps.Z),f(sample.TemperatureC),
            sample.Synthetic.ToString(),sample.ScaleVerified.ToString(),sample.TimingVerified.ToString(),
            f(attitude.RollDeg),f(attitude.PitchDeg),f(attitude.YawRelativeDeg),algorithm,safeQuality,
            f(attitude.Quaternion.X),f(attitude.Quaternion.Y),f(attitude.Quaternion.Z),f(attitude.Quaternion.W),sample.HostArrivalTicks.ToString(c)}));
        Count++;if(Count%128==0)_writer.Flush();
    }
    public void AppendDisplayed(ImuSample sample, AttitudeState absolute, AttitudeState? displayed,
        string referenceMode, Quaternion? relativeReference)
    {
        var c=CultureInfo.InvariantCulture;
        string Num(double value) => value.ToString("R",c);
        string Opt(double? value) => value.HasValue ? Num(value.Value) : "";
        var q=displayed?.Quaternion;
        var valid=displayed.HasValue;
        _displayWriter.WriteLine(string.Join(",",new[]{
            sample.Sequence.ToString(c),Num(sample.TimeSeconds),referenceMode,
            Opt(displayed?.RollDeg),Opt(displayed?.PitchDeg),Opt(displayed?.YawRelativeDeg),
            Num(absolute.RollDeg),Num(absolute.PitchDeg),
            Opt(q?.X),Opt(q?.Y),Opt(q?.Z),Opt(q?.W),
            Opt(relativeReference?.X),Opt(relativeReference?.Y),Opt(relativeReference?.Z),Opt(relativeReference?.W),
            valid ? "True" : "False"
        }));
        if(Count%128==0)_displayWriter.Flush();
    }
    public void Dispose(){_displayWriter.Flush();_displayWriter.Dispose();_writer.Flush();_writer.Dispose();}
}
