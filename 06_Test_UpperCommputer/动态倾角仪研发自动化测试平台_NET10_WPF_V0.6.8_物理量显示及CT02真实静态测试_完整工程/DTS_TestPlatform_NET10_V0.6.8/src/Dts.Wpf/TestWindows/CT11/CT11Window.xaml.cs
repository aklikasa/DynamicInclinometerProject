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
using Dts.Tests.S1.CT11;

namespace Dts.Wpf.TestWindows.CT11;

[Dts.Wpf.TestWindows.TestWindowFor("CT-11")]
public partial class CT11Window : Window, Dts.Wpf.TestWindows.ICalibrationRunAware
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

    public CT11Window(TestDefinition definition,ITestModule module,
        IStaticAngleHardware hardware,TestRunner runner,string outputRoot)
    {
        InitializeComponent();
        _definition=definition;_module=module;_hardware=hardware;_runner=runner;_root=outputRoot;
        OutputText.Text=outputRoot;
        UidText.Text=hardware.CurrentIdentity is { } id
            ? $"设备 {id.DtsId} / UID {id.UidHex} / 2TD {(hardware.IsTwoTdConnected?"已连接":"未连接")}"
            : "IMU尚未获取完整UID";
        RefreshBridge();
    }
    public void SetCalibrationRun(CalibrationRun run)
    {
        _calibration=run;
        try
        {
            var id=_hardware.CurrentIdentity??throw new InvalidOperationException("请连接IMU并获取完整UID");
            if(run.Mode!=CalibrationMode.Ambient)
                throw new InvalidOperationException("请先在主界面选择『常温标定』");
            run.Validate(id);
            var gyro=run.Files?.Gyro??throw new InvalidDataException("缺少UID匹配的Gyro JSON");
            var acc=run.Files?.Acc??throw new InvalidDataException("缺少UID匹配的ACC JSON");
            CalibrationText.Text=$"Gyro：{Path.GetFileName(gyro.FilePath)} (拟合输入±{gyro.FsHint}°/s)\n"+
                $"ACC：{Path.GetFileName(acc.FilePath)}；标定只读并保留SHA256";
        }
        catch(Exception ex){CalibrationText.Text="标定尚未就绪："+ex.Message;}
        RefreshBridge();
    }
    private void RefreshBridge()
    {
        if(BridgeText is null || StartButton is null)return;
        var bridge=Ct10DynamicBridge.Resolve(_hardware);
        bool ready=bridge?.IsRealDynamicCaptureReady==true;
        BridgeText.Text=ready
            ? $"已连接CT-10真实动态采集适配器（主机时标工程诊断）。\n"+
              $"已核验限速：内轴{bridge!.MaximumCertifiedSpeedDps(Ct10Axis.Inner):F3}°/s；"+
              $"外轴{bridge.MaximumCertifiedSpeedDps(Ct10Axis.Outer):F3}°/s。"
            : bridge is null
                ? "未注册真实动态采集桥：允许编辑参数及离线预览，但禁止旋转。先安装并修复CT-10。"
                : "动态采集尚未就绪：检查真实IMU/2TD、常温模型以及ct10_machine_profile.json。预览不受影响。";
        StartButton.IsEnabled=ready && _cts is null;
        RefreshPlan();
    }
    private static double Num(TextBox box)
    {
        if(!double.TryParse(box.Text.Trim(),NumberStyles.Float,CultureInfo.InvariantCulture,out double d)||
           !double.IsFinite(d))throw new InvalidDataException("参数"+box.Name+"必须是有限数值，请使用英文小数点");
        return d;
    }
    private static int Integer(TextBox box)
    {
        if(!int.TryParse(box.Text.Trim(),NumberStyles.Integer,CultureInfo.InvariantCulture,out int v))
            throw new InvalidDataException("参数"+box.Name+"必须是整数");
        return v;
    }
    private Ct11Settings Settings()=>new(_root,Speeds.Text.Trim(),
        InnerAxis.IsChecked==true,OuterAxis.IsChecked==true,Integer(RepeatCount),
        Num(TravelMin),Num(TravelMax),Num(ApprovedMin),Num(ApprovedMax),
        Num(SetupSpeed),Num(SettleSeconds),Num(SpeedTolerance),Num(EncoderWindow),
        Integer(MinFrames),InvertInner.IsChecked==true?-1:1,InvertOuter.IsChecked==true?-1:1,
        MotionApproval.IsChecked==true,EmergencyApproval.IsChecked==true,
        MappingApproval.IsChecked==true,_calibration);

    private void RefreshPlan()
    {
        if(Speeds is null || PlanGrid is null || PlanSummary is null ||
            InnerAxis is null || OuterAxis is null || RepeatCount is null ||
            SetupSpeed is null || TravelMin is null || TravelMax is null ||
            ApprovedMin is null || ApprovedMax is null || SettleSeconds is null ||
            SpeedTolerance is null || EncoderWindow is null || MinFrames is null ||
            InvertInner is null || InvertOuter is null || MotionApproval is null ||
            EmergencyApproval is null || MappingApproval is null)return;
        try
        {
            var s=Settings();var plan=Ct11Algorithm.Preview(s);
            PlanGrid.ItemsSource=plan;
            PlanSummary.Text=$"{plan.Count}段、{plan.Count/2}个正反配对，速度{s.LowSpeedsCsv}°/s，"+
                $"单次{Math.Abs(s.TravelMaxDeg-s.TravelMinDeg):F1}°；固定辅助轴0°。"+
                "此处为离线预览，真实限速、安全及时间质量将在启动时再检查。";
        }
        catch(Exception ex){PlanGrid.ItemsSource=null;PlanSummary.Text="参数检查："+ex.Message;}
    }
    private void SettingsChanged(object sender,TextChangedEventArgs e)=>RefreshPlan();
    private void AxisChanged(object sender,RoutedEventArgs e)=>RefreshPlan();
    private void PreviewClick(object sender,RoutedEventArgs e)
    {
        RefreshBridge();
        MessageBox.Show(this,PlanSummary.Text,"CT-11低速扫描计划预览",
            MessageBoxButton.OK,MessageBoxImage.Information);
    }
    private async void StartClick(object sender,RoutedEventArgs e)
    {
        if(_cts is not null)return;
        try
        {
            var live=Ct10DynamicBridge.Resolve(_hardware);
            if(live is null || !live.IsRealDynamicCaptureReady)
                throw new NotSupportedException("CT-10真实动态采集适配器未就绪，禁止启动CT-11");
            var id=_hardware.CurrentIdentity??throw new InvalidOperationException("IMU未读取UID");
            if(!_hardware.IsTwoTdConnected)throw new InvalidOperationException("双轴2TD没有连接");
            if(_module.TestId!="CT-11" || !_module.IsExecutable)
                throw new InvalidOperationException("CT-11注册错误或仍然是占位类");
            if(_calibration.Mode!=CalibrationMode.Ambient)
                throw new InvalidOperationException("请先在主窗口选择常温标定并重新打开CT-11");
            _calibration.Validate(id);
            if(!Directory.Exists(_root))throw new DirectoryNotFoundException("报告根目录不存在："+_root);
            var s=Settings();var plan=Ct11Algorithm.Plan(s,live);
            if(MessageBox.Show(this,
                $"设备UID：{id.UidHex}\n真实动态扫描段数：{plan.Count}\n"+
                $"速度档位：{s.LowSpeedsCsv}°/s，重复配对：{s.Repetitions}\n"+
                $"扫描角度：{s.TravelMinDeg:F2}°～{s.TravelMaxDeg:F2}°\n"+
                $"现场批准行程：{s.ApprovedMinDeg:F2}°～{s.ApprovedMaxDeg:F2}°\n\n"+
                "确认线缆、限位、实体急停、Gyro轴映射及现场人员监护；开始后全自动执行，不逐轮确认。",
                "CT-11真实动态运动确认",MessageBoxButton.YesNo,MessageBoxImage.Warning)!=MessageBoxResult.Yes)
                return;
            _cts=new CancellationTokenSource();_runStartUtc=DateTime.UtcNow;
            _reportHtml=null;ReportButton.IsEnabled=false;StartButton.IsEnabled=false;
            StopButton.IsEnabled=true;PreviewButton.IsEnabled=false;RunProgress.Value=0;
            ResultGrid.ItemsSource=null;MetricsText.Text="真实动态测试中，不提前判断PASS";
            var progress=new Progress<string>(message=>
            {
                StatusText.Text=message;
                var m=System.Text.RegularExpressions.Regex.Match(message,@"\[(\d+)/(\d+)\]");
                if(m.Success && double.TryParse(m.Groups[1].Value,out double n) &&
                   double.TryParse(m.Groups[2].Value,out double total) && total>0)
                    RunProgress.Value=Math.Clamp(n/total*100,0,100);
            });
            var context=new TestExecutionContext(_definition,TimeSpan.FromSeconds(s.SettleSeconds),
                _hardware,progress,s);
            var result=await _runner.RunAsync(_module,context,_cts.Token);
            StatusText.Text=result.Summary;RunProgress.Value=100;
            string? json=result.Files.FirstOrDefault(f=>f.EndsWith("CT-11_result.json",StringComparison.OrdinalIgnoreCase));
            if(json is not null&&File.Exists(json))ShowReport(json);
        }
        catch(OperationCanceledException)
        {
            StatusText.Text="操作已取消，将保留已完成的扫描段和部分报告";
            LoadPartial();
        }
        catch(Exception ex)
        {
            StatusText.Text="CT-11执行中止："+ex.Message;LoadPartial();
            MessageBox.Show(this,ex.Message,"CT-11动态测试中止",MessageBoxButton.OK,MessageBoxImage.Warning);
        }
        finally
        {
            _cts?.Dispose();_cts=null;PreviewButton.IsEnabled=true;
            StopButton.IsEnabled=false;RefreshBridge();
        }
    }
    private void ShowReport(string json)
    {
        var data=JsonSerializer.Deserialize<Ct11ReportData>(File.ReadAllText(json))
            ??throw new InvalidDataException("CT-11报告JSON无效");
        ResultGrid.ItemsSource=data.Sweeps.Select(s=>new {
            Axis=s.Axis.ToString(),Direction=s.Direction.ToString(),
            Reference=s.ReferenceSignedDps.ToString("F4",CultureInfo.InvariantCulture),
            X=s.GyroMeanDps[0].ToString("F5",CultureInfo.InvariantCulture),
            Y=s.GyroMeanDps[1].ToString("F5",CultureInfo.InvariantCulture),
            Z=s.GyroMeanDps[2].ToString("F5",CultureInfo.InvariantCulture),
            Frames=s.AcceptedFrames
        }).ToArray();
        MetricsText.Text=data.AxisSummaries.Count==0
            ? $"当前状态：{data.State}。完成扫描{data.Sweeps.Count}段；未形成有效完整速度拟合。"
            : string.Join("\n",data.AxisSummaries.Select(a=>$"{a.DriveAxis} / Gyro-{a.MainGyroAxis}："+
                $"增益偏差{a.MainGainErrorPercent:F4}%，低速最大非线性{a.LowSpeedNonlinearityMaxDps:F5}°/s，"+
                $"非主轴最大耦合{a.MaximumCrossAxisCouplingPercent:F4}%"));
        _reportHtml=Path.Combine(Path.GetDirectoryName(json)!,"CT-11_report.html");
        ReportButton.IsEnabled=File.Exists(_reportHtml);
        ReportText.Text="报告位置："+_reportHtml;
        Tabs.SelectedIndex=1;
    }
    private void LoadPartial()
    {
        try
        {
            var id=_hardware.CurrentIdentity;
            if(id is null || _runStartUtc==DateTime.MaxValue)return;
            var folder=Path.Combine(_root,id.DtsId+"_"+id.UidHex);
            if(!Directory.Exists(folder))return;
            string? latest=Directory.EnumerateDirectories(folder,"*_CT-11")
                .Where(p=>Directory.GetCreationTimeUtc(p)>=_runStartUtc.AddSeconds(-3))
                .OrderByDescending(Directory.GetCreationTimeUtc).FirstOrDefault();
            if(latest is null)return;
            string json=Path.Combine(latest,"CT-11_result.json");
            if(File.Exists(json))ShowReport(json);
        }
        catch(Exception ex)when(ex is IOException or UnauthorizedAccessException or JsonException)
        {ReportText.Text="部分报告读取失败，请在报告目录检查："+ex.Message;}
    }
    private void StopClick(object sender,RoutedEventArgs e)
    {
        StatusText.Text="已请求取消，程序将进行双轴软停车；如有异常请使用现场实体急停";
        _cts?.Cancel();
    }
    private void ReportClick(object sender,RoutedEventArgs e)
    {
        if(_reportHtml is not null&&File.Exists(_reportHtml))
            Process.Start(new ProcessStartInfo(_reportHtml){UseShellExecute=true});
    }
    private void CloseClick(object sender,RoutedEventArgs e)=>Close();
    private void OnClosing(object? sender,CancelEventArgs e)
    {
        if(_cts is null)return;
        e.Cancel=true;_cts.Cancel();
        MessageBox.Show(this,"正在取消真实动态运动并请求软停车，请确认实体安全后关闭窗口。",
            "CT-11停止中",MessageBoxButton.OK,MessageBoxImage.Warning);
    }
}
