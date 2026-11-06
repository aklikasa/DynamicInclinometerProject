using System.Runtime.InteropServices;

namespace Dts.Devices;

/// <summary>Signatures verified against supplied Python ctypes wrappers and actual x64 DLL export names.</summary>
internal static class TdNative
{
    [DllImport("2TD600.dll",EntryPoint="OpenPort",CallingConvention=CallingConvention.Cdecl)] public static extern int OpenPort(int port,int baud);
    [DllImport("2TD600.dll",EntryPoint="ClosePort",CallingConvention=CallingConvention.Cdecl)] public static extern void ClosePort();
    [DllImport("2TD600.dll",EntryPoint="GetPosition",CallingConvention=CallingConvention.Cdecl)] public static extern double GetPosition(int axis);
    [DllImport("2TD600.dll",EntryPoint="GetSpeed",CallingConvention=CallingConvention.Cdecl)] public static extern double GetSpeed(int axis);
    [DllImport("2TD600.dll",EntryPoint="GetAxisNormal",CallingConvention=CallingConvention.Cdecl)] public static extern int GetAxisNormal(int axis);
    [DllImport("2TD600.dll",EntryPoint="GetAxisEnable",CallingConvention=CallingConvention.Cdecl)] public static extern int GetAxisEnable(int axis);
    [DllImport("2TD600.dll",EntryPoint="GetAxisMoveInPlace",CallingConvention=CallingConvention.Cdecl)] public static extern int GetAxisMoveInPlace(int axis);
    [DllImport("2TD600.dll",EntryPoint="GetAxisDriverFault",CallingConvention=CallingConvention.Cdecl)] public static extern int GetAxisDriverFault(int axis);
    [DllImport("2TD600.dll",EntryPoint="GetAxisUpLimit",CallingConvention=CallingConvention.Cdecl)] public static extern int GetAxisUpLimit(int axis);
    [DllImport("2TD600.dll",EntryPoint="GetAxisDownLimit",CallingConvention=CallingConvention.Cdecl)] public static extern int GetAxisDownLimit(int axis);
    [DllImport("2TD600.dll",EntryPoint="GetAxisOverSpeed",CallingConvention=CallingConvention.Cdecl)] public static extern int GetAxisOverSpeed(int axis);
    [DllImport("2TD600.dll",EntryPoint="GetAxisOverDiff",CallingConvention=CallingConvention.Cdecl)] public static extern int GetAxisOverDiff(int axis);
    [DllImport("2TD600.dll",EntryPoint="SetAxisPosition",CallingConvention=CallingConvention.Cdecl)] public static extern int Position(int axis,double degrees,double speed);
    // Actual incremental-position command exported by vendor DLL; signature matches provided Python ctypes driver.
    [DllImport("2TD600.dll",EntryPoint="SetAxisOpposition",CallingConvention=CallingConvention.Cdecl)] public static extern int Opposition(int axis,double relativeDegrees,double speed);
    [DllImport("2TD600.dll",EntryPoint="SetAxisStop",CallingConvention=CallingConvention.Cdecl)] public static extern int Stop(int axis);
    [DllImport("2TD600.dll",EntryPoint="SetAxisEnable",CallingConvention=CallingConvention.Cdecl)] public static extern int Enable(int axis);
    [DllImport("2TD600.dll",EntryPoint="SetAxisDisable",CallingConvention=CallingConvention.Cdecl)] public static extern int Disable(int axis);
}
internal static class FdtNative
{
    [DllImport("2FDT600WK.dll",EntryPoint="OpenPort",CallingConvention=CallingConvention.Cdecl)] public static extern int OpenPort(int port,int baud);
    [DllImport("2FDT600WK.dll",EntryPoint="ClosePort",CallingConvention=CallingConvention.Cdecl)] public static extern int ClosePort(int port);
    [DllImport("2FDT600WK.dll",EntryPoint="SetTimeout",CallingConvention=CallingConvention.Cdecl)] public static extern int SetTimeout(int port,int ms);
    [DllImport("2FDT600WK.dll",EntryPoint="GetStateInfo",CallingConvention=CallingConvention.Cdecl)]
    public static extern int GetStateInfo(int port,int axis,out sbyte alarm,out sbyte state,out float angle);
    [DllImport("2FDT600WK.dll",EntryPoint="SetAxisPosition",CallingConvention=CallingConvention.Cdecl)]
    public static extern int Position(int port,int axis,byte mode,ushort acceleration,float speed,float position);
    [DllImport("2FDT600WK.dll",EntryPoint="SetAxisStop",CallingConvention=CallingConvention.Cdecl)] public static extern int Stop(int port,int axis);
    [DllImport("2FDT600WK.dll",EntryPoint="SetAxisEnable",CallingConvention=CallingConvention.Cdecl)] public static extern int Enable(int port,int axis);
    [DllImport("2FDT600WK.dll",EntryPoint="SetAxisDisable",CallingConvention=CallingConvention.Cdecl)] public static extern int Disable(int port,int axis);
}
public sealed record AxisState(double PositionDeg,double SpeedDps,bool Normal,bool Enabled,string Detail,
    bool? InPlace=null,bool? EnableVerified=null,bool? Fault=null);
