using System.ComponentModel;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using Dts.Core;
using Dts.TestEngine;
using Dts.Tests.S1.CT03;

namespace Dts.Wpf.TestWindows.CT03;

[Dts.Wpf.TestWindows.TestWindowFor("CT-03")]
public partial class CT03Window : Window, Dts.Wpf.TestWindows.ICalibrationRunAware
{
    private readonly TestDefinition _definition;
    private readonly ITestModule _module;
    private readonly IStaticAngleHardware _hardware;
    private readonly TestRunner _runner;
    private readonly string _root;
    private CalibrationRun _calibration = CalibrationRun.Raw;
    private CancellationTokenSource? _cts;
    private string? _reportHtml;
    private DateTime _runStartUtc = DateTime.MaxValue;

    // Signature required by MainWindow's reflection-based test-window creator.
    public CT03Window(TestDefinition definition, ITestModule module, IStaticAngleHardware hardware,
        TestRunner runner, string outputRoot)
    {
        InitializeComponent();
        _definition = definition;
        _module = module;
        _hardware = hardware;
        _runner = runner;
        _root = outputRoot;
        RootText.Text = outputRoot;
        UidText.Text = hardware.CurrentIdentity is { } id
            ? $"设备 {id.DtsId}  /  MCU UID {id.UidHex}  /  2TD {(hardware.IsTwoTdConnected ? "已连接" : "未连接")}" : "尚未读取真实 IMU UID";
        RefreshPlan();
    }

    public void SetCalibrationRun(CalibrationRun run)
    {
        _calibration = run;
        try
        {
            var id = _hardware.CurrentIdentity ?? throw new InvalidOperationException("请先连接IMU并读取UID");
            if (run.Mode != CalibrationMode.Ambient)
                throw new InvalidOperationException("CT-03 当前仅支持主窗口选择『常温标定』的已校正ACC矢量");
            run.Validate(id);
            var acc = run.Files?.Acc ?? throw new InvalidDataException("找不到同UID的ACC常温文件");
            var gyro = run.Files?.Gyro ?? throw new InvalidDataException("找不到同UID的Gyro常温文件");
            CalibrationText.Text = $"ACC：{Path.GetFileName(acc.FilePath)}\n" +
                $"Gyro：{Path.GetFileName(gyro.FilePath)}\n" +
                $"输入单位：ACC ±{acc.FsHint}g / Gyro ±{gyro.FsHint}°/s\n" +
                "逐点记录保留真实原始计数，不重复执行矩阵补偿。";
            RefreshPlan();
        }
        catch (Exception ex)
        {
            CalibrationText.Text = "未就绪：" + ex.Message;
            StatusText.Text = CalibrationText.Text;
        }
    }

    private string PlanKind => (PlanBox.SelectedItem as ComboBoxItem)?.Content?.ToString()
        ?? "局部12点(0~90°)";

    private static double ReadNumber(TextBox input)
    {
        if (!double.TryParse(input.Text.Trim(), NumberStyles.Float,
            CultureInfo.InvariantCulture, out double value) || !double.IsFinite(value))
            throw new InvalidDataException($"参数『{input.Name}』不是有限数字（小数点使用 .）");
        return value;
    }

    private static int ReadPositiveInteger(TextBox input)
    {
        if (!int.TryParse(input.Text.Trim(), NumberStyles.Integer, CultureInfo.InvariantCulture, out int result))
            throw new InvalidDataException($"参数『{input.Name}』必须是整数");
        return result;
    }

    private Ct03Settings Settings() => new(_root, PlanKind,
        ReadNumber(MotionSpeed), ReadNumber(SettleSeconds), ReadNumber(CaptureSeconds),
        ReadNumber(Tolerance), ReadNumber(MinTravel), ReadNumber(MaxTravel),
        ReadPositiveInteger(MinSamples), ReadNumber(MaxRejection),
        FullRangeConfirmed.IsChecked == true, DirectionConfirmed.IsChecked == true,
        SafetyConfirmed.IsChecked == true,
        ReadPositiveInteger(InnerDivisionsBox), ReadPositiveInteger(OuterDivisionsBox),
        ReadNumber(InnerStartBox), ReadNumber(OuterStartBox), _calibration);

