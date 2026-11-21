using System.ComponentModel;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Text.Json;
using System.Windows;
using Dts.Core;
using Dts.TestEngine;
using Dts.Tests.S1.CT14;

namespace Dts.Wpf.TestWindows.CT14;

[Dts.Wpf.TestWindows.TestWindowFor("CT-14")]
public partial class CT14Window : Window, Dts.Wpf.TestWindows.ICalibrationRunAware
{
    private readonly TestDefinition _definition;
    private readonly ITestModule _module;
    private readonly IStaticAngleHardware _hardware;
    private readonly TestRunner _runner;
    private readonly string _root;
    private CalibrationRun _calibration = CalibrationRun.Raw;
    private CancellationTokenSource? _cts;
    private TaskCompletionSource<bool>? _mountConfirmation;
    private string? _sessionFolder;
    private string? _reportHtml;
    private string? _expectedUid;
    private string? _expectedDevice;
    private DateTimeOffset _sessionStarted;
    private Ct14SettingsSnapshot? _settingsSnapshot;
    private bool _isWaitingForMount;
    private int _gravitySign;
    private string _referenceModel = "";

    public CT14Window(TestDefinition definition, ITestModule module, IStaticAngleHardware hardware,
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
            var id = _hardware.CurrentIdentity ?? throw new InvalidOperationException("请先在主窗口连接IMU并读取完整UID。");
            if (run.Mode != CalibrationMode.Ambient)
                throw new InvalidOperationException("CT-14当前要求主界面选择常温标定模式。");
            run.Validate(id);
            var acc = run.Files?.Acc ?? throw new InvalidDataException("缺少当前UID匹配的ACC常温JSON。");
            var gyro = run.Files?.Gyro ?? throw new InvalidDataException("缺少当前UID匹配的Gyro常温JSON。");
            (_gravitySign, _referenceModel) = ReadGravityReference(acc.FilePath);
            CalibrationText.Text = $"常温标定已匹配：ACC {Path.GetFileName(acc.FilePath)}（±{acc.FsHint}g）；Gyro {Path.GetFileName(gyro.FilePath)}（±{gyro.FsHint}°/s）；{run.IdentityProof}";
        }
        catch (Exception ex) { CalibrationText.Text = "标定条件未就绪：" + ex.Message; }
    }

    private static double D(string value, string name)
    {
        if (!double.TryParse(value.Trim(), NumberStyles.Float, CultureInfo.InvariantCulture, out double v) || !double.IsFinite(v))
            throw new InvalidDataException($"{name}必须是有效数值，使用英文小数点。");
        return v;
    }
    private static int I(string value, string name)
    {
        if (!int.TryParse(value.Trim(), NumberStyles.Integer, CultureInfo.InvariantCulture, out int v))
            throw new InvalidDataException($"{name}必须是整数。");
        return v;
    }

    private Ct14SettingsSnapshot BuildSnapshot()
    {
        var poses = new List<Ct14Pose>();
        int index = 0;
        foreach (var item in PoseBox.Text.Split(';', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
        {
            var pair = item.Split(',', StringSplitOptions.TrimEntries);
            if (pair.Length != 2) throw new InvalidDataException($"姿态格式错误：{item}。格式为内轴°,外轴°。");
            poses.Add(new Ct14Pose(++index, D(pair[0], "内轴角"), D(pair[1], "外轴角")));
        }
        return new Ct14SettingsSnapshot(I(MountCountBox.Text, "独立装夹次数"), MountingSopBox.Text.Trim(), poses,
            I(RepeatBox.Text, "每姿态重复次数"), D(SpeedBox.Text, "定位速度"),
            D(WarmupBox.Text, "预热时间"), D(SettleBox.Text, "静置时间"),
            D(SampleBox.Text, "采集时间"), D(ToleranceBox.Text, "到位容差"),
            D(MinTravelBox.Text, "允许最小角度"), D(MaxTravelBox.Text, "允许最大角度"),
            I(MinSamplesBox.Text, "最少有效帧"), D(MaxOutlierBox.Text, "最大异常剔除比例"));
    }

    private Ct14Settings BuildSettings(int mountIndex, string sessionFolder, bool safetyRequired = true)
    {
        var p = BuildSnapshot();
        var settings = new Ct14Settings(_root, sessionFolder, mountIndex, p.PlannedMounts, p.MountingProcedureNote,
            p.Poses, p.RepeatsPerPose, p.MotionSpeedDps, p.WarmupSeconds, p.SettleSeconds,
            p.SampleSeconds, p.PositionToleranceDeg, p.AllowedMinDeg, p.AllowedMaxDeg,
            p.MinValidSamples, p.MaxOutlierFraction, DirectionCheck.IsChecked == true,
            SafetyCheck.IsChecked == true, _calibration);
        Ct14Algorithm.Validate(settings, safetyRequired);
        return settings;
    }

    private void PreviewClick(object sender, RoutedEventArgs e)
    {
        try
        {
            var p = BuildSnapshot();
            Ct14Algorithm.Validate(new Ct14Settings(_root, _root, 1, p.PlannedMounts, p.MountingProcedureNote,
                p.Poses, p.RepeatsPerPose, p.MotionSpeedDps, p.WarmupSeconds,
                p.SettleSeconds, p.SampleSeconds, p.PositionToleranceDeg,
                p.AllowedMinDeg, p.AllowedMaxDeg, p.MinValidSamples,
                p.MaxOutlierFraction, false, false, _calibration), false);
            MessageBox.Show(this,
                $"计划独立装夹：{p.PlannedMounts}次；每次装夹姿态：{p.Poses.Count}个；每姿态重复：{p.RepeatsPerPose}次。\n" +
                $"总采集单元：{p.PlannedMounts * p.Poses.Count * p.RepeatsPerPose}段。\n" +
                $"每次重新连接后预热：{p.WarmupSeconds:F0}s；定位速度：{p.MotionSpeedDps:F1}°/s；" +
                $"静置：{p.SettleSeconds:F1}s；采集：{p.SampleSeconds:F1}s。\n\n" +
                "注意：每轮装夹后都必须使用相同机械基准、紧固顺序/扭矩和线缆布置。姿态计划与行程仍须现场核验。",
                "CT-14测试预览", MessageBoxButton.OK, MessageBoxImage.Information);
        }
        catch (Exception ex) { MessageBox.Show(this, ex.Message, "CT-14参数检查", MessageBoxButton.OK, MessageBoxImage.Warning); }
    }

    private async void StartClick(object sender, RoutedEventArgs e)
    {
        if (_cts is not null) return;
        try
        {
            if (!_module.IsExecutable || _module.TestId != "CT-14")
                throw new InvalidOperationException("CT-14模块尚未正确注册。");
            if (!_hardware.IsTwoTdConnected)
                throw new InvalidOperationException("请先连接真实2TD双轴转台。");
            var id = _hardware.CurrentIdentity ?? throw new InvalidOperationException("请先连接IMU并读取完整UID。");
            if (_calibration.Mode != CalibrationMode.Ambient)
                throw new InvalidOperationException("请在主界面选择当前PCB匹配的常温ACC/Gyro标定。");
            _calibration.Validate(id);
            if (!Directory.Exists(_root)) throw new DirectoryNotFoundException("报告根目录不存在：" + _root);
            if (InitialMountCheck.IsChecked != true)
                throw new InvalidOperationException("请先确认首轮PCB已按规定装夹并核验完整UID。");
            if (MountProcedureCheck.IsChecked != true)
                throw new InvalidOperationException("请先确认重复装夹的定位基准、紧固顺序/扭矩及线缆规范。");

            var snapshot = BuildSnapshot();
            _ = BuildSettings(1, _root); // Validate all parameters and safety confirmations before hardware activity.
            var accModel = _calibration.Files?.Acc ?? throw new InvalidDataException("缺少ACC常温标定文件。");
            (_gravitySign, _referenceModel) = ReadGravityReference(accModel.FilePath);
            await _hardware.VerifyImuForPrecisionTestAsync(CancellationToken.None);
            var initialFeedback = await _hardware.ReadTwoTdAsync(CancellationToken.None);
            if (!initialFeedback.Inner.Normal || !initialFeedback.Outer.Normal ||
                initialFeedback.Inner.Enabled != true || initialFeedback.Outer.Enabled != true ||
                Math.Abs(initialFeedback.Inner.SpeedDps) > 0.05 || Math.Abs(initialFeedback.Outer.SpeedDps) > 0.05)
                throw new IOException("开始前要求2TD双轴正常、已使能且静止。");

            string poseText = string.Join("\n", snapshot.Poses.Select(p => $"内轴{p.InnerDeg:F1}° / 外轴{p.OuterDeg:F1}°"));
            if (MessageBox.Show(this,
                $"设备：{id.DtsId} / UID：{id.UidHex}\n计划装夹：{snapshot.PlannedMounts}次\n姿态：\n{poseText}\n" +
                $"每姿态重复：{snapshot.RepeatsPerPose}次；总采集单元：{snapshot.PlannedMounts * snapshot.Poses.Count * snapshot.RepeatsPerPose}。\n\n" +
                "确认已核对夹具定位基准、紧固方式、线缆运动路径、真实行程及实体急停？测试过程中须现场监护。",
                "CT-14真实硬件测试确认", MessageBoxButton.YesNo, MessageBoxImage.Warning) != MessageBoxResult.Yes)
                return;

            _expectedUid = id.UidHex; _expectedDevice = id.DtsId;
            _sessionStarted = DateTimeOffset.UtcNow;
            _settingsSnapshot = snapshot;
            _sessionFolder = Path.Combine(_root, $"{id.DtsId}_{id.UidHex}",
                $"{DateTime.Now:yyyyMMdd_HHmmss_fff}_CT-14");
            Directory.CreateDirectory(_sessionFolder);
            _cts = new CancellationTokenSource();
            StartButton.IsEnabled = false; StopButton.IsEnabled = true; CloseButton.IsEnabled = false;
            SettingsScroll.IsEnabled = false;
            ReportButton.IsEnabled = false; ConfirmMountButton.IsEnabled = false;
            RunsGrid.ItemsSource = null; PoseGrid.ItemsSource = null; RunProgressBar.Value = 0;
            var allVisits = new List<Ct14Visit>();
            string state = "RUNNING", reason = "", finalReportProblem = "";

            try
            {
                for (int mount = 1; mount <= snapshot.PlannedMounts; mount++)
                {
                    _cts.Token.ThrowIfCancellationRequested();
                    if (mount > 1)
                        await WaitForOperatorRemountAsync(mount, _cts.Token);

                    var current = _hardware.CurrentIdentity ?? throw new InvalidOperationException("当前IMU未连接。");
                    if (!current.UidHex.Equals(_expectedUid, StringComparison.OrdinalIgnoreCase) ||
                        !current.DtsId.Equals(_expectedDevice, StringComparison.OrdinalIgnoreCase))
                        throw new InvalidDataException($"第{mount}次装夹的设备UID与首轮不一致。");
                    if (!_hardware.IsTwoTdConnected)
                        throw new InvalidOperationException("第" + mount + "次装夹开始前2TD连接已丢失。");
                    _calibration.Validate(current);

                    var settings = BuildSettings(mount, _sessionFolder);
                    var progress = new Progress<string>(message =>
                    {
                        StatusText.Text = message;
                        ProgressText.Text = $"当前装夹：{mount}/{snapshot.PlannedMounts}";
                    });
                    var context = new TestExecutionContext(_definition,
                        TimeSpan.FromSeconds(settings.SampleSeconds), _hardware, progress, settings);
                    var result = await _runner.RunAsync(_module, context, _cts.Token);
                    if (result.Outcome != TestOutcome.PendingAcceptance)
                        throw new InvalidOperationException("CT-14本轮未返回预期的研发待验收结果。");
                    var mountJson = result.Files.FirstOrDefault(f =>
                        f.EndsWith($"CT-14_mount_{mount:D2}_result.json", StringComparison.OrdinalIgnoreCase));
                    if (mountJson is null || !File.Exists(mountJson))
                        throw new FileNotFoundException("CT-14本轮结果JSON未生成。");
                    var mountData = JsonSerializer.Deserialize<Ct14ReportData>(File.ReadAllText(mountJson))
                        ?? throw new InvalidDataException("CT-14本轮JSON无法读取。");
                    allVisits.AddRange(mountData.Visits);
                    RefreshGrids(allVisits);
                    var interim = MakeSessionReport(allVisits, "RUNNING",
                        $"已完成{mount}/{snapshot.PlannedMounts}次装夹；等待下一轮人工拆卸/重装。");
                    await Ct14Report.SaveSessionCheckpointAsync(_sessionFolder, interim, _cts.Token);
                    StatusText.Text = $"第{mount}/{snapshot.PlannedMounts}次装夹完成，已采集{mountData.Visits.Count}段。";
                    RunProgressBar.Value = mount * 100d / snapshot.PlannedMounts;
                }

                state = "COMPLETED_PENDING_ACCEPTANCE";
                reason = $"完成{snapshot.PlannedMounts}次独立装夹，共{allVisits.Count}段真实采集；结果待产品指标验收。";
            }
            catch (OperationCanceledException)
            {
                state = "CANCELLED_PARTIAL"; reason = "测试被用户取消；保留已完成装夹周期和部分采集。";
                allVisits = LoadMountVisits(_sessionFolder);
                throw;
            }
            catch (Exception ex)
            {
                state = "FAILED_PARTIAL"; reason = ex.Message;
                allVisits = LoadMountVisits(_sessionFolder);
                throw;
            }
            finally
            {
                var final = MakeSessionReport(allVisits, state, reason);
                try
                {
                    var files = await Ct14Report.ExportSessionAsync(_sessionFolder, final, CancellationToken.None);
                    _reportHtml = files.FirstOrDefault(f => f.EndsWith("CT-14_report.html", StringComparison.OrdinalIgnoreCase));
                    ReportButton.IsEnabled = _reportHtml is not null && File.Exists(_reportHtml);
                    OutputText.Text = "最终报告目录：" + _sessionFolder;
                    RefreshGrids(allVisits);
                    RefreshMetrics(final);
                }
                catch (Exception ex)
                {
                    finalReportProblem = ex.Message;
                }
            }

            StatusText.Text = reason + (finalReportProblem.Length > 0 ? "；最终汇总报告生成失败：" + finalReportProblem : "");
            RunProgressBar.Value = state == "COMPLETED_PENDING_ACCEPTANCE" ? 100 : RunProgressBar.Value;
        }
        catch (OperationCanceledException)
        {
            StatusText.Text = "已请求停止。已完成装夹周期已保留；请检查转台实际状态和部分报告。";
            if (_sessionFolder is not null) LoadPartialSession();
        }
        catch (Exception ex)
        {
            StatusText.Text = "CT-14测试中止：" + ex.Message;
            if (_sessionFolder is not null) LoadPartialSession();
            MessageBox.Show(this, ex.Message, "CT-14测试中止", MessageBoxButton.OK, MessageBoxImage.Warning);
        }
        finally
        {
            _mountConfirmation?.TrySetCanceled();
            _mountConfirmation = null;
            _isWaitingForMount = false;
            _cts?.Dispose(); _cts = null;
            StartButton.IsEnabled = true; StopButton.IsEnabled = false;
            CloseButton.IsEnabled = true; ConfirmMountButton.IsEnabled = false;
            SettingsScroll.IsEnabled = true;
        }
    }

    private async Task WaitForOperatorRemountAsync(int mountIndex, CancellationToken ct)
    {
        _isWaitingForMount = true;
        ReinstallCheck.IsChecked = false; ReconnectCheck.IsChecked = false;
        MountInstructionText.Text =
            $"请完成第{mountIndex}/{_settingsSnapshot!.PlannedMounts}次装夹：将PCB从夹具拆下，再按相同机械定位基准、紧固顺序/扭矩和线缆布置重新安装。若断开供电，请在主程序重新连接COM口并确认完整UID。可最小化本窗口操作主程序。";
        StatusText.Text = $"等待人工完成第{mountIndex}次拆卸与重新装夹。";
        ConfirmMountButton.IsEnabled = true;
        _mountConfirmation = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
        await _mountConfirmation.Task.WaitAsync(ct);
        ConfirmMountButton.IsEnabled = false;
        _isWaitingForMount = false;
        MountInstructionText.Text = $"第{mountIndex}次装夹已确认。即将统一预热{_settingsSnapshot.WarmupSeconds:F0}s，然后自动定位和采集。";
    }

    private async void ConfirmMountClick(object sender, RoutedEventArgs e)
    {
        try
        {
            if (!_isWaitingForMount || _mountConfirmation is null)
                throw new InvalidOperationException("当前没有等待确认的装夹周期。");
            if (ReinstallCheck.IsChecked != true || ReconnectCheck.IsChecked != true)
                throw new InvalidOperationException("请同时确认重新装夹规范和主程序重新连接。");
            var id = _hardware.CurrentIdentity ?? throw new InvalidOperationException("当前IMU未连接或UID不可读。");
            if (_expectedUid is null || _expectedDevice is null ||
                !id.UidHex.Equals(_expectedUid, StringComparison.OrdinalIgnoreCase) ||
                !id.DtsId.Equals(_expectedDevice, StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("当前连接设备UID与首轮不一致，禁止继续。");
            if (!_hardware.IsTwoTdConnected)
                throw new InvalidOperationException("2TD未连接。");
            await _hardware.VerifyImuForPrecisionTestAsync(CancellationToken.None);
            var b = await _hardware.ReadTwoTdAsync(CancellationToken.None);
            if (!b.Inner.Normal || !b.Outer.Normal || b.Inner.Enabled != true || b.Outer.Enabled != true ||
                Math.Abs(b.Inner.SpeedDps) > 0.05 || Math.Abs(b.Outer.SpeedDps) > 0.05)
                throw new IOException("重新装夹后要求2TD双轴正常、使能且静止。");
            _mountConfirmation.TrySetResult(true);
            ConfirmMountButton.IsEnabled = false;
            StatusText.Text = "重新装夹确认完成，开始下一轮。";
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, "CT-14装夹确认", MessageBoxButton.OK, MessageBoxImage.Warning);
        }
    }

    private static (int Sign, string Model) ReadGravityReference(string file)
    {
        using var doc = JsonDocument.Parse(File.ReadAllText(file));
        var root = doc.RootElement;
        if (!root.TryGetProperty("axis_model", out var modelElement) ||
            modelElement.ValueKind != JsonValueKind.String ||
            modelElement.GetString() != "outer_x_inner_z")
            throw new InvalidDataException("CT-14仅支持ACC常温JSON中明确声明的axis_model=outer_x_inner_z。");
        if (!root.TryGetProperty("gravity_sign", out var signElement) ||
            !signElement.TryGetInt32(out int sign) || sign is not (1 or -1))
            throw new InvalidDataException("ACC常温JSON必须明确提供gravity_sign=+1或-1。");
        return (sign, modelElement.GetString()!);
    }

    private Ct14ReportData MakeSessionReport(IReadOnlyList<Ct14Visit> visits, string state, string reason)
    {
        var id = _hardware.CurrentIdentity;
        string device = _expectedDevice ?? id?.DtsId ?? "UNKNOWN";
        string uid = _expectedUid ?? id?.UidHex ?? "UNKNOWN";
        var acc = _calibration.Files?.Acc;
        var gyro = _calibration.Files?.Gyro;
        var scale = acc?.FsHint is int af && gyro?.FsHint is int gf
            ? CalibrationInputScalePolicy.Resolve(af, gf, 0, 0)?.Display ?? "未解析"
            : "标定JSON未声明输入量程";
        int sign = _gravitySign;
        string model = _referenceModel;
        if (sign is not (1 or -1) || model != "outer_x_inner_z")
            throw new InvalidDataException("CT-14汇总缺少已核验的ACC重力参考模型。");
        var p = _settingsSnapshot ?? BuildSnapshot();
        var conclusion = state == "COMPLETED_PENDING_ACCEPTANCE"
            ? "已完成计划装夹与真实采集；跨装夹差异为研发诊断指标，不自动判定产品PASS。"
            : "部分装夹/采集已保留；当前汇总不能作为完整试验结论。";
        return new Ct14ReportData("CT-14", "重复装夹与复测一致性", device, uid, 0,
            _sessionStarted, DateTimeOffset.UtcNow, state, reason, conclusion,
            acc is null ? "" : Path.GetFileName(acc.FilePath), acc?.Sha256 ?? "",
            gyro is null ? "" : Path.GetFileName(gyro.FilePath), gyro?.Sha256 ?? "",
            sign, model, scale, p, visits.ToArray(), Ct14Algorithm.Summarize(visits));
    }

    private static List<Ct14Visit> LoadMountVisits(string sessionFolder)
    {
        var visits = new List<Ct14Visit>();
        if (!Directory.Exists(sessionFolder)) return visits;
        foreach (var file in Directory.EnumerateFiles(sessionFolder, "CT-14_mount_*_result.json", SearchOption.AllDirectories))
        {
            try
            {
                var data = JsonSerializer.Deserialize<Ct14ReportData>(File.ReadAllText(file));
                if (data is not null) visits.AddRange(data.Visits);
            }
            catch (Exception ex) when (ex is IOException or JsonException or UnauthorizedAccessException) { }
        }
        return visits.OrderBy(v => v.MountIndex).ThenBy(v => v.VisitIndex).ToList();
    }

    private void LoadPartialSession()
    {
        try
        {
            if (_sessionFolder is null) return;
            var visits = LoadMountVisits(_sessionFolder);
            if (_settingsSnapshot is null) return;
            var data = MakeSessionReport(visits, "PARTIAL_PENDING_ACCEPTANCE", "测试中止；已完成装夹周期保留。");
            var files = Ct14Report.ExportSessionAsync(_sessionFolder, data, CancellationToken.None).GetAwaiter().GetResult();
            _reportHtml = files.FirstOrDefault(f => f.EndsWith("CT-14_report.html", StringComparison.OrdinalIgnoreCase));
            ReportButton.IsEnabled = _reportHtml is not null && File.Exists(_reportHtml);
            RefreshGrids(visits); RefreshMetrics(data);
            OutputText.Text = "部分报告目录：" + _sessionFolder;
        }
        catch (Exception ex) { OutputText.Text = "部分报告生成失败，请检查数据目录：" + ex.Message; }
    }

    private void RefreshGrids(IReadOnlyList<Ct14Visit> visits)
    {
        RunsGrid.ItemsSource = visits.Select(v => new
        {
            Mount = v.MountIndex, Pose = v.PoseIndex, v.Repeat,
            ErrorMg = v.VectorReferenceErrorMg.ToString("F3", CultureInfo.InvariantCulture),
            AngleError = v.DirectionReferenceErrorDeg.ToString("F4", CultureInfo.InvariantCulture),
            Gx = v.GyroCorrectedMeanDps[0].ToString("F6", CultureInfo.InvariantCulture),
            Gy = v.GyroCorrectedMeanDps[1].ToString("F6", CultureInfo.InvariantCulture),
            Gz = v.GyroCorrectedMeanDps[2].ToString("F6", CultureInfo.InvariantCulture),
            Frames = $"{v.AcceptedSamples}/{v.TotalSamples}",
            Temp = v.MeanTemperatureC.ToString("F2", CultureInfo.InvariantCulture)
        }).ToArray();

        var summaries = visits.GroupBy(v => new { v.MountIndex, v.PoseIndex })
            .OrderBy(g => g.Key.MountIndex).ThenBy(g => g.Key.PoseIndex)
            .Select(g => new
            {
                Mount = g.Key.MountIndex, Pose = g.Key.PoseIndex,
                Ax = g.Average(v => v.AccCorrectedMeanG[0]).ToString("F7"),
                Ay = g.Average(v => v.AccCorrectedMeanG[1]).ToString("F7"),
                Az = g.Average(v => v.AccCorrectedMeanG[2]).ToString("F7"),
                Gx = g.Average(v => v.GyroCorrectedMeanDps[0]).ToString("F6"),
                Gy = g.Average(v => v.GyroCorrectedMeanDps[1]).ToString("F6"),
                Gz = g.Average(v => v.GyroCorrectedMeanDps[2]).ToString("F6"),
                Temp = g.Average(v => v.MeanTemperatureC).ToString("F2")
            }).ToArray();
        PoseGrid.ItemsSource = summaries;
    }

    private void RefreshMetrics(Ct14ReportData data)
    {
        if (data.Metrics is not { } m)
        {
            MetricsText.Text = $"已完成{data.Visits.Select(v => v.MountIndex).Distinct().Count()}次装夹；至少需要2次装夹且存在相同姿态数据，才能计算跨装夹差异。";
            return;
        }
        MetricsText.Text =
            $"ACC跨装夹STD X/Y/Z：{m.AccMountingStdMg[0]:F4} / {m.AccMountingStdMg[1]:F4} / {m.AccMountingStdMg[2]:F4} mg\n" +
            $"ACC矢量差RMS：{m.AccMountingVectorRmsMg:F4} mg；最大偏离：{m.AccMountingVectorMaxMg:F4} mg；方向差RMS：{m.AccMountingAngleRmsDeg:F5}°\n" +
            $"Gyro跨装夹STD X/Y/Z：{m.GyroMountingStdDps[0]:F6} / {m.GyroMountingStdDps[1]:F6} / {m.GyroMountingStdDps[2]:F6} °/s\n" +
            $"芯片温度范围：{m.TemperatureMinC:F2}～{m.TemperatureMaxC:F2}℃；有效帧：{m.AcceptedFrames}。";
    }

    private void StopClick(object sender, RoutedEventArgs e)
    {
        StatusText.Text = "已请求停止。当前运动会执行双轴软停车；如出现失控或异常运动，立即使用实体急停。";
        _cts?.Cancel();
        _mountConfirmation?.TrySetCanceled();
    }

    private void ReportClick(object sender, RoutedEventArgs e)
    {
        if (_reportHtml is not null && File.Exists(_reportHtml))
            Process.Start(new ProcessStartInfo(_reportHtml) { UseShellExecute = true });
    }

    private void OnClosing(object? sender, CancelEventArgs e)
    {
        if (_cts is not null)
        {
            e.Cancel = true;
            MessageBox.Show(this, "CT-14测试或人工装夹确认仍在进行，请先停止测试并等待软停车。", "CT-14正在运行");
        }
    }

    private void CloseClick(object sender, RoutedEventArgs e)
    {
        if (_cts is not null)
        {
            MessageBox.Show(this, "测试或人工装夹确认流程正在进行，请先停止测试。", "CT-14正在运行");
            return;
        }
        Close();
    }
}