public sealed record TableSnapshot(AxisState Inner,AxisState Outer,DateTimeOffset Time);

/// <summary>
/// UI must explicitly confirm environment, physical E-Stop and axis collision clearance before any movement.
/// Software stop is NOT emergency safety hardware.
/// </summary>
public interface IRealTurntable:IDisposable
{
    string Name {get;}
    string Ports {get;}
    bool Connected {get;}
    void Connect();
    TableSnapshot Read();
    void EnableAxis(int axis);
    void DisableAxis(int axis);
    void MoveAbsolute(int axis,double angle,double speed);
    void MoveRelative(int axis,double delta,double speed);
    void StopAxis(int axis);
}

public sealed class Td600 : IRealTurntable
{
    private readonly string _com;
    private readonly int _baud;
    public Td600(string com,int baud=115200){_com=com;_baud=baud;}
    public string Name=>"2TD-600";
    public string Ports=>_com;
    public bool Connected {get;private set;}
    public void Connect()
    {
        if(Connected)throw new InvalidOperationException("2TD 已连接");
        if(TdNative.OpenPort(ComPorts.Number(_com),_baud)!=1)throw new IOException("2TD600.dll OpenPort 失败");
        Connected=true;
        // Caller can only connect after a verified read-only discovery result.
    }
    private void Check(){if(!Connected)throw new IOException("2TD 未连接");}
    public TableSnapshot Read()
    {
        Check();
        AxisState ReadAxis(int axis)
        {
            double pos=TdNative.GetPosition(axis),speed=TdNative.GetSpeed(axis);
            if(!double.IsFinite(pos)||!double.IsFinite(speed))throw new IOException("2TD 状态非有限数");
            static bool Bit(int v,string name)
            {
                if(v!=0&&v!=1)throw new IOException($"2TD {name}返回无效状态 {v}");
                return v==1;
            }
            bool normal=Bit(TdNative.GetAxisNormal(axis),"normal");
            bool enabled=Bit(TdNative.GetAxisEnable(axis),"enabled");
            bool inPlace=Bit(TdNative.GetAxisMoveInPlace(axis),"in_place");
            // Read every flag separately: OR short-circuiting would hide subsequent
            // hardware faults and make first-connect failures hard to diagnose.
            bool driverFault=Bit(TdNative.GetAxisDriverFault(axis),"driver_fault");
            bool upLimit=Bit(TdNative.GetAxisUpLimit(axis),"up_limit");
            bool downLimit=Bit(TdNative.GetAxisDownLimit(axis),"down_limit");
            bool overSpeed=Bit(TdNative.GetAxisOverSpeed(axis),"over_speed");
            bool overDiff=Bit(TdNative.GetAxisOverDiff(axis),"over_diff");
            bool faults=driverFault||upLimit||downLimit||overSpeed||overDiff;
            return new AxisState(pos,speed,normal&&!faults,enabled,
                $"正常位={(normal?1:0)},使能位={(enabled?1:0)},到位位={(inPlace?1:0)}," +
                $"驱动故障={(driverFault?1:0)},上限位={(upLimit?1:0)},下限位={(downLimit?1:0)}," +
                $"超速={(overSpeed?1:0)},超差={(overDiff?1:0)}",inPlace,enabled,faults);
        }
        return new TableSnapshot(ReadAxis(0),ReadAxis(2),DateTimeOffset.UtcNow);
    }
    public void EnableAxis(int axis){Check();if(TdNative.Enable(Axis(axis))!=1)throw new IOException("2TD 使能失败");}
    public void DisableAxis(int axis){Check();if(TdNative.Disable(Axis(axis))!=1)throw new IOException("2TD 断使能失败");}
    public void MoveAbsolute(int axis,double angle,double speed)
    {
        Check();axis=Axis(axis);
        if(!double.IsFinite(angle)||angle<0||angle>360 || !double.IsFinite(speed)||speed<=0||speed>60)
            throw new ArgumentOutOfRangeException(nameof(angle),"2TD 允许绝对位置 0～360°，速度 (0,60]°/s；需现场核实行程与机械安全");
        var s=Read();
        if(!s.Inner.Normal||!s.Outer.Normal||(axis==0?!s.Inner.Enabled:!s.Outer.Enabled))
            throw new IOException("控制轴未使能或双轴报警，禁止运动");
        if(TdNative.Position(axis,angle,speed)!=1)throw new IOException("2TD 位置指令失败");
    }
    public void MoveRelative(int axis,double delta,double speed)
    {
        Check(); axis=Axis(axis);
        // Incremental position (0xD6 in 2TD manual). No arbitrary ±90° or 0..360° clamp.
        // The actual vendor SetAxisOpposition DLL entry point is used instead of adding
        // the relative angle to the modulo-360 feedback and issuing an absolute command.
        if(!double.IsFinite(delta) || delta==0 || !double.IsFinite(speed) || speed<0.01 || speed>60)
            throw new ArgumentOutOfRangeException(nameof(delta),
                "2TD 相对角度须为有限非零值；速率范围为0.01～60°/s");
        var state=Read();
        var moving=axis==0?state.Inner:state.Outer;
        var other=axis==0?state.Outer:state.Inner;
        if(!state.Inner.Normal || !state.Outer.Normal || !moving.Enabled)
            throw new IOException("转台存在报警/限位或控制轴未使能，禁止运动");
        if(Math.Abs(other.SpeedDps)>0.05)
            throw new IOException("另一个轴仍在运动；不允许两轴互相干扰");
        // 2TD manual: continuous inner-axis rotation requires the outer axis at 0°.
        // This requirement cannot be bypassed merely because the UI supports multiple turns.
        if(axis==0 && Math.Abs(delta)>=360 && Math.Abs(other.PositionDeg)>0.2)
            throw new IOException("内轴连续多圈运动要求外轴保持零位；请先调整外轴并核实工装线缆");
        if(TdNative.Opposition(axis,delta,speed)!=1)
            throw new IOException("厂家相对位置指令 SetAxisOpposition 执行失败");
    }
    public void StopAxis(int axis){Check();if(TdNative.Stop(Axis(axis))!=1)throw new IOException("2TD 停车失败");}
    private static int Axis(int axis)=>axis is 0 or 2?axis:throw new ArgumentOutOfRangeException(nameof(axis));
    public void Dispose(){if(Connected){TdNative.ClosePort();Connected=false;}}
}

