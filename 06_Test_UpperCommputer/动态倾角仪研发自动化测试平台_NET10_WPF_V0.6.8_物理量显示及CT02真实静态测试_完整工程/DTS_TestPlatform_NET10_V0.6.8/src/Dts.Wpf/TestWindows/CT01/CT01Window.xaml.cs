using System;
using System.ComponentModel;
using System.Threading;
using System.Threading.Tasks;
using System.IO;
using System.Linq;
using System.Diagnostics;
using System.Globalization;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using Dts.Core;
using Dts.TestEngine;
using Dts.Tests.S1.CT01;

namespace Dts.Wpf.TestWindows.CT01;

[Dts.Wpf.TestWindows.TestWindowFor("CT-01")]
public sealed class CT01Window : Window, Dts.Wpf.TestWindows.ICalibrationRunAware
{
    private readonly TestDefinition _definition;
    private readonly ITestModule _module;
    private readonly IStaticAngleHardware _hardware;
    private readonly TestRunner _runner;
    private readonly string _outputRoot;
    private CalibrationRun _run = CalibrationRun.Raw;
    private bool _runReady;
    private CancellationTokenSource? _cts;
    private string? _htmlReport;
    private readonly TextBlock _uidText = new();
    private readonly TextBlock _calibrationText = new();
    private readonly TextBlock _statusText = new();
    private readonly TextBlock _resultText = new();
    private readonly TextBlock _rootText = new();
    private readonly TextBox _durationBox = new() { Text = "60", Width = 100, Margin = new Thickness(8, 0, 0, 0) };
    private readonly Button _startButton = new() { Content = "开始真实采集与参数核验", MinWidth = 190, Padding = new Thickness(14, 8, 14, 8), Margin = new Thickness(0, 0, 8, 0) };
    private readonly Button _stopButton = new() { Content = "停止", IsEnabled = false, Padding = new Thickness(14, 8, 14, 8), Margin = new Thickness(0, 0, 8, 0) };
    private readonly Button _reportButton = new() { Content = "打开报告", IsEnabled = false, Padding = new Thickness(14, 8, 14, 8), Margin = new Thickness(0, 0, 8, 0) };

    public CT01Window(TestDefinition definition, ITestModule module, IStaticAngleHardware hardware,
        TestRunner runner, string outputRoot)
    {
        _definition = definition; _module = module; _hardware = hardware; _runner = runner; _outputRoot = outputRoot;
        Title = "CT-01 参数生效与补偿前后对比";
        Width = 900; Height = 690; MinWidth = 780; MinHeight = 600;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;
        Background = Brushes.White;
        Content = BuildUi();
        _rootText.Text = outputRoot;
        _uidText.Text = hardware.CurrentIdentity is { } id
            ? $"DTS短编号：{id.DtsId}\n完整 MCU UID（12字节/24位HEX）：{id.UidHex}"
            : "未读取真实 MCU UID";
        _startButton.Click += StartClick;
        _stopButton.Click += (_, _) => _cts?.Cancel();
        _reportButton.Click += (_, _) =>
        {
            if (_htmlReport is not null && File.Exists(_htmlReport))
                Process.Start(new ProcessStartInfo(_htmlReport) { UseShellExecute = true });
        };
        Loaded += (_, _) => { if (Owner is not null) Owner.IsEnabled = false; };
        Closed += (_, _) => { if (Owner is not null) Owner.IsEnabled = true; };
        Closing += OnClosing;
    }

