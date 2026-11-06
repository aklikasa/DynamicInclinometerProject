using System.ComponentModel;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using Dts.Core;
using Dts.TestEngine;
using Dts.Tests.S1.CT08;

namespace Dts.Wpf.TestWindows.CT08;

[Dts.Wpf.TestWindows.TestWindowFor("CT-08")]
public partial class CT08Window : Window,Dts.Wpf.TestWindows.ICalibrationRunAware
{
    private readonly TestDefinition _definition;
    private readonly ITestModule _module;
    private readonly IStaticAngleHardware _hardware;
    private readonly TestRunner _runner;
    private readonly string _outputRoot;
    private CalibrationRun _calibration=CalibrationRun.Raw;
    private CancellationTokenSource? _cts;
    private string? _reportHtml;
    private DateTime _runStartUtc=DateTime.MaxValue;

    public CT08Window(TestDefinition definition,ITestModule module,
        IStaticAngleHardware hardware,TestRunner runner,string outputRoot)
    {
        InitializeComponent();
        _definition=definition;_module=module;_hardware=hardware;_runner=runner;_outputRoot=outputRoot;
        RootText.Text=outputRoot;
        UidText.Text=hardware.CurrentIdentity is { } id
            ? $"设备 {id.DtsId} / UID {id.UidHex} / 2TD {(hardware.IsTwoTdConnected?"已连接":"未连接")}"
            : "还未读取真实IMU UID";
        RefreshPlan();
    }
    public void SetCalibrationRun(CalibrationRun run)
    {
        _calibration=run;
        try
        {
            var id=_hardware.CurrentIdentity??throw new InvalidOperationException("先连接真实IMU并读取UID");
            if(run.Mode!=CalibrationMode.Ambient)
                throw new InvalidOperationException("主窗口应选择常温标定");
            run.Validate(id);
            var acc=run.Files?.Acc??throw new InvalidDataException("缺少ACC JSON");
            var gyro=run.Files?.Gyro??throw new InvalidDataException("缺少Gyro JSON");
            CalibrationText.Text=$"ACC：{Path.GetFileName(acc.FilePath)}\n"+
                $"Gyro：{Path.GetFileName(gyro.FilePath)}\n"+
                $"历史输入量程：ACC ±{acc.FsHint}g / Gyro ±{gyro.FsHint}°/s；严格按JSON配套换算。";
        }
        catch(Exception ex)
        {
            CalibrationText.Text="常温标定条件未就绪："+ex.Message;
            StatusText.Text=CalibrationText.Text;
        }
    }
    private static double Number(TextBox box)
    {
        if(!double.TryParse(box.Text.Trim(),NumberStyles.Float,CultureInfo.InvariantCulture,out var v)||
            !double.IsFinite(v))throw new InvalidDataException("参数『"+box.Name+"』不是有效有限数字（小数点用.）");
        return v;
    }
    private static int Integer(TextBox box)
    {
        if(!int.TryParse(box.Text.Trim(),NumberStyles.Integer,CultureInfo.InvariantCulture,out var v))
            throw new InvalidDataException("参数『"+box.Name+"』必须是整数");
        return v;
    }
    private Ct08Settings Settings()=>new(_outputRoot,InnerPositions.Text.Trim(),OuterTargets.Text.Trim(),
        Number(ApproachOffset),Integer(PairRepeat),Number(MotionSpeed),Number(SettleSeconds),
        Number(SampleSeconds),Number(Tolerance),Number(MinTravel),Number(MaxTravel),
        Integer(MinSamples),Number(MaxRejection),DirectionConfirmed.IsChecked==true,
        SafetyConfirmed.IsChecked==true,_calibration);

