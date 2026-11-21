using System.ComponentModel;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Windows;
using System.Windows.Controls;
using Dts.Core;
using Dts.TestEngine;
using Dts.Tests.S1.CT10;
using Dts.Tests.S1.CT27;
using Dts.Wpf.TestWindows;

namespace Dts.Wpf.TestWindows.CT27;

[TestWindowFor("CT-27")]
public partial class CT27Window : Window, ICalibrationRunAware
{
    private readonly TestDefinition _definition;
    private readonly ITestModule _module;
    private readonly ITestHardware _hardware;
    private readonly TestRunner _runner;
    private readonly string _root;
    private CalibrationRun _calibration = CalibrationRun.Raw;
    private CancellationTokenSource? _cts;
    private DateTime _startedUtc = DateTime.MaxValue;
    private string? _htmlReport;
    private bool _calibrationReady;
    private bool _planValid;

    public CT27Window(TestDefinition definition, ITestModule module, ITestHardware hardware,
        TestRunner runner, string outputRoot)
    {
        InitializeComponent();
        _definition = definition;
        _module = module;
        _hardware = hardware;
        _runner = runner;
        _root = outputRoot;
        IdentityText.Text = hardware.CurrentIdentity is { } id
            ? $"设备：{id.DtsId} / 完整UID：{id.UidHex}"
            : "IMU尚未连接或未读取完整UID";
        StatusText.Text = "报告根目录：" + outputRoot;
        RefreshBridge();
        RefreshPlan();
    }

    public void SetCalibrationRun(CalibrationRun run)
    {
        _calibration = run;
        _calibrationReady = false;
        try
        {
            var id = _hardware.CurrentIdentity ?? throw new InvalidOperationException("IMU未连接或完整UID不可用");
            if (run.Mode != CalibrationMode.Ambient)
                throw new InvalidOperationException("CT-27当前仅使用常温标定模式");
            run.Validate(id);
            var acc = run.Files?.Acc ?? throw new InvalidDataException("缺少UID匹配的ACC常温JSON");
            var gyro = run.Files?.Gyro ?? throw new InvalidDataException("缺少UID匹配的Gyro常温JSON");
            if (acc.FsHint is null || gyro.FsHint is null)
                throw new InvalidDataException("ACC/Gyro JSON缺少历史拟合输入量程");
            CalibrationText.Text = $"UID匹配常温JSON：ACC {Path.GetFileName(acc.FilePath)}（±{acc.FsHint}g）；" +
                $"Gyro {Path.GetFileName(gyro.FilePath)}（±{gyro.FsHint}°/s）";
            _calibrationReady = true;
        }
        catch (Exception ex)
        {
            CalibrationText.Text = "常温标定未就绪：" + ex.Message;
        }
        RefreshBridge();
        RefreshPlan();
    }

    private static double D(TextBox box, string label)
    {
        if (!double.TryParse(box.Text.Trim(), NumberStyles.Float, CultureInfo.InvariantCulture, out double value) ||
            !double.IsFinite(value))
            throw new InvalidDataException(label + "必须为有效数字（使用英文小数点）");
        return value;
    }

    private static int I(TextBox box, string label)
    {
        if (!int.TryParse(box.Text.Trim(), NumberStyles.Integer, CultureInfo.InvariantCulture, out int value))
            throw new InvalidDataException(label + "必须为整数");
        return value;
    }

    private Ct27Settings BuildSettings() => new(
        _root,
        RatesBox.Text,
        AxisZ.IsChecked == true,
        AxisX.IsChecked == true,
        I(RepeatsBox, "每工况重复次数"),
        D(TravelMinBox, "运动起点"),
        D(TravelMaxBox, "运动终点"),
        D(ApprovedMinBox, "批准行程下界"),
        D(ApprovedMaxBox, "批准行程上界"),
        D(SetupSpeedBox, "准备定位速度"),
        D(SettleBox, "运动前静置时间"),
        D(BaselineBox, "运动前基线时长"),
        D(RecoveryBox, "运动后恢复观察时长"),
        D(BinBox, "恢复窗口时长"),
        D(BandBox, "零偏恢复观察带"),
        I(ConsecutiveBox, "连续稳定窗口数"),
        I(MinSamplesBox, "每窗最少有效帧"),
        MotionApproval.IsChecked == true,
        EmergencyApproval.IsChecked == true,
        MappingApproval.IsChecked == true,
        _calibration);

