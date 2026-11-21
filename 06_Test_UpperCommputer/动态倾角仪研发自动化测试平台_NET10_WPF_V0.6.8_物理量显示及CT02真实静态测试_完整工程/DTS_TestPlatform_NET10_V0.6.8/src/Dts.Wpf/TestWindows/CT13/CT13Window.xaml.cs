using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Text;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using Dts.Core;
using Dts.TestEngine;
using Dts.Tests.S1.CT13;

namespace Dts.Wpf.TestWindows.CT13;

[Dts.Wpf.TestWindows.TestWindowFor("CT-13")]
public partial class CT13Window : Window, Dts.Wpf.TestWindows.ICalibrationRunAware
{
    private readonly TestDefinition _definition;
    private readonly ITestModule _module;
    private readonly IStaticAngleHardware _hardware;
    private readonly TestRunner _runner;
    private readonly string _root;
    private CalibrationRun _calibration = CalibrationRun.Raw;
    private readonly List<Ct13Cycle> _cycles = [];
    private string? _folder;
    private DateTimeOffset? _powerOffStartedUtc;
    private DateTimeOffset? _powerOnConfirmedUtc;
    private string? _expectedUid;
    private string? _expectedDevice;
    private bool _busy;

    public CT13Window(TestDefinition definition, ITestModule module, IStaticAngleHardware hardware,
        TestRunner runner, string outputRoot)
    {
        InitializeComponent();
        _definition = definition;
        _module = module;
        _hardware = hardware;
        _runner = runner;
        _root = outputRoot;
        OutputText.Text = "数据根目录：" + outputRoot;
        RefreshIdentity();
        RefreshProgress();
    }

    public void SetCalibrationRun(CalibrationRun run) => _calibration = run;

    private void RefreshIdentity()
    {
        var id = _hardware.CurrentIdentity;
        DeviceText.Text = id is null
            ? "当前未连接IMU / 未读取完整UID"
            : $"当前设备：{id.DtsId}    UID：{id.UidHex}";
    }

    private static int ReadInt(TextBox box, string name, int min, int max)
    {
        if (!int.TryParse(box.Text.Trim(), NumberStyles.Integer, CultureInfo.InvariantCulture, out int value) ||
            value < min || value > max)
            throw new InvalidDataException($"{name}必须为{min}～{max}的整数。");
        return value;
    }

    private (int Total, int Warmup, int Capture, int Off) ReadParameters()
    {
        int total = ReadInt(CyclesBox, "上电次数", 3, 30);
        int warmup = ReadInt(WarmupBox, "稳定等待", 0, 1800);
        int capture = ReadInt(CaptureBox, "采集时长", 5, 1800);
        int off = ReadInt(OffBox, "断电间隔", 5, 600);
        if (_cycles.Count > total)
            throw new InvalidOperationException("已完成轮数超过新的计划次数，请不要中途减少计划次数。");
        return (total, warmup, capture, off);
    }

