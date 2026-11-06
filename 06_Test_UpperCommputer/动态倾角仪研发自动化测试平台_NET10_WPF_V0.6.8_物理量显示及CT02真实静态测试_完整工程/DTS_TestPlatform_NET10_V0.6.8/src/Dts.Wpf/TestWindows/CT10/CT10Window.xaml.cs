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

namespace Dts.Wpf.TestWindows.CT10;

[Dts.Wpf.TestWindows.TestWindowFor("CT-10")]
public partial class CT10Window : Window, Dts.Wpf.TestWindows.ICalibrationRunAware
{
    private readonly TestDefinition _definition;
    private readonly ITestModule _module;
    private readonly IStaticAngleHardware _hardware;
    private readonly TestRunner _runner;
    private readonly string _outputRoot;
    private CalibrationRun _calibration = CalibrationRun.Raw;
    private CancellationTokenSource? _cts;
    private string? _html;
    private DateTime _startUtc;

    public CT10Window(TestDefinition definition, ITestModule module,
        IStaticAngleHardware hardware, TestRunner runner, string outputRoot)
    {
        InitializeComponent();
        _definition = definition; _module = module;
        _hardware = hardware; _runner = runner; _outputRoot = outputRoot;
        OutputText.Text = outputRoot;
        UidText.Text = hardware.CurrentIdentity is { } id
            ? $"设备 {id.DtsId} / UID {id.UidHex} / 2TD {(hardware.IsTwoTdConnected ? "已连接" : "未连接")}" :
            "IMU尚未获取完整UID";
        RefreshBridge();
    }

    public void SetCalibrationRun(CalibrationRun calibration)
    {
        _calibration = calibration;
        try
        {
            var id = _hardware.CurrentIdentity ?? throw new InvalidOperationException("IMU尚未连接");
            if (calibration.Mode != CalibrationMode.Ambient)
                throw new InvalidOperationException("本版CT-10要求先在主界面选择常温标定");
            calibration.Validate(id);
            var gyro = calibration.Files?.Gyro ?? throw new InvalidDataException("Gyro UID JSON不存在");
            var acc = calibration.Files?.Acc ?? throw new InvalidDataException("ACC UID JSON不存在");
            CalibrationText.Text = $"Gyro：{Path.GetFileName(gyro.FilePath)}\n"+
                $"ACC：{Path.GetFileName(acc.FilePath)}\nGyro历史拟合输入 ±{gyro.FsHint}°/s";
        }
        catch (Exception ex) { CalibrationText.Text = "标定尚未就绪：" + ex.Message; }
        RefreshBridge();
    }

    private void RefreshBridge()
    {
        if (BridgeText is null || StartButton is null) return;
        var bridge = Ct10DynamicBridge.Resolve(_hardware);
        bool ready = bridge?.IsRealDynamicCaptureReady == true;
        BridgeText.Text = ready
            ? $"真实动态设备适配器就绪（工程诊断，非硬件时间同步）：{bridge!.HardwareSourceDescription}\n核验的限速：内轴 {bridge.MaximumCertifiedSpeedDps(Ct10Axis.Inner):F3}°/s、外轴 {bridge.MaximumCertifiedSpeedDps(Ct10Axis.Outer):F3}°/s"
            : bridge is null
                ? "动态接口未注册：可先编辑并预览扫描参数，但不能启动测试。请检查适配器注册。"
                : "动态接口未就绪：可预览全部测试计划，但不能启动。请核验实时IMU/2TD、常温标定与ct10_machine_profile.json（默认禁用）。";
        StartButton.IsEnabled = ready && _cts is null;
        if (!ready && _cts is null && ReportText is not null && _html is null)
            ReportText.Text = "当前只是参数预览：尚未完成真实动态采样，不会凭空生成结果报告。设备就绪并实测后自动导出CSV/JSON/HTML/Excel。";
        RefreshPlan();
    }

    private static double ReadDouble(TextBox box)
    {
        if (!double.TryParse(box.Text.Trim(), NumberStyles.Float,
            CultureInfo.InvariantCulture, out double result) || !double.IsFinite(result))
            throw new InvalidDataException($"{box.Name}必须是有效数字，使用英文小数点");
        return result;
    }
    private static int ReadInt(TextBox box)
    {
        if (!int.TryParse(box.Text.Trim(), NumberStyles.Integer,
            CultureInfo.InvariantCulture, out int n))
            throw new InvalidDataException($"{box.Name}必须是整数");
        return n;
    }

    private Ct10Settings Settings() => new(_outputRoot, Speeds.Text.Trim(),
        InnerAxis.IsChecked == true, OuterAxis.IsChecked == true,
        ReadInt(RepeatCount), ReadDouble(TravelMin), ReadDouble(TravelMax),
        ReadDouble(ApprovedMin), ReadDouble(ApprovedMax), ReadDouble(SetupSpeed), ReadDouble(SettleSeconds), ReadDouble(SpeedTolerance),
        ReadDouble(EncoderWindow), ReadInt(MinFrames),
        InvertInner.IsChecked == true ? -1 : 1,
        InvertOuter.IsChecked == true ? -1 : 1,
        MotionApproval.IsChecked == true, EmergencyApproval.IsChecked == true,
        SensorMappingApproval.IsChecked == true, _calibration);

