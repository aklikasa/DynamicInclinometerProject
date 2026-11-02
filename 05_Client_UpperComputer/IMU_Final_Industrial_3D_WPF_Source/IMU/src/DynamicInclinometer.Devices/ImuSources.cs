using System.IO;
using System.IO.Ports;
using System.Numerics;
using System.Diagnostics;
using System.Globalization;
using DynamicInclinometer.Core;
namespace DynamicInclinometer.Devices;

public interface IImuSource
{
    Task RunAsync(Action<ImuSample> onSample,Action<string> onStatus,CancellationToken ct);
}

public sealed class SimulatedImuSource(CalibrationProfile calibration):IImuSource
{
    public async Task RunAsync(Action<ImuSample> onSample,Action<string> onStatus,CancellationToken ct)
    {
        onStatus("SYNTHETIC 仿真：绝非设备精度实测");
        long n=0;
        const double fs=200.0;
        var clock=Stopwatch.StartNew();
        while(!ct.IsCancellationRequested)
        {
            // Construct consistent gravity and angular rates from q(t) = Rz(0) Ry(pitch) Rx(roll).
            double t=n/fs;
            double r=.17*Math.Sin(.7*t),p=.12*Math.Cos(.45*t);
            double rd=.17*.7*Math.Cos(.7*t),pd=-.12*.45*Math.Sin(.45*t);
            var q=Quaternion.CreateFromYawPitchRoll(0,(float)p,(float)r);
            var a=Vector3.Transform(Vector3.UnitZ,Quaternion.Inverse(q));
            var w=new Vector3((float)rd,(float)(pd*Math.Cos(r)),(float)(-pd*Math.Sin(r)))*(float)(180/Math.PI);
            // Synthetic sample is in platform frame, calibration inverse must be applied by demo caller.
            var rawAcc=MatrixMath.Apply(MatrixMath.Inverse(calibration.AccMatrix),a)+new Vector3((float)calibration.AccBias[0],(float)calibration.AccBias[1],(float)calibration.AccBias[2]);
            Vector3 rawGyro=calibration.HasGyro
               ? MatrixMath.Apply(MatrixMath.Inverse(calibration.GyroMatrix!),w)+new Vector3((float)calibration.GyroBiasDps![0],(float)calibration.GyroBiasDps[1],(float)calibration.GyroBiasDps[2])
               : Vector3.Zero;
            onSample(new ImuSample(n++,t,rawAcc,rawGyro,25,true,true,true,Stopwatch.GetTimestamp()));
            var due=TimeSpan.FromSeconds(n/fs-clock.Elapsed.TotalSeconds);
            if(due>TimeSpan.Zero)await Task.Delay(due,ct);else if(n%64==0)await Task.Yield();
        }
    }
}

/// <summary>Deterministic reference-following SYNTHETIC source; NEVER connects a physical turntable.</summary>
public sealed class SimulatedSineSweepSource(SineSweepPlan plan, CalibrationProfile calibration) : IImuSource
{
    public async Task RunAsync(Action<ImuSample> onSample,Action<string> onStatus,CancellationToken ct)
    {
        plan.Validate();
        onStatus($"自动正弦仿真 · {plan.Axis} · ±{plan.AmplitudeDeg:F2}° · {plan.FrequencyHz:F3} Hz · 不控制实机");
        var inverseAcc=MatrixMath.Inverse(calibration.AccMatrix);
        var inverseGyro=calibration.HasGyro ? MatrixMath.Inverse(calibration.GyroMatrix!) : null;
        var biasA=new Vector3((float)calibration.AccBias[0],(float)calibration.AccBias[1],(float)calibration.AccBias[2]);
        var biasG=calibration.HasGyro ? new Vector3((float)calibration.GyroBiasDps![0],(float)calibration.GyroBiasDps[1],(float)calibration.GyroBiasDps[2]) : Vector3.Zero;
        var clock=Stopwatch.StartNew();
        long samples=(long)Math.Ceiling(plan.DurationSeconds*plan.SampleHz);
        for(long i=0;i<=samples;i++)
        {
            ct.ThrowIfCancellationRequested();
            double t=Math.Min(plan.DurationSeconds,i/(double)plan.SampleHz);
            var (r,p)=plan.AnglesAt(t);
            var q=TiltMath.FromTilt(r,p);
            var expectedAcc=Vector3.Transform(Vector3.UnitZ,Quaternion.Inverse(q));
            double rate=plan.RateAt(t);
            var expectedGyro=plan.Axis==SweepAxis.Roll ? new Vector3((float)rate,0,0) : new Vector3(0,(float)rate,0);
            var acc=MatrixMath.Apply(inverseAcc,expectedAcc)+biasA;
            var gyro=inverseGyro!=null ? MatrixMath.Apply(inverseGyro,expectedGyro)+biasG : Vector3.Zero;
            onSample(new ImuSample(i,t,acc,gyro,25,true,true,true,Stopwatch.GetTimestamp()));
            var delay=t-clock.Elapsed.TotalSeconds;
            if(delay>.003)await Task.Delay(TimeSpan.FromSeconds(delay),ct);
            else if(i%64==0)await Task.Yield();
        }
        onStatus("正弦仿真采集完成；将生成仅用于代码验证的合成数据误差统计");
    }
}

