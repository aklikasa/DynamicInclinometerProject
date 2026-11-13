using System.Globalization;
using System.Net;
using System.Text;
using System.Text.Json;

namespace Dts.Tests.S1.CT09;

public static class Ct09Report
{
    private static readonly JsonSerializerOptions JsonOptions = new() { WriteIndented = true };
    private static string F(double v, string format = "G8") =>
        double.IsFinite(v) ? v.ToString(format, CultureInfo.InvariantCulture) : "";
    private static string F(double? v, string format = "G8") =>
        v.HasValue && double.IsFinite(v.Value) ? v.Value.ToString(format, CultureInfo.InvariantCulture) : "";
    private static string Q(string? s) => "\"" + (s ?? "").Replace("\"", "\"\"") + "\"";
    private static string H(string? s) => WebUtility.HtmlEncode(s ?? "");

    public static async Task SaveCheckpointAsync(string folder, Ct09ReportData data, CancellationToken ct)
    {
        Directory.CreateDirectory(folder);
        string path = Path.Combine(folder, "CT-09_checkpoint.json");
        await File.WriteAllTextAsync(path, JsonSerializer.Serialize(data, JsonOptions), new UTF8Encoding(true), ct);
    }

    public static async Task<IReadOnlyList<string>> ExportAsync(string folder, Ct09ReportData data, CancellationToken ct)
    {
        Directory.CreateDirectory(folder);
        string json = Path.Combine(folder, "CT-09_result.json");
        await File.WriteAllTextAsync(json, JsonSerializer.Serialize(data, JsonOptions), new UTF8Encoding(true), ct);

        string csv = Path.Combine(folder, "CT-09_runs.csv");
        var rows = new StringBuilder("index,pose_index,repeat,inner_target_deg,outer_target_deg,inner_actual_deg,outer_actual_deg,gyro_x_mean_dps,gyro_y_mean_dps,gyro_z_mean_dps,gyro_x_within_std_dps,gyro_y_within_std_dps,gyro_z_within_std_dps,zero_rate_norm_dps,temp_mean_c,total_samples,accepted_samples,rejected_fraction,physical_csv,corrected_csv\r\n");
        foreach (var v in data.Visits)
        {
            var cells = new[]
            {
                v.Index.ToString(CultureInfo.InvariantCulture), v.PoseIndex.ToString(CultureInfo.InvariantCulture),
                v.Repeat.ToString(CultureInfo.InvariantCulture), F(v.InnerTargetDeg), F(v.OuterTargetDeg),
                F(v.InnerActualDeg), F(v.OuterActualDeg),
                F(v.GyroCorrectedMeanDps[0]), F(v.GyroCorrectedMeanDps[1]), F(v.GyroCorrectedMeanDps[2]),
                F(v.GyroWithinStdDps[0]), F(v.GyroWithinStdDps[1]), F(v.GyroWithinStdDps[2]),
                F(v.ZeroRateNormDps), F(v.MeanTemperatureC), v.TotalSamples.ToString(CultureInfo.InvariantCulture),
                v.AcceptedSamples.ToString(CultureInfo.InvariantCulture), F(v.RejectedFraction),
                Q(v.PhysicalCsv), Q(v.CorrectedCsv)
            };
            rows.AppendLine(string.Join(",", cells));
        }
        await File.WriteAllTextAsync(csv, rows.ToString(), new UTF8Encoding(true), ct);

        string poseCsv = Path.Combine(folder, "CT-09_pose_summary.csv");
        var p = new StringBuilder("pose_index,inner_deg,outer_deg,runs,mean_gx_dps,mean_gy_dps,mean_gz_dps,between_run_std_x_dps,between_run_std_y_dps,between_run_std_z_dps,zero_rate_norm_dps,mean_temperature_c\r\n");
        foreach (var v in data.Metrics?.PoseSummaries ?? Array.Empty<Ct09PoseSummary>())
            p.AppendLine(string.Join(",", v.PoseIndex, F(v.InnerDeg), F(v.OuterDeg), v.Runs,
                F(v.MeanGyroDps[0]), F(v.MeanGyroDps[1]), F(v.MeanGyroDps[2]),
                F(v.BetweenRunStdDps[0]), F(v.BetweenRunStdDps[1]), F(v.BetweenRunStdDps[2]),
                F(v.ZeroRateNormDps), F(v.MeanTemperatureC)));
        await File.WriteAllTextAsync(poseCsv, p.ToString(), new UTF8Encoding(true), ct);

        string html = Path.Combine(folder, "CT-09_report.html");
        var sb = new StringBuilder("<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><title>CT-09报告</title>");
        sb.Append("<style>body{font:14px 'Microsoft YaHei',Arial,sans-serif;color:#20364a;background:#f4f7fb;max-width:1200px;margin:24px auto;padding:0 18px}h1,h2{color:#195b94}.card{background:#fff;border:1px solid #d9e4ee;border-radius:10px;padding:18px;margin:14px 0}table{border-collapse:collapse;width:100%;font-size:12px}th,td{border:1px solid #d5e0e9;padding:7px;text-align:right}th:first-child,td:first-child{text-align:left}th{background:#eaf2fa}.note{color:#65798b}</style></head><body>");
        sb.Append("<h1>CT-09 · Gyro零速残差与姿态相关性</h1>");
        sb.Append($"<div class='card'><p><b>设备：</b>{H(data.DeviceNumber)}　<b>UID：</b>{H(data.UidHex)}</p><p><b>状态：</b>{H(data.State)}</p><p><b>开始：</b>{H(data.StartedUtc.ToString("O"))}<br><b>结束：</b>{H(data.FinishedUtc.ToString("O"))}</p><p>{H(data.FailureReason)}</p><p>Gyro标定：{H(data.GyroJsonFile)}；SHA256：{H(data.GyroJsonSha256)}；输入量程：±{data.GyroFsHint}°/s</p><p>{H(data.InputScaleDescription)}</p></div>");
        if (data.Metrics is { } m)
        {
            sb.Append($"<div class='card'><h2>测试参数</h2><p>姿态数：{data.Settings.Poses.Count}；每姿态重复：{data.Settings.RepeatsPerPose}；定位速度：{F(data.Settings.MotionSpeedDps)}°/s；静置：{F(data.Settings.SettleSeconds)}s；采集：{F(data.Settings.SampleSeconds)}s；允许行程：[{F(data.Settings.AllowedMinDeg)},{F(data.Settings.AllowedMaxDeg)}]°。</p></div>");
            sb.Append($"<div class='card'><h2>总体指标</h2><p>完成姿态：{m.Poses}；完成采集单元：{m.Visits}；有效帧：{m.AcceptedFrames}</p>");
            sb.Append($"<p>总体Gyro零速均值 X/Y/Z：{F(m.GrandMeanGyroDps[0])} / {F(m.GrandMeanGyroDps[1])} / {F(m.GrandMeanGyroDps[2])} °/s</p>");
            sb.Append($"<p>姿态均值范围 X/Y/Z：{F(m.PoseMeanRangeDps[0])} / {F(m.PoseMeanRangeDps[1])} / {F(m.PoseMeanRangeDps[2])} °/s</p>");
            sb.Append($"<p>最大姿态均值矢量差异：{F(m.MaxPoseMeanVectorDifferenceDps)} °/s；最大姿态零速模：{F(m.MaxPoseZeroRateNormDps)} °/s</p>");
            sb.Append($"<p>芯片温度范围：{F(m.TemperatureMinC, "F2")}～{F(m.TemperatureMaxC, "F2")} ℃</p></div>");
            sb.Append("<div class='card'><h2>各姿态汇总</h2><table><tr><th>姿态</th><th>内轴°</th><th>外轴°</th><th>重复</th><th>Gyro X/Y/Z均值(°/s)</th><th>零速模(°/s)</th><th>温度℃</th></tr>");
            foreach (var v in m.PoseSummaries)
                sb.Append($"<tr><td>{v.PoseIndex}</td><td>{F(v.InnerDeg)}</td><td>{F(v.OuterDeg)}</td><td>{v.Runs}</td><td>{F(v.MeanGyroDps[0])} / {F(v.MeanGyroDps[1])} / {F(v.MeanGyroDps[2])}</td><td>{F(v.ZeroRateNormDps)}</td><td>{F(v.MeanTemperatureC, "F2")}</td></tr>");
            sb.Append("</table></div>");
        }
        sb.Append("<div class='card'><h2>逐次采集</h2><table><tr><th>序号</th><th>姿态</th><th>重复</th><th>Gyro X/Y/Z均值</th><th>轮内STD</th><th>有效帧</th><th>拒绝比例</th><th>温度℃</th></tr>");
        foreach (var v in data.Visits)
            sb.Append($"<tr><td>{v.Index}</td><td>{v.PoseIndex}</td><td>{v.Repeat}</td><td>{F(v.GyroCorrectedMeanDps[0])} / {F(v.GyroCorrectedMeanDps[1])} / {F(v.GyroCorrectedMeanDps[2])}</td><td>{F(v.GyroWithinStdDps[0])} / {F(v.GyroWithinStdDps[1])} / {F(v.GyroWithinStdDps[2])}</td><td>{v.AcceptedSamples}/{v.TotalSamples}</td><td>{F(v.RejectedFraction, "P2")}</td><td>{F(v.MeanTemperatureC, "F2")}</td></tr>");
        sb.Append("</table></div>");
        sb.Append($"<div class='card'><h2>测量解释与限制</h2><p>{H(data.MeasurementCaveat)}</p><p class='note'>本报告为研发诊断，不自动判定产品PASS/FAIL。姿态相关性是本次姿态集合中的校正后静态零速均值差异；需结合芯片温度、转台实际位置、环境和测量不确定度解释。各轮原始CSV与校正CSV独立保存。</p></div></body></html>");
        await File.WriteAllTextAsync(html, sb.ToString(), new UTF8Encoding(false), ct);
        return new[] { json, csv, poseCsv, html, Path.Combine(folder, "CT-09_checkpoint.json") };
    }
}
