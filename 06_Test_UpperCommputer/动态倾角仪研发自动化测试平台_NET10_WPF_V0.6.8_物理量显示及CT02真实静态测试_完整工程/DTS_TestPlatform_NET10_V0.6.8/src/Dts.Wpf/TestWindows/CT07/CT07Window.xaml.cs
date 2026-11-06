using System.ComponentModel;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using Dts.Core;
using Dts.TestEngine;
using Dts.Tests.S1.CT07;

namespace Dts.Wpf.TestWindows.CT07;

[Dts.Wpf.TestWindows.TestWindowFor("CT-07")]
public partial class CT07Window : Window, Dts.Wpf.TestWindows.ICalibrationRunAware
{
    private readonly TestDefinition _definition;
    private readonly ITestModule _module;
    private readonly IStaticAngleHardware _hardware;
    private readonly TestRunner _runner;
    private readonly string _root;
    private CalibrationRun _calibration=CalibrationRun.Raw;
    private CancellationTokenSource? _cts;
    private string? _reportHtml;
    private DateTime _runStartUtc=DateTime.MaxValue;

    // Matches the existing reflection-based TestWindowFor factory; no MainWindow change.
    public CT07Window(TestDefinition definition,ITestModule module,
        IStaticAngleHardware hardware,TestRunner runner,string outputRoot)
    {
        InitializeComponent();
        _definition=definition;_module=module;_hardware=hardware;_runner=runner;_root=outputRoot;
        RootText.Text=outputRoot;
        UidText.Text=hardware.CurrentIdentity is { } id
            ? $"设备 {id.DtsId} / UID {id.UidHex} / 2TD {(hardware.IsTwoTdConnected?"已连接":"未连接")}"
            : "尚未读取真实IMU UID";
        RefreshPlan();
    }
    public void SetCalibrationRun(CalibrationRun run)
    {
        _calibration=run;
        try
        {
            var id=_hardware.CurrentIdentity ?? throw new InvalidOperationException("请先连接IMU并读取完整UID");
            if(run.Mode!=CalibrationMode.Ambient)
                throw new InvalidOperationException("先在主界面选择『常温标定』");
            run.Validate(id);
            var acc=run.Files?.Acc ?? throw new InvalidDataException("缺少ACC常温JSON");
            var gyro=run.Files?.Gyro ?? throw new InvalidDataException("缺少Gyro常温JSON");
            CalibrationText.Text=$"ACC：{Path.GetFileName(acc.FilePath)}\n"+
                $"Gyro：{Path.GetFileName(gyro.FilePath)}\n"+
                $"匹配JSON的输入量程：ACC ±{acc.FsHint}g，Gyro ±{gyro.FsHint}°/s；保留真实原始CSV。";
        }
        catch(Exception ex)
        {
            CalibrationText.Text="标定条件未就绪："+ex.Message;
            StatusText.Text=CalibrationText.Text;
        }
    }
    private static double Number(TextBox box)
    {
        if(!double.TryParse(box.Text.Trim(),NumberStyles.Float,CultureInfo.InvariantCulture,out var value) ||
            !double.IsFinite(value))
            throw new InvalidDataException($"参数『{box.Name}』必须是有限数值，使用.作为小数点");
        return value;
    }
    private static int Integer(TextBox box)
    {
        if(!int.TryParse(box.Text.Trim(),NumberStyles.Integer,CultureInfo.InvariantCulture,out int n))
            throw new InvalidDataException($"参数『{box.Name}』必须是整数");
        return n;
    }
    private Ct07Settings Settings() => new(_root,Number(InnerTarget),Number(OuterTarget),
        Number(InnerDelta),Number(OuterDelta),Integer(RepeatCount),
        AlternateApproach.IsChecked==true,Number(MotionSpeed),Number(SettleSeconds),
        Number(CaptureSeconds),Number(Tolerance),Number(MinTravel),Number(MaxTravel),
        Integer(MinSamples),Number(MaxRejection),DirectionConfirmed.IsChecked==true,
        SafetyConfirmed.IsChecked==true,_calibration);