public enum TimingPolicy
{
    UnresolvedBatch,
    EngineeringAssumptionLastSampleTick,
    FirmwareVerifiedLastSampleTick
}

/// <summary>Modbus 104-register protocol inherited from the original Python project.
/// The single MCU tick must be verified as referring to the LAST sample before using real-time fusion.
/// Engineer's override is explicitly marked unverified in data.</summary>
public sealed class SerialImuSource(string port,int baud=1500000,byte slave=1,int fallbackAcc=2,int fallbackGyro=2000,
    TimingPolicy timingPolicy=TimingPolicy.UnresolvedBatch,int fallbackOdr=0,int timeoutMs=1200,bool dtrRts=true):IImuSource
{
    public async Task RunAsync(Action<ImuSample> onSample,Action<string> onStatus,CancellationToken ct)
    {
        if(slave<1||slave>247)throw new ArgumentOutOfRangeException(nameof(slave));
        using var serial=CreatePort(port,baud,timeoutMs,dtrRts);
        serial.Open();onStatus($"连接 {port}/{baud}; slave={slave}; DTR/RTS={dtrRts}; 时间策略 {timingPolicy}; 参数未核实不可用于精度验收");
        long seq=0;uint? prevTick=null;long extendedMs=0;double prevSampleTime=double.NegativeInfinity;
        long lastHostFrameTick=0;
        bool hostClockFallback=false, warned=false;
        int consecutiveErrors=0;long validFrames=0;
        // Host monotonic time is used ONLY as an explicitly unverified engineering fallback.
        // It preserves continuous attitude output after a broken HAL_GetTick field, but
        // does not establish exact hardware sample times or certified dynamic accuracy.
        while(!ct.IsCancellationRequested)
        {
            try
            {
                serial.DiscardInBuffer(); var req=ImuProtocol.Request(slave);serial.Write(req,0,req.Length);
                byte[] header=ReadExactly(serial,3,ct,"应答头",req);
                if(header[0]!=slave)throw new InvalidDataException("Modbus 地址不匹配");
                if(header[1]==0x83)
                {
                    var exceptionTail=ReadExactly(serial,2,ct,"Modbus 异常帧尾",req);
                    var exc=header.Concat(exceptionTail).ToArray();
                    if(ImuProtocol.Crc(exc.AsSpan(0,3))!=(ushort)(exc[3]|(exc[4]<<8)))throw new InvalidDataException("异常响应 CRC 错误");
                    throw new InvalidDataException($"设备返回 Modbus exception {header[2]:X2}");
                }
                if(header[1]!=3||header[2]!=208)throw new InvalidDataException("Modbus 功能码/长度异常");
                byte[] packet=header.Concat(ReadExactly(serial,210,ct,"208字节数据+CRC",req)).ToArray();
                var f=ImuProtocol.Decode(ImuProtocol.ParseReply(packet,slave),fallbackAcc,fallbackGyro);
                validFrames++;
                long hostFrameTick=Stopwatch.GetTimestamp();
                if(validFrames==1)onStatus($"接收到真实 Modbus 帧：{port}；开始逐样本解析");
                if(!f.ConfigurationVerified&&!warned)
                {
                    onStatus("量程或 ODR 尚未可靠上报：可进行研究级实时融合，无法据此确认动态精度");
                    warned=true;
                }
                if(f.Samples.All(x=>x.acc.LengthSquared()==0 && x.gyro.LengthSquared()==0))
                {
                    consecutiveErrors=0;lastHostFrameTick=hostFrameTick;continue;
                }
                // The ODR register may encode an enum, not a rate in Hz. If absent or
                // implausible, use the explicitly chosen candidate, never call it verified.
                int odr=timingPolicy==TimingPolicy.FirmwareVerifiedLastSampleTick &&
                    f.Odr is >=10 and <=6667 ? f.Odr : fallbackOdr;
                bool reconstruction=timingPolicy!=TimingPolicy.UnresolvedBatch && odr>=10 && odr<=6667;
                if(reconstruction && prevTick.HasValue && !hostClockFallback)
                {
                    uint diff=unchecked(f.TickMs-prevTick.Value); // normal uint32 rollover
                    double hostGap=lastHostFrameTick>0?
                        (hostFrameTick-lastHostFrameTick)/(double)Stopwatch.Frequency:0;
                    // Reject a raw tick leap inconsistent with actual elapsed host time.
                    // Such jumps often indicate incorrect register mapping / MCU restart.
                    if(diff>10_000 || (hostGap>0 && diff>Math.Max(2000,hostGap*1000*8)))
                    {
                        hostClockFallback=true;
                        onStatus($"MCU tick 异常：prev={prevTick.Value}, curr={f.TickMs}, delta={diff}ms, hostGap={hostGap:F3}s；"+
                            "已切换到主机单调时钟批次重建，仅用于实时研究显示，不能用于精度验收。请核查固件tick/字序/复位。");
                    }
                    else if(diff==0)
                    {
                        // Do not double integrate a repeated FIFO batch.
                        consecutiveErrors=0;lastHostFrameTick=hostFrameTick;continue;
                    }
                    else extendedMs+=diff;
                }
                else if(!prevTick.HasValue) extendedMs=f.TickMs;
                prevTick=f.TickMs;
                double last=extendedMs/1000.0;
                if(hostClockFallback)
                {
                    double elapsed=lastHostFrameTick>0?
                        Math.Max(0,(hostFrameTick-lastHostFrameTick)/(double)Stopwatch.Frequency):0;
                    // Do not compress 16 samples into one reception time; preserve the
                    // monotonic batch elapsed time while making timing uncertainty visible.
                    last=double.IsFinite(prevSampleTime)?
                        prevSampleTime+Math.Max(elapsed,f.Samples.Count/(double)Math.Max(1,odr)):
                        f.Samples.Count/(double)Math.Max(1,odr);
                }
                bool timeVerified=!hostClockFallback &&
                    timingPolicy==TimingPolicy.FirmwareVerifiedLastSampleTick &&
                    f.ConfigurationVerified && odr==f.Odr;
                int count=f.Samples.Count;
                for(int i=0;i<count;i++)
                {
                    double t=reconstruction?last-(count-1-i)/(double)odr:last;
                    if(reconstruction && t<=prevSampleTime)continue;
                    prevSampleTime=t;
                    var (acc,gyro)=f.Samples[i];
                    onSample(new ImuSample(seq++,t,acc,gyro,f.TempC,f.AccFsVerified&&f.GyroFsVerified,timeVerified,false,Stopwatch.GetTimestamp()));
                }
                lastHostFrameTick=hostFrameTick;
                consecutiveErrors=0;
            }
            catch(OperationCanceledException){break;}
            catch(Exception ex) when(ex is not OperationCanceledException)
            {
                consecutiveErrors++;
                if(consecutiveErrors<=2)onStatus($"Modbus 响应错误（{consecutiveErrors}/3）：{ex.Message}。当前 {port}/{baud}/slave={slave}/DTR+RTS={dtrRts}");
                if(consecutiveErrors>=3)throw new IOException($"连续 {consecutiveErrors} 次 Modbus 解码或通信失败（已成功帧数 {validFrames}）：{ex.Message}。参数 {port}/{baud}/slave={slave}/DTR+RTS={dtrRts}。请使用【检查 IMU 通信】查看 TX/RX 字节，再核查设备供电、接线、端口及固件。",ex);
                await Task.Delay(150,ct);
            }
        }
    }
    private static SerialPort CreatePort(string name,int speed,int timeout,bool dtrRts)
    {
        // pyserial (used in the working Python tool) defaults to DTR=True and RTS=True on open;
        // System.IO.Ports defaults both to false. Expose this difference for real equipment diagnosis.
        return new SerialPort(name,speed,Parity.None,8,StopBits.One)
        {
            ReadTimeout=timeout,WriteTimeout=timeout,
            Handshake=Handshake.None,DtrEnable=dtrRts,RtsEnable=dtrRts,
            ReadBufferSize=8192,WriteBufferSize=2048
        };
    }

    /// <summary>One read-only Modbus diagnostic transaction. No calibration required; never touches the turntable.</summary>
    public static string Probe(string port,int baud,byte slave,int timeoutMs,bool dtrRts)
    {
        using var serial=CreatePort(port,baud,timeoutMs,dtrRts);
        serial.Open();
        serial.DiscardInBuffer();
        var req=ImuProtocol.Request(slave);
        serial.Write(req,0,req.Length);
        try
        {
            var header=ReadExactly(serial,3,CancellationToken.None,"应答头",req);
            if(header[0]!=slave)throw new InvalidDataException($"收到地址 {header[0]}，但请求地址是 {slave}。RX头：{Convert.ToHexString(header)}");
            if(header[1]==0x83)
            {
                var tail=ReadExactly(serial,2,CancellationToken.None,"Modbus异常帧",req);
                var exceptionFrame=header.Concat(tail).ToArray();
                if(ImuProtocol.Crc(exceptionFrame.AsSpan(0,3)) != (ushort)(exceptionFrame[3]|(exceptionFrame[4]<<8)))
                    throw new InvalidDataException("Modbus异常帧 CRC 校验失败："+Convert.ToHexString(exceptionFrame));
                return $"设备已响应，但返回异常码 0x{header[2]:X2}；请核查寄存器1000、数量104和功能码03。TX={Convert.ToHexString(req)} RX={Convert.ToHexString(exceptionFrame)}";
            }
            if(header[1]!=3||header[2]!=208)throw new InvalidDataException($"收到了 {Convert.ToHexString(header)}，但预期 01 03 D0（208字节）；可能协议不匹配。");
            var rest=ReadExactly(serial,210,CancellationToken.None,"208字节数据+CRC",req);
            var words=ImuProtocol.ParseReply(header.Concat(rest).ToArray(),slave);
            return $"Modbus 链路成功：{port}/{baud}，收到 213 字节完整响应、CRC 正确。"+
                   $" MCU tick={words[98]|((uint)words[99]<<16)}，ACC量程寄存器={words[100]}，GYRO量程寄存器={words[101]}，ODR字段={words[102]}，FIFO={words[103]}。"+
                   " 注意：字段是否代表实际配置仍须对照固件验证。";
        }
        catch(Exception ex)
        {
            throw new IOException($"一次性诊断失败：{port}/{baud}/slave={slave}，DTR+RTS={dtrRts}，timeout={timeoutMs}ms；TX={Convert.ToHexString(req)}。原因：{ex.Message}。"+
                " 如 RX=0 字节，请检查真正的 IMU COM、接口方向、供电、串口被占用、波特率/站号，并可对照旧 Python 同端口是否能读。",ex);
        }
    }

    private static byte[] ReadExactly(SerialPort serial,int length,CancellationToken ct,string phase,byte[] request)
    {
        var packet=new byte[length];int got=0;
        while(got<length)
        {
            ct.ThrowIfCancellationRequested();
            int n;
            try {n=serial.Read(packet,got,length-got);}
            catch(TimeoutException ex)
            {
                throw new IOException($"{phase}读取超时：收到 {got}/{length} 字节；RX={Convert.ToHexString(packet.AsSpan(0,got))}；TX={Convert.ToHexString(request)}。"+
                    (got==0?"未收到该阶段任何字节。":"已收到部分数据，请检查响应长度、串口缓冲与固件协议。"),ex);
            }
            if(n<=0)throw new IOException($"{phase}：串口无有效数据；已接收 {got}/{length} 字节");
            got+=n;
        }
        return packet;
    }

}