    private void RefreshPlan()
    {
        if (PlanBox is null || PlanGrid is null || PlanSummary is null ||
            CustomGridPanel is null || InnerDivisionsBox is null || OuterDivisionsBox is null ||
            InnerStartBox is null || OuterStartBox is null) return;
        bool custom = PlanKind == Ct03Algorithm.GridPlan;
        CustomGridPanel.Visibility = custom ? Visibility.Visible : Visibility.Collapsed;
        try
        {
            var points = Ct03Algorithm.BuildPlan(PlanKind,
                ReadPositiveInteger(InnerDivisionsBox), ReadPositiveInteger(OuterDivisionsBox),
                ReadNumber(InnerStartBox), ReadNumber(OuterStartBox));
            PlanGrid.ItemsSource = points;
            int directions = Ct03Algorithm.CountDistinctGravityDirections(points);
            int? historical = _calibration.Files?.Acc is { } acc
                ? Ct03Algorithm.CountHistoricalGravityOverlaps(points, acc.FilePath) : null;
            string warning = directions < points.Count
                ? $"注意：只有{directions}个不同参考重力方向，另有{points.Count - directions}个重复方向工位。"
                : "所有机械工位对应不同参考重力方向。";
            if (historical is > 0)
                warning += $" 其中{historical}个工位与本UID历史ACC标定/验证方向重合，不属于全新独立方向。";
            PlanSummary.Text = $"{points.Count}个机械工位 / {directions}个不同参考重力方向。" + warning +
                (PlanKind.StartsWith("局部", StringComparison.Ordinal)
                    ? " 仅局部范围，默认批准0~90°。"
                    : " 全向移动必须先现场核验限位、电缆与绝对运动方向，并设置实际已批准行程。 ");
        }
        catch (Exception ex)
        {
            PlanGrid.ItemsSource = null;
            PlanSummary.Text = "扫描参数不合法：" + ex.Message;
        }
    }

    private void GridSettingsChanged(object sender, TextChangedEventArgs e) => RefreshPlan();
    private void PlanChanged(object sender, SelectionChangedEventArgs e) => RefreshPlan();

