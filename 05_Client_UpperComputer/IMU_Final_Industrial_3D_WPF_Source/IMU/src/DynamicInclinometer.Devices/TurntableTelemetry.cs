using System.Globalization;
using System.IO;
using System.Runtime.InteropServices;
using System.Diagnostics;

namespace DynamicInclinometer.Devices;

/// <summary>
/// Native turntable adapter, including guarded motor commands.
/// OpenPort/Position/Stop/Enable signatures match an earlier Python driver.
/// SetAxisSway and SetAxisFindZero signatures were confirmed against the legacy Python ctypes wrapper and DLL exports.
/// Successful real motor behavior must still be verified at the installation site.
/// The native library is copied alongside app; startup is opt-in and controlled by the user.
/// </summary>
public sealed class TurntableTelemetry : IDisposable
{
    private readonly Stopwatch _clock=Stopwatch.StartNew();
    public bool IsOpen {get;private set;}
    public string Port {get;private set;}="";
    [DllImport("2TD600.dll",CallingConvention=CallingConvention.Cdecl,EntryPoint="OpenPort")]
    private static extern int OpenPort(int com,int baud);
    [DllImport("2TD600.dll",CallingConvention=CallingConvention.Cdecl,EntryPoint="ClosePort")]
    private static extern void ClosePort();
    [DllImport("2TD600.dll",CallingConvention=CallingConvention.Cdecl,EntryPoint="GetPosition")]
    private static extern double GetPosition(int axis);
    [DllImport("2TD600.dll",CallingConvention=CallingConvention.Cdecl,EntryPoint="GetSpeed")]
    private static extern double GetSpeed(int axis);
    [DllImport("2TD600.dll",CallingConvention=CallingConvention.Cdecl,EntryPoint="GetAxisEnable")]
    private static extern int GetAxisEnable(int axis);
    [DllImport("2TD600.dll",CallingConvention=CallingConvention.Cdecl,EntryPoint="GetAxisNormal")]
    private static extern int GetAxisNormal(int axis);

    public void Open(string port,int baud=115200)
    {
        if(IsOpen)throw new InvalidOperationException("转台已经连接");
        if(!port.StartsWith("COM",StringComparison.OrdinalIgnoreCase)||!int.TryParse(port[3..],NumberStyles.Integer,CultureInfo.InvariantCulture,out int number)||number<1)
          throw new ArgumentException("转台端口格式为 COMn",nameof(port));
        if(OpenPort(number,baud)!=1)throw new IOException("2TD600 OpenPort != 1：未确认连接，禁止运动");
        Port=port;IsOpen=true;
    }
    public TurntableReadback Read()
    {
        if(!IsOpen)throw new InvalidOperationException("转台未连接");
        var inner=ReadAxis(0); var outer=ReadAxis(2);
        return new TurntableReadback(_clock.Elapsed.TotalSeconds,Stopwatch.GetTimestamp(),inner,outer);
    }
    private static AxisFeedback ReadAxis(int axis)
    {
        double pos=GetPosition(axis),speed=GetSpeed(axis);
        int enabled=GetAxisEnable(axis),normal=GetAxisNormal(axis);
        if(!double.IsFinite(pos)||!double.IsFinite(speed)||enabled is not (0 or 1)||normal is not (0 or 1))
          throw new IOException("转台反馈异常 / 有无效的状态码");
        return new AxisFeedback(axis,pos,speed,enabled==1,normal==1);
    }
    // Signatures below are matched to the supplied working Python ctypes driver.
    [DllImport("2TD600.dll", CallingConvention=CallingConvention.Cdecl, EntryPoint="GetAxisFindZero")]
    private static extern int GetAxisFindZero(int axis);
    [DllImport("2TD600.dll", CallingConvention=CallingConvention.Cdecl, EntryPoint="GetAxisLock")]
    private static extern int GetAxisLock(int axis);
    [DllImport("2TD600.dll", CallingConvention=CallingConvention.Cdecl, EntryPoint="GetRunMode")]
    private static extern int GetRunMode(int axis);
    [DllImport("2TD600.dll", CallingConvention=CallingConvention.Cdecl, EntryPoint="SetAxisFindZero")]
    private static extern int NativeFindZero(int axis,double targetSpeed,double targetAcceleration);
    [DllImport("2TD600.dll", CallingConvention=CallingConvention.Cdecl, EntryPoint="SetAxisSway")]
    private static extern int NativeSway(int axis,double targetAmplitude,double targetFrequency);
    [DllImport("2TD600.dll", CallingConvention=CallingConvention.Cdecl, EntryPoint="SetAxisEnable")]
    private static extern int NativeEnable(int axis);
    [DllImport("2TD600.dll", CallingConvention=CallingConvention.Cdecl, EntryPoint="SetAxisDisable")]
    private static extern int NativeDisable(int axis);
    // ABI (int,double,double)->int cross-checked with legacy Python and 64-bit DLL export.
    // This does not certify on-site motion direction, response, or safety.
    public const bool SwayAbiVerified=true;
    [DllImport("2TD600.dll", CallingConvention=CallingConvention.Cdecl, EntryPoint="SetAxisStop")]
    private static extern int NativeStop(int axis);
    [DllImport("2TD600.dll", CallingConvention=CallingConvention.Cdecl, EntryPoint="SetAxisPosition")]
    private static extern int NativePosition(int axis, double position360, double speedDps);
    // Verified against the user-supplied legacy ctypes driver AND the DLL exports.
    [DllImport("2TD600.dll", CallingConvention=CallingConvention.Cdecl, EntryPoint="SetAxisOpposition")]
    private static extern int NativeRelative(int axis,double deltaDeg,double speedDps);
    [DllImport("2TD600.dll", CallingConvention=CallingConvention.Cdecl, EntryPoint="SetUniteAxisAction")]
    [return: MarshalAs(UnmanagedType.I4)]
    private static extern int NativeUnited(int axis,int runMode,double param1,double param2,
        [MarshalAs(UnmanagedType.I1)] bool init,[MarshalAs(UnmanagedType.I1)] bool runImmediately);
    [DllImport("2TD600.dll", CallingConvention=CallingConvention.Cdecl, EntryPoint="GetAxisMoveInPlace")]
    private static extern int GetAxisMoveInPlace(int axis);
    [DllImport("2TD600.dll", CallingConvention=CallingConvention.Cdecl, EntryPoint="GetAxisDriverFault")]
    private static extern int GetAxisDriverFault(int axis);
    [DllImport("2TD600.dll", CallingConvention=CallingConvention.Cdecl, EntryPoint="GetAxisUpLimit")]
    private static extern int GetAxisUpLimit(int axis);
    [DllImport("2TD600.dll", CallingConvention=CallingConvention.Cdecl, EntryPoint="GetAxisDownLimit")]
    private static extern int GetAxisDownLimit(int axis);
    [DllImport("2TD600.dll", CallingConvention=CallingConvention.Cdecl, EntryPoint="GetAxisOverSpeed")]
    private static extern int GetAxisOverSpeed(int axis);
    [DllImport("2TD600.dll", CallingConvention=CallingConvention.Cdecl, EntryPoint="GetAxisOverDiff")]
    private static extern int GetAxisOverDiff(int axis);

