using System.ComponentModel;
using System.Globalization;
using System.IO;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using Dts.Core;
using Dts.TestEngine;
using Dts.Tests.S1.CT10;
using Dts.Tests.S1.CT19;
using Dts.Wpf.TestWindows;

namespace Dts.Wpf.TestWindows.CT19;

[TestWindowFor("CT-19")]
public partial class CT19Window : Window, ICalibrationRunAware
{
    private readonly TestDefinition _definition;
    private readonly ITestModule _module;
    private readonly ITestHardware _hardware;
    private readonly TestRunner _runner;
    private readonly string _root;
    private CalibrationRun _calibration = CalibrationRun.Raw;
    private CancellationTokenSource? _cts;

    public CT19Window(TestDefinition definition, ITestModule module, ITestHardware hardware,
        TestRunner runner, string outputRoot)
    {
        InitializeComponent();
        _definition = definition;
        _module = module;
        _hardware = hardware;
        _runner = runner;
        _root = outputRoot;
        IdentityText.Text = hardware.CurrentIdentity is { } id
            ? $"设备：{id.DtsId} / UID：{id.UidHex}"
            : "IMU尚未连接或未读取完整UID";
        StatusText.Text = "主程序报告目录：" + outputRoot;
        RefreshBridge();
        RefreshPlan();
    }

    public void SetCalibrationRun(CalibrationRun run)
    {
        _calibration = run;
        try
        {
            var id = _hardware.CurrentIdentity ?? throw new InvalidOperationException("IMU尚未连接");
            if (run.Mode != CalibrationMode.Ambient)
                throw new InvalidOperationException("CT-19必须选择常温标定");
            run.Validate(id);
            var acc = run.Files?.Acc ?? throw new InvalidDataException("ACC常温JSON缺失");
            var gyro = run.Files?.Gyro ?? throw new InvalidDataException("Gyro常温JSON缺失");
            if (gyro.FsHint is null) throw new InvalidDataException("Gyro JSON缺少历史输入量程");
            CalibrationText.Text = $"UID匹配常温JSON：ACC {Path.GetFileName(acc.FilePath)}；Gyro {Path.GetFileName(gyro.FilePath)}；Gyro输入量程±{gyro.FsHint}°/s";
        }
        catch (Exception ex)
        {
            CalibrationText.Text = "常温标定未就绪：" + ex.Message;
        }
        RefreshPlan();
    }

    private static double D(TextBox box, string label)
    {
        if (!double.TryParse(box.Text.Trim(), NumberStyles.Float, CultureInfo.InvariantCulture, out double v) ||
            !double.IsFinite(v))
            throw new InvalidDataException(label + "必须为有效数字（使用英文小数点）");
        return v;
    }
    private static int I(TextBox box, string label)
    {
        if (!int.TryParse(box.Text.Trim(), NumberStyles.Integer, CultureInfo.InvariantCulture, out int v))
            throw new InvalidDataException(label + "必须为整数");
        return v;
    }

    private Ct19Settings BuildSettings() => new(
        _root, RatesBox.Text,
        AxisZ.IsChecked == true, AxisX.IsChecked == true,
        I(RepeatsBox, "重复次数"),
        D(TravelMinBox, "扫描起始角"), D(TravelMaxBox, "扫描终止角"),
        D(ApprovedMinBox, "批准行程下界"), D(ApprovedMaxBox, "批准行程上界"),
        D(SetupSpeedBox, "定位速度"), D(SettleBox, "静置时间"),
        D(SpeedToleranceBox, "速率允许偏差"), D(DerivativeWindowBox, "编码器微分窗口"),
        I(MinFramesBox, "最少有效帧"),
        InvertInner.IsChecked == true ? -1 : 1,
        InvertOuter.IsChecked == true ? -1 : 1,
        MotionApproval.IsChecked == true,
        EmergencyApproval.IsChecked == true,
        MappingApproval.IsChecked == true,
        _calibration);

    private IStaticAngleHardware? Host => _hardware as IStaticAngleHardware;
    private ICt10DynamicHardware? Dynamic => Host is { } h ? Ct10DynamicBridge.Resolve(h) : null;