public sealed class Fdt600 : IRealTurntable
{
    private readonly string _inner,_outer;
    public Fdt600(string inner,string outer){_inner=inner;_outer=outer;}
    private int Inner=>ComPorts.Number(_inner);
    private int Outer=>ComPorts.Number(_outer);
    private int Port(int axis)=>axis switch{0=>Inner,2=>Outer,_=>throw new ArgumentOutOfRangeException(nameof(axis))};
    public string Name=>"2FDT600WK 温控转台";
    public string Ports=>$"内轴 {_inner} / 外轴 {_outer}";
    public bool Connected {get;private set;}
    public void Connect()
    {
        if(Connected)throw new InvalidOperationException("FDT 已连接");
        if(FdtNative.OpenPort(Inner,115200)!=0)throw new IOException("2FDT 内轴 OpenPort 失败");
        try
        {
            FdtNative.SetTimeout(Inner,500);
            if(Outer!=Inner)
            {
                if(FdtNative.OpenPort(Outer,115200)!=0)throw new IOException("2FDT 外轴 OpenPort 失败");
                FdtNative.SetTimeout(Outer,500);
            }
            Connected=true;
            _=Read(); // real round trip; does not accept ports by OpenPort alone
        }
        catch{ if(Outer!=Inner)FdtNative.ClosePort(Outer);FdtNative.ClosePort(Inner);Connected=false;throw; }
    }
    private AxisState ReadAxis(int axis)
    {
        int code=FdtNative.GetStateInfo(Port(axis),axis,out sbyte alarm,out sbyte state,out float pos);
        if(code!=0||!float.IsFinite(pos))throw new IOException($"2FDT 轴 {axis} 设备未返回有效状态，错误码={code}");
        // The vendor-provided state enum/bitmask mapping is not yet documented.
        // Do not invent enabled / in-place from state != 0.
        return new AxisState(pos,double.NaN,alarm==0,false,
            $"厂家状态原码={state}，报警={alarm}；使能/到位语义待厂家确认",null,null,alarm!=0);
    }
    private void Check(){if(!Connected)throw new IOException("2FDT 未连接");}
    public TableSnapshot Read(){Check();return new TableSnapshot(ReadAxis(0),ReadAxis(2),DateTimeOffset.UtcNow);}
    public void EnableAxis(int axis){Check();if(FdtNative.Enable(Port(axis),axis)!=0)throw new IOException("2FDT 使能失败");}
    public void DisableAxis(int axis){Check();if(FdtNative.Disable(Port(axis),axis)!=0)throw new IOException("2FDT 断使能失败");}
    public void MoveAbsolute(int axis,double angle,double speed)
    {
        Check();
        // Conservative UI guard until the individual 2FDT hardware mechanical limits are accepted.
        if(!double.IsFinite(angle)||Math.Abs(angle)>30 || !double.IsFinite(speed)||speed<=0||speed>5)
            throw new ArgumentOutOfRangeException(nameof(angle),"2FDT 初始安全限幅：|角度|≤30°, 速度≤5°/s；需核实厂家实际限位");
        var s=Read();if(!s.Inner.Normal||!s.Outer.Normal)throw new IOException("FDT 报警/状态异常，禁止运动");
        if(FdtNative.Position(Port(axis),axis,0,10,(float)speed,(float)angle)!=0)
            throw new IOException("2FDT 位置命令失败");
    }
    public void MoveRelative(int axis,double delta,double speed)
    {
        Check();
        if(!double.IsFinite(delta)||Math.Abs(delta)>30)
            throw new ArgumentOutOfRangeException(nameof(delta),"2FDT 单次相对运动暂限±30°");
        // 2FDT mode=0 confirmed by supplied Python driver to mean absolute command.
        var s=Read();double now=axis==0?s.Inner.PositionDeg:s.Outer.PositionDeg;
        MoveAbsolute(axis,now+delta,speed);
    }
    public void StopAxis(int axis){Check();if(FdtNative.Stop(Port(axis),axis)!=0)throw new IOException("2FDT 停车命令失败");}
    public void Dispose(){if(Connected){if(Outer!=Inner)FdtNative.ClosePort(Outer);FdtNative.ClosePort(Inner);Connected=false;}}
}

