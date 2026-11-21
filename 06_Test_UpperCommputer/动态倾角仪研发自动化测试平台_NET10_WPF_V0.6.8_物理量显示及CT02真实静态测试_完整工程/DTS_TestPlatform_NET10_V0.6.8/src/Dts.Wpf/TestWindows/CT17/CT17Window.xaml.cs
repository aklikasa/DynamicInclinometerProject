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
using Dts.Tests.S1.CT17;

namespace Dts.Wpf.TestWindows.CT17;

[Dts.Wpf.TestWindows.TestWindowFor("CT-17")]
public partial class CT17Window:Window,Dts.Wpf.TestWindows.ICalibrationRunAware
{
    private readonly TestDefinition _definition;
    private readonly ITestModule _module;
    private readonly IStaticAngleHardware _hardware;
    private readonly TestRunner _runner;
    private readonly string _outputRoot;
    private CalibrationRun _calibration=CalibrationRun.Raw;
    private CancellationTokenSource? _cts;
    private string? _html;
    private DateTime _startedLocal;

    public CT17Window(TestDefinition definition,ITestModule module,IStaticAngleHardware hardware,
        TestRunner runner,string outputRoot)
    {
        InitializeComponent();
        _definition=definition;_module=module;_hardware=hardware;_runner=runner;_outputRoot=outputRoot;
        RootText.Text="报告根目录："+outputRoot;
        IdentityText.Text=hardware.CurrentIdentity is { } id?
            $"设备：{id.DtsId} / UID：{id.UidHex} / 2TD：{(hardware.IsTwoTdConnected?"已连接":"未连接")}":
            "请先连接真实IMU并读取完整UID";
        RefreshBridge();
    }

    public void SetCalibrationRun(CalibrationRun run)
    {
        _calibration=run;
        try
        {
            var id=_hardware.CurrentIdentity??throw new InvalidOperationException("IMU尚未连接");
            if(run.Mode!=CalibrationMode.Ambient)throw new InvalidOperationException("CT-17必须使用常温标定");
            run.Validate(id);
            var acc=run.Files?.Acc??throw new InvalidDataException("ACC常温JSON缺失");
            var gyro=run.Files?.Gyro??throw new InvalidDataException("Gyro常温JSON缺失");
            CalibrationText.Text=$"UID匹配常温标定：ACC {Path.GetFileName(acc.FilePath)}；Gyro {Path.GetFileName(gyro.FilePath)}（输入量程±{gyro.FsHint}°/s）";
        }
        catch(Exception ex){CalibrationText.Text="常温标定尚未就绪："+ex.Message;}
        RefreshBridge();
    }

    private void RefreshBridge()
    {
        if(BridgeText is null||StartButton is null)return;
        var bridge=Ct10DynamicBridge.Resolve(_hardware);
        bool ready=bridge?.IsRealDynamicCaptureReady==true;
        bool timing=bridge is ICt17TimingTelemetry;
        BridgeText.Text=ready&&timing?
            $"真实动态采集适配器就绪；内轴限速{bridge!.MaximumCertifiedSpeedDps(Ct10Axis.Inner):F2}°/s，外轴限速{bridge.MaximumCertifiedSpeedDps(Ct10Axis.Outer):F2}°/s。使用主机Stopwatch同一时基。":
            bridge is null?"未注册真实动态适配器；CT-17禁止运动。":
            !ready?"动态适配器未就绪；请核验IMU/2TD和ct10_machine_profile.json。":
            "动态适配器未实现CT-17命令时标扩展，请安装CT-17适配器补丁。";
        StartButton.IsEnabled=ready&&timing&&_cts is null;
        RefreshPlan();
    }

