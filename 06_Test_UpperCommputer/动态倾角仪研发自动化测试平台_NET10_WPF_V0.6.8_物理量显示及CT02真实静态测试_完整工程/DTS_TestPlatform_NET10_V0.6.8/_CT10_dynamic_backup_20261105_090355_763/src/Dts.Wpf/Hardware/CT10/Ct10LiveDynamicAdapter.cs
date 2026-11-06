using System.Collections.Concurrent;
using System.Diagnostics;
using System.Text.Json;
using Dts.Core;
using Dts.Devices;
using Dts.TestEngine;
using Dts.Tests.S1.CT10;

namespace Dts.Wpf.Hardware.CT10;

/// <summary>
/// Real device connection for CT-10. Uses existing shared locks, real Modbus FIFO and real
/// 2TD-600 driver feedback. This is an *engineering diagnostic*, not certified time sync.
/// The firmware exposes only batch-level tick, not per-frame sensor acquisition time;
/// use ONE operator-verified latest FIFO slot per successful poll stamped at HOST RECEIVE.
/// The profile must document that interpretation. No fictitious 16 precise timestamps.
/// </summary>
public sealed class Ct10LiveDynamicAdapter : ICt10DynamicHardware
{
    private readonly LiveTestHardware _host;
    private readonly Func<RealImu?> _imu;
    private readonly Func<IRealTurntable?> _table;
    private readonly Func<CalibrationRun> _calibration;
    private readonly string _profilePath;
    private int _inSweep;

    public Ct10LiveDynamicAdapter(LiveTestHardware host, Func<RealImu?> imu,
        Func<IRealTurntable?> table, Func<CalibrationRun> calibration, string profilePath)
    {
        _host=host;_imu=imu;_table=table;_calibration=calibration;
        _profilePath=profilePath;
    }

