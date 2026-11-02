using System;
using System.Collections.Generic;
using System.Collections.Concurrent;
using System.Globalization;
using System.IO;
using System.IO.Ports;
using System.Diagnostics;
using System.Linq;
using System.Numerics;
using System.Text;
using System.Text.Json;
using System.Security.Cryptography;
using System.Threading;
using System.Threading.Channels;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Media3D;
using System.Windows.Threading;
using Microsoft.Win32;
using DynamicInclinometer.Core;
using DynamicInclinometer.Devices;
using DynamicInclinometer.Infrastructure;
using DynamicInclinometer.App.Controls;

namespace DynamicInclinometer.App;

public partial class MainWindow : Window
{
    private CalibrationProfile? _cal;
    private string? _accPath, _gyroPath;
    private AttitudeEngine _engine = new();
    private readonly object _stateLock = new();
    private readonly object _tableWriterLock = new();
    private readonly object _recordLock = new();
    private ExperimentRecorder? _liveRecorder;
    private long _recordStartTicks;
    private long _recordedCount;
    private long _rateWindowTick;
    private long _rateWindowCount;
    private double _observedProcessingHz;
    private int _candidateOdrHz = 200;

    private AttitudeState _latestState = new(System.Numerics.Quaternion.Identity,0,0,0,false,"待机");
    // Two independent display references. Only ABS is used by the recorder and the automatic-test evaluator.
    private enum TiltDisplayReference { Abs, Rel }
    private TiltDisplayReference _displayReference = TiltDisplayReference.Abs;
    private System.Numerics.Quaternion? _relativeZero;
    private string _relativeZeroDescription = "";

    private ImuSample _latestSample;
    private bool _hasLatest;
    private double _latestAccRoll, _latestAccPitch;
    private long _latestArrivalTicks;
    private long _startCaptureTicks;
    private long _received, _processed, _lost;
    private readonly List<double> _roll = new(),_pitch = new();
    private readonly QuaternionRotation3D _rotation = new();
    private bool _showImuAxes=true;
    private bool _autoOrbitCamera;
    private bool _draggingCamera;
    private System.Windows.Point _lastCameraMouse;
    private double _cameraAzimuth=-135.0;
    private double _cameraElevation=28.0;
    private double _cameraDistance=9.7;
    private readonly Stopwatch _cameraOrbitWatch=Stopwatch.StartNew();
    private readonly DispatcherTimer _uiTimer = new() { Interval = TimeSpan.FromMilliseconds(40) };
    private CancellationTokenSource? _captureCts;
    private Task? _captureTask;
    private bool _disconnecting;
    private bool _rawOutputRequested;
    // Compatibility-only fields: the obsolete automatic-test tab and all of its
    // commands have been removed from XAML. These references are never presented or
    // invoked by the retained monitoring/manual-control interface.
    private readonly ComboBox SweepAxisChoice = new();
    private readonly TextBox SineAmplitude = new();
    private readonly TextBox SineFrequency = new();
    private readonly TextBox SineCycles = new();
    private readonly TextBox ReportDirectoryBox = new();
    private readonly TextBlock ExperimentProgressText = new();
    private readonly ProgressBar ExperimentProgress = new();
    private readonly Button RealAutoRunButton = new();
    private readonly TextBlock ExperimentHint = new();
    private readonly TextBox SineCenter = new();
    private readonly TextBox SineSampleRate = new();
    private readonly TextBox StaticRollRef = new();
    private readonly TextBox StaticPitchRef = new();

    // Reusable GPU glass layer: only backdrop scene is sampled, never the panes
    // themselves (no recursive VisualBrush). The IMU receive/ESKF threads are untouched.
    private readonly Stopwatch _glassClock = Stopwatch.StartNew();
    private readonly List<LiquidGlassPane> _glassPanes = new();
    private bool _glassEnabled = true;
    private bool _shaderFallbackLogged;
    private long _glassLastFrame;
    private int _glassDiscoveryFrames;
    private CancellationTokenSource? _autoTestCts;
    private volatile bool _autoMotionCollecting;
    private readonly object _autoPointsLock=new();
    private readonly List<(long ticks,double roll,double pitch,bool fused,bool synthetic)> _autoAngles=new();
    private readonly List<(long ticks,double inner,double outer,double velocity)> _autoEncoders=new();