    private static double D(TextBox b,string name)
    {
        if(!double.TryParse(b.Text.Trim(),NumberStyles.Float,CultureInfo.InvariantCulture,out double v)||!double.IsFinite(v))
            throw new InvalidDataException(name+"必须为有效数字（使用英文小数点）");
        return v;
    }
    private static int I(TextBox b,string name)
    {
        if(!int.TryParse(b.Text.Trim(),NumberStyles.Integer,CultureInfo.InvariantCulture,out int v))
            throw new InvalidDataException(name+"必须为整数");
        return v;
    }
    private Ct17Settings Settings()=>new(_calibration,_outputRoot,
        D(StaticSeconds,"静态采集时长"),D(ExpectedHz,"目标主机批次频率"),D(RateTolerance,"频率容差"),
        D(PreMotionDwell,"运动前静置"),D(SettleSeconds,"定位静置"),
        TestInner.IsChecked==true,TestOuter.IsChecked==true,I(Repeats,"重复次数"),
        D(CenterDeg,"中心角"),D(AmplitudeDeg,"单侧幅值"),D(CommandSpeed,"往复速率"),D(SetupSpeed,"定位速率"),
        D(ApprovedMin,"批准行程下界"),D(ApprovedMax,"批准行程上界"),
        D(DerivativeWindow,"编码器微分窗口"),D(MaxLagMs,"最大时延搜索"),
        InvertInner.IsChecked==true?-1:1,InvertOuter.IsChecked==true?-1:1,
        MotionApproval.IsChecked==true,EmergencyApproval.IsChecked==true,MappingApproval.IsChecked==true);

    private void RefreshPlan()
    {
        if(PlanText is null||StaticSeconds is null||TestInner is null||TestOuter is null||Repeats is null||
           CenterDeg is null||AmplitudeDeg is null||CommandSpeed is null||SetupSpeed is null||
           ApprovedMin is null||ApprovedMax is null||ExpectedHz is null||RateTolerance is null||
           PreMotionDwell is null||SettleSeconds is null||DerivativeWindow is null||MaxLagMs is null||
           InvertInner is null||InvertOuter is null||MotionApproval is null||EmergencyApproval is null||MappingApproval is null)return;
        try
        {
            var s=Settings();Ct17Algorithm.Validate(s,false);
            int count=((s.TestInner?1:0)+(s.TestOuter?1:0))*s.Repetitions*2;
            var bridge=Ct10DynamicBridge.Resolve(_hardware);
            string limits=bridge is null?"动态适配器未注册。":
                $"核验限速：内轴{bridge.MaximumCertifiedSpeedDps(Ct10Axis.Inner):F2}°/s、外轴{bridge.MaximumCertifiedSpeedDps(Ct10Axis.Outer):F2}°/s。";
            PlanText.Text=$"静态采集{s.StaticCaptureSeconds:F0}s；目标批次输出{s.ExpectedHostBatchHz:F1}Hz。动态计划{count}段真实运动：中心{s.CenterDeg:F2}°，±{s.AmplitudeDeg:F2}°，速率{s.CommandSpeedDps:F2}°/s，正反向各{s.Repetitions}次。{limits}此处只预览参数，不执行运动。";
        }
        catch(Exception ex){PlanText.Text="参数待调整："+ex.Message;}
    }
    private void SettingsChanged(object sender,TextChangedEventArgs e)=>RefreshPlan();
    private void SettingsChanged(object sender,RoutedEventArgs e)=>RefreshPlan();
    private void PreviewClick(object sender,RoutedEventArgs e)
    {
        RefreshBridge();MessageBox.Show(this,PlanText.Text,"CT-17测试计划预览",MessageBoxButton.OK,MessageBoxImage.Information);
    }

