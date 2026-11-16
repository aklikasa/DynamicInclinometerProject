using System.Globalization;
using System.Net;
using System.Text;
using System.Text.Json;
using Dts.Core;
using Dts.Tests.S1.CT10;

namespace Dts.Tests.S1.CT27;

/// <summary>CT-27 evidence export: immutable JSON, per-window CSV, per-cycle CSV and self-contained HTML.</summary>
public static class Ct27Report
{
    private static readonly CultureInfo Ci = CultureInfo.InvariantCulture;
    private static readonly JsonSerializerOptions JsonOptions = new() { WriteIndented = true };

    private static string F(double value, string format = "G17") => value.ToString(format, Ci);
    private static string Q(string? value) => "\"" + (value ?? string.Empty).Replace("\"", "\"\"") + "\"";
    private static string H(string? value) => WebUtility.HtmlEncode(value ?? string.Empty);

    public static async Task SaveCheckpointAsync(string folder, Ct27ReportData data, CancellationToken ct)
    {
        string target = Path.Combine(folder, "CT-27_checkpoint.json");
        string temporary = target + ".tmp";
        await File.WriteAllTextAsync(temporary, JsonSerializer.Serialize(data, JsonOptions),
            new UTF8Encoding(false), ct);
        File.Move(temporary, target, true);
    }

    public static async Task<(string GyroCsv, string EncoderCsv)> WriteMotionEvidenceAsync(
        string folder, int cycleIndex, Ct10Capture capture, CalibrationMatrix gyro, CancellationToken ct)
    {
        string gyroPath = Path.Combine(folder, $"cycle_{cycleIndex:D2}_motion_gyro.csv");
        string encoderPath = Path.Combine(folder, $"cycle_{cycleIndex:D2}_motion_encoder.csv");
        var gyroFrames = capture.GyroFrames.OrderBy(x => x.TimestampTicks).ToArray();
        long gyroStart = gyroFrames.Length == 0 ? 0 : gyroFrames[0].TimestampTicks;
        var gyroLines = new List<string>
        {
            "time_seconds,input_gx_dps,input_gy_dps,input_gz_dps,calibrated_gx_dps,calibrated_gy_dps,calibrated_gz_dps,temp_c,raw_gx,raw_gy,raw_gz"
        };
        foreach (var frame in gyroFrames)
        {
            ct.ThrowIfCancellationRequested();
            double[] calibrated = gyro.Apply(frame.InputX_Dps, frame.InputY_Dps, frame.InputZ_Dps);
            double time = (frame.TimestampTicks - gyroStart) / (double)capture.TimestampFrequency;
            gyroLines.Add(string.Join(",", new[]
            {
                F(time), F(frame.InputX_Dps), F(frame.InputY_Dps), F(frame.InputZ_Dps),
                F(calibrated[0]), F(calibrated[1]), F(calibrated[2]), F(frame.TemperatureC),
                frame.RawCountX?.ToString(Ci) ?? string.Empty,
                frame.RawCountY?.ToString(Ci) ?? string.Empty,
                frame.RawCountZ?.ToString(Ci) ?? string.Empty
            }));
        }
        await File.WriteAllLinesAsync(gyroPath, gyroLines, new UTF8Encoding(true), ct);

        var encoderFrames = capture.EncoderFrames.OrderBy(x => x.TimestampTicks).ToArray();
        long encoderStart = encoderFrames.Length == 0 ? 0 : encoderFrames[0].TimestampTicks;
        var encoderLines = new List<string>
        {
            "time_seconds,inner_deg,outer_deg,inner_normal,outer_normal,inner_enabled,outer_enabled"
        };
        foreach (var frame in encoderFrames)
        {
            ct.ThrowIfCancellationRequested();
            double time = (frame.TimestampTicks - encoderStart) / (double)capture.TimestampFrequency;
            encoderLines.Add(string.Join(",", new[]
            {
                F(time), F(frame.InnerDeg), F(frame.OuterDeg),
                frame.InnerNormal ? "1" : "0", frame.OuterNormal ? "1" : "0",
                frame.InnerEnabled ? "1" : "0", frame.OuterEnabled ? "1" : "0"
            }));
        }
        await File.WriteAllLinesAsync(encoderPath, encoderLines, new UTF8Encoding(true), ct);
        return (gyroPath, encoderPath);
    }

