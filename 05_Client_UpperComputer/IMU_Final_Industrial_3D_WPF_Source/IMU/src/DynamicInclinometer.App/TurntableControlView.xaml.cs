using System;
using System.Globalization;
using System.IO;
using System.IO.Ports;
using System.Linq;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Threading;
using DynamicInclinometer.Devices;
using DynamicInclinometer.Core;

namespace DynamicInclinometer.App;

public partial class TurntableControlView : UserControl
{
    private readonly SemaphoreSlim _gate=new(1,1);
    private readonly DispatcherTimer _timer=new(){Interval=TimeSpan.FromMilliseconds(180)};
    private TurntableTelemetry? _device;
    private bool _armed;
    private bool _safetySessionConfirmed;
    private bool _busy;  // exclusive automatic/homing/combined command
    private bool _manualInnerBusy;
    private bool _manualOuterBusy;
    private int _stopGeneration;
    private readonly System.Diagnostics.Stopwatch _feedbackClock=System.Diagnostics.Stopwatch.StartNew();
    private bool _safeToClose;
    private bool _telemetryValid;
    private long _lastFeedbackStamp; // Monotonic timestamp of latest successful two-axis readback.
    
    public event Action<TurntableReadback>? FeedbackArrived;
    public event Action? StopRequested;
    public bool SafeToClose => _safeToClose || _device is null;
    public bool IsConnected => _device is not null;
    public string? SelectedPort => PortChoice.SelectedItem as string;
    public void SuggestPort(string? port) { if (_device is null) RefreshPorts(port); }