    private void RefreshPlan()
    {
        if (Speeds is null || InnerAxis is null || OuterAxis is null || PlanGrid is null ||
            PlanSummary is null || RepeatCount is null || TravelMin is null || TravelMax is null ||
            ApprovedMin is null || ApprovedMax is null ||
            SetupSpeed is null || SpeedTolerance is null || EncoderWindow is null || MinFrames is null ||
            SettleSeconds is null || InvertInner is null || InvertOuter is null ||
            MotionApproval is null || EmergencyApproval is null || SensorMappingApproval is null)
            return;
        try
        {
            var s = Settings();
            // A CT-07-style preview must work without connecting/authorizing dynamic motion.
            var plan = Ct10Algorithm.PreviewPlan(s);
            PlanGrid.ItemsSource = plan;
            var bridge = Ct10DynamicBridge.Resolve(_hardware);
            bool hardwareReady = bridge?.IsRealDynamicCaptureReady == true;
            string speedApproval = hardwareReady
                ? "动态适配器就绪；实际点击运行还会核验每轴限速、UID、标定及现场安全确认。"
                : "仅软件参数预览：真实动态采集尚未核验，速度上限未批准，禁止自动旋转。";
            PlanSummary.Text = $"{plan.Count}段（{plan.Count / 2}次正反配对），" +
                $"速率 {s.SpeedsCsv}°/s；{s.TravelMinDeg:F2}° → {s.TravelMaxDeg:F2}°，固定轴 0°。" +
                speedApproval;
        }
        catch (Exception ex)
        {
            PlanGrid.ItemsSource = null;
            PlanSummary.Text = "参数/设备限速检查：" + ex.Message;
        }
    }
    private void SettingsChanged(object sender, TextChangedEventArgs e) => RefreshPlan();
    private void AxesChanged(object sender, RoutedEventArgs e) => RefreshPlan();
    private void PreviewClick(object sender, RoutedEventArgs e)
    {
        RefreshBridge();
        MessageBox.Show(this, PlanSummary.Text, "CT-10 多速率计划预览",
            MessageBoxButton.OK, MessageBoxImage.Information);
    }