    private TimingPolicy _activeCaptureTimingPolicy=TimingPolicy.UnresolvedBatch;
    private SineSweepPlan? _visibleSinePlan;
    private StreamWriter? _turnWriter;
    private string? _runDir;
    private string _experimentRoot = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments),"DynamicInclinometerExperiments");
    private string _sourceDescription="";
    private string _lastError="";
    private bool _isClosing;
    private bool _allowFinalClose;
    private bool _displayFaultReported;
    private bool _plotPaused;
    private long _lastSampleUiUpdateTicks;

    public MainWindow()
    {
        InitializeComponent();
        // Default: product-style calibrated ESKF; unverified MCU time base is labelled research-grade.
        _engine.Mode=ProcessingMode.Eskf;
        _engine.AllowResearchFusionWithUnverifiedConfiguration=true;
        TimingChoice.SelectedIndex=1;
        ResearchOverride.IsChecked=true;
        FusedOutputButton.FontWeight=FontWeights.Bold;
        BuildPcb();
        RefreshPorts();
        _uiTimer.Tick += (_, _) =>
        {
            try { UpdateDisplay(); AdvanceAttitudeCamera(); }
            catch (Exception ex)
            {
                if (_displayFaultReported) return;
                _displayFaultReported = true;
                App.Log("DISPLAY UPDATE FAILED", ex);
                _uiTimer.Stop();
                StatusLabel.Text = "显示更新故障，已记录日志；数据采集状态请检查";
                MessageBox.Show(this, "实时显示发生异常，显示刷新已暂停。请检查日志：\n" + App.DiagnosticsPath,
                    "显示异常", MessageBoxButton.OK, MessageBoxImage.Warning);
            }
        };
        _uiTimer.Start();
        Closing += OnClosing;
        Loaded += (_, _) =>
        {
            FindVisibleGlassPanes();
            CompositionTarget.Rendering += UpdateGlassFrame;
        };
        Closed += (_, _) => CompositionTarget.Rendering -= UpdateGlassFrame;
        MainTabs.SelectionChanged += (_, e) =>
        {
            if(ReferenceEquals(e.OriginalSource,MainTabs))
            {
                Dispatcher.BeginInvoke(new Action(FindVisibleGlassPanes),DispatcherPriority.Loaded);
                RefreshNavigation();
            }
        };
        RecordPathText.Text = "记录目录：" + _experimentRoot;
        ReportDirectoryBox.Text = _experimentRoot;
        if(TurntablePanel is not null)
        {
            TurntablePanel.FeedbackArrived += OnTableFeedbackArrived;
            TurntablePanel.StopRequested += () => _autoTestCts?.Cancel();
        }
        App.Log("MAIN WINDOW CREATED");
        AppendLog("上位机启动；先导入设备号对应的 ACC/GYRO 标定，再选择 IMU COM 连接。仿真与真实数据严格区分。");
        AppendLog("设备超时排查：确认供电、1500000 baud、Modbus RTU 站号1、保持寄存器1000/104和串口占用。");
    }

    // Sidebar replaces the old tab headers, while keeping the original two-page navigation model.
    private bool IsQuickAbsolute => QuickPositionMode.SelectedIndex==1;
    private async void QuickInnerMove_Click(object sender,RoutedEventArgs e)
        => await RunDashboardAxisAsync(0,QuickInnerCommand.Text);
    private async void QuickOuterMove_Click(object sender,RoutedEventArgs e)
        => await RunDashboardAxisAsync(2,QuickOuterCommand.Text);
    private async Task RunDashboardAxisAsync(int axis,string command)
    {
        if(TurntablePanel is not { IsConnected:true })
        {
            MessageBox.Show(this,"请先打开【转台控制】页面并连接真实转台，随后即可从首页执行手动命令。", "转台未连接",MessageBoxButton.OK,MessageBoxImage.Information);
            MainTabs.SelectedIndex=1;
            return;
        }
        try { await TurntablePanel.MoveFromDashboardAsync(axis,command,QuickMoveSpeed.Text,IsQuickAbsolute); }
        catch(Exception ex) { App.Log("QUICK TABLE COMMAND",ex);AppendLog("快捷转台指令未执行："+ex.Message); }
    }
    private async void QuickHomeBoth_Click(object sender,RoutedEventArgs e)
    {
        if(TurntablePanel is not { IsConnected:true })
        {
            MessageBox.Show(this,"先在【转台控制】页连接真实转台。", "双轴归零尚不可用");
            MainTabs.SelectedIndex=1;return;
        }
        try { await TurntablePanel.HomeFromDashboardAsync(); }
        catch(Exception ex) { App.Log("QUICK HOME",ex);AppendLog("快捷双轴归零未执行："+ex.Message); }
    }
    private async void QuickStopBoth_Click(object sender,RoutedEventArgs e)
    {
        try { if(TurntablePanel is not null)await TurntablePanel.StopFromDashboardAsync(); }
        catch(Exception ex) { App.Log("QUICK STOP",ex);AppendLog("转台停车未确认："+ex.Message); }
    }
    private void ClearPlot_Click(object sender,RoutedEventArgs e)
    {
        lock(_stateLock){_roll.Clear();_pitch.Clear();}
        RollLine.Points=new PointCollection();PitchLine.Points=new PointCollection();
        AppendLog("用户清空实时趋势显示（不删除任何已记录 CSV 数据）");
    }
    private void PlotPause_Click(object sender,RoutedEventArgs e)
    {
        _plotPaused=!_plotPaused;
        PlotPauseButton.Content=_plotPaused?"继续画面":"暂停画面";
        AppendLog(_plotPaused?"暂停绘制实时曲线，采集和文件记录仍继续":"恢复实时曲线绘制");
    }
    private void UpdateAcquisitionReadouts()
    {
        // Connection starts monitoring; the separate toggle is solely for writing files.
        bool connected=_captureCts is not null && !_captureCts.IsCancellationRequested;
        bool recording;
        lock(_recordLock) recording=_liveRecorder is not null;
        ConnectImuButton.Content=connected?"断开设备":"连接设备";
        ConnectImuButton.IsEnabled=!_disconnecting;
        StopImuButton.Content=recording?"■  停止采集":"▶  开始采集";
        StopImuButton.IsEnabled=connected && !_disconnecting;
        RecordStateText.Text=!connected?"未连接 / 未记录":recording?"● 正在保存":"● 在线监测 · 未记录";
        RecordStateText.Foreground=new SolidColorBrush(recording?Color.FromRgb(118,218,160):Color.FromRgb(169,192,212));
        long now=Stopwatch.GetTimestamp();
        if(!connected)
        {
            SessionElapsedText.Text="--:--:--";
            SampleRateText.Text="-- Hz";
            ProcessedCountText.Text="--";
            LostCountText.Text="--";
            OdrDisplayText.Text=$"芯片 ODR 未读回（硬件报告 833 Hz） · 时标候选 {_candidateOdrHz} Hz";
            TopConnectionLamp.Fill=new SolidColorBrush(Color.FromRgb(113,128,150));
            return;
        }
        if(recording)
        {
            double duration=Math.Max(0,(now-_recordStartTicks)/(double)Stopwatch.Frequency);
            SessionElapsedText.Text=TimeSpan.FromSeconds(duration).ToString(@"hh\:mm\:ss",CultureInfo.InvariantCulture);
        }
        else SessionElapsedText.Text="--:--:--";
        ProcessedCountText.Text=Interlocked.Read(ref _recordedCount).ToString("N0",CultureInfo.InvariantCulture);
        LostCountText.Text=Interlocked.Read(ref _lost).ToString("N0",CultureInfo.InvariantCulture);
        double windowSeconds=(now-_rateWindowTick)/(double)Stopwatch.Frequency;
        if(windowSeconds>=1.0)
        {
            long processed=Interlocked.Read(ref _processed);
            _observedProcessingHz=(processed-_rateWindowCount)/windowSeconds;
            _rateWindowCount=processed;
            _rateWindowTick=now;
        }
        bool fresh=_hasLatest && (now-_latestArrivalTicks)/(double)Stopwatch.Frequency<1.5;
        SampleRateText.Text=fresh?$"{_observedProcessingHz:F0} Hz":"-- Hz";
        OdrDisplayText.Text=$"芯片 ODR 未读回（硬件报告 833 Hz） · 时标候选 {_candidateOdrHz} Hz";
        OdrDisplayText.ToolTip=$"硬件工程师报告 ASM330LHHX 设置为 833 Hz，但当前没有芯片 ODR 寄存器读回。\n\n"+
            $"最近1秒上位机有效处理率 {_observedProcessingHz:F1} 样本/s；目前时间重建候选 {_candidateOdrHz} Hz（不等于已验证 ODR）。\n\n"+
            "如存在差异，应核对 MCU CTRL1_XL / CTRL2_G、FIFO、时标和串口吞吐，不应直接把处理率当作芯片采样率。";
        TopConnectionLamp.Fill=new SolidColorBrush(fresh?Color.FromRgb(81,212,147):Color.FromRgb(201,158,86));
    }

    private void NavMonitor_Click(object sender,RoutedEventArgs e)
    {
        MainTabs.SelectedIndex=0;
        RefreshNavigation();
    }
    private void NavTurntable_Click(object sender,RoutedEventArgs e)
    {
        MainTabs.SelectedIndex=1;
        RefreshNavigation();
    }
    private void NavRecords_Click(object sender,RoutedEventArgs e)
    {
        // The product records to the session directory: no fake history database or demo data.
        try
        {
            Directory.CreateDirectory(_experimentRoot);
            Process.Start(new ProcessStartInfo("explorer.exe",_experimentRoot){UseShellExecute=true});
        }
        catch(Exception ex)
        {
            App.Log("OPEN RECORD DIRECTORY FAILED",ex);
            MessageBox.Show(this,"无法打开数据记录目录："+ex.Message+"\n"+_experimentRoot);
        }
    }
    private void NavSettings_Click(object sender,RoutedEventArgs e)
    {
        MainTabs.SelectedIndex=0;
        AdvancedPanel.IsExpanded=true;
        Dispatcher.BeginInvoke(new Action(()=>AdvancedPanel.BringIntoView()),DispatcherPriority.Loaded);
        RefreshNavigation();
    }
    private void RefreshNavigation()
    {
        if(NavMonitorButton is null || NavTurntableButton is null)return;
        NavMonitorButton.Style=(Style)FindResource(MainTabs.SelectedIndex==0?"NavSelected":"NavAction");
        NavTurntableButton.Style=(Style)FindResource(MainTabs.SelectedIndex==1?"NavSelected":"NavAction");
    }

    private void FindVisibleGlassPanes()
    {
        // TabControl creates its inactive content on demand. Refresh after tab switches.
        _glassPanes.Clear();
        WalkGlassTree(this);
        foreach (var pane in _glassPanes)
        {
            pane.BackgroundVisual = LiquidScene;
            pane.SetGlassActive(_glassEnabled);
            pane.SetDistortion(GlassStrengthSlider.Value);
            pane.RefreshSampling();
        }
        GlassGpuToggleButton.Content = _glassEnabled ? "关闭 GPU 折射" : "开启 GPU 折射";
        GlassStatusText.Text = !_glassEnabled ? "省资源模式 · 玻璃高光保留" :
            _glassPanes.Any(p => !p.ShaderAvailable)
                ? "着色器未加载 · 已回退普通玻璃（详情见诊断日志）"
                : "原生 GPU 折射 · 20 FPS 限速";
        if (_glassPanes.Any(p => !p.ShaderAvailable) && !_shaderFallbackLogged)
        {
            _shaderFallbackLogged = true;
            AppendLog("GPU 着色器不可用，已自动使用普通玻璃：" +
                _glassPanes.First(p => !p.ShaderAvailable).ShaderDiagnostic);
        }
    }

    private void WalkGlassTree(DependencyObject parent)
    {
        if (parent is LiquidGlassPane pane)
        {
            _glassPanes.Add(pane);
            return; // visual parts of the pane do not need additional traversal
        }
        int count;
        try { count = VisualTreeHelper.GetChildrenCount(parent); }
        catch (InvalidOperationException) { return; }
        for (int i = 0; i < count; i++) WalkGlassTree(VisualTreeHelper.GetChild(parent,i));
    }

    private void UpdateGlassFrame(object? sender,EventArgs e)
    {
        if(!_glassEnabled || !IsVisible || WindowState==WindowState.Minimized)return;
        long ticks=_glassClock.ElapsedTicks;
        if ((ticks-_glassLastFrame)/(double)Stopwatch.Frequency < 0.05) return;
        _glassLastFrame=ticks;
        // Re-discover lazily loaded manual tab content about every 3 s.
        if(++_glassDiscoveryFrames>=60)
        {
            _glassDiscoveryFrames=0;
            FindVisibleGlassPanes();
        }
        double elapsed=_glassClock.Elapsed.TotalSeconds;
        foreach(var pane in _glassPanes)
            if(pane.IsVisible) pane.SetTime(elapsed);
    }

    private void ToggleGpuGlass_Click(object sender,RoutedEventArgs e)
    {
        _glassEnabled=!_glassEnabled;
        foreach(var pane in _glassPanes) pane.SetGlassActive(_glassEnabled);
        GlassGpuToggleButton.Content = _glassEnabled ? "关闭 GPU 折射" : "开启 GPU 折射";
        GlassStatusText.Text = !_glassEnabled ? "省资源模式 · 玻璃高光保留" :
            _glassPanes.Any(p => !p.ShaderAvailable)
                ? "着色器未加载 · 已回退普通玻璃（详情见诊断日志）"
                : "原生 GPU 折射 · 20 FPS 限速";
        AppendLog("液态玻璃 GPU 动态效果：" + (_glassEnabled?"已启用":"已关闭"));
    }

    private void GlassDistortion_ValueChanged(object sender,RoutedPropertyChangedEventArgs<double> e)
    {
        foreach(var pane in _glassPanes) pane.SetDistortion(e.NewValue);
    }

    private void AppendLog(string message)
    {
        if(!Dispatcher.CheckAccess()) { Dispatcher.BeginInvoke(new Action(()=>AppendLog(message))); return; }
        var line=$"[{DateTime.Now:HH:mm:ss.fff}] {message}";
        RunLog.AppendText(line+Environment.NewLine);
        if(message.Contains("故障",StringComparison.OrdinalIgnoreCase)||message.Contains("失败",StringComparison.OrdinalIgnoreCase)||message.Contains("超时",StringComparison.OrdinalIgnoreCase)||message.Contains("timed out",StringComparison.OrdinalIgnoreCase))
            LogExpander.IsExpanded=true;
        if(RunLog.Text.Length>45000)RunLog.Text=RunLog.Text[^30000..];
        RunLog.ScrollToEnd();
        try
        {
            var path=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                                  "DynamicInclinometerLab","session.log");
            Directory.CreateDirectory(Path.GetDirectoryName(path)!);
            File.AppendAllText(path,line+Environment.NewLine,Encoding.UTF8);
        }
        catch(Exception ex){App.Log("SESSION LOG WRITE FAILED",ex);}
    }
    private void CopyLog_Click(object sender,RoutedEventArgs e)
    {
        try { Clipboard.SetText(RunLog.Text); AppendLog("可见运行日志已复制到剪贴板"); }
        catch(Exception ex){MessageBox.Show(this,"复制日志失败："+ex.Message);}
    }
    private void OpenLogFolder_Click(object sender,RoutedEventArgs e)
    {
        try {Process.Start(new ProcessStartInfo("explorer.exe",Path.GetDirectoryName(App.DiagnosticsPath)!){UseShellExecute=true});}
        catch(Exception ex){MessageBox.Show(this,"无法打开日志目录："+ex.Message+"\n"+App.DiagnosticsPath);}
    }

    // Industrial IMU model: real WPF mesh, full 3D perspective, material highlights and
    // mechanically detailed enclosure. It is deliberately an illustrative generic model.
    private void BuildPcb()
    {
        DeviceVisual.Content=IndustrialImu3D.CreateBody(_rotation,_showImuAxes);
        ReferenceAxesVisual.Content=IndustrialImu3D.CreateWorldReference(_showImuAxes);
        ApplyAttitudeCamera();
    }

    // The camera is independent of ESKF quaternion / hardware attitude.
    private void ApplyAttitudeCamera()
    {
        if(AttitudeViewport.Camera is not PerspectiveCamera camera)return;
        double az=_cameraAzimuth*Math.PI/180,el=_cameraElevation*Math.PI/180;
        double radius=_cameraDistance*Math.Cos(el);
        var position=new Point3D(radius*Math.Cos(az),radius*Math.Sin(az),_cameraDistance*Math.Sin(el));
        var target=new Point3D(0,0,-.055);
        camera.Position=position;
        camera.LookDirection=target-position;
        camera.UpDirection=new Vector3D(0,0,1);
        camera.FieldOfView=42;
        camera.NearPlaneDistance=.05;
    }
    private void ResetAttitudeCamera_Click(object sender,RoutedEventArgs e)
    {
        _cameraAzimuth=-135.0;_cameraElevation=28.0;_cameraDistance=9.7;
        _autoOrbitCamera=false;
        AutoOrbitCameraButton.Content="环绕视角";
        ApplyAttitudeCamera();
    }
    private void ToggleImuAxes_Click(object sender,RoutedEventArgs e)
    {
        _showImuAxes=!_showImuAxes;
        ToggleAxesButton.Content=_showImuAxes?"隐藏坐标轴":"显示坐标轴";
        BuildPcb();
    }
    private void AutoOrbitCamera_Click(object sender,RoutedEventArgs e)
    {
        _autoOrbitCamera=!_autoOrbitCamera;
        _cameraOrbitWatch.Restart();
        AutoOrbitCameraButton.Content=_autoOrbitCamera?"停止环绕":"环绕视角";
    }
    private void AttitudeScene_MouseDown(object sender,System.Windows.Input.MouseButtonEventArgs e)
    {
        if(e.ChangedButton!=System.Windows.Input.MouseButton.Left)return;
        _draggingCamera=true;
        _lastCameraMouse=e.GetPosition(AttitudeSceneSurface);
        _autoOrbitCamera=false;
        AutoOrbitCameraButton.Content="环绕视角";
        AttitudeSceneSurface.CaptureMouse();
        e.Handled=true;
    }
    private void AttitudeScene_MouseUp(object sender,System.Windows.Input.MouseButtonEventArgs e)
    {
        if(e.ChangedButton!=System.Windows.Input.MouseButton.Left)return;
        _draggingCamera=false;
        if(AttitudeSceneSurface.IsMouseCaptured)AttitudeSceneSurface.ReleaseMouseCapture();
        e.Handled=true;
    }
    private void AttitudeScene_MouseMove(object sender,System.Windows.Input.MouseEventArgs e)
    {
        if(!_draggingCamera)return;
        var pos=e.GetPosition(AttitudeSceneSurface);
        _cameraAzimuth+=(pos.X-_lastCameraMouse.X)*.43;
        _cameraElevation=Math.Clamp(_cameraElevation-(pos.Y-_lastCameraMouse.Y)*.37,-65,85);
        _lastCameraMouse=pos;
        ApplyAttitudeCamera();
        e.Handled=true;
    }
    private void AttitudeScene_MouseWheel(object sender,System.Windows.Input.MouseWheelEventArgs e)
    {
        _cameraDistance=Math.Clamp(_cameraDistance*Math.Pow(.90,e.Delta/120.0),5.8,17.0);
        ApplyAttitudeCamera();e.Handled=true;
    }
    private void AdvanceAttitudeCamera()
    {
        if(!_autoOrbitCamera)return;
        double dt=Math.Min(.12,_cameraOrbitWatch.Elapsed.TotalSeconds);
        _cameraOrbitWatch.Restart();
        _cameraAzimuth+=dt*11.0;
        ApplyAttitudeCamera();
    }

    private void RefreshPorts()
    {
        var imu=ImuPort.SelectedItem as string;var table=TurntablePort.SelectedItem as string;
        string[] names;
        try { names = SerialPort.GetPortNames().OrderBy(x => x).ToArray(); }
        catch (Exception ex)
        {
            App.Log("SERIAL PORT ENUMERATION FAILED", ex);
            StatusLabel.Text = "串口列表读取失败：" + ex.Message;
            AppendLog(StatusLabel.Text);
            return;
        }
        ImuPort.ItemsSource=names.Length>0?names:new[]{"无可用 COM 串口"};TurntablePort.ItemsSource=names.Length>0?names:new[]{"无可用 COM 串口"};
        AppendLog(names.Length==0 ? "未检测到 COM 串口：请检查 USB 串口线和设备管理器" : "检测到串口："+string.Join("、",names));
        if(imu!=null&&names.Contains(imu))ImuPort.SelectedItem=imu;else if(names.Length>0)ImuPort.SelectedIndex=0;
        if(table!=null&&names.Contains(table))TurntablePort.SelectedItem=table;else if(names.Length>1)TurntablePort.SelectedIndex=1;
        else if(names.Length==0){ImuPort.SelectedIndex=0;TurntablePort.SelectedIndex=0;}
        TurntablePanel?.SuggestPort(TurntablePort.SelectedItem as string);
    }
    private void RefreshPorts_Click(object sender,RoutedEventArgs e)=>RefreshPorts();

    private bool EnsureStopped()
    {
        if(_captureCts!=null){MessageBox.Show(this,"请先停止采集，再修改设备、校准或算法。","状态锁定");return false;}
        return true;
    }
    private void ImportAcc_Click(object sender,RoutedEventArgs e)
    {
        if(!EnsureStopped())return;
        var d=new OpenFileDialog{Filter="Calibration JSON (*.json)|*.json"};if(d.ShowDialog(this)!=true)return;
        try
        {
            var cal=CalibrationProfile.Load(d.FileName);
            if(cal.DeviceSerial!=SerialId.Text.Trim())throw new InvalidDataException($"设备编号不匹配：界面 {SerialId.Text.Trim()} / JSON {cal.DeviceSerial}");
            _cal=cal;_accPath=d.FileName;_gyroPath=null;_engine.Reset();
            InvalidateRelativeZero("ACC 校准文件更换");
            CalibrationText.Text=$"已绑定 ACC · 编号 {cal.DeviceSerial} · {cal.Verdict} · {(!cal.ApprovedForProduction?"仅用于常温研发，未准予出厂":"生产放行标志已设置（仍需硬件配置核验）")} · GYRO 未绑定";
            StatusLabel.Text="ACC 校准已加载";
            AppendLog($"ACC 校准导入成功：设备 {cal.DeviceSerial} · {Path.GetFileName(d.FileName)} · {cal.Verdict}");
        }
        catch(Exception ex)
        {
            App.Log("ACC IMPORT FAILED", ex);
            AppendLog("ACC 校准导入失败："+ex.Message);
            MessageBox.Show(this, ex.Message, "ACC 校准无法加载", MessageBoxButton.OK, MessageBoxImage.Warning);
        }
    }
    private void ImportGyro_Click(object sender,RoutedEventArgs e)
    {
        if(!EnsureStopped())return;
        if(_cal==null){MessageBox.Show(this,"请先加载 ACC 校准文件");return;}
        var d=new OpenFileDialog{Filter="Gyroscope JSON (*.json)|*.json"};if(d.ShowDialog(this)!=true)return;
        try
        {
            var updated = _cal.WithGyro(d.FileName);
            _cal = updated;
            _gyroPath = d.FileName;
            _engine.Reset();
            InvalidateRelativeZero("GYRO 校准文件更换");
            CalibrationText.Text = $"ACC + GYRO 已绑定 · 设备 {updated.DeviceSerial} · ACC: {updated.Verdict} · GYRO: {updated.GyroVerdict} · " +
                "量程/ODR/采样时间仍需核验；校准报告状态不会自动升级为出厂合格";
            StatusLabel.Text = "GYRO 校准已载入：" + Path.GetFileName(d.FileName);
            App.Log("GYRO IMPORTED; device=" + updated.DeviceSerial + "; verdict=" + updated.GyroVerdict);
            AppendLog($"GYRO 校准导入成功：设备 {updated.DeviceSerial} · {Path.GetFileName(d.FileName)} · {updated.GyroVerdict}");
        }
        catch(Exception ex)
        {
            App.Log("GYRO IMPORT FAILED", ex);
            AppendLog("GYRO 校准导入失败："+ex.Message);
            MessageBox.Show(this, ex.Message, "GYRO 校准无法加载", MessageBoxButton.OK, MessageBoxImage.Warning);
        }
    }
    private bool Ready()
    {
        if(!EnsureStopped())return false;
        if (_cal==null || _accPath==null || _cal.DeviceSerial!=SerialId.Text.Trim() || !_cal.HasGyro || _gyroPath==null)
        {
            MessageBox.Show(this,"请先填写设备编号，导入同一设备的 ACC、GYRO 两份标定文件，再开始成品式实时融合。\n\n固件尚未提供可信的唯一设备号，当前依靠输入编号与校准文件匹配。","校准文件未齐全");
            return false;
        }
        return true;
    }
    private (string Port, int Baud, byte Slave, int TimeoutMs, bool DtrRts)? ReadImuConnectionParameters()
    {
        if (ImuPort.SelectedItem is not string port || !port.StartsWith("COM", StringComparison.OrdinalIgnoreCase))
        {
            AppendLog("无有效 IMU COM：请刷新端口，确保选中了传感器 USB 串口，而不是 2TD600 转台串口。");
            MessageBox.Show(this,"请先选择真实 IMU 的 COM 串口。", "串口未选择");return null;
        }
        if (TurntablePanel is { IsConnected:true } && TurntablePanel.SelectedPort is string table && string.Equals(table,port,StringComparison.OrdinalIgnoreCase))
        {
            AppendLog("安全检查：IMU 与转台 COM 相同，拒绝发送 Modbus 请求。");
            MessageBox.Show(this,"IMU COM 与转台 COM 不能相同；请检查设备管理器中的实际接口。","端口冲突");return null;
        }
        if (!int.TryParse(ImuBaudInput.Text,NumberStyles.Integer,CultureInfo.InvariantCulture,out int baud)||baud<1200||baud>5000000)
        {MessageBox.Show(this,"IMU 波特率不合法（建议按固件配置；旧版默认 1500000）。");return null;}
        if (!byte.TryParse(ImuSlaveInput.Text,NumberStyles.Integer,CultureInfo.InvariantCulture,out byte slave)||slave<1||slave>247)
        {MessageBox.Show(this,"Modbus 从站地址应为 1～247。");return null;}
        if (!int.TryParse(ImuTimeoutInput.Text,NumberStyles.Integer,CultureInfo.InvariantCulture,out int timeout)||timeout<250||timeout>10000)
        {MessageBox.Show(this,"超时时间应在 250～10000 毫秒之间。");return null;}
        return (port,baud,slave,timeout,DtrRtsChoice.IsChecked==true);
    }

    private async void DiagnoseModbus_Click(object sender,RoutedEventArgs e)
    {
        if (_captureCts!=null){MessageBox.Show(this,"请先停止实时采集，再运行一次性通信检查。");return;}
        var setting=ReadImuConnectionParameters(); if(setting is null)return;
        var cfg=setting.Value;
        DiagnosticButton.IsEnabled=false;
        try
        {
            AppendLog($"一次性只读诊断：{cfg.Port} / {cfg.Baud} baud / slave={cfg.Slave} / timeout={cfg.TimeoutMs}ms / DTR+RTS={cfg.DtrRts}。仅发 1000×104 读取，不控制转台。");
            string message=await Task.Run(()=>SerialImuSource.Probe(cfg.Port,cfg.Baud,cfg.Slave,cfg.TimeoutMs,cfg.DtrRts));
            AppendLog(message);
            MessageBox.Show(this,message,"IMU 通信诊断",MessageBoxButton.OK,MessageBoxImage.Information);
        }
        catch(Exception ex)
        {
            AppendLog("IMU 通信检查失败："+ex.Message);
            App.Log("IMU PROBE FAILED",ex);
            MessageBox.Show(this,ex.Message+"\n\n详见可复制运行日志。","IMU 通信诊断",MessageBoxButton.OK,MessageBoxImage.Warning);
        }
        finally {DiagnosticButton.IsEnabled=true;}
    }

    private async void Connect_Click(object sender,RoutedEventArgs e)
    {
        if(_disconnecting)return;
        if(_captureCts is not null)
        {
            _disconnecting=true;
            ConnectImuButton.IsEnabled=false;
            try { await StopCaptureAsync(); }
            finally { _disconnecting=false; ConnectImuButton.IsEnabled=true; }
            return;
        }
        if(!Ready())return;
        var setting=ReadImuConnectionParameters();if(setting is null)return;
        var cfg=setting.Value;
        if(!int.TryParse(OdrInput.Text,NumberStyles.Integer,CultureInfo.InvariantCulture,out int odr)||odr<0||odr>6667)
        {MessageBox.Show(this,"候选 ODR 不合法");return;}
        var pol=TimingChoice.SelectedIndex switch{1=>TimingPolicy.EngineeringAssumptionLastSampleTick,2=>TimingPolicy.FirmwareVerifiedLastSampleTick,_=>TimingPolicy.UnresolvedBatch};
        if(pol==TimingPolicy.FirmwareVerifiedLastSampleTick)
        {
            if(MessageBox.Show(this,"只有在已核验 MCU 固件定义了 Tick=本帧末样本时间，且量程、ODR配置真实有效时才能选择此模式。\n是否已经完成实机及固件验证？","时间来源确认",MessageBoxButton.YesNo,MessageBoxImage.Warning)!=MessageBoxResult.Yes)return;
        }
        if(pol==TimingPolicy.EngineeringAssumptionLastSampleTick)
            AppendLog("时间策略：采用研究级批次末样本时标假设；实时显示开放，精度验收需核实采样时间。");
        AppendLog($"请求连接 IMU：{cfg.Port} / {cfg.Baud} baud / RTU站号{cfg.Slave} / 03 / 寄存器1000×104 / 超时{cfg.TimeoutMs}ms / DTR+RTS={cfg.DtrRts}");
        _activeCaptureTimingPolicy=pol;
        _candidateOdrHz=odr;
        BeginCapture(new SerialImuSource(cfg.Port,baud:cfg.Baud,slave:cfg.Slave,timingPolicy:pol,fallbackOdr:odr,timeoutMs:cfg.TimeoutMs,dtrRts:cfg.DtrRts),"REAL "+cfg.Port);
    }
    private void Demo_Click(object sender,RoutedEventArgs e)
    {
        if(!Ready())return;
        BeginCapture(new SimulatedImuSource(_cal!),"SYNTHETIC / 仿真");
    }
    private void Replay_Click(object sender,RoutedEventArgs e)
    {
        if(!Ready())return;
        var d=new OpenFileDialog{Filter="Recorded CSV (raw_processed.csv)|raw_processed.csv|All CSV (*.csv)|*.csv"};
        if(d.ShowDialog(this)!=true)return;
        var manifest=Path.Combine(Path.GetDirectoryName(d.FileName)!,"manifest.json");
        if(File.Exists(manifest))
        {
            try
            {
                using var json=JsonDocument.Parse(File.ReadAllText(manifest));
                string? sid=json.RootElement.GetProperty("device_serial").GetString();
                if(sid!=_cal!.DeviceSerial){MessageBox.Show(this,"记录设备编号与当前校准不匹配，拒绝回放。");return;}
                var accHash=json.RootElement.TryGetProperty("acc_sha256",out var h)?h.GetString():null;
                var actualHash=Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(_accPath!)));
                if(accHash!=actualHash && MessageBox.Show(this,"注意：当前 ACC 校准与原实验快照不一致。重新计算属于校准算法对比，不能覆盖旧结果。是否继续？","校准版本变化",MessageBoxButton.YesNo,MessageBoxImage.Warning)!=MessageBoxResult.Yes)return;
            }
            catch(Exception ex){MessageBox.Show(this,"无法验证回放元数据："+ex.Message);return;}
        }
        else{MessageBox.Show(this,"所选 CSV 缺少 manifest.json，不能证明设备身份与校准参数对应。", "回放被拒绝");return;}
        BeginCapture(new ReplayImuSource(d.FileName),"REPLAY / 旧数据重算");
    }
    private void EnableEngineeringFusion_Click(object sender,RoutedEventArgs e)
    {
        if(!EnsureStopped())return;
        if(_cal?.HasGyro!=true)
        {
            MessageBox.Show(this,"请先导入设备编号一致的 ACC、GYRO 两份真实标定文件。","无法启动融合");return;
        }
        if(MessageBox.Show(this,
            "准备开启【真实 IMU 的 ESKF 实时融合工程模式】。\n\n"+
            "当前 MCU 的 ODR 字段为 0，Tick 对应哪组样本尚未核实。程序将暂时假设 Tick 为一批16组数据中最后一组的时间，并使用界面候选 ODR 重建时间。\n\n"+
            "这能用于观察真实滤波器是否运行，但角度、相位、精度和延迟都不能据此验收。请确认先做研发调试？",
            "研究级融合 / 时间假设未核实",MessageBoxButton.YesNo,MessageBoxImage.Warning)!=MessageBoxResult.Yes)return;
        TimingChoice.SelectedIndex=1;
        ResearchOverride.IsChecked=true;
        _rawOutputRequested=false;
        lock(_stateLock){_engine.Mode=ProcessingMode.Eskf;_engine.Reset();}
        InvalidateRelativeZero("研究级 ESKF 重新初始化");
        ModeText.Text="ESKF 已选；请点击【连接 IMU】开始实时融合（研发级）";
        AppendLog("手动启用 ESKF 工程融合：Tick=最后样本、ODR=候选值、研究覆盖开；未核实，不可用于精度验收");
    }
    private void AccMode_Click(object sender,RoutedEventArgs e)=>SetMode(ProcessingMode.AccelerometerOnly);
    private void MahonyMode_Click(object sender,RoutedEventArgs e)=>SetMode(ProcessingMode.Mahony);
    private void EskfMode_Click(object sender,RoutedEventArgs e)=>SetMode(ProcessingMode.Eskf);
    private void SetMode(ProcessingMode m)
    {
        if(!EnsureStopped())return;
        if(m!=ProcessingMode.AccelerometerOnly&&_cal?.HasGyro!=true){MessageBox.Show(this,"必须加载设备编号一致的真实陀螺仪校准文件。演示示例数据不等于陀螺仪标定。", "融合锁定");return;}
        _rawOutputRequested=false;
        lock(_stateLock){_engine.Mode=m;_engine.Reset();}
        InvalidateRelativeZero("姿态算法切换");
        ModeText.Text="待运行 · "+m;
    }
    private void Reset_Click(object sender,RoutedEventArgs e)
    {
        if(!EnsureStopped())return;
        lock(_stateLock)_engine.Reset();
        InvalidateRelativeZero("滤波器重置");
        StatusLabel.Text="滤波器已重置";
    }
    private string ResolveReportDirectory()
    {
        string? raw=ReportDirectoryBox.Text.Trim();
        if(string.IsNullOrWhiteSpace(raw))throw new InvalidDataException("请先填写报告保存目录。 ");
        string result=Path.GetFullPath(Environment.ExpandEnvironmentVariables(raw));
        Directory.CreateDirectory(result);
        _experimentRoot=result;
        return result;
    }

    private static double ParseUserDouble(string text,string field)
    {
        if(!double.TryParse(text,NumberStyles.Float,CultureInfo.InvariantCulture,out var value)||!double.IsFinite(value))
            throw new InvalidDataException($"{field} 必须使用有效数字（小数点为 .）");
        return value;
    }
    private static int ParseUserInt(string text,string field)
    {
        if(!int.TryParse(text,NumberStyles.Integer,CultureInfo.InvariantCulture,out var value))
            throw new InvalidDataException($"{field} 必须是整数");
        return value;
    }
    private SineSweepPlan ReadSinePlan()
    {
        var axis=SweepAxisChoice.SelectedIndex==1?SweepAxis.Pitch:SweepAxis.Roll;
        var plan=new SineSweepPlan(axis,ParseUserDouble(SineAmplitude.Text,"幅值"),
           ParseUserDouble(SineFrequency.Text,"频率"),ParseUserInt(SineCycles.Text,"周期数"),
           ParseUserDouble(SineCenter.Text,"中心角"),ParseUserInt(SineSampleRate.Text,"采样率"));
        plan.Validate();return plan;
    }
    private readonly bool _automaticTestingRemoved = true;
    private async void RealAutoRun_Click(object sender,RoutedEventArgs e)
    {
        // No UI exposes this legacy handler in the monitoring/manual-only release.
        // Keep this guard in case old integrations attempt to call it by reflection.
        if(_automaticTestingRemoved)
        {
            AppendLog("自动测试已从此版本移除；不会发送任何自动摇摆命令");
            return;
        }
        if(_autoTestCts is not null)return;
        try
        {
            if(_captureCts is null || !_sourceDescription.StartsWith("REAL",StringComparison.Ordinal))
                throw new InvalidOperationException("请先连接真实 IMU 并持续采集。自动测试不接受仿真/回放数据。");
            if(_cal?.HasGyro!=true || _rawOutputRequested || _engine.Mode!=ProcessingMode.Eskf)
                throw new InvalidOperationException("自动动态测试要求已导入编号一致的 ACC/GYRO，并选择校准 + ESKF 输出。");
            if(TurntablePanel is null)
                throw new InvalidOperationException("找不到转台控制模块。请重新打开软件并查看启动日志。");
            var tableBlocker=TurntablePanel.GetAutomaticTestBlocker();
            if(tableBlocker is not null)
                throw new InvalidOperationException(tableBlocker);
            if(!_hasLatest || (Stopwatch.GetTimestamp()-_latestArrivalTicks)/(double)Stopwatch.Frequency>1.0)
                throw new InvalidOperationException("没有新鲜的 IMU 数据，请检查采集连接。");
            var plan=ReadSinePlan();
            if(plan.CenterDeg!=0)throw new InvalidOperationException("当前真实自动摇摆要求中心角为0°。先在安全位置验证后才能开放其它中心角。");
            ResolveReportDirectory();
            if(string.IsNullOrWhiteSpace(ReportDirectoryBox.Text))throw new InvalidOperationException("请先选择报告保存目录");
            double innerTarget=plan.Axis==SweepAxis.Roll?0:90;
            if(MessageBox.Show(this,$"准备执行【真实转台】{plan.Axis} 测试。\n\n程序将自动读取双轴找零标志，必要时受控找零，再确认外轴0°及内轴{innerTarget:F0}°。"+
                $"\n之后外轴2 摇摆 ±{plan.AmplitudeDeg:F1}°，{plan.FrequencyHz:F3}Hz，{plan.Cycles}周期。"+
                "\n\n需确认机械空间、工装锁紧与实体急停，找零可能产生大角度运动。该操作只生成研发报告，绝非精度验收。\n\n继续？",
                "真实转台自动测试准备",MessageBoxButton.YesNo,MessageBoxImage.Warning)!=MessageBoxResult.Yes)return;
            string root=Path.Combine(_experimentRoot,$"REAL_SINE_{DateTime.Now:yyyyMMdd_HHmmss}_{plan.Axis}");
            Directory.CreateDirectory(root);plan.WritePlan(root);
            _autoTestCts=new CancellationTokenSource();
            lock(_autoPointsLock){_autoAngles.Clear();_autoEncoders.Clear();}
            _autoMotionCollecting=false;
            RealAutoRunButton.IsEnabled=false;
            ExperimentProgress.Value=0;ExperimentProgressText.Text="检查机械找零状态并执行受控预定位…";
            MainTabs.SelectedIndex=1;
            var progress=new Progress<double>(v=>{ExperimentProgress.Value=100*v;ExperimentProgressText.Text=$"真实转台测试中 · {100*v:F0}%";});
            try
            {
                await TurntablePanel.PrepareAutomaticTestAsync(innerTarget,_autoTestCts.Token);
                // Exclude mechanical homing / positioning transients from measurement
                // and encoder comparison; only record the commanded periodic motion.
                lock(_autoPointsLock){_autoAngles.Clear();_autoEncoders.Clear();}
                _autoMotionCollecting=true;
                ExperimentProgressText.Text="机械预检完成，正在记录真实摇摆…";
                await TurntablePanel.RunPhysicalSwayAsync(2,plan.AmplitudeDeg,plan.FrequencyHz,plan.Cycles,progress,_autoTestCts.Token,innerTarget,
                    ()=>_captureCts is not null && (Stopwatch.GetTimestamp()-_latestArrivalTicks)/(double)Stopwatch.Frequency<1.0);
                // Host arrival timestamp comparison, research only until latency calibration.
                var report=GenerateRealSineReport(root,plan);
                ExperimentProgress.Value=100;
                ExperimentProgressText.Text="已完成 · 100% · 转台停车反馈已确认";
                ExperimentHint.Text="真实实验研究报告："+report;
                AppendLog("真实自动摇摆完成；报告："+report);
                try {Process.Start(new ProcessStartInfo(report){UseShellExecute=true});}
                catch(Exception openEx){App.Log("OPEN AUTO REPORT FAILED",openEx);AppendLog("报告已保存但未自动打开："+openEx.Message);}
                MessageBox.Show(this,"转台运动和停车已完成，已生成研究报告：\n"+report+"\n\n注意：时标/相位延迟未标定，结果不可作为出厂精度结论。","实验完成",MessageBoxButton.OK,MessageBoxImage.Information);
            }
            finally{_autoMotionCollecting=false;_autoTestCts?.Dispose();_autoTestCts=null;RealAutoRunButton.IsEnabled=true;}
        }
        catch(OperationCanceledException){ExperimentProgressText.Text="已取消 · 已请求转台停车";AppendLog("自动实验已取消");}
        catch(Exception ex){App.Log("AUTO TEST FAILED",ex);AppendLog("自动测试中止："+ex.Message);ExperimentProgressText.Text="未完成 · 请检查转台真实停稳反馈";MessageBox.Show(this,ex.Message,"自动测试未完成",MessageBoxButton.OK,MessageBoxImage.Warning);}
    }
    private void StopAuto_Click(object sender,RoutedEventArgs e)
    {
        if(_autoTestCts is null)return;
        _autoTestCts.Cancel();AppendLog("用户请求取消自动测试；正在走受控停车流程");
    }
    private string GenerateRealSineReport(string root,SineSweepPlan plan)
    {
        (long ticks,double roll,double pitch,bool fused,bool synthetic)[] a;
        (long ticks,double inner,double outer,double velocity)[] b;
        lock(_autoPointsLock){a=_autoAngles.ToArray();b=_autoEncoders.ToArray();}
        if(a.Length<50||b.Length<20)throw new InvalidDataException("IMU 或转台实际反馈数据不足，拒绝生成有效误差报告");
        if(a.Any(x=>!x.fused||x.synthetic))throw new InvalidDataException("记录包含未融合或仿真数据，不能生成真实融合报告");
        using(var w=new StreamWriter(Path.Combine(root,"measured_host_time.csv"),false,new UTF8Encoding(false)))
        {
            w.WriteLine("host_ticks,roll_deg,pitch_deg");
            foreach(var x in a)w.WriteLine(FormattableString.Invariant($"{x.ticks},{x.roll:R},{x.pitch:R}"));
        }
        using(var w=new StreamWriter(Path.Combine(root,"encoder_host_time.csv"),false,new UTF8Encoding(false)))
        {
            w.WriteLine("host_ticks,inner_deg,outer_deg,outer_dps");
            foreach(var x in b)w.WriteLine(FormattableString.Invariant($"{x.ticks},{x.inner:R},{x.outer:R},{x.velocity:R}"));
        }
        // Compare relative angle variations, not absolute accuracy, to avoid hiding mechanical-zero uncertainties.
        double firstEncoder=b[0].outer;
        double firstRoll=a[0].roll,firstPitch=a[0].pitch;
        double sign=plan.Axis==SweepAxis.Roll?1:1; // axis sign MUST be verified with physical known-direction test
        long t0=Math.Min(a[0].ticks,b[0].ticks);
        double F(long t) => (t - t0) / (double)Stopwatch.Frequency;
        var m=a.Select(x=>new AnglePoint(F(x.ticks),
            AngleEvaluator.Wrap180(x.roll-firstRoll),
            AngleEvaluator.Wrap180(x.pitch-firstPitch))).ToArray();
        var r=b.Select(x=>new AnglePoint(F(x.ticks),
            plan.Axis==SweepAxis.Roll?sign*AngleEvaluator.Wrap180(x.outer-firstEncoder):0,
            plan.Axis==SweepAxis.Pitch?sign*AngleEvaluator.Wrap180(x.outer-firstEncoder):0)).ToArray();
        var stats=AngleEvaluator.Evaluate(m,r,0.04);
        var csv=Path.Combine(root,"relative_dynamic_comparison.csv");
        using(var w=new StreamWriter(csv,false,new UTF8Encoding(false)))
        {
            w.WriteLine("time_s,roll_measured_deg,pitch_measured_deg");
            foreach(var x in m)w.WriteLine(FormattableString.Invariant($"{x.Seconds:R},{x.RollDeg:R},{x.PitchDeg:R}"));
        }
        // Report is clearly marked as engineering-only until synchronized reference and signs are checked.
        var html=Sst810HtmlReport.Write(root,m,r,_cal!.DeviceSerial,"真实转台编码器主机轮询（相对变化，未独立校时）",plan.AmplitudeDeg,plan.FrequencyHz,false);
        File.WriteAllText(Path.Combine(root,"measurement_limitations.txt"),
            "本轮是真实转台与IMU采样，但使用两条不同主机接收链路时间戳。未校准串口延迟和相位延迟，误差仅供研发参考。\n"+
            "外轴2摇摆+内轴0/90对应Roll/Pitch的符号和零位需通过实机坐标核验。报告仅比较相对变化，不表示绝对倾角精度。\n"+
            "IMU MCU量程/ODR/Tick语义与转台实际运动波形若尚未验证，不允许标记为QC PASS。\n"+
            JsonSerializer.Serialize(stats,new JsonSerializerOptions{WriteIndented=true}),Encoding.UTF8);
        return html;
    }

    private void SaveSinePlan_Click(object sender,RoutedEventArgs e)
    {
        try
        {
            var plan=ReadSinePlan();
            ResolveReportDirectory();
            var dir=Path.Combine(_experimentRoot,"PLANS",$"SINE_{DateTime.Now:yyyyMMdd_HHmmss}");
            plan.WritePlan(dir);
            ExperimentHint.Text=$"已生成计划：{plan.Axis} · ±{plan.AmplitudeDeg:F2}° · {plan.FrequencyHz:F3}Hz · {plan.Cycles}周期 · {plan.DurationSeconds:F1}s；估算速度上界 {plan.PeakSpeedUpperBoundDps:F2}°/s；没有执行转台运动。";
            AppendLog("正弦计划已生成："+dir+"。计划轨迹不是转台实测反馈，禁止用作真实精度参考。");
            MessageBox.Show(this,"已保存参数与计划参考 CSV：\n"+dir+"\n\n注意：计划角度不是编码器实际角度，不能用于真实精度验收。","试验方案");
        }
        catch(Exception ex){AppendLog("正弦计划参数错误："+ex.Message);MessageBox.Show(this,ex.Message,"无法生成正弦计划");}
    }
    private void RunSineSimulation_Click(object sender,RoutedEventArgs e)
    {
        if(!Ready())return;
        try
        {
            var plan=ReadSinePlan();
            ResolveReportDirectory();
            if(MessageBox.Show(this,$"准备执行【纯软件自动仿真】，不驱动 2TD600。\n通道 {plan.Axis}，幅值 ±{plan.AmplitudeDeg:F2}°，频率 {plan.FrequencyHz:F3}Hz，周期 {plan.Cycles}，约 {plan.DurationSeconds:F1}s。\n\n合成结果不得视为真机测角精度。是否开始？",
                "自动仿真试验",MessageBoxButton.YesNo,MessageBoxImage.Information)!=MessageBoxResult.Yes)return;
            BeginCapture(new SimulatedSineSweepSource(plan,_cal!),"SYNTHETIC SINE / 自动仿真",plan);
        }
        catch(Exception ex){AppendLog("自动仿真启动失败："+ex.Message);MessageBox.Show(this,ex.Message,"自动试验参数错误");}
    }
    private void StaticPlan_Click(object sender,RoutedEventArgs e)
    {
        try
        {
            var plan=new StaticScanPlan(-180,180,10,3,5);
            ResolveReportDirectory();
            var dir=Path.Combine(_experimentRoot,"PLANS",$"STATIC_{DateTime.Now:yyyyMMdd_HHmmss}");
            plan.WritePlan(dir);
            AppendLog("74点静态扫描计划已生成："+dir+"。仅输出计划，不发送任何转台运动指令。");
            MessageBox.Show(this,"已导出双轴 74 点静态计划（内轴0°与90°、外轴 -180°至+180°、步进10°、静置3秒、采样5秒）：\n"+dir+"\n此处不执行实机运动。","静态计划");
        }
        catch(Exception ex){AppendLog("静态计划失败："+ex.Message);MessageBox.Show(this,ex.Message,"静态计划失败");}
    }

    private void OpenExperimentFolder_Click(object sender,RoutedEventArgs e)
    {
        try
        {
            string root=ResolveReportDirectory();
            Process.Start(new ProcessStartInfo("explorer.exe",root){UseShellExecute=true});
        }
        catch(Exception ex)
        {
            App.Log("OPEN REPORT DIR FAILED",ex);
            MessageBox.Show(this,"无法打开报告目录："+ex.Message,"报告目录");
        }
    }

    private void SelectDirectory_Click(object sender,RoutedEventArgs e)
    {
        if(!EnsureStopped())return;
        var d=new OpenFolderDialog{Title="选择实验自动保存根目录"};
        if(d.ShowDialog(this)!=true)return;
        _experimentRoot=d.FolderName;
        ReportDirectoryBox.Text=_experimentRoot;
        RecordPathText.Text="实验根目录："+_experimentRoot;
    }

    /// <summary>Start a CSV session without restarting the IMU or ESKF.</summary>
    private void StartManualRecording(SineSweepPlan? plan=null)
    {
        if(_captureCts is null || _captureCts.IsCancellationRequested)
        { MessageBox.Show(this,"请先连接 IMU，确认能够看到实时姿态，再开始采集记录。","设备未连接"); return; }
        long age=Stopwatch.GetTimestamp()-Interlocked.Read(ref _latestArrivalTicks);
        if(!_hasLatest || age/(double)Stopwatch.Frequency>1.5)
        { MessageBox.Show(this,"尚无最近1.5秒内的新鲜 IMU 样本；不能开始采集记录。","实时数据未就绪"); return; }
        try
        {
            ResolveReportDirectory();
            lock(_recordLock)
            {
                if(_liveRecorder is not null)return;
                var recorder=ExperimentRecorder.Start(_experimentRoot,_cal!.DeviceSerial,_accPath!,_gyroPath??"",_engine.Mode.ToString(),_sourceDescription);
                try { if(plan is not null)plan.WritePlan(recorder.DirectoryPath); }
                catch { recorder.Dispose(); throw; }
                _liveRecorder=recorder;
                _runDir=recorder.DirectoryPath;
                _recordStartTicks=Stopwatch.GetTimestamp();
                Interlocked.Exchange(ref _recordedCount,0);
            }
            RecordPathText.Text="当前正在记录："+_runDir;
            AppendLog("开始采集记录（连接和姿态监测不会中断）："+_runDir);
            StatusLabel.Text="在线监测 · 正在保存采集数据";
        }
        catch(Exception ex)
        {
            App.Log("START RECORDING FAILED",ex);
            AppendLog("创建采集记录失败："+ex.Message);
            MessageBox.Show(this,ex.Message,"无法开始采集记录",MessageBoxButton.OK,MessageBoxImage.Warning);
        }
    }

    /// <summary>Close CSV safely; retain the live device stream and ESKF state.</summary>
    private void FinishManualRecording(string reason)
    {
        string? dir=null;long saved=0;Exception? error=null;
        lock(_recordLock)
        {
            if(_liveRecorder is null)return;
            var recorder=_liveRecorder;
            _liveRecorder=null;
            dir=recorder.DirectoryPath;
            saved=recorder.Count;
            try { recorder.Dispose(); } catch(Exception ex) { error=ex; }
            _runDir=null; // Prevent turntable feedback from continuing to write this closed session.
        }
        lock(_tableWriterLock)
        {
            try { _turnWriter?.Flush();_turnWriter?.Dispose(); }
            catch(Exception ex){error??=ex;}
            _turnWriter=null;
        }
        RecordPathText.Text="上次记录："+dir;
        AppendLog($"{reason}；记录样本 {saved:N0}；文件夹：{dir}");
        if(error is not null)
        {
            App.Log("RECORDING CLOSE FAILED",error);
            AppendLog("记录文件关闭失败："+error.Message);
            MessageBox.Show(this,"关闭文件时出现错误，请确认 CSV 是否完整："+error.Message,"记录保存警告");
        }
        else StatusLabel.Text="在线监测 · 未记录（可随时重新开始采集）";
    }

    private void BeginCapture(IImuSource source,string sourceDescription,SineSweepPlan? plan=null)
    {
        if(_cal==null||_accPath==null)return;
        InvalidateRelativeZero("新采集会话开始；不会沿用旧设备/旧时标的零点");
        _lastError="";
        _visibleSinePlan=plan;
        ExperimentProgress.Value=0;
        ExperimentProgressText.Text=plan is null?"在线监测进行中（尚未开始采集记录）":"软件演示进行中：0%（非真实转台）";
        _captureCts=new CancellationTokenSource();
        // Clear stale readings on each connection; monitoring starts independently of file recording.
        RollText.Text="--.---°";PitchText.Text="--.---°";YawText.Text="无有效数据";
        QualityText.Text="连接中 · 尚未收到任何有效样本";
        LiveSampleText.Text="等待真实设备采样或仿真数据…";
        ModeText.Text="尚未获得当前采集会话的有效姿态";
        _rotation.Quaternion=System.Windows.Media.Media3D.Quaternion.Identity;
        _lastSampleUiUpdateTicks=Stopwatch.GetTimestamp();
        _startCaptureTicks=_lastSampleUiUpdateTicks;
        FusedDataNotice.Text="等待实时数据 · 启动后将分别显示 ACC 倾角与实际融合输出";
        AppendLog("开始在线监测（不自动创建 CSV）："+sourceDescription+" · 算法="+_engine.Mode);
        var ct=_captureCts.Token;_sourceDescription=sourceDescription;
        Interlocked.Exchange(ref _received,0);Interlocked.Exchange(ref _processed,0);Interlocked.Exchange(ref _lost,0);
        lock(_stateLock){_engine.Reset();_engine.AllowResearchFusionWithUnverifiedConfiguration=ResearchOverride.IsChecked==true;_roll.Clear();_pitch.Clear();_hasLatest=false;}
        // Normal connection performs continuous live monitoring but does NOT create CSV.
        // The hidden legacy synthetic-plan path may still request a recorded run.
        StatusLabel.Text="在线监测："+sourceDescription+" · 尚未开始采集记录";
        _runDir=null;
        _rateWindowTick=Stopwatch.GetTimestamp();
        _rateWindowCount=0;
        _observedProcessingHz=0;
        Interlocked.Exchange(ref _recordedCount,0);
        _captureTask=RunPipeline(source,ct,plan);
        if(plan is not null) StartManualRecording(plan);
    }
    private async Task RunPipeline(IImuSource source,CancellationToken ct,SineSweepPlan? plan)
    {
        try
        {
            var channel=Channel.CreateBounded<ImuSample>(new BoundedChannelOptions(16_384){SingleReader=true,SingleWriter=true,FullMode=BoundedChannelFullMode.Wait});
            var processing=Task.Run(async()=>
            {
                await foreach(var sample in channel.Reader.ReadAllAsync())
                {
                    AttitudeState state;
                    AttitudeState? displayedState;
                    System.Numerics.Quaternion? recordedReference;
                    string displayMode;
                    lock(_stateLock)
                    {
                        if(_rawOutputRequested)
                        {
                            var (r,p)=TiltMath.FromAcceleration(sample.AccG);
                            var q=TiltMath.FromTilt(r,p);
                            state=new AttitudeState(q,r,p,0,false,"原始加速度倾角 · 未应用校准与融合");
                        }
                        else state=_engine.Update(sample,_cal!);
                        string quality = state.Quality;
                        if(sample.Synthetic)quality+=" · SYNTHETIC";
                        else if(!sample.ScaleVerified || !sample.TimingVerified)quality+=" · 配置/时标未核实";
                        state=state with {Quality=quality};
                        var calibratedAcceleration=_rawOutputRequested ? sample.AccG : _cal!.CorrectAcc(sample.AccG);
                        (_latestAccRoll,_latestAccPitch)=TiltMath.FromAcceleration(calibratedAcceleration);
                        _latestState=state;_latestSample=sample;_hasLatest=true;
                        if(_autoMotionCollecting && _autoTestCts is not null)
                        {
                            lock(_autoPointsLock) _autoAngles.Add((sample.HostArrivalTicks,state.RollDeg,state.PitchDeg,state.IsSixAxis,sample.Synthetic));
                        }
                        _latestArrivalTicks=Stopwatch.GetTimestamp();
                        displayMode=_displayReference == TiltDisplayReference.Abs ? "ABS" : "REL";
                        recordedReference=_displayReference == TiltDisplayReference.Rel ? _relativeZero : null;
                        displayedState=_displayReference == TiltDisplayReference.Abs ? state :
                            _relativeZero.HasValue && state.IsSixAxis ? TiltReferenceMath.RelativeTo(state,_relativeZero.Value) : null;
                        long count=Interlocked.Increment(ref _processed);
                        if(count%8==0)
                        {
                            AttitudeState? plotState = _displayReference == TiltDisplayReference.Abs
                                ? state : _relativeZero.HasValue && state.IsSixAxis
                                    ? TiltReferenceMath.RelativeTo(state, _relativeZero.Value) : null;
                            if(plotState.HasValue)
                            {
                                _roll.Add(plotState.Value.RollDeg);_pitch.Add(plotState.Value.PitchDeg);
                                if(_roll.Count>250){_roll.RemoveAt(0);_pitch.RemoveAt(0);}
                            }
                        }
                    }
                    // Snapshot both CSVs atomically under the record lock. No writer exists during monitoring.
                    try
                    {
                        lock(_recordLock)
                        {
                            if(_liveRecorder is not null)
                            {
                                _liveRecorder.Append(sample,state,_rawOutputRequested ? "RawUncalibratedAcc" : _engine.Mode.ToString());
                                _liveRecorder.AppendDisplayed(sample,state,displayedState,displayMode,recordedReference);
                                Interlocked.Increment(ref _recordedCount);
                            }
                        }
                    }
                    catch(Exception ex)
                    {
                        // A disk failure must be visible; do not keep a misleading "recording" state.
                        await Dispatcher.InvokeAsync(()=>
                        {
                            App.Log("RECORDING WRITE FAILED",ex);
                            FinishManualRecording("存储异常，已停止记录");
                            AppendLog("采集记录写入失败："+ex.Message+"；实时监测仍运行");
                        });
                    }
                }
            });
            try
            {
                await Task.Run(async()=>await source.RunAsync(sample=>
                {
                    Interlocked.Increment(ref _received);
                    if(!channel.Writer.TryWrite(sample))
                    {
                        Interlocked.Increment(ref _lost);
                        _captureCts?.Cancel();
                        throw new IOException("采集队列溢出；已终止试验避免静默丢失原始数据");
                    }
                },message=>Dispatcher.BeginInvoke(new Action(()=>{StatusLabel.Text=message;AppendLog(message);})),ct));
            }
            catch(OperationCanceledException){ }
            catch(Exception ex)
            {
                _lastError=ex.ToString();App.Log("ACQUISITION FAILED",ex);
                await Dispatcher.InvokeAsync(()=>{StatusLabel.Text="采集故障："+ex.Message;AppendLog(StatusLabel.Text);});
            }
            finally {channel.Writer.TryComplete();}
            try { await processing; }
            catch(Exception ex){_lastError=ex.ToString();App.Log("PROCESSING/RECORDING FAILED",ex);await Dispatcher.InvokeAsync(()=>{StatusLabel.Text="数据处理/存储故障："+ex.Message;AppendLog(StatusLabel.Text);});}
        if(plan is not null && !ct.IsCancellationRequested && string.IsNullOrEmpty(_lastError) && _runDir is not null)
        {
            try
            {
                var measured=ReadAngles(Path.Combine(_runDir,"raw_processed.csv"),true);
                var ideal=ReadAngles(Path.Combine(_runDir,"reference_planned_NOT_ENCODER.csv"),false);
                var stats=AngleEvaluator.Evaluate(measured,ideal,Math.Max(.03,2.0/plan.SampleHz));
                var file=Path.Combine(_runDir,"synthetic_only_metrics.json");
                File.WriteAllText(file,JsonSerializer.Serialize(new{plan,stats,synthetic_only=true,
                   statement="这只是算法管线模拟验证，不是设备动态精度；理想计划曲线不是转台实际反馈。"},
                   new JsonSerializerOptions{WriteIndented=true}),Encoding.UTF8);
                await Dispatcher.InvokeAsync(()=>{AppendLog($"自动仿真完成：{stats.Count}点，Roll RMSE={stats.RollRmseDeg:F3}°，Pitch RMSE={stats.PitchRmseDeg:F3}°（仅合成数据）");
                    ExperimentHint.Text="仿真报告："+file+"；禁止作为实机性能结论。";});
            }
            catch(Exception ex){App.Log("SYNTHETIC METRICS FAILED",ex);await Dispatcher.InvokeAsync(()=>AppendLog("自动仿真评价失败："+ex.Message));}
        }
        }
        catch (Exception ex)
        {
            _lastError = ex.ToString();
            App.Log("PIPELINE FATAL OR RECORDER CLOSE FAILED", ex);
            if (!Dispatcher.HasShutdownStarted)
                await Dispatcher.InvokeAsync(() => StatusLabel.Text = "采集/存储异常：" + ex.Message);
        }
        finally
        {
            if (!Dispatcher.HasShutdownStarted)
                await Dispatcher.InvokeAsync(()=>FinishManualRecording("连接断开，采集记录自动收尾"));
            lock (_tableWriterLock)
            {
                try { _turnWriter?.Flush(); _turnWriter?.Dispose(); }
                catch (Exception ex) { App.Log("TURNTABLE WRITER CLOSE FAILED", ex); }
                _turnWriter = null;
            }
            if (!Dispatcher.HasShutdownStarted)
                await Dispatcher.InvokeAsync(() =>
                {
                    _captureCts?.Dispose();
                    _captureCts = null;
                    _captureTask = null;
                    StatusLabel.Text += " · 设备已断开";
                    if(plan is not null && string.IsNullOrEmpty(_lastError) && !ct.IsCancellationRequested)
                    {
                        ExperimentProgress.Value=100;
                        ExperimentProgressText.Text="软件仿真已完成 100% · 非真实转台测试";
                    }
                    QualityText.Text = "设备已断开 · 不再提供实时测量";
                    AppendLog($"设备数据流结束。处理样本={Interlocked.Read(ref _processed)}；日志路径：{App.DiagnosticsPath}");
                });
        }
    }
    private async Task StopCaptureAsync()
    {
        var ct=_captureCts;var task=_captureTask;
        if(ct!=null)AppendLog("请求断开 IMU 数据连接；如正在记录将先保存 CSV；不控制机械转台运动");
        ct?.Cancel();
        if(task!=null)
        {
            try{await task;}catch(Exception ex){StatusLabel.Text="停止异常："+ex.Message;}
        }
    }
    private void Stop_Click(object sender,RoutedEventArgs e)
    {
        if(_autoTestCts is not null){AppendLog("自动运动期间禁止切换记录按钮");return;}
        if(_captureCts is null || _captureCts.IsCancellationRequested || _disconnecting)return;
        bool recording;
        lock(_recordLock)recording=_liveRecorder is not null;
        if(recording)FinishManualRecording("用户停止采集记录，IMU 继续实时监测");
        else StartManualRecording();
    }

    private void OpenTurntableConsole_Click(object sender,RoutedEventArgs e) => MainTabs.SelectedIndex=1;
    // The turntable lives in the third TAB rather than a modal window. Keeping the event
    // wiring at the application boundary preserves capture provenance and timestamp logs.
    private void OnTableFeedbackArrived(TurntableReadback fb)
    {
        if(_autoMotionCollecting && _autoTestCts is not null)
        {
            lock(_autoPointsLock) _autoEncoders.Add((fb.HostMonotonicTicks,fb.Inner.Position360Deg,fb.Outer.Position360Deg,fb.Outer.RateDps));
        }
        TurntableText.Text=$"实时转台反馈 · 内轴0：{fb.Inner.Position360Deg:F3}° / {fb.Inner.RateDps:F3}°/s · 外轴2：{fb.Outer.Position360Deg:F3}° / {fb.Outer.RateDps:F3}°/s";
        QuickInnerAngleText.Text=$"{fb.Inner.Position360Deg:F3}°";
        QuickOuterAngleText.Text=$"{fb.Outer.Position360Deg:F3}°";
        QuickTableConnectionText.Text=fb.Inner.Normal && fb.Outer.Normal && fb.Inner.Enabled && fb.Outer.Enabled
            ? "双轴就绪" : "已连接 · 请核对状态";
        try
        {
            lock(_tableWriterLock)
            {
                if(_runDir is null || _captureCts is null || _liveRecorder is null)return;
                _turnWriter??=NewTurnWriter(_runDir);
                var c=CultureInfo.InvariantCulture;
                _turnWriter.WriteLine(string.Join(",",new[]{fb.HostMonotonicTicks.ToString(c),fb.HostElapsedSeconds.ToString("R",c),fb.Inner.Position360Deg.ToString("R",c),fb.Outer.Position360Deg.ToString("R",c),fb.Inner.RateDps.ToString("R",c),fb.Outer.RateDps.ToString("R",c),fb.Inner.Enabled.ToString(),fb.Outer.Enabled.ToString(),fb.Inner.Normal.ToString(),fb.Outer.Normal.ToString()}));
                _turnWriter.Flush();
            }
        }
        catch(Exception ex){App.Log("TURNTABLE FEEDBACK SAVE FAILED",ex);AppendLog("转台反馈保存失败："+ex.Message);}
    }

    // Two product-facing output modes: raw uncalibrated gravity tilt and corrected 6-axis ESKF.