    public TurntableControlView()
    {
        InitializeComponent();
        _timer.Tick+=async (_,_)=>await RefreshFeedbackAsync();
        RefreshPorts();
        Log("安全提示：停车为软件命令，不能替代独立硬件急停。所有动作需要实际位置和状态反馈确认。");
    }
    private void Log(string message)
    {
        var line=$"[{DateTime.Now:HH:mm:ss.fff}] {message}";
        OperationLog.AppendText(line+Environment.NewLine);
        OperationLog.ScrollToEnd();
        try
        {
            string dir=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"DynamicInclinometerLab");
            Directory.CreateDirectory(dir);
            File.AppendAllText(Path.Combine(dir,"table_control.log"),line+Environment.NewLine,Encoding.UTF8);
        }
        catch(Exception ex){ App.Log("TURNTABLE LOG FAILED",ex); }
    }
    private void RefreshPorts(string? port=null)
    {
        string[] names=SerialPort.GetPortNames().OrderBy(x=>x).ToArray();
        var chosen=port??PortChoice.SelectedItem as string;
        PortChoice.ItemsSource=names;
        if(chosen is not null && names.Contains(chosen))PortChoice.SelectedItem=chosen;
        else if(names.Length>0)PortChoice.SelectedIndex=0;
    }
    private void Refresh_Click(object sender,RoutedEventArgs e){try{RefreshPorts();}catch(Exception ex){Error(ex);}}
    private void Error(Exception ex)
    {
        App.Log("TURNTABLE CONTROL ERROR",ex);
        _armed=false;_safetySessionConfirmed=false;
        Log("错误："+ex.Message);
        ConnectStatus.Text="错误或状态未确认；禁止新增运动指令。"+ex.Message;
        MessageBox.Show(Window.GetWindow(this),ex.Message+"\n若机械仍在运动，请使用独立硬件急停并确认实际状态。","转台控制异常",MessageBoxButton.OK,MessageBoxImage.Warning);
    }
    private async Task RunLockedAsync(Action<TurntableTelemetry> action)
    {
        await _gate.WaitAsync();
        try
        {
            if(_device is null)throw new InvalidOperationException("请先连接转台");
            await Task.Run(()=>action(_device));
        }
        finally{_gate.Release();}
    }
    private async Task<T> ReadLockedAsync<T>(Func<TurntableTelemetry,T> reader)
    {
        await _gate.WaitAsync();
        try
        {
            if(_device is null)throw new InvalidOperationException("请先连接转台");
            return await Task.Run(()=>reader(_device));
        }
        finally{_gate.Release();}
    }
    private async void Connect_Click(object sender,RoutedEventArgs e)
    {
        if(_device is not null){Log("转台已连接");return;}
        if(PortChoice.SelectedItem is not string port){MessageBox.Show(Window.GetWindow(this),"选择转台 COM 端口");return;}
        ConnectButton.IsEnabled=false;
        try
        {
            var device=new TurntableTelemetry();
            await Task.Run(()=>device.Open(port));
            _device=device;_safeToClose=false;_armed=false;_safetySessionConfirmed=false;
            await RefreshFeedbackAsync();
            if(!_telemetryValid)throw new IOException("端口打开但转台反馈未通过验证；禁止操作，需检查DLL连接与状态");
            _timer.Start();
            Log($"已连接 {port} / 115200；只读取真实轴反馈");
            ConnectStatus.Text=$"{port} 已连接 · 反馈有效 · 手动控制已就绪（首次运动将确认现场安全）";
        }
        catch(Exception ex){Error(ex); /* Retain possibly open native device until verified safe disconnect. */}
        finally
        {
            // A button still labeled "连接转台" after opening COM is misleading.
            // Do not permit a second Open while the native driver owns the port.
            ConnectButton.IsEnabled=_device is null;
            ConnectButton.Content=_device is null?"连接转台":
                (_telemetryValid?$"已连接 {port}":$"{port} 状态异常·请安全断开");
        }
    }
    // One detailed read per axis: the previous implementation read both axes a second
    // time for the chart, overloading the native DLL and causing screen jitter.
    private (DetailedAxisFeedback Inner,DetailedAxisFeedback Outer,TurntableReadback Basic) ReadAll(TurntableTelemetry d)
    {
        var inner=d.ReadDetailed(0);
        var outer=d.ReadDetailed(2);
        return (inner,outer,new TurntableReadback(_feedbackClock.Elapsed.TotalSeconds,
            System.Diagnostics.Stopwatch.GetTimestamp(),inner.Axis,outer.Axis));
    }
    private async Task RefreshFeedbackAsync()
    {
        if(_device is null)return;
        if(!await _gate.WaitAsync(0))return;
        try
        {
            var d=_device;
            var r=await Task.Run(()=>ReadAll(d));
            // Fixed-size readouts: do not alter the geometry of the manual control page.
            InnerAngleText.Text=$"{r.Inner.Axis.Position360Deg:F3}°";
            OuterAngleText.Text=$"{r.Outer.Axis.Position360Deg:F3}°";
            InnerRateText.Text=$"{r.Inner.Axis.RateDps:F3} °/s";
            OuterRateText.Text=$"{r.Outer.Axis.RateDps:F3} °/s";
            InnerStatus.Text=$"{(r.Inner.Axis.Enabled?"已使能":"未使能")} / {(r.Inner.Homed?"已找零":"未找零")} / {(r.Inner.Healthy?"正常":"故障/限位")}";
            OuterStatus.Text=$"{(r.Outer.Axis.Enabled?"已使能":"未使能")} / {(r.Outer.Homed?"已找零":"未找零")} / {(r.Outer.Healthy?"正常":"故障/限位")}";
            InnerAngle360=r.Inner.Axis.Position360Deg;
            _lastFeedbackStamp=System.Diagnostics.Stopwatch.GetTimestamp();
            _telemetryValid=true;
            FeedbackArrived?.Invoke(r.Basic);
        }
        catch(Exception ex)
        {
            _telemetryValid=false;_armed=false;_timer.Stop();Error(ex);
        }
        finally{_gate.Release();}
    }
    private static bool Stationary(DetailedAxisFeedback x)=>Math.Abs(x.Axis.RateDps)<=.05;
    private static void RequireHealthy(DetailedAxisFeedback x)
    {
        if(!x.Healthy)throw new InvalidOperationException($"轴{x.Axis.Axis} 状态异常（正常、限位或故障反馈），不允许运动");
        if(!Stationary(x))throw new InvalidOperationException($"轴{x.Axis.Axis} 尚未静止");
    }
    private async Task VerifyStableAsync()
    {
        for(int i=0;i<3;i++)
        {
            var states=await ReadLockedAsync(d=>(d.ReadDetailed(0),d.ReadDetailed(2)));
            RequireHealthy(states.Item1);RequireHealthy(states.Item2);
            await Task.Delay(200);
        }
    }
    // Keep the page simple, but do not silently authorise real motor motion.
    // The operator confirms the real emergency stop and mechanical setup once per connection.
    private async Task EnsureManualPermissionAsync()
    {
        if (_device is null || !_telemetryValid)
            throw new InvalidOperationException("先连接转台，等待有效的位置、速度和故障反馈");
        if (!_safetySessionConfirmed)
        {
            var reply=MessageBox.Show(Window.GetWindow(this),
                "即将允许真实转台电机运动。请确认：\n"+
                "① 已检查控制柜实体急停、人员距离及线缆空间；\n"+
                "② 已核对安装方向和内轴0／外轴2对应关系；\n"+
                "③ 转台两轴状态正常且已确认目标运动路径。\n\n"+
                "本次连接只需要确认一次。是否继续？",
                "首次运动确认",MessageBoxButton.YesNo,MessageBoxImage.Warning);
            if (reply!=MessageBoxResult.Yes)
                throw new OperationCanceledException("操作员取消首次运动确认");
        }
        // First authorisation is made only while both axes are known stationary.
        // Subsequent independently commanded manual-axis moves may overlap;
        // requiring both axes stationary here incorrectly prevented two-axis control.
        if(!_safetySessionConfirmed)await VerifyStableAsync();
        _safetySessionConfirmed=true;
        _armed=true;
    }
    private static double ParseManualSpeed(string text)
    {
        if (!double.TryParse(text,NumberStyles.Float,CultureInfo.InvariantCulture,out var speed) ||
            !double.IsFinite(speed) || speed<0.01 || speed>60.0)
            throw new ArgumentException("位置运动速度范围为 0.01～60°/s（设备标称速率范围），使用小数点 .；高速度需确认负载和路径。");
        return speed;
    }
    private async Task AwaitEnableFeedbackAsync(int axis,bool enabled)
    {
        int matches=0;
        for(int i=0;i<18;i++)
        {
            var status=await ReadLockedAsync(d=>d.ReadDetailed(axis));
            if (status.Axis.Enabled==enabled) matches++; else matches=0;
            if (matches>=2) return;
            await Task.Delay(170);
        }
        throw new InvalidOperationException($"轴{axis} 使能反馈未确认，不允许继续运动");
    }

    private async Task EnableAsync(int axis,bool value)
    {
        try
        {
            if (value) await EnsureManualPermissionAsync();
            else await VerifyStationaryAsync();
            var feedback=await ReadLockedAsync(d=>d.ReadDetailed(axis));
            if(feedback.Axis.Enabled==value)
            {
                Log($"轴{axis} 实际使能状态已是 {(value?"已使能":"未使能")}，不重复下发命令");
                return;
            }
            await RunLockedAsync(d=>d.SetEnable(axis,value));
            await AwaitEnableFeedbackAsync(axis,value);
            if(!value) _armed=false;
            Log($"轴{axis} {(value?"使能":"解除使能")}反馈已确认");
            await RefreshFeedbackAsync();
        }
        catch(OperationCanceledException) { Log("操作员取消运动确认"); }
        catch(Exception ex) { Error(ex); }
    }
    private async Task VerifyStationaryAsync()
    {
        int ok=0;
        for(int i=0;i<12;i++)
        {
            var both=await ReadLockedAsync(d=>(d.ReadDetailed(0),d.ReadDetailed(2)));
            ok=(Stationary(both.Item1)&&Stationary(both.Item2))?ok+1:0;
            if(ok>=3)return;
            await Task.Delay(180);
        }
        throw new InvalidOperationException("无法证实两轴连续静止，拒绝解除使能");
    }
    private async void EnableInner_Click(object sender,RoutedEventArgs e)=>await EnableAsync(0,true);
    private async void EnableOuter_Click(object sender,RoutedEventArgs e)=>await EnableAsync(2,true);
    private async void DisableInner_Click(object sender,RoutedEventArgs e)=>await EnableAsync(0,false);
    private async void DisableOuter_Click(object sender,RoutedEventArgs e)=>await EnableAsync(2,false);
    private async void EnableBoth_Click(object sender,RoutedEventArgs e)
    {
        if(_busy||_manualInnerBusy||_manualOuterBusy){Log("运动中不允许重新使能双轴");return;}
        try
        {
            await EnsureManualPermissionAsync();
            await EnsureAxisEnabledAsync(0);
            await EnsureAxisEnabledAsync(2);
            var r=await ReadLockedAsync(d=>(d.ReadDetailed(0),d.ReadDetailed(2)));
            if(!r.Item1.Axis.Enabled||!r.Item2.Axis.Enabled)throw new IOException("双轴使能反馈未确认");
            Log("双轴真实使能反馈均为1（已使能）；未重复使能原本已使能的轴");
        }
        catch(OperationCanceledException ex){Log("双轴使能取消："+ex.Message);}
        catch(Exception ex){Error(ex);}
    }
    private static double ParseAngle(string raw,bool absolute)
    {
        if(!double.TryParse(raw,NumberStyles.Float,CultureInfo.InvariantCulture,out var angle) ||
           !double.IsFinite(angle))throw new ArgumentException("请输入有效的角度，使用小数点 .");
        if(absolute && (angle<0 || angle>=360))
            throw new ArgumentException("绝对目标角度需要在 0≤角度<360° 内");
        if(!absolute && Math.Abs(angle)>360)
            throw new ArgumentException("相对增量单次不得超过 ±360°，较大位移请分次现场核验");
        return angle;
    }
    private static bool IsAbsolute(ComboBox mode)=>mode.SelectedIndex==1;
    private static string ModeLabel(bool absolute)=>absolute?"绝对定位":"相对增量";
    private bool ManualBusy(int axis)=>axis==0?_manualInnerBusy:_manualOuterBusy;
    private void SetManualBusy(int axis,bool value)
    {
        if(axis==0)_manualInnerBusy=value;else _manualOuterBusy=value;
    }
    private static double ExpectedPosition(double start,double command,bool absolute)
    {
        if(absolute)return command;
        double target=(start+command)%360;
        return target<0?target+360:target;
    }
    private async Task EnsureAxisEnabledAsync(int axis)
    {
        var state=await ReadLockedAsync(d=>d.ReadDetailed(axis));
        if(state.Axis.Enabled)return;  // Trust actual driver feedback, not the software _armed flag.
        if(MessageBox.Show(Window.GetWindow(this),$"轴{axis} 驱动器当前反馈【未使能】，是否在确认现场条件后使能？",
           "转台实际使能状态",MessageBoxButton.YesNo,MessageBoxImage.Question)!=MessageBoxResult.Yes)
            throw new OperationCanceledException($"轴{axis} 未使能；操作员取消使能");
        await RunLockedAsync(d=>d.SetEnable(axis,true));
        await AwaitEnableFeedbackAsync(axis,true);
    }
    private static void RequireMotionFeedback(DetailedAxisFeedback status,int axis)
    {
        if(!status.Healthy)throw new IOException($"轴{axis} 反馈故障/限位/机械锁紧，拒绝运动");
        if(!status.Axis.Enabled)throw new IOException($"轴{axis} 当前已失能");
    }
    private async Task MoveAsync(int axis,string commandText,string speedText,bool absolute)
    {
        if(_busy || ManualBusy(axis)) { Log($"轴{axis} 已有运动任务，忽略重复点击"); return; }
        int stopGeneration=_stopGeneration;
        SetManualBusy(axis,true);
        bool issued=false;
        try
        {
            var command=ParseAngle(commandText,absolute);
            var speed=ParseManualSpeed(speedText);
            await EnsureManualPermissionAsync();
            await EnsureAxisEnabledAsync(axis);
            var fb=await ReadLockedAsync(d=>d.ReadDetailed(axis));
            RequireHealthy(fb);
            double target=ExpectedPosition(fb.Axis.Position360Deg,command,absolute);
            double distance=absolute?Math.Abs(command-fb.Axis.Position360Deg):Math.Abs(command);
            if(distance<.001){Log($"轴{axis} 目标与当前位置相同，跳过运动");return;}
            if(distance>30 || speed>10)
            {
                var choice=MessageBox.Show(Window.GetWindow(this),
                    $"即将执行真实转台运动：\n轴{axis} / {ModeLabel(absolute)}\n"+
                    $"当前位置 {fb.Axis.Position360Deg:F3}°，指令角 {command:+0.###;-0.###;0}°，预计目标显示 {target:F3}°\n"+
                    $"指令速度 {speed:F2}°/s\n\n"+
                    "请确保所选运动模式的方向、限位、工装、滑环和机械路径安全。"+
                    (distance>180?"\n注意：本次超过180°，绝对模式下方向/跨周路径必须事先核对。":""),
                    "确认真实运动",MessageBoxButton.YesNo,MessageBoxImage.Warning);
                if(choice!=MessageBoxResult.Yes)throw new OperationCanceledException("操作员取消大角度/高速运动");
            }
            if(_stopGeneration!=stopGeneration)throw new OperationCanceledException("停车已请求，运动未启动");
            await RunLockedAsync(d=>
            {
                if(absolute)d.MoveAbsolute(axis,command,speed);
                else d.MoveRelative(axis,command,speed);
            });
            issued=true;
            Log($"轴{axis} {ModeLabel(absolute)}：指令角={command:F3}° 速度={speed:F3}°/s；绝对反馈目标≈{target:F3}°");
            var sw=System.Diagnostics.Stopwatch.StartNew();
            int matched=0;
            bool motionObserved=distance<=.05;
            // 60°/s is a rated velocity, not a guaranteed transient acceleration/settle time.
            double timeout=Math.Max(30,distance/Math.Max(.01,speed)*2.5+30);
            while(sw.Elapsed.TotalSeconds<timeout)
            {
                if(_stopGeneration!=stopGeneration)throw new OperationCanceledException("收到停车请求");
                var s=await ReadLockedAsync(d=>d.ReadDetailed(axis));
                RequireMotionFeedback(s,axis);
                // Require observing motion before accepting a potentially stale InPlace flag.
                motionObserved|=Math.Abs(s.Axis.RateDps)>.08 ||
                    AxisZeroPositionPlanner.AngularDistance(s.Axis.Position360Deg,fb.Axis.Position360Deg)>Math.Min(.05,distance*.35);
                // Readout uses the actual ABSOLUTE encoder angle for either command mode.
                matched=motionObserved && AxisZeroPositionPlanner.AngularDistance(s.Axis.Position360Deg,target)<=.10 &&
                    Stationary(s) && s.InPlace?matched+1:0;
                if(matched>=3){Log($"轴{axis} 已到位：绝对角度 {s.Axis.Position360Deg:F3}°");return;}
                await Task.Delay(180);
            }
            throw new TimeoutException($"轴{axis} {ModeLabel(absolute)}到位超时，需确认真实停车");
        }
        catch(OperationCanceledException ex){Log($"轴{axis} 定位取消：{ex.Message}");}
        catch(Exception ex)
        {
            Log($"轴{axis} 定位错误：{ex.Message}");
            if(issued)
            {
                // Stop both on unknown position/feedback errors, not only the active axis.
                try{await StopAllAndVerifyAsync();}
                catch(Exception stopEx){Log("危险：停车未确认 "+stopEx.Message);}
            }
            Error(ex);
        }
        finally{SetManualBusy(axis,false);await RefreshFeedbackAsync();}
    }
    private async void MoveInner_Click(object sender,RoutedEventArgs e)
        =>await MoveAsync(0,InnerTarget.Text,SpeedInput.Text,IsAbsolute(InnerPositionMode));
    private async void MoveOuter_Click(object sender,RoutedEventArgs e)
        =>await MoveAsync(2,OuterTarget.Text,OuterSpeedInput.Text,IsAbsolute(OuterPositionMode));

    private async void MoveBoth_Click(object sender,RoutedEventArgs e)
    {
        if(_busy||_manualInnerBusy||_manualOuterBusy){Log("当前存在其他运动任务，拒绝覆盖双轴动作");return;}
        int stopGeneration=_stopGeneration;
        _busy=true;
        bool issued=false;
        try
        {
            bool iAbs=IsAbsolute(InnerPositionMode),oAbs=IsAbsolute(OuterPositionMode);
            double ia=ParseAngle(InnerTarget.Text,iAbs),oa=ParseAngle(OuterTarget.Text,oAbs);
            double ispeed=ParseManualSpeed(SpeedInput.Text),ospeed=ParseManualSpeed(OuterSpeedInput.Text);
            await EnsureManualPermissionAsync();
            await EnsureAxisEnabledAsync(0);await EnsureAxisEnabledAsync(2);
            var before=await ReadLockedAsync(d=>(d.ReadDetailed(0),d.ReadDetailed(2)));
            RequireHealthy(before.Item1);RequireHealthy(before.Item2);
            if(!before.Item1.Axis.Enabled || !before.Item2.Axis.Enabled)
                throw new InvalidOperationException("实际反馈中仍有轴未使能，拒绝双轴联动");
            double itarget=ExpectedPosition(before.Item1.Axis.Position360Deg,ia,iAbs);
            double otarget=ExpectedPosition(before.Item2.Axis.Position360Deg,oa,oAbs);
            double idist=iAbs?Math.Abs(ia-before.Item1.Axis.Position360Deg):Math.Abs(ia);
            double odist=oAbs?Math.Abs(oa-before.Item2.Axis.Position360Deg):Math.Abs(oa);
            var confirm=MessageBox.Show(Window.GetWindow(this),
                "警告：准备使用厂家 SetUniteAxisAction 同步启动内外轴。\n"+
                $"内轴 {ModeLabel(iAbs)} {ia:F3}° / {ispeed:F2}°/s，外轴 {ModeLabel(oAbs)} {oa:F3}° / {ospeed:F2}°/s。\n\n"+
                "2TD-600 说明书对部分负载安装姿态明确要求另一轴保持静止。\n"+
                "请确认本次工装、台面姿态、机械间隙、线缆与负载确实允许两轴同时运动，急停可用。未经实机确认请选择【否】。",
                "双轴联合运动：现场确认",MessageBoxButton.YesNo,MessageBoxImage.Warning);
            if(confirm!=MessageBoxResult.Yes)throw new OperationCanceledException("未授权双轴联合运动");
            if(_stopGeneration!=stopGeneration)throw new OperationCanceledException("停车已请求");
            issued=true; // Even a partially staged native joint command requires stop verification.
            await RunLockedAsync(d=>d.MoveBoth(iAbs,ia,ispeed,oAbs,oa,ospeed));
            Log($"DLL 双轴联合运行已接受；内轴目标绝对≈{itarget:F3}°，外轴目标绝对≈{otarget:F3}°");
            var sw=System.Diagnostics.Stopwatch.StartNew();int matched=0;
            bool innerObserved=idist<=.05,outerObserved=odist<=.05;
            double timeout=Math.Max(30,Math.Max(idist/Math.Max(.01,ispeed),odist/Math.Max(.01,ospeed))*2.5+30);
            while(sw.Elapsed.TotalSeconds<timeout)
            {
                if(_stopGeneration!=stopGeneration)throw new OperationCanceledException("停车已请求");
                var r=await ReadLockedAsync(d=>(d.ReadDetailed(0),d.ReadDetailed(2)));
                RequireMotionFeedback(r.Item1,0);RequireMotionFeedback(r.Item2,2);
                innerObserved|=Math.Abs(r.Item1.Axis.RateDps)>.08 ||
                    AxisZeroPositionPlanner.AngularDistance(r.Item1.Axis.Position360Deg,before.Item1.Axis.Position360Deg)>Math.Min(.05,idist*.35);
                outerObserved|=Math.Abs(r.Item2.Axis.RateDps)>.08 ||
                    AxisZeroPositionPlanner.AngularDistance(r.Item2.Axis.Position360Deg,before.Item2.Axis.Position360Deg)>Math.Min(.05,odist*.35);
                matched=innerObserved&&outerObserved&&AxisZeroPositionPlanner.AngularDistance(r.Item1.Axis.Position360Deg,itarget)<=.12 &&
                    AxisZeroPositionPlanner.AngularDistance(r.Item2.Axis.Position360Deg,otarget)<=.12 &&
                    Stationary(r.Item1)&&Stationary(r.Item2)&&r.Item1.InPlace&&r.Item2.InPlace?matched+1:0;
                if(matched>=3){Log("双轴联合运动完成，编码器和到位反馈均已确认");return;}
                await Task.Delay(180);
            }
            throw new TimeoutException("双轴联合运行未在预计时间内确认双轴同时到位");
        }
        catch(OperationCanceledException ex){Log("双轴运动取消："+ex.Message);}
        catch(Exception ex)
        {
            if(issued)try{await StopAllAndVerifyAsync();}catch(Exception stop){Log("危险：双轴停车未确认 "+stop.Message);}
            Error(ex);
        }
        finally{_busy=false;await RefreshFeedbackAsync();}
    }

    private async Task HomeAxesAsync(int[] axes)
    {
        if(_busy||_manualInnerBusy||_manualOuterBusy){Log("已有运动在执行，请先停车");return;}
        int stopGeneration=_stopGeneration;
        _busy=true;
        bool issued=false;
        try
        {
            await EnsureManualPermissionAsync();
            foreach(int axis in axes)
            {
                if(_stopGeneration!=stopGeneration)throw new OperationCanceledException("停车已请求");
                await EnsureAxisEnabledAsync(axis);
                var before=await ReadLockedAsync(d=>(d.ReadDetailed(0),d.ReadDetailed(2)));
                RequireHealthy(before.Item1);RequireHealthy(before.Item2);
                var current=axis==0?before.Item1:before.Item2;
                if(current.Homed && AxisZeroPositionPlanner.AngularDistance(current.Axis.Position360Deg,0)<=.20)
                {Log($"轴{axis} 已机械找零且绝对角度≈0°，跳过重复回零");continue;}
                if(MessageBox.Show(Window.GetWindow(this),
                    $"轴{axis} 当前绝对角度 {current.Axis.Position360Deg:F3}°，已找零标志={current.Homed}。\n"+
                    "确认执行厂家真实 SetAxisFindZero 机械回零？运动可能跨越大角度，另一轴必须静止；操作员应事先确认工装和限位。",
                    "机械回零确认",MessageBoxButton.YesNo,MessageBoxImage.Warning)!=MessageBoxResult.Yes)
                    throw new OperationCanceledException("操作员取消机械回零");
                await RunLockedAsync(d=>d.FindZero(axis,2.0,2.0));
                issued=true;
                Log($"轴{axis} 已发送机械找零，等待厂家找零标志、零速和角度回读");
                int matched=0;
                var originalOther=axis==0?before.Item2:before.Item1;
                for(int i=0;i<2400;i++)
                {
                    if(_stopGeneration!=stopGeneration)throw new OperationCanceledException("停车已请求");
                    var state=await ReadLockedAsync(d=>(d.ReadDetailed(0),d.ReadDetailed(2)));
                    var moving=axis==0?state.Item1:state.Item2;
                    var other=axis==0?state.Item2:state.Item1;
                    RequireMotionFeedback(moving,axis);
                    if(!other.Healthy)throw new IOException("机械回零期间另一轴故障或限位");
                    if(!Stationary(other) || AxisZeroPositionPlanner.AngularDistance(other.Axis.Position360Deg,originalOther.Axis.Position360Deg)>.15)
                        throw new IOException("找零期间另一轴意外运动，停止继续操作");
                    matched=moving.Homed&&moving.InPlace&&Stationary(moving)&&
                        AxisZeroPositionPlanner.AngularDistance(moving.Axis.Position360Deg,0)<=.20?matched+1:0;
                    if(matched>=3){Log($"轴{axis} 机械回零成功，零点反馈 {moving.Axis.Position360Deg:F3}°");break;}
                    await Task.Delay(180);
                }
                if(matched<3)throw new TimeoutException($"轴{axis} 机械找零超时，未获已找零+到位+零速+0°反馈");
                issued=false;
            }
        }
        catch(OperationCanceledException ex){Log("回零取消："+ex.Message);}
        catch(Exception ex)
        {
            if(issued)try{await StopAllAndVerifyAsync();}catch(Exception stop){Log("危险：机械回零停车未确认 "+stop.Message);}
            Error(ex);
        }
        finally{_busy=false;await RefreshFeedbackAsync();}
    }
    private async void HomeInner_Click(object sender,RoutedEventArgs e)=>await HomeAxesAsync(new[]{0});
    private async void HomeOuter_Click(object sender,RoutedEventArgs e)=>await HomeAxesAsync(new[]{2});
    private async void HomeBoth_Click(object sender,RoutedEventArgs e)=>await HomeAxesAsync(new[]{0,2});

    // Dashboard commands are thin delegates to the existing, safety-confirmed controller.
    // They never bypass enable/fault/path confirmation, locking or stop-generation checks.
    public Task MoveFromDashboardAsync(int axis,string angle,string speed,bool absolute)
    {
        if(axis is not (0 or 2))throw new ArgumentOutOfRangeException(nameof(axis));
        if(!IsConnected)throw new InvalidOperationException("请先在【转台控制】页连接真实 2TD-600 转台");
        return MoveAsync(axis,angle,speed,absolute);
    }
    public Task HomeFromDashboardAsync()
    {
        if(!IsConnected)throw new InvalidOperationException("请先在【转台控制】页连接真实 2TD-600 转台");
        return HomeAxesAsync(new[]{0,2});
    }
    public async Task StopFromDashboardAsync()
    {
        System.Threading.Interlocked.Increment(ref _stopGeneration);
        StopRequested?.Invoke();
        if(!IsConnected)return;
        try { await StopAllAndVerifyAsync(); await RefreshFeedbackAsync(); }
        catch(Exception ex) { Error(ex); }
    }

    private async Task StopAllAndVerifyAsync()
    {
        if(_device is null)return;
        _armed=false;
        // Independently attempt both axes even if one STOP returns error.
        var before=await ReadLockedAsync(d=>(d.ReadDetailed(0),d.ReadDetailed(2)));
        var errors=new System.Collections.Generic.List<string>();
        foreach(var (axis,status) in new[]{(0,before.Item1),(2,before.Item2)})
        {
            if(!status.Axis.Enabled && Stationary(status))continue;
            try{await RunLockedAsync(d=>d.StopAxis(axis));Log($"轴{axis} 软件停车命令已接受");}
            catch(Exception ex)
            {
                var message=$"轴{axis} 停车命令返回异常：{ex.Message}";
                if(Stationary(status))Log(message+"；之前该轴已报告零速，继续等待连续新反馈；不直接判定成功");
                else {errors.Add(message);Log(message+"；轴之前处于运动状态！");}
            }
        }
        int good=0; (DetailedAxisFeedback,DetailedAxisFeedback)? previous=null;
        for(int i=0;i<50;i++)
        {
            var fb=await ReadLockedAsync(d=>(d.ReadDetailed(0),d.ReadDetailed(2)));
            bool still=Stationary(fb.Item1)&&Stationary(fb.Item2);
            if(previous is not null)
            {
                still &= AxisZeroPositionPlanner.AngularDistance(fb.Item1.Axis.Position360Deg,previous.Value.Item1.Axis.Position360Deg)<=.05;
                still &= AxisZeroPositionPlanner.AngularDistance(fb.Item2.Axis.Position360Deg,previous.Value.Item2.Axis.Position360Deg)<=.05;
            }
            good=still?good+1:0;previous=fb;
            if(good>=3)
            {
                if(errors.Count>0)throw new IOException(string.Join("；",errors)+"。尽管已回读零速，但停车指令未确认，禁止断开");
                Log("已确认连续3次双轴零速且位置稳定");return;
            }
            await Task.Delay(180);
        }
        throw new TimeoutException("双轴停车未获得连续稳定反馈，禁止断开；请使用独立硬件急停确认");
    }
    private async void Stop_Click(object sender,RoutedEventArgs e)
    {
        System.Threading.Interlocked.Increment(ref _stopGeneration);
        StopRequested?.Invoke();
        _armed=false;
        try{await StopAllAndVerifyAsync();await RefreshFeedbackAsync();}
        catch(Exception ex){Error(ex);}
    }
    private async Task DisconnectSafeAsync()
    {
        if(_device is null)return;
        _armed=false;_safetySessionConfirmed=false;
        await StopAllAndVerifyAsync();
        foreach(int axis in new[]{0,2})
        {
            var state=await ReadLockedAsync(d=>d.ReadDetailed(axis));
            if(state.Axis.Enabled)
            {
                await RunLockedAsync(d=>d.SetEnable(axis,false));
                int good=0;
                for(int i=0;i<20;i++)
                {
                    var feedback=await ReadLockedAsync(d=>d.ReadDetailed(axis));
                    if(!Stationary(feedback))throw new InvalidOperationException($"轴{axis} 解除使能过程中检测到运动");
                    good=!feedback.Axis.Enabled?good+1:0;
                    if(good>=2)break;
                    await Task.Delay(180);
                }
                if(good<2)throw new InvalidOperationException($"轴{axis} 解除使能未得到连续确认，保留端口连接");
            }
        }
        await VerifyStationaryAsync();
        await _gate.WaitAsync();
        try{var closingDevice=_device;await Task.Run(()=>closingDevice.Dispose());_device=null;}
        finally{_gate.Release();}
        _timer.Stop();_safeToClose=true;
        _telemetryValid=false;_lastFeedbackStamp=0;
        ConnectButton.IsEnabled=true;ConnectButton.Content="连接转台";
        ConnectStatus.Text="双轴已停车、解除使能并安全关闭端口";
        InnerStatus.Text="已断开";OuterStatus.Text="已断开";
        InnerAngleText.Text="---.---°";OuterAngleText.Text="---.---°";
        InnerRateText.Text="--.--- °/s";OuterRateText.Text="--.--- °/s";
        Log("安全断开完成；双轴停车 → 失能反馈 → ClosePort");
    }
    private async void Disconnect_Click(object sender,RoutedEventArgs e)
    {
        if(_busy||_manualInnerBusy||_manualOuterBusy){StopRequested?.Invoke();MessageBox.Show(Window.GetWindow(this),"转台仍在执行定位或自动测试，请先停止并核对实际停稳，再安全关闭转台。","正在运动");return;}
        try{await DisconnectSafeAsync();}
        catch(Exception ex){Error(ex);}
    }
    public double? InnerAngle360 {get;private set;}
    /// <summary>
    /// Explains why a real automated test cannot start. Being "connected" is NOT the
    /// same condition as "ready and idle". Never tell the operator to reconnect
    /// when the real cause is a pending manual command or stale telemetry.
    /// </summary>
    public string? GetAutomaticTestBlocker()
    {
        if(_device is null)
            return "转台通信尚未建立。请在【转台手动控制】选择转台 COM 端口并点击【连接转台】。";
        if(!_telemetryValid || _lastFeedbackStamp==0)
            return "转台端口已经打开，但双轴状态反馈未通过校验。请检查转台控制页底部连接状态及诊断日志。";
        double age=(System.Diagnostics.Stopwatch.GetTimestamp()-_lastFeedbackStamp)/
                   (double)System.Diagnostics.Stopwatch.Frequency;
        if(age>3.0)
            return $"转台已连接，但最近一次有效双轴反馈距今 {age:F1} 秒。界面角度可能是旧值；请检查转台诊断日志及刷新是否停止。";
        if(_busy)
            return "转台已经连接且反馈有效，但程序仍有双轴联合运行、找零或自动运动任务未结束；请等待任务完成并核对实际停稳，不能重叠启动测试。";
        if(_manualInnerBusy || _manualOuterBusy)
            return $"转台已经连接且反馈有效，但{(_manualInnerBusy?"内轴0 ":"")}{(_manualOuterBusy?"外轴2 ":"")}手动定位任务仍在等待完成反馈。请检查手动控制页的诊断日志与实际停车状态。";
        return null;
    }
    public bool MotionPermissionGranted => GetAutomaticTestBlocker() is null;
    // This property denotes readiness to START the controlled preflight, NOT a blanket
    // authorisation to move motors or proof that both drives are enabled.

    // Before each real automatic test: verify homing independently of 0-degree position,
    // search for mechanical zero if absent, then position the fixture. All commands are
    // serialized and confirmed by multiple hardware feedback samples.
    public async Task PrepareAutomaticTestAsync(double innerTarget,CancellationToken ct)
    {
        var blocker=GetAutomaticTestBlocker();
        if(blocker is not null)throw new InvalidOperationException(blocker);
        // A connected, physically enabled table does not need to be re-enabled in the
        // manual page. On-site consent is still required before any actual motor motion.
        await EnsureManualPermissionAsync();
        await EnsureAxisEnabledAsync(0);
        await EnsureAxisEnabledAsync(2);
        if(innerTarget!=0 && innerTarget!=90)
            throw new ArgumentOutOfRangeException(nameof(innerTarget));
        await VerifyStableAsync();
        var initial=await ReadLockedAsync(d=>(d.ReadDetailed(0),d.ReadDetailed(2)));
        if(!initial.Item1.Healthy||!initial.Item2.Healthy)
            throw new InvalidOperationException("双轴反馈不正常或机械锁紧，禁止自动找零");
        if(!initial.Item1.Axis.Enabled || !initial.Item2.Axis.Enabled)
            throw new InvalidOperationException("驱动器使能未从真实反馈确认，拒绝自动运动");
        var ask=MessageBox.Show(Window.GetWindow(this),
            "本程序将先检查内轴0、外轴2是否完成机械找零，未找零的轴将调用厂家DLL执行真实找零运动。"+
            "\n\n请现场确认：\n① 独立硬件急停可用、人员距离机械转动范围至少3米；"+
            "\n② 已松开两轴机械锁，线缆滑环/工装没有缠绕和干涉；"+
            "\n③ 已核对两轴找零可能经过的全部运动路径，找零时另一轴必须保持静止；"+
            "\n④ 若执行Pitch测试，请确认内轴转到90°的姿态及外轴摇摆路径不会碰撞。"+
            "\n\n安全条件不满足请选【否】，不要启动。",
            "自动找零及测试路径确认",MessageBoxButton.YesNo,MessageBoxImage.Warning);
        if(ask!=MessageBoxResult.Yes)throw new OperationCanceledException("现场未授权自动找零/定位");
        _busy=true;_armed=false;
        try
        {
            // Physical first-zero motion can span a full axis revolution. Do not infer
            // zero from a displayed position: only GetAxisFindZero is authoritative.
            // Outer first; during homing the other axis is monitored for unintended motion.
            foreach(int axis in new[]{2,0})
            {
                ct.ThrowIfCancellationRequested();
                var b=await ReadLockedAsync(d=>(d.ReadDetailed(0),d.ReadDetailed(2)));
                var current=axis==0?b.Item1:b.Item2;
                var other=axis==0?b.Item2:b.Item1;
                if(!current.Healthy||!other.Healthy||!Stationary(current)||!Stationary(other))
                    throw new IOException("找零准备阶段出现限位/故障/机械锁或未停稳");
                if(current.Homed)
                {
                    Log($"轴{axis} 已找到机械零点（GetAxisFindZero=1），无需重复找零");
                    continue;
                }
                Log($"轴{axis} 尚未完成机械找零；开始低速自动找零，另一轴必须静止");
                await RunLockedAsync(d=>d.FindZero(axis,1.0,2.0));
                int matches=0;
                for(int i=0;i<2400;i++) // allow up to 432s for a cautious 1°/s full revolution
                {
                    ct.ThrowIfCancellationRequested();
                    var states=await ReadLockedAsync(d=>(d.ReadDetailed(0),d.ReadDetailed(2)));
                    var moving=axis==0?states.Item1:states.Item2;
                    var fixedAxis=axis==0?states.Item2:states.Item1;
                    if(!moving.Healthy||!fixedAxis.Healthy||!Stationary(fixedAxis)||
                       Math.Abs(fixedAxis.Axis.Position360Deg-other.Axis.Position360Deg)>.10)
                        throw new IOException($"轴{axis} 找零期间出现转台故障或另一轴意外运动");
                    matches=moving.Homed&&Stationary(moving)?matches+1:0;
                    if(matches>=3){Log($"轴{axis} 找零成功（已连续3次确认完成标志和零速）");break;}
                    await Task.Delay(180,ct);
                }
                if(matches<3)throw new TimeoutException($"轴{axis} 找零超过432秒；找零完成反馈未连续确认");
                await VerifyStationaryAsync();
            }
            // Homed != at zero. Position outer at zero before changing inner orientation.
            await PositionForTestAsync(2,0,ct);
            await PositionForTestAsync(0,innerTarget,ct);
            var done=await ReadLockedAsync(d=>(d.ReadDetailed(0),d.ReadDetailed(2)));
            if(!done.Item1.Homed||!done.Item2.Homed||!done.Item1.Healthy||!done.Item2.Healthy ||
               Math.Min(Math.Abs(done.Item2.Axis.Position360Deg),Math.Abs(done.Item2.Axis.Position360Deg-360))>.30 ||
               AxisZeroPositionPlanner.AngularDistance(done.Item1.Axis.Position360Deg,innerTarget)>.35)
               throw new IOException("预备结束后找零状态或目标位置复核失败，拒绝自动摇摆");
            Log($"自动预检完成：双轴找零标志有效；内轴={innerTarget:F1}°、外轴=0°、实际反馈连续稳定");
            _armed=true;
        }
        catch(Exception ex)
        {
            Log("自动预检失败；尝试双轴软件停车："+ex.Message);
            try{await StopAllAndVerifyAsync();}
            catch(Exception stopEx){Log("危险：停车未确认，请现场使用硬件急停："+stopEx.Message);}
            _armed=false;
            throw;
        }
        finally {_busy=false;await RefreshFeedbackAsync();}
    }


    // Controlled seam crossing for inner-axis preorientation ONLY: unlike a native
    // absolute-position command, a small *relative* command states the intended
    // direction. We still cannot certify native axis conventions without a physical
    // commissioning test, so operator permission and per-step telemetry are mandatory.
    // The outer axis must stay at its mechanical 0° throughout.
    private async Task PositionInnerAcrossWrapAsync(double currentAngle,CancellationToken ct)
    {
        double distance=(90.0-AxisZeroPositionPlanner.Normalize360(currentAngle)+360)%360;
        if(distance>110 || distance<0.30)
            throw new InvalidOperationException("跨界定位条件不满足，只允许已确认的内轴接近360°→90°路径");
        var answer=MessageBox.Show(Window.GetWindow(this),
            $"内轴当前编码器角度 {currentAngle:F3}°（圆周零位等效0°），Pitch测试需要内轴90°。\n\n"+
            $"预期沿【正向相对增量】约 {distance:F2}°，经过0°/360°，先试动+1°，逐段不超过10°、速度1°/s。\n"+
            "每一段会检查实际运动方向、角度变化、到位、故障和外轴静止。\n\n"+
            "必须由现场人员根据厂家旧控制软件确认+方向和跨界机械路径正确；工装/线缆无干涉、机械锁已松开、硬件急停有效。"+
            "如不能确认，选择【否】，在厂家控制软件安全定位内轴90°后再启动本测试。\n\n是否确认正方向+跨界路线？",
            "内轴0/360°→90°：真实相对运动路径授权",
            MessageBoxButton.YesNo,MessageBoxImage.Warning);
        if(answer!=MessageBoxResult.Yes)
            throw new OperationCanceledException("未授权跨0°/360°的内轴正向相对运动；请先用厂家控制软件完成90°预定位");

        double remaining=distance;
        int step=0;
        while(remaining>0.24)
        {
            ct.ThrowIfCancellationRequested();
            var start=await ReadLockedAsync(d=>(d.ReadDetailed(0),d.ReadDetailed(2)));
            var inner=start.Item1;var outer=start.Item2;
            if(!inner.Homed||!inner.Healthy||!outer.Healthy||
               !inner.Axis.Enabled||!outer.Axis.Enabled||!Stationary(inner)||!Stationary(outer)||
               !inner.InPlace || AxisZeroPositionPlanner.AngularDistance(outer.Axis.Position360Deg,0)>.30)
                throw new IOException("跨界分段之前发现未找零、失能、未到位、故障或外轴偏离0°");
            double from=inner.Axis.Position360Deg;
            double to=AxisZeroPositionPlanner.Normalize360(from+Math.Min(step==0?1:10,remaining));
            double delta=Math.Min(step==0?1.0:10.0,remaining);
            var fixedOuter=outer.Axis.Position360Deg;
            Log($"内轴跨界受控相对定位：第{step+1}段，反馈{from:F3}°，下发+{delta:F2}° / 1°/s，目标圆周角约{to:F3}°");
            ct.ThrowIfCancellationRequested();
            await RunLockedAsync(d=>d.MoveRelative(0,delta,1.0));
            var sw=System.Diagnostics.Stopwatch.StartNew();
            int matched=0;
            while(sw.Elapsed<TimeSpan.FromSeconds(Math.Max(22,delta+15)))
            {
                ct.ThrowIfCancellationRequested();
                var fb=await ReadLockedAsync(d=>(d.ReadDetailed(0),d.ReadDetailed(2)));
                if(!fb.Item1.Healthy||!fb.Item2.Healthy||!fb.Item1.Homed||
                   !fb.Item1.Axis.Enabled||!fb.Item2.Axis.Enabled||!Stationary(fb.Item2)||
                   AxisZeroPositionPlanner.AngularDistance(fb.Item2.Axis.Position360Deg,fixedOuter)>.10)
                    throw new IOException("内轴相对跨界运动检测到故障、失能或外轴意外运动");
                double progressed=AxisZeroPositionPlanner.SignedShortDelta(from,fb.Item1.Axis.Position360Deg);
                if(progressed<-.35 || progressed>delta+.8)
                    throw new IOException($"内轴运动方向或距离异常：计划+{delta:F2}°，反馈变化{progressed:F2}°。停止后请核对厂家相对方向约定");
                matched=AxisZeroPositionPlanner.AngularDistance(fb.Item1.Axis.Position360Deg,to)<=.10 &&
                        Stationary(fb.Item1) && fb.Item1.InPlace ? matched+1:0;
                if(matched>=3)break;
                await Task.Delay(180,ct);
            }
            if(matched<3)throw new TimeoutException($"内轴跨界定位第{step+1}段未确认连续3次到位与零速反馈；后续运动已禁止");
            // Use the actual feedback for next-step travel, not the commanded delta.
            var actual=await ReadLockedAsync(d=>d.ReadDetailed(0));
            remaining=AxisZeroPositionPlanner.SignedShortDelta(actual.Axis.Position360Deg,90);
            if(remaining<-.24 || remaining>110)
                throw new IOException("内轴反馈与剩余相对路径不一致；禁止继续定位");
            step++;
            if(step>16)throw new TimeoutException("跨界定位步数异常，禁止继续运动");
        }
        var final=await ReadLockedAsync(d=>d.ReadDetailed(0));
        if(!final.Homed||!final.Healthy||!final.InPlace||!Stationary(final)||
           AxisZeroPositionPlanner.AngularDistance(final.Axis.Position360Deg,90)>.30)
            throw new IOException("跨界预定位未确认真实内轴达到90°，禁止启动Pitch摇摆");
        Log($"内轴已完成经授权的跨界相对预定位；实际反馈={final.Axis.Position360Deg:F3}°（目标90°）");
    }

    // Mechanical reference (GetAxisFindZero) is NOT equivalent to current axis position 0°.
    // Reuses the old calibration workflow: check home status first, then move to test zero.
    // Large moves are split into <=20° waypoints only after an explicit on-site path approval.
    private async Task PositionForTestAsync(int axis,double target,CancellationToken ct)
    {
        ct.ThrowIfCancellationRequested();
        var b=await ReadLockedAsync(d=>(d.ReadDetailed(0),d.ReadDetailed(2)));
        var current=axis==0?b.Item1:b.Item2;
        var other=axis==0?b.Item2:b.Item1;
        if(!current.Homed || !current.Healthy||!other.Healthy ||
           !current.Axis.Enabled||!other.Axis.Enabled||!Stationary(current)||!Stationary(other))
            throw new InvalidOperationException("轴机械找零、使能、故障或静止状态不合格，禁止自动定位");

        double position=current.Axis.Position360Deg;
        // The U-T turntable manual restricts independent axis motion by mounting orientation.
        // The inner axis should never rotate here unless the outer axis is at its known 0° position.
        if(axis==0 && AxisZeroPositionPlanner.AngularDistance(other.Axis.Position360Deg,0)>.30)
            throw new InvalidOperationException("内轴0运动前，外轴2必须停在0°附近。请先安全预定位外轴并检查负载安装条件。");
        // With a nonzero inner axis, automatically moving the outer axis can violate installation clearances.
        if(axis==2 && AxisZeroPositionPlanner.AngularDistance(other.Axis.Position360Deg,0)>.30 &&
           AxisZeroPositionPlanner.AngularDistance(position,target)>.30)
            throw new InvalidOperationException("内轴不在0°时，自动移动外轴可能发生工装干涉。请先按厂家要求确认姿态并手动预定位。");

        // Absolute-position commands near the wrap seam have vendor-dependent path
        // selection. For the sole expected Pitch setup path, use the explicitly
        // authorised, feedback-checked relative microstep routine instead.
        if(axis==0 && target==90 && position>340 && position<=360)
        {
            await PositionInnerAcrossWrapAsync(position,ct);
            return;
        }
        var waypoints=AxisZeroPositionPlanner.Plan(position,target,20);
        if(waypoints.Count==0)
        {
            Log($"轴{axis} 机械找零有效，且已经处于 {target:F1}° 的等效起始位置，无需再次找零或定位");
            return;
        }
        double span=AxisZeroPositionPlanner.TotalTravel(position,waypoints);
        if(span>90.0)
        {
            string route=string.Join(" → ",waypoints.Select(x=>x.ToString("F1",CultureInfo.InvariantCulture)+"°"));
            var confirm=MessageBox.Show(Window.GetWindow(this),
                $"轴{axis} 已经完成机械找零，但当前位置不是 {target:F1}°。\n"+
                $"当前反馈：{position:F2}°，目标：{target:F2}°，计划运动约 {span:F2}°。\n"+
                $"低速分段目标：{route}\n\n"+
                "这是厂家 SetAxisPosition 真实电机运动，不是重复机械找零。\n"+
                "仅当操作员已经确认【完整行程】的工装、负载、滑环线缆、机械限位和其他轴静止，"+
                "并保证人员距离及硬件急停可用时，才能继续。\n"+
                "无法确认时必须选【否】，交由厂家控制台安全预定位。\n\n"+
                "是否授权此次长行程低速分段定位？",
                "长行程回零：现场路径授权",MessageBoxButton.YesNo,MessageBoxImage.Warning);
            if(confirm!=MessageBoxResult.Yes)
                throw new OperationCanceledException($"轴{axis} 约{span:F2}°长行程未获现场路径授权，未发送定位指令");
        }

        Log($"轴{axis} 已机械找零；开始低速分段回到 {target:F1}°。原始角度={position:F3}°，位移={span:F2}°，步骤={waypoints.Count}");
        for(int step=0;step<waypoints.Count;step++)
        {
            ct.ThrowIfCancellationRequested();
            double waypoint=waypoints[step];
            var initial=await ReadLockedAsync(d=>(d.ReadDetailed(0),d.ReadDetailed(2)));
            var moving=axis==0?initial.Item1:initial.Item2;
            var fixedAxis=axis==0?initial.Item2:initial.Item1;
            if(!moving.Healthy||!fixedAxis.Healthy||!moving.Homed||
               !moving.Axis.Enabled||!fixedAxis.Axis.Enabled||!Stationary(moving)||!Stationary(fixedAxis)||
               AxisZeroPositionPlanner.AngularDistance(fixedAxis.Axis.Position360Deg,other.Axis.Position360Deg)>.10)
                throw new IOException($"轴{axis} 第{step+1}步开始前发现故障、未停稳、找零状态丢失或另一轴移动");
            double startPosition=moving.Axis.Position360Deg;
            double travel=waypoint-startPosition;
            if(Math.Abs(travel)>20.5 || Math.Abs(travel)<.001)
            {
                if(Math.Abs(travel)<.04)continue;
                throw new IOException($"轴{axis} 分段行程与反馈不一致（{travel:F2}°），拒绝继续自动运动");
            }
            Log($"轴{axis} 回零定位 {step+1}/{waypoints.Count}：{startPosition:F2}° → {waypoint:F2}°，1°/s");
            ct.ThrowIfCancellationRequested();
            await RunLockedAsync(d=>d.MoveAbsolute(axis,waypoint,1.0));
            var deadline=System.Diagnostics.Stopwatch.StartNew();
            int matches=0;
            while(deadline.Elapsed < TimeSpan.FromSeconds(Math.Max(30,Math.Abs(travel)+20)))
            {
                ct.ThrowIfCancellationRequested();
                var fb=await ReadLockedAsync(d=>(d.ReadDetailed(0),d.ReadDetailed(2)));
                var moved=axis==0?fb.Item1:fb.Item2;
                var otherAxis=axis==0?fb.Item2:fb.Item1;
                if(!moved.Healthy||!otherAxis.Healthy||!moved.Homed||
                   !moved.Axis.Enabled||!otherAxis.Axis.Enabled||!Stationary(otherAxis)||
                   AxisZeroPositionPlanner.AngularDistance(otherAxis.Axis.Position360Deg,other.Axis.Position360Deg)>.10)
                    throw new IOException($"轴{axis} 分段定位期间发生故障、机械找零状态丢失、失能或另一轴意外运动");
                // A short waypoint should not cause an unexpected >180° path through the 0/360 boundary.
                double progress=Math.Sign(travel)*(moved.Axis.Position360Deg-startPosition);
                if(progress<-.5 || progress>Math.Abs(travel)+1.0)
                    throw new IOException($"轴{axis} 运行方向/运动距离与分段计划不一致，请检查厂家绝对位置命令的真实路径");
                matches=Math.Abs(moved.Axis.Position360Deg-waypoint)<=.05 &&
                        Stationary(moved) && moved.InPlace ? matches+1:0;
                if(matches>=3)break;
                await Task.Delay(180,ct);
            }
            if(matches<3)
                throw new TimeoutException($"轴{axis} 第{step+1}段未获得连续位置、速度和厂家到位标志确认，已停止继续下发指令");
        }
        var finalFeedback=await ReadLockedAsync(d=>d.ReadDetailed(axis));
        if(!finalFeedback.Homed || !finalFeedback.Healthy || !finalFeedback.InPlace ||
            !Stationary(finalFeedback) ||
            AxisZeroPositionPlanner.AngularDistance(finalFeedback.Axis.Position360Deg,target)>.30)
            throw new IOException($"轴{axis} 自动定位结束但未确认在 {target:F1}° 等效位置，禁止测试");
        Log($"轴{axis} 已安全完成分段定位，实际角度={finalFeedback.Axis.Position360Deg:F3}°（目标等效 {target:F1}°）");
    }


    /// <summary>Run verified single-axis physical swing, abort on telemetry loss or external stop,
    /// and ALWAYS attempt a stop; report success only after continuous zero-rate feedback.</summary>
    public async Task RunPhysicalSwayAsync(int axis,double amplitudeDeg,double frequencyHz,int cycles,
        IProgress<double> progress,CancellationToken ct,double expectedInner360,Func<bool>? isImuFresh=null)
    {
        if(!_telemetryValid || _device is null || !_safetySessionConfirmed)
            throw new InvalidOperationException("需要有效转台反馈和当前连接的现场运动安全确认");

        if(axis!=2)throw new InvalidOperationException("当前设备坐标约定下，横滚/俯仰倾斜测试均由外轴2摇摆产生；内轴0用于改变方向。");
        if(cycles<3 || cycles>200)throw new ArgumentOutOfRangeException(nameof(cycles));
        var peakSpeed=2*Math.PI*frequencyHz*amplitudeDeg;
        if(!(amplitudeDeg>0&&amplitudeDeg<=30&&frequencyHz>=.02&&frequencyHz<=.5&&peakSpeed<=20))
            throw new InvalidOperationException("当前程序限定幅值≤30°、频率0.02～0.5Hz、峰值速度≤20°/s；还需转台加速度与波形实机验证。");
        await VerifyStableAsync();
        var initial=await ReadLockedAsync(d=>(d.ReadDetailed(0),d.ReadDetailed(2)));
        if(!initial.Item2.Axis.Enabled || !initial.Item1.Axis.Enabled)throw new InvalidOperationException("双轴未全部使能；请先使能并确认正常。");
        if(!initial.Item1.Homed || !initial.Item2.Homed)throw new InvalidOperationException("双轴未全部找零；禁止启动摇摆");
        if(!initial.Item1.Healthy||!initial.Item2.Healthy)
            throw new InvalidOperationException("双轴有故障、限位或超差，禁止自动运行");
        double inner=initial.Item1.Axis.Position360Deg;
        if(AxisZeroPositionPlanner.AngularDistance(inner,expectedInner360)>.35)
            throw new InvalidOperationException($"真实预检发现内轴位置变化：需在{expectedInner360:F1}°附近，现为{inner:F3}°。拒绝发出运动指令。");
        // Starting orientation has already been checked by PrepareAutomaticTestAsync.
        if(Math.Abs(initial.Item2.Axis.Position360Deg)>0.3 && Math.Abs(initial.Item2.Axis.Position360Deg-360)>0.3)
            throw new InvalidOperationException($"外轴应先位于0°附近，当前为{initial.Item2.Axis.Position360Deg:F3}°；预检不通过，拒绝摇摆。");
        if(amplitudeDeg>15 && Math.Abs(inner-90)<.3)
            throw new InvalidOperationException("内轴90°姿态的大幅度摇摆尚未完成实机确认，拒绝下发。");
        _busy=true; _armed=false; // lock out manual controls while auto-test owns motor
        bool commandAttempted=false;
        try
        {
            ct.ThrowIfCancellationRequested();
            commandAttempted=true;
            await RunLockedAsync(d=>d.StartSway(axis,amplitudeDeg,frequencyHz));
            Log($"真实摇摆命令已接受：轴{axis}, 幅值±{amplitudeDeg:F2}°, 频率{frequencyHz:F3}Hz；等待编码器状态确认");
            var duration=TimeSpan.FromSeconds(cycles/frequencyHz);
            var sw=System.Diagnostics.Stopwatch.StartNew();
            double maxActualExcursion=0;
            while(sw.Elapsed<duration)
            {
                ct.ThrowIfCancellationRequested();
                if(isImuFresh is not null && !isImuFresh())throw new IOException("IMU 实时数据已中断，自动请求停车");
                var r=await ReadLockedAsync(d=>(d.ReadDetailed(0),d.ReadDetailed(2)));
                if(!r.Item1.Healthy || !r.Item2.Healthy || !r.Item2.Axis.Enabled)
                    throw new IOException("运动中检测到转台故障、限位或外轴失能");
                if(Math.Abs(r.Item1.Axis.RateDps)>.12 ||
                   Math.Abs(r.Item1.Axis.Position360Deg-initial.Item1.Axis.Position360Deg)>.25)
                    throw new IOException("运动中内轴发生意外位置或速度变化，已请求停车");
                double excursion=(r.Item2.Axis.Position360Deg-initial.Item2.Axis.Position360Deg+540)%360-180;
                maxActualExcursion=Math.Max(maxActualExcursion,Math.Abs(excursion));
                if(maxActualExcursion>amplitudeDeg*1.6+1.0)
                    throw new IOException("编码器检测到实际摆动超出期望幅值包络，正在停车");
                if(Math.Abs(r.Item2.Axis.RateDps)>Math.Max(25,peakSpeed*1.8))
                    throw new IOException("编码器检测到异常角速度，正在停车");
                if(sw.Elapsed.TotalSeconds>1.5/frequencyHz && maxActualExcursion<Math.Min(.5,amplitudeDeg*.25))
                    throw new IOException("转台未观测到实际摇摆位移，不能将DLL接受命令当作成功");
                // Both reference angles and timestamp come from actual DLL feedback, not the sine command.
                var nowTicks=System.Diagnostics.Stopwatch.GetTimestamp();
                FeedbackArrived?.Invoke(new TurntableReadback(sw.Elapsed.TotalSeconds,nowTicks,r.Item1.Axis,r.Item2.Axis));
                progress.Report(Math.Min(.98,sw.Elapsed.TotalSeconds/duration.TotalSeconds));
                await Task.Delay(30,ct);
            }
        }
        finally
        {
            try
            {
                if(commandAttempted)
                {
                    try { await StopAllAndVerifyAsync();
                        _armed=_safetySessionConfirmed && _telemetryValid;
                        Log("自动摇摆已停车且连续回读零速"); }
                    catch(Exception ex){Log("危险：自动摇摆停车未确认："+ex.Message);_armed=false;throw;}
                }
            }
            finally { _busy=false; }
        }
        progress.Report(1.0);
    }

}