public static class FdtDiscovery
{
    public static Task<IReadOnlyList<DetectedPort>> ScanAsync(IEnumerable<string> ports,
        IProgress<string>? progress,CancellationToken token)=>Task.Run<IReadOnlyList<DetectedPort>>(()=>
    {
        var found=new List<DetectedPort>();
        foreach(string com in ports)
        {
            token.ThrowIfCancellationRequested();
            progress?.Report($"查询温控转台 {com}（只读状态，轴0/2）");
            int port=ComPorts.Number(com);
            try
            {
                if(FdtNative.OpenPort(port,115200)!=0)continue;
                try
                {
                    FdtNative.SetTimeout(port,250);
                    foreach(int axis in new[]{0,2})
                    {
                        bool ok=FdtNative.GetStateInfo(port,axis,out sbyte alarm,out sbyte state,out float angle)==0;
                        if(ok && float.IsFinite(angle) && state is >=0 and <=10 && alarm is >=0 and <=15)
                        {
                            // Double read avoids classifying an open but nonresponding UART as connected.
                            Thread.Sleep(50);
                            if(FdtNative.GetStateInfo(port,axis,out _,out _,out float a2)==0 && float.IsFinite(a2))
                                found.Add(new DetectedPort("2FDT600WK",com,$"状态轮询成功，角度={a2:F4}°",axis==0?"内轴":"外轴"));
                        }
                    }
                }
                finally{FdtNative.ClosePort(port);}
            }
            catch(Exception e) when(e is IOException or UnauthorizedAccessException or DllNotFoundException or BadImageFormatException or EntryPointNotFoundException)
            { }
        }
        return found;
    },token);
}
