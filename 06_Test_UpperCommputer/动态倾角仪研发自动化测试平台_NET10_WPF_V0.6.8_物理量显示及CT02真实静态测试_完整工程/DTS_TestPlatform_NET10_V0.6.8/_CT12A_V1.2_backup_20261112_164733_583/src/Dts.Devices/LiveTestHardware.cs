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
    private readonly Func<CalibrationRun> _run;
    public LiveTestHardware(Func<RealImu?> currentImu,Func<IRealTurntable?>? table=null,
        SemaphoreSlim? tableGate=null,Func<string>? outputRoot=null,Func<CalibrationRun>? calibrationRun=null)
    {
        _imu=currentImu;_td=table??(()=>null);
        _tableGate=tableGate??new SemaphoreSlim(1,1);
        _outputRoot=outputRoot??(()=>Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments),"DTS_RealData"));
        _run=calibrationRun??(()=>CalibrationRun.Raw);
    }
    public DeviceIdentity? CurrentIdentity=>_imu()?.Identity;
    public bool IsTwoTdConnected=>_td() is Td600 {Connected:true};
    public async Task<CaptureArtifacts> CaptureStaticImuAsync(string testId,TimeSpan duration,
        bool analyzeRawStatistics,IProgress<string>? progress,CancellationToken ct)
    {
        var imu=_imu()??throw new InvalidOperationException("没有连接真实 IMU");
        var id=imu.Identity??throw new InvalidOperationException("没有读取真实 UID");
        var run=_run();
        run.Validate(id);
        var captured=await Acquisition.CollectAsync(imu,duration,testId,progress,ct,_outputRoot(),run);
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
    public async Task VerifyImuForPrecisionTestAsync(CancellationToken ct)
    {
        var device=_imu()??throw new InvalidOperationException("请先连接真实 IMU");
        var id=device.Identity??throw new IOException("CT-05 前置检查：IMU 未连接或 UID 不可用");
        if(!device.Connected)throw new IOException("CT-05 前置检查：IMU 串口未连接");
        var run=_run();
        run.Validate(id);
        var b=await device.ReadBatchAsync(ct,requireSensorOk:false); // SIM_MODE is still rejected.
        if(b.FifoUnread==0 || b.Samples.Count==0)
            throw new InvalidDataException("CT-05 前置检查：没有真实的新 FIFO 采样帧，禁止启动自动运动");
        if(run.Mode==CalibrationMode.Ambient)
        {
            // Firmware metadata may be 0 even while actual signed int16 samples stream.
            // For the historical calibration use its own scale (Gyro 2000 -> 0.070),
            // never the MCU's 250 or an extra factor of 1/8.
            var r=SelectedImuFrame.FromSample(b,b.Samples[^1],b.Samples.Count-1,run);
            if(!r.HasComputedCalibration || r.PhysicalAcc is not { Length: 3 } ||
               r.PhysicalGyro is not { Length: 3 })
                throw new InvalidDataException("CT-05 前置检查：未能使用当前UID的常温JSON计算出真实六轴物理值："+r.Status);
        }
        else if(!b.AllUnitsValid || (b.FifoFlags & 0x0001)==0)
        {
            // Thermal model has a separate conversion contract and is not changed here.
            throw new InvalidDataException("CT-05 全温模式仍要求MCU量程和状态有效，防止错误使用全温换算");
        }
    }

    public async Task<StaticPointSamples> CaptureStaticPointAsync(string csvPath,TimeSpan duration,
        IProgress<string>? progress,CancellationToken ct)
    {
        var device=_imu()??throw new InvalidOperationException("IMU 未连接");
        if(!device.Connected||device.Identity is null)throw new IOException("未读取真实 UID");
        Directory.CreateDirectory(Path.GetDirectoryName(csvPath)!);
        var run=_run();
        run.Validate(device.Identity);
        var samples=new List<RealImuVector>();
        int batches=0,dup=0;uint? lastTick=null;double sumT=0;
        DateTimeOffset start=DateTimeOffset.UtcNow;
        await using var output=new FileStream(csvPath,FileMode.CreateNew,FileAccess.Write,FileShare.Read,
            32768,FileOptions.Asynchronous);
        await using var writer=new StreamWriter(output,new UTF8Encoding(true));
        await writer.WriteLineAsync("host_utc,mcu_tick_ms,frame_index,ax_g,ay_g,az_g,gx_dps,gy_dps,gz_dps,temp_c,odr_hz,raw_ax,raw_ay,raw_az,raw_gx,raw_gy,raw_gz,acc_input_fs_g,gyro_input_fs_dps,input_scale_source,sensor_ok_reported");
        var sw=System.Diagnostics.Stopwatch.StartNew();
        while(sw.Elapsed<duration)
        {
            ct.ThrowIfCancellationRequested();
            var b=await device.ReadBatchAsync(ct,requireSensorOk:run.Mode!=CalibrationMode.Ambient);
            if(run.Mode!=CalibrationMode.Ambient && !b.AllUnitsValid)
                throw new InvalidDataException("CT-05 全温模式仍要求MCU量程有效");
            if(b.FifoUnread==0||b.McuTickMs==lastTick){dup++;await Task.Delay(10,ct);continue;}
            lastTick=b.McuTickMs;batches++;sumT+=b.TemperatureC;
            for(int i=0;i<b.Samples.Count;i++)
            {
                var sample=b.Samples[i];
                double[] a, g;
                int usedAccFs=b.AccFsG,usedGyroFs=b.GyroFsDps;
                string scaleSource="MCU";
                if(run.Mode==CalibrationMode.Ambient)
                {
                    // Raw -> physical only. CT05's analysis applies the ACC matrix once.
                    // Applying the matrix here as well would double-calibrate.
                    var selected=SelectedImuFrame.FromSample(b,sample,i,run);
                    if(selected.PhysicalAcc is not { Length: 3 } ax ||
                       selected.PhysicalGyro is not { Length: 3 } gy)
                        throw new InvalidDataException("CT-05 单点采样无法进行JSON配套量程换算："+selected.Status);
                    a=ax;g=gy;
                    var scale=CalibrationInputScalePolicy.Resolve(run.Files!.Acc?.FsHint,
                        run.Files.Gyro?.FsHint,b.AccFsG,b.GyroFsDps)
                        ??throw new InvalidDataException("CT-05 无法确定标定文件的输入换算系数");
                    usedAccFs=scale.AccFullScaleG;usedGyroFs=scale.GyroFullScaleDps;
                    scaleSource=scale.AccFromJson && scale.GyroFromJson ? "UID_JSON" : "JSON_OR_MCU";
                }
                else
                {
                    a=new[]{sample.AxG,sample.AyG,sample.AzG};
                    g=new[]{sample.GxDps,sample.GyDps,sample.GzDps};
                }
                samples.Add(new RealImuVector(a[0],a[1],a[2],g[0],g[1],g[2],b.TemperatureC));
                var ci=CultureInfo.InvariantCulture;
                await writer.WriteLineAsync(string.Join(",",b.HostTimeUtc.ToString("O"),b.McuTickMs,
                    i,a[0].ToString("G17",ci),a[1].ToString("G17",ci),a[2].ToString("G17",ci),
                    g[0].ToString("G17",ci),g[1].ToString("G17",ci),g[2].ToString("G17",ci),
                    b.TemperatureC.ToString("G17",ci),b.OdrHz,
                    sample.RawAx,sample.RawAy,sample.RawAz,sample.RawGx,sample.RawGy,sample.RawGz,
                    usedAccFs,usedGyroFs,scaleSource,(b.FifoFlags&0x0001)!=0));
            }
            if(batches%20==0)progress?.Report($"静态逐点采集：{samples.Count} 帧 / {batches} 批，{sw.Elapsed.TotalSeconds:F1}s");
            await Task.Delay(10,ct);
        }
        await writer.FlushAsync(ct);
        return new StaticPointSamples(csvPath,samples,batches,start,DateTimeOffset.UtcNow,dup,
            batches>0?sumT/batches:double.NaN);
    }
}