    private IStaticAngleHardware? Host => _hardware as IStaticAngleHardware;
    private ICt10DynamicHardware? Dynamic => Host is { } host ? Ct10DynamicBridge.Resolve(host) : null;

    private void RefreshBridge()
    {
        if (BridgeText is null || StartButton is null || AxisZ is null || AxisX is null ||
            MotionApproval is null || EmergencyApproval is null || MappingApproval is null) return;
        var host = Host;
        var bridge = Dynamic;
        if (host is null)
        {
            BridgeText.Text = "主程序硬件对象不支持IStaticAngleHardware，禁止执行。";
            StartButton.IsEnabled = false;
            return;
        }
        if (bridge is null)
        {
            BridgeText.Text = "CT-10真实动态桥未注册；CT-27不另开COM连接，也不会用命令速率冒充实测运动。";
            StartButton.IsEnabled = false;
            return;
        }
        if (!bridge.IsRealDynamicCaptureReady)
        {
            BridgeText.Text = "CT-10动态桥尚未就绪。请先核验ct10_machine_profile.json中的FIFO槽位、时序说明和每轴限速；当前禁止运动。";
            StartButton.IsEnabled = false;
            return;
        }
        string inner = AxisZ.IsChecked == true
            ? $"内轴/Gyro Z限速{bridge.MaximumCertifiedSpeedDps(Ct10Axis.Inner):F2}°/s；" : string.Empty;
        string outer = AxisX.IsChecked == true
            ? $"外轴/Gyro X限速{bridge.MaximumCertifiedSpeedDps(Ct10Axis.Outer):F2}°/s。" : string.Empty;
        BridgeText.Text = "复用CT-10真实动态适配器：" + bridge.HardwareSourceDescription + " " + inner + outer;
        StartButton.IsEnabled = _calibrationReady && _planValid && _cts is null &&
            (AxisZ.IsChecked == true || AxisX.IsChecked == true) &&
            MotionApproval.IsChecked == true && EmergencyApproval.IsChecked == true &&
            MappingApproval.IsChecked == true;
    }

    private void RefreshPlan()
    {
        if (PlanText is null || RatesBox is null || AxisZ is null || AxisX is null ||
            RepeatsBox is null || TravelMinBox is null || TravelMaxBox is null ||
            ApprovedMinBox is null || ApprovedMaxBox is null || SetupSpeedBox is null ||
            SettleBox is null || BaselineBox is null || RecoveryBox is null || BinBox is null ||
            BandBox is null || ConsecutiveBox is null || MinSamplesBox is null ||
            MotionApproval is null || EmergencyApproval is null || MappingApproval is null) return;
        _planValid = false;
        try
        {
            Ct27Settings settings = BuildSettings();
            Ct27Algorithm.ValidateSettings(settings, requireSafety: false);
            var plan = Ct27Algorithm.PreviewPlan(settings);
            double captureMinutes = plan.Count * (settings.BaselineSeconds + settings.RecoverySeconds) / 60d;
            PlanGrid.ItemsSource = plan.Select(x => new
            {
                x.Index,
                Axis = x.Axis == Ct10Axis.Inner ? "内轴 / Gyro Z" : "外轴 / Gyro X",
                Rate = x.CommandDps,
                Direction = x.DirectionText,
                x.Repetition,
                x.StartDeg,
                x.EndDeg
            }).ToArray();
            PlanText.Text = $"计划{plan.Count}个真实运动工况（{(settings.TestInner ? "内轴/Gyro Z " : string.Empty)}{(settings.TestOuter ? "外轴/Gyro X" : string.Empty)}）；" +
                $"速率{settings.SpeedsCsv}°/s；每档正反向各{settings.Repetitions}次。" +
                $"基线{settings.BaselineSeconds:F0}s + 恢复观察{settings.RecoverySeconds:F0}s，预计采样约{captureMinutes:F1}分钟（不含运动/定位时间）。";
            _planValid = true;
        }
        catch (Exception ex)
        {
            PlanGrid.ItemsSource = null;
            PlanText.Text = "参数预览待调整：" + ex.Message;
        }
        RefreshBridge();
    }

    private void SettingsChanged(object sender, TextChangedEventArgs e) => RefreshPlan();
    private void SettingsChanged(object sender, RoutedEventArgs e) => RefreshPlan();