    private async void StartClick(object sender,RoutedEventArgs e)
    {
        if(_cts is not null)return;
        try
        {
            if(_module.TestId!="CT-17"||!_module.IsExecutable)throw new InvalidOperationException("CT-17模块未正确加载");
            if(_runner.IsRunning)throw new InvalidOperationException("已有其他测试正在运行");
            var id=_hardware.CurrentIdentity??throw new InvalidOperationException("IMU尚未连接或未读取完整UID");
            var bridge=Ct10DynamicBridge.Resolve(_hardware);
            if(bridge is null||!bridge.IsRealDynamicCaptureReady||bridge is not ICt17TimingTelemetry)
                throw new NotSupportedException("真实动态适配器/CT-17时标扩展未就绪，禁止运动");
            if(!_hardware.IsTwoTdConnected)throw new InvalidOperationException("2TD未连接");
            var s=Settings();Ct17Algorithm.Validate(s);
            if(s.Calibration.Mode!=CalibrationMode.Ambient)throw new InvalidOperationException("请在主界面选择当前UID对应的常温标定");
            s.Calibration.Validate(id);
            if(!Directory.Exists(_outputRoot))throw new DirectoryNotFoundException("报告根目录不存在");
            if(MessageBox.Show(this,
                $"设备：{id.DtsId}\nUID：{id.UidHex}\n静态时间基采集：{s.StaticCaptureSeconds:F0}s\n"+
                $"动态轴：{(s.TestInner?"内轴 ":"")}{(s.TestOuter?"外轴":"")}\n"+
                $"中心角：{s.CenterDeg:F2}°，单侧幅值：±{s.AmplitudeDeg:F2}°\n"+
                $"运动速度：{s.CommandSpeedDps:F2}°/s，正反向各{s.Repetitions}次\n"+
                $"现场批准行程：{s.ApprovedMinDeg:F1}°～{s.ApprovedMaxDeg:F1}°\n\n"+
                "确认工装固定、线缆余量、轴向符号、实体急停和现场监护。CT-17会真实驱动2TD进行小幅往复；任何异常立即停止并使用实体急停。",
                "CT-17真实动态测试确认",MessageBoxButton.YesNo,MessageBoxImage.Warning)!=MessageBoxResult.Yes)return;
            _cts=new CancellationTokenSource();_startedLocal=DateTime.Now;
            _html=null;ReportButton.IsEnabled=false;StartButton.IsEnabled=false;StopButton.IsEnabled=true;PreviewButton.IsEnabled=false;
            SweepGrid.ItemsSource=null;StaticSummaryText.Text="静态时间基采集中……";SummaryText.Text="等待真实动态往复采集完成。";
            ProgressBar.IsIndeterminate=true;
            var progress=new Progress<string>(m=>StatusText.Text=m);
            var context=new TestExecutionContext(_definition,TimeSpan.FromSeconds(s.StaticCaptureSeconds),_hardware,progress,s);
            var result=await _runner.RunAsync(_module,context,_cts.Token);
            StatusText.Text=result.Summary;
            string? json=result.Files.FirstOrDefault(x=>x.EndsWith("CT-17_result.json",StringComparison.OrdinalIgnoreCase));
            if(json is not null&&File.Exists(json))ShowReport(json);
        }
        catch(OperationCanceledException){StatusText.Text="CT-17已取消；已请求停止并保留可用数据。";TryLoadPartial();}
        catch(Exception ex){StatusText.Text="CT-17未完成："+ex.Message;TryLoadPartial();MessageBox.Show(this,ex.Message,"CT-17执行中止",MessageBoxButton.OK,MessageBoxImage.Warning);}
        finally
        {
            ProgressBar.IsIndeterminate=false;_cts?.Dispose();_cts=null;StopButton.IsEnabled=false;PreviewButton.IsEnabled=true;RefreshBridge();
        }
    }

