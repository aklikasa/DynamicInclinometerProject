using System.ComponentModel;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using Dts.Core;
using Dts.TestEngine;
using Dts.Tests.S1.CT16;

namespace Dts.Wpf.TestWindows.CT16;

[Dts.Wpf.TestWindows.TestWindowFor("CT-16")]
public partial class CT16Window : Window,Dts.Wpf.TestWindows.ICalibrationRunAware
{
    private readonly TestDefinition _definition;
    private readonly ITestModule _module;
    private readonly IStaticAngleHardware _hardware;
    private readonly TestRunner _runner;
    private readonly string _root;
    private CalibrationRun _calibration=CalibrationRun.Raw;
    private CancellationTokenSource? _cts;
    private string? _html;
    private DateTime _startedUtc=DateTime.MaxValue;
    public CT16Window(TestDefinition definition,ITestModule module,IStaticAngleHardware hardware,
        TestRunner runner,string outputRoot)
    {
        InitializeComponent();_definition=definition;_module=module;_hardware=hardware;_runner=runner;_root=outputRoot;
        RootText.Text=outputRoot;
        DeviceText.Text=hardware.CurrentIdentity is { } id?
            $"设备 {id.DtsId} / 完整UID {id.UidHex} / 2TD {(hardware.IsTwoTdConnected?"已连接":"未连接")}" :
            "请先连接真实IMU并读取完整UID";
        CalibrationText.Text="等待主窗口传入常温ACC/Gyro标定文件";
        RefreshPlan();
    }
    public void SetCalibrationRun(CalibrationRun run)
    {
        _calibration=run;
        try
        {
            var id=_hardware.CurrentIdentity??throw new InvalidOperationException("未连接IMU/UID缺失");
            if(run.Mode!=CalibrationMode.Ambient)throw new InvalidOperationException("主窗口先选择常温标定");
            run.Validate(id);
            var acc=run.Files?.Acc??throw new InvalidDataException("缺少常温ACC文件");
            var gyro=run.Files?.Gyro??throw new InvalidDataException("缺少常温Gyro文件");
            CalibrationText.Text=$"ACC：{Path.GetFileName(acc.FilePath)}\nGyro：{Path.GetFileName(gyro.FilePath)}\n"+
                $"历史输入量程：ACC ±{acc.FsHint}g / Gyro ±{gyro.FsHint}°/s";
        }
        catch(Exception ex){CalibrationText.Text="标定未就绪："+ex.Message;}
    }
    private static double Double(TextBox input)
    {
        if(!double.TryParse(input.Text.Trim(),NumberStyles.Float,CultureInfo.InvariantCulture,out double v)||
           !double.IsFinite(v))throw new InvalidDataException($"『{input.Name}』须填写有限数字，使用.作为小数点");
        return v;
    }
    private static int Integer(TextBox input)
    {
        if(!int.TryParse(input.Text.Trim(),NumberStyles.Integer,CultureInfo.InvariantCulture,out int v))
            throw new InvalidDataException($"『{input.Name}』须填写整数");
        return v;
    }
    private Ct16Settings Settings()=>new(_root,Double(InnerFixedBox),Double(HomeBox),Double(ExcursionBox),
        SpeedsBox.Text,Integer(RepeatsBox),Double(PrepareSpeedBox),Double(BaselineSecBox),
        Double(RecoverySecBox),Double(BinSecBox),Double(ThresholdBox),Integer(ConsecutiveBox),
        Double(ToleranceBox),Double(AllowedMinBox),Double(AllowedMaxBox),
        Integer(MinFramesBox),PathApproved.IsChecked==true,EStopApproved.IsChecked==true,_calibration);
    private void SettingChanged(object sender,TextChangedEventArgs e)=>RefreshPlan();
    private void RefreshPlan()
    {
        if(PlanGrid is null||PlanSummary is null||SpeedsBox is null||InnerFixedBox is null||HomeBox is null||
            ExcursionBox is null||RepeatsBox is null||ThresholdBox is null||MinFramesBox is null)return;
        try
        {
            var s=Settings();var plan=Ct16Algorithm.BuildPlan(s);Ct16Algorithm.Validate(s,plan,false);
            PlanGrid.ItemsSource=plan;
            PlanSummary.Text=$"计划{plan.Count}组：{Ct16Algorithm.ParseSpeeds(s.SpeedsDps).Length}档速度×正反2向×{s.Repeats}次。"+
                $"固定内轴{s.InnerFixedDeg:F2}°、外轴零位{s.OuterHomeDeg:F2}°、离位幅度±{s.ExcursionDeg:F2}°；"+
                $"每组基线{s.BaselineSeconds:F1}s，停车后恢复{s.RecoverySeconds:F1}s。";
            SummaryText.Text=$"预计{plan.Count}组；参数预览不需要设备已连接。最终报告仅为ACC倾角代理诊断。";
        }
        catch(Exception ex)
        {
            PlanGrid.ItemsSource=null;
            PlanSummary.Text="参数检查："+ex.Message;
        }
    }
    private void PreviewClick(object sender,RoutedEventArgs e)
    {
        try
        {
            var s=Settings();var plan=Ct16Algorithm.BuildPlan(s);Ct16Algorithm.Validate(s,plan,false);
            MessageBox.Show(this,$"{plan.Count}组低速归零诊断\n"+
                $"固定内轴{s.InnerFixedDeg:F2}°，外轴零位{s.OuterHomeDeg:F2}°\n"+
                $"外轴正反离开目标{s.OuterHomeDeg+s.ExcursionDeg:F2}° / {s.OuterHomeDeg-s.ExcursionDeg:F2}°\n"+
                $"速度档位：{s.SpeedsDps}°/s\n单组停车后观察{s.RecoverySeconds:F1}s，恢复阈值{s.RecoveryThresholdDeg:F4}°\n\n"+
                "本预览不证明实际工装与走线安全；开始前必须现场核验。",
                "CT-16 自动动作预览",MessageBoxButton.OK,MessageBoxImage.Information);
        }
        catch(Exception ex){MessageBox.Show(this,ex.Message,"参数无效",MessageBoxButton.OK,MessageBoxImage.Warning);}
    }
    private async void StartClick(object sender,RoutedEventArgs e)
    {
        if(_cts is not null)return;
        try
        {
            var id=_hardware.CurrentIdentity??throw new InvalidOperationException("IMU未连接或UID不可用");
            if(_module.TestId!="CT-16"||!_module.IsExecutable)
                throw new InvalidOperationException("CT-16测试模块未正确注册");
            if(!_hardware.IsTwoTdConnected)throw new InvalidOperationException("双轴2TD未连接");
            if(!Directory.Exists(_root))throw new DirectoryNotFoundException("报告根目录不存在");
            if(_calibration.Mode!=CalibrationMode.Ambient)throw new InvalidOperationException("请先在主窗口选择『常温标定』");
            _calibration.Validate(id);
            var s=Settings();var plan=Ct16Algorithm.BuildPlan(s);Ct16Algorithm.Validate(s,plan);
            await _hardware.VerifyImuForPrecisionTestAsync(CancellationToken.None);
            var feedback=await _hardware.ReadTwoTdAsync(CancellationToken.None);
            if(!feedback.Inner.Normal||!feedback.Outer.Normal||feedback.Inner.Enabled!=true||feedback.Outer.Enabled!=true)
                throw new IOException("真实转台未双轴正常使能");
            if(MessageBox.Show(this,$"设备：{id.DtsId}\n固定内轴：{s.InnerFixedDeg:F2}°\n"+
                $"外轴零位：{s.OuterHomeDeg:F2}°，双侧离位：±{s.ExcursionDeg:F2}°\n"+
                $"速度档位：{s.SpeedsDps}°/s，共{plan.Count}组。\n"+
                $"每组停车后恢复观察：{s.RecoverySeconds:F1}s\n"+
                $"批准行程：{s.AllowedMinDeg:F2}～{s.AllowedMaxDeg:F2}°\n\n"+
                "点击『是』后自动完成所有往返与采集，不再逐轮确认。"+
                "请确认设备、夹具、线缆、实体急停及现场监护。",
                "CT-16 真实运动安全确认",MessageBoxButton.YesNo,MessageBoxImage.Warning)!=MessageBoxResult.Yes)return;
            _cts=new CancellationTokenSource();_startedUtc=DateTime.UtcNow;
            _html=null;ReportButton.IsEnabled=false;StartButton.IsEnabled=false;
            PreviewButton.IsEnabled=false;StopButton.IsEnabled=true;RunProgressBar.Value=0;
            ResultGrid.ItemsSource=null;MetricsText.Text="真实采样执行中；不提前判PASS";
            var progress=new Progress<string>(msg=>
            {
                StatusText.Text=msg;
                var match=System.Text.RegularExpressions.Regex.Match(msg,@"\[(\d+)/(\d+)\]");
                if(match.Success&&int.TryParse(match.Groups[1].Value,out int n)&&
                   int.TryParse(match.Groups[2].Value,out int all)&&all>0)
                    RunProgressBar.Value=Math.Clamp(n*100d/all,0,100);
            });
            var context=new TestExecutionContext(_definition,TimeSpan.FromSeconds(s.BinSeconds),
                _hardware,progress,s);
            var result=await _runner.RunAsync(_module,context,_cts.Token);
            StatusText.Text=result.Summary;RunProgressBar.Value=100;
            var json=result.Files.FirstOrDefault(f=>f.EndsWith("CT-16_result.json",StringComparison.OrdinalIgnoreCase));
            if(json is not null&&File.Exists(json))ShowResult(json);
        }
        catch(OperationCanceledException)
        {
            StatusText.Text="已请求取消和双轴软停车，现场确认安全后查看部分报告";
            TryLoadPartial();
        }
        catch(Exception ex)
        {
            StatusText.Text="CT-16中止："+ex.Message;TryLoadPartial();
            MessageBox.Show(this,ex.Message,"CT-16中止",MessageBoxButton.OK,MessageBoxImage.Warning);
        }
        finally
        {
            _cts?.Dispose();_cts=null;StartButton.IsEnabled=true;
            PreviewButton.IsEnabled=true;StopButton.IsEnabled=false;
        }
    }
    private void ShowResult(string path)
    {
        var data=JsonSerializer.Deserialize<Ct16ReportData>(File.ReadAllText(path))
            ??throw new InvalidDataException("无法读取CT-16结果JSON");
        ResultGrid.ItemsSource=data.Cycles.Select(c=>new
        {
            c.Index,Speed=c.SpeedDps.ToString("F2",CultureInfo.InvariantCulture),c.Direction,
            Peak=c.PeakObservedAfterStopDeg.ToString("F5",CultureInfo.InvariantCulture),
            Final=c.FinalSignedOffsetDeg.ToString("F5",CultureInfo.InvariantCulture),
            Recovery=c.RecoveredBySeconds is double t?t.ToString("F2",CultureInfo.InvariantCulture):"未确认"
        }).ToArray();
        ResultTabs.SelectedIndex=1;
        if(data.Aggregate is { } a)
            MetricsText.Text=$"完成{a.CompletedCycles}组，确认恢复{a.RecoveryObservedCycles}组；"+
                $"最大停车后ACC代理角偏离{a.MaximumObservedPostStopPeakDeg:F5}°。不等于设备融合角恢复。";
        else MetricsText.Text="没有完整恢复周期；仅保存已经完成的真实采样证据";
        SummaryText.Text=$"状态：{data.State}；诊断仅涉及ACC代理角";
        _html=Path.Combine(Path.GetDirectoryName(path)!,"CT-16_report.html");
        ReportButton.IsEnabled=File.Exists(_html);ReportText.Text="报告位置："+_html;
    }
    private void TryLoadPartial()
    {
        try
        {
            var id=_hardware.CurrentIdentity;
            if(id is null||_startedUtc==DateTime.MaxValue)return;
            var root=Path.Combine(_root,id.DtsId+"_"+id.UidHex);
            if(!Directory.Exists(root))return;
            var last=Directory.EnumerateDirectories(root,"*_CT-16")
                .Where(p=>Directory.GetCreationTimeUtc(p)>=_startedUtc.AddSeconds(-4))
                .OrderByDescending(Directory.GetCreationTimeUtc).FirstOrDefault();
            if(last is null)return;
            var file=Path.Combine(last,"CT-16_result.json");
            if(File.Exists(file))ShowResult(file);
        }
        catch(Exception ex) when(ex is IOException or UnauthorizedAccessException or JsonException)
        {ReportText.Text="部分报告读取受限："+ex.Message;}
    }
    private void StopClick(object sender,RoutedEventArgs e)
    {
        StatusText.Text="请求取消；程序将软停车并保留已完成文件，必要时使用实体急停";
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
        MessageBox.Show(this,"CT-16仍在运动或采集，已请求取消和软停车；请等程序完成并确认实体安全后关闭。",
            "正在安全结束",MessageBoxButton.OK,MessageBoxImage.Warning);
    }
}