private void RefreshReferenceControls()
{
    AbsoluteAngleButton.FontWeight = _displayReference == TiltDisplayReference.Abs ? FontWeights.Bold : FontWeights.Normal;
    RelativeAngleButton.FontWeight = _displayReference == TiltDisplayReference.Rel ? FontWeights.Bold : FontWeights.Normal;
    ReferenceModeText.Text = _displayReference == TiltDisplayReference.Abs
        ? "当前 ABS：以重力水平面为参考的融合倾角；REL " + (_relativeZero.HasValue ? "已设置（可切换）" : "未设零点")
        : _relativeZero.HasValue
            ? "当前 REL：以手动捕获的姿态为零点 · " + _relativeZeroDescription
            : "当前 REL：尚未设置相对零点；点击「设置当前姿态为相对零点」后才会显示角度";
}

private void AbsoluteAngle_Click(object sender, RoutedEventArgs e) => SelectAngleReference(TiltDisplayReference.Abs);
private void RelativeAngle_Click(object sender, RoutedEventArgs e) => SelectAngleReference(TiltDisplayReference.Rel);

private void SelectAngleReference(TiltDisplayReference next)
{
    lock (_stateLock)
    {
        if (_displayReference == next) return;
        _displayReference = next;
        _roll.Clear(); _pitch.Clear(); // never combine ABS and REL points in one plotted trace
    }
    RefreshReferenceControls();
    AppendLog(next == TiltDisplayReference.Abs ? "实时显示切换：ABS 重力参考绝对倾角" :
        "实时显示切换：REL 手动参考倾角（不改变算法与原始记录）");
    if(next == TiltDisplayReference.Rel && !_relativeZero.HasValue)
        AppendLog("REL 零点尚未设置，不会自动使用开机姿态代替用户零点");
    UpdateDisplay();
}

