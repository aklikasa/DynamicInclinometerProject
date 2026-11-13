using System.ComponentModel;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using Dts.Core;
using Dts.TestEngine;
using Dts.Tests.S1.CT12A;

namespace Dts.Wpf.TestWindows.CT12A;

[Dts.Wpf.TestWindows.TestWindowFor("CT-12A")]
public partial class CT12AWindow : Window, Dts.Wpf.TestWindows.ICalibrationRunAware
{
    private readonly TestDefinition _definition;
    private readonly ITestModule _module;
    private readonly IStaticAngleHardware _hardware;
    private readonly TestRunner _runner;
    private readonly string _root;
    private CalibrationRun _calibration=CalibrationRun.Raw;
    private CancellationTokenSource? _cts;
    private string? _reportHtml;

    public CT12AWindow(TestDefinition definition,ITestModule module,
        IStaticAngleHardware hardware,TestRunner runner,string outputRoot)
    {
        InitializeComponent();
        _definition=definition;_module=module;_hardware=hardware;
        _runner=runner;_root=outputRoot;
        RootText.Text=outputRoot;
        UidText.Text=hardware.CurrentIdentity is { } id
            ? $"设备 {id.DtsId}  /  完整UID {id.UidHex}"
            : "请先连接真实IMU并读取完整UID";
        Preview();
    }
    public void SetCalibrationRun(CalibrationRun run)
    {
        _calibration=run;
        try
        {
            var id=_hardware.CurrentIdentity??throw new InvalidOperationException("请先连接IMU获取完整UID");
            if(run.Mode!=CalibrationMode.Ambient)
                throw new InvalidOperationException("主界面需要选择『常温标定』模式");
            run.Validate(id);
            var acc=run.Files?.Acc??throw new InvalidDataException("ACC JSON未匹配");
            var gyro=run.Files?.Gyro??throw new InvalidDataException("Gyro JSON未匹配");
            CalibrationText.Text=$"ACC {Path.GetFileName(acc.FilePath)} / Gyro {Path.GetFileName(gyro.FilePath)}\n"+
                $"历史拟合输入量程：ACC ±{acc.FsHint}g，Gyro ±{gyro.FsHint}°/s。";
        }
        catch(Exception ex)
        {
            CalibrationText.Text="常温补偿尚未就绪："+ex.Message;
            StatusText.Text=CalibrationText.Text;
        }
    }
    private static double Number(TextBox box)
    {
        if(!double.TryParse(box.Text.Trim(),NumberStyles.Float,CultureInfo.InvariantCulture,out double v)||
            !double.IsFinite(v))
            throw new InvalidDataException($"参数{box.Name}须为有限数值，小数点使用'.'");
        return v;
    }
    private static int Integer(TextBox box)
    {
        if(!int.TryParse(box.Text.Trim(),NumberStyles.Integer,CultureInfo.InvariantCulture,out int v))
            throw new InvalidDataException($"参数{box.Name}须为整数");
        return v;
    }
    private Ct12aSettings Settings()=>new(_calibration,_root,Number(DurationMinutes),
        Number(TauMin),Number(TauMax),Integer(PointsPerDecade),
        Number(HostJitter),Number(McuJitter),Number(FifoTolerance),Number(MaxTempRange),Integer(MinimumBatches),
        StationaryConfirm.IsChecked==true,ThermalConfirm.IsChecked==true,
        TimebaseConfirm.IsChecked==true);
    private void SettingChanged(object sender,TextChangedEventArgs e)=>Preview();
    private void Preview()
    {
        if(PlanText is null||DurationMinutes is null||MinimumBatches is null||
           TauMin is null||TauMax is null||PointsPerDecade is null||HostJitter is null||
           McuJitter is null||FifoTolerance is null||MaxTempRange is null)return;
        try
        {
            var p=Settings();Ct12aAlgorithm.Validate(p,false);
            PlanText.Text=$"预计静态采集 {p.DurationMinutes:F1} 分钟；请求τ范围"+
                $" {p.TauMinSeconds:F3}～{p.TauMaxSeconds:F2}秒。"+
                "最终τ上限还受实际记录长度/12和完整FIFO批次数限制。"+
                "不会把缺失批次插值成真实样本。";
        }
        catch(Exception ex){PlanText.Text="参数待调整："+ex.Message;}
    }
    private void PreviewClick(object sender,RoutedEventArgs e)
    {
        try
        {
            var p=Settings();Ct12aAlgorithm.Validate(p,false);
            MessageBox.Show(this,$"采集{p.DurationMinutes:F1}分钟，τ期望{p.TauMinSeconds:F2}～{p.TauMaxSeconds:F1}秒。\n"+
                "全部参数均可编辑，硬件不需要转动。\n"+
                "无逐帧硬件时戳，只有通过严格批次连续性审核后才输出工程级Allan偏差。",
                "CT-12A 测试计划",MessageBoxButton.OK,MessageBoxImage.Information);
        }
        catch(Exception ex){MessageBox.Show(this,ex.Message,"CT-12A参数错误",MessageBoxButton.OK,MessageBoxImage.Warning);}
    }
    private async void StartClick(object sender,RoutedEventArgs e)
    {
        if(_cts is not null)return;
        try
        {
            if(!_module.IsExecutable||_module.TestId!="CT-12A")
                throw new InvalidOperationException("CT-12A独立测试模块未正确加载");
            var id=_hardware.CurrentIdentity??throw new InvalidOperationException("没有连接真实IMU或完整UID无效");
            var p=Settings();Ct12aAlgorithm.Validate(p);
            if(p.Calibration.Mode!=CalibrationMode.Ambient)
                throw new InvalidOperationException("请在主窗口选择『常温标定』并更新CT-12A设置");
            p.Calibration.Validate(id);
            if(!Directory.Exists(p.ReportRoot))
                throw new DirectoryNotFoundException("报告根目录不存在："+p.ReportRoot);
            if(_runner.IsRunning)throw new InvalidOperationException("已有其他测试正在运行");
            if(MessageBox.Show(this,$"设备：{id.DtsId}　UID：{id.UidHex}\n"+
                $"静止采集：{p.DurationMinutes:F1}分钟\n"+
                $"τ={p.TauMinSeconds:F3}～{p.TauMaxSeconds:F1}s\n\n"+
                "本测试不移动任何转台轴；采集全程保持静止与稳定环境。\n"+
                "仅批次时间戳，工程估计不等于硬件同步认证。确认现在开始？",
                "CT-12A 真实静态长时采集",MessageBoxButton.YesNo,MessageBoxImage.Warning)
                !=MessageBoxResult.Yes)return;
            _reportHtml=null;ReportButton.IsEnabled=false;StartButton.IsEnabled=false;
            PreviewButton.IsEnabled=false;StopButton.IsEnabled=true;
            AxisGrid.ItemsSource=null;CurveGrid.ItemsSource=null;
            RunProgressBar.IsIndeterminate=true;
            SummaryText.Text="正在写入真实FIFO原始/校正CSV，完成后检查时标并计算Allan";
            _cts=new CancellationTokenSource();
            var progress=new Progress<string>(message=>StatusText.Text=message);
            var context=new TestExecutionContext(_definition,TimeSpan.FromMinutes(p.DurationMinutes),
                _hardware,progress,p);
            var result=await _runner.RunAsync(_module,context,_cts.Token);
            StatusText.Text=result.Summary;
            string? json=result.Files.FirstOrDefault(f=>f.EndsWith("CT-12A_result.json",StringComparison.OrdinalIgnoreCase));
            if(json is not null&&File.Exists(json))ShowReport(json);
        }
        catch(OperationCanceledException)
        {
            StatusText.Text="已取消：已有真实FIFO CSV及manifest应保留，不生成已完成结论；请查看采集根目录";
        }
        catch(Exception ex)
        {
            StatusText.Text="CT-12A未完成："+ex.Message;
            MessageBox.Show(this,ex.Message,"CT-12A未完成",MessageBoxButton.OK,MessageBoxImage.Warning);
        }
        finally
        {
            RunProgressBar.IsIndeterminate=false;
            _cts?.Dispose();_cts=null;StopButton.IsEnabled=false;StartButton.IsEnabled=true;
            PreviewButton.IsEnabled=true;
        }
    }
    private void ShowReport(string file)
    {
        var data=JsonSerializer.Deserialize<Ct12aReportData>(File.ReadAllText(file))
            ??throw new InvalidDataException("Allan结果JSON反序列化失败");
        _reportHtml=Path.Combine(Path.GetDirectoryName(file)!,"CT-12A_report.html");
        ReportButton.IsEnabled=File.Exists(_reportHtml);
        SummaryText.Text=$"状态：{data.State}；{data.Conclusion}";
        QualityText.Text=data.Analysis is null ?"分析未完成："+data.FailureReason:
            $"时标等级：{data.Analysis.TimeQuality.Classification}，"+
            $"完整批次{data.Analysis.TimeQuality.Batches}，"+
            $"疑似缺帧/重叠{data.Analysis.TimeQuality.GapsOrOverlaps}处。"+
            (data.Analysis.CoefficientsReleased?"仅工程估计，未硬件同步认证。":"数据质量未达标，禁止发布噪声系数。 ");
        ReportText.Text="报告："+_reportHtml+"　原始数据："+data.AcquisitionFolder;
        if(data.Analysis is not { } a)return;
        static string F(double? v,string fmt="F6")=>v?.ToString(fmt,CultureInfo.InvariantCulture)??"N/A";
        AxisGrid.ItemsSource=a.Axes.Select(x=>new
        {
            x.Axis,x.Unit,Mean=F(x.Mean),Std=F(x.StandardDeviation),Min=F(x.MinAllanDeviation),
            Tau=F(x.TauAtMinimumSeconds,"F3"),
            Arw=F(x.WhiteNoiseCoefficient)+" "+x.WhiteNoiseCoefficientUnit,
            Bias=F(x.BiasInstabilityProxy)+" "+x.BiasInstabilityUnit
        }).ToArray();
        CurveGrid.ItemsSource=a.Curves.Select(x=>new
        {
            Tau=x.TauSeconds.ToString("F4",CultureInfo.InvariantCulture),
            X=x.GxAllanDeviationDps.ToString("G6",CultureInfo.InvariantCulture),
            Y=x.GyAllanDeviationDps.ToString("G6",CultureInfo.InvariantCulture),
            Z=x.GzAllanDeviationDps.ToString("G6",CultureInfo.InvariantCulture),
            Ax=x.AxAllanDeviationG.ToString("G6",CultureInfo.InvariantCulture),
            Ay=x.AyAllanDeviationG.ToString("G6",CultureInfo.InvariantCulture),
            Az=x.AzAllanDeviationG.ToString("G6",CultureInfo.InvariantCulture),
            Differences=x.OverlappingDifferences
        }).ToArray();
        Tabs.SelectedIndex=0;
    }
    private void StopClick(object sender,RoutedEventArgs e)
    {
        StatusText.Text="正在取消真实IMU采集；不发送任何转台命令。已完成CSV将在采集目录保留";
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
        MessageBox.Show(this,"长时采集正在结束，已发出取消请求，请完成写盘后再关闭窗口。",
            "CT-12A保存中",MessageBoxButton.OK,MessageBoxImage.Warning);
    }
}
