using System.Globalization;
using System.Net;
using System.Text;
using System.Text.Json;
using Dts.Tests.S1.CT12A;

namespace Dts.Tests.S1.CT17;

public static class Ct17Report
{
    private static readonly CultureInfo Ci=CultureInfo.InvariantCulture;
    private static string F(double? v)=>v is null||!double.IsFinite(v.Value)?"":v.Value.ToString("G17",Ci);
    private static string H(string? s)=>WebUtility.HtmlEncode(s??"");
    private static string Q(string? s)=>"\""+(s??"").Replace("\"","\"\"")+"\"";

    public static async Task WriteSweepCsvAsync(string path,Ct17SweepResult sweep,CancellationToken ct)
    {
        var b=new StringBuilder("host_timestamp_ticks,time_from_command_ms,host_relative_seconds,encoder_position_deg,encoder_reference_rate_dps,gyro_measured_rate_dps,residual_dps,temperature_c,encoder_sample_age_ms,has_reference,quality\r\n");
        foreach(var x in sweep.Samples)
            b.AppendLine(string.Join(",",x.HostTimestampTicks.ToString(Ci),F(x.TimeFromCommandMs),F(x.HostTimeSeconds),F(x.EncoderPositionDeg),
                F(x.EncoderReferenceRateDps),F(x.GyroMeasuredRateDps),F(x.ResidualDps),F(x.TemperatureC),
                F(x.EncoderSampleAgeMs),x.HasReference?"true":"false",Q(x.Quality)));
        await File.WriteAllTextAsync(path,b.ToString(),new UTF8Encoding(true),ct);
    }

    public static async Task<IReadOnlyList<string>> ExportAsync(string folder,Ct17ReportData report,
        IReadOnlyList<Ct12aBatch> batches,CancellationToken ct)
    {
        Directory.CreateDirectory(folder);
        string json=Path.Combine(folder,"CT-17_result.json");
        string timing=Path.Combine(folder,"CT-17_static_timing.csv");
        string summary=Path.Combine(folder,"CT-17_dynamic_summary.csv");
        string html=Path.Combine(folder,"CT-17_report.html");
        foreach(var s in report.Sweeps)
            if(s.Samples.Count>0)await WriteSweepCsvAsync(s.CsvPath,s,ct);
        await File.WriteAllTextAsync(json,JsonSerializer.Serialize(report,new JsonSerializerOptions{WriteIndented=true}),new UTF8Encoding(false),ct);
        var tb=new StringBuilder("batch_index,host_utc_seconds,mcu_tick_ms,odr_hz,frames,gx_mean_dps,gy_mean_dps,gz_mean_dps,temp_mean_c\r\n");
        for(int i=0;i<batches.Count;i++)
        {
            var x=batches[i];
            tb.AppendLine(string.Join(",",i.ToString(Ci),F(x.HostUtcSeconds),x.McuTickMs.ToString(Ci),
                x.OdrHz.ToString(Ci),x.Frames.ToString(Ci),F(x.GxDps),F(x.GyDps),F(x.GzDps),F(x.TemperatureC)));
        }
        await File.WriteAllTextAsync(timing,tb.ToString(),new UTF8Encoding(true),ct);
        var sb=new StringBuilder("index,axis,direction,repetition,command_speed_dps,command_call_ms,command_to_encoder_onset_ms,command_to_gyro_onset_ms,encoder_to_gyro_onset_ms,cross_correlation_lag_ms,cross_correlation_coefficient,median_reference_dps,median_gyro_dps,median_residual_dps,residual_rmse_dps,gyro_interval_ms,encoder_interval_ms,timing_resolution_ms,quality,csv_path\r\n");
        foreach(var x in report.Sweeps)
            sb.AppendLine(string.Join(",",x.Index.ToString(Ci),x.Axis,x.Direction,x.Repetition.ToString(Ci),F(x.CommandSpeedDps),
                F(x.CommandCallDurationMs),F(x.CommandToEncoderOnsetMs),F(x.CommandToGyroOnsetMs),F(x.EncoderToGyroOnsetMs),
                F(x.CrossCorrelationLagMs),F(x.CrossCorrelationCoefficient),F(x.MedianReferenceRateDps),F(x.MedianGyroRateDps),
                F(x.MedianResidualDps),F(x.ResidualRmseDps),F(x.GyroBatchIntervalMedianMs),F(x.EncoderIntervalMedianMs),
                F(x.TimingResolutionMs),Q(x.Quality),Q(Path.GetFileName(x.CsvPath))));
        await File.WriteAllTextAsync(summary,sb.ToString(),new UTF8Encoding(true),ct);
        await File.WriteAllTextAsync(html,BuildHtml(report),new UTF8Encoding(false),ct);
        return new[]{json,timing,summary,html}.Concat(report.Sweeps.Select(x=>x.CsvPath)).ToArray();
    }

