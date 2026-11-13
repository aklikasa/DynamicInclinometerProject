
using System.Globalization;
using System.Net;
using System.Text;
using System.Text.Json;
namespace Dts.Tests.S1.CT20;
public static class Ct20Report
{
    private static readonly CultureInfo Ci=CultureInfo.InvariantCulture;
    private static string F(double v)=>v.ToString("G17",Ci);
    private static string H(string? s)=>WebUtility.HtmlEncode(s??"");
    public static async Task<IReadOnlyList<string>> ExportAsync(string folder,Ct20ReportData d,CancellationToken ct)
    {
        Directory.CreateDirectory(folder);
        string json=Path.Combine(folder,"CT-20_result.json"),csv=Path.Combine(folder,"CT-20_windows.csv"),html=Path.Combine(folder,"CT-20_report.html");
        await File.WriteAllTextAsync(json,JsonSerializer.Serialize(d,new JsonSerializerOptions{WriteIndented=true}),new UTF8Encoding(false),ct);
        var b=new StringBuilder("minutes_since_power_on_start,minutes_since_power_on_end,batches,gx_mean_dps,gy_mean_dps,gz_mean_dps,gx_std_dps,gy_std_dps,gz_std_dps,temp_mean_c,temp_min_c,temp_max_c,gx_drift_dps_min,gy_drift_dps_min,gz_drift_dps_min,stable,status\r\n");
        foreach(var r in d.Analysis?.Windows??Array.Empty<Ct20WindowRow>())
            b.AppendLine(string.Join(",",new[]{F(r.StartMinute),F(r.EndMinute),r.Batches.ToString(Ci),F(r.GxMean),F(r.GyMean),F(r.GzMean),F(r.GxStd),F(r.GyStd),F(r.GzStd),F(r.TemperatureMean),F(r.TemperatureMin),F(r.TemperatureMax),F(r.GxDriftDpsPerMin),F(r.GyDriftDpsPerMin),F(r.GzDriftDpsPerMin),r.Stable?"true":"false","\""+r.Status.Replace("\"","\"\"")+"\""}));
        await File.WriteAllTextAsync(csv,b.ToString(),new UTF8Encoding(true),ct);
        await File.WriteAllTextAsync(html,Html(d),new UTF8Encoding(false),ct);
        return new[]{json,csv,html};
    }
    private static string Html(Ct20ReportData d)
    {
        var b=new StringBuilder("<!doctype html><html lang='zh-CN'><meta charset='utf-8'><title>CT-20报告</title><style>body{font:14px 'Microsoft YaHei',Arial;max-width:1100px;margin:28px auto;padding:0 20px;color:#23384d;background:#f4f7fb}section{background:white;border:1px solid #dce5ed;border-radius:9px;padding:18px;margin:14px 0}h1,h2{color:#195b94}table{border-collapse:collapse;width:100%;font-size:12px}td,th{border:1px solid #d7e0e8;padding:7px;text-align:right}td:last-child,th:last-child{text-align:left}</style><body>");
        b.Append("<h1>CT-20｜Gyro冷启动预热零偏稳定性</h1><section>");
        b.Append($"<p>设备：{H(d.DeviceNumber)}　UID：{H(d.UidHex)}　状态：{H(d.State)}</p><p>人工记录上电时间：{H(d.Settings.PowerOnUtc.ToLocalTime().ToString("yyyy-MM-dd HH:mm:ss",Ci))}<br>采集启动时间：{H(d.StartedUtc.ToString("O"))}<br>结束：{H(d.FinishedUtc.ToString("O"))}</p><p>{H(d.Conclusion)}</p><p>{H(d.FailureReason)}</p></section>");
        b.Append($"<section><h2>测试设置与溯源</h2><p>时长：{d.Settings.DurationMinutes:F1} min；统计窗口：{d.Settings.WindowSeconds:F0}s；连续稳定时长：{d.Settings.StableWindowSeconds:F0}s；零偏阈值：±{d.Settings.BiasToleranceDps:G4}°/s；漂移率阈值：±{d.Settings.DriftToleranceDpsPerMin:G4}°/min；最低批次：{d.Settings.MinimumBatches}</p><p>ACC：{H(d.AccJsonFile)} SHA256 {H(d.AccJsonSha256)}<br>Gyro：{H(d.GyroJsonFile)} SHA256 {H(d.GyroJsonSha256)}</p></section>");
        if(d.Analysis is { } a)
        {
            b.Append($"<section><h2>总体结果</h2><p>有效批次：{a.TotalBatches}；帧数：{a.TotalFrames}；实际采集时长：{a.DurationMinutes:F2} min；上电至首个有效FIFO批次：{a.CaptureStartDelaySeconds:F1} s</p><p>温度范围：{a.TemperatureMinC:F2}～{a.TemperatureMaxC:F2}℃（Δ{a.TemperatureRangeC:F2}℃）</p><p>Gyro总体均值 X/Y/Z：{string.Join(" / ",a.OverallMeanDps.Select(v=>v.ToString("F6",Ci)))} °/s</p><p>总体STD X/Y/Z：{string.Join(" / ",a.OverallStdDps.Select(v=>v.ToString("F6",Ci)))} °/s</p><p>总体峰峰值 X/Y/Z：{string.Join(" / ",a.OverallPeakToPeakDps.Select(v=>v.ToString("F6",Ci)))} °/s</p><p>稳定开始时间（从人工上电起算）：{(a.StableStartMinute is null?"未达到":a.StableStartMinute.Value.ToString("F2",Ci)+" min")}；{H(a.Qualification)}</p><p>判据：{H(a.StabilityRule)}</p></section>");
            b.Append("<section><h2>预热分窗分析（时间零点为人工记录上电时间）</h2><table><tr><th>时间 min</th><th>批次</th><th>均值 X/Y/Z °/s</th><th>STD X/Y/Z °/s</th><th>漂移率 X/Y/Z °/min</th><th>温度℃</th><th>稳定</th></tr>");
            foreach(var r in a.Windows)b.Append($"<tr><td>{r.StartMinute:F2}–{r.EndMinute:F2}</td><td>{r.Batches}</td><td>{r.GxMean:F6}/{r.GyMean:F6}/{r.GzMean:F6}</td><td>{r.GxStd:F6}/{r.GyStd:F6}/{r.GzStd:F6}</td><td>{r.GxDriftDpsPerMin:F5}/{r.GyDriftDpsPerMin:F5}/{r.GzDriftDpsPerMin:F5}</td><td>{r.TemperatureMean:F2}</td><td>{(r.Stable?"是":"否")}</td></tr>");
            b.Append("</table></section><section><h2>质量警告</h2><ul>");
            foreach(var w in a.Warnings)b.Append("<li>"+H(w)+"</li>");
            b.Append("</ul></section>");
        }
        b.Append($"<section><h2>方法限制</h2><p>{H(d.Limitation)}</p><p>本报告为研发诊断，不自动判定产品PASS/FAIL。</p><p>原始采集：{H(d.AcquisitionFolder)}</p></section></body></html>");
        return b.ToString();
    }
}
