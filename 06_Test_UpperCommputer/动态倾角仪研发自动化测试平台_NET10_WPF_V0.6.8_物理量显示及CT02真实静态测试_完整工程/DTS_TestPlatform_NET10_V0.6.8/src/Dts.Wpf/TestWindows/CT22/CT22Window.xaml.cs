using System.ComponentModel;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using Dts.Core;
using Dts.TestEngine;
using Dts.Tests.S1.CT22;

namespace Dts.Wpf.TestWindows.CT22;

[Dts.Wpf.TestWindows.TestWindowFor("CT-22")]
public partial class CT22Window : Window,Dts.Wpf.TestWindows.ICalibrationRunAware
{
    private readonly TestDefinition _definition;
    private readonly ITestModule _module;
    private readonly IStaticAngleHardware _hardware;
    private readonly TestRunner _runner;
    private readonly string _root;
    private CalibrationRun _calibration=CalibrationRun.Raw;
    private CancellationTokenSource? _cts;
    private string? _reportHtml;

    public CT22Window(TestDefinition definition,ITestModule module,
        IStaticAngleHardware hardware,TestRunner runner,string outputRoot)
    {
        InitializeComponent();
        _definition=definition;_module=module;_hardware=hardware;
        _runner=runner;_root=outputRoot;RootText.Text=outputRoot;
        UidText.Text=hardware.CurrentIdentity is { } id
            ? $"设备 {id.DtsId}　完整UID {id.UidHex}"
            : "请先连接真实IMU并取得完整UID";
        Preview();
    }
    public void SetCalibrationRun(CalibrationRun run)
    {
        _calibration=run;
        try
        {
            var id=_hardware.CurrentIdentity??throw new InvalidOperationException("请先连接真实IMU");
            if(run.Mode!=CalibrationMode.Ambient)
                throw new InvalidOperationException("主窗口需要选择『常温标定』模式");
            run.Validate(id);
            var gyro=run.Files?.Gyro??throw new InvalidDataException("Gyro UID匹配JSON缺失");
            var acc=run.Files?.Acc??throw new InvalidDataException("ACC UID匹配JSON缺失");
            CalibrationText.Text=$"ACC：{Path.GetFileName(acc.FilePath)}\n"+
                $"Gyro：{Path.GetFileName(gyro.FilePath)}\n"+
                $"历史输入量程：ACC ±{acc.FsHint}g，Gyro ±{gyro.FsHint}°/s；无额外测试期零偏复位";
        }
        catch(Exception ex)
        {
            CalibrationText.Text="常温模型尚未满足要求："+ex.Message;
            StatusText.Text=CalibrationText.Text;
        }
    }
    private static double Number(TextBox input)
    {
        if(!double.TryParse(input.Text.Trim(),NumberStyles.Float,CultureInfo.InvariantCulture,out double n)||
            !double.IsFinite(n))
            throw new InvalidDataException($"{input.Name}必须为有效数值；小数点用英文'.'");
        return n;
    }
    private static int Integer(TextBox input)
    {
        if(!int.TryParse(input.Text.Trim(),NumberStyles.Integer,CultureInfo.InvariantCulture,out int n))
            throw new InvalidDataException($"{input.Name}必须是整数");
        return n;
    }
    private Ct22Settings Settings()=>new(_calibration,_root,Number(DurationMinutes),
        Integer(MinimumBatches),Number(HostJitter),Number(McuJitter),Number(FifoSpan),
        Number(ClockMismatch),Number(TempRange),Number(AccAngle),Number(PlotInterval),
        StationaryConfirm.IsChecked==true,ThermalConfirm.IsChecked==true,
        TimebaseConfirm.IsChecked==true);
    private void SettingChanged(object sender,TextChangedEventArgs e)=>Preview();
    private void Preview()
    {
        if(PlanText is null||DurationMinutes is null||MinimumBatches is null||HostJitter is null||
            McuJitter is null||FifoSpan is null||ClockMismatch is null||TempRange is null||
            AccAngle is null||PlotInterval is null)return;
        try
        {
            var p=Settings();Ct22Algorithm.Validate(p,false);
            string checkpoints=p.DurationMinutes<10.2?"记录可能不足10分钟；两项检查点均不保证覆盖":
                p.DurationMinutes<30.2?"计划覆盖10分钟检查点；30分钟需要延长采样":"计划覆盖10与30分钟检查点";
            PlanText.Text=$"静止采集{p.DurationMinutes:F2}分钟；{checkpoints}。"+
                $"计算使用真实MCU批次时间间隔，绘图步长{p.PlotIntervalSeconds:F1}s。"+
                "如果实际记录未覆盖600/1800秒，对应值记N/A；不会补出未采到的结果。";
        }
        catch(Exception ex){PlanText.Text="参数待调整："+ex.Message;}
    }
    private void PreviewClick(object sender,RoutedEventArgs e)
    {
        try
        {
            var p=Settings();Ct22Algorithm.Validate(p,false);
            MessageBox.Show(this,$"采集{p.DurationMinutes:F2}分钟，最少{p.MinimumBatches}个完整FIFO批次。\n"+
                "本测试无转台运动命令，直接从真实MCU批次时间增量积分校正后未融合Gyro。\n"+
                "没有逐帧硬件时间戳；时标质量不合格时，禁止发布漂移指标。",
                "CT-22 静止积分计划",MessageBoxButton.OK,MessageBoxImage.Information);
        }
        catch(Exception ex){MessageBox.Show(this,ex.Message,"参数错误",MessageBoxButton.OK,MessageBoxImage.Warning);}
    }
    private async void StartClick(object sender,RoutedEventArgs e)
    {
        if(_cts is not null)return;
        try
        {
            if(!_module.IsExecutable||_module.TestId!="CT-22")
                throw new InvalidOperationException("CT-22模块未正确注册");
            var id=_hardware.CurrentIdentity??throw new InvalidOperationException("请先连接真实IMU并读取UID");
            var p=Settings();Ct22Algorithm.Validate(p);
            if(p.Calibration.Mode!=CalibrationMode.Ambient)
                throw new InvalidOperationException("请先在主窗口选择常温补偿，再打开CT-22");
            p.Calibration.Validate(id);
            if(!Directory.Exists(p.ReportRoot))
                throw new DirectoryNotFoundException("报告根目录不存在："+p.ReportRoot);
            if(_runner.IsRunning)throw new InvalidOperationException("其他测试正在运行");
            if(MessageBox.Show(this,$"设备：{id.DtsId}\n完整UID：{id.UidHex}\n"+
                $"真实静止采集：{p.DurationMinutes:F2}分钟\n"+
                "不会移动2TD转台，也不在测试期重新做Gyro零偏消除。\n"+
                "10/30分钟漂移只在实际MCU时间覆盖时给出。\n\n"+
                "已经确认设备、线缆和转台全程静止，并接受批次级时间戳局限？",
                "CT-22 开始真实静止积分",MessageBoxButton.YesNo,MessageBoxImage.Warning)
                !=MessageBoxResult.Yes)return;
            _reportHtml=null;ReportButton.IsEnabled=false;StartButton.IsEnabled=false;
            PreviewButton.IsEnabled=false;StopButton.IsEnabled=true;
            AxisGrid.ItemsSource=null;CurveGrid.ItemsSource=null;
            RunProgressBar.IsIndeterminate=true;
            SummaryText.Text="正在将真实FIFO逐批写入原始/补偿CSV，结束后再审核时标并计算积分";
            _cts=new CancellationTokenSource();
            var progress=new Progress<string>(message=>StatusText.Text=message);
            var context=new TestExecutionContext(_definition,TimeSpan.FromMinutes(p.DurationMinutes),
                _hardware,progress,p);
            var result=await _runner.RunAsync(_module,context,_cts.Token);
            StatusText.Text=result.Summary;
            string? file=result.Files.FirstOrDefault(f=>f.EndsWith("CT-22_result.json",StringComparison.OrdinalIgnoreCase));
            if(file is not null&&File.Exists(file))ShowReport(file);
        }
        catch(OperationCanceledException)
        {
            StatusText.Text="已请求取消；原始采集CSV及manifest应保留，取消运行不视为完成的10/30分钟测试";
        }
        catch(Exception ex)
        {
            StatusText.Text="CT-22运行失败："+ex.Message;
            MessageBox.Show(this,ex.Message,"CT-22 未完成",MessageBoxButton.OK,MessageBoxImage.Warning);
        }
        finally
        {
            RunProgressBar.IsIndeterminate=false;
            _cts?.Dispose();_cts=null;StopButton.IsEnabled=false;
            StartButton.IsEnabled=true;PreviewButton.IsEnabled=true;
        }
    }
    private void ShowReport(string file)
    {
        var data=JsonSerializer.Deserialize<Ct22ReportData>(File.ReadAllText(file))
            ??throw new InvalidDataException("CT-22分析JSON无法读取");
        _reportHtml=Path.Combine(Path.GetDirectoryName(file)!,"CT-22_report.html");
        ReportButton.IsEnabled=File.Exists(_reportHtml);
        SummaryText.Text=$"状态：{data.State}；{data.Conclusion}";
        ReportText.Text="图文报告："+_reportHtml+"\n原始采集："+data.AcquisitionFolder;
        if(data.Analysis is not { } a)
        {
            QualityText.Text="分析未成功："+data.FailureReason;return;
        }
        var q=a.TimeQuality;
        QualityText.Text=$"批次时标等级：{q.Classification}；有效16帧批次{q.Batches}，"+
            $"MCU记录{q.McuDurationSeconds/60:F3}分钟；断点{q.GapOrOverlapIntervals}。"+
            (a.MetricsReleased?"仅工程估计，待验收":"积分质量不合格，未发布结果："+data.FailureReason);
        if(!a.MetricsReleased)return;
        static string F(double value,string fmt="F5")=>value.ToString(fmt,CultureInfo.InvariantCulture);
        static string FN(double? value)=>value is null?"N/A":F(value.Value);
        AxisGrid.ItemsSource=a.Axes.Select(x=>new
        {
            x.Axis,Min10=FN(x.DriftAt10MinutesDeg),Min30=FN(x.DriftAt30MinutesDeg),
            Last=F(x.FinalAngleDeg),Peak=F(x.MaxAbsoluteAngleDeg),
            Slope=F(x.LeastSquaresSlopeDegPerMinute,"F7"),Rate=F(x.MeanRateDps,"F7")
        }).ToArray();
        CurveGrid.ItemsSource=a.Curve.Select(x=>new
        {
            T=F(x.ElapsedSeconds,"F2"),X=F(x.GxDeg,"F5"),Y=F(x.GyDeg,"F5"),
            Z=F(x.GzDeg,"F5"),Temp=F(x.TemperatureC,"F2"),
            Acc=F(x.AccAngleFromStartDeg,"F5")
        }).ToArray();
        Tabs.SelectedIndex=0;
    }
    private void StopClick(object sender,RoutedEventArgs e)
    {
        StatusText.Text="正在取消记录并写盘，本测试不会发送转台运动指令";
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
        MessageBox.Show(this,"正在取消长时采集，请等待真实FIFO CSV写盘结束后再关闭窗口。",
            "CT-22记录中",MessageBoxButton.OK,MessageBoxImage.Warning);
    }
}