    private void ValidateClick(object sender, RoutedEventArgs e)
    {
        try
        {
            var p = ReadParameters();
            ProgressBar.Maximum = p.Total;
            StatusText.Text = $"参数有效：{p.Total}次上电；稳定等待{p.Warmup}s；采集{p.Capture}s；人工断电至少{p.Off}s。";
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, "CT-13参数检查", MessageBoxButton.OK, MessageBoxImage.Warning);
        }
    }

    private void OffClick(object sender, RoutedEventArgs e)
    {
        if (_busy) return;
        try
        {
            var p = ReadParameters();
            if (_powerOffStartedUtc is not null || _powerOnConfirmedUtc is not null)
                throw new InvalidOperationException("当前轮次尚未完成或已处于断电/重连流程中。请先完成当前轮次；若当前轮失败，请关闭窗口并重新开始测试。");
            if (!PoseCheck.IsChecked.GetValueOrDefault())
                throw new InvalidOperationException("请确认PCB固定姿态、安装方向和线缆布置全程不变。");

            var id = _hardware.CurrentIdentity ??
                throw new InvalidOperationException("请先在主窗口连接真实IMU并读取完整UID。");
            if (_cycles.Count == 0)
            {
                _expectedUid = id.UidHex;
                _expectedDevice = id.DtsId;
                _folder = Path.Combine(_root, $"{id.DtsId}_{id.UidHex}",
                    $"{DateTime.Now:yyyyMMdd_HHmmss_fff}_CT-13");
                Directory.CreateDirectory(_folder);
                File.WriteAllText(Path.Combine(_folder, "CT13_protocol.json"),
                    JsonSerializer.Serialize(new
                    {
                        TestId = "CT-13",
                        TestName = "多次上电重复性",
                        Device = id.DtsId,
                        Uid = id.UidHex,
                        Cycles = p.Total,
                        WarmupSeconds = p.Warmup,
                        CaptureSeconds = p.Capture,
                        OffSeconds = p.Off,
                        PowerControl = "MANUAL_USB_OR_EXTERNAL_POWER_DISCONNECT",
                        CalibrationMode = _calibration.Mode.ToString(),
                        TimestampMeaning = "PowerOnConfirmedUtc is operator confirmation after reconnection, not an electrical edge timestamp.",
                        Note = "每次采集必须在主程序重新连接后执行；软件不自动切断供电。"
                    }, new JsonSerializerOptions { WriteIndented = true }));
            }
            else
            {
                if (!string.Equals(id.UidHex, _expectedUid, StringComparison.OrdinalIgnoreCase) ||
                    !string.Equals(id.DtsId, _expectedDevice, StringComparison.Ordinal))
                    throw new InvalidDataException("当前设备身份与首轮测试基准不一致。");
            }

            if (_cycles.Count >= p.Total)
                throw new InvalidOperationException("计划上电次数已完成。");

            _powerOffStartedUtc = DateTimeOffset.UtcNow;
            OffButton.IsEnabled = false;
            OffDoneButton.IsEnabled = true;
            CaptureButton.IsEnabled = false;
            CountdownText.Text = $"请立即手动拔掉USB/PCB电源。本轮断电计时开始：{_powerOffStartedUtc:O}。断电至少{p.Off}秒。";
            StatusText.Text = "等待人工断电并重新上电；此时不要启动采集。";
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, "CT-13", MessageBoxButton.OK, MessageBoxImage.Warning);
        }
    }

    private void OffDoneClick(object sender, RoutedEventArgs e)
    {
        try
        {
            if (_powerOffStartedUtc is null)
                throw new InvalidOperationException("尚未开始本轮断电。");
            if (!PowerCheck.IsChecked.GetValueOrDefault())
                throw new InvalidOperationException("请确认已完成真实断电及重新上电。");

            int required = ReadInt(OffBox, "断电间隔", 5, 600);
            var now = DateTimeOffset.UtcNow;
            var elapsed = now - _powerOffStartedUtc.Value;
            if (elapsed.TotalSeconds < required)
                throw new InvalidOperationException($"断电计时仅{elapsed.TotalSeconds:F1}s，未达到设定的{required}s。");

            // Operator must reconnect the same IMU in the main window before confirming this step.
            var id = _hardware.CurrentIdentity ??
                throw new InvalidOperationException("尚未检测到重新上电后的IMU。请先在主程序重新连接设备。");
            if (_expectedUid is null || _expectedDevice is null ||
                !id.UidHex.Equals(_expectedUid, StringComparison.OrdinalIgnoreCase) ||
                id.DtsId != _expectedDevice)
                throw new InvalidDataException("重新连接后的设备UID/编号与首轮基准不一致。");

            _powerOnConfirmedUtc = now;
            CountdownText.Text = $"已确认重新连接同一设备：{_powerOnConfirmedUtc:O}。可以开始本轮稳定等待和采集。";
            CaptureButton.IsEnabled = true;
            OffDoneButton.IsEnabled = false;
            StatusText.Text = "设备身份已核对；点击采集后还会再次核验UID并执行精度测试连接检查。";
            RefreshIdentity();
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, "CT-13", MessageBoxButton.OK, MessageBoxImage.Warning);
            RefreshIdentity();
        }
    }

    private async void CaptureClick(object sender, RoutedEventArgs e)
    {
        if (_busy) return;
        try
        {
            var p = ReadParameters();
            if (_powerOnConfirmedUtc is null)
                throw new InvalidOperationException("本轮尚未确认重新上电并在主程序重新连接IMU。");
            if (_expectedUid is null || _expectedDevice is null || _folder is null)
                throw new InvalidOperationException("请先开始第一轮测试并建立测试基准。");
            if (!PoseCheck.IsChecked.GetValueOrDefault())
                throw new InvalidOperationException("请确认PCB姿态和线缆布置全程固定。");

            var id = _hardware.CurrentIdentity ??
                throw new InvalidOperationException("当前IMU未连接或UID不可用。请先在主程序重新连接。");
            if (!id.UidHex.Equals(_expectedUid, StringComparison.OrdinalIgnoreCase) || id.DtsId != _expectedDevice)
                throw new InvalidDataException($"设备身份不一致。预期UID={_expectedUid}，当前UID={id.UidHex}。");
            if (_calibration.Mode != CalibrationMode.Ambient)
                throw new InvalidOperationException("CT-13当前要求主程序选择常温标定；如需RAW/全温对比，应另行定义独立试验方案。");
            _calibration.Validate(id);

            _busy = true;
            CaptureButton.IsEnabled = false;
            OffButton.IsEnabled = false;
            StatusText.Text = $"第{_cycles.Count + 1}/{p.Total}次：等待上电稳定{p.Warmup}s……";
            await Task.Delay(TimeSpan.FromSeconds(p.Warmup));

            id = _hardware.CurrentIdentity ??
                throw new InvalidOperationException("稳定等待期间IMU连接丢失。");
            if (!id.UidHex.Equals(_expectedUid, StringComparison.OrdinalIgnoreCase) || id.DtsId != _expectedDevice)
                throw new InvalidDataException("稳定等待期间设备UID发生变化，停止本轮。");
            _calibration.Validate(id);

            var settings = new Ct13Settings(_cycles.Count + 1, p.Total, p.Capture, _expectedUid, _expectedDevice);
            var progress = new Progress<string>(message => StatusText.Text = message);
            var context = new TestExecutionContext(
                _definition, TimeSpan.FromSeconds(p.Capture), _hardware, progress, settings);

            DateTimeOffset captureStarted = DateTimeOffset.UtcNow;
            var result = await _runner.RunAsync(_module, context, CancellationToken.None);
            DateTimeOffset captureEnded = DateTimeOffset.UtcNow;

            if (result.Outcome is not TestOutcome.DiagnosticOnly)
                throw new InvalidOperationException("CT-13本轮没有返回预期的诊断采集结果。");
            var artifact = result.Capture as CaptureArtifacts;
            if (artifact is null)
                throw new InvalidDataException("测试结果缺少真实采集文件信息。");
            if (artifact.Samples <= 0)
                throw new InvalidDataException("本轮没有有效采集样本，不能计入完成轮次。");

            var cycle = new Ct13Cycle(
                settings.CycleIndex, artifact.UidHex, artifact.DeviceNumber,
                _powerOnConfirmedUtc.Value.ToString("O"),
                captureStarted.ToString("O"), captureEnded.ToString("O"),
                artifact.Samples, artifact.Batches, artifact.CsvFile, artifact.ManifestFile,
                artifact.AnalysisFile, null, NoteBox.Text.Trim());

            _cycles.Add(cycle);
            SaveCheckpoint();
            RefreshGrid();

            _powerOffStartedUtc = null;
            _powerOnConfirmedUtc = null;
            PowerCheck.IsChecked = false;
            PoseCheck.IsChecked = true;
            OffButton.IsEnabled = _cycles.Count < p.Total;
            CaptureButton.IsEnabled = false;
            CountdownText.Text = _cycles.Count < p.Total
                ? "本轮完成。下一轮请再次人工断电。"
                : "计划轮次已全部采集完成。";
            StatusText.Text = $"第{_cycles.Count}/{p.Total}次采集完成：{artifact.Samples}帧，{artifact.Batches}批。";
            RefreshProgress();
        }
        catch (Exception ex)
        {
            // Do not silently retry a partially completed capture as the same power cycle.
            // The operator must inspect the output and start a fresh manual power cycle.
            _powerOffStartedUtc = null;
            _powerOnConfirmedUtc = null;
            CaptureButton.IsEnabled = false;
            PowerCheck.IsChecked = false;
            StatusText.Text = "本轮未计入完成次数：" + ex.Message + "；请检查已生成文件，确认后重新执行一次人工断电循环。";
            MessageBox.Show(this, StatusText.Text, "CT-13采集失败", MessageBoxButton.OK, MessageBoxImage.Warning);
            RefreshIdentity();
        }
        finally
        {
            _busy = false;
            OffButton.IsEnabled = _cycles.Count < SafeTotal();
        }
    }

    private int SafeTotal()
    {
        try { return ReadInt(CyclesBox, "上电次数", 3, 30); }
        catch { return 10; }
    }

    private void RefreshProgress()
    {
        int total = SafeTotal();
        ProgressBar.Maximum = total;
        ProgressBar.Value = _cycles.Count;
        ProgressText.Text = $"{_cycles.Count} / {total} 次上电周期完成";
        SummaryText.Text = _cycles.Count < 2
            ? "至少完成2次后才可进行跨周期比较；建议完成全部计划轮次。"
            : Ct13Algorithm.Summarize(_cycles).Interpretation;
    }

    private void RefreshGrid()
    {
        CycleGrid.ItemsSource = _cycles.Select(c => new
        {
            c.Index,
            UidShort = c.UidHex.Length > 12 ? c.UidHex[..12] + "…" : c.UidHex,
            PowerOnUtc = c.PowerOnConfirmedUtc,
            c.Samples,
            Temperature = c.TemperatureC?.ToString("F2", CultureInfo.InvariantCulture) ?? "见原始记录",
            CsvFile = Path.GetFileName(c.CsvFile)
        }).ToArray();
        RefreshProgress();
    }

    private void SaveCheckpoint()
    {
        if (_folder is null) return;
        var report = new
        {
            TestId = "CT-13",
            TestName = "多次上电重复性",
            State = _cycles.Count == SafeTotal() ? "COMPLETED_PENDING_ACCEPTANCE" : "RUNNING",
            CompletedCycles = _cycles.Count,
            ExpectedUid = _expectedUid,
            ExpectedDevice = _expectedDevice,
            PowerControl = "MANUAL_USB_OR_EXTERNAL_POWER_DISCONNECT",
            Cycles = _cycles,
            Summary = Ct13Algorithm.Summarize(_cycles),
            Caveat = "上电时间为操作者在主程序重新连接后点击确认的时间，不是电气边沿硬件时间戳。跨周期差异包含供电重启、温度、安装与测量噪声影响；不自动判PASS。"
        };
        File.WriteAllText(Path.Combine(_folder, "CT-13_checkpoint.json"),
            JsonSerializer.Serialize(report, new JsonSerializerOptions { WriteIndented = true }));
    }

    private void ExportClick(object sender, RoutedEventArgs e)
    {
        try
        {
            if (_folder is null || _cycles.Count == 0)
                throw new InvalidOperationException("尚无已完成采集轮次。");
            SaveCheckpoint();

            var csv = new StringBuilder(
                "cycle,uid,device,power_on_confirmed_utc,capture_started_utc,capture_ended_utc,samples,batches,csv_file,manifest_file,analysis_file,operator_note\r\n");
            foreach (var c in _cycles)
                csv.AppendLine(string.Join(",",
                    c.Index, Q(c.UidHex), Q(c.DeviceNumber), Q(c.PowerOnConfirmedUtc),
                    Q(c.CaptureStartedUtc), Q(c.CaptureEndedUtc),
                    c.Samples, c.Batches, Q(c.CsvFile), Q(c.ManifestFile),
                    Q(c.AnalysisFile ?? ""), Q(c.OperatorNote)));
            File.WriteAllText(Path.Combine(_folder, "CT-13_cycles.csv"), csv.ToString(), new UTF8Encoding(true));

            var html = new StringBuilder(
                "<!doctype html><html><head><meta charset='utf-8'><title>CT-13报告</title>" +
                "<style>body{font-family:Arial,'Microsoft YaHei',sans-serif;margin:28px;color:#243447}" +
                "table{border-collapse:collapse;width:100%}th,td{border:1px solid #ccd5df;padding:7px;text-align:left}" +
                "th{background:#edf2f7}code{overflow-wrap:anywhere}</style></head><body>" +
                "<h1>CT-13 多次上电重复性报告</h1>");
            html.Append("<p>状态：研发诊断/待验收；供电循环由人工完成，软件不控制电源。</p>");
            html.Append($"<p>设备：{Html(_expectedDevice)}；UID：{Html(_expectedUid)}</p>");
            html.Append($"<p>完成轮次：{_cycles.Count}/{SafeTotal()}</p>");
            html.Append("<table><tr><th>轮次</th><th>重新连接确认时间(UTC)</th><th>采集开始(UTC)</th><th>采集结束(UTC)</th><th>样本</th><th>批次</th><th>原始CSV</th><th>备注</th></tr>");
            foreach (var c in _cycles)
                html.Append($"<tr><td>{c.Index}</td><td>{Html(c.PowerOnConfirmedUtc)}</td>" +
                    $"<td>{Html(c.CaptureStartedUtc)}</td><td>{Html(c.CaptureEndedUtc)}</td>" +
                    $"<td>{c.Samples}</td><td>{c.Batches}</td><td><code>{Html(c.CsvFile)}</code></td>" +
                    $"<td>{Html(c.OperatorNote)}</td></tr>");
            html.Append("</table><h2>解释与限制</h2><p>每轮真实采集CSV、manifest及平台静态诊断文件均按UID关联归档。");
            html.Append("重新连接确认时间由操作者记录，不是电气边沿时间戳。当前版本不从未经确认的诊断JSON字段推导六轴跨周期均值/标准差，也不自动生成PASS/FAIL。</p>");
            html.Append("<p>跨周期差异可能同时包含供电重启、温度、安装状态和测量噪声影响，不能直接解释为纯粹的IMU上电随机性。</p></body></html>");

            string path = Path.Combine(_folder, "CT-13_report.html");
            File.WriteAllText(path, html.ToString(), new UTF8Encoding(false));
            Process.Start(new ProcessStartInfo(path) { UseShellExecute = true });
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, "CT-13报告", MessageBoxButton.OK, MessageBoxImage.Warning);
        }
    }

    private static string Q(string? value) =>
        "\"" + (value ?? "").Replace("\"", "\"\"") + "\"";

    private static string Html(string? value) =>
        System.Net.WebUtility.HtmlEncode(value ?? "");

    private void CloseClick(object sender, RoutedEventArgs e) => Close();
}