    private async void StartClick(object sender, RoutedEventArgs e)
    {
        if (_cts is not null) return;
        try
        {
            var hw = Ct10DynamicBridge.Resolve(_hardware);
            if (hw is null || !hw.IsRealDynamicCaptureReady)
                throw new NotSupportedException("尚未接通真实动态数据源，请先完成一次设备适配");
            var id = _hardware.CurrentIdentity ?? throw new InvalidOperationException("尚未连接IMU并读取UID");
            if (!_hardware.IsTwoTdConnected) throw new InvalidOperationException("2TD未连接");
            if (_module.TestId != "CT-10" || !_module.IsExecutable)
                throw new InvalidOperationException("CT-10注册编号与模块不符");
            if (_calibration.Mode != CalibrationMode.Ambient)
                throw new InvalidOperationException("请先在主界面选择常温标定后重新打开CT-10窗口");
            _calibration.Validate(id);
            if (!Directory.Exists(_outputRoot)) throw new DirectoryNotFoundException("报告根目录不存在");
            var settings = Settings();
            var plan = Ct10Algorithm.BuildPlan(settings, hw);
            if (MessageBox.Show(this,
                $"设备UID：{id.UidHex}\n轴数：{(settings.TestInner ? 1 : 0) + (settings.TestOuter ? 1 : 0)}\n"+
                $"速度：{settings.SpeedsCsv} °/s\n共{plan.Count}次真实连续运动\n"+
                $"扫描范围：{settings.TravelMinDeg:F2}°～{settings.TravelMaxDeg:F2}°\n"+
                $"现场批准范围：{settings.ApprovedMinDeg:F2}°～{settings.ApprovedMaxDeg:F2}°\n"+
                "启动后自动运行所有速度/方向，不再逐项询问。请再次确认所有行程安全、实体急停、轴向和人员现场监护。",
                "CT-10 真实动态扫描确认", MessageBoxButton.YesNo,
                MessageBoxImage.Warning) != MessageBoxResult.Yes)
                return;
            _cts = new CancellationTokenSource(); _startUtc = DateTime.UtcNow;
            _html = null; ReportButton.IsEnabled = false; StartButton.IsEnabled = false;
            StopButton.IsEnabled = true; PreviewButton.IsEnabled = false;
            RunProgress.Value = 0; ResultGrid.ItemsSource = null;
            var progress = new Progress<string>(message =>
            {
                StatusText.Text = message;
                var match = System.Text.RegularExpressions.Regex.Match(message, @"\[(\d+)/(\d+)\]");
                if (match.Success && double.TryParse(match.Groups[1].Value, out double step) &&
                    double.TryParse(match.Groups[2].Value, out double total) && total > 0)
                    RunProgress.Value = Math.Clamp(step / total * 100, 0, 100);
            });
            var context = new TestExecutionContext(_definition, TimeSpan.FromSeconds(settings.SettleSeconds),
                _hardware, progress, settings);
            var outcome = await _runner.RunAsync(_module, context, _cts.Token);
            StatusText.Text = outcome.Summary;
            string? json = outcome.Files.FirstOrDefault(x => x.EndsWith("CT-10_result.json",
                StringComparison.OrdinalIgnoreCase));
            if (json is not null && File.Exists(json)) ShowResult(json);
        }
        catch (OperationCanceledException)
        {
            StatusText.Text = "操作取消，正在保存完成的扫描段并请求双轴软停车";
            TryLoadPartial();
        }
        catch (Exception ex)
        {
            StatusText.Text = "CT-10已中止：" + ex.Message;
            TryLoadPartial();
            MessageBox.Show(this, ex.Message, "CT-10执行中止", MessageBoxButton.OK,
                MessageBoxImage.Warning);
        }
        finally
        {
            _cts?.Dispose(); _cts = null;
            PreviewButton.IsEnabled = true; StopButton.IsEnabled = false;
            RefreshBridge();
        }
    }
    private void ShowResult(string path)
    {
        var data = JsonSerializer.Deserialize<Ct10ReportData>(File.ReadAllText(path))
            ?? throw new InvalidDataException("CT-10报告反序列化失败");
        ResultGrid.ItemsSource = data.SpeedPairs.Select(p => new
        {
            Axis = p.Axis.ToString(), Speed = p.SpeedDps.ToString("F3", CultureInfo.InvariantCulture),
            p.PairCount, Forward = p.ForwardMeanResidualDps.ToString("F5", CultureInfo.InvariantCulture),
            Reverse = p.ReverseMeanResidualDps.ToString("F5", CultureInfo.InvariantCulture),
            Delta = p.SignedDirectionDifferenceDps.ToString("F5", CultureInfo.InvariantCulture)
        }).ToArray();
        SummaryText.Text = $"状态 {data.State} · 完成 {data.Sweeps.Count} 段真实运动，"+
            $"{data.SpeedPairs.Count}个轴/速度配对，待验收";
        MetricsText.Text = data.SpeedPairs.Count == 0 ? "未形成完整有效正反配对" :
            $"正反残差差值绝对最大：{data.SpeedPairs.Max(p=>Math.Abs(p.SignedDirectionDifferenceDps)):F5} °/s";
        ResultTabs.SelectedIndex = 1;
        _html = Path.Combine(Path.GetDirectoryName(path)!, "CT-10_report.html");
        ReportButton.IsEnabled = File.Exists(_html);
        ReportText.Text = "报告目录：" + Path.GetDirectoryName(path);
    }
    private void TryLoadPartial()
    {
        try
        {
            var id = _hardware.CurrentIdentity;
            if (id is null || _startUtc == default) return;
            string root = Path.Combine(_outputRoot, id.DtsId + "_" + id.UidHex);
            if (!Directory.Exists(root)) return;
            var directory = Directory.EnumerateDirectories(root, "*_CT-10")
                .Where(x => Directory.GetCreationTimeUtc(x) >= _startUtc.AddSeconds(-5))
                .OrderByDescending(Directory.GetCreationTimeUtc).FirstOrDefault();
            if (directory is null) return;
            string file = Path.Combine(directory, "CT-10_result.json");
            if (File.Exists(file)) ShowResult(file);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or JsonException)
        {
            ReportText.Text = "部分报告暂无法预览：" + ex.Message;
        }
    }
    private async void StopClick(object sender, RoutedEventArgs e)
    {
        _cts?.Cancel();
        StopButton.IsEnabled = false;
        StatusText.Text = "已请求取消并立即发出双轴软停车命令；必要时使用实体急停";
        var bridge = Ct10DynamicBridge.Resolve(_hardware);
        if (bridge is not null)
        {
            using var stop = new CancellationTokenSource(TimeSpan.FromSeconds(5));
            try { await bridge.StopBothAxesAsync(stop.Token); }
            catch (Exception ex)
            {
                StatusText.Text = "危险：停止命令未确认，请使用实体急停并检查现场：" + ex.Message;
            }
        }
    }
    private void ReportClick(object sender, RoutedEventArgs e)
    {
        if (_html is not null && File.Exists(_html))
            Process.Start(new ProcessStartInfo(_html) { UseShellExecute = true });
    }
    private void CloseClick(object sender, RoutedEventArgs e) => Close();
    private void OnClosing(object? sender, CancelEventArgs e)
    {
        if (_cts is null) return;
        e.Cancel = true;
        _cts.Cancel();
        MessageBox.Show(this, "CT-10运行中，已请求取消。请等运动停止并确认现场安全后关闭。",
            "CT-10正在停止", MessageBoxButton.OK, MessageBoxImage.Warning);
    }
}
