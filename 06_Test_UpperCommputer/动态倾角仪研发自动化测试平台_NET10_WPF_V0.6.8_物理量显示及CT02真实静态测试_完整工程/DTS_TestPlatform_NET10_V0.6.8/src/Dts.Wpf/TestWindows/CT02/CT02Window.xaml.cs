using System.ComponentModel;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using Dts.Core;
using Dts.TestEngine;
using Dts.Tests.S1.CT02;

namespace Dts.Wpf.TestWindows.CT02;

[Dts.Wpf.TestWindows.TestWindowFor("CT-02")]
public partial class CT02Window : Window, Dts.Wpf.TestWindows.ICalibrationRunAware
{
    private readonly TestDefinition _definition;
    private readonly ITestModule _module;
    private readonly IStaticAngleHardware _hardware;
    private readonly TestRunner _runner;
    private readonly string _outputRoot;
    private CalibrationRun _run = CalibrationRun.Raw;
    private CancellationTokenSource? _cts;
    private string? _htmlReport;

    public CT02Window(TestDefinition definition, ITestModule module, IStaticAngleHardware hardware,
        TestRunner runner, string outputRoot)
    {
        InitializeComponent();
        _definition = definition;
        _module = module;
        _hardware = hardware;
        _runner = runner;
        _outputRoot = outputRoot;
        RootText.Text = outputRoot;
        UidText.Text = hardware.CurrentIdentity is { } id
            ? $"DTS: {id.DtsId}    MCU UID: {id.UidHex}" : "未读取真实 IMU UID";
    }

    public void SetCalibrationRun(CalibrationRun run)
    {
        _run = run;
        try
        {
            var identity = _hardware.CurrentIdentity ?? throw new InvalidOperationException("请先连接IMU并读取完整UID");
            if (run.Mode != CalibrationMode.Ambient)
                throw new InvalidOperationException("本测试要求在主窗口选择『常温标定』");
            run.Validate(identity);
            CalibrationText.Text = $"ACC: {Path.GetFileName(run.Files!.Acc!.FilePath)}\n" +
                $"Gyro: {Path.GetFileName(run.Files.Gyro!.FilePath)}\n" +
                $"拟合输入：ACC ±{run.Files.Acc.FsHint}g；Gyro ±{run.Files.Gyro.FsHint}°/s";
        }
        catch (Exception ex)
        {
            CalibrationText.Text = "暂不可启动：" + ex.Message;
            StatusText.Text = CalibrationText.Text;
        }
    }