    public void SetCalibrationRun(CalibrationRun run)
    {
        _run = run;
        try
        {
            var id = _hardware.CurrentIdentity ?? throw new InvalidOperationException("请先连接真实 IMU 并读取完整 MCU UID。");
            if (run.Mode is not (CalibrationMode.Ambient or CalibrationMode.Thermal))
                throw new InvalidOperationException("请在主窗口选择『常温补偿』或『全温补偿』，CT-01 不接受 RAW 未标定模式。");
            run.Validate(id);
            if (run.Sources.Count != 2)
                throw new InvalidDataException("当前模式必须同时匹配 ACC 和 Gyro 两份标定文件。");
            _calibrationText.Text = $"模式：{run.Mode}\n" +
                string.Join("\n", run.Sources.Select(s =>
                    $"{Path.GetFileName(s.FilePath)}\nSHA256：{s.Sha256}\n身份依据：{(s.FullUidVerified ? "JSON内完整UID匹配" : "DTS短编号匹配，需操作者确认")}"));
            _runReady = true;
            _statusText.Text = "标定文件与当前完整 UID 匹配。开始前请保持 IMU 静止并固定。";
        }
        catch (Exception ex)
        {
            _runReady = false;
            _calibrationText.Text = "暂不可启动：" + ex.Message;
            _statusText.Text = _calibrationText.Text;
        }
        _startButton.IsEnabled = _runReady && _module.IsExecutable;
    }

    private UIElement BuildUi()
    {
        var outer = new DockPanel { Margin = new Thickness(18) };
        var footer = new StackPanel { Orientation = Orientation.Horizontal, HorizontalAlignment = HorizontalAlignment.Right, Margin = new Thickness(0, 14, 0, 0) };
        footer.Children.Add(_reportButton); footer.Children.Add(_stopButton); footer.Children.Add(_startButton);
        var close = new Button { Content = "关闭", Padding = new Thickness(14, 8, 14, 8), Margin = new Thickness(8, 0, 0, 0) };
        close.Click += (_, _) => Close();
        footer.Children.Add(close);
        DockPanel.SetDock(footer, Dock.Bottom);
        outer.Children.Add(footer);

        var scroll = new ScrollViewer { VerticalScrollBarVisibility = ScrollBarVisibility.Auto };
        var stack = new StackPanel();
        stack.Children.Add(Card("CT-01  /  参数生效与补偿前后对比",
            "真实 MCU FIFO · 同批原始与补偿数据 · 冻结 JSON 独立重算 · 不控制转台"));
        stack.Children.Add(Card("① 设备身份", _uidText));
        stack.Children.Add(Card("② 当前标定文件（由主窗口按 UID 匹配，本窗口不另选文件）", _calibrationText));
        var settings = new StackPanel();
        var duration = new StackPanel { Orientation = Orientation.Horizontal, VerticalAlignment = VerticalAlignment.Center };
        duration.Children.Add(new TextBlock { Text = "采样时长（5～1800秒）", VerticalAlignment = VerticalAlignment.Center });
        duration.Children.Add(_durationBox);
        settings.Children.Add(duration);
        settings.Children.Add(new TextBlock
        {
            Text = "测试期间主窗口会暂时锁定，避免采集模式或标定文件被更改。只读取真实 IMU，不发送转台运动指令。",
            TextWrapping = TextWrapping.Wrap, Foreground = Brushes.SaddleBrown, Margin = new Thickness(0, 10, 0, 0)
        });
        stack.Children.Add(Card("③ 采集设置", settings));
        stack.Children.Add(Card("④ 测试结果", _resultText));
        var statusPanel = new StackPanel();
        statusPanel.Children.Add(_statusText);
        statusPanel.Children.Add(new TextBlock { Text = "报告根目录：", Margin = new Thickness(0, 8, 0, 2), Foreground = Brushes.Gray });
        statusPanel.Children.Add(_rootText);
        stack.Children.Add(Card("⑤ 状态与报告目录", statusPanel));
        scroll.Content = stack;
        outer.Children.Add(scroll);
        return outer;
    }

    private static Border Card(string title, string body)
    {
        var panel = new StackPanel();
        panel.Children.Add(new TextBlock { Text = title, FontSize = 17, FontWeight = FontWeights.SemiBold, Foreground = Brushes.DarkSlateGray });
        panel.Children.Add(new TextBlock { Text = body, TextWrapping = TextWrapping.Wrap, Margin = new Thickness(0, 8, 0, 0), Foreground = Brushes.SlateGray });
        return new Border { BorderBrush = new SolidColorBrush(Color.FromRgb(220, 228, 236)), BorderThickness = new Thickness(1), CornerRadius = new CornerRadius(8), Padding = new Thickness(14), Margin = new Thickness(0, 0, 0, 10), Child = panel };
    }