    private Ct10DeviceProfile? Profile()
    {
        try
        {
            if (!File.Exists(_profilePath)) return null;
            var p=JsonSerializer.Deserialize<Ct10DeviceProfile>(File.ReadAllText(_profilePath),
                new JsonSerializerOptions {PropertyNameCaseInsensitive=true});
            if (p is null || p.Enabled!=true || !p.FirmwareNewestSlotConfirmed ||
                string.IsNullOrWhiteSpace(p.FirmwareEvidence) ||
                string.IsNullOrWhiteSpace(p.SpeedLimitEvidence) ||
                !double.IsFinite(p.InnerConfirmedSpeedLimitDps) ||
                !double.IsFinite(p.OuterConfirmedSpeedLimitDps) ||
                p.InnerConfirmedSpeedLimitDps is <=0 or >60 ||
                p.OuterConfirmedSpeedLimitDps is <=0 or >60 ||
                p.NewestFifoSlot is <0 or >15 ||
                !double.IsFinite(p.MaximumImuReadMs) || p.MaximumImuReadMs is <1 or >200 ||
                !double.IsFinite(p.MaximumEncoderReadMs) || p.MaximumEncoderReadMs is <1 or >500 ||
                !double.IsFinite(p.MinimumEncoderRateHz) || p.MinimumEncoderRateHz is <1 or >50 ||
                !double.IsFinite(p.MaxObservedTimingUncertaintyMs) ||
                p.MaxObservedTimingUncertaintyMs is <=0 or >100)
                return null;
            return p;
        }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException or JsonException)
        { return null; }
    }

    public bool IsRealDynamicCaptureReady => Profile() is not null &&
        _imu() is {Connected:true,Identity:not null} && _table() is Td600 {Connected:true} &&
        _host.IsTwoTdConnected && _calibration().Mode == CalibrationMode.Ambient;

    public string HardwareSourceDescription =>
        "真实Modbus FIFO选定固件确认槽位(每批1帧，主机接收时标)+2TD600.dll编码器实测。"+
        "非硬件同步，接收时间≠传感器采样时间；仅工程诊断。配置："+_profilePath;

    public string CurrentUidHex => _imu()?.Identity?.UidHex ?? "";
    public double MaximumCertifiedSpeedDps(Ct10Axis axis)
    {
        var p=Profile();
        return p is null ? double.NaN :
            axis==Ct10Axis.Inner ? p.InnerConfirmedSpeedLimitDps : p.OuterConfirmedSpeedLimitDps;
    }

    public async Task<Ct10StageStatus> ReadStageAsync(CancellationToken ct)
    {
        long began=Stopwatch.GetTimestamp();
        var feedback=await _host.ReadTwoTdAsync(ct);
        long ended=Stopwatch.GetTimestamp();
        // Time is the midpoint of a real multi-command vendor read, not the device's own sample time.
        long at=began+(ended-began)/2;
        static bool Still(RealAxisFeedback a) => a.Normal && a.Enabled==true &&
            a.InPlace==true && Math.Abs(a.SpeedDps)<=0.05;
        return new Ct10StageStatus(at,feedback.Inner.PositionDeg,feedback.Outer.PositionDeg,
            feedback.Inner.Enabled==true,feedback.Outer.Enabled==true,
            feedback.Inner.Normal,feedback.Outer.Normal,
            Still(feedback.Inner),Still(feedback.Outer),
            feedback.Inner.Detail+" | "+feedback.Outer.Detail);
    }

    public async Task MoveToSafeStartAsync(Ct10Axis axis,double startDeg,double speedDps,
        double allowedMinDeg,double allowedMaxDeg,CancellationToken ct)
    {
        if (!IsRealDynamicCaptureReady) throw new InvalidOperationException("CT-10动态硬件验证未就绪");
        var max=MaximumCertifiedSpeedDps(axis);
        if (!double.IsFinite(startDeg) || startDeg < allowedMinDeg ||
            startDeg > allowedMaxDeg || !double.IsFinite(speedDps) ||
            speedDps <= 0 || speedDps > max)
            throw new InvalidDataException("起点或准备速度超出现场确认范围");
        var b=await ReadStageAsync(ct);
        EnsureSafeFeedback(b,allowedMinDeg,allowedMaxDeg);
        // The 2TD manual requires outer 0 before moving the inner axis; we enforce
        // that sequence even if the axis currently already seems at its start.
        await MoveAndConfirmAsync(Ct10Axis.Outer,0,speedDps,allowedMinDeg,allowedMaxDeg,ct);
        if (axis == Ct10Axis.Inner)
            await MoveAndConfirmAsync(Ct10Axis.Inner,startDeg,speedDps,allowedMinDeg,allowedMaxDeg,ct);
        else
        {
            await MoveAndConfirmAsync(Ct10Axis.Inner,0,speedDps,allowedMinDeg,allowedMaxDeg,ct);
            await MoveAndConfirmAsync(Ct10Axis.Outer,startDeg,speedDps,allowedMinDeg,allowedMaxDeg,ct);
        }
        var end=await ReadStageAsync(ct);
        EnsureSafeFeedback(end,allowedMinDeg,allowedMaxDeg);
        if (!end.InnerStationary || !end.OuterStationary ||
            Math.Abs((axis==Ct10Axis.Inner?end.InnerPositionDeg:end.OuterPositionDeg)-startDeg)>0.25 ||
            Math.Abs((axis==Ct10Axis.Inner?end.OuterPositionDeg:end.InnerPositionDeg))>0.25)
            throw new IOException("准备定位后目标/固定轴反馈未通过确认");
    }

    private async Task MoveAndConfirmAsync(Ct10Axis axis,double target,double speed,
        double min,double max,CancellationToken ct)
    {
        if (target < min || target > max) throw new InvalidOperationException("绝对目标超出允许行程");
        var start=await ReadStageAsync(ct);
        EnsureSafeFeedback(start,min,max);
        double current=axis==Ct10Axis.Inner?start.InnerPositionDeg:start.OuterPositionDeg;
        if (Math.Abs(current-target)<0.1 &&
            (axis==Ct10Axis.Inner?start.InnerStationary:start.OuterStationary)) return;
        await _host.SetTwoTdAbsoluteAsync((int)axis,target,speed,ct);
        var sw=Stopwatch.StartNew();int stable=0;
        double seconds=Math.Min(600,Math.Max(35,Math.Abs(target-current)/speed*2.5+30));
        while(sw.Elapsed.TotalSeconds<seconds)
        {
            ct.ThrowIfCancellationRequested();
            await Task.Delay(180,ct);
            var fb=await ReadStageAsync(ct);
            EnsureSafeFeedback(fb,min,max);
            bool arriving=axis==Ct10Axis.Inner ?
                fb.InnerStationary && Math.Abs(fb.InnerPositionDeg-target)<0.15 :
                fb.OuterStationary && Math.Abs(fb.OuterPositionDeg-target)<0.15;
            stable=arriving?stable+1:0;
            if(stable>=3)return;
        }
        throw new TimeoutException($"准备定位超时：{axis} -> {target:F2}°");
    }

    private static void EnsureSafeFeedback(Ct10StageStatus b,double min,double max)
    {
        if(!b.InnerEnabled || !b.OuterEnabled || !b.InnerNormal || !b.OuterNormal ||
            !double.IsFinite(b.InnerPositionDeg) || !double.IsFinite(b.OuterPositionDeg) ||
            b.InnerPositionDeg < min-0.3 || b.InnerPositionDeg > max+0.3 ||
            b.OuterPositionDeg < min-0.3 || b.OuterPositionDeg > max+0.3)
            throw new IOException("转台反馈报警、失能或超出现场批准行程："+b.Detail);
    }

    public async Task<Ct10Capture> ExecuteSynchronizedSweepAsync(Ct10SweepRequest request,
        IProgress<string>? progress,CancellationToken ct)
    {
        if(Interlocked.CompareExchange(ref _inSweep,1,0)!=0)
            throw new InvalidOperationException("已有一段CT-10动态扫描进行中");
        try
        {
            var p=Profile() ?? throw new InvalidOperationException("未提供经过核实的CT-10动态采集配置");
            var imu=_imu() ?? throw new InvalidOperationException("真实IMU未连接");
            var expectedUid=imu.Identity?.UidHex ?? throw new InvalidOperationException("IMU UID不可用");
            if(!imu.Connected || _table() is not Td600 {Connected:true})
                throw new InvalidOperationException("动态采样设备连接已丢失");
            if(!double.IsFinite(request.CommandDps) || request.CommandDps <=0 ||
                request.CommandDps > MaximumCertifiedSpeedDps(request.Axis) ||
                request.StartDeg<request.AllowedMinDeg || request.EndDeg>request.AllowedMaxDeg ||
                request.StartDeg>request.AllowedMaxDeg || request.EndDeg<request.AllowedMinDeg ||
                request.OtherAxisHoldDeg!=0)
                throw new InvalidOperationException("扫描命令超出已核实的速度/绝对行程");
            var calibration=_calibration();
            if(calibration.Mode!=CalibrationMode.Ambient) throw new InvalidOperationException("必须使用UID对应常温JSON");
            calibration.Validate(imu.Identity!);
            var gyro=calibration.Files?.Gyro ?? throw new InvalidDataException("Gyro JSON缺失");
            var scale=CalibrationInputScalePolicy.Resolve(calibration.Files?.Acc?.FsHint,gyro.FsHint,0,0)
                ?? throw new InvalidDataException("历史JSON缺少有效的输入量程");
            using var timeout=CancellationTokenSource.CreateLinkedTokenSource(ct);
            timeout.CancelAfter(TimeSpan.FromSeconds(request.SafetyTimeoutSeconds));
            var token=timeout.Token;
            var enc=new ConcurrentQueue<Ct10EncoderFrame>();
            var gyroFrames=new ConcurrentQueue<Ct10GyroFrame>();
            var encoderReady=new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
            var imuReady=new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
            var arrived=new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
            bool motionStarted=false;
            async Task EncoderLoop()
            {
                int polls=0;int stable=0;bool leftStart=false;
                while(!token.IsCancellationRequested)
                {
                    long a=Stopwatch.GetTimestamp();
                    var b=await _host.ReadTwoTdAsync(token);
                    long z=Stopwatch.GetTimestamp();
                    double elapsedMs=(z-a)*1000d/Stopwatch.Frequency;
                    if(elapsedMs>p.MaximumEncoderReadMs)
                        throw new IOException($"2TD反馈采集耗时{elapsedMs:F1}ms，超过配置上限");
                    var item=new Ct10EncoderFrame(a+(z-a)/2,b.Inner.PositionDeg,b.Outer.PositionDeg,
                        b.Inner.Normal,b.Outer.Normal,b.Inner.Enabled==true,b.Outer.Enabled==true);
                    if(!item.InnerNormal || !item.OuterNormal || !item.InnerEnabled || !item.OuterEnabled)
                        throw new IOException("2TD动态读取中发生报警或失能");
                    var pos=request.Axis==Ct10Axis.Inner?b.Inner.PositionDeg:b.Outer.PositionDeg;
                    var other=request.Axis==Ct10Axis.Inner?b.Outer.PositionDeg:b.Inner.PositionDeg;
                    if(!double.IsFinite(pos) || !double.IsFinite(other) ||
                        pos<request.AllowedMinDeg-0.3 || pos>request.AllowedMaxDeg+0.3 ||
                        Math.Abs(other)>0.3)
                        throw new IOException("运动中超出批准行程或固定轴离开0°");
                    enc.Enqueue(item);polls++;
                    if(polls>=3)encoderReady.TrySetResult();
                    if(motionStarted)
                    {
                        if(Math.Abs(pos-request.StartDeg)>0.5)leftStart=true;
                        bool ended=leftStart && Math.Abs(pos-request.EndDeg)<=0.15 &&
                            Math.Abs(request.Axis==Ct10Axis.Inner?b.Inner.SpeedDps:b.Outer.SpeedDps)<0.05 &&
                            (request.Axis==Ct10Axis.Inner?b.Inner.InPlace:b.Outer.InPlace)==true;
                        stable=ended?stable+1:0;
                        if(stable>=3) arrived.TrySetResult();
                    }
                    await Task.Delay(TimeSpan.FromSeconds(1/Math.Max(1,p.MinimumEncoderRateHz)),token);
                }
            }
            async Task GyroLoop()
            {
                int samples=0;uint? lastTick=null;long lastStamp=0;
                while(!token.IsCancellationRequested)
                {
                    long a=Stopwatch.GetTimestamp();
                    var batch=await imu.ReadBatchAsync(token,requireSensorOk:false);
                    long z=Stopwatch.GetTimestamp();
                    double elapsedMs=(z-a)*1000d/Stopwatch.Frequency;
                    if(elapsedMs>p.MaximumImuReadMs)
                        throw new IOException($"IMU单批读取耗时{elapsedMs:F1}ms，超过核验上限");
                    if((batch.FifoFlags & 0x0001)==0 || (batch.FifoFlags & 0x0002)!=0 ||
                        batch.FifoUnread==0 || batch.Samples.Count!=16 || batch.OdrHz==0)
                        throw new InvalidDataException("运动中IMU FIFO无效、模拟模式或ODR未知");
                    if(imu.Identity?.UidHex!=expectedUid)
                        throw new InvalidDataException("运动中IMU UID发生变化");
                    if(lastTick is not null && (uint)(batch.McuTickMs-lastTick.Value)==0)
                    { await Task.Delay(10,token); continue; }
                    if(lastTick is not null && (uint)(batch.McuTickMs-lastTick.Value)>1000)
                        throw new InvalidDataException("MCU批次时钟存在超过1秒的中断");
                    lastTick=batch.McuTickMs;
                    var frame=batch.Samples[p.NewestFifoSlot];
                    // This is NOT a hardware sample timestamp! It is real host receipt time.
                    // Only one verified latest slot per batch is used, not invented 16 timestamps.
                    // A commissioning test must establish a bound on timestamp uncertainty.
                    long stamp=z;
                    if(stamp<=lastStamp) throw new InvalidDataException("主机接收时间倒退");
                    lastStamp=stamp;
                    gyroFrames.Enqueue(new Ct10GyroFrame(stamp,
                        frame.RawGx*scale.GyroDpsPerLsb,frame.RawGy*scale.GyroDpsPerLsb,
                        frame.RawGz*scale.GyroDpsPerLsb,batch.TemperatureC,
                        frame.RawGx,frame.RawGy,frame.RawGz));
                    samples++;if(samples>=3)imuReady.TrySetResult();
                    await Task.Delay(8,token);
                }
            }
            Task encoderTask=Task.Run(EncoderLoop,CancellationToken.None);
            Task imuTask=Task.Run(GyroLoop,CancellationToken.None);
            try
            {
                var arm=Task.WhenAll(encoderReady.Task,imuReady.Task);
                var armed=await Task.WhenAny(arm,encoderTask,imuTask,Task.Delay(12000,token));
                if(armed!=arm)
                {
                    if(armed==encoderTask)await encoderTask;
                    if(armed==imuTask)await imuTask;
                    throw new TimeoutException("动态IMU或编码器采集无法在12秒内预置到可采样状态");
                }
                await arm;
                token.ThrowIfCancellationRequested();
                // Both real telemetry streams have been armed BEFORE the motion command.
                motionStarted=true;
                await _host.SetTwoTdAbsoluteAsync((int)request.Axis,request.EndDeg,request.CommandDps,token);
                progress?.Report($"CT-10 真实动态采集：{request.Axis} {request.CommandDps:F2}°/s");
                var completed=await Task.WhenAny(arrived.Task,encoderTask,imuTask,
                    Task.Delay(TimeSpan.FromSeconds(request.SafetyTimeoutSeconds),token));
                if(completed!=arrived.Task)
                {
                    if(completed==encoderTask)await encoderTask;
                    if(completed==imuTask)await imuTask;
                    throw new TimeoutException("转台动态扫描未收到到位反馈，或遥测流已中断");
                }
                await arrived.Task;
                // Extra validation: enough real samples & encoder feedback; no need to synthesize frames.
                var gyros=gyroFrames.ToArray();var encoders=enc.ToArray();
                if(gyros.Length<20 || encoders.Length<12)
                    throw new InvalidDataException("动态采样数量不足，不计算残差");
                double encoderSpan=(encoders[^1].TimestampTicks-encoders[0].TimestampTicks)/(double)Stopwatch.Frequency;
                if(encoderSpan<=0 || encoders.Length/encoderSpan<p.MinimumEncoderRateHz*0.65)
                    throw new InvalidDataException("转台反馈平均轮询率太低，不能微分得出可信参考速度");
                return new Ct10Capture(expectedUid,
                    "REAL_IMU_LATEST_SLOT_HOST_RECEIPT_APPROX + REAL_TD600_ENCODER; DIAGNOSTIC_NOT_HARDWARE_SYNC",
                    Stopwatch.Frequency,scale.GyroFullScaleDps,gyros,encoders,true,
                    $"gyro timestamp=host receive Stopwatch tick (not sensor sample instant). "+
                    $"FIFO slot={p.NewestFifoSlot}; confirmed firmware ref={p.FirmwareEvidence}; "+
                    $"time uncertainty verified <= {p.MaxObservedTimingUncertaintyMs:F2} ms; "+
                    $"speed-limit evidence={p.SpeedLimitEvidence}; no per-frame hardware synchronization.");
            }
            finally
            {
                timeout.Cancel();
                Exception? workerFault=null;
                foreach(var worker in new[]{encoderTask,imuTask})
                {
                    try{await worker;}
                    catch(OperationCanceledException){}
                    catch(Exception ex)
                    {
                        workerFault ??=ex;
                        progress?.Report("CT-10遥测任务终止："+ex.Message);
                    }
                }
                if(workerFault is not null)
                    throw new IOException("动态扫描存在设备遥测异常，本段结果不得用于分析",workerFault);
            }
        }
        catch
        {
            // Fail-safe stop. Outer CT-10 Test also issues stop in its own finally block.
            using var emergency=new CancellationTokenSource(TimeSpan.FromSeconds(8));
            try{await _host.StopTwoTdBothAsync(emergency.Token);}catch{}
            throw;
        }
        finally {Interlocked.Exchange(ref _inSweep,0);}
    }

    public Task StopBothAxesAsync(CancellationToken ct)=>_host.StopTwoTdBothAsync(ct);
}

/// <summary>Bench-specific commissioning record. Nothing here is populated with guessed limits.</summary>
public sealed record Ct10DeviceProfile(
    bool Enabled,
    bool FirmwareNewestSlotConfirmed,
    int NewestFifoSlot,
    string FirmwareEvidence,
    double InnerConfirmedSpeedLimitDps,
    double OuterConfirmedSpeedLimitDps,
    string SpeedLimitEvidence,
    double MaximumImuReadMs,
    double MaximumEncoderReadMs,
    double MinimumEncoderRateHz,
    double MaxObservedTimingUncertaintyMs);