    public static async Task<IReadOnlyList<string>> ExportAsync(
        string folder, Ct27ReportData data, CancellationToken ct)
    {
        Directory.CreateDirectory(folder);
        string json = Path.Combine(folder, "CT-27_result.json");
        string binsCsv = Path.Combine(folder, "CT-27_recovery_bins.csv");
        string cyclesCsv = Path.Combine(folder, "CT-27_cycles.csv");
        string html = Path.Combine(folder, "CT-27_report.html");
        await SaveCheckpointAsync(folder, data, ct);
        await File.WriteAllTextAsync(json, JsonSerializer.Serialize(data, JsonOptions),
            new UTF8Encoding(false), ct);

        var binLines = new List<string>
        {
            "cycle,bin,since_stop_midpoint_s,since_stop_end_s,started_utc,finished_utc,mean_gx_dps,mean_gy_dps,mean_gz_dps,std_gx_dps,std_gy_dps,std_gz_dps,delta_gx_dps,delta_gy_dps,delta_gz_dps,max_abs_delta_dps,temp_c,samples,batches,duplicates,physical_csv"
        };
        foreach (var b in data.Bins)
        {
            binLines.Add(string.Join(",", new[]
            {
                b.CycleIndex.ToString(Ci), b.BinIndex.ToString(Ci), F(b.SinceStopMidpointSeconds),
                F(b.SinceStopEndSeconds), Q(b.StartedUtc), Q(b.FinishedUtc),
                F(b.MeanX), F(b.MeanY), F(b.MeanZ), F(b.StdX), F(b.StdY), F(b.StdZ),
                F(b.DeltaX), F(b.DeltaY), F(b.DeltaZ), F(b.MaxAbsDeltaDps),
                F(b.MeanTemperatureC), b.Samples.ToString(Ci), b.Batches.ToString(Ci),
                b.DuplicateBatches.ToString(Ci), Q(b.PhysicalCsv)
            }));
        }
        await File.WriteAllLinesAsync(binsCsv, binLines, new UTF8Encoding(true), ct);

        var cycleLines = new List<string>
        {
            "cycle,gyro_axis,turntable_axis,command_dps,measured_median_encoder_dps,repeat,direction,start_deg,end_deg,baseline_started_utc,baseline_ended_utc,baseline_gx_dps,baseline_gy_dps,baseline_gz_dps,baseline_std_gx_dps,baseline_std_gy_dps,baseline_std_gz_dps,baseline_temp_c,baseline_samples,stop_confirmed_utc,peak_max_abs_delta_dps,final_delta_gx_dps,final_delta_gy_dps,final_delta_gz_dps,recovered_by_s,recovery_bins,quality,baseline_csv,motion_gyro_csv,motion_encoder_csv"
        };
        foreach (var c in data.Cycles)
        {
            cycleLines.Add(string.Join(",", new[]
            {
                c.Index.ToString(Ci), Q(c.GyroAxis), Q(c.TurntableAxis), F(c.CommandDps),
                F(c.MeasuredMedianRateDps), c.Repetition.ToString(Ci), Q(c.Direction),
                F(c.StartDeg), F(c.EndDeg), Q(c.BaselineStartedUtc), Q(c.BaselineEndedUtc),
                F(c.BaselineMeanX), F(c.BaselineMeanY), F(c.BaselineMeanZ),
                F(c.BaselineStdX), F(c.BaselineStdY), F(c.BaselineStdZ), F(c.BaselineTemperatureC),
                c.BaselineSamples.ToString(Ci), Q(c.StopConfirmedUtc), F(c.PeakMaxAbsDeltaDps),
                F(c.FinalDeltaX), F(c.FinalDeltaY), F(c.FinalDeltaZ),
                c.RecoveredBySeconds.HasValue ? F(c.RecoveredBySeconds.Value) : string.Empty,
                c.RecoveryBins.ToString(Ci), Q(c.Quality), Q(c.BaselineCsv),
                Q(c.MotionGyroCsv), Q(c.MotionEncoderCsv)
            }));
        }
        await File.WriteAllLinesAsync(cyclesCsv, cycleLines, new UTF8Encoding(true), ct);
        await File.WriteAllTextAsync(html, BuildHtml(data), new UTF8Encoding(false), ct);
        return new[] { json, binsCsv, cyclesCsv, html, Path.Combine(folder, "CT-27_checkpoint.json") };
    }