    private void PreviewClick(object sender, RoutedEventArgs e)
    {
        RefreshBridge();
        RefreshPlan();
        MessageBox.Show(this, PlanText.Text + "\n\n" + BridgeText.Text +
            "\n\n预览不会连接或驱动转台，也不会生成测试结果。",
            "CT-27工况计划预览", MessageBoxButton.OK, MessageBoxImage.Information);
    }

    private async void StartClick(object sender, RoutedEventArgs e)
    {
        if (_cts is not null) return;
        try
        {
            if (_module.TestId != "CT-27" || !_module.IsExecutable)
                throw new InvalidOperationException("CT-27模块未正确注册或尚未编译");
            if (_runner.IsRunning) throw new InvalidOperationException("主程序已有其他测试正在执行");
            var host = Host ?? throw new InvalidOperationException("主程序真实硬件接口不可用");
            var dynamic = Dynamic ?? throw new NotSupportedException("CT-10真实动态桥未注册");
            if (!host.IsTwoTdConnected) throw new InvalidOperationException("请先连接真实2TD-600");
            if (!dynamic.IsRealDynamicCaptureReady)
                throw new NotSupportedException("CT-10动态profile尚未通过核验，禁止CT-27运动");
            var id = host.CurrentIdentity ?? throw new InvalidOperationException("IMU未连接或UID不可用");
            if (!string.Equals(dynamic.CurrentUidHex, id.UidHex, StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("CT-10动态适配器UID与主界面IMU UID不一致");
            Ct27Settings settings = BuildSettings();
            settings.Calibration.Validate(id);
            var plan = Ct27Algorithm.BuildPlan(settings, dynamic);
            await host.VerifyImuForPrecisionTestAsync(CancellationToken.None);
            var initial = await dynamic.ReadStageAsync(CancellationToken.None);
            if (!initial.InnerEnabled || !initial.OuterEnabled || !initial.InnerNormal || !initial.OuterNormal ||
                !initial.InnerStationary || !initial.OuterStationary)
                throw new IOException("启动前2TD双轴必须正常使能且完全静止：" + initial.Detail);

            string axes = string.Join("、", plan.Select(x => x.Axis == Ct10Axis.Inner ? "内轴/Gyro Z" : "外轴/Gyro X").Distinct());
            double minutes = plan.Count * (settings.BaselineSeconds + settings.RecoverySeconds) / 60d;
            string rates = string.Join(", ", Ct27Algorithm.ParseRates(settings.SpeedsCsv).Select(x => x.ToString("0.###", CultureInfo.InvariantCulture)));
            if (MessageBox.Show(this,
                $"设备：{id.DtsId}\n完整UID：{id.UidHex}\n轴：{axes}\n速率：{rates}°/s\n" +
                $"每个工况：运动前基线{settings.BaselineSeconds:F0}s + 单向真实扫描 + 运动后恢复观察{settings.RecoverySeconds:F0}s\n" +
                $"计划工况：{plan.Count}；预计采样时间约{minutes:F1}分钟（不含定位和运动时间）\n" +
                $"扫描范围：{settings.TravelMinDeg:F1}°～{settings.TravelMaxDeg:F1}°；批准范围：{settings.ApprovedMinDeg:F1}°～{settings.ApprovedMaxDeg:F1}°\n\n" +
                "请再次确认工装、线缆、转台行程、实体急停、现场监护及Gyro轴向映射。CT-27将真实驱动2TD；若取消或异常，程序请求双轴软停车。",
                "CT-27真实运动测试安全确认", MessageBoxButton.YesNo, MessageBoxImage.Warning) != MessageBoxResult.Yes)
                return;

            _startedUtc = DateTime.UtcNow;
            _htmlReport = null;
            CyclesGrid.ItemsSource = null;
            OutputText.Text = "真实采集进行中；不会提前判PASS";
            _cts = new CancellationTokenSource();
            StartButton.IsEnabled = false;
            StopButton.IsEnabled = true;
            CloseButton.IsEnabled = false;
            OpenReportButton.IsEnabled = false;
            ProgressBar.Value = 0;
            var progress = new Progress<string>(message =>
            {
                StatusText.Text = message;
                Match match = Regex.Match(message, @"\[(\d+)/(\d+)\]");
                if (match.Success && int.TryParse(match.Groups[1].Value, out int current) &&
                    int.TryParse(match.Groups[2].Value, out int total) && total > 0)
                    ProgressBar.Value = Math.Clamp(current * 100d / total, 0, 100);
            });
            var context = new TestExecutionContext(_definition, TimeSpan.FromSeconds(settings.BinSeconds), host, progress, settings);
            TestExecutionResult result = await _runner.RunAsync(_module, context, _cts.Token);
            StatusText.Text = result.Summary;
            ProgressBar.Value = 100;
            string? json = result.Files.FirstOrDefault(x =>
                x.EndsWith("CT-27_result.json", StringComparison.OrdinalIgnoreCase));
            if (json is not null && File.Exists(json)) ShowReport(json);
        }
        catch (OperationCanceledException)
        {
            StatusText.Text = "CT-27已取消；模块已请求双轴软停车并保留部分数据。请确认转台实际静止。";
            TryLoadPartial();
        }
        catch (Exception ex)
        {
            StatusText.Text = "CT-27执行中止：" + ex.Message;
            TryLoadPartial();
            MessageBox.Show(this, ex.ToString(), "CT-27错误", MessageBoxButton.OK, MessageBoxImage.Warning);
        }
        finally
        {
            _cts?.Dispose();
            _cts = null;
            StopButton.IsEnabled = false;
            CloseButton.IsEnabled = true;
            RefreshBridge();
        }
    }

    private void ShowReport(string jsonPath)
    {
        Ct27ReportData data = JsonSerializer.Deserialize<Ct27ReportData>(File.ReadAllText(jsonPath))
            ?? throw new InvalidDataException("CT-27结果JSON无法读取");
        CyclesGrid.ItemsSource = data.Cycles;
        var aggregate = data.Aggregate;
        OutputText.Text = $"报告目录：{Path.GetDirectoryName(jsonPath)}\n" +
            $"HTML：{Path.Combine(Path.GetDirectoryName(jsonPath)!, "CT-27_report.html")}\n" +
            $"完成工况：{data.Cycles.Count}；观察到恢复：{aggregate?.RecoveryObservedCycles ?? 0}；恢复窗口：{data.Bins.Count}";
        _htmlReport = Path.Combine(Path.GetDirectoryName(jsonPath)!, "CT-27_report.html");
        OpenReportButton.IsEnabled = File.Exists(_htmlReport);
    }

    private void TryLoadPartial()
    {
        try
        {
            var id = _hardware.CurrentIdentity;
            if (id is null || _startedUtc == DateTime.MaxValue) return;
            string parent = Path.Combine(_root, id.DtsId + "_" + id.UidHex);
            if (!Directory.Exists(parent)) return;
            string? folder = Directory.EnumerateDirectories(parent, "*_CT-27")
                .Where(x => Directory.GetCreationTimeUtc(x) >= _startedUtc.AddSeconds(-5))
                .OrderByDescending(Directory.GetCreationTimeUtc).FirstOrDefault();
            if (folder is null) return;
            string json = Path.Combine(folder, "CT-27_result.json");
            if (!File.Exists(json)) json = Path.Combine(folder, "CT-27_checkpoint.json");
            if (File.Exists(json)) ShowReport(json);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or JsonException)
        {
            OutputText.Text = "部分报告读取失败：" + ex.Message;
        }
    }

    private void StopClick(object sender, RoutedEventArgs e)
    {
        _cts?.Cancel();
        StopButton.IsEnabled = false;
        StatusText.Text = "已请求取消；测试模块将请求双轴软停车。若转台未停止，请立即使用实体急停。";
    }

    private void OpenReportClick(object sender, RoutedEventArgs e)
    {
        if (!string.IsNullOrWhiteSpace(_htmlReport) && File.Exists(_htmlReport))
            Process.Start(new ProcessStartInfo(_htmlReport) { UseShellExecute = true });
    }

    private void CloseClick(object sender, RoutedEventArgs e)
    {
        if (_cts is not null)
        {
            MessageBox.Show(this, "CT-27仍在执行或保存数据。请先取消并等待双轴软停车确认后再关闭。", "CT-27运行中");
            return;
        }
        Close();
    }

    private void OnClosing(object? sender, CancelEventArgs e)
    {
        if (_cts is null) return;
        e.Cancel = true;
        _cts.Cancel();
        MessageBox.Show(this, "CT-27正在安全结束。请确认转台完全静止、数据保存完成后再关闭窗口。",
            "CT-27停止中", MessageBoxButton.OK, MessageBoxImage.Warning);
    }
}
