using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Text.Json;
using System.Windows;
using Dts.Core;
using Dts.TestEngine;
using Dts.Tests.S1.CT09;

namespace Dts.Wpf.TestWindows.CT09;

[Dts.Wpf.TestWindows.TestWindowFor("CT-09")]
public partial class CT09Window : Window, Dts.Wpf.TestWindows.ICalibrationRunAware
{
    private readonly TestDefinition _definition;
    private readonly ITestModule _module;
    private readonly IStaticAngleHardware _hardware;
    private readonly TestRunner _runner;
    private readonly string _root;
    private CalibrationRun _calibration = CalibrationRun.Raw;
    private CancellationTokenSource? _cts;
    private string? _reportHtml;
    private string? _latestFolder;

    public CT09Window(TestDefinition definition, ITestModule module, IStaticAngleHardware hardware,
        TestRunner runner, string outputRoot)
    {
        InitializeComponent();
        _definition = definition; _module = module; _hardware = hardware; _runner = runner; _root = outputRoot;
        DeviceText.Text = hardware.CurrentIdentity is { } id
            ? $"设备：{id.DtsId} / UID：{id.UidHex} / 2TD：{(hardware.IsTwoTdConnected ? "已连接" : "未连接")}"
            : "IMU尚未连接或尚未读取完整UID";
        OutputText.Text = "报告根目录：" + outputRoot;
    }

    public void SetCalibrationRun(CalibrationRun run)
    {
        _calibration = run;
        try
        {
            var id = _hardware.CurrentIdentity ?? throw new InvalidOperationException("请先连接IMU并读取完整UID。");
            if (run.Mode != CalibrationMode.Ambient)
                throw new InvalidOperationException("CT-09要求主界面选择常温标定模式。");
            run.Validate(id);
            var gyro = run.Files?.Gyro ?? throw new InvalidDataException("缺少当前UID匹配的Gyro常温JSON。");
            var acc = run.Files?.Acc ?? throw new InvalidDataException("缺少当前UID匹配的ACC常温JSON。");
            CalibrationText.Text = $"常温模型已匹配：Gyro {Path.GetFileName(gyro.FilePath)}（±{gyro.FsHint}°/s）；ACC {Path.GetFileName(acc.FilePath)}；{run.IdentityProof}";
        }
        catch (Exception ex) { CalibrationText.Text = "标定条件未就绪：" + ex.Message; }
    }

    private static double D(string text, string name)
    {
        if (!double.TryParse(text.Trim(), NumberStyles.Float, CultureInfo.InvariantCulture, out double v) || !double.IsFinite(v))
            throw new InvalidDataException($"{name}必须是有效数值，使用英文小数点。");
        return v;
    }
    private static int I(string text, string name)
    {
        if (!int.TryParse(text.Trim(), NumberStyles.Integer, CultureInfo.InvariantCulture, out int v))
            throw new InvalidDataException($"{name}必须是整数。");
        return v;
    }