private void SetRelativeZero_Click(object sender, RoutedEventArgs e)
{
    if (_autoTestCts is not null)
    { MessageBox.Show(this, "自动测试期间不能修改显示参考零点，请先停车并结束实验。", "相对零点锁定"); return; }
    string? error = null;
    lock (_stateLock)
    {
        double age = (Stopwatch.GetTimestamp() - _latestArrivalTicks) / (double)Stopwatch.Frequency;
        if (_captureCts is null || !_hasLatest || age > 1.0)
            error = "当前没有 1 秒内的新鲜姿态数据，请先连接 IMU 并保持采集。";
        else if (_rawOutputRequested || !_latestState.IsSixAxis || !TiltReferenceMath.IsValid(_latestState.Quaternion))
            error = "当前不是有效的六轴融合姿态，请先载入 ACC/GYRO 标定并启用 ESKF。";
        else
        {
            _relativeZero = System.Numerics.Quaternion.Normalize(_latestState.Quaternion);
            _relativeZeroDescription = $"设备 {_cal?.DeviceSerial}，{DateTime.Now:HH:mm:ss} 捕获；" +
                (_latestSample.Synthetic ? "仿真样本" : "真实 IMU 样本") +
                ($" · ABS Roll={_latestState.RollDeg:+0.000;-0.000;0.000}° Pitch={_latestState.PitchDeg:+0.000;-0.000;0.000}°");
            _displayReference = TiltDisplayReference.Rel;
            _roll.Clear(); _pitch.Clear();
        }
    }
    if(error is not null)
    { MessageBox.Show(this, error, "无法设置相对零点", MessageBoxButton.OK, MessageBoxImage.Information); return; }
    RefreshReferenceControls();
    AppendLog("用户手动设定 REL 参考零点；" + _relativeZeroDescription + "；原始 ABS 记录及自动测试误差计算保持不变");
    UpdateDisplay();
}