    private static bool Flag(Func<int,int> read, int axis, string name)
    {
        int value=read(axis);
        if (value is not (0 or 1)) throw new IOException($"轴{axis} {name} 返回未知状态 {value}");
        return value==1;
    }
    public DetailedAxisFeedback ReadDetailed(int axis)
    {
        if (!IsOpen) throw new InvalidOperationException("未打开转台");
        if (axis is not (0 or 2)) throw new ArgumentOutOfRangeException(nameof(axis));
        var basic=ReadAxis(axis);
        return new DetailedAxisFeedback(basic,
            Flag(GetAxisMoveInPlace,axis,"GetAxisMoveInPlace"),
            Flag(GetAxisDriverFault,axis,"GetAxisDriverFault"),
            Flag(GetAxisUpLimit,axis,"GetAxisUpLimit"),
            Flag(GetAxisDownLimit,axis,"GetAxisDownLimit"),
            Flag(GetAxisOverSpeed,axis,"GetAxisOverSpeed"),
            Flag(GetAxisOverDiff,axis,"GetAxisOverDiff"),
            Flag(GetAxisFindZero,axis,"GetAxisFindZero"),
            Flag(GetAxisLock,axis,"GetAxisLock"),
            ReadMode(axis));
    }
    private static int ReadMode(int axis)
    {
        int mode=GetRunMode(axis);
        if (mode is not (0 or 2 or 3 or 4 or 5 or 6 or 8 or 20))
            throw new IOException($"轴{axis} 运行模式反馈未知：{mode}");
        return mode;
    }
    public void FindZero(int axis,double speedDps=1.0,double accelerationDps2=2.0)
    {
        if(!IsOpen||axis is not (0 or 2))throw new InvalidOperationException("转台未连接或轴号无效");
        if(!double.IsFinite(speedDps)||speedDps<=0||speedDps>2 ||
           !double.IsFinite(accelerationDps2)||accelerationDps2<=0||accelerationDps2>3)
           throw new ArgumentOutOfRangeException(nameof(speedDps),"找零限速 <=2°/s、加速度 <=3°/s²；仍需现场核实厂家找零路径");
        if(NativeFindZero(axis,speedDps,accelerationDps2)!=1)
            throw new IOException($"轴{axis} SetAxisFindZero 返回失败；禁止假定已经找零");
    }
    public void SetEnable(int axis,bool enable)
    {
        if (!IsOpen || axis is not (0 or 2))throw new InvalidOperationException("转台未连接或轴号无效");
        int code=enable?NativeEnable(axis):NativeDisable(axis);
        if(code!=1) throw new IOException($"轴{axis} {(enable?"使能":"解除使能")}命令返回 {code}，未确认成功");
    }
    public void MoveAbsolute(int axis,double target360Deg,double speedDps)
    {
        if(!IsOpen || axis is not (0 or 2))throw new InvalidOperationException("转台未连接或轴号无效");
        if(!double.IsFinite(target360Deg)||target360Deg<0||target360Deg>=360||
           !double.IsFinite(speedDps)||speedDps<0.01||speedDps>60.0)
            throw new ArgumentOutOfRangeException(nameof(target360Deg),"本界面支持 0～360° 目标位置及 0.01～60°/s 设备标称速率；需现场确认安全路径");
        if(NativePosition(axis,target360Deg,speedDps)!=1)
            throw new IOException($"轴{axis} SetAxisPosition 未接受命令；不能认定已运动");
    }
    public void MoveRelative(int axis,double deltaDeg,double speedDps)
    {
        if(!IsOpen || axis is not (0 or 2))throw new InvalidOperationException("转台未连接或轴号无效");
        if(!double.IsFinite(deltaDeg)||Math.Abs(deltaDeg)>360 ||
           !double.IsFinite(speedDps)||speedDps<0.01||speedDps>60)
            throw new ArgumentOutOfRangeException(nameof(deltaDeg),"相对位移在±360°内，速度0.01～60°/s");
        if(NativeRelative(axis,deltaDeg,speedDps)!=1)
            throw new IOException($"轴{axis} SetAxisOpposition 相对定位指令失败");
    }
    public void MoveBoth(bool innerAbsolute,double innerDegrees,double innerSpeed,
        bool outerAbsolute,double outerDegrees,double outerSpeed)
    {
        if(!IsOpen)throw new InvalidOperationException("转台未连接");
        static bool Valid(bool absolute,double angle,double speed)=>double.IsFinite(angle) &&
            (absolute ? angle>=0 && angle<360 : Math.Abs(angle)<=360) &&
            double.IsFinite(speed)&&speed>=0.01&&speed<=60;
        if(!Valid(innerAbsolute,innerDegrees,innerSpeed) || !Valid(outerAbsolute,outerDegrees,outerSpeed))
            throw new ArgumentException("双轴参数无效；绝对0～360°，相对±360°，速度0.01～60°/s");
        // Existing Python 2TD600 driver: mode1 absolute, mode2 relative;
        // stage inner with Init=true/RunImmediately=false, then dispatch both
        // when staging outer with Init=false/RunImmediately=true.
        // If the second call fails the caller must request a controlled stop.
        int r1=NativeUnited(0,innerAbsolute?1:2,innerDegrees,innerSpeed,true,false);
        if(r1!=1)throw new IOException("SetUniteAxisAction 内轴预装指令失败");
        int r2=NativeUnited(2,outerAbsolute?1:2,outerDegrees,outerSpeed,false,true);
        if(r2!=1)throw new IOException("SetUniteAxisAction 外轴触发指令失败；应立即软件停车并核对反馈");
    }
    /// <summary>Legacy ctypes ABI confirmed; run only after independent physical-path
    /// authorisation, homing, known zero, feedback freshness, and E-stop check.</summary>
    public void StartSway(int axis, double amplitudeDeg, double frequencyHz)
    {
        if (!IsOpen || axis is not (0 or 2)) throw new InvalidOperationException("转台未连接或轴号无效");
        if (!double.IsFinite(amplitudeDeg)||amplitudeDeg<=0||amplitudeDeg>30 ||
            !double.IsFinite(frequencyHz)||frequencyHz<0.02||frequencyHz>0.5 ||
            2*Math.PI*frequencyHz*amplitudeDeg>20)
            throw new ArgumentOutOfRangeException(nameof(amplitudeDeg),"当前验证范围：幅值0～30°，频率0.02～0.5 Hz，峰值角速度≤20°/s；不代表机械保证精度");
        if(NativeSway(axis,amplitudeDeg,frequencyHz)!=1)
            throw new IOException($"轴{axis} SetAxisSway 命令失败，不能认定已经摇摆");
    }
    public void StopAxis(int axis)
    {
        if(!IsOpen || axis is not (0 or 2))throw new InvalidOperationException("转台未连接或轴号无效");
        if(NativeStop(axis)!=1)throw new IOException($"轴{axis} SetAxisStop 未被驱动确认；请核对实际反馈，必要时使用实体急停");
    }
    public void Dispose(){if(!IsOpen)return;ClosePort();IsOpen=false;}
}
public readonly record struct AxisFeedback(int Axis,double Position360Deg,double RateDps,bool Enabled,bool Normal);
public readonly record struct TurntableReadback(double HostElapsedSeconds,long HostMonotonicTicks,AxisFeedback Inner,AxisFeedback Outer);

public readonly record struct DetailedAxisFeedback(AxisFeedback Axis,bool InPlace,bool DriverFault,bool UpLimit,bool DownLimit,bool OverSpeed,bool OverDiff,bool Homed,bool Locked,int RunMode)
{
    public bool Healthy => Axis.Normal && !DriverFault && !UpLimit && !DownLimit && !OverSpeed && !OverDiff && !Locked;
}