    private static string BuildChart(IReadOnlyList<Ct27RecoveryBin> bins, double band)
    {
        if (bins.Count == 0) return "<p>无恢复窗口数据。</p>";
        double max = Math.Max(band * 1.5, bins.Max(x => x.MaxAbsDeltaDps));
        if (!double.IsFinite(max) || max <= 0) max = 1;
        const double width = 760, height = 220, left = 48, right = 18, top = 16, bottom = 34;
        double xStep = bins.Count <= 1 ? 0 : (width - left - right) / (bins.Count - 1);
        double y(double v) => top + (height - top - bottom) * (1 - Math.Clamp(v / max, 0, 1));
        var points = string.Join(" ", bins.Select((b, i) =>
            $"{(left + i * xStep).ToString("F2", Ci)},{y(b.MaxAbsDeltaDps).ToString("F2", Ci)}"));
        double bandY = y(band);
        return $"<svg viewBox='0 0 {width} {height}' role='img' aria-label='Gyro bias recovery curve'>" +
               $"<line x1='{left}' y1='{bandY:F2}' x2='{width - right}' y2='{bandY:F2}' stroke='#b45b32' stroke-dasharray='6 4'/>" +
               $"<polyline points='{points}' fill='none' stroke='#1769aa' stroke-width='2.5'/>" +
               $"<line x1='{left}' y1='{top}' x2='{left}' y2='{height - bottom}' stroke='#68798a'/>" +
               $"<line x1='{left}' y1='{height - bottom}' x2='{width - right}' y2='{height - bottom}' stroke='#68798a'/>" +
               $"<text x='6' y='16' font-size='11'>max |Δbias| (°/s)</text>" +
               $"<text x='{left}' y='{height - 8}' font-size='11'>恢复窗口序号 →</text>" +
               $"<text x='{width - 190}' y='{Math.Max(12, bandY - 5):F2}' font-size='11' fill='#a34d2c'>观察带 {band:F4}°/s</text></svg>";
    }

