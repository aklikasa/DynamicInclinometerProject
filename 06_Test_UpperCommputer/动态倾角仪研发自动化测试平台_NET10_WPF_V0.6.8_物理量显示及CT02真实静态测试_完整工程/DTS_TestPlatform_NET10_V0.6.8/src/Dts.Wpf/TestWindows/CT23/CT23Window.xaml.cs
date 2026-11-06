using System.ComponentModel;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using Dts.Core;
using Dts.TestEngine;
using Dts.Tests.S1.CT10;
using Dts.Tests.S1.CT23;

namespace Dts.Wpf.TestWindows.CT23;

[Dts.Wpf.TestWindows.TestWindowFor("CT-23")]
public partial class CT23Window:Window,Dts.Wpf.TestWindows.ICalibrationRunAware
{
    private readonly TestDefinition _definition;
    private readonly ITestModule _module;
    private readonly IStaticAngleHardware _hardware;
    private readonly TestRunner _runner;
    private readonly string _root;
    private CalibrationRun _calibration=CalibrationRun.Raw;
    private CancellationTokenSource? _cts;
    private string? _html;
    private DateTime _startUtc=DateTime.MaxValue;

    public CT23Window(TestDefinition definition,ITestModule module,IStaticAngleHardware hardware,
        TestRunner runner,string outputRoot)
    {
        InitializeComponent();
        _definition=definition;_module=module;_hardware=hardware;_runner=runner;_root=outputRoot;
        RootText.Text=outputRoot;
        UidText.Text=hardware.CurrentIdentity is { } id
            ? $"设备 {id.DtsId}，UID {id.UidHex}，2TD {(hardware.IsTwoTdConnected?"已连接":"未连接")}"
            : "尚未连接真实IMU或未读取完整UID";
        RefreshBridge();RefreshPlan();
    }
    private void RefreshBridge()
    {
        var live=Ct10DynamicBridge.Resolve(_hardware);
        DynamicText.Text=live is null?
            "CT-10动态桥接器没有注册：允许离线预览，禁止旋转实测。":
            live.IsRealDynamicCaptureReady?
                $"动态桥接器已就绪，外轴核验限速：{live.MaximumCertifiedSpeedDps(Ct10Axis.Outer):F3}°/s。注意仅工程级时间诊断。":
                "CT-10真实动态桥接器尚未核验，允许设置参数，但禁止开始实测。";
    }
    public void SetCalibrationRun(CalibrationRun run)
    {
        _calibration=run;
        try
        {
            var id=_hardware.CurrentIdentity??throw new InvalidOperationException("没有连接真实IMU");
            if(run.Mode!=CalibrationMode.Ambient)throw new InvalidOperationException("请先在主窗口选择常温标定");
            run.Validate(id);
            var a=run.Files?.Acc??throw new InvalidDataException("常温ACC标定文件缺失");
            var g=run.Files?.Gyro??throw new InvalidDataException("常温Gyro标定文件缺失");
            CalibrationText.Text=$"ACC：{Path.GetFileName(a.FilePath)}（输入±{a.FsHint}g）\n"+
                $"Gyro：{Path.GetFileName(g.FilePath)}（输入±{g.FsHint}°/s）\n两套矩阵独立、只应用一次。";
        }
        catch(Exception e){CalibrationText.Text="标定尚未就绪："+e.Message;}
        RefreshBridge();
    }
    private static double D(TextBox control)
    {
        if(!double.TryParse(control.Text.Trim(),NumberStyles.Float,CultureInfo.InvariantCulture,out var n)||!double.IsFinite(n))
            throw new InvalidDataException($"参数 {control.Name} 不是有效数值，使用英文小数点");
        return n;
    }
    private static int I(TextBox control)
    {
        if(!int.TryParse(control.Text.Trim(),NumberStyles.Integer,CultureInfo.InvariantCulture,out var n))
            throw new InvalidDataException($"参数 {control.Name} 不是整数");
        return n;
    }
    private Ct23Settings Settings()=>new(_root,TrajectoryInput.Text,D(SpeedInput),D(SetupSpeedInput),
        I(RepeatsInput),D(SettleInput),D(StaticDurationInput),I(MinStaticInput),I(MinDynamicInput),
        D(MaxGapInput),D(MaxSkewInput),D(TravelMinInput),D(TravelMaxInput),
        D(PositionToleranceInput),D(AngleMismatchInput),SafetyCheck.IsChecked==true,
        StopCheck.IsChecked==true,AxesCheck.IsChecked==true,_calibration);
    private void RefreshPlan()
    {
        if(PlanGrid is null||PlanSummary is null||TrajectoryInput is null||SpeedInput is null||RepeatsInput is null)
            return;
        try
        {
            var settings=Settings();var plan=Ct23Algorithm.BuildPlan(settings);
            Ct23Algorithm.Validate(settings,plan,null,false);
            PlanGrid.ItemsSource=plan;
            PlanSummary.Text=$"离线预览：共{plan.Count}次、{plan.Select(x=>x.TrajectoryIndex).Distinct().Count()}条外轴路径；"+
                "每次真实ACC初态采集→Gyro运动积分→停车ACC终态采集。"+
                "当前CT-10接口只能形成外轴可观测子项，不能估计完整3D旋转矩阵。";
        }
        catch(Exception ex){PlanGrid.ItemsSource=null;PlanSummary.Text="参数未通过预览检查："+ex.Message;}
    }
    private void PlanSettingChanged(object sender,TextChangedEventArgs e)=>RefreshPlan();
    private void PreviewClick(object sender,RoutedEventArgs e)
    {
        try
        {
            var settings=Settings();var plan=Ct23Algorithm.BuildPlan(settings);
            Ct23Algorithm.Validate(settings,plan,null,false);
            RefreshBridge();
            MessageBox.Show(this,$"计划共{plan.Count}次自动扫描，实际路径：\n"+
                string.Join("\n",plan.Select(p=>$"#{p.Index}: {p.OuterStartDeg:F2}° → {p.OuterEndDeg:F2}°"))+
                "\n\n此处仅是离线运动计划预览。静态ACC+动态Gyro必须同一UID，运动必须现场核验。",
                "CT-23 扫描计划",MessageBoxButton.OK,MessageBoxImage.Information);
        }
        catch(Exception ex){MessageBox.Show(this,ex.Message,"CT-23设置不合法",MessageBoxButton.OK,MessageBoxImage.Warning);}
    }
    private async void StartClick(object sender,RoutedEventArgs e)
    {
        if(_cts is not null)return;
        try
        {
            if(_module.TestId!="CT-23"||!_module.IsExecutable)
                throw new InvalidOperationException("CT-23测试注册信息不正确");
            var id=_hardware.CurrentIdentity??throw new InvalidOperationException("未连接IMU或读取完整UID");
            if(!_hardware.IsTwoTdConnected)throw new InvalidOperationException("真实2TD未连接");
            if(!Directory.Exists(_root))throw new DirectoryNotFoundException("报告根目录不存在");
            _calibration.Validate(id);
            var s=Settings();var plan=Ct23Algorithm.BuildPlan(s);
            var live=Ct10DynamicBridge.Resolve(_hardware);
            if(live is null)throw new InvalidOperationException("没有注册CT-10真实动态桥接器");
            Ct23Algorithm.Validate(s,plan,live);
            await _hardware.VerifyImuForPrecisionTestAsync(CancellationToken.None);
            var stage=await live.ReadStageAsync(CancellationToken.None);
            if(!stage.InnerEnabled||!stage.OuterEnabled||!stage.InnerNormal||!stage.OuterNormal||
                !stage.InnerStationary||!stage.OuterStationary)
                throw new IOException("启动前双轴不在正常静止且使能状态");
            if(MessageBox.Show(this,$"设备 {id.DtsId} / {id.UidHex}\n"+
                $"共{plan.Count}条真实动态闭合扫描；速度{s.MotionSpeedDps:F2}°/s；"+
                $"允许行程[{s.AllowedMinDeg:F2},{s.AllowedMaxDeg:F2}]°。\n"+
                "此版本仅能诊断外轴单驱动轴闭合，并不能证明完整3D六轴对齐。\n\n"+
                "点击‘是’后将连续自动定位与运动，中途不逐条询问。确认转台现场监护、真实限位、布线与实体急停可用。",
                "CT-23 真机自动测试确认",MessageBoxButton.YesNo,MessageBoxImage.Warning)!=MessageBoxResult.Yes)
                return;
            _cts=new CancellationTokenSource();_startUtc=DateTime.UtcNow;
            _html=null;ReportButton.IsEnabled=false;StartButton.IsEnabled=false;
            StopButton.IsEnabled=true;PreviewButton.IsEnabled=false;RunProgressBar.Value=0;
            ResultGrid.ItemsSource=null;MetricsText.Text="采集中，不自动判PASS";
            var progress=new Progress<string>(text=>
            {
                StatusText.Text=text;
                var m=System.Text.RegularExpressions.Regex.Match(text,@"\[(\d+)/(\d+)\]");
                if(m.Success&&double.TryParse(m.Groups[1].Value,out var a)&&
                   double.TryParse(m.Groups[2].Value,out var b)&&b>0)
                    RunProgressBar.Value=Math.Clamp(a/b*100,0,100);
            });
            var execution=new TestExecutionContext(_definition,TimeSpan.FromSeconds(s.StaticCaptureSeconds),
                _hardware,progress,s);
            var result=await _runner.RunAsync(_module,execution,_cts.Token);
            StatusText.Text=result.Summary;RunProgressBar.Value=100;
            var file=result.Files.FirstOrDefault(f=>f.EndsWith("CT-23_result.json",StringComparison.OrdinalIgnoreCase));
            if(file is not null&&File.Exists(file))ShowReport(file);
        }
        catch(OperationCanceledException)
        {StatusText.Text="取消已发出；测试已请求停车和部分报告，请检查实体转台";LoadPartial();}
        catch(Exception ex)
        {
            StatusText.Text="CT-23未能完成："+ex.Message;LoadPartial();
            MessageBox.Show(this,ex.Message,"CT-23实测中止",MessageBoxButton.OK,MessageBoxImage.Warning);
        }
        finally
        {
            _cts?.Dispose();_cts=null;StartButton.IsEnabled=true;
            StopButton.IsEnabled=false;PreviewButton.IsEnabled=true;RefreshBridge();
        }
    }
    private void ShowReport(string file)
    {
        var d=JsonSerializer.Deserialize<Ct23ReportData>(File.ReadAllText(file))
            ??throw new InvalidDataException("CT-23结果JSON无效");
        ResultGrid.ItemsSource=d.Trials.Select(t=>new{
            t.Index,From=t.OuterStartActualDeg.ToString("F3",CultureInfo.InvariantCulture),
            To=t.OuterEndActualDeg.ToString("F3",CultureInfo.InvariantCulture),
            Closure=t.ClosureAngleDeg.ToString("F5",CultureInfo.InvariantCulture),
            Gyro=t.IntegratedGyroXDeg.ToString("F4",CultureInfo.InvariantCulture),
            Encoder=t.EncoderTravelDeg.ToString("F4",CultureInfo.InvariantCulture),
            Samples=t.DynamicFrames}).ToArray();
        if(d.Metrics is{ } m)
        {
            MetricsText.Text=$"Gyro→ACC重力闭合RMS {m.ClosureRmsDeg:F5}°，"+
                $"最大 {m.ClosureMaxDeg:F5}°，完成{m.CompletedTrials}次；三维相对轴系不可观测。";
            SummaryText.Text=d.State;
        }
        else{MetricsText.Text="没有完整闭合轨迹，已保留可用证据";SummaryText.Text=d.State;}
        _html=Path.Combine(Path.GetDirectoryName(file)!,"CT-23_report.html");
        ReportButton.IsEnabled=File.Exists(_html);ReportText.Text="报告目录："+Path.GetDirectoryName(file);
        ResultTabs.SelectedIndex=1;
    }
    private void LoadPartial()
    {
        try
        {
            var id=_hardware.CurrentIdentity;
            if(id is null||_startUtc==DateTime.MaxValue)return;
            string basePath=Path.Combine(_root,id.DtsId+"_"+id.UidHex);
            if(!Directory.Exists(basePath))return;
            var newest=Directory.EnumerateDirectories(basePath,"*_CT-23")
                .Where(p=>Directory.GetCreationTimeUtc(p)>=_startUtc.AddSeconds(-3))
                .OrderByDescending(Directory.GetCreationTimeUtc).FirstOrDefault();
            string? json=newest is null?null:Path.Combine(newest,"CT-23_result.json");
            if(json is not null&&File.Exists(json))ShowReport(json);
        }
        catch(Exception ex) when(ex is IOException or UnauthorizedAccessException or JsonException)
        {ReportText.Text="部分报告无法在窗口加载："+ex.Message;}
    }
    private void StopClick(object sender,RoutedEventArgs e)
    {
        StatusText.Text="已请求取消，正在尝试双轴软停车；必要时使用实体急停。";
        _cts?.Cancel();
    }
    private void ReportClick(object sender,RoutedEventArgs e)
    {
        if(_html is not null&&File.Exists(_html))
            Process.Start(new ProcessStartInfo(_html){UseShellExecute=true});
    }
    private void CloseClick(object sender,RoutedEventArgs e)=>Close();
    private void OnClosing(object? sender,CancelEventArgs e)
    {
        if(_cts is null)return;
        e.Cancel=true;_cts.Cancel();
        MessageBox.Show(this,"测试仍在运行，已请求软停车，请确认设备停止后再关闭窗口。",
            "CT-23 执行中",MessageBoxButton.OK,MessageBoxImage.Warning);
    }
}