public sealed class ReplayImuSource(string path,double speed=1.0):IImuSource
{
    public async Task RunAsync(Action<ImuSample> onSample,Action<string> onStatus,CancellationToken ct)
    {
        onStatus("历史数据回放："+Path.GetFileName(path));
        using var reader=new StreamReader(path);
        var heading=await reader.ReadLineAsync(ct);
        if(heading is null || !heading.StartsWith("seq,time_s,",StringComparison.Ordinal))throw new InvalidDataException("不是实验录制的 raw_processed.csv");
        double? first=null;var clock=Stopwatch.StartNew();string? line;
        while((line=await reader.ReadLineAsync(ct))!=null)
        {
            if(string.IsNullOrWhiteSpace(line))continue;
            var s=line.Split(','); if(s.Length<13)throw new InvalidDataException("记录列数不正确");
            var c=CultureInfo.InvariantCulture;
            var sample=new ImuSample(long.Parse(s[0],c),double.Parse(s[1],c),
                new Vector3(float.Parse(s[2],c),float.Parse(s[3],c),float.Parse(s[4],c)),
                new Vector3(float.Parse(s[5],c),float.Parse(s[6],c),float.Parse(s[7],c)),
                double.Parse(s[8],c),bool.Parse(s[10]),bool.Parse(s[11]),bool.Parse(s[9]),s.Length>21?long.Parse(s[21],c):0);
            first??=sample.TimeSeconds;
            if(speed>0 && speed<100)
            {
                var delay=(sample.TimeSeconds-first.Value)/speed-clock.Elapsed.TotalSeconds;
                if(delay>0.003)await Task.Delay(TimeSpan.FromSeconds(delay),ct);
            }
            onSample(sample);
        }
    }
}
