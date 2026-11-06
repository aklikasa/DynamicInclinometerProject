using System.ComponentModel;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using Dts.Core;
using Dts.TestEngine;
using Dts.Tests.S1.CT25;

namespace Dts.Wpf.TestWindows.CT25;

[Dts.Wpf.TestWindows.TestWindowFor("CT-25")]
public partial class CT25Window:Window,Dts.Wpf.TestWindows.ICalibrationRunAware
{
    private readonly TestDefinition _definition;
    private readonly ITestModule _module;
    private readonly IStaticAngleHardware _hardware;
    private readonly TestRunner _runner;
    private readonly string _root;
    private CalibrationRun _calibration=CalibrationRun.Raw;
    private CancellationTokenSource? _cts;
    private string? _html;

    public CT25Window(TestDefinition definition,ITestModule module,
        IStaticAngleHardware hardware,TestRunner runner,string outputRoot)
    {
        InitializeComponent();
        _definition=definition;_module=module;_hardware=hardware;_runner=runner;_root=outputRoot;
        RootText.Text="报告根目录："+outputRoot;
        UidText.Text=hardware.CurrentIdentity is { } id
            ? $"设备：{id.DtsId} / 完整UID：{id.UidHex} / 双轴2TD：{(hardware.IsTwoTdConnected?"已连接":"未连接")}"
            : "尚未读取完整设备UID；可以先离线预览参数。";
        RefreshBridge();RefreshPlan();
    }
    public void SetCalibrationRun(CalibrationRun run)
    {
        _calibration=run;
        try
        {
            var id=_hardware.CurrentIdentity??throw new InvalidOperationException("尚未连接真实IMU");
            if(run.Mode!=CalibrationMode.Ambient)throw new InvalidOperationException("须选择常温模型");
            run.Validate(id);
            var acc=run.Files?.Acc??throw new InvalidDataException("没有常温ACC标定JSON");
            var gyro=run.Files?.Gyro??throw new InvalidDataException("没有常温Gyro标定JSON");
            CalibrationText.Text=$"常温ACC：{Path.GetFileName(acc.FilePath)}\n"+
                $"常温Gyro：{Path.GetFileName(gyro.FilePath)}\n"+
                "本项目直接读取设备融合倾角；不得用原始ACC或Gyro离线代替。";
        }
        catch(Exception ex){CalibrationText.Text="常温标定待就绪："+ex.Message;}
        RefreshBridge();
    }
    private void RefreshBridge()
    {
        var provider=Ct25DynamicBridge.Resolve(_hardware);
        BridgeStatus.Text=provider is null?
            "真实正弦运动和融合倾角适配器未接入：当前仅能预览计划，禁止自动实测。":
            provider.IsReadyForTrueSineAndFusedTilt?
                "动态融合角接口已宣告就绪。开始前仍核验实际转台认证能力、时标、标定与急停。来源："+provider.SourceDescription:
                "适配器存在但未完成真实正弦/设备融合倾角同步核验，仅能离线预览。";
    }
    private static double D(TextBox t)
    {
        if(!double.TryParse(t.Text.Trim(),NumberStyles.Float,CultureInfo.InvariantCulture,out double v)||
            !double.IsFinite(v))throw new InvalidDataException("参数"+t.Name+"须为有限数字，小数点用英文句点");
        return v;
    }
    private static int I(TextBox t)
    {
        if(!int.TryParse(t.Text.Trim(),NumberStyles.Integer,CultureInfo.InvariantCulture,out int n))
            throw new InvalidDataException("参数"+t.Name+"须为整数");
        return n;
    }
    private Ct25Settings Settings()=>new(_root,AmplitudesInput.Text,FrequenciesInput.Text,
        TestX.IsChecked==true,TestY.IsChecked==true,I(CyclesInput),I(RepeatsInput),
        D(InnerCenterInput),D(OuterCenterInput),D(MinTravelInput),D(MaxTravelInput),
        D(SetupSpeedInput),D(SettleInput),D(RecoveryInput),D(ClockErrorInput),
        D(MaxGapInput),I(MinFramesInput),D(EncoderR2Input),D(AmplitudeToleranceInput),
        I(SignXInput),I(SignYInput),SafetyCheck.IsChecked==true,
        EstopCheck.IsChecked==true,MappingCheck.IsChecked==true,_calibration);
    private void RefreshPlan()
    {
        if(PlanGrid is null||PlanSummary is null||AmplitudesInput is null||FrequenciesInput is null||
            TestX is null||TestY is null||CyclesInput is null||RepeatsInput is null)return;
        try
        {
            var s=Settings();
            var source=Ct25DynamicBridge.Resolve(_hardware);
            var plan=Ct25Algorithm.BuildPlan(s,source?.IsReadyForTrueSineAndFusedTilt==true?source:null);
            Ct25Algorithm.Validate(s,plan,false);
            PlanGrid.ItemsSource=plan;
            int good=plan.Count(p=>p.Eligible);
            PlanSummary.Text=$"离线预览：{plan.Count}个组合，{good}个候选，{plan.Count-good}个标记超限；"+
                $"预计稳态正弦总时长{plan.Sum(p=>p.DurationSeconds)/60:F1}分钟。"+
                " 没有认证设备适配器时，只显示数学/行程候选，尚未按硬件速度与加速度过滤。";
        }
        catch(Exception ex){PlanGrid.ItemsSource=null;PlanSummary.Text="幅频参数："+ex.Message;}
    }
    private void OptionsTextChanged(object sender,TextChangedEventArgs e)=>RefreshPlan();
    private void OptionsChanged(object sender,RoutedEventArgs e)=>RefreshPlan();
    private void PreviewClick(object sender,RoutedEventArgs e)
    {
        try
        {
            RefreshBridge();RefreshPlan();
            var s=Settings();var device=Ct25DynamicBridge.Resolve(_hardware);
            var plan=Ct25Algorithm.BuildPlan(s,device?.IsReadyForTrueSineAndFusedTilt==true?device:null);
            Ct25Algorithm.Validate(s,plan,false);
            MessageBox.Show(this,$"共{plan.Count}个幅频组合；"+
                $"X轴={(s.TestX?"开启":"关闭")}，Y轴={(s.TestY?"开启":"关闭")}。"+
                $"\n每档{s.Cycles}周期，计划稳态采集{plan.Sum(p=>p.DurationSeconds)/60:F1}分钟。\n"+
                "速度峰值=2πfA，加速度峰值=(2πf)²A。\n"+
                "实际运动须有经验证的2TD正弦运动接口、设备融合倾角输出及共同时基。\n"+
                "仅能预览不能代表设备已经可安全执行。",
                "CT-25 幅频计划预览",MessageBoxButton.OK,MessageBoxImage.Information);
        }
        catch(Exception ex){MessageBox.Show(this,ex.Message,"参数检查失败",MessageBoxButton.OK,MessageBoxImage.Warning);}
    }
    private async void StartClick(object sender,RoutedEventArgs e)
    {
        if(_cts is not null)return;
        try
        {
            if(_module.TestId!="CT-25"||!_module.IsExecutable)
                throw new InvalidOperationException("CT-25测试入口未正确注册");
            var device=Ct25DynamicBridge.Resolve(_hardware);
            if(device is null||!device.IsReadyForTrueSineAndFusedTilt)
                throw new NotSupportedException("尚未接入可靠的真实正弦运动及设备融合倾角时间对齐适配器。禁止开始实测；可先预览参数。详见包内README。");
            var id=_hardware.CurrentIdentity??throw new InvalidOperationException("真实IMU尚未连接/获取UID");
            if(!_hardware.IsTwoTdConnected)throw new InvalidOperationException("真实2TD双轴未连接");
            _calibration.Validate(id);
            if(_calibration.Mode!=CalibrationMode.Ambient)throw new InvalidOperationException("须先选择常温标定模型");
            var s=Settings();var plan=Ct25Algorithm.BuildPlan(s,device);
            Ct25Algorithm.Validate(s,plan);
            if(!plan.Any(p=>p.Eligible))throw new InvalidOperationException("没有通过机械和设备认证能力筛选的测试组合");
            if(!Directory.Exists(_root))throw new DirectoryNotFoundException("报告根目录不存在："+_root);
            await _hardware.VerifyImuForPrecisionTestAsync(CancellationToken.None);
            if(MessageBox.Show(this,$"设备：{id.DtsId} / {id.UidHex}\n"+
                $"共{plan.Count(p=>p.Eligible)}项自动测试，{plan.Count(p=>!p.Eligible)}项超限跳过。\n"+
                $"X/Y真实正弦，幅值 {s.AmplitudesCsv}°，频率 {s.FrequenciesCsv}Hz。\n"+
                "使用设备真实融合倾角，采集真实2TD编码器，进行时标同步与幅相比较。\n\n"+
                "点击‘是’后连续运动不再逐档询问。必须现场监护，确认硬件限位、线缆和实体急停！",
                "CT-25 实际运动确认",MessageBoxButton.YesNo,MessageBoxImage.Warning)!=MessageBoxResult.Yes)
                return;
            _cts=new CancellationTokenSource();StartButton.IsEnabled=false;StopButton.IsEnabled=true;
            PreviewButton.IsEnabled=false;Progress.Value=0;ReportButton.IsEnabled=false;_html=null;
            ResultGrid.ItemsSource=null;MetricsText.Text="正在等待真实融合角/2TD同步数据，尚不生成任何虚构结果";
            var progress=new Progress<string>(m=>
            {
                StatusText.Text=m;
                var match=System.Text.RegularExpressions.Regex.Match(m,@"\[(\d+)/(\d+)\]");
                if(match.Success&&double.TryParse(match.Groups[1].Value,out var n)&&
                    double.TryParse(match.Groups[2].Value,out var total)&&total>0)
                    Progress.Value=Math.Clamp(n/total*100,0,100);
            });
            var ctx=new TestExecutionContext(_definition,TimeSpan.FromSeconds(s.Cycles/0.05),_hardware,progress,s);
            var result=await _runner.RunAsync(_module,ctx,_cts.Token);
            StatusText.Text=result.Summary;Progress.Value=100;
            string? json=result.Files.FirstOrDefault(p=>p.EndsWith("CT-25_result.json",StringComparison.OrdinalIgnoreCase));
            if(json is not null&&File.Exists(json))ShowReport(json);
        }
        catch(OperationCanceledException){StatusText.Text="用户取消；请确认转台实际静止及报告目录";}
        catch(Exception ex)
        {
            StatusText.Text="CT-25不可实测/中止："+ex.Message;
            MessageBox.Show(this,ex.Message,"CT-25未启动或中止",MessageBoxButton.OK,MessageBoxImage.Warning);
        }
        finally
        {
            _cts?.Dispose();_cts=null;StartButton.IsEnabled=true;
            StopButton.IsEnabled=false;PreviewButton.IsEnabled=true;
        }
    }
    private void ShowReport(string path)
    {
        var data=JsonSerializer.Deserialize<Ct25ReportData>(File.ReadAllText(path))
            ??throw new InvalidDataException("CT-25报告JSON为空");
        ResultGrid.ItemsSource=data.Results;
        ResultTabs.SelectedIndex=1;
        MetricsText.Text=$"状态：{data.State}，完成真实正弦/融合倾角分析{data.Results.Count}项；产品级PASS尚未判断。";
        _html=Path.Combine(Path.GetDirectoryName(path)!,"CT-25_report.html");
        ReportText.Text="报告目录："+Path.GetDirectoryName(path);
        ReportButton.IsEnabled=File.Exists(_html);
    }
    private void StopClick(object sender,RoutedEventArgs e)
    {
        _cts?.Cancel();StatusText.Text="已请求取消，测试模块会尝试双轴软停车；必要时使用实体急停";
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
        MessageBox.Show(this,"测试尚在执行，已请求取消。必须确认真实双轴安全静止后才能关闭。",
            "CT-25 正在停止",MessageBoxButton.OK,MessageBoxImage.Warning);
    }
}