    private void ShowReport(string json)
    {
        var d=JsonSerializer.Deserialize<Ct17ReportData>(File.ReadAllText(json))??throw new InvalidDataException("CT-17报告JSON无法读取");
        _html=Path.Combine(Path.GetDirectoryName(json)!,"CT-17_report.html");ReportButton.IsEnabled=File.Exists(_html);
        OutputText.Text="报告："+_html+"\n静态原始数据："+d.StaticRawCsv;
        SweepGrid.ItemsSource=d.Sweeps.Select(x=>new
        {
            x.Axis,x.Direction,重复=x.Repetition,命令调用毫秒=x.CommandCallDurationMs,
            命令至编码器起动毫秒=x.CommandToEncoderOnsetMs,
            命令至Gyro响应毫秒=x.CommandToGyroOnsetMs,
            编码器至Gyro表观延迟毫秒=x.EncoderToGyroOnsetMs,
            互相关时延毫秒=x.CrossCorrelationLagMs,相关系数=x.CrossCorrelationCoefficient,
            时间分辨率毫秒=x.TimingResolutionMs,质量=x.Quality
        }).ToArray();
        if(d.StaticTiming is { } t)
            StaticSummaryText.Text=$"完整FIFO批次：{t.Batches}；帧数：{t.Frames}；ODR：{t.OdrHz}Hz；时长：{t.DurationSeconds:F2}s\n"+
                $"主机批次输出：{t.HostBatchRateHz:F3}Hz；目标：{t.ExpectedHostBatchHz:F2}Hz；偏差：{t.HostBatchRateErrorPercent:F1}%\n"+
                $"主机批次周期：{t.HostBatchPeriodMedianMs:F3}ms；P95抖动：{t.HostBatchJitterP95Ms:F3}ms\n"+
                $"MCU tick周期：{t.McuTickPeriodMedianMs:F3}ms；16/ODR预期：{t.ExpectedMcuBatchPeriodMs:F3}ms；偏差：{t.McuTickPeriodErrorPercent:F1}%\n"+
                $"候选漏批：{t.CandidateMissingBatches}；无法分类长间隔：{t.UnclassifiedLongGaps}\n"+
                string.Join("\n",t.Warnings);
        SummaryText.Text=$"状态：{d.State}\n{d.Conclusion}\n\n{d.Limitation}\n\n{d.FailureReason}";
    }
    private void TryLoadPartial()
    {
        try
        {
            var id=_hardware.CurrentIdentity;if(id is null||_startedLocal==default)return;
            string root=Path.Combine(_outputRoot,id.DtsId+"_"+id.UidHex);
            if(!Directory.Exists(root))return;
            var dir=Directory.EnumerateDirectories(root,"*_CT-17").Where(x=>Directory.GetCreationTime(x)>=_startedLocal.AddSeconds(-5))
                .OrderByDescending(Directory.GetCreationTime).FirstOrDefault();
            if(dir is null)return;
            var json=Path.Combine(dir,"CT-17_result.json");if(File.Exists(json))ShowReport(json);
        }
        catch(Exception ex)when(ex is IOException or UnauthorizedAccessException or JsonException){OutputText.Text="部分报告无法预览："+ex.Message;}
    }
    private async void StopClick(object sender,RoutedEventArgs e)
    {
        _cts?.Cancel();StopButton.IsEnabled=false;StatusText.Text="已请求取消；正在请求双轴软停车。若转台未停止，请立即使用实体急停。";
        var bridge=Ct10DynamicBridge.Resolve(_hardware);
        if(bridge is not null)
        {
            using var stop=new CancellationTokenSource(TimeSpan.FromSeconds(6));
            try{await bridge.StopBothAxesAsync(stop.Token);}
            catch(Exception ex){StatusText.Text="危险：双轴软停车未确认，请使用实体急停："+ex.Message;}
        }
    }
    private void ReportClick(object sender,RoutedEventArgs e){if(_html is not null&&File.Exists(_html))Process.Start(new ProcessStartInfo(_html){UseShellExecute=true});}
    private void CloseClick(object sender,RoutedEventArgs e)=>Close();
    private void OnClosing(object? sender,CancelEventArgs e)
    {
        if(_cts is null)return;e.Cancel=true;_cts.Cancel();
        MessageBox.Show(this,"CT-17正在停止。请确认转台完全静止并完成写盘后再关闭窗口。","CT-17停止中",MessageBoxButton.OK,MessageBoxImage.Warning);
    }
}