    private void RefreshBridge()
    {
        var h = Host;
        var d = Dynamic;
        if (h is null)
        {
            BridgeText.Text = "主程序硬件对象不支持IStaticAngleHardware，禁止执行。";
            StartButton.IsEnabled = false;
            return;
        }
        if (d is null)
        {
            BridgeText.Text = "CT-10动态桥未注册；CT-19不会另开COM/DLL连接，也不会用静态采样冒充动态数据。";
            StartButton.IsEnabled = false;
            return;
        }
        BridgeText.Text = d.IsRealDynamicCaptureReady
            ? $"复用CT-10真实动态适配器：{d.HardwareSourceDescription}；内轴/Gyro Z限速{d.MaximumCertifiedSpeedDps(Ct10Axis.Inner):F2}°/s，外轴/Gyro X限速{d.MaximumCertifiedSpeedDps(Ct10Axis.Outer):F2}°/s。"
            : "CT-10动态适配器尚未通过profile核验；请检查ct10_machine_profile.json。当前禁止运动。";
        StartButton.IsEnabled = d.IsRealDynamicCaptureReady && _cts is null;
    }

    private void RefreshPlan()
    {
        if (PlanText is null || RatesBox is null) return;
        try
        {
            var s = BuildSettings();
            Ct19Algorithm.Validate(s);
            var p = Ct19Algorithm.PreviewPlan(s);
            var rates = Ct19Algorithm.ParseRates(s.SpeedsCsv);
            PlanText.Text = $"计划：{p.Count}段真实动态扫描（{(s.TestInner ? "内轴/Gyro Z " : "")}{(s.TestOuter ? "外轴/Gyro X" : "")}）；速率{string.Join(", ", rates.Select(x => x.ToString("0.###", CultureInfo.InvariantCulture)))}°/s；每档正反向各{s.Repetitions}次。10°/s不再作为软件上限，实际最高速率必须低于设备profile已核验限速。";
        }
        catch (Exception ex)
        {
            PlanText.Text = "参数预览待调整：" + ex.Message;
        }
    }

    private void SettingsChanged(object sender, TextChangedEventArgs e) => RefreshPlan();
    private void SettingsChanged(object sender, RoutedEventArgs e) => RefreshPlan();

    private void PreviewClick(object sender, RoutedEventArgs e)
    {
        RefreshBridge();
        RefreshPlan();
        MessageBox.Show(this, PlanText.Text + "\n\n" + BridgeText.Text,
            "CT-19测试计划预览", MessageBoxButton.OK, MessageBoxImage.Information);
    }

