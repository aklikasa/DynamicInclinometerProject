using System.Globalization;
using System.Net;
using System.Text;
using System.Text.Json;
using Dts.Tests.S1.CT10;

namespace Dts.Tests.S1.CT19;

public static class Ct19Report
{
    private static readonly CultureInfo Ci = CultureInfo.InvariantCulture;
    private static readonly JsonSerializerOptions JsonOptions = new() { WriteIndented = true };
    private static string F(double x) => double.IsFinite(x) ? x.ToString("G17", Ci) : "";
    private static string Q(string? s) => "\"" + (s ?? "").Replace("\"", "\"\"") + "\"";
    private static string H(string? s) => WebUtility.HtmlEncode(s ?? "");

    public static async Task WriteSweepCsvAsync(string path, Ct10SweepResult result, CancellationToken ct)
    {
        var b = new StringBuilder("timestamp_ticks,time_seconds,reference_rate_dps,commanded_rate_dps,gyro_axis_rate_dps,residual_dps,gyro_x_corrected_dps,gyro_y_corrected_dps,gyro_z_corrected_dps,temperature_c,encoder_position_deg,accepted,rejection_reason,raw_gx,raw_gy,raw_gz\r\n");
        foreach (var x in result.Samples)
            b.AppendLine(string.Join(",", x.TimestampTicks.ToString(Ci), F(x.TimeSeconds),
                F(x.ReferenceRateDps), F(x.CommandedRateDps), F(x.GyroAxisMeasuredDps), F(x.ResidualDps),
                F(x.GyroXCorrectedDps), F(x.GyroYCorrectedDps), F(x.GyroZCorrectedDps),
                F(x.TemperatureC), F(x.AxisEncoderDeg), x.Accepted ? "true" : "false",
                Q(x.RejectionReason), x.RawGx?.ToString(Ci) ?? "", x.RawGy?.ToString(Ci) ?? "",
                x.RawGz?.ToString(Ci) ?? ""));
        await File.WriteAllTextAsync(path, b.ToString(), new UTF8Encoding(true), ct);
    }

    public static async Task<IReadOnlyList<string>> SaveAsync(
        string folder, Ct19ReportData data, CancellationToken ct, bool checkpoint = false)
    {
        Directory.CreateDirectory(folder);
        string json = Path.Combine(folder, checkpoint ? "CT-19_checkpoint.json" : "CT-19_result.json");
        await File.WriteAllTextAsync(json, JsonSerializer.Serialize(data, JsonOptions), new UTF8Encoding(true), ct);
        if (checkpoint) return new[] { json };

        string runs = Path.Combine(folder, "CT-19_runs.csv");
        var rb = new StringBuilder("index,gyro_axis,turntable_axis,rate_dps,repeat,direction,mean_reference_dps,mean_gyro_dps,mean_residual_dps,residual_rmse_dps,residual_std_dps,scale_ratio_percent,mean_temperature_c,total_gyro_frames,accepted_frames,encoder_frames,csv_file,evidence_source,quality\r\n");
        foreach (var x in data.Runs)
            rb.AppendLine(string.Join(",", x.Index.ToString(Ci), Q(x.GyroAxis), Q(x.TurntableAxis),
                F(x.RateDps), x.Repeat.ToString(Ci), Q(x.Direction), F(x.MeanReferenceDps),
                F(x.MeanGyroDps), F(x.MeanResidualDps), F(x.ResidualRmseDps), F(x.ResidualStdDps),
                F(x.ScaleRatioPercent), F(x.MeanTemperatureC), x.TotalGyroFrames.ToString(Ci),
                x.AcceptedFrames.ToString(Ci), x.EncoderFrames.ToString(Ci), Q(Path.GetFileName(x.CsvFile)),
                Q(x.EvidenceSource), Q(x.Quality)));
        await File.WriteAllTextAsync(runs, rb.ToString(), new UTF8Encoding(true), ct);

        string groups = Path.Combine(folder, "CT-19_groups.csv");
        var gb = new StringBuilder("gyro_axis,rate_dps,direction,repeats,output_mean_dps,output_between_run_std_dps,residual_mean_dps,residual_between_run_std_dps,reference_mean_dps,reference_between_run_std_dps,status\r\n");
        foreach (var x in data.Groups)
            gb.AppendLine(string.Join(",", Q(x.GyroAxis), F(x.RateDps), Q(x.Direction),
                x.Repeats.ToString(Ci), F(x.OutputMeanDps), F(x.OutputBetweenRunStdDps),
                F(x.ResidualMeanDps), F(x.ResidualBetweenRunStdDps), F(x.ReferenceMeanDps),
                F(x.ReferenceBetweenRunStdDps), Q(x.Status)));
        await File.WriteAllTextAsync(groups, gb.ToString(), new UTF8Encoding(true), ct);

        string pairs = Path.Combine(folder, "CT-19_direction_pairs.csv");
        var pb = new StringBuilder("gyro_axis,rate_dps,complete_pairs,forward_residual_dps,reverse_residual_dps,forward_reverse_difference_dps,mean_residual_rmse_dps\r\n");
        foreach (var x in data.DirectionPairs)
            pb.AppendLine(string.Join(",", Q(x.GyroAxis), F(x.RateDps), x.CompletePairs.ToString(Ci),
                F(x.ForwardResidualDps), F(x.ReverseResidualDps), F(x.ForwardReverseDifferenceDps),
                F(x.MeanResidualRmseDps)));
        await File.WriteAllTextAsync(pairs, pb.ToString(), new UTF8Encoding(true), ct);

        string html = Path.Combine(folder, "CT-19_report.html");
        await File.WriteAllTextAsync(html, BuildHtml(data), new UTF8Encoding(true), ct);
        return new[] { json, runs, groups, pairs, html }.Concat(data.Runs.Select(x => x.CsvFile)).ToArray();
    }