    private void RefreshPlan()
    {
        if(PlanGrid is null || PlanSummary is null || InnerTarget is null || OuterTarget is null ||
            InnerDelta is null || OuterDelta is null || RepeatCount is null || AlternateApproach is null)
            return;
        try
        {
            var plan=Ct07Algorithm.BuildPlan(Settings());
            PlanGrid.ItemsSource=plan;
            var p=Settings();
            Ct07Algorithm.Validate(p,plan,false);
            PlanSummary.Text=$"{plan.Count}轮，固定目标内轴{p.InnerTargetDeg:F2}° / 外轴{p.OuterTargetDeg:F2}°。"+
                $"离开幅度内±{p.InnerExcursionDeg:F2}°、外±{p.OuterExcursionDeg:F2}°；"+
                (p.AlternateApproach?"回位方向正负交替。":"所有轮次从同一侧回位。")+
                " 每轮都会离位、回位、等待并采样；不是连续静止采样。";
        }
        catch(Exception ex)
        {
            PlanGrid.ItemsSource=null;PlanSummary.Text="扫描参数检查："+ex.Message;
        }
    }
    private void GridSettingChanged(object sender,TextChangedEventArgs e)=>RefreshPlan();
    private void GridCheckChanged(object sender,RoutedEventArgs e)=>RefreshPlan();
    private void PreviewClick(object sender,RoutedEventArgs e)
    {
        try
        {
            var p=Settings();var plan=Ct07Algorithm.BuildPlan(p);
            Ct07Algorithm.Validate(p,plan,false);
            MessageBox.Show(this,$"计划{plan.Count}轮，目标姿态始终为"+
                $"内轴{p.InnerTargetDeg:F2}°、外轴{p.OuterTargetDeg:F2}°。\n"+
                $"第一轮离开位置：内轴{plan[0].InnerDepartDeg:F2}°，外轴{plan[0].OuterDepartDeg:F2}°。\n"+
                $"最后一轮离开位置：内轴{plan[^1].InnerDepartDeg:F2}°，外轴{plan[^1].OuterDepartDeg:F2}°。\n"+
                "软件预览不能证明机械全路径安全：必须核验夹具、线缆、急停与真实限位。",
                "CT-07 扫描预览",MessageBoxButton.OK,MessageBoxImage.Information);
        }
        catch(Exception ex) {MessageBox.Show(this,ex.Message,"CT-07参数错误",MessageBoxButton.OK,MessageBoxImage.Warning);}
    }
    private async void StartClick(object sender,RoutedEventArgs e)
    {
        if(_cts is not null)return;
        try
        {
            var id=_hardware.CurrentIdentity ?? throw new InvalidOperationException("IMU未连接或UID不可用");
            if(!_module.IsExecutable || _module.TestId!="CT-07")
                throw new InvalidOperationException("CT-07模块未正确注册");
            if(!_hardware.IsTwoTdConnected)
                throw new InvalidOperationException("必须先连接并使能真实2TD双轴转台");
            if(!Directory.Exists(_root))throw new DirectoryNotFoundException("报告根目录不存在");
            if(_calibration.Mode!=CalibrationMode.Ambient)
                throw new InvalidOperationException("请先在主窗口选择『常温标定』再打开此窗口");
            _calibration.Validate(id);
            var p=Settings();var plan=Ct07Algorithm.BuildPlan(p);Ct07Algorithm.Validate(p,plan);
            await _hardware.VerifyImuForPrecisionTestAsync(CancellationToken.None);
            var b=await _hardware.ReadTwoTdAsync(CancellationToken.None);
            if(!b.Inner.Normal || !b.Outer.Normal || b.Inner.Enabled!=true || b.Outer.Enabled!=true)
                throw new IOException("转台未处于双轴正常已使能状态");
            if(MessageBox.Show(this,$"设备：{id.DtsId}\n自动重复次数：{p.RepeatCount}轮\n"+
                $"回位目标：内轴{p.InnerTargetDeg:F2}° / 外轴{p.OuterTargetDeg:F2}°\n"+
                $"离开幅度：内轴±{p.InnerExcursionDeg:F2}° / 外轴±{p.OuterExcursionDeg:F2}°\n"+
                $"扫描速度{p.SpeedDps:F2}°/s，静置{p.SettleSeconds:F1}s，每轮采样{p.SampleSeconds:F1}s\n"+
                $"允许行程[{p.AllowedMinDeg:F2},{p.AllowedMaxDeg:F2}]°\n\n"+
                "点击是后将连续自动运动并采样，不再逐轮询问。确认现场监护、急停可用、走线和运动路径安全。",
                "CT-07真实自动测试确认",MessageBoxButton.YesNo,MessageBoxImage.Warning)!=MessageBoxResult.Yes)
                return;
            _cts=new CancellationTokenSource();_runStartUtc=DateTime.UtcNow;
            _reportHtml=null;ReportButton.IsEnabled=false;StartButton.IsEnabled=false;
            PreviewButton.IsEnabled=false;StopButton.IsEnabled=true;RunProgressBar.Value=0;
            ResultGrid.ItemsSource=null;MetricsText.Text="采集中，不提前判PASS";
            var progress=new Progress<string>(message=>
            {
                StatusText.Text=message;
                var match=System.Text.RegularExpressions.Regex.Match(message,@"\[(\d+)/(\d+)\]");
                if(match.Success && int.TryParse(match.Groups[1].Value,out int index) &&
                    int.TryParse(match.Groups[2].Value,out int total) && total>0)
                    RunProgressBar.Value=Math.Clamp(index*100d/total,0,100);
            });
            var context=new TestExecutionContext(_definition,TimeSpan.FromSeconds(p.SampleSeconds),
                _hardware,progress,p);
            var result=await _runner.RunAsync(_module,context,_cts.Token);
            StatusText.Text=result.Summary;RunProgressBar.Value=100;
            string? json=result.Files.FirstOrDefault(x=>x.EndsWith("CT-07_result.json",StringComparison.OrdinalIgnoreCase));
            if(json is not null && File.Exists(json))ShowResult(json);
        }
        catch(OperationCanceledException)
        {
            StatusText.Text="已取消，正在处理软停车及部分报告，请检查现场实际状态";
            LoadPartial();
        }
        catch(Exception ex)
        {
            StatusText.Text="CT-07测试中止："+ex.Message;LoadPartial();
            MessageBox.Show(this,ex.Message,"CT-07 中止",MessageBoxButton.OK,MessageBoxImage.Warning);
        }
        finally
        {
            _cts?.Dispose();_cts=null;StartButton.IsEnabled=true;
            PreviewButton.IsEnabled=true;StopButton.IsEnabled=false;
        }
    }
    private void ShowResult(string file)
    {
        var data=JsonSerializer.Deserialize<Ct07ReportData>(File.ReadAllText(file))
            ?? throw new InvalidDataException("CT-07报告JSON无法反序列化");
        ResultGrid.ItemsSource=data.Visits.Select(v=>new
        {
            v.Index,Inner=v.InnerActualDeg.ToString("F4",CultureInfo.InvariantCulture),
            Outer=v.OuterActualDeg.ToString("F4",CultureInfo.InvariantCulture),
            Ax=v.AccCorrectedMeanG[0].ToString("F5",CultureInfo.InvariantCulture),
            Ay=v.AccCorrectedMeanG[1].ToString("F5",CultureInfo.InvariantCulture),
            Az=v.AccCorrectedMeanG[2].ToString("F5",CultureInfo.InvariantCulture),
            ErrorMg=v.VectorReferenceErrorMg.ToString("F3",CultureInfo.InvariantCulture),
            Samples=v.AcceptedSamples
        }).ToArray();
        if(data.Metrics is { } m)
        {
            MetricsText.Text=$"跨轮ACC矢量离散RMS：{m.AccBetweenVectorRmsMg:F3} mg　"+
                $"角度离散RMS：{m.DirectionBetweenRmsDeg:F5}°\n"+
                $"内/外轴回位标准差：{m.InnerReturnStdDeg:F5}° / {m.OuterReturnStdDeg:F5}°；"+
                $"有效真实帧：{m.AcceptedFrames}。";
            SummaryText.Text=$"状态：{data.State}，完成{m.Visits}轮，研发待验收";
        }
        else {MetricsText.Text="完成轮次不足以统计跨轮重复性";SummaryText.Text=data.State;}
        ResultTabs.SelectedIndex=1;
        _reportHtml=Path.Combine(Path.GetDirectoryName(file)!,"CT-07_report.html");
        ReportButton.IsEnabled=File.Exists(_reportHtml);ReportText.Text="已存报告："+_reportHtml;
    }
    private void LoadPartial()
    {
        try
        {
            var id=_hardware.CurrentIdentity;
            if(id is null || _runStartUtc==DateTime.MaxValue)return;
            string folder=Path.Combine(_root,id.DtsId+"_"+id.UidHex);
            if(!Directory.Exists(folder))return;
            var latest=Directory.EnumerateDirectories(folder,"*_CT-07")
                .Where(path=>Directory.GetCreationTimeUtc(path)>=_runStartUtc.AddSeconds(-3))
                .OrderByDescending(Directory.GetCreationTimeUtc).FirstOrDefault();
            if(latest is null)return;
            var file=Path.Combine(latest,"CT-07_result.json");
            if(File.Exists(file))ShowResult(file);
        }
        catch(Exception ex) when(ex is IOException or UnauthorizedAccessException or JsonException)
        {ReportText.Text="部分报告暂无法预览，请查看报告根目录："+ex.Message;}
    }
    private void StopClick(object sender,RoutedEventArgs e)
    {
        StatusText.Text="已请求取消。软件将尝试双轴软停车并输出已完成轮次；必要时使用实体急停";
        _cts?.Cancel();
    }
    private void ReportClick(object sender,RoutedEventArgs e)
    {
        if(_reportHtml is not null && File.Exists(_reportHtml))
            Process.Start(new ProcessStartInfo(_reportHtml){UseShellExecute=true});
    }
    private void CloseClick(object sender,RoutedEventArgs e)=>Close();
    private void OnClosing(object? sender,CancelEventArgs e)
    {
        if(_cts is null)return;
        e.Cancel=true;_cts.Cancel();
        MessageBox.Show(this,"测试仍在运行，已请求取消和软停车。请等任务结束并确认实体安全后关闭窗口。",
            "CT-07 正在结束",MessageBoxButton.OK,MessageBoxImage.Warning);
    }
}