    private void RefreshPlan()
    {
        if(PlanGrid is null||PlanSummary is null||InnerPositions is null||OuterTargets is null||
           PairRepeat is null||ApproachOffset is null||DirectionConfirmed is null||SafetyConfirmed is null)
            return;
        try
        {
            var settings=Settings();var plan=Ct08Algorithm.BuildPlan(settings);
            Ct08Algorithm.Validate(settings,plan,false);
            PlanGrid.ItemsSource=plan;
            PlanSummary.Text=$"{Ct08Algorithm.ParseAngles(settings.InnerPositionsText,"内轴").Length} 个内轴姿态 × " +
                $"{Ct08Algorithm.ParseAngles(settings.OuterTargetsText,"外轴").Length} 个外轴目标 × " +
                $"{settings.PairsPerTarget}对 = {plan.Count/2} 对、{plan.Count}站真实采样。"+
                "每轮正反顺序交替，避免将缓慢温漂直接当作回程差。";
            SummaryText.Text=PlanSummary.Text;
        }
        catch(Exception ex)
        {
            PlanGrid.ItemsSource=null;PlanSummary.Text="参数预检查："+ex.Message;
        }
    }
    private void SettingChanged(object sender,TextChangedEventArgs e)=>RefreshPlan();
    private void PreviewClick(object sender,RoutedEventArgs e)
    {
        try
        {
            var s=Settings();var plan=Ct08Algorithm.BuildPlan(s);
            Ct08Algorithm.Validate(s,plan,false);
            MessageBox.Show(this,$"计划 {plan.Count/2} 正反配对，{plan.Count} 次真实采样。\n"+
                $"第一站内轴 {plan[0].InnerTargetDeg:F2}°，外轴从 {plan[0].OuterDepartDeg:F2}° 到 {plan[0].OuterTargetDeg:F2}°。\n"+
                $"最后一站内轴 {plan[^1].InnerTargetDeg:F2}°，外轴从 {plan[^1].OuterDepartDeg:F2}° 到 {plan[^1].OuterTargetDeg:F2}°。\n"+
                "预览不等于机械路径安全验证；严禁无人监护进行自动运动。",
                "CT-08 扫描预览",MessageBoxButton.OK,MessageBoxImage.Information);
        }
        catch(Exception ex)
        {MessageBox.Show(this,ex.Message,"CT-08参数错误",MessageBoxButton.OK,MessageBoxImage.Warning);}
    }
    private async void StartClick(object sender,RoutedEventArgs e)
    {
        if(_cts is not null)return;
        try
        {
            var id=_hardware.CurrentIdentity??throw new InvalidOperationException("IMU未连接或没有真实UID");
            if(!_module.IsExecutable||_module.TestId!="CT-08")
                throw new InvalidOperationException("CT-08执行模块未正确注册");
            if(!_hardware.IsTwoTdConnected)
                throw new InvalidOperationException("2TD双轴转台没有连接并确认使能");
            if(!Directory.Exists(_outputRoot))throw new DirectoryNotFoundException("报告根目录不存在");
            if(_calibration.Mode!=CalibrationMode.Ambient)
                throw new InvalidOperationException("在主界面勾选常温标定后重新打开CT-08");
            _calibration.Validate(id);
            var s=Settings();var plan=Ct08Algorithm.BuildPlan(s);Ct08Algorithm.Validate(s,plan);
            await _hardware.VerifyImuForPrecisionTestAsync(CancellationToken.None);
            var state=await _hardware.ReadTwoTdAsync(CancellationToken.None);
            if(!state.Inner.Normal||!state.Outer.Normal||state.Inner.Enabled!=true||state.Outer.Enabled!=true)
                throw new IOException("转台两轴没有正常使能");
            if(MessageBox.Show(this,$"设备：{id.DtsId}\n正反配对：{plan.Count/2} 对 / {plan.Count} 次采样\n"+
                $"外轴从每个目标 ±{s.ApproachOffsetDeg:F2}° 接近，内轴按设定角度自动换位。\n"+
                $"速度 {s.SpeedDps:F2}°/s，静置 {s.SettleSeconds:F1}s，每次采集{s.SampleSeconds:F1}s。\n"+
                $"批准行程[{s.AllowedMinDeg:F2},{s.AllowedMaxDeg:F2}]°\n\n"+
                "确认现场人员监护、夹具线缆、限位、急停可用。选择“是”后不会每站重复弹出操作请求。",
                "CT-08 真实自动测试确认",MessageBoxButton.YesNo,MessageBoxImage.Warning)!=MessageBoxResult.Yes)
                return;
            _cts=new CancellationTokenSource();_runStartUtc=DateTime.UtcNow;
            _reportHtml=null;ReportButton.IsEnabled=false;StartButton.IsEnabled=false;
            PreviewButton.IsEnabled=false;StopButton.IsEnabled=true;RunProgressBar.Value=0;
            ResultGrid.ItemsSource=null;MetricsText.Text="正在真实采样；不提前判合格";
            var progress=new Progress<string>(msg=>
            {
                StatusText.Text=msg;
                var match=System.Text.RegularExpressions.Regex.Match(msg,@"\[(\d+)/(\d+)\]");
                if(match.Success&&int.TryParse(match.Groups[1].Value,out int index)&&
                   int.TryParse(match.Groups[2].Value,out int total)&&total>0)
                    RunProgressBar.Value=Math.Clamp(index*100d/total,0,100);
            });
            var context=new TestExecutionContext(_definition,TimeSpan.FromSeconds(s.SampleSeconds),
                _hardware,progress,s);
            var result=await _runner.RunAsync(_module,context,_cts.Token);
            StatusText.Text=result.Summary;RunProgressBar.Value=100;
            var json=result.Files.FirstOrDefault(p=>p.EndsWith("CT-08_result.json",StringComparison.OrdinalIgnoreCase));
            if(json is not null&&File.Exists(json))ShowResult(json);
        }
        catch(OperationCanceledException)
        {StatusText.Text="取消已请求。检查双轴停车与现场安全；保留已有记录。";LoadPartial();}
        catch(Exception ex)
        {
            StatusText.Text="CT-08中止："+ex.Message;
            LoadPartial();MessageBox.Show(this,ex.Message,"CT-08测试中止",MessageBoxButton.OK,MessageBoxImage.Warning);
        }
        finally
        {
            _cts?.Dispose();_cts=null;StartButton.IsEnabled=true;
            PreviewButton.IsEnabled=true;StopButton.IsEnabled=false;
        }
    }
    private void ShowResult(string file)
    {
        var data=JsonSerializer.Deserialize<Ct08ReportData>(File.ReadAllText(file))
            ??throw new InvalidDataException("CT-08结果JSON不可读取");
        ResultGrid.ItemsSource=data.Pairs.Select(p=>new
        {
            Pair=p.PairIndex,Inner=p.InnerTargetDeg.ToString("F3",CultureInfo.InvariantCulture),
            Outer=p.OuterTargetDeg.ToString("F3",CultureInfo.InvariantCulture),
            Dx=p.HysteresisErrorMg[0].ToString("F4",CultureInfo.InvariantCulture),
            Dy=p.HysteresisErrorMg[1].ToString("F4",CultureInfo.InvariantCulture),
            Dz=p.HysteresisErrorMg[2].ToString("F4",CultureInfo.InvariantCulture),
            Magnitude=p.HysteresisMagnitudeMg.ToString("F3",CultureInfo.InvariantCulture),
            Feedback=p.OuterActualDifferenceDeg.ToString("F5",CultureInfo.InvariantCulture)
        }).ToArray();
        if(data.Metrics is { } m)
        {
            MetricsText.Text=$"ACC路径残差差 RMS：{m.RmsHysteresisMg:F3}mg；"+
                $"最大：{m.MaxHysteresisMg:F3}mg；方向差均值：{m.MeanDirectionHysteresisDeg:F5}°\n"+
                $"外轴实际反馈差 RMS：{m.OuterFeedbackDifferenceRmsDeg:F5}°；"+
                $"完成{m.CompletedPairs}对，真实有效帧{m.AcceptedFrames}。";
            SummaryText.Text=$"{data.State}；完成{m.CompletedPairs}对，研发待验收";
        }
        else
        {MetricsText.Text="没有完整正反配对，已保存部分真实采样";SummaryText.Text=data.State;}
        ResultTabs.SelectedIndex=1;
        _reportHtml=Path.Combine(Path.GetDirectoryName(file)!,"CT-08_report.html");
        ReportButton.IsEnabled=File.Exists(_reportHtml);ReportText.Text="报告路径："+_reportHtml;
    }
    private void LoadPartial()
    {
        try
        {
            var id=_hardware.CurrentIdentity;
            if(id is null||_runStartUtc==DateTime.MaxValue)return;
            string folder=Path.Combine(_outputRoot,id.DtsId+"_"+id.UidHex);
            if(!Directory.Exists(folder))return;
            var latest=Directory.EnumerateDirectories(folder,"*_CT-08")
                .Where(p=>Directory.GetCreationTimeUtc(p)>=_runStartUtc.AddSeconds(-3))
                .OrderByDescending(Directory.GetCreationTimeUtc).FirstOrDefault();
            if(latest is null)return;
            string file=Path.Combine(latest,"CT-08_result.json");
            if(File.Exists(file))ShowResult(file);
        }
        catch(Exception ex) when(ex is IOException or UnauthorizedAccessException or JsonException)
        {ReportText.Text="暂无法预览部分报告："+ex.Message;}
    }
    private void StopClick(object sender,RoutedEventArgs e)
    {StatusText.Text="已请求取消与双轴软停车；必要时用实体急停";_cts?.Cancel();}
    private void ReportClick(object sender,RoutedEventArgs e)
    {if(_reportHtml is not null&&File.Exists(_reportHtml))
        Process.Start(new ProcessStartInfo(_reportHtml){UseShellExecute=true});}
    private void CloseClick(object sender,RoutedEventArgs e)=>Close();
    private void OnClosing(object? sender,CancelEventArgs e)
    {
        if(_cts is null)return;
        e.Cancel=true;_cts.Cancel();
        MessageBox.Show(this,"CT-08正在取消并尝试双轴停车，必须现场确认安全后再关闭窗口。",
            "CT-08测试运行中",MessageBoxButton.OK,MessageBoxImage.Warning);
    }
}
