using System.ComponentModel;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using Dts.Core;
using Dts.TestEngine;
using Dts.Tests.S1.CT05;
using Microsoft.Win32;

namespace Dts.Wpf.TestWindows.CT05;

[Dts.Wpf.TestWindows.TestWindowFor("CT-05")]
public partial class CT05Window : Window
{
    private readonly TestDefinition _definition;
    private readonly ITestModule _module;
    private readonly IStaticAngleHardware _hardware;
    private readonly TestRunner _runner;
    private readonly string _root;
    private CancellationTokenSource? _cts;
    private string? _lastReport;
    private DateTime _currentRunStartedUtc=DateTime.MaxValue;
    public CT05Window(TestDefinition definition,ITestModule module,IStaticAngleHardware hardware,
        TestRunner runner,string outputRoot)
    {
        InitializeComponent();
        _definition=definition;_module=module;_hardware=hardware;_runner=runner;
        _root=outputRoot;RootText.Text=_root;
        UidText.Text=hardware.CurrentIdentity is { } id?$"DTS: {id.DtsId}   原始UID: {id.UidHex}":"未读取UID / 无法开始";
        RefreshPlan();
    }
    private string PlanKind=>(PlanBox.SelectedItem as ComboBoxItem)?.Content?.ToString()??"小角度";
    private static double Number(TextBox box)
    {
        if(!double.TryParse(box.Text,NumberStyles.Float,CultureInfo.InvariantCulture,out var val)||!double.IsFinite(val))
            throw new InvalidDataException($"参数 {box.Name} 必须是有效数字（小数使用 . ）");
        return val;
    }
    private Ct05Settings Settings()=>new(_root,CalPath.Text,Number(Settle),Number(Sample),
        Number(MotionSpeed),Number(Tolerance),Number(MinTravel),Number(MaxTravel),PlanKind,
        FullTravelApproved.IsChecked==true,NegativeDirectionApproved.IsChecked==true,
        CalibrationOwnership.IsChecked==true);
    private void RefreshPlan()
    {
        var plan=Ct05Algorithm.BuildPlan(PlanKind);
        PlanGrid.ItemsSource=plan;
        PlanSummary.Text=$"本方案 {plan.Count} 个检测姿态 · Y轴内轴0°，X轴内轴90°。"+
            " 外轴负角按 Python 原方案转换为 0~360° 绝对指令；未经实机校验不能假定旋转方向。";
    }
    private void PlanChanged(object sender,SelectionChangedEventArgs e)
    {
        if(PlanGrid is not null)RefreshPlan();
    }
    private void PreviewClick(object sender,RoutedEventArgs e)
    {
        try{RefreshPlan();Ct05Algorithm.ValidatePlan(Settings(),Ct05Algorithm.BuildPlan(PlanKind));
            MessageBox.Show("扫描计划处于已填写的行程内。仍需现场核实实际轴向、限位和急停。","计划检查",MessageBoxButton.OK,MessageBoxImage.Information);}
        catch(Exception ex){MessageBox.Show(ex.Message,"计划未通过检查",MessageBoxButton.OK,MessageBoxImage.Warning);}
    }
    private void ChooseCalibrationClick(object sender,RoutedEventArgs e)
    {
        var d=new OpenFileDialog{Title="选择当前设备的 ACC 标定 JSON",Filter="校准文件 (*.json)|*.json|所有文件|*.*"};
        if(d.ShowDialog(this)==true){CalPath.Text=d.FileName;CalibrationOwnership.IsChecked=false;}
    }
    private async void StartClick(object sender,RoutedEventArgs e)
    {
        if(_cts is not null)return;
        try
        {
            if(_hardware.CurrentIdentity is null||!_hardware.IsTwoTdConnected)
                throw new InvalidOperationException("必须先在主窗口连接真实IMU并读取UID，连接真实2TD-600并校验两轴状态");
            if(!Directory.Exists(_root))throw new DirectoryNotFoundException("报告根目录不可用；请在主窗口重新选择目录");
            if(SafetyConfirmed.IsChecked!=true)throw new InvalidOperationException("请先逐项现场确认机械安全条件");
            var p=Settings();var plan=Ct05Algorithm.BuildPlan(p.PlanKind);
            Ct05Algorithm.ValidatePlan(p,plan);
            _=Ct05Calibration.Load(p.CalibrationJson);
            if(MessageBox.Show(this,
                $"将向真实2TD-600发送连续位置运动，{plan.Count} 个检测点。\n速度 {p.SpeedDps}°/s、检测序列 {p.PlanKind}。\n\n请现场确认物理急停可用、固定夹具/线缆和预期旋转方向已经验证。\n\n确认开始真实自动测试？",
                "实物运动最终确认",MessageBoxButton.YesNo,MessageBoxImage.Warning)!=MessageBoxResult.Yes)return;
            _currentRunStartedUtc=DateTime.UtcNow;
            _lastReport=null;
            ResultGrid.ItemsSource=null;
            _cts=new CancellationTokenSource();StartButton.IsEnabled=false;StopButton.IsEnabled=true;
            RunProgressBar.Value=0;StatusText.Text="正在执行真实测试";FileText.Text="逐点原始数据和检查点将持续写盘";
            var progress=new Progress<string>(message=>
            {
                StatusText.Text=message;
                var m=System.Text.RegularExpressions.Regex.Match(message,@"\[(\d+)/(\d+)\]");
                if(m.Success)RunProgressBar.Value=Math.Clamp(100.0*int.Parse(m.Groups[1].Value)/int.Parse(m.Groups[2].Value),0,100);
            });
            var ctx=new TestExecutionContext(_definition,TimeSpan.FromSeconds(p.CaptureSeconds),_hardware,progress,p);
            var result=await _runner.RunAsync(_module,ctx,_cts.Token);
            _lastReport=result.Files.FirstOrDefault(f=>f.EndsWith(".html",StringComparison.OrdinalIgnoreCase));
            StatusText.Text=result.Summary;FileText.Text=_lastReport??"已保存，未找到HTML路径";
            RunProgressBar.Value=100;
            if(result.Files.FirstOrDefault(f=>f.EndsWith("CT-05_result.json",StringComparison.OrdinalIgnoreCase)) is string resultJson)
                LoadResult(resultJson);
        }
        catch(OperationCanceledException){StatusText.Text="已取消：保留已采数据和部分报告，请检查实体转台安全状态";LoadLatestPartial();}
        catch(Exception ex){StatusText.Text="任务未完成："+ex.Message;LoadLatestPartial();MessageBox.Show(this,ex.Message,"检测终止",MessageBoxButton.OK,MessageBoxImage.Warning);}
        finally{_cts?.Dispose();_cts=null;StartButton.IsEnabled=true;StopButton.IsEnabled=false;}
    }
    private void LoadResult(string path)
    {
        try
        {
            var summary=JsonSerializer.Deserialize<Ct05Summary>(File.ReadAllText(path));
            if(summary is null)return;
            ResultGrid.ItemsSource=summary.Points;
            StatsText.Text=$"状态：{summary.Status}  |  采集点数：{summary.Points.Count}  |  Bias：{summary.BiasDeg:F6}°  |  RMSE：{summary.RmseDeg:F6}°  |  MaxAbs：{summary.MaxAbsErrorDeg:F6}°（研发结果，非产品PASS）";
            DataTabs.SelectedIndex=1;
            _lastReport=Path.Combine(Path.GetDirectoryName(path)!,"CT-05_report.html");
            FileText.Text="本次报告："+_lastReport;
        }
        catch(Exception ex){StatusText.Text+="；报告预览失败："+ex.Message;}
    }
    private void LoadLatestPartial()
    {
        // Only read files under the exact current UID directory, and never claim they are PASS.
        try
        {
            var id=_hardware.CurrentIdentity;
            if(id is null)return;
            var dir=Path.Combine(_root,id.DtsId+"_"+id.UidHex);
            if(!Directory.Exists(dir))return;
            var recent=Directory.EnumerateDirectories(dir,"*_CT-05")
                .Where(path=>Directory.GetCreationTimeUtc(path)>=_currentRunStartedUtc.AddSeconds(-2))
                .OrderByDescending(Directory.GetCreationTimeUtc).FirstOrDefault();
            if(recent is null)return;
            var report=Path.Combine(recent,"CT-05_result.json");
            if(File.Exists(report))LoadResult(report);
        }
        catch(IOException){}
        catch(UnauthorizedAccessException){}
    }
    private void StopClick(object sender,RoutedEventArgs e)
    {
        StatusText.Text="正在请求取消并执行双轴软停车；请现场观察反馈。必要时使用物理急停。";
        _cts?.Cancel();
    }
    private void OpenReportClick(object sender,RoutedEventArgs e)
    {
        if(_lastReport is not null&&File.Exists(_lastReport))
            Process.Start(new ProcessStartInfo(_lastReport){UseShellExecute=true});
        else MessageBox.Show(this,"本次完整报告尚未生成；若中途停止，请到保存根目录检查对应 UID 的 CT-05 文件夹。","报告提示");
    }
    private void CloseClick(object sender,RoutedEventArgs e)=>Close();
    private void OnClosing(object? sender,CancelEventArgs e)
    {
        if(_cts is not null)
        {
            e.Cancel=true;
            _cts.Cancel();
            MessageBox.Show(this,"检测任务仍在执行。已请求取消，需等待停车与报告检查点写入结束后才能关闭此窗口。","正在结束真实设备任务",MessageBoxButton.OK,MessageBoxImage.Warning);
        }
    }
}
