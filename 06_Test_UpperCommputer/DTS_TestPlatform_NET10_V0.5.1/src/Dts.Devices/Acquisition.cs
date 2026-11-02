using System.Globalization;
using System.Text;
using System.Text.Json;
using Dts.Core;

namespace Dts.Devices;

public sealed record AcquisitionResult(string Folder,int Batches,int Samples,int SkippedDuplicates,
    double MeanGx,double MeanGy,double MeanGz,DateTimeOffset Start,DateTimeOffset End);

/// <summary>Records only physical Modbus readings, rejects FIFO_SIM_MODE, writes incrementally.</summary>
public static class Acquisition
{
    public static async Task<AcquisitionResult> CollectAsync(RealImu imu,TimeSpan duration,
        string testId,IProgress<string>? progress,CancellationToken ct,string? selectedRoot=null)
    {
        if(!imu.Connected||imu.Identity is null)throw new InvalidOperationException("必须连接真实 IMU 并读取硬件 UID");
        if(duration<=TimeSpan.Zero||duration>TimeSpan.FromHours(24))throw new ArgumentOutOfRangeException(nameof(duration));
        var id=imu.Identity;
        string root=Path.Combine(selectedRoot ?? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments),
            "DTS_RealData"), id.DtsId+"_"+id.UidHex,DateTime.UtcNow.ToString("yyyyMMdd_HHmmss_fff")+"_"+testId);
        Directory.CreateDirectory(root);
        string file=Path.Combine(root,"imu_raw.csv");
        DateTimeOffset start=DateTimeOffset.UtcNow;
        int batchCount=0,sampleCount=0,duplicates=0;
        double sgx=0,sgy=0,sgz=0;
        uint? lastTick=null;
        await using var stream=new FileStream(file,FileMode.CreateNew,FileAccess.Write,FileShare.Read,65536,FileOptions.Asynchronous);
        await using var csv=new StreamWriter(stream,new UTF8Encoding(true));
        await csv.WriteLineAsync("host_utc,mcu_tick_ms,sample_index,acc_fs_g,gyro_fs_dps,odr_hz,fifo_flags,temp_c,ax_g,ay_g,az_g,gx_dps,gy_dps,gz_dps,raw_ax,raw_ay,raw_az,raw_gx,raw_gy,raw_gz");
        var watch=System.Diagnostics.Stopwatch.StartNew();
        try
        {
            while(watch.Elapsed<duration)
            {
                ct.ThrowIfCancellationRequested();
                var batch=await imu.ReadBatchAsync(ct);
                if(batch.FifoUnread==0 || (lastTick==batch.McuTickMs))
                {duplicates++;await Task.Delay(12,ct);continue;}
                lastTick=batch.McuTickMs;
                batchCount++;
                for(int i=0;i<batch.Samples.Count;i++)
                {
                    var s=batch.Samples[i];
                    sgx+=s.GxDps;sgy+=s.GyDps;sgz+=s.GzDps;sampleCount++;
                    var ci=CultureInfo.InvariantCulture;
                    string line=string.Join(",",batch.HostTimeUtc.ToString("O"),batch.McuTickMs,i,batch.AccFsG,
                        batch.GyroFsDps,batch.OdrHz,batch.FifoFlags,batch.TemperatureC.ToString("G17",ci),
                        s.AxG.ToString("G17",ci),s.AyG.ToString("G17",ci),s.AzG.ToString("G17",ci),
                        s.GxDps.ToString("G17",ci),s.GyDps.ToString("G17",ci),s.GzDps.ToString("G17",ci),
                        s.RawAx,s.RawAy,s.RawAz,s.RawGx,s.RawGy,s.RawGz);
                    await csv.WriteLineAsync(line);
                }
                if(batchCount%25==0)
                {await csv.FlushAsync(ct);progress?.Report($"真实采集：{batchCount} 批 / {sampleCount} 帧，ODR={batch.OdrHz}Hz，{watch.Elapsed.TotalSeconds:F1}s");}
                await Task.Delay(10,ct);
            }
        }
        finally{await csv.FlushAsync(CancellationToken.None);}
        var end=DateTimeOffset.UtcNow;
        var result=new AcquisitionResult(root,batchCount,sampleCount,duplicates,
            sampleCount==0?double.NaN:sgx/sampleCount,sampleCount==0?double.NaN:sgy/sampleCount,
            sampleCount==0?double.NaN:sgz/sampleCount,start,end);
        var meta=new
        {
            test_id=testId,uid_raw_12_bytes=id.UidHex,device_sn=id.DtsId,mode="REAL_HARDWARE",
            start_utc=start,end_utc=end,source="MCU_Modbus_RTU_0x03_1000_104",result.Batches,result.Samples,
            result.SkippedDuplicates,result.MeanGx,result.MeanGy,result.MeanGz,
            note="HOST timestamp per batch, NOT synchronized per IMU sample; MCU tick is recorded separately. This is acquisition/diagnostic output, NOT calibrated product acceptance."
        };
        await File.WriteAllTextAsync(Path.Combine(root,"manifest.json"),JsonSerializer.Serialize(meta,new JsonSerializerOptions{WriteIndented=true}),ct);
        return result;
    }
}