    private Ct09Settings BuildSettings(bool safetyRequired = true)
    {
        var poses = new List<Ct09Pose>();
        int index = 0;
        foreach (var item in PoseBox.Text.Split(';', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
        {
            var pair = item.Split(',', StringSplitOptions.TrimEntries);
            if (pair.Length != 2) throw new InvalidDataException($"姿态格式错误：{item}。格式应为内轴°,外轴°。");
            poses.Add(new Ct09Pose(++index, D(pair[0], "内轴角"), D(pair[1], "外轴角")));
        }
        var settings = new Ct09Settings(_root, poses, I(RepeatBox.Text, "重复次数"),
            D(SpeedBox.Text, "定位速度"), D(SettleBox.Text, "静置时间"), D(SampleBox.Text, "采集时间"),
            D(ToleranceBox.Text, "到位容差"), D(MinTravelBox.Text, "允许最小角度"),
            D(MaxTravelBox.Text, "允许最大角度"), I(MinSamplesBox.Text, "最少有效帧"),
            D(MaxOutlierBox.Text, "最大剔除比例"), DirectionCheck.IsChecked == true,
            SafetyCheck.IsChecked == true, _calibration);
        Ct09Algorithm.Validate(settings, safetyRequired);
        return settings;
    }

    private void PreviewClick(object sender, RoutedEventArgs e)
    {
        try
        {
            var s = BuildSettings(false);
            MessageBox.Show(this,
                $"计划姿态：{s.Poses.Count}个；每姿态重复{s.RepeatsPerPose}次；总采集单元{s.Poses.Count * s.RepeatsPerPose}。\n" +
                $"定位速度{s.MotionSpeedDps:F2}°/s；静置{s.SettleSeconds:F1}s；采集{s.SampleSeconds:F1}s。\n" +
                "转台将按外轴先回0°、再调整内轴、最后设置外轴的顺序移动。实际路径仍须现场确认。",
                "CT-09测试预览", MessageBoxButton.OK, MessageBoxImage.Information);
        }
        catch (Exception ex) { MessageBox.Show(this, ex.Message, "CT-09参数检查", MessageBoxButton.OK, MessageBoxImage.Warning); }
    }

    private async void StartClick(object sender, RoutedEventArgs e)
    {
        if (_cts is not null) return;
        try
        {
            if (!_module.IsExecutable || _module.TestId != "CT-09")
                throw new InvalidOperationException("CT-09模块未正确注册。");
            if (!_hardware.IsTwoTdConnected)
                throw new InvalidOperationException("请先连接真实2TD双轴转台。");
            var id = _hardware.CurrentIdentity ?? throw new InvalidOperationException("请先连接IMU并读取完整UID。");
            if (_calibration.Mode != CalibrationMode.Ambient)
                throw new InvalidOperationException("请在主界面选择当前PCB匹配的常温ACC/Gyro标定。");
            _calibration.Validate(id);
            var s = BuildSettings();
            if (!Directory.Exists(_root)) throw new DirectoryNotFoundException("报告根目录不存在：" + _root);
            await _hardware.VerifyImuForPrecisionTestAsync(CancellationToken.None);
            var feedback = await _hardware.ReadTwoTdAsync(CancellationToken.None);
            if (!feedback.Inner.Normal || !feedback.Outer.Normal ||
                feedback.Inner.Enabled != true || feedback.Outer.Enabled != true ||
                Math.Abs(feedback.Inner.SpeedDps) > 0.05 || Math.Abs(feedback.Outer.SpeedDps) > 0.05)
                throw new IOException("开始前2TD双轴必须正常、已使能且静止。");

            string poseText = string.Join("\n", s.Poses.Select(p => $"内轴{p.InnerDeg:F1}° / 外轴{p.OuterDeg:F1}°"));
            if (MessageBox.Show(this,
                $"设备：{id.DtsId} / {id.UidHex}\n计划姿态：\n{poseText}\n\n" +
                $"每姿态重复{s.RepeatsPerPose}次，共{s.Poses.Count * s.RepeatsPerPose}段采集。\n" +
                $"定位速度{s.MotionSpeedDps:F1}°/s，静置{s.SettleSeconds:F1}s，采集{s.SampleSeconds:F1}s。\n\n" +
                "确认夹具、线缆、真实行程和实体急停已检查，并安排人员现场监护？",
                "CT-09真实硬件测试确认", MessageBoxButton.YesNo, MessageBoxImage.Warning) != MessageBoxResult.Yes)
                return;

            _cts = new CancellationTokenSource();
            StartButton.IsEnabled = false; StopButton.IsEnabled = true; CloseButton.IsEnabled = false;
            ReportButton.IsEnabled = false; RunsGrid.ItemsSource = null; PoseGrid.ItemsSource = null;
            MetricsText.Text = "采集中；尚不提前判定PASS。";
            RunProgressBar.Value = 0;
            int total = s.Poses.Count * s.RepeatsPerPose;
            var progress = new Progress<string>(message =>
            {
                StatusText.Text = message;
                var match = System.Text.RegularExpressions.Regex.Match(message, @"\[(\d+)/(\d+)\]");
                if (match.Success && int.TryParse(match.Groups[1].Value, out int done) &&
                    int.TryParse(match.Groups[2].Value, out int all) && all > 0)
                {
                    ProgressText.Text = $"{done}/{all}段采集";
                    RunProgressBar.Value = Math.Clamp(done * 100d / all, 0, 100);
                }
            });
            var context = new TestExecutionContext(_definition, TimeSpan.FromSeconds(s.SampleSeconds),
                _hardware, progress, s);
            var result = await _runner.RunAsync(_module, context, _cts.Token);
            StatusText.Text = result.Summary;
            RunProgressBar.Value = 100;
            var json = result.Files.FirstOrDefault(f => f.EndsWith("CT-09_result.json", StringComparison.OrdinalIgnoreCase));
            if (json is not null && File.Exists(json)) ShowReport(json);
        }
        catch (OperationCanceledException)
        {
            StatusText.Text = "已取消；已完成采集数据应保留。请确认转台实际停稳。";
            LoadPartialReport();
        }
        catch (Exception ex)
        {
            StatusText.Text = "CT-09测试中止：" + ex.Message;
            LoadPartialReport();
            MessageBox.Show(this, ex.Message, "CT-09测试中止", MessageBoxButton.OK, MessageBoxImage.Warning);
        }
        finally
        {
            _cts?.Dispose(); _cts = null;
            StartButton.IsEnabled = true; StopButton.IsEnabled = false; CloseButton.IsEnabled = true;
        }
    }

    private void ShowReport(string json)
    {
        var data = JsonSerializer.Deserialize<Ct09ReportData>(File.ReadAllText(json))
            ?? throw new InvalidDataException("CT-09结果JSON无法读取。");
        RunsGrid.ItemsSource = data.Visits.Select(v => new
        {
            v.Index, v.PoseIndex, v.Repeat,
            Inner = v.InnerActualDeg.ToString("F2", CultureInfo.InvariantCulture),
            Outer = v.OuterActualDeg.ToString("F2", CultureInfo.InvariantCulture),
            Gx = v.GyroCorrectedMeanDps[0].ToString("F6", CultureInfo.InvariantCulture),
            Gy = v.GyroCorrectedMeanDps[1].ToString("F6", CultureInfo.InvariantCulture),
            Gz = v.GyroCorrectedMeanDps[2].ToString("F6", CultureInfo.InvariantCulture),
            Norm = v.ZeroRateNormDps.ToString("F6", CultureInfo.InvariantCulture),
            Frames = $"{v.AcceptedSamples}/{v.TotalSamples}",
            Temp = v.MeanTemperatureC?.ToString("F2", CultureInfo.InvariantCulture) ?? "—"
        }).ToArray();
        if (data.Metrics is { } m)
        {
            PoseGrid.ItemsSource = m.PoseSummaries.Select(v => new
            {
                v.PoseIndex, Inner = v.InnerDeg.ToString("F1"), Outer = v.OuterDeg.ToString("F1"),
                v.Runs, Gx = v.MeanGyroDps[0].ToString("F6"), Gy = v.MeanGyroDps[1].ToString("F6"),
                Gz = v.MeanGyroDps[2].ToString("F6"), Norm = v.ZeroRateNormDps.ToString("F6"),
                Temp = v.MeanTemperatureC?.ToString("F2") ?? "—"
            }).ToArray();
            MetricsText.Text =
                $"总体Gyro零速均值 X/Y/Z：{m.GrandMeanGyroDps[0]:F6} / {m.GrandMeanGyroDps[1]:F6} / {m.GrandMeanGyroDps[2]:F6} °/s\n" +
                $"姿态均值范围 X/Y/Z：{m.PoseMeanRangeDps[0]:F6} / {m.PoseMeanRangeDps[1]:F6} / {m.PoseMeanRangeDps[2]:F6} °/s\n" +
                $"最大姿态均值矢量差异：{m.MaxPoseMeanVectorDifferenceDps:F6} °/s；温度：{(m.TemperatureMinC.HasValue ? m.TemperatureMinC.Value.ToString("F2") : "—")}～{(m.TemperatureMaxC.HasValue ? m.TemperatureMaxC.Value.ToString("F2") : "—")}℃。";
        }
        else MetricsText.Text = "完成采集不足2轮，暂不能计算跨姿态统计。";
        _reportHtml = Path.Combine(Path.GetDirectoryName(json)!, "CT-09_report.html");
        _latestFolder = Path.GetDirectoryName(json);
        ReportButton.IsEnabled = File.Exists(_reportHtml);
        OutputText.Text = "结果目录：" + _latestFolder;
    }

    private void LoadPartialReport()
    {
        try
        {
            var id = _hardware.CurrentIdentity;
            if (id is null) return;
            string deviceFolder = Path.Combine(_root, id.DtsId + "_" + id.UidHex);
            if (!Directory.Exists(deviceFolder)) return;
            var latest = Directory.EnumerateDirectories(deviceFolder, "*_CT-09")
                .OrderByDescending(Directory.GetCreationTimeUtc).FirstOrDefault();
            if (latest is null) return;
            _latestFolder = latest;
            string json = Path.Combine(latest, "CT-09_result.json");
            if (File.Exists(json)) ShowReport(json);
            else
            {
                string checkpoint = Path.Combine(latest, "CT-09_checkpoint.json");
                if (File.Exists(checkpoint)) OutputText.Text = "部分检查点：" + checkpoint;
            }
            _reportHtml = Path.Combine(latest, "CT-09_report.html");
            ReportButton.IsEnabled = File.Exists(_reportHtml);
        }
        catch { /* Keep the original test error visible. */ }
    }

    private void ReportClick(object sender, RoutedEventArgs e)
    {
        if (_reportHtml is not null && File.Exists(_reportHtml))
            Process.Start(new ProcessStartInfo(_reportHtml) { UseShellExecute = true });
    }
    private void StopClick(object sender, RoutedEventArgs e) => _cts?.Cancel();
    private void CloseClick(object sender, RoutedEventArgs e)
    {
        if (_cts is not null) { MessageBox.Show(this, "请先停止测试并等待软停车流程结束。", "CT-09正在运行"); return; }
        Close();
    }
}