    private void PreviewClick(object sender, RoutedEventArgs e)
    {
        try
        {
            var settings = Settings();
            var plan = Ct03Algorithm.BuildPlan(settings);
            // Preview is not a safety authorization; just inspect param/value range.
            Ct03Algorithm.ValidatePlan(settings with
            {
                HardwareSafetyConfirmed = true,
                DirectionAndCablingApproved = true,
                FullRangeApproved = true
            }, plan);
            MessageBox.Show(this,
                $"已检查 {plan.Count} 个机械工位，包含 {Ct03Algorithm.CountDistinctGravityDirections(plan)} 个不同参考重力方向。\n" +
                (_calibration.Files?.Acc is { } source
                    ? $"与历史ACC标定方向重合的工位：{Ct03Algorithm.CountHistoricalGravityOverlaps(plan, source.FilePath)?.ToString() ?? "未知"}。\n"
                    : "未加载ACC历史文件，无法检查与历史标定方向是否重合。\n") +
                "此操作只检查软件参数，不代表现场转台、线缆或急停安全已验证。",
                "CT-03 扫描预览", MessageBoxButton.OK, MessageBoxImage.Information);
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, "扫描计划检查失败", MessageBoxButton.OK, MessageBoxImage.Warning);
        }
    }

    private async void StartClick(object sender, RoutedEventArgs e)
    {
        if (_cts is not null) return;
        try
        {
            var id = _hardware.CurrentIdentity ?? throw new InvalidOperationException("真实IMU未连接或UID不可用");
            if (!_module.IsExecutable || _module.TestId != "CT-03")
                throw new InvalidOperationException("CT-03真实执行模块未注册");
            if (!_hardware.IsTwoTdConnected)
                throw new InvalidOperationException("先在主界面连接并使能真实2TD-600");
            if (!Directory.Exists(_root))
                throw new DirectoryNotFoundException("主窗口指定的报告根目录不存在");
            if (_calibration.Mode != CalibrationMode.Ambient)
                throw new InvalidOperationException("先在主窗口选择常温标定并重新打开本窗口");
            _calibration.Validate(id);
            var settings = Settings();
            var plan = Ct03Algorithm.BuildPlan(settings);
            Ct03Algorithm.ValidatePlan(settings, plan);
            await _hardware.VerifyImuForPrecisionTestAsync(CancellationToken.None);
            var initial = await _hardware.ReadTwoTdAsync(CancellationToken.None);
            if (!initial.Inner.Normal || !initial.Outer.Normal || initial.Inner.Enabled != true || initial.Outer.Enabled != true)
                throw new IOException("双轴未正常使能，禁止进入真实运动测试");
            if (MessageBox.Show(this,
                $"设备：{id.DtsId}\n自动检测：{plan.Count} 机械工位 / {settings.PlanKind}\n" +
                $"不同参考重力方向：{Ct03Algorithm.CountDistinctGravityDirections(plan)}\n" +
                $"运动速度：{settings.SpeedDps:F2}°/s\n静置：{settings.SettleSeconds:F1}s / 采集：{settings.SampleSeconds:F1}s\n" +
                $"允许行程：[{settings.AllowedMinDeg:F0}, {settings.AllowedMaxDeg:F0}]°\n\n" +
                "即将自动连续发送真实转台运动命令。开始后不再逐点询问。\n" +
                "请最后确认无人接触旋转机构，实体急停可用，已核验方向、限位及电缆绕转安全。",
                "CT-03 · 真实自动运动确认", MessageBoxButton.YesNo,
                MessageBoxImage.Warning) != MessageBoxResult.Yes)
                return;
            _cts = new CancellationTokenSource();
            _runStartUtc = DateTime.UtcNow;
            _reportHtml = null;
            ReportButton.IsEnabled = false;
            StartButton.IsEnabled = false;
            PreviewButton.IsEnabled = false;
            StopButton.IsEnabled = true;
            RunProgressBar.Value = 0;
            ResultGrid.ItemsSource = null;
            MetricsText.Text = "真实采样中：未得到正式验收结论";
            ReportText.Text = "逐点保存原始计数、物理量和补偿结果；任务中断仍会保存部分报告。";
            var progress = new Progress<string>(text =>
            {
                StatusText.Text = text;
                var found = System.Text.RegularExpressions.Regex.Match(text, @"\[(\d+)/(\d+)\]");
                if (found.Success && int.TryParse(found.Groups[1].Value, out int idx) &&
                    int.TryParse(found.Groups[2].Value, out int total) && total > 0)
                    RunProgressBar.Value = Math.Clamp(idx * 100d / total, 0, 100);
            });
            var context = new TestExecutionContext(_definition, TimeSpan.FromSeconds(settings.SampleSeconds),
                _hardware, progress, settings);
            var result = await _runner.RunAsync(_module, context, _cts.Token);
            StatusText.Text = result.Summary;
            RunProgressBar.Value = 100;
            var json = result.Files.FirstOrDefault(f => f.EndsWith("CT-03_result.json", StringComparison.OrdinalIgnoreCase));
            if (json is not null && File.Exists(json)) ShowResult(json);
        }
        catch (OperationCanceledException)
        {
            StatusText.Text = "操作员取消；已请求自动双轴软停车。请现场检查反馈与实体安全状态。";
            LoadPartial();
        }
        catch (Exception ex)
        {
            StatusText.Text = "CT-03 未完成：" + ex.Message;
            LoadPartial();
            MessageBox.Show(this, ex.Message, "CT-03 测试中止", MessageBoxButton.OK, MessageBoxImage.Warning);
        }
        finally
        {
            _cts?.Dispose();
            _cts = null;
            StartButton.IsEnabled = true;
            PreviewButton.IsEnabled = true;
            StopButton.IsEnabled = false;
        }
    }

    private void ShowResult(string file)
    {
        var data = JsonSerializer.Deserialize<Ct03ReportData>(File.ReadAllText(file));
        if (data is null) throw new InvalidDataException("报告JSON结构不完整");
        ResultGrid.ItemsSource = data.Points.Select(p => new
        {
            p.Index,
            Inner = p.InnerActualDeg.ToString("F3", CultureInfo.InvariantCulture),
            Outer = p.OuterActualDeg.ToString("F3", CultureInfo.InvariantCulture),
            ErrorX = (p.AxisErrorG[0] * 1000).ToString("F3", CultureInfo.InvariantCulture),
            ErrorY = (p.AxisErrorG[1] * 1000).ToString("F3", CultureInfo.InvariantCulture),
            ErrorZ = (p.AxisErrorG[2] * 1000).ToString("F3", CultureInfo.InvariantCulture),
            VectorMg = (p.VectorErrorG * 1000).ToString("F3", CultureInfo.InvariantCulture),
            Angle = p.DirectionErrorDeg.ToString("F5", CultureInfo.InvariantCulture),
            Samples = p.AcceptedSamples
        }).ToArray();
        if (data.Metrics is { } m)
        {
            MetricsText.Text = $"三轴RMSE：X={m.AxisRmseG[0]*1000:F3}mg  Y={m.AxisRmseG[1]*1000:F3}mg  Z={m.AxisRmseG[2]*1000:F3}mg\n" +
                $"矢量RMSE={m.VectorRmseG*1000:F3}mg  ·  最大方向误差={m.DirectionMaxDeg:F5}°  ·  有效帧={m.SampleCount}";
            SummaryText.Text = $"{data.State}  ·  {m.CompletedPoints} 点完成，待验收（无自动PASS）";
        }
        else SummaryText.Text = data.State + "（部分测试记录）";
        ResultTabs.SelectedIndex = 1;
        _reportHtml = Path.Combine(Path.GetDirectoryName(file)!, "CT-03_report.html");
        ReportButton.IsEnabled = File.Exists(_reportHtml);
        ReportText.Text = "本次报告：" + _reportHtml;
    }

    private void LoadPartial()
    {
        try
        {
            var id = _hardware.CurrentIdentity;
            if (id is null || _runStartUtc == DateTime.MaxValue) return;
            var deviceFolder = Path.Combine(_root, id.DtsId + "_" + id.UidHex);
            if (!Directory.Exists(deviceFolder)) return;
            var found = Directory.EnumerateDirectories(deviceFolder, "*_CT-03")
                .Where(p => Directory.GetCreationTimeUtc(p) >= _runStartUtc.AddSeconds(-3))
                .OrderByDescending(Directory.GetCreationTimeUtc).FirstOrDefault();
            if (found is null) return;
            var json = Path.Combine(found, "CT-03_result.json");
            if (File.Exists(json)) ShowResult(json);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or JsonException)
        {
            ReportText.Text = "部分报告预览失败，请从报告目录查看：" + ex.Message;
        }
    }

    private void StopClick(object sender, RoutedEventArgs e)
    {
        StatusText.Text = "取消已发出，正在请求双轴软停车并写入部分报告；如反馈异常请使用实体急停。";
        _cts?.Cancel();
    }

    private void ReportClick(object sender, RoutedEventArgs e)
    {
        if (_reportHtml is not null && File.Exists(_reportHtml))
            Process.Start(new ProcessStartInfo(_reportHtml) { UseShellExecute = true });
    }

    private void CloseClick(object sender, RoutedEventArgs e) => Close();

    private void OnClosing(object? sender, CancelEventArgs e)
    {
        if (_cts is null) return;
        e.Cancel = true;
        _cts.Cancel();
        MessageBox.Show(this,
            "真实自动任务还未结束。已请求取消并执行停车，需等待运动反馈和报告保存完成后再关闭。",
            "CT-03 正在结束任务", MessageBoxButton.OK, MessageBoxImage.Warning);
    }
}