private void ClearRelativeZero_Click(object sender, RoutedEventArgs e)
{
    if (_autoTestCts is not null)
    { MessageBox.Show(this, "自动测试期间不能修改零点。", "零点锁定"); return; }
    InvalidateRelativeZero("用户清除相对零点");
    UpdateDisplay();
}

private void InvalidateRelativeZero(string reason)
{
    lock(_stateLock)
    {
        _relativeZero = null;
        _relativeZeroDescription = "";
        _displayReference = TiltDisplayReference.Abs;
        _roll.Clear(); _pitch.Clear();
    }
    RefreshReferenceControls();
    AppendLog("REL 参考零点失效，切回 ABS：" + reason);
}

    private void RawOutput_Click(object sender,RoutedEventArgs e)
    {
        if(_autoTestCts is not null){MessageBox.Show(this,"自动运动期间不能修改姿态解算方式，请先停止测试并确认转台已停稳。");return;}
        lock(_stateLock){_rawOutputRequested=true;_engine.Mode=ProcessingMode.AccelerometerOnly;_engine.Reset();}
        InvalidateRelativeZero("切换至未校准原始 ACC 对照");
        OutputStatusText.Text="原始未校准模式 · 仅使用直接换算的加速度；不代表产品精度";
        ModeText.Text="原始 ACC · 无校准矩阵、无姿态融合";
        AppendLog("用户选择原始未校准 ACC 对照模式");
    }
    private void FusedOutput_Click(object sender,RoutedEventArgs e)
    {
        if(_autoTestCts is not null){MessageBox.Show(this,"自动运动期间不能重置姿态融合，请先停止测试。");return;}
        if(_cal?.HasGyro!=true)
        {
            MessageBox.Show(this,"请先导入与设备编号一致的 ACC 和 GYRO 两份校准文件。", "六轴融合尚不可用",MessageBoxButton.OK,MessageBoxImage.Information);
            return;
        }
        if(_captureCts is not null && _sourceDescription.StartsWith("REAL",StringComparison.Ordinal) && _activeCaptureTimingPolicy==TimingPolicy.UnresolvedBatch)
        {
            MessageBox.Show(this,"当前采集连接是在『时标未确认』模式下建立的，因此没有有效逐样本时间。\n请先停止采集，在高级参数里选择经过确认的时标策略，或明确启用研究级假设，然后重新连接。","无法在当前数据流中融合",MessageBoxButton.OK,MessageBoxImage.Warning);
            return;
        }
        if(TimingChoice.SelectedIndex==0)
        {
            if(MessageBox.Show(this,
                "当前 MCU 的实际 ODR 和 16 组采样的 Tick 语义尚未得到确认。\n\n"+
                "可以暂以 Tick=最后样本、候选 ODR=200 Hz 进行研究级 ESKF 融合，但不允许将结果作为动态精度验收。\n\n是否启用这一明确标识的研究模式？",
                "融合时间基尚未核实",MessageBoxButton.YesNo,MessageBoxImage.Warning)!=MessageBoxResult.Yes)return;
            TimingChoice.SelectedIndex=1;
            ResearchOverride.IsChecked=true;
        }
        lock(_stateLock){_rawOutputRequested=false;_engine.Mode=ProcessingMode.Eskf;_engine.Reset();_engine.AllowResearchFusionWithUnverifiedConfiguration=ResearchOverride.IsChecked==true;}
        InvalidateRelativeZero("重新启用 ESKF 姿态融合");
        OutputStatusText.Text=TimingChoice.SelectedIndex==1 ? "ESKF 已选择 · 研究级时间假设，禁止精度验收" : "ESKF 已选择 · 等待真实六轴采样";
        ModeText.Text=OutputStatusText.Text;
        AppendLog("用户选择校准 + ESKF 输出；配置和时基状态以样本质量标志为准");
    }

    private static StreamWriter NewTurnWriter(string dir)
    {
        var w=new StreamWriter(new FileStream(Path.Combine(dir,"turntable_readback.csv"),FileMode.Create,FileAccess.Write,FileShare.Read));
        w.WriteLine("host_monotonic_ticks,table_elapsed_s,inner_deg_360,outer_deg_360,inner_dps,outer_dps,inner_enabled,outer_enabled,inner_normal,outer_normal");return w;
    }

    private void StaticEvaluate_Click(object sender,RoutedEventArgs e)
    {
        if(!EnsureStopped())return;
        var c=CultureInfo.InvariantCulture;
        if(!double.TryParse(StaticRollRef.Text,NumberStyles.Float,c,out var rr)||!double.TryParse(StaticPitchRef.Text,NumberStyles.Float,c,out var rp))
        {MessageBox.Show(this,"请输入有效的静态参考角度（使用小数点）");return;}
        var d=new OpenFileDialog{Title="选择静态记录 raw_processed.csv，分析最后 5 秒",Filter="CSV|*.csv"};
        if(d.ShowDialog(this)!=true)return;
        try
        {
            var points=ReadAngles(d.FileName,true);
            var stats=StaticWindowEvaluator.EvaluateLastSeconds(points,rr,rp);
            var outPath=Path.Combine(Path.GetDirectoryName(d.FileName)!,"static_last5s_metrics.json");
            File.WriteAllText(outPath,JsonSerializer.Serialize(new{reference_roll=rr,reference_pitch=rp,stats,note="手动输入的参考角需独立校验。此评价不是计量合格证。"},new JsonSerializerOptions{WriteIndented=true}),Encoding.UTF8);
            MessageBox.Show(this,$"最后 {stats.DurationSeconds:F2} 秒 / {stats.Samples} 样本\nRoll RMSE {stats.Errors.RollRmseDeg:F4}°  Max {stats.Errors.RollMaxAbsDeg:F4}°  σ {stats.RollStdDeg:F4}°\nPitch RMSE {stats.Errors.PitchRmseDeg:F4}°  Max {stats.Errors.PitchMaxAbsDeg:F4}°  σ {stats.PitchStdDeg:F4}°\n\n报告：{outPath}","静态单点精度结果");
        }
        catch(Exception ex){MessageBox.Show(this,ex.Message,"静态试验数据不足或格式错误");}
    }
    private void Evaluate_Click(object sender,RoutedEventArgs e)
    {
        if(!EnsureStopped())return;
        var d1=new OpenFileDialog{Title="选择本程序记录的 raw_processed.csv",Filter="CSV|*.csv"};
        if(d1.ShowDialog(this)!=true)return;
        var d2=new OpenFileDialog{Title="选择已经同步的参考角度 CSV (time_s,roll_deg,pitch_deg)",Filter="CSV|*.csv"};
        if(d2.ShowDialog(this)!=true)return;
        try
        {
            var measured=ReadAngles(d1.FileName,true);
            var reference=ReadAngles(d2.FileName,false);
            var stats=AngleEvaluator.Evaluate(measured,reference);
            string outFile=ExperimentReport.WriteMetrics(Path.GetDirectoryName(d1.FileName)!,stats,"参考文件必须与 IMU 使用同一时间基准、坐标系并完成延迟标定；未自动推断同步关系。特别注意 2TD600 0/2 轴角与 Roll/Pitch 的几何转换。");
            string htmlReport="";
            string firstRaw=File.ReadLines(d1.FileName).Skip(1).FirstOrDefault()??"";
            bool syntheticFirst=firstRaw.Split(',').Length>9 && firstRaw.Split(',')[9].Equals("True",StringComparison.OrdinalIgnoreCase);
            bool idealReference=Path.GetFileName(d2.FileName).Contains("NOT_ENCODER",StringComparison.OrdinalIgnoreCase)
                 ||Path.GetFileName(d2.FileName).Contains("PLANNED",StringComparison.OrdinalIgnoreCase);
            if(!syntheticFirst && !idealReference)
            {
                try
                {
                    var c=CultureInfo.InvariantCulture;
                    double.TryParse(SineAmplitude.Text,NumberStyles.Float,c,out var amplitude);
                    double.TryParse(SineFrequency.Text,NumberStyles.Float,c,out var frequency);
                    htmlReport=Sst810HtmlReport.Write(Path.GetDirectoryName(d1.FileName)!,measured,reference,SerialId.Text.Trim(),d2.FileName,amplitude,frequency,false);
                    AppendLog("已生成研究用图形报告（未校验同步/计量）："+htmlReport);
                }
                catch(Exception reportException){AppendLog("HTML 报告未生成："+reportException.Message);}
            }
            else AppendLog("拒绝从仿真或计划参考产生真实测量报告；保留 JSON 比较结果供内部研发诊断");
            MessageBox.Show(this,$"匹配点数 {stats.Count}\nRoll RMSE = {stats.RollRmseDeg:F4}°  Max = {stats.RollMaxAbsDeg:F4}°\nPitch RMSE = {stats.PitchRmseDeg:F4}°  Max = {stats.PitchMaxAbsDeg:F4}°\n\n仅当参考坐标和时间已经独立同步时，以上指标才可视为测角误差。\n报告：{outFile}","角度误差分析（HTML为研究用、非QC报告）",MessageBoxButton.OK,MessageBoxImage.Information);
        }
        catch(Exception ex){MessageBox.Show(this,ex.Message,"无法计算有效的动态误差");}
    }
    private static List<AnglePoint> ReadAngles(string path,bool measured)
    {
        using var sr=new StreamReader(path);
        string? head=sr.ReadLine();
        var expected=measured?"seq,time_s,":"time_s,roll_deg,pitch_deg";
        if(head==null||!head.StartsWith(expected,StringComparison.OrdinalIgnoreCase))throw new InvalidDataException($"CSV 格式错误：期望以 {expected} 开头");
        var lines=new List<AnglePoint>();string? line;var c=CultureInfo.InvariantCulture;
        while((line=sr.ReadLine())!=null)
        {
            if(string.IsNullOrWhiteSpace(line))continue;
            var s=line.Split(',');
            if(measured)
            {
                if(s.Length<15)throw new InvalidDataException("测量 CSV 缺少姿态列");
                lines.Add(new(double.Parse(s[1],c),double.Parse(s[12],c),double.Parse(s[13],c)));
            }
            else
            {
                if(s.Length<3)throw new InvalidDataException("参考 CSV 至少包含 time_s,roll_deg,pitch_deg");
                lines.Add(new(double.Parse(s[0],c),double.Parse(s[1],c),double.Parse(s[2],c)));
            }
        }
        return lines;
    }

    private void UpdateDisplay()
    {
        UpdateAcquisitionReadouts();
        if(_cal==null)
        {
            RollText.Text="--.---°";PitchText.Text="--.---°";YawText.Text="不可观测";
            PlotCaptionText.Text="等待设备连接与有效数据 · 无模拟角度";
            return;
        }
        ImuSample s;AttitudeState a;bool has;List<double> roll,pitch;double accR,accP;long lastArrival;
        TiltDisplayReference referenceMode;System.Numerics.Quaternion? relativeZero;
        lock(_stateLock){has=_hasLatest;s=_latestSample;a=_latestState;roll=_roll.ToList();pitch=_pitch.ToList();accR=_latestAccRoll;accP=_latestAccPitch;lastArrival=_latestArrivalTicks;
            referenceMode=_displayReference;relativeZero=_relativeZero;}
        if(!has)
        {
            AccComparisonText.Text="ACC：--.---° / --.---°";
            if(_captureCts!=null && _sourceDescription.StartsWith("REAL",StringComparison.Ordinal))
                QualityText.Text="等待真实 IMU 有效数据；如有超时请展开运行日志";
            DataFreshnessText.Text="没有本次会话的有效采样，不能显示实时姿态";
            return;
        }
        // A REL display requires an explicit, current-session zero reference; never silently use startup attitude.
        bool relativeReady=referenceMode==TiltDisplayReference.Rel && relativeZero.HasValue && a.IsSixAxis;
        bool displayReady=referenceMode==TiltDisplayReference.Abs || relativeReady;
        AttitudeState shown=relativeReady ? TiltReferenceMath.RelativeTo(a,relativeZero!.Value) : a;
        // Product rule: never present stale or stopped values as live measurement digits.
        // Recorded values remain accessible in CSV; live UI blanks after 1.5 s without fresh data.
        var ageAtGauge=(Stopwatch.GetTimestamp()-lastArrival)/(double)Stopwatch.Frequency;
        bool gaugeLive=displayReady && _captureCts is not null && ageAtGauge<=1.5 &&
            double.IsFinite(shown.RollDeg) && double.IsFinite(shown.PitchDeg);
        RollText.Text=gaugeLive?$"{shown.RollDeg:+0.000;-0.000;0.000}°":"--.---°";
        PitchText.Text=gaugeLive?$"{shown.PitchDeg:+0.000;-0.000;0.000}°":"--.---°";
        YawText.Text=gaugeLive && shown.IsSixAxis?$"{shown.YawRelativeDeg:+0.00;-0.00;0.00}°":"不可观测";
        AccComparisonText.Text=$"ACC {accR:+0.000;-0.000;0.000}° / {accP:+0.000;-0.000;0.000}°";
        FusedDataNotice.Text=referenceMode==TiltDisplayReference.Rel
            ? (relativeReady ? "REL · 数字/曲线/3D 为相对参考姿态，算法保持原 ESKF 输出" : "REL · 等待用户设置参考零点（显示已锁定）")
            : (a.IsSixAxis ? "ABS · 六轴重力参考融合输出（"+_engine.Mode+"）" : (_rawOutputRequested ? "ABS · 未校准原始 ACC 对照" : "ABS · 校准 ACC 倾角，融合未启用"));
        ModeText.Text=a.Quality;
        var ageSeconds=(Stopwatch.GetTimestamp()-lastArrival)/(double)Stopwatch.Frequency;
        QualityText.Text=_captureCts is null ? "未连接 · 最后显示非实时数据" :
            (ageSeconds>1.5? $"无新样本 {ageSeconds:F1} 秒 · 非实时！" :
            s.Synthetic?"SYNTHETIC / 仿真数据" : !a.IsSixAxis?"真实 IMU · ACC 未融合" :
            (!s.TimingVerified||!s.ScaleVerified?"实时 ESKF 研究模式 · 配置未核实":"实时六轴融合 · 硬件参数已标记验证"));
        DataFreshnessText.Text=QualityText.Text;
        OutputStatusText.Text=_captureCts is null ? "未连接 · 无实时输出" : (s.Synthetic ? "仿真数据 · 不代表真实产品" :
            ageSeconds>1.5 ? "数据过期 · 当前不是实时姿态" : a.IsSixAxis ? "真实六轴 ESKF/Mahony 输出 · "+(s.TimingVerified&&s.ScaleVerified?"配置已标记核实":"研究级配置待核实") :
            _rawOutputRequested?"原始未校准 ACC（没有滤波）":"校准 ACC 倾角（融合未生效）");
        if(_visibleSinePlan is not null && _captureCts is not null)
        {
            double fraction=Math.Clamp(s.TimeSeconds / Math.Max(.01,_visibleSinePlan.DurationSeconds),0,1);
            ExperimentProgress.Value=100*fraction;
            ExperimentProgressText.Text=$"纯软件模拟：{100*fraction:F0}% · 非真实转台运动";
        }
        var visualQ=gaugeLive ? shown.Quaternion : System.Numerics.Quaternion.Identity;
        _rotation.Quaternion=new System.Windows.Media.Media3D.Quaternion(visualQ.X,visualQ.Y,visualQ.Z,visualQ.W);
        // Product output: the measurement panel must use the SAME ACC/GYRO calibration
        // profile as the attitude estimator, not display uncorrected register values.
        var displayAcc=_rawOutputRequested ? s.AccG : _cal.CorrectAcc(s.AccG);
        var displayGyro=_rawOutputRequested ? s.GyroDps : _cal.CorrectGyro(s.GyroDps);
        var displayTag=_rawOutputRequested ? "原始对照（无标定）" : "设备标定后（成品测量）";
        LiveSampleText.Text=$"{displayTag}\nACC [g]  {displayAcc.X:F4} / {displayAcc.Y:F4} / {displayAcc.Z:F4}\nGYRO [°/s]  {displayGyro.X:F3} / {displayGyro.Y:F3} / {displayGyro.Z:F3}\nIMU T: {s.TemperatureC:F2}℃  ·  t={s.TimeSeconds:F3} s";
        var elapsed=Math.Max(.1,(Stopwatch.GetTimestamp()-_startCaptureTicks)/(double)Stopwatch.Frequency);
        FilterDiagnostic.Text=$"模式：{(_rawOutputRequested?"RawUncalibrated":_engine.Mode.ToString())} / 实际融合：{(a.IsSixAxis?"YES":"NO")} / 输出样本率约 {Interlocked.Read(ref _processed)/elapsed:F1} 样本/s（非标称 ODR）\n"+
           (a.IsSixAxis && _engine.Mode==ProcessingMode.Eskf ?
             $"ESKF 协方差 σ≈{_engine.Eskf.RollSigmaDeg:F3}°/{_engine.Eskf.PitchSigmaDeg:F3}°；重力更新 {(_engine.Eskf.LastGravityUpdateAccepted?"接受":"拒绝")}；NIS={_engine.Eskf.LastNis:F2}（σ非实测精度）" :
             "融合诊断："+a.Quality);
        FooterText.Text=$"输入 {Interlocked.Read(ref _received)} · 处理 {Interlocked.Read(ref _processed)} · 丢失 {Interlocked.Read(ref _lost)} · 设备 {_cal.DeviceSerial} · {_sourceDescription} · 质量 {a.Quality}";
        PlotCaptionText.Text=gaugeLive ? "最近 250 个趋势点 · 当前显示参考："+(referenceMode==TiltDisplayReference.Abs?"ABS":"REL")
            : "没有新鲜实时数据 · 曲线只显示历史趋势";
        if(!_plotPaused)RenderPlot(roll,pitch);
    }
    private void PlotSizeChanged(object sender,SizeChangedEventArgs e)
    {
        lock(_stateLock)RenderPlot(_roll.ToList(),_pitch.ToList());
    }
    private void RenderPlot(List<double> roll,List<double> pitch)
    {
        var w=PlotCanvas.ActualWidth;var h=PlotCanvas.ActualHeight;if(w<2||h<2)return;
        static PointCollection Points(List<double> vals,double w,double h)
        {
            var pts=new PointCollection();for(int i=0;i<vals.Count;i++)pts.Add(new System.Windows.Point(i*w/Math.Max(1,vals.Count-1),h/2-Math.Clamp(vals[i],-45,45)*h/100));return pts;
        }
        RollLine.Points=Points(roll,w,h);PitchLine.Points=Points(pitch,w,h);
    }
    private async void OnClosing(object? sender, System.ComponentModel.CancelEventArgs e)
    {
        if (_autoTestCts is not null)
        { e.Cancel=true;MessageBox.Show(this,"自动运动正在运行，请先点击【停止自动测试】，确认实体转台停稳并安全断开。","运动中禁止退出");return; }
        if (TurntablePanel is { SafeToClose:false })
        {
            e.Cancel=true;
            MainTabs.SelectedIndex=1;
            MessageBox.Show(this,"转台当前仍有打开的硬件会话，请在转台控制页执行软件停车、确认双轴停稳、解除使能及安全断开。\n软件窗口不能替代实体急停。", "转台会话尚未安全关闭",MessageBoxButton.OK,MessageBoxImage.Warning);
            return;
        }
        if (_allowFinalClose)
        {
            _uiTimer.Stop();
            App.Log("MAIN WINDOW CLOSED");
            return;
        }
        if (_captureCts is null)
        {
            _uiTimer.Stop();
            App.Log("MAIN WINDOW CLOSED (NO ACTIVE DEVICES)");
            return;
        }
        e.Cancel = true;
        if (_isClosing) return;
        _isClosing = true;
        try
        {
            StatusLabel.Text = "正在断开设备并保存可能进行中的采集记录…";
            await StopCaptureAsync();
            lock (_tableWriterLock)
            {
                _turnWriter?.Dispose();
                _turnWriter = null;
            }
            _allowFinalClose = true;
            Close();
        }
        catch (Exception ex)
        {
            App.Log("SHUTDOWN FAILED; WINDOW KEPT OPEN", ex);
            StatusLabel.Text = "关闭流程异常；请确认设备安全状态：" + ex.Message;
            MessageBox.Show(this,
                "停止或关闭设备通信时出现异常，窗口暂时保持打开。\n" +
                "请确认机械已停止并检查独立硬件急停。\n日志：" + App.DiagnosticsPath,
                "关闭流程异常", MessageBoxButton.OK, MessageBoxImage.Error);
            _isClosing = false;
        }
    }
}