    private static string BuildHtml(Ct17ReportData d)
    {
        var b=new StringBuilder("<!doctype html><html lang='zh-CN'><meta charset='utf-8'><title>CT-17时间对齐与延迟诊断</title><style>body{font:14px 'Microsoft YaHei',Arial;max-width:1250px;margin:28px auto;padding:0 20px;color:#23384d;background:#f4f7fb}section{background:white;border:1px solid #dce5ed;border-radius:9px;padding:18px;margin:14px 0}h1,h2{color:#195b94}table{border-collapse:collapse;width:100%;font-size:12px}td,th{border:1px solid #d7e0e8;padding:7px;text-align:right}td:last-child,th:last-child{text-align:left}.warn{color:#8a5a24}</style><body>");
        b.Append("<h1>CT-17｜数据时间对齐与延迟诊断</h1><section>");
        b.Append($"<p>设备：{H(d.DeviceNumber)}　UID：{H(d.UidHex)}　状态：{H(d.State)}</p><p>开始：{H(d.StartedUtc.ToString("O"))}<br>结束：{H(d.FinishedUtc.ToString("O"))}</p><p>{H(d.Conclusion)}</p><p>{H(d.FailureReason)}</p></section>");
        b.Append($"<section><h2>采集溯源</h2><p>ACC常温JSON：{H(d.AccJsonFile)} / SHA256：{H(d.AccJsonSha256)}<br>Gyro常温JSON：{H(d.GyroJsonFile)} / SHA256：{H(d.GyroJsonSha256)}</p><p>静态原始数据：{H(d.StaticRawCsv)}<br>静态校正数据：{H(d.StaticSelectedCsv)}<br>Manifest：{H(d.StaticManifest)}</p></section>");
        if(d.StaticTiming is { } t)
        {
            b.Append($"<section><h2>静态FIFO与主机时间基</h2><p>完整批次：{t.Batches}；帧数：{t.Frames}；ODR：{t.OdrHz}Hz；时长：{t.DurationSeconds:F2}s</p><p>主机批次频率：{t.HostBatchRateHz:F3}Hz（目标{t.ExpectedHostBatchHz:F2}Hz，偏差{t.HostBatchRateErrorPercent:F1}%）；主机批次周期中位数：{t.HostBatchPeriodMedianMs:F3}ms；P95抖动：{t.HostBatchJitterP95Ms:F3}ms</p><p>MCU tick批次周期：{t.McuTickPeriodMedianMs:F3}ms；按16/ODR预期：{t.ExpectedMcuBatchPeriodMs:F3}ms；偏差：{t.McuTickPeriodErrorPercent:F1}%；由主机批次频率估算帧吞吐：{t.EffectiveFrameRateFromHostHz:F1}frame/s</p><p>主机与MCU时钟频率差工程估计：{t.HostVsMcuClockDriftPpm:F1}ppm；线性映射残差P95：{t.HostVsMcuResidualP95Ms:F3}ms</p><p>疑似漏批：{t.CandidateMissingBatches}；无法分类长间隔：{t.UnclassifiedLongGaps}；候选漏帧比例：{(t.CandidateMissingFrameRatio?.ToString("P3",Ci)??"N/A")}</p><p class='warn'>注意：候选漏帧是按16帧/ODR和MCU tick整数倍推断，不是全局序号直接计数。</p><ul>");
            foreach(var w in t.Warnings)b.Append("<li>"+H(w)+"</li>");
            b.Append("</ul></section>");
        }
        b.Append("<section><h2>动态往复时延结果</h2><table><tr><th>轴/方向/重复</th><th>命令调用ms</th><th>命令→编码器起动ms</th><th>命令→Gyro响应ms</th><th>编码器→Gyro表观延迟ms</th><th>互相关lag ms</th><th>相关系数</th><th>时间分辨率ms</th><th>质量</th></tr>");
        foreach(var x in d.Sweeps)
            b.Append($"<tr><td>{H(x.Axis)} / {H(x.Direction)} / R{x.Repetition}</td><td>{F(x.CommandCallDurationMs)}</td><td>{F(x.CommandToEncoderOnsetMs)}</td><td>{F(x.CommandToGyroOnsetMs)}</td><td>{F(x.EncoderToGyroOnsetMs)}</td><td>{F(x.CrossCorrelationLagMs)}</td><td>{F(x.CrossCorrelationCoefficient)}</td><td>{F(x.TimingResolutionMs)}</td><td>{H(x.Quality)}</td></tr>");
        b.Append("</table></section>");
        b.Append($"<section><h2>方法限制</h2><p>{H(d.Limitation)}</p><p>本测试为研发诊断，不自动判定产品PASS/FAIL。所有动态曲线保存在同目录CSV。</p></section></body></html>");
        return b.ToString();
    }
}
