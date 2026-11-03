using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.IO.Ports;
using System.Reflection;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Threading;
using Dts.Wpf.TestWindows;
using Dts.Wpf.TestWindows.CT05;
using Microsoft.Win32;
using Dts.Core;
using Dts.Devices;
using Dts.TestEngine;
using Dts.Tests.S0;

namespace Dts.Wpf;

public partial class MainWindow : Window
{
    private readonly IReadOnlyList<TestDefinition> _tests;
    private readonly ObservableCollection<StageTileGroup> _groups=[];
    private TestDefinition? _selectedTest;
    // Modules are automatically discovered from Dts.Tests + optional trusted plugins DLLs.
    private readonly TestModuleRegistry _moduleRegistry;
    private readonly TestRunner _testRunner = new();
    private readonly LiveTestHardware _testHardware;
    private CancellationTokenSource? _activeTest;
    private readonly ObservableCollection<string> _logs=[];
    private readonly ObservableCollection<SelectedImuFrame> _liveRows=[];
    private const int MaxLiveRows = 240;
    private ImuMonitorWindow? _imuMonitorWindow;
    private bool? _lastCompactHeight;
    private readonly HashSet<string> _verifiedTd=new(StringComparer.OrdinalIgnoreCase);
    private readonly HashSet<string> _verifiedFdtInner=new(StringComparer.OrdinalIgnoreCase);
    private readonly HashSet<string> _verifiedFdtOuter=new(StringComparer.OrdinalIgnoreCase);
    private readonly SemaphoreSlim _tdGate=new(1,1),_fdtGate=new(1,1);
    private readonly DispatcherTimer _poll=new(){Interval=TimeSpan.FromMilliseconds(900)};
    private RealImu? _imu;
    private IRealTurntable? _td,_fdt;
    // True when the serial port is open but the two axes have not passed the
    // verified auto-enable sequence. No motion is permitted in this state.
    private bool _tdDiagnosticOnly;
    // Last verified feedback is used only while the corresponding port remains connected.
    private TableSnapshot? _latestTdSnapshot;
    private TableSnapshot? _latestFdtSnapshot;
    private CancellationTokenSource? _recorder;
    private bool _busyScanning,_busyPolling;
    private CalibrationSet? _calibration;
    private string _calibrationRoot="";
    private bool _updatingCompensationMode;
    private string _stage="S1";
    private string _saveRoot=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments),"DTS_RealData");
    // Manual IMU recorder uses its own output directory. Test reports keep _saveRoot.
    private string _captureRoot=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments),"DTS_IMU_Captures");

    public MainWindow()
    {
        InitializeComponent();
        _moduleRegistry = TestModuleRegistry.Discover(
            typeof(S0_04_Test).Assembly, Path.Combine(AppContext.BaseDirectory,"plugins"));
        _testHardware = new LiveTestHardware(() => _imu, () => _tdDiagnosticOnly ? null : _td, _tdGate, () => _saveRoot,
            () => CurrentRunForTests());
        _saveRoot = LoadOutputRoot();
        SaveRootText.Text=_saveRoot;
        _captureRoot=LoadCaptureRoot();
        CaptureRootText.Text=_captureRoot;
        _calibrationRoot=LoadCalibrationRoot();
        CalibrationRootText.Text=string.IsNullOrEmpty(_calibrationRoot)?"尚未选择":_calibrationRoot;
        _tests = _moduleRegistry.MergeDefinitions(
            TestCatalog.Load(Path.Combine(AppContext.BaseDirectory,"assets","tests.json")));
        StageGroupsList.ItemsSource=_groups;
        LogList.ItemsSource=_logs;
        ImuSamplesGrid.ItemsSource=_liveRows;
        SetStage("S1");
        RefreshPorts();
        _poll.Tick+=async (_,_)=>await PollAsync();
        _poll.Start();
        Log($"启动：模块化 V0.6.2。自动发现 {_moduleRegistry.Modules.Count} 个测试模块；可执行 {_moduleRegistry.Modules.Count(x=>x.IsExecutable)} 项子功能。");
        foreach (var warning in _moduleRegistry.Warnings) Log("模块注册提示：" + warning);
        Log("真实硬件模式：不生成模拟数据；未实现的测试模块禁止执行，实测诊断不等于产品 PASS。");
    }
    // Adaptive layout: maximize on startup, then redistribute logical (DPI-aware) WPF units.
    // At narrower widths the large navigation sidebar is replaced by compact stage chips.
    private bool _tileResizeQueued;
    private void OnMainSizeChanged(object sender, SizeChangedEventArgs e)
    {
        if (NavSidebar is null || CompactStages is null || TestsPanel is null)
            return; // SizeChanged may arrive while InitializeComponent is still constructing controls.

        // The right equipment workbench is the primary operational area.
        // Keep the tests rail compact; real two-column tiles fill it exactly.
        bool compact = ActualWidth < 1280;
        NavColumn.Width = compact ? new GridLength(0) : new GridLength(178);
        NavSidebar.Visibility = compact ? Visibility.Collapsed : Visibility.Visible;
        CompactStages.Visibility = compact ? Visibility.Visible : Visibility.Collapsed;
        double desiredTestsWidth = ActualWidth >= 1800 ? 565
            : ActualWidth >= 1450 ? 515
            : ActualWidth >= 1200 ? 475 : 430;
        // Reserve enough space for the equipment view, even at 125/150% Windows scaling.
        double testsWidth = Math.Max(255, Math.Min(desiredTestsWidth,
            ActualWidth - (compact ? 520 : 710)));
        TestsColumn.Width = new GridLength(testsWidth, GridUnitType.Pixel);
        DeviceColumn.Width = new GridLength(1, GridUnitType.Star);
        ApplyVerticalLayout();

        // Coalesce rapid resize events; width update runs after the star columns are measured.
        if (_tileResizeQueued) return;
        _tileResizeQueued = true;
        Dispatcher.BeginInvoke((Action)(() =>
        {
            _tileResizeQueued = false;
            UpdateTileSizing();
        }), DispatcherPriority.Loaded);
    }

    // The logical WPF height changes with the monitor DPI. Keep the live-data grid
    // prioritized; secondary diagnostic text remains available under the Expander.
    private void ApplyVerticalLayout()
    {
        if (IdentityBorder is null || ImuDetailsExpander is null || GlobalPathsExpander is null ||
            SelectedTestRow is null || CaptureFileHint is null || WorkbenchDeviceHint is null || TestProcedure is null)
            return;

        bool compact = ActualHeight < 820;
        bool veryCompact = ActualHeight < 650;
        HeaderRow.Height = new GridLength(compact ? 45 : 54);
        IdentityBorder.Padding = compact ? new Thickness(12, 4, 12, 4) : new Thickness(17, 9, 17, 9);
        IdentityGap1.Height = new GridLength(compact ? 3 : 7);
        SelectedTestRow.Height = new GridLength(veryCompact ? 102 : compact ? 122 : 155);
        WorkbenchDeviceHint.Visibility = compact ? Visibility.Collapsed : Visibility.Visible;
        CaptureFileHint.Visibility = compact ? Visibility.Collapsed : Visibility.Visible;
        TestProcedure.Visibility = veryCompact ? Visibility.Collapsed : Visibility.Visible;
        if (_lastCompactHeight != compact)
        {
            // Do not override the operator's expand/collapse choice on every resize event.
            ImuDetailsExpander.IsExpanded = !compact;
            GlobalPathsExpander.IsExpanded = !compact;
            _lastCompactHeight = compact;
        }
    }

    private void OpenImuMonitorClick(object sender, RoutedEventArgs e)
    {
        if (_imuMonitorWindow is { IsVisible: true })
        {
            _imuMonitorWindow.Activate();
            return;
        }
        var monitor = new ImuMonitorWindow(_liveRows);
        _imuMonitorWindow = monitor;
        monitor.Closed += (_, _) => _imuMonitorWindow = null;
        monitor.Show();
    }

    private void UpdateTileSizing()
    {
        if (TestsPanel is null || TestsPanel.ActualWidth <= 0) return;
        // UniformGrid gives each tile exactly half the available row width.
        // WrapPanel + explicit tile widths used to leave a large empty right half
        // on some 125%-150% DPI setups. At truly narrow widths, fall back to 1 column.
        double available = Math.Max(0, TestsPanel.ActualWidth - 80);
        Application.Current.Resources["TestTileColumns"] = available >= 312 ? 2 : 1;
    }

    private void ToggleLogClick(object sender, RoutedEventArgs e)
    {
        bool expanded = LogList.Visibility == Visibility.Visible;
        LogList.Visibility = expanded ? Visibility.Collapsed : Visibility.Visible;
        LogRow.Height = new GridLength(expanded ? 48 : 120);
        LogToggleButton.Content = expanded ? "展开日志" : "收起日志";
    }

    private void CopyUidClick(object sender, RoutedEventArgs e)
    {
        string uid = RawUid.Text.Trim();
        if (uid.Length != 24 || !uid.All(Uri.IsHexDigit))
        {
            MessageBox.Show("尚未取得有效的 12 字节 MCU UID。请先连接真实 IMU。", "复制 UID");
            return;
        }
        Clipboard.SetText(uid);
        Log("已复制 MCU 原始 UID 到剪贴板");
    }

    private void Log(string message)
    {
        _logs.Insert(0,$"{DateTime.Now:HH:mm:ss.fff}  {message}");
        while(_logs.Count>250)_logs.RemoveAt(_logs.Count-1);
    }
    private static string StageTitle(string stage) => stage switch
    {
        "S0" => "常温内参标定",
        "S1" => "常温标定后验证",
        "S2" => "全温与温度补偿",
        "S3" => "动态与抗干扰",
        "S4" => "可靠性与一致性",
        _ => "全部测试阶段"
    };
    private void SetStage(string stage)
    {
        _stage=stage;
        _groups.Clear();
        foreach(string key in new[]{"S0","S1","S2","S3","S4"})
        {
            if(stage!="ALL" && stage!=key)continue;
            var items=_tests.Where(x=>x.Stage==key).ToList();
            var tiles=items.Select(t=>new TestTileView(t,_moduleRegistry.Find(t.Id))).ToList();
            _groups.Add(new StageTileGroup($"{key} · {StageTitle(key)}",$"{items.Count} 项 / 可真实执行子项 {tiles.Count(t=>t.Ready)}",tiles));
        }
        StageName.Text=stage=="ALL"?"全部阶段 / S0～S4":stage+" · "+StageTitle(stage);
        CountLabel.Text=$"{_groups.Sum(x=>x.Tiles.Count)} / {_tests.Count} 项";
        StagesScroller.ScrollToTop();
        if(stage!="ALL") SelectTest(_tests.First(x=>x.Stage==stage));
    }
    private void StageClick(object sender,RoutedEventArgs e) => SetStage((string)((Button)sender).Tag);
    private void SelectTest(TestDefinition t)
    {
        _selectedTest=t;
        SelectedTestName.Text=$"{t.Id}  {t.Name}";
        TestPurpose.Text="目的："+t.Purpose;
        TestProcedure.Text="方法："+t.Procedure;
        var module=_moduleRegistry.Find(t.Id);
        bool ready=module?.IsExecutable==true;
        SelectedTestState.Text=ready?"● "+module!.ImplementationNote:"○ 安全占位 / 尚未实现";
        SelectedTestState.Foreground=ready?Brushes.ForestGreen:Brushes.SaddleBrown;
        TestRunStatus.Text=ready?"等待真实硬件":"尚未开发";
        if(t.Id=="CT-12")DurationSeconds.Text="600";
        else if(t.Id is "CT-09" or "S0-04")DurationSeconds.Text="180";
    }
    // Each card opens its own dedicated (or generic) setup window, never starts blindly.
    private void TestTileClick(object sender,RoutedEventArgs e)
    {
        if(((Button)sender).Tag is not TestTileView tile)return;
        SelectTest(tile.Definition);
        OpenTestWindow(tile.Definition);
    }
    private void RunSelectedTestClick(object sender,RoutedEventArgs e)
    {
        if(_selectedTest is not null)OpenTestWindow(_selectedTest);
    }
    private void OpenTestWindow(TestDefinition definition)
    {
        if(_testRunner.IsRunning || _recorder is not null)
        {MessageBox.Show("当前有真实任务执行中，请完成或取消后再打开另一测试。","任务占用");return;}
        if(string.IsNullOrWhiteSpace(_saveRoot)||!Directory.Exists(_saveRoot))
        {MessageBox.Show("请先在顶部选择有效的报告保存目录。","报告目录",MessageBoxButton.OK,MessageBoxImage.Information);return;}
        var module=_moduleRegistry.Find(definition.Id);
        // Find dedicated subwindow through an attribute; adding another compiled XAML window
        // requires no MainWindow source change. Tests without dedicated UI use generic setup.
        var type=typeof(MainWindow).Assembly.GetTypes().FirstOrDefault(t=>
            !t.IsAbstract && typeof(Window).IsAssignableFrom(t) &&
            string.Equals(t.GetCustomAttribute<TestWindowForAttribute>()?.TestId,
                definition.Id,StringComparison.OrdinalIgnoreCase));
        Window child;
        if(type is not null)
        {
            if(module is null)throw new InvalidOperationException("测试未注册执行模块");
            child=(Window)(Activator.CreateInstance(type,
                definition,module,_testHardware,_testRunner,_saveRoot)
                ??throw new InvalidOperationException("测试专用窗口无法创建"));
        }
        else child=new GenericTestWindow(definition,module,_testRunner,_testHardware,_saveRoot);
        if(child is ICalibrationDirectoryAware aware)
            aware.SuggestCalibrationDirectory(_calibrationRoot);
        if(child is ICalibrationRunAware runAware)
            runAware.SetCalibrationRun(BuildSelectedRun());
        child.Owner=this;
        child.Show();
        Log($"打开专用测试窗口：{definition.Id}，报告根目录={_saveRoot}");
    }
    private static string OutputSettingsFile=>Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "DTS_TestPlatform","output_root.txt");
    private string LoadOutputRoot()
    {
        try
        {
            var f=OutputSettingsFile;
            if(File.Exists(f))
            {
                string dir=File.ReadAllText(f).Trim();
                if(Directory.Exists(dir))return dir;
            }
        }
        catch(IOException){}
        catch(UnauthorizedAccessException){}
        return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments),"DTS_RealData");
    }
    private static string CaptureSettingsFile=>Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "DTS_TestPlatform","capture_root.txt");

    private static string LoadCaptureRoot()
    {
        try
        {
            if(File.Exists(CaptureSettingsFile))
            {
                string dir=File.ReadAllText(CaptureSettingsFile).Trim();
                if(Directory.Exists(dir))return dir;
            }
        }
        catch(IOException){}
        catch(UnauthorizedAccessException){}
        // Distinct from test-report storage; neither path can be inferred from the other.
        return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments),"DTS_IMU_Captures");
    }

    private void ChooseCaptureRootClick(object sender,RoutedEventArgs e)
    {
        if(_recorder is not null || _activeTest is not null || _testRunner.IsRunning)
        {
            MessageBox.Show("采集或测试进行中，不能更改采集目录。","采集目录被占用");
            return;
        }
        var dialog=new OpenFolderDialog
        {
            Title="选择 IMU 原始/所选模式数据的保存目录（与报告目录独立）",
            Multiselect=false
        };
        if(dialog.ShowDialog(this)!=true)return;
        try
        {
            string selected=Path.GetFullPath(dialog.FolderName);
            if(string.Equals(Path.TrimEndingDirectorySeparator(selected),Path.TrimEndingDirectorySeparator(Path.GetFullPath(_saveRoot)),StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("采集目录应与测试报告目录分开，请选择其他文件夹。");
            Directory.CreateDirectory(selected);
            string probe=Path.Combine(selected,".dts_capture_write_probe_"+Guid.NewGuid().ToString("N"));
            try{File.WriteAllText(probe,"ok");}
            finally{if(File.Exists(probe))File.Delete(probe);}
            Directory.CreateDirectory(Path.GetDirectoryName(CaptureSettingsFile)!);
            File.WriteAllText(CaptureSettingsFile,selected);
            _captureRoot=selected;
            CaptureRootText.Text=selected;
            Log("IMU 手动采集目录已设置："+selected);
        }
        catch(Exception ex)
        {
            MessageBox.Show(ex.Message,"无法使用采集目录",MessageBoxButton.OK,MessageBoxImage.Warning);
        }
    }

    private static string CalibrationSettingsFile=>Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "DTS_TestPlatform","calibration_root.txt");
    private static string LoadCalibrationRoot()
    {
        try
        {
            if(File.Exists(CalibrationSettingsFile))
            {
                string path=File.ReadAllText(CalibrationSettingsFile).Trim();
                if(Directory.Exists(path)) return path;
            }
        }
        catch(IOException) { }
        catch(UnauthorizedAccessException) { }
        return "";
    }
    private void ChooseCalibrationRootClick(object sender,RoutedEventArgs e)
    {
        if(_recorder is not null || _testRunner.IsRunning)
        {MessageBox.Show("采集/测试期间禁止更改标定来源。","标定目录占用");return;}
        var picker=new OpenFolderDialog{Title="选择标定总目录（递归查找全部子文件夹）",Multiselect=false};
        if(picker.ShowDialog(this)!=true)return;
        try
        {
            _calibrationRoot=Path.GetFullPath(picker.FolderName);
            CalibrationRootText.Text=_calibrationRoot;
            Directory.CreateDirectory(Path.GetDirectoryName(CalibrationSettingsFile)!);
            File.WriteAllText(CalibrationSettingsFile,_calibrationRoot);
            CalibrationOwnership.IsChecked=false;
            LoadMatchingCalibration();
            Log("已选择标定总目录（递归匹配）："+_calibrationRoot);
        }
        catch(Exception ex){MessageBox.Show(ex.Message,"读取标定文件夹失败",MessageBoxButton.OK,MessageBoxImage.Warning);}
    }
    private CalibrationMode SelectedMode => AmbientCompensation.IsChecked == true ? CalibrationMode.Ambient :
        ThermalCompensation.IsChecked == true ? CalibrationMode.Thermal : CalibrationMode.Raw;

    private CalibrationRun BuildSelectedRun() => new(SelectedMode, _calibration, CalibrationOwnership.IsChecked == true);
    private CalibrationRun CurrentRunForTests()
    {
        var run=BuildSelectedRun();
        var id=_imu?.Identity;
        if(id is null)throw new InvalidOperationException("尚未读取真实IMU UID");
        run.Validate(id);
        return run;
    }
    private void CompensationModeChanged(object sender,RoutedEventArgs e)
    {
        if(_updatingCompensationMode || AmbientCompensation is null || ThermalCompensation is null)return;
        _updatingCompensationMode=true;
        try
        {
            if(sender==AmbientCompensation && AmbientCompensation.IsChecked==true)
                ThermalCompensation.IsChecked=false;
            if(sender==ThermalCompensation && ThermalCompensation.IsChecked==true)
                AmbientCompensation.IsChecked=false;
        }
        finally{_updatingCompensationMode=false;}
        _liveRows.Clear();
        LiveRowsCountText.Text="最近 0 帧 / 最多显示 240 帧";
        StreamStatusText.Text=$"实时六轴：{(SelectedMode==CalibrationMode.Raw ? "原始计数 (count)" : SelectedMode==CalibrationMode.Ambient ? "常温补偿 (g / °/s)" : "全温补偿 (g / °/s)")} · 等待读取";
        CalibrationOptionsChanged(sender,e);
    }
    private void LoadMatchingCalibration()
    {
        _liveRows.Clear();
        LiveRowsCountText.Text="最近 0 帧 / 最多显示 240 帧";
        _calibration=null;
        CalibrationOwnership.IsChecked=false;
        var id=_imu?.Identity;
        if(id is null)
        {CalibrationStatus.Text="先连接IMU获取完整UID；无须手动选择标定JSON";return;}
        if(string.IsNullOrWhiteSpace(_calibrationRoot))
        {CalibrationStatus.Text="尚未选择标定文件夹；原始计数采集可用";return;}
        try
        {
            _calibration=CalibrationLibrary.Load(_calibrationRoot,id);
            CalibrationOwnership.IsChecked=_calibration.AllFullUidVerified;
            Log("UID递归匹配4类标定文件："+_calibration.Summary);
            CalibrationOptionsChanged(this,new RoutedEventArgs());
        }
        catch(Exception ex)
        {
            CalibrationStatus.Text="标定文件未加载："+ex.Message+"。原始数据采集仍可用。";
            Log(CalibrationStatus.Text);
        }
    }
    private void CalibrationOptionsChanged(object sender,RoutedEventArgs e)
    {
        if(CalibrationStatus is null || ModeHint is null || AmbientCompensation is null || ThermalCompensation is null)return;
        if(_recorder is not null)return;
        var mode=SelectedMode;
        if(mode==CalibrationMode.Raw)
        {
            ModeHint.Text="当前：原始 int16 数据。无须标定文件，不对原始计数做标定补偿。";
            CalibrationStatus.Text=_calibration is null?"未加载标定文件（原始采集正常可用）":_calibration.Summary;
            return;
        }
        try
        {
            CurrentRunForTests();
            ModeHint.Text=mode==CalibrationMode.Ambient?"常温：实时使用ACC/Gyro常温矩阵；原始计数仍保留":
                "全温：实时按芯片温度计算F(T)逆矩阵和b(T)；原始计数仍保留";
            CalibrationStatus.Text="匹配成功："+_calibration!.Summary+"；若MCU量程未报告，补偿值留空。";
        }
        catch(Exception ex)
        {
            ModeHint.Text="所选补偿模式尚不可用；原始计数仍可采集。";
            CalibrationStatus.Text="尚不能应用补偿："+ex.Message;
        }
    }
    private void UpdateLiveRows(IReadOnlyList<SelectedImuFrame> frames)
    {
        if(frames.Count==0)return;
        // A delayed UI progress callback from a previous capture must not mix
        // rows from another compensation mode into the current view.
        if(frames[0].Mode!=SelectedMode)return;
        foreach(var frame in frames)
        {
            _liveRows.Add(frame);
            if(_liveRows.Count>MaxLiveRows)_liveRows.RemoveAt(0);
        }
        var newest=frames[^1];
        StreamStatusText.Text=$"实时六轴：{newest.ModeLabel} · ACC {newest.AccUnit} / Gyro {newest.GyroUnit} · {newest.Status}";
        LiveRowsCountText.Text=$"最近 {_liveRows.Count} 帧 / 最多显示 {MaxLiveRows} 帧";
        // DataGrid handles its own vertical scrollbar; control-panel buttons never scroll.
        ImuSamplesGrid.ScrollIntoView(_liveRows[^1]);
    }
    private void ChooseSaveRootClick(object sender,RoutedEventArgs e)
    {
        if(_recorder is not null || _testRunner.IsRunning)
        {MessageBox.Show("采集/测试期间禁止更改报告保存目录。","数据目录占用");return;}
        var d=new OpenFolderDialog{Title="选择测试数据和报告保存根目录",Multiselect=false};
        if(d.ShowDialog(this)!=true)return;
        try
        {
            string selected=Path.GetFullPath(d.FolderName);
            if(string.Equals(Path.TrimEndingDirectorySeparator(selected),
                    Path.TrimEndingDirectorySeparator(Path.GetFullPath(_captureRoot)),
                    StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("报告目录应与 IMU 手动采集目录分开，请选择其他文件夹。");
            Directory.CreateDirectory(selected);
            string test=Path.Combine(selected,".dts_write_probe.tmp");
            File.WriteAllText(test,"ok");File.Delete(test);
            _saveRoot=selected;SaveRootText.Text=selected;
            Directory.CreateDirectory(Path.GetDirectoryName(OutputSettingsFile)!);
            File.WriteAllText(OutputSettingsFile,_saveRoot);
            Log("已设置报告根目录："+_saveRoot);
        }
        catch(Exception ex){MessageBox.Show(ex.Message,"保存目录无法写入",MessageBoxButton.OK,MessageBoxImage.Warning);}
    }

    /// <summary>所有测试按钮走同一个 TestRunner，不再按编号写 if/switch。</summary>
    private async Task RunModuleAsync(TestDefinition definition)
    {
        var module = _moduleRegistry.Find(definition.Id);
        if(module?.IsExecutable!=true)
        {
            Log($"{definition.Id} 尚未实现，不允许运行或生成测试结果");
            return;
        }
        if(_activeTest is not null || _recorder is not null || _testRunner.IsRunning)
        {
            Log("已有实测任务正在运行，不能同时启动第二项");
            return;
        }
        try
        {
            if(!double.TryParse(DurationSeconds.Text,NumberStyles.Float,CultureInfo.InvariantCulture,out var seconds)
               || seconds<1 || seconds>86400)
                throw new ArgumentOutOfRangeException(nameof(seconds),"采样时长必须在 1～86400 秒之间");
            // Every executable test requires operator confirmation, including future plug-ins.
            if(module.RequiresStaticBench && (_imu?.Connected!=true || _imu.Identity is null))
                throw new InvalidOperationException("请先连接真实 IMU 并完成 MCU UID 核验");
            if(!module.RequiresStaticBench && SafetyConfirm.IsChecked!=true)
                throw new InvalidOperationException("非静态测试请先勾选右侧机械安全条件确认；未核准的运动流程不得执行");
            string benchNote=module.RequiresStaticBench
                ? "请现场确认：IMU 固定牢靠、转台完全停止、无人触碰设备。\n当前已接入的静态子项不发送转台运动指令。"
                : "此模块可能涉及真实转台运动或其他实验动作。\n请确认机械限位、夹具、线缆、隔离区域和物理急停均已核验。\n自动运动还必须经过独立硬件安全调度服务验证。";
            var confirmed=MessageBox.Show(
                $"准备执行 {definition.Id}：{definition.Name}\n\n{module.ImplementationNote}\n\n"+
                benchNote+$"\n预计持续 {seconds:F0} 秒。\n\n继续？",
                "确认真实设备测试",MessageBoxButton.YesNo,MessageBoxImage.Warning);
            if(confirmed!=MessageBoxResult.Yes) return;
            var cts=new CancellationTokenSource();
            _activeTest=cts;
            TestRunStatus.Text="实测任务执行中";
            Log($"模块执行：{definition.Id} / {module.GetType().FullName}");
            var progress=new Progress<string>(x=> {TestRunStatus.Text=x; ImuStatus.Text=x;});
            var context=new TestExecutionContext(definition,TimeSpan.FromSeconds(seconds),_testHardware,progress);
            var result=await _testRunner.RunAsync(module,context,cts.Token);
            TestRunStatus.Text=result.Outcome==TestOutcome.DiagnosticOnly
                ? "真实诊断子项完成（非产品 PASS）"
                : $"已完成：{result.Outcome}";
            Log($"{result.TestId}: {result.Summary}");
            if(result.Capture is { } a)
            {
                ImuStatus.Text=$"实采 {a.Samples} 帧 / {a.Batches} 批；DTS={a.DeviceNumber}";
                Log($"原始UID={a.UidHex}；结果目录：{a.Folder}");
            }
        }
        catch(OperationCanceledException)
        {
            TestRunStatus.Text="已取消（不生成完成/PASS 结论）";
            Log($"{definition.Id} 测试取消，可能保留部分原始采样文件");
        }
        catch(Exception ex)
        {
            TestRunStatus.Text="未完成："+ex.Message;
            Log($"{definition.Id} 模块异常：{ex.Message}");
            MessageBox.Show(ex.Message,"测试未完成",MessageBoxButton.OK,MessageBoxImage.Warning);
        }
        finally
        {
            _activeTest?.Dispose();
            _activeTest=null;
        }
    }

    private void RefreshPortsClick(object sender,RoutedEventArgs e)=>RefreshPorts();
    private void RefreshPorts()
    {
        var names=ComPorts.Available();
        foreach(ComboBox box in new[]{ImuPort,TdPort,FdtInnerPort,FdtOuterPort})
        {
            var prior=box.SelectedItem as string;
            box.ItemsSource=names;
            box.SelectedItem=prior is not null && names.Contains(prior)?prior:null;
        }
        ScanStatus.Text="发现的 COM 端口："+(names.Length==0?"无（检查驱动/接线）":string.Join("、",names));
    }
    private async void ScanClick(object sender,RoutedEventArgs e)
    {
        if(_testRunner.IsRunning || _recorder is not null)
        {Log("当前测试/采集占用硬件，禁止扫描端口");return;}
        if(_busyScanning){return;}
        SetScanningUi(true);
        try
        {
            if(_imu?.Connected==true||_td?.Connected==true||_fdt?.Connected==true)
                throw new InvalidOperationException("扫描前请关闭已连接设备/退出其他串口上位机；避免端口竞争。此版本可重启程序后扫描。");
            _verifiedTd.Clear();_verifiedFdtInner.Clear();_verifiedFdtOuter.Clear();
            string[] ports=ComPorts.Available();
            if(ports.Length==0){Log("未发现 COM 端口");return;}
            var progress=new Progress<string>(x=>{ScanStatus.Text=x;Log(x);});
            int baud=ParseInt(ImuBaud.Text,1500000);
            byte slave=checked((byte)ParseInt(ImuSlave.Text,1));
            // Discover the 2TD using passive listening FIRST: no Modbus probe is sent to a motor controller.
            var td=await SerialDiscovery.Find2TdAsync(ports,progress,CancellationToken.None);
            var busyPorts=td.Select(x=>x.Port).ToHashSet(StringComparer.OrdinalIgnoreCase);
            foreach(var t in td)_verifiedTd.Add(t.Port);
            var potentialImu=ports.Where(p=>!busyPorts.Contains(p)).ToArray();
            var imu=await SerialDiscovery.FindImuAsync(potentialImu,baud,slave,progress,CancellationToken.None);
            foreach(var i in imu)busyPorts.Add(i.Port);
            var other=ports.Where(p=>!busyPorts.Contains(p)).ToArray();
            var fdt=await FdtDiscovery.ScanAsync(other,progress,CancellationToken.None);
            foreach(var t in fdt)
            {
                if(t.Axis=="内轴")_verifiedFdtInner.Add(t.Port);
                if(t.Axis=="外轴")_verifiedFdtOuter.Add(t.Port);
            }
            if(imu.FirstOrDefault() is { } im)ImuPort.SelectedItem=im.Port;
            if(td.FirstOrDefault() is { } ttd){TdPort.SelectedItem=ttd.Port;TdBaud.Text=ttd.Proof.Contains("921600")?"921600":"115200";}
            if(fdt.FirstOrDefault(x=>x.Axis=="内轴") is { } fi)FdtInnerPort.SelectedItem=fi.Port;
            if(fdt.FirstOrDefault(x=>x.Axis=="外轴") is { } fo)FdtOuterPort.SelectedItem=fo.Port;
            ScanStatus.Text=$"验证成功：IMU {imu.Count}，2TD {td.Count}，2FDT 轴 {fdt.Count}（真实只读响应）";
            Log(ScanStatus.Text);
            foreach(var item in imu.Concat(td).Concat(fdt))Log($"识别 {item.Device}/{item.Axis} {item.Port}：{item.Proof}");
        }
        catch(Exception ex){ScanStatus.Text="扫描失败："+ex.Message;Log(ScanStatus.Text);}
        finally{SetScanningUi(false);}
    }
    private string[] PortsNotOccupiedByConnectedDevices()
    {
        var excluded=new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        if(_imu?.Connected==true && !string.IsNullOrWhiteSpace(_imu.PortName))
            excluded.Add(_imu.PortName);
        if(_td?.Connected==true)
        {
            string tdPort=_td.Ports;
            if(!string.IsNullOrWhiteSpace(tdPort))excluded.Add(tdPort);
        }
        if(_fdt?.Connected==true)
        {
            // FDT is connected; skip its two selected ports to avoid contention.
            if(FdtInnerPort.SelectedItem is string inner)excluded.Add(inner);
            if(FdtOuterPort.SelectedItem is string outer)excluded.Add(outer);
        }
        return ComPorts.Available().Where(port=>!excluded.Contains(port)).ToArray();
    }

    private void SetScanningUi(bool scanning)
    {
        _busyScanning=scanning;
        ScanButton.IsEnabled=!scanning;
        TdScanButton.IsEnabled=!scanning;
        FdtScanButton.IsEnabled=!scanning;
    }

    private async void TdScanClick(object sender,RoutedEventArgs e)
    {
        if(_busyScanning || _recorder is not null || _activeTest is not null || _testRunner.IsRunning)
        {TdStatus.Text="当前存在扫描/采集/测试任务，暂不能扫描串口";return;}
        if(_td?.Connected==true){TdStatus.Text="2TD 已连接，无需重复扫描；先断开后再扫描";return;}
        SetScanningUi(true);
        _verifiedTd.Clear();
        try
        {
            RefreshPorts();
            string[] ports=PortsNotOccupiedByConnectedDevices();
            if(ports.Length==0){TdStatus.Text="没有可用于扫描的空闲 COM 口";return;}
            TdStatus.Text="正在自动监听 2TD-600 状态帧（不发送运动指令）…";
            var progress=new Progress<string>(message=>TdStatus.Text=message);
            var detected=await SerialDiscovery.Find2TdAsync(ports,progress,CancellationToken.None);
            foreach(var found in detected)_verifiedTd.Add(found.Port);
            if(detected.Count==1)
            {
                var found=detected[0];
                TdPort.SelectedItem=found.Port;
                TdBaud.Text=found.Proof.Contains("921600",StringComparison.Ordinal)?"921600":"115200";
                TdStatus.Text=$"已识别 {found.Port}，{found.Proof}；请点击连接 2TD";
                Log("2TD 独立自动扫描："+TdStatus.Text);
            }
            else if(detected.Count>1)
            {
                TdStatus.Text="识别到多个 2TD 候选端口："+string.Join("、",detected.Select(x=>x.Port))+"；请核对硬件后手动选择";
                Log(TdStatus.Text);
            }
            else TdStatus.Text="未监听到有效 2TD 状态帧。某些设备不主动上报，请检查接线/占用及厂家上报模式；不自动猜测串口。";
        }
        catch(Exception ex){TdStatus.Text="2TD 扫描失败："+ex.Message;Log(TdStatus.Text);}
        finally{SetScanningUi(false);}
    }

    private async void FdtScanClick(object sender,RoutedEventArgs e)
    {
        if(_busyScanning || _recorder is not null || _activeTest is not null || _testRunner.IsRunning)
        {FdtStatus.Text="当前存在扫描/采集/测试任务，暂不能扫描串口";return;}
        if(_fdt?.Connected==true){FdtStatus.Text="温控转台已连接，无需重复扫描；先断开后再扫描";return;}
        SetScanningUi(true);
        _verifiedFdtInner.Clear();_verifiedFdtOuter.Clear();
        try
        {
            RefreshPorts();
            string[] ports=PortsNotOccupiedByConnectedDevices();
            if(ports.Length==0){FdtStatus.Text="没有可用于扫描的空闲 COM 口";return;}
            FdtStatus.Text="正在查询温控转台内外轴实际状态（无运动/使能指令）…";
            var progress=new Progress<string>(message=>FdtStatus.Text=message);
            var detected=await FdtDiscovery.ScanAsync(ports,progress,CancellationToken.None);
            foreach(var match in detected)
            {
                if(match.Axis=="内轴")_verifiedFdtInner.Add(match.Port);
                if(match.Axis=="外轴")_verifiedFdtOuter.Add(match.Port);
            }
            var innerCandidates=detected.Where(x=>x.Axis=="内轴").ToList();
            var outerCandidates=detected.Where(x=>x.Axis=="外轴").ToList();
            if(innerCandidates.Count==1 && outerCandidates.Count==1 &&
               !string.Equals(innerCandidates[0].Port,outerCandidates[0].Port,StringComparison.OrdinalIgnoreCase))
            {
                FdtInnerPort.SelectedItem=innerCandidates[0].Port;
                FdtOuterPort.SelectedItem=outerCandidates[0].Port;
                FdtStatus.Text=$"内轴 {innerCandidates[0].Port} / 外轴 {outerCandidates[0].Port}；已通过两次状态读取，请点击连接温控转台";
            }
            else
            {
                FdtStatus.Text=$"候选：内轴 [{string.Join("、",innerCandidates.Select(x=>x.Port))}]，外轴 [{string.Join("、",outerCandidates.Select(x=>x.Port))}]。"+
                    "无法唯一确认独立轴端口；请核对线缆/配置后手动选择，不能自动误配。";
            }
            Log("温控转台独立自动扫描："+FdtStatus.Text);
        }
        catch(Exception ex){FdtStatus.Text="温控转台扫描失败："+ex.Message;Log(FdtStatus.Text);}
        finally{SetScanningUi(false);}
    }

    private async void ImuConnectClick(object sender,RoutedEventArgs e)
    {
        if(_testRunner.IsRunning || _activeTest is not null || _recorder is not null)
        {Log("正在执行真实测试，不能切换IMU连接");return;}
        try
        {
            if(_imu?.Connected==true)
            {
                // Only disconnected while idle (checked above); no need to close the application.
                var old = _imu;
                _imu = null; // prevent new timer polls using this instance
                await Task.Delay(100); // let any in-flight read-only preview settle
                old.Dispose();
                DeviceNumber.Text="--";
                RawUid.Text="--";
                ImuStatus.Text="IMU 已断开；串口已释放";
                StreamStatusText.Text="IMU 已断开";
                UpdateConnection();
                Log("用户主动断开 IMU 串口");
                return;
            }
            string port=Selected(ImuPort);
            int baud=ParseInt(ImuBaud.Text,1500000);
            byte slave=checked((byte)ParseInt(ImuSlave.Text,1));
            var imu=new RealImu();
            await imu.ConnectAsync(port,baud,slave,CancellationToken.None);
            _imu=imu;
            DeviceNumber.Text=imu.Identity!.DtsId;
            RawUid.Text=imu.Identity.UidHex;
            ImuStatus.Text=$"实际设备已连接：{port} @ {baud}，{imu.Identity.DtsId}";
            Log("硬件 IMU 身份核验："+imu.Identity.UidHex+"，显示编号="+imu.Identity.DtsId);
            UpdateConnection();
            LoadMatchingCalibration();
        }
        catch(Exception ex){ImuStatus.Text="IMU 连接失败："+ex.Message;Log(ImuStatus.Text);}
    }
    private async void RecordClick(object sender,RoutedEventArgs e)
    {
        if(_recorder is not null)
        {
            RecordButton.Content="正在停止…";
            RecordButton.IsEnabled=false;
            _recorder.Cancel();
            return;
        }
        await RunRealTestAsync("RAW_ACQUISITION","真实 IMU 原始/标定并行采集",false);
    }

    private async Task RunRealTestAsync(string id,string testName,bool analyze)
    {
        if(_recorder is not null || _activeTest is not null || _testRunner.IsRunning)
        {Log("已有真实任务正在运行，不能重复启动采集");return;}
        try
        {
            if(_imu?.Connected!=true || _imu.Identity is null)
                throw new InvalidOperationException("请先连接真实 IMU，读取并核验 MCU 12 字节 UID");
            bool isTimed=TimedCapture.IsChecked==true;
            TimeSpan? duration=null;
            if(isTimed)
            {
                if(!double.TryParse(ImuRawSeconds.Text,NumberStyles.Float,CultureInfo.InvariantCulture,out var seconds)
                   || seconds<1 || seconds>86400)
                    throw new ArgumentOutOfRangeException(nameof(seconds),"定时时长须为1～86400秒；取消“定时自动停止”可手动停止");
                duration=TimeSpan.FromSeconds(seconds);
            }
            var selectedRun=BuildSelectedRun();
            selectedRun.Validate(_imu.Identity);
            // Do not route the manual IMU recorder into the test report directory.
            if(!Directory.Exists(_captureRoot))Directory.CreateDirectory(_captureRoot);
            var device=_imu;
            var identity=device.Identity;
            var cts=new CancellationTokenSource();_recorder=cts;
            RecordButton.Content="停止采集";
            RecordButton.Background=new SolidColorBrush(Color.FromRgb(188,69,84));
            TimedCapture.IsEnabled=false;
            ImuRawSeconds.IsEnabled=false;
            CalibrationOwnership.IsEnabled=false;
            AmbientCompensation.IsEnabled=false;
            ThermalCompensation.IsEnabled=false;
            TestRunStatus.Text="正在采集真实 IMU";
            Log($"真实采集启动：{id}；DTS={identity.DtsId}；采集目录={_captureRoot}；"+
                (duration is null?"手动停止模式":$"限时 {duration.Value.TotalSeconds:F1}s")+
                $"；处理模式={selectedRun.Mode}；UID凭据={selectedRun.IdentityProof}");
            var progress=new Progress<string>(p=>{TestRunStatus.Text=p;ImuStatus.Text=p;});
            _liveRows.Clear();
            StreamStatusText.Text=$"正在采集：{selectedRun.Mode}，主数据 CSV 与表格同步";
            var liveRows=new Progress<IReadOnlyList<SelectedImuFrame>>(UpdateLiveRows);
            var result=await Acquisition.CollectAsync(device,duration,id,progress,cts.Token,_captureRoot,
                selectedRun,finishOnManualStop:true,liveRows:liveRows);
            string? report=null;
            if(analyze && result.Samples>=50)
                report=await StaticDiagnostics.AnalyzeAsync(result,identity,id,CancellationToken.None);
            TestRunStatus.Text=result.Status=="STOPPED_BY_OPERATOR" ?
                $"已手动停止，已保存 {result.Samples} 帧（不是验收 PASS）":
                $"定时采集完成，已保存 {result.Samples} 帧（不是验收 PASS）";
            ImuStatus.Text=$"UID {identity.DtsId} · {result.Samples}帧 / {result.Batches}批 · {result.SelectedMode} " +
                $"补偿成功 {result.ProcessedSamples} 帧，量程未核实批次 {result.UnknownScaleBatches}";
            Log($"真实数据：{result.Folder}，状态={result.Status}；主记录=imu_selected.csv ({result.SelectedMode})，原始备份=imu_raw.csv；补偿帧 {result.ProcessedSamples}，量程未知批次 {result.UnknownScaleBatches}");
            if(report is not null)Log("静态统计输出："+report);
        }
        catch(Exception ex)
        {
            TestRunStatus.Text="采集未完成："+ex.Message;
            Log("采集异常："+ex.Message);
            MessageBox.Show(ex.Message,"真实采集异常",MessageBoxButton.OK,MessageBoxImage.Warning);
        }
        finally
        {
            _recorder?.Dispose();_recorder=null;
            RecordButton.Content="开始采集";
            RecordButton.IsEnabled=true;
            RecordButton.ClearValue(Control.BackgroundProperty);
            TimedCapture.IsEnabled=true;
            ImuRawSeconds.IsEnabled=true;
            CalibrationOwnership.IsEnabled=true;
            AmbientCompensation.IsEnabled=true;
            ThermalCompensation.IsEnabled=true;
        }
    }
    private void CancelRecordClick(object sender,RoutedEventArgs e)
    {
        _activeTest?.Cancel();
        _recorder?.Cancel();
    }
    private static string DescribeTdAxis(string name, AxisState axis) =>
        $"{name}: 角度={axis.PositionDeg:F4}°，速度={axis.SpeedDps:F4}°/s，" +
        $"正常={(axis.Normal ? "是" : "否")}，使能={(axis.Enabled ? "是" : "否")}，" +
        $"到位={(axis.InPlace == true ? "是" : axis.InPlace == false ? "否" : "未知")}；{axis.Detail}";

    private async void TdConnectClick(object sender, RoutedEventArgs e)
    {
        if (_busyScanning || _testRunner.IsRunning || _recorder is not null)
        { Log("扫描/测试/采集期间不能切换 2TD 连接"); return; }
        await _tdGate.WaitAsync();
        try
        {
            if (_td?.Connected == true)
            {
                // Diagnosis-only connection: no enable commands have succeeded
                // as far as the software can verify. Do not blindly issue Disable.
                var before = await Task.Run(_td.Read);
                if (!TdConnectionPolicy.Stopped(before))
                    throw new IOException("2TD 未确认双轴静止：禁止直接关闭串口。请先按厂家规定安全停车。");
                if (_tdDiagnosticOnly && !before.Inner.Enabled && !before.Outer.Enabled)
                {
                    if (SafetyConfirm.IsChecked != true)
                        throw new IOException("只读断开前请现场核实两轴已停稳、实体急停可用并勾选安全确认。");
                    if (MessageBox.Show("已读取到双轴速度接近零且均未使能。请现场再次核实机械已停稳、装夹及负载已得到支撑。是否只关闭通信端口？\n注意：关闭串口不等于停车。",
                            "2TD 只读诊断安全断开", MessageBoxButton.YesNo, MessageBoxImage.Warning)
                        != MessageBoxResult.Yes) return;
                    _td.Dispose(); _td = null; _tdDiagnosticOnly = false;
                    TdStatus.Text = "2TD 诊断端口已关闭（无自动断使能命令）";
                    Log(TdStatus.Text); UpdateConnection(); return;
                }
                if (!before.Inner.Normal || !before.Outer.Normal)
                    throw new IOException("状态异常且已有使能状态；不可自动断使能/断开。请使用厂家操作规程处理，再确认安全状态。");
                if (MessageBox.Show("双轴已反馈静止。断使能可能使轴失去保持力，请确认夹具/负载安全。是否断使能、验证后关闭端口？",
                    "2TD 安全断开", MessageBoxButton.YesNo, MessageBoxImage.Warning) != MessageBoxResult.Yes) return;
                await Task.Run(() =>
                {
                    if (before.Inner.Enabled) _td.DisableAxis(0);
                    if (before.Outer.Enabled) _td.DisableAxis(2);
                    var after = _td.Read();
                    if (after.Inner.Enabled || after.Outer.Enabled || !TdConnectionPolicy.Stopped(after))
                        throw new IOException("无法确认双轴已断使能且静止；保持串口连接，禁止当作安全断开");
                    _td.Dispose();
                });
                _td = null; _tdDiagnosticOnly = false;
                TdStatus.Text = "2TD 已验证断使能并关闭串口";
                Log(TdStatus.Text); UpdateConnection(); return;
            }

            string port = Selected(TdPort);
            if (!_verifiedTd.Contains(port))
                throw new InvalidOperationException("请先自动扫描并确认 2TD COM 端口有可校验的真实状态帧");
            if (SafetyConfirm.IsChecked != true)
                throw new InvalidOperationException("连接后可能自动使能：先确认实体急停、夹具、机械位置与线缆并勾选安全确认");
            if (MessageBox.Show("先建立 2TD 通信并读取双轴状态。只有双轴确认正常且静止才会自动使能；否则保留只读诊断连接、禁止运动。确认现场安全？",
                "2TD 安全连接", MessageBoxButton.YesNo, MessageBoxImage.Warning) != MessageBoxResult.Yes) return;

            var table = new Td600(port, ParseInt(TdBaud.Text, 115200));
            try { await Task.Run(table.Connect); }
            catch { table.Dispose(); throw; }
            // Opening a COM port is not the same as confirming that axes can enable.
            // Do not dispose the port because the first read returns "normal=0";
            // that erases precisely the diagnostic state needed by the operator.
            _td = table;
            _tdDiagnosticOnly = true;
            UpdateConnection();

            TableSnapshot? snapshot = null;
            string? readError = null;
            // The vendor DLL can deliver a stale/empty first state after OpenPort.
            // Make a few read-only attempts without sending any motor commands.
            for (int attempt = 0; attempt < 4; attempt++)
            {
                try
                {
                    snapshot = await Task.Run(table.Read);
                    if (TdConnectionPolicy.CanAutoEnable(snapshot)) break;
                }
                catch (Exception ex) { readError = ex.Message; }
                if (attempt < 3) await Task.Delay(250);
            }
            if (snapshot is null)
            {
                TdStatus.Text = "2TD 串口已打开（只读），但未取得可信状态：" + (readError ?? "未知原因");
                Log(TdStatus.Text); return;
            }
            string diagnostic = DescribeTdAxis("内轴", snapshot.Inner) + "；" +
                                DescribeTdAxis("外轴", snapshot.Outer);
            Log("2TD 连接初始状态：" + diagnostic);
            if (!TdConnectionPolicy.CanAutoEnable(snapshot))
            {
                TdStatus.Text = "2TD 已连接·仅诊断（未自动使能）：" + diagnostic;
                // A fault indication must not be bypassed simply to permit movement.
                Log("2TD 自动使能条件未满足；保留状态读取，运动仍被设备层安全检查拦截");
                return;
            }

            try
            {
                await Task.Run(() => { table.EnableAxis(0); table.EnableAxis(2); });
                await Task.Delay(300);
                var afterEnable = await Task.Run(table.Read);
                if (!afterEnable.Inner.Enabled || !afterEnable.Outer.Enabled ||
                    !afterEnable.Inner.Normal || !afterEnable.Outer.Normal)
                    throw new IOException("发送使能后未获取双轴正常且已使能的反馈：" +
                        DescribeTdAxis("内轴", afterEnable.Inner) + "；" +
                        DescribeTdAxis("外轴", afterEnable.Outer));
                _tdDiagnosticOnly = false;
                TdStatus.Text = "2TD 已连接，双轴使能已由反馈确认";
                Log(TdStatus.Text);
            }
            catch (Exception ex)
            {
                // One axis may already be enabled. Never silently release this
                // port or claim that both axes are disabled after a partial failure.
                _tdDiagnosticOnly = true;
                TdStatus.Text = "2TD 已连接·使能未确认（禁止运动）：" + ex.Message;
                Log(TdStatus.Text);
            }
        }
        catch (Exception ex)
        {
            TdStatus.Text = "2TD 连接/断开操作失败：" + ex.Message;
            Log(TdStatus.Text);
        }
        finally { UpdateConnection(); _tdGate.Release(); }
    }
    private async void FdtConnectClick(object sender,RoutedEventArgs e)
    {
        if(_busyScanning || _testRunner.IsRunning || _recorder is not null)
        {Log("正在扫描/执行测试/采集，不能切换转台连接");return;}
        await _fdtGate.WaitAsync();
        try
        {
            if(_fdt?.Connected==true)
            {
                if(SafetyConfirm.IsChecked!=true)
                    throw new InvalidOperationException("温控转台断开前，请先确认现场安全条件");
                if(MessageBox.Show("2FDT 厂商状态码尚未确认能否判断已到位和速度。请先在现场确认两轴已停止。\n是否发送双轴软停车、断使能并关闭串口？",
                    "温控转台断开确认",MessageBoxButton.YesNo,MessageBoxImage.Warning)!=MessageBoxResult.Yes)return;
                await Task.Run(() =>
                {
                    _fdt.StopAxis(0); _fdt.StopAxis(2);
                });
                await Task.Delay(400);
                var check=await Task.Run(_fdt.Read);
                if(!check.Inner.Normal || !check.Outer.Normal)
                    throw new IOException("温控转台状态异常；不能自动视为已安全停车，需现场处理");
                if(MessageBox.Show("已经发送软停车但没有可信速度/到位反馈。确认现场观察到两个轴均已停稳，允许断使能和关闭通讯？",
                    "再次确认实物停止",MessageBoxButton.YesNo,MessageBoxImage.Warning)!=MessageBoxResult.Yes)return;
                await Task.Run(() =>
                {
                    _fdt.DisableAxis(0); _fdt.DisableAxis(2);
                    _fdt.Dispose();
                });
                _fdt=null;
                FdtStatus.Text="温控转台已发送断使能并释放端口（静止状态由现场确认）";
                Log("用户主动断开 2FDT（现场确认停稳）");UpdateConnection();
                return;
            }
            string inner=Selected(FdtInnerPort),outer=Selected(FdtOuterPort);
            if(!_verifiedFdtInner.Contains(inner)||!_verifiedFdtOuter.Contains(outer))
                throw new InvalidOperationException("温控转台内/外轴尚未分别通过状态查询验证，请先扫描");
            var table=new Fdt600(inner,outer);
            try{await Task.Run(table.Connect);_fdt=table;}catch{table.Dispose();throw;}
            FdtStatus.Text="温控转台已连接，自动使能待厂家状态码核实（使用原使能控制）";
            Log($"真实 2FDT 连接成功：{table.Ports}；使能语义仍待核验");UpdateConnection();
        }
        catch(Exception ex){FdtStatus.Text="2FDT 操作失败："+ex.Message;Log(FdtStatus.Text);}
        finally{_fdtGate.Release();}
    }
    private async Task PollAsync()
    {
        if(_busyScanning||_busyPolling)return;
        _busyPolling=true;
        try
        {
            // Idle preview is read-only, at ~1 Hz. It must not compete with a capture or CT-05.
            if(_imu?.Connected==true && _recorder is null && !_testRunner.IsRunning && _activeTest is null)
            {
                try
                {
                    var b=await _imu.ReadBatchAsync(CancellationToken.None,requireSensorOk:false);
                    if(b.FifoUnread>0)
                    {
                        try
                        {
                            var selected=CurrentRunForTests();
                            UpdateLiveRows(Acquisition.PreviewBatch(b,selected));
                        }
                        catch(Exception e)
                        {
                            // Never silently display RAW counts while a selected
                            // calibration mode is invalid or lacks UID confirmation.
                            StreamStatusText.Text="当前选择的补偿模式不可用："+e.Message;
                        }
                    }
                }
                catch(Exception ex){StreamStatusText.Text="实时IMU预览暂停："+ex.Message;}
            }
            if(_td?.Connected==true)
            {
                if(await _tdGate.WaitAsync(0))
                {
                    try
                    {
                        var snapshot=await Task.Run(_td.Read);
                        _latestTdSnapshot = snapshot;
                        TdStatus.Text=_tdDiagnosticOnly
                            ? "仅诊断连接：" + DescribeTdAxis("内轴", snapshot.Inner) + "；" + DescribeTdAxis("外轴", snapshot.Outer)
                            : $"已连接/反馈：内轴 {snapshot.Inner.SpeedDps:F4}°/s，外轴 {snapshot.Outer.SpeedDps:F4}°/s";
                        TdInnerStateText.ToolTip=snapshot.Inner.Detail;
                        TdOuterStateText.ToolTip=snapshot.Outer.Detail;
                        TdInnerStateText.Text=AxisLabel(snapshot.Inner);
                        TdOuterStateText.Text=AxisLabel(snapshot.Outer);
                        TdInnerAngleText.Text=snapshot.Inner.PositionDeg.ToString("+0.0000;-0.0000;0.0000",CultureInfo.InvariantCulture);
                        TdOuterAngleText.Text=snapshot.Outer.PositionDeg.ToString("+0.0000;-0.0000;0.0000",CultureInfo.InvariantCulture);
                    }
                    catch(Exception e){_latestTdSnapshot=null;TdStatus.Text="2TD 反馈异常："+e.Message;}
                    finally{_tdGate.Release();}
                }
            }
            if(_fdt?.Connected==true)
            {
                if(await _fdtGate.WaitAsync(0))
                {
                    try
                    {
                        var snapshot=await Task.Run(_fdt.Read);
                        _latestFdtSnapshot = snapshot;
                        FdtStatus.Text=$"真实反馈 · 内轴 {snapshot.Inner.Detail} / 外轴 {snapshot.Outer.Detail}";
                        FdtInnerStateText.Text=AxisLabel(snapshot.Inner);
                        FdtOuterStateText.Text=AxisLabel(snapshot.Outer);
                        FdtInnerAngleText.Text=snapshot.Inner.PositionDeg.ToString("+0.0000;-0.0000;0.0000",CultureInfo.InvariantCulture);
                        FdtOuterAngleText.Text=snapshot.Outer.PositionDeg.ToString("+0.0000;-0.0000;0.0000",CultureInfo.InvariantCulture);
                    }
                    catch(Exception e){_latestFdtSnapshot=null;FdtStatus.Text="2FDT 反馈异常："+e.Message;}
                    finally{_fdtGate.Release();}
                }
            }
        }
        finally{_busyPolling=false;UpdateConnection();}
    }
    private static string AxisLabel(AxisState a) =>
        $"使能 {(a.EnableVerified is bool en?(en?"是":"否"):"待确认")} / 已到位 {(a.InPlace is bool place?(place?"是":"否"):"待确认")} / {(a.Normal?"正常":"故障/报警")}";
    private static int ControlAxis(object sender)
    {
        if(sender is not Button b || b.Tag is not string tag ||
           !int.TryParse(tag,out int axis) || axis is not (0 or 2))
            throw new InvalidOperationException("控制轴标签必须是0或2");
        return axis;
    }
    private bool ConfirmMovement(string message)
    {
        if(SafetyConfirm.IsChecked!=true)
        {
            MessageBox.Show("先确认：实体急停、机械位置与限位、固定夹具、线缆余量和人员撤离。","安全条件未确认",MessageBoxButton.OK,MessageBoxImage.Warning);
            return false;
        }
        return MessageBox.Show(message+"\n真实转台即将执行运动/使能；软件停车不能替代物理急停。",
            "确认真实硬件操作",MessageBoxButton.YesNo,MessageBoxImage.Warning)==MessageBoxResult.Yes;
    }
    private async Task<bool> Operate(IRealTurntable? table,SemaphoreSlim gate,int axis,
        Action<IRealTurntable,int> op,string name,bool requiresConfirmation)
    {
        try
        {
            if(table?.Connected!=true)throw new InvalidOperationException(name+"未连接");
            if(ReferenceEquals(table,_td) && _tdDiagnosticOnly && !name.Contains("停车"))
                throw new InvalidOperationException("2TD 当前仅可读取状态：尚未确认自动使能，禁止运动/归零/使能。先排查状态报警，现场安全确认后重新连接。");
            if(_testRunner.IsRunning && !name.Contains("停车"))
                throw new InvalidOperationException("自动测试运行中，不允许手动使能或移动。请先停止自动测试。");
            if(requiresConfirmation&&!ConfirmMovement(name+" · "+(axis==0?"内轴":"外轴")))return false;
            await gate.WaitAsync();
            try{await Task.Run(()=>op(table,axis));Log(name+" 命令已发送；是否到位以新的设备反馈为准");}
            finally{gate.Release();}
            return true;
        }
        catch(Exception ex){Log(name+" 操作失败："+ex.Message);MessageBox.Show(ex.Message,"硬件操作失败",MessageBoxButton.OK,MessageBoxImage.Error);return false;}
    }
    private async Task AxisRelative(IRealTurntable? table,SemaphoreSlim gate,int axis,
        TextBox deltaBox,TextBox speedBox,string name)
    {
        try
        {
            double delta=ParseDouble(deltaBox.Text),speed=ParseDouble(speedBox.Text);
            if(!double.IsFinite(delta)||!double.IsFinite(speed)||delta==0||speed<=0)
                throw new InvalidDataException("角度必须为有限非零值；速率须为正值");
            var t=table??throw new IOException(name+"未连接");
            if(ReferenceEquals(t,_td) && _tdDiagnosticOnly)
                throw new IOException("2TD 当前是仅诊断连接，尚未确认安全使能；禁止发送相对运动指令");
            // Fresh feedback, never use a cached UI value to calculate relative movement.
            await gate.WaitAsync();
            TableSnapshot snapshot;
            try{snapshot=await Task.Run(t.Read);}
            finally{gate.Release();}
            double before=(axis==0?snapshot.Inner:snapshot.Outer).PositionDeg;
            double seconds=Math.Abs(delta)/speed; // ideal constant-speed estimate; excludes ramp-up/down
            if(!ConfirmMovement($"{name} {(axis==0?"内轴":"外轴")}：当前反馈角 {before:F4}°；发送相对增量 {delta:+0.####;-0.####;0}°，速率 {speed:F3}°/s。理想匀速用时约 {seconds:F1} 秒（实际含加减速；跨360°使用厂家增量指令）。请核实对应转轴的连续转动与工装、线缆条件。"))return;
            await Operate(table,gate,axis,(obj,a)=>obj.MoveRelative(a,delta,speed),$"{name} 相对运行 {delta:+0.####;-0.####;0}° @ {speed}°/s",false);
        }
        catch(Exception ex){MessageBox.Show(ex.Message,"相对运动参数/安全限制",MessageBoxButton.OK,MessageBoxImage.Warning);}
    }
    private async void TdAxisEnableClick(object sender,RoutedEventArgs e)=>await Operate(_td,_tdGate,ControlAxis(sender),(t,a)=>t.EnableAxis(a),"2TD 使能",true);
    private async void TdAxisDisableClick(object sender,RoutedEventArgs e)=>await Operate(_td,_tdGate,ControlAxis(sender),(t,a)=>t.DisableAxis(a),"2TD 解除使能",true);
    private async void FdtAxisEnableClick(object sender,RoutedEventArgs e)=>await Operate(_fdt,_fdtGate,ControlAxis(sender),(t,a)=>t.EnableAxis(a),"2FDT 使能",true);
    private async void FdtAxisDisableClick(object sender,RoutedEventArgs e)=>await Operate(_fdt,_fdtGate,ControlAxis(sender),(t,a)=>t.DisableAxis(a),"2FDT 解除使能",true);
    private async void TdAxisRelativeClick(object sender,RoutedEventArgs e)
    {
        int a=ControlAxis(sender);
        await AxisRelative(_td,_tdGate,a,a==0?TdInnerDelta:TdOuterDelta,a==0?TdInnerSpeed:TdOuterSpeed,"2TD");
    }
    private async void FdtAxisRelativeClick(object sender,RoutedEventArgs e)
    {
        int a=ControlAxis(sender);
        await AxisRelative(_fdt,_fdtGate,a,a==0?FdtInnerDelta:FdtOuterDelta,a==0?FdtInnerSpeed:FdtOuterSpeed,"2FDT");
    }
    private async void TdAxisStopClick(object sender,RoutedEventArgs e)=>await Operate(_td,_tdGate,ControlAxis(sender),(t,a)=>t.StopAxis(a),"2TD 软停车",false);
    private async void FdtAxisStopClick(object sender,RoutedEventArgs e)=>await Operate(_fdt,_fdtGate,ControlAxis(sender),(t,a)=>t.StopAxis(a),"2FDT 软停车",false);
    private async Task ZeroSelected(IRealTurntable? table,SemaphoreSlim gate,
        bool inner,bool outer,string name,double speed)
    {
        if(!inner&&!outer){MessageBox.Show("请至少选择一个要归零的轴");return;}
        if(name=="2FDT"&&inner&&outer)
        {
            MessageBox.Show("2FDT 厂家状态码尚未映射到“到位”位。暂不允许无等待的双轴连续回零；请逐轴操作并现场核实停止/到位。",
                "温控转台状态反馈未确认",MessageBoxButton.OK,MessageBoxImage.Warning);
            return;
        }
        if(!ConfirmMovement(name+" 将执行绝对零点0°："+(inner?"内轴 ":"")+(outer?"外轴":"")))return;
        // Python V1.4/2TD mechanical constraints: outer must return to zero before changing inner.
        // Do NOT issue a second axis command without verifying the first has actually arrived.
        foreach(int axis in new[]{2,0})
        {
            if(axis==0&&!inner||axis==2&&!outer)continue;
            bool sent=await Operate(table,gate,axis,(t,a)=>t.MoveAbsolute(a,0,speed),name+" 绝对零位命令",false);
            if(!sent)return;
            if(name=="2TD" && table?.Connected==true)
            {
                int count=0;
                var timer=Stopwatch.StartNew();
                while(timer.Elapsed<TimeSpan.FromSeconds(120))
                {
                    await Task.Delay(250);
                    await gate.WaitAsync();
                    TableSnapshot fresh;
                    try{fresh=await Task.Run(table.Read);}
                    finally{gate.Release();}
                    AxisState state=axis==0?fresh.Inner:fresh.Outer;
                    bool ready=state.Normal&&state.InPlace==true&&
                        Math.Abs(state.PositionDeg)<0.1&&Math.Abs(state.SpeedDps)<0.05;
                    count=ready?count+1:0;
                    if(count>=3)break;
                }
                if(count<3)
                {
                    MessageBox.Show(name+" 轴"+axis+" 未获得连续3次归零到位反馈；不向下一轴发指令。请现场核实，必要时使用实体急停。",
                        "归零未确认",MessageBoxButton.OK,MessageBoxImage.Warning);
                    return;
                }
            }
        }
    }
    private async void TdZeroClick(object sender,RoutedEventArgs e)=>await ZeroSelected(_td,_tdGate,TdZeroInner.IsChecked==true,TdZeroOuter.IsChecked==true,"2TD",1);
    private async void FdtZeroClick(object sender,RoutedEventArgs e)=>await ZeroSelected(_fdt,_fdtGate,FdtZeroInner.IsChecked==true,FdtZeroOuter.IsChecked==true,"2FDT",1);
    private async Task StopBoth(IRealTurntable? table,SemaphoreSlim gate,string name)
    {
        if(table?.Connected!=true){Log(name+" 未连接，不能发软停车");return;}
        await gate.WaitAsync();
        try
        {
            foreach(int axis in new[]{0,2})
            {
                try{await Task.Run(()=>table.StopAxis(axis));Log(name+" 轴"+axis+" 软停车已发出");}
                catch(Exception e){Log(name+" 轴"+axis+" 软停车失败："+e.Message);}
            }
        }
        finally{gate.Release();}
    }
    private async void TdStopClick(object sender,RoutedEventArgs e)=>await StopBoth(_td,_tdGate,"2TD");
    private async void FdtStopClick(object sender,RoutedEventArgs e)=>await StopBoth(_fdt,_fdtGate,"2FDT");
    private void UpdateConnection()
    {
        bool imu=_imu?.Connected==true, td=_td?.Connected==true, fdt=_fdt?.Connected==true;
        ConnectionStatus.Text=$"IMU {(imu?"已连接":"离线")} | 2TD {(td?"已连接":"离线")} | 2FDT {(fdt?"已连接":"离线")}";
        if(ImuConnectButton!=null) ImuConnectButton.Content=imu?"断开":"连接 / 读 UID";
        if(TdConnectButton!=null) TdConnectButton.Content=td?"安全断开":"连接";
        if(FdtConnectButton!=null) FdtConnectButton.Content=fdt?"安全断开":"连接";
        if(ImuStateValue is null || TdStateValue is null || FdtStateValue is null) return;

        ImuStateValue.Text=imu?"已连接":"未连接";
        ImuStateDetail.Text=imu ? $"{_imu!.PortName} · {_imu.Identity?.DtsId ?? "UID待确认"}" : "等待 UID";
        ImuStateDot.Fill=imu ? Brushes.SeaGreen : Brushes.LightSlateGray;

        if(!td) _latestTdSnapshot=null;
        bool tdHealthy = td && !_tdDiagnosticOnly && _latestTdSnapshot is { } t &&
                         DateTimeOffset.UtcNow - t.Time < TimeSpan.FromSeconds(4) &&
                         t.Inner.Normal && t.Outer.Normal && t.Inner.Enabled && t.Outer.Enabled;
        TdStateValue.Text=!td?"未连接":_tdDiagnosticOnly?"仅诊断":tdHealthy?"双轴正常":"状态待核实";
        TdStateDetail.Text=td ? (_td?.Ports??"已连接") : "等待串口";
        TdStateDot.Fill=!td?Brushes.LightSlateGray:tdHealthy?Brushes.SeaGreen:Brushes.DarkOrange;

        if(!fdt) _latestFdtSnapshot=null;
        bool fdtFeedbackFresh = _latestFdtSnapshot is { } ft &&
                                DateTimeOffset.UtcNow - ft.Time < TimeSpan.FromSeconds(4);
        FdtStateValue.Text=fdt ? (fdtFeedbackFresh?"状态已更新":"状态待核实") : "未连接";
        FdtStateDetail.Text=fdt ? $"{_fdt?.Ports} · 使能待核验" : "等待内外轴";
        // The 2FDT native state code has not been mapped to trusted enable bits.
        FdtStateDot.Fill=fdt?Brushes.DarkOrange:Brushes.LightSlateGray;
    }
    private static string Selected(ComboBox box)=>box.SelectedItem as string ?? throw new InvalidOperationException("请先自动扫描并选择实际端口");
    private static int ParseInt(string? v,int defaultValue)=>int.TryParse(v,out var n)?n:defaultValue;
    private static double ParseDouble(string? v)=>double.Parse(v??"",CultureInfo.InvariantCulture);
    private void OpenDataClick(object sender,RoutedEventArgs e)
    {
        string path=_saveRoot;
        Directory.CreateDirectory(path);
        Process.Start(new ProcessStartInfo("explorer.exe",$"\"{path}\""){UseShellExecute=true});
    }
    private void OnClosing(object? sender,CancelEventArgs e)
    {
        if(_recorder is not null)
        {
            e.Cancel=true;
            _recorder.Cancel();
            MessageBox.Show("已请求停止真实数据采集。为避免CSV文件及记录丢失，请等采集状态变为已停止后再关闭窗口。",
                "正在保存采集数据",MessageBoxButton.OK,MessageBoxImage.Information);
            return;
        }
        if(_testRunner.IsRunning)
        {
            e.Cancel=true;
            MessageBox.Show("真实测试任务仍在执行；请先在测试子窗口停止并等待双轴停车反馈及检查点保存。",
                "禁止运行中直接退出",MessageBoxButton.OK,MessageBoxImage.Warning);
            return;
        }
        // ClosePort/Dispose only releases serial handles; it is NOT a motor stop.
        if(_td?.Connected==true || _fdt?.Connected==true)
        {
            e.Cancel=true;
            MessageBox.Show("有转台仍处于连接状态。请先按停止、确认实际转速为零，再通过对应页签执行安全断开。关闭WPF窗口不会保证物理轴停车。",
                "请先安全断开转台",MessageBoxButton.OK,MessageBoxImage.Warning);
            return;
        }
        _poll.Stop();
        _recorder?.Cancel();
        _activeTest?.Cancel();
        // Never issue motor commands implicitly on exit; safety relies on physical controller/interlocks.
        _imu?.Dispose();_td?.Dispose();_fdt?.Dispose();
    }
}

public sealed class StageTileGroup(string caption,string summary,IReadOnlyList<TestTileView> tiles)
{
    public string Caption {get;}=caption;
    public string Summary {get;}=summary;
    public IReadOnlyList<TestTileView> Tiles {get;}=tiles;
}
public sealed class TestTileView(TestDefinition definition, ITestModule? module)
{
    public TestDefinition Definition {get;}=definition;
    public string Id=>Definition.Id;
    public string Name=>Definition.Name;
    public string Priority=>Definition.Priority;
    public string Description=>Definition.Purpose+"\n"+Definition.Procedure+"\n"+(module?.ImplementationNote??"无已注册执行类");
    public bool Ready {get;}=module?.IsExecutable==true;
    public string ReadyLabel=>Ready?"● 实测子项":"○ 尚未实现";
    public string ActionLabel=>Ready?"点击真实执行 ›":"查看方案 ›";
    public Brush StatusColor=>Ready?Brushes.ForestGreen:Brushes.Gray;
}