    private async void StartClick(object sender, RoutedEventArgs e)
    {
        if (_cts is not null) return;
        try
        {
            var id = _hardware.CurrentIdentity ?? throw new InvalidOperationException("请先连接真实IMU");
            if (!_module.IsExecutable) throw new InvalidOperationException("CT-02测试尚未注册");
            if (_run.Mode != CalibrationMode.Ambient)
                throw new InvalidOperationException("请在主窗口勾选常温标定并重新打开CT-02窗口");
            _run.Validate(id);
            if (!Directory.Exists(_outputRoot)) throw new DirectoryNotFoundException("报告根目录不存在");
            if (!double.TryParse(DurationBox.Text, NumberStyles.Float, CultureInfo.InvariantCulture, out var seconds) ||
                seconds < 5 || seconds > 1800)
                throw new InvalidDataException("采样时长应为 5～1800 秒");
            if (ReferenceBox.SelectedItem is not ComboBoxItem item ||
                !int.TryParse(item.Tag?.ToString(), out var sign) || sign is not (1 or -1))
                throw new InvalidDataException("请选择机械平台P坐标系已知的+Z或-Z重力方向");
            var settings = new Ct02Settings(_run, sign,
                LevelConfirmed.IsChecked == true, StationaryConfirmed.IsChecked == true);
            if (!settings.MechanicalZeroConfirmed || !settings.StationarityConfirmed)
                throw new InvalidOperationException("请先确认真实机械零位、静止状态和夹具安全");
            if (MessageBox.Show(this,
                $"设备：{id.DtsId}\n参考重力：{(sign > 0 ? "+Z" : "-Z")}\n采样时长：{seconds:F0}s\n\n" +
                "即将采集真实IMU数据，不会向转台发送运动指令。\n确认当前已知零位与稳定静止条件？",
                "CT-02 真实测试确认", MessageBoxButton.YesNo, MessageBoxImage.Warning) != MessageBoxResult.Yes)
                return;
            _htmlReport = null;
            ReportButton.IsEnabled = false;
            StartButton.IsEnabled = false;
            StopButton.IsEnabled = true;
            MetricsGrid.ItemsSource = null;
            MetricText.Text = "";
            _cts = new CancellationTokenSource();
            var progress = new Progress<string>(message => StatusText.Text = message);
            var context = new TestExecutionContext(_definition, TimeSpan.FromSeconds(seconds),
                _hardware, progress, settings);
            var result = await _runner.RunAsync(_module, context, _cts.Token);
            _htmlReport = result.Files.FirstOrDefault(f => f.EndsWith("CT-02_report.html", StringComparison.OrdinalIgnoreCase));
            ReportButton.IsEnabled = _htmlReport is not null && File.Exists(_htmlReport);
            StatusText.Text = result.Summary;
            FilesText.Text = _htmlReport ?? "已保存原始/已校正记录，未找到HTML报告";
            var resultJson = result.Files.FirstOrDefault(f => f.EndsWith("CT-02_result.json", StringComparison.OrdinalIgnoreCase));
            if (resultJson is not null) ShowReport(resultJson);
        }
        catch (OperationCanceledException) { StatusText.Text = "已取消：保留已写入的真实采集文件，不生成已完成结论"; }
        catch (Exception ex)
        {
            StatusText.Text = "未完成：" + ex.Message;
            MessageBox.Show(this, ex.Message, "CT-02 测试未完成", MessageBoxButton.OK, MessageBoxImage.Warning);
        }
        finally
        {
            _cts?.Dispose();
            _cts = null;
            StartButton.IsEnabled = true;
            StopButton.IsEnabled = false;
        }
    }

    private void ShowReport(string jsonPath)
    {
        var report = JsonSerializer.Deserialize<Ct02ReportData>(File.ReadAllText(jsonPath));
        if (report is null) return;
        var m = report.Metrics;
        var labels = new[] { "Ax", "Ay", "Az", "Gx", "Gy", "Gz" };
        MetricsGrid.ItemsSource = Enumerable.Range(0, 6).Select(i => new
        {
            Axis = labels[i],
            Mean = m.Means[i].ToString("F6", CultureInfo.InvariantCulture),
            Std = m.StandardDeviations[i].ToString("F6", CultureInfo.InvariantCulture),
            Unit = i < 3 ? "g" : "°/s"
        }).ToArray();
        SummaryText.Text = $"真实采集 {m.Samples}帧 / {m.DistinctMcuTicks}个MCU批次，参考 {report.ReferenceDescription}；待人工验收";
        MetricText.Text = $"Roll零位：{m.RollZeroDeg:F6}°   Pitch零位：{m.PitchZeroDeg:F6}°\n" +
            $"重力方向误差：{m.TotalGravityDirectionErrorDeg:F6}°；模长残差：{m.AccNormResidualG:F6}g\n" +
            $"Gyro零速矢量：{m.GyroZeroVectorNormDps:F6}°/s；温度均值：{m.MeanTemperatureC:F3}℃";
    }

    private void StopClick(object sender, RoutedEventArgs e) => _cts?.Cancel();
    private void CloseClick(object sender, RoutedEventArgs e) => Close();
    private void ReportClick(object sender, RoutedEventArgs e)
    {
        if (_htmlReport is not null && File.Exists(_htmlReport))
            Process.Start(new ProcessStartInfo(_htmlReport) { UseShellExecute = true });
    }
    private void OnClosing(object? sender, CancelEventArgs e)
    {
        if (_cts is not null)
        {
            e.Cancel = true;
            _cts.Cancel();
            MessageBox.Show(this, "正在取消真实采集并保存文件，完成后再关闭窗口。");
        }
    }
}