    private static Border Card(string title, UIElement content)
    {
        var panel = new StackPanel();
        panel.Children.Add(new TextBlock { Text = title, FontSize = 17, FontWeight = FontWeights.SemiBold, Foreground = Brushes.DarkSlateGray });
        panel.Children.Add(content);
        if (content is FrameworkElement fe) fe.Margin = new Thickness(0, 8, 0, 0);
        return new Border { BorderBrush = new SolidColorBrush(Color.FromRgb(220, 228, 236)), BorderThickness = new Thickness(1), CornerRadius = new CornerRadius(8), Padding = new Thickness(14), Margin = new Thickness(0, 0, 0, 10), Child = panel };
    }

    private async void StartClick(object sender, RoutedEventArgs e)
    {
        if (_cts is not null) return;
        try
        {
            var id = _hardware.CurrentIdentity ?? throw new InvalidOperationException("请先连接真实 IMU。");
            if (!_runReady) throw new InvalidOperationException("当前标定文件尚未通过 UID/模式检查。");
            _run.Validate(id);
            if (!double.TryParse(_durationBox.Text, NumberStyles.Float, CultureInfo.InvariantCulture, out double seconds) ||
                seconds < 5 || seconds > 1800)
                throw new InvalidDataException("采样时长必须为 5～1800 秒。");
            if (!Directory.Exists(_outputRoot)) throw new DirectoryNotFoundException("报告根目录不存在：" + _outputRoot);
            string files = string.Join("\n", _run.Sources.Select(s => Path.GetFileName(s.FilePath)));
            if (MessageBox.Show(this,
                $"设备 DTS：{id.DtsId}\n完整 MCU UID：{id.UidHex}\n模式：{_run.Mode}\n采样：{seconds:F0}s\n\n标定文件：\n{files}\n\n即将采集真实 FIFO 数据。请确认 IMU 固定且静止；本测试不控制转台，也不自动判定产品精度 PASS。继续？",
                "CT-01 真实参数应用核验", MessageBoxButton.YesNo, MessageBoxImage.Warning) != MessageBoxResult.Yes)
                return;

            _cts = new CancellationTokenSource();
            _startButton.IsEnabled = false; _stopButton.IsEnabled = true; _reportButton.IsEnabled = false;
            _resultText.Text = "";
            var progress = new Progress<string>(s => _statusText.Text = s);
            var context = new TestExecutionContext(_definition, TimeSpan.FromSeconds(seconds),
                _hardware, progress, new Ct01RunSettings(_run));
            var result = await _runner.RunAsync(_module, context, _cts.Token);
            _htmlReport = result.Files.FirstOrDefault(f => f.EndsWith("CT-01_report.html", StringComparison.OrdinalIgnoreCase));
            _reportButton.IsEnabled = _htmlReport is not null && File.Exists(_htmlReport);
            _resultText.Text = result.Summary + "\n\n" + string.Join("\n", result.Files);
            _statusText.Text = "CT-01 完成：参数应用链诊断完成；不代表产品精度验收。";
        }
        catch (OperationCanceledException)
        {
            _statusText.Text = "已取消；已写入的部分原始数据保留，不生成完成/PASS结论。";
        }
        catch (Exception ex)
        {
            _statusText.Text = "未完成：" + ex.Message;
            MessageBox.Show(this, ex.Message, "CT-01 未完成", MessageBoxButton.OK, MessageBoxImage.Warning);
        }
        finally
        {
            _cts?.Dispose(); _cts = null;
            _startButton.IsEnabled = _runReady && _module.IsExecutable;
            _stopButton.IsEnabled = false;
        }
    }

    private void OnClosing(object? sender, CancelEventArgs e)
    {
        if (_cts is not null)
        {
            e.Cancel = true;
            _cts.Cancel();
            MessageBox.Show(this, "正在取消真实采集并保存文件，完成后才能关闭 CT-01。");
        }
    }
}