    private static string BuildHtml(Ct27ReportData d)
    {
        var sb = new StringBuilder();
        sb.Append("<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>");
        sb.Append("<title>CT-27 Gyro运动后零偏恢复报告</title><style>");
        sb.Append("body{font-family:'Microsoft YaHei',Arial,sans-serif;background:#f3f6fa;color:#243447;margin:24px}h1{color:#1d4f7a}h2{margin-top:0;color:#244e70}.card{background:#fff;border:1px solid #dce5ed;border-radius:10px;padding:18px;margin:14px 0}.muted{color:#60758a}.warn{color:#9b5429;background:#fff6eb;padding:12px;border-radius:6px}table{border-collapse:collapse;width:100%;font-size:13px}th,td{border-bottom:1px solid #e3eaf0;padding:8px;text-align:left}th{background:#edf3f8}svg{width:100%;max-width:850px;height:auto}");
        sb.Append("</style></head><body>");
        sb.Append("<h1>CT-27 · Gyro运动后零偏恢复专项</h1>");
        sb.Append($"<p class='muted'>设备：{H(d.DeviceNumber)}　完整UID：{H(d.UidHex)}　状态：{H(d.State)}</p>");
        sb.Append("<div class='card'><h2>测试摘要</h2>");
        sb.Append($"<p>{H(d.Conclusion)}</p><p>开始：{H(d.StartedUtc)}<br>结束：{H(d.FinishedUtc)}</p>");
        if (d.Aggregate is { } a)
            sb.Append($"<p>完成工况：{a.CompletedCycles}；观察到恢复：{a.RecoveryObservedCycles}；最大观测零偏台阶：{F(a.MaximumObservedBiasStepDps)}°/s；最终最大分量偏差均值：{F(a.MeanFinalMaxAbsDeltaDps)}°/s；恢复时间上界均值：{(a.MeanRecoveryUpperBoundSeconds is double t ? F(t) + "s" : "未确认")}</p>");
        sb.Append($"<p>运动档位：{H(d.Settings.SpeedsCsv)}°/s；基线：{F(d.Settings.BaselineSeconds)}s；恢复观察：{F(d.Settings.RecoverySeconds)}s；窗口：{F(d.Settings.BinSeconds)}s；观察带：{F(d.Settings.RecoveryBandDps)}°/s。</p>");
        sb.Append($"<p>ACC：{H(d.AccFile)}<br>ACC SHA256：{H(d.AccSha256)}<br>Gyro：{H(d.GyroFile)}<br>Gyro SHA256：{H(d.GyroSha256)}</p></div>");
        sb.Append("<div class='card'><h2>工况结果</h2><table><tr><th>序号</th><th>Gyro轴</th><th>方向</th><th>命令速率</th><th>编码器中段速率</th><th>最大零偏台阶</th><th>最终ΔX/Y/Z</th><th>基线温度</th><th>恢复时间上界</th><th>质量</th></tr>");
        foreach (var c in d.Cycles)
            sb.Append($"<tr><td>{c.Index}</td><td>{H(c.GyroAxis)}</td><td>{H(c.Direction)}</td><td>{F(c.CommandDps, "F2")}</td><td>{F(c.MeasuredMedianRateDps, "F2")}</td><td>{F(c.PeakMaxAbsDeltaDps)}</td><td>{F(c.FinalDeltaX)}, {F(c.FinalDeltaY)}, {F(c.FinalDeltaZ)}</td><td>{F(c.BaselineTemperatureC, "F2")}℃</td><td>{(c.RecoveredBySeconds is double t ? F(t) + "s" : "未确认")}</td><td>{H(c.Quality)}</td></tr>");
        sb.Append("</table></div>");
        foreach (var c in d.Cycles)
        {
            var bins = d.Bins.Where(x => x.CycleIndex == c.Index).OrderBy(x => x.BinIndex).ToArray();
            sb.Append($"<div class='card'><h2>工况 {c.Index} · Gyro {H(c.GyroAxis)} · {F(c.CommandDps, "F2")}°/s · {H(c.Direction)}</h2>");
            sb.Append($"<p>运动：{F(c.StartDeg, "F1")}° → {F(c.EndDeg, "F1")}°；编码器中段实测速率中位数：{F(c.MeasuredMedianRateDps, "F3")}°/s。</p>");
            sb.Append(BuildChart(bins, d.Settings.RecoveryBandDps));
            sb.Append("<p class='muted'>曲线为三个已校正Gyro轴相对运动前零速基线的最大绝对均值偏差；虚线仅表示用户设定的观察带，不代表产品验收限值。</p>");
            sb.Append("</div>");
        }
        sb.Append("<div class='card'><h2>方法与限制</h2><p class='warn'>");
        sb.Append(H(d.MethodLimitations));
        sb.Append("</p><p>本报告仅为工程诊断（DiagnosticOnly），不自动给出产品PASS/FAIL。恢复时间是基于离散窗口的观察上界，不是精确物理恢复时刻。</p></div>");
        sb.Append("</body></html>");
        return sb.ToString();
    }
}