    private async void StartClick(object sender, RoutedEventArgs e)
    {
        if (_cts is not null) return;
        try
        {
            if (_module.TestId != "CT-19" || !_module.IsExecutable)
                throw new InvalidOperationException("CT-19模块未正确注册");
            if (_runner.IsRunning) throw new InvalidOperationException("主程序已有其他测试正在执行");
            var host = Host ?? throw new InvalidOperationException("主程序真实硬件接口不可用");
            var dynamic = Dynamic ?? throw new NotSupportedException("CT-10真实动态桥未注册");
            if (!host.IsTwoTdConnected) throw new InvalidOperationException("请先连接真实2TD-600");
            if (!dynamic.IsRealDynamicCaptureReady)
                throw new NotSupportedException("CT-10动态适配器未就绪。先完成固件FIFO槽位、时序不确定度和设备限速证据核验；不能绕过profile。");
            var id = host.CurrentIdentity ?? throw new InvalidOperationException("IMU未连接或UID不可用");
            if (!string.Equals(dynamic.CurrentUidHex, id.UidHex, StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("CT-10动态适配器UID与主界面UID不一致");
            var s = BuildSettings();
            Ct19Algorithm.Validate(s);
            s.Calibration.Validate(id);
            var plan = Ct19Algorithm.BuildPlan(s, dynamic);
            var rateSummary = string.Join(", ", Ct19Algorithm.ParseRates(s.SpeedsCsv).Select(x => x.ToString("0.###", CultureInfo.InvariantCulture)));
            if (MessageBox.Show(this,
                $"设备：{id.DtsId}\nUID：{id.UidHex}\n动态数据源：复用CT-10真实采集桥\n"+
                $"轴：{(s.TestInner ? "内轴/Gyro Z " : "")}{(s.TestOuter ? "外轴/Gyro X" : "")}\n"+
                $"速率：{rateSummary}°/s\n正反向各重复：{s.Repetitions}次\n"+
                $"扫描行程：{s.TravelMinDeg:F1}°～{s.TravelMaxDeg:F1}°\n"+
                $"计划真实运动段：{plan.Count}\n\n"+
                "确认工装、线缆、轴向符号、实体急停和现场监护。CT-19将真实驱动2TD；实际最高速率受profile已核验限速约束。",
                "CT-19真实动态测试确认", MessageBoxButton.YesNo, MessageBoxImage.Warning) != MessageBoxResult.Yes)
                return;

            _cts = new CancellationTokenSource();
            StartButton.IsEnabled = false;
            StopButton.IsEnabled = true;
            CloseButton.IsEnabled = false;
            PreviewButton.IsEnabled = false;
            ProgressBar.IsIndeterminate = true;
            RunsGrid.ItemsSource = null;
            GroupsGrid.ItemsSource = null;
            var progress = new Progress<string>(m => StatusText.Text = m);
            var context = new TestExecutionContext(_definition,
                TimeSpan.FromSeconds(0), host, progress, s);
            var result = await _runner.RunAsync(_module, context, _cts.Token);
            StatusText.Text = result.Summary;
            string? json = result.Files.FirstOrDefault(x =>
                x.EndsWith("CT-19_result.json", StringComparison.OrdinalIgnoreCase));
            if (json is not null && File.Exists(json)) ShowReport(json);
        }
        catch (OperationCanceledException)
        {
            StatusText.Text = "CT-19已取消；测试模块已请求双轴软停车并保留已完成数据。请确认转台实际静止。";
            TryLoadPartial();
        }
        catch (Exception ex)
        {
            StatusText.Text = "CT-19执行中止：" + ex.Message;
            TryLoadPartial();
            MessageBox.Show(this, ex.ToString(), "CT-19错误", MessageBoxButton.OK, MessageBoxImage.Warning);
        }
        finally
        {
            ProgressBar.IsIndeterminate = false;
            _cts?.Dispose();
            _cts = null;
            StopButton.IsEnabled = false;
            CloseButton.IsEnabled = true;
            PreviewButton.IsEnabled = true;
            RefreshBridge();
        }
    }

    private void ShowReport(string json)
    {
        var data = JsonSerializer.Deserialize<Ct19ReportData>(File.ReadAllText(json))
            ?? throw new InvalidDataException("CT-19报告JSON无法读取");
        RunsGrid.ItemsSource = data.Runs;
        GroupsGrid.ItemsSource = data.Groups;
        OutputText.Text = "报告目录：" + Path.GetDirectoryName(json) +
            "\nHTML：" + Path.Combine(Path.GetDirectoryName(json)!, "CT-19_report.html") +
            "\n逐段CSV数量：" + data.Runs.Count;
    }

    private void TryLoadPartial()
    {
        try
        {
            var id = _hardware.CurrentIdentity;
            if (id is null) return;
            string parent = Path.Combine(_root, id.DtsId + "_" + id.UidHex);
            if (!Directory.Exists(parent)) return;
            var folder = Directory.EnumerateDirectories(parent, "*_CT-19")
                .OrderByDescending(Directory.GetCreationTime).FirstOrDefault();
            if (folder is null) return;
            string json = Path.Combine(folder, "CT-19_result.json");
            if (!File.Exists(json)) json = Path.Combine(folder, "CT-19_checkpoint.json");
            if (File.Exists(json)) ShowReport(json);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or JsonException)
        {
            OutputText.Text = "部分报告预览失败：" + ex.Message;
        }
    }

    private void StopClick(object sender, RoutedEventArgs e)
    {
        _cts?.Cancel();
        StopButton.IsEnabled = false;
        StatusText.Text = "已请求取消。测试模块将请求双轴软停车；若转台未停止，请立即使用实体急停。";
    }

    private void CloseClick(object sender, RoutedEventArgs e)
    {
        if (_cts is not null)
        {
            MessageBox.Show(this, "请先取消并等待双轴停车确认后再关闭窗口。", "CT-19正在运行");
            return;
        }
        Close();
    }

    private void OnClosing(object? sender, CancelEventArgs e)
    {
        if (_cts is null) return;
        e.Cancel = true;
        _cts.Cancel();
        MessageBox.Show(this, "CT-19正在停止。请确认转台完全静止并完成数据保存后再关闭窗口。",
            "CT-19停止中", MessageBoxButton.OK, MessageBoxImage.Warning);
    }
}