    private static string BuildHtml(Ct19ReportData d)
    {
        var b = new StringBuilder("<!doctype html><html lang='zh-CN'><meta charset='utf-8'><title>CT-19 Gyro短期重复性报告</title>");
        b.Append("<style>body{font:14px 'Microsoft YaHei',Arial;max-width:1300px;margin:28px auto;padding:0 20px;color:#23384d}section{border:1px solid #d9e2eb;border-radius:8px;padding:16px;margin:14px 0}h1,h2{color:#185b91}table{border-collapse:collapse;width:100%;font-size:12px}th,td{border:1px solid #d5dee8;padding:7px;text-align:right}th:first-child,td:first-child{text-align:left}.note{color:#8a5a24}</style><body>");
        b.Append("<h1>CT-19｜Gyro独立运行短期重复性</h1><section>");
        b.Append($"<p>设备：{H(d.DeviceNumber)}　UID：{H(d.Uid)}</p><p>开始：{H(d.StartedUtc.ToString("O"))}<br>结束：{H(d.EndedUtc.ToString("O"))}</p>");
        b.Append($"<p>状态：{H(d.State)}</p><p>{H(d.Conclusion)}</p><p class='note'>{H(d.FailureReason)}</p></section>");
        b.Append($"<section><h2>采集溯源</h2><p>ACC常温JSON：{H(d.CalibrationAccFile)} / SHA256：{H(d.CalibrationAccSha256)}<br>Gyro常温JSON：{H(d.CalibrationGyroFile)} / SHA256：{H(d.CalibrationGyroSha256)}</p><p>{H(d.HardwareSource)}</p></section>");
        b.Append("<section><h2>按轴/速率/方向分组的跨运行重复性</h2><table><tr><th>Gyro轴</th><th>速率 °/s</th><th>方向</th><th>重复数</th><th>输出均值 °/s</th><th>输出跨运行STD °/s</th><th>残差均值 °/s</th><th>残差跨运行STD °/s</th><th>状态</th></tr>");
        foreach (var x in d.Groups)
            b.Append($"<tr><td>{H(x.GyroAxis)}</td><td>{F(x.RateDps)}</td><td>{H(x.Direction)}</td><td>{x.Repeats}</td><td>{F(x.OutputMeanDps)}</td><td>{F(x.OutputBetweenRunStdDps)}</td><td>{F(x.ResidualMeanDps)}</td><td>{F(x.ResidualBetweenRunStdDps)}</td><td>{H(x.Status)}</td></tr>");
        b.Append("</table></section>");
        b.Append("<section><h2>正反向配对差异</h2><table><tr><th>Gyro轴</th><th>速率 °/s</th><th>完整配对数</th><th>正向残差</th><th>反向残差</th><th>正反向差值</th><th>平均残差RMSE</th></tr>");
        foreach (var x in d.DirectionPairs)
            b.Append($"<tr><td>{H(x.GyroAxis)}</td><td>{F(x.RateDps)}</td><td>{x.CompletePairs}</td><td>{F(x.ForwardResidualDps)}</td><td>{F(x.ReverseResidualDps)}</td><td>{F(x.ForwardReverseDifferenceDps)}</td><td>{F(x.MeanResidualRmseDps)}</td></tr>");
        b.Append("</table></section>");
        b.Append("<section><h2>方法边界</h2><p>" + H(d.MethodLimitations) + "</p><p>本报告为研发诊断，不自动判定产品PASS/FAIL。</p></section></body></html>");
        return b.ToString();
    }
}
