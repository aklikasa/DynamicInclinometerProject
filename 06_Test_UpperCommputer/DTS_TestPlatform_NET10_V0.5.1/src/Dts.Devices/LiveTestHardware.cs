using System.Globalization;
using System.Text;
using Dts.Core;
using Dts.TestEngine;

namespace Dts.Devices;

/// <summary>Only physical device APIs; all turntable calls share the main UI semaphore.</summary>
public sealed class LiveTestHardware : IStaticAngleHardware
{
    private readonly Func<RealImu?> _imu;
    private readonly Func<IRealTurntable?> _td;
    private readonly SemaphoreSlim _tableGate;
    private readonly Func<string> _outputRoot;
    public LiveTestHardware(Func<RealImu?> currentImu,Func<IRealTurntable?>? table=null,
        SemaphoreSlim? tableGate=null,Func<string>? outputRoot=null)
    {
        _imu=currentImu;_td=table??(()=>null);
        _tableGate=tableGate??new SemaphoreSlim(1,1);
        _outputRoot=outputRoot??(()=>Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments),"DTS_RealData"));
    }
    public DeviceIdentity? CurrentIdentity=>_imu()?.Identity;
    public bool IsTwoTdConnected=>_td() is Td600 {Connected:true};
    public async Task<CaptureArtifacts> CaptureStaticImuAsync(string testId,TimeSpan duration,
        bool analyzeRawStatistics,IProgress<string>? progress,CancellationToken ct)
    {
        var imu=_imu()??throw new InvalidOperationException("没有连接真实 IMU");
        var id=imu.Identity??throw new InvalidOperationException("没有读取真实 UID");
        var captured=await Acquisition.CollectAsync(imu,duration,testId,progress,ct,_outputRoot());
        var analysis=analyzeRawStatistics?await StaticDiagnostics.AnalyzeAsync(captured,id,testId,ct):null;
        return new CaptureArtifacts(captured.Folder,Path.Combine(captured.Folder,"imu_raw.csv"),
            Path.Combine(captured.Folder,"manifest.json"),analysis,
            captured.Samples,captured.Batches,id.UidHex,id.DtsId);
    }
    private IRealTurntable RequireTd()
    {
        var t=_td();
        return t is Td600{Connected:true} ?t :throw new InvalidOperationException("CT-05 需连接真实 2TD-600");
    }
    public async Task<RealTableFeedback> ReadTwoTdAsync(CancellationToken ct)
    {
        await _tableGate.WaitAsync(ct);
        try
        {
            var s=await Task.Run(()=>RequireTd().Read(),ct);
            static RealAxisFeedback ConvertAxis(AxisState a)=>new(a.PositionDeg,a.SpeedDps,
                a.Normal,a.EnableVerified,a.InPlace,a.Detail);
            return new RealTableFeedback(ConvertAxis(s.Inner),ConvertAxis(s.Outer),s.Time);
        }
        finally{_tableGate.Release();}
    }
    public async Task SetTwoTdAbsoluteAsync(int axis,double targetDeg,double speedDps,CancellationToken ct)
    {
        await _tableGate.WaitAsync(ct);
        try{await Task.Run(()=>RequireTd().MoveAbsolute(axis,targetDeg,speedDps),ct);}
        finally{_tableGate.Release();}
    }
    public async Task StopTwoTdBothAsync(CancellationToken ct)
    {
        await _tableGate.WaitAsync(ct);
        try
        {
            var t=RequireTd();var errors=new List<string>();
            foreach(int axis in new[]{0,2})
            {
                try{await Task.Run(()=>t.StopAxis(axis),ct);}
                catch(Exception e){errors.Add($"轴{axis}:{e.Message}");}
            }
            // Verify fresh feedback, not merely successful DLL return.
            int consecutive=0;var watch=System.Diagnostics.Stopwatch.StartNew();
            while(watch.Elapsed<TimeSpan.FromSeconds(8))
            {
                var s=await Task.Run(t.Read,ct);
                bool stable=Math.Abs(s.Inner.SpeedDps)<0.05&&Math.Abs(s.Outer.SpeedDps)<0.05;
                consecutive=stable?consecutive+1:0;
                if(consecutive>=3)break;
                await Task.Delay(200,ct);
            }
            if(consecutive<3||errors.Count>0)
                throw new IOException("双轴软停车未完整确认："+string.Join(";",errors));
        }
        finally{_tableGate.Release();}
    }
    public async Task<StaticPointSamples> CaptureStaticPointAsync(string csvPath,TimeSpan duration,
        IProgress<string>? progress,CancellationToken ct)
    {
        var device=_imu()??throw new InvalidOperationException("IMU 未连接");
        if(!device.Connected||device.Identity is null)throw new IOException("未读取真实 UID");
        Directory.CreateDirectory(Path.GetDirectoryName(csvPath)!);
        var samples=new List<RealImuVector>();
        int batches=0,dup=0;uint? lastTick=null;double sumT=0;
        DateTimeOffset start=DateTimeOffset.UtcNow;
        await using var output=new FileStream(csvPath,FileMode.CreateNew,FileAccess.Write,FileShare.Read,
            32768,FileOptions.Asynchronous);
        await using var writer=new StreamWriter(output,new UTF8Encoding(true));
        await writer.WriteLineAsync("host_utc,mcu_tick_ms,frame_index,ax_g,ay_g,az_g,gx_dps,gy_dps,gz_dps,temp_c,odr_hz");
        var sw=System.Diagnostics.Stopwatch.StartNew();
        while(sw.Elapsed<duration)
        {
            ct.ThrowIfCancellationRequested();
            var b=await device.ReadBatchAsync(ct); // SIM_MODE and SENSOR_OK checked here.
            if(b.FifoUnread==0||b.McuTickMs==lastTick){dup++;await Task.Delay(10,ct);continue;}
            lastTick=b.McuTickMs;batches++;sumT+=b.TemperatureC;
            for(int i=0;i<b.Samples.Count;i++)
            {
                var s=b.Samples[i];
                samples.Add(new RealImuVector(s.AxG,s.AyG,s.AzG,s.GxDps,s.GyDps,s.GzDps));
                var ci=CultureInfo.InvariantCulture;
                await writer.WriteLineAsync(string.Join(",",b.HostTimeUtc.ToString("O"),b.McuTickMs,
                    i,s.AxG.ToString("G17",ci),s.AyG.ToString("G17",ci),s.AzG.ToString("G17",ci),
                    s.GxDps.ToString("G17",ci),s.GyDps.ToString("G17",ci),s.GzDps.ToString("G17",ci),
                    b.TemperatureC.ToString("G17",ci),b.OdrHz));
            }
            if(batches%20==0)progress?.Report($"静态逐点采集：{samples.Count} 帧 / {batches} 批，{sw.Elapsed.TotalSeconds:F1}s");
            await Task.Delay(10,ct);
        }
        await writer.FlushAsync(ct);
        return new StaticPointSamples(csvPath,samples,batches,start,DateTimeOffset.UtcNow,dup,
            batches>0?sumT/batches:double.NaN);
    }
}
