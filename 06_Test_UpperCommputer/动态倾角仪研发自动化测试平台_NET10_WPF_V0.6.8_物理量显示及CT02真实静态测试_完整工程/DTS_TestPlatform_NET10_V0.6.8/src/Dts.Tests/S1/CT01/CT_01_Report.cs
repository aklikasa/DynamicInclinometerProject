using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Threading;
using System.Threading.Tasks;
using System.Net;
using System.Text;
using System.Text.Json;

namespace Dts.Tests.S1.CT01;

public static class Ct01Report
{
    private static string F(double value) => value.ToString("G17", CultureInfo.InvariantCulture);
    private static string E(string value) => WebUtility.HtmlEncode(value);

    public static async Task<IReadOnlyList<string>> WriteAsync(
        string folder, Ct01VerificationResult result, CancellationToken ct)
    {
        string json = Path.Combine(folder, "CT-01_result.json");
        string csv = Path.Combine(folder, "CT-01_metrics.csv");
        string html = Path.Combine(folder, "CT-01_report.html");

        await File.WriteAllTextAsync(json,
            JsonSerializer.Serialize(result, new JsonSerializerOptions { WriteIndented = true }),
            new UTF8Encoding(true), ct);

        var sb = new StringBuilder();
        sb.AppendLine("axis,unit,samples,before_mean,before_std,after_mean,after_std,mean_shift,transform_rms,max_abs_shift,max_recompute_abs_error");
        foreach (var m in result.Metrics)
            sb.AppendLine(string.Join(",", m.Axis, m.Unit, m.Samples, F(m.BeforeMean), F(m.BeforeStd),
                F(m.AfterMean), F(m.AfterStd), F(m.MeanShift), F(m.TransformRms),
                F(m.MaxAbsShift), F(m.MaxRecomputeAbsError)));
        await File.WriteAllTextAsync(csv, sb.ToString(), new UTF8Encoding(true), ct);

        var h = new StringBuilder();
        h.Append("""
<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>CT-01 参数生效核验报告</title>
<style>
body{font-family:"Microsoft YaHei",Arial,sans-serif;margin:28px;color:#1f2937;line-height:1.55}
h1{font-size:24px}h2{font-size:18px;margin-top:26px}
.meta{background:#f3f6fa;padding:14px;border-radius:8px}
table{border-collapse:collapse;width:100%;font-size:13px;margin-top:12px}
th,td{border:1px solid #d5dce5;padding:8px;text-align:right}
th:first-child,td:first-child{text-align:left}
th{background:#eef2f7}
.warning{border-left:4px solid #d18b36;padding:10px 14px;background:#fff8ed;margin-top:18px}
.small{color:#64748b;font-size:12px}
</style></head><body>
<h1>CT-01 参数生效与补偿前后对比</h1>
<p><b>结果类型：参数应用链诊断（非产品精度验收）</b></p>
""");
        h.Append("<div class=\"meta\">");
        h.Append($"<b>设备 DTS：</b>{E(result.DeviceNumber)}<br>");
        h.Append($"<b>完整 MCU UID：</b>{E(result.UidHex)}<br>");
        h.Append($"<b>补偿模式：</b>{E(result.Mode)}<br>");
        h.Append($"<b>身份依据：</b>{E(result.IdentityProof)}<br>");
        h.Append($"<b>采样：</b>{result.Samples} 帧 / {result.Batches} FIFO批次 / {result.DistinctMcuTicks} 个不同MCU时戳<br>");
        h.Append($"<b>SENSOR_OK：</b>{result.SensorOkSamples} 帧；来源状态未核实 {result.SensorUnverifiedSamples} 帧<br>");
        h.Append($"<b>输入量程独立复核最大差值：</b>{F(result.MaxPhysicalConversionAbsError)}<br>");
        h.Append($"<b>补偿矩阵独立重算最大差值：</b>{F(result.MaxRecomputeAbsError)}<br>");
        h.Append("</div>");
        h.Append("<h2>六轴补偿前后统计</h2><table><thead><tr><th>轴</th><th>单位</th><th>样本数</th><th>补偿前均值</th><th>补偿前标准差</th><th>补偿后均值</th><th>补偿后标准差</th><th>均值变化</th><th>变换RMS</th><th>最大绝对变化</th><th>独立重算最大差值</th></tr></thead><tbody>");
        foreach (var m in result.Metrics)
        {
            h.Append("<tr>");
            h.Append($"<td>{E(m.Axis)}</td><td>{E(m.Unit)}</td><td>{m.Samples}</td>");
            h.Append($"<td>{F(m.BeforeMean)}</td><td>{F(m.BeforeStd)}</td><td>{F(m.AfterMean)}</td><td>{F(m.AfterStd)}</td>");
            h.Append($"<td>{F(m.MeanShift)}</td><td>{F(m.TransformRms)}</td><td>{F(m.MaxAbsShift)}</td><td>{F(m.MaxRecomputeAbsError)}</td>");
            h.Append("</tr>");
        }
        h.Append("</tbody></table>");
        h.Append($"<div class=\"warning\"><b>结论边界：</b>{E(result.Limitation)}</div>");
        h.Append($"<p class=\"small\">Assessment: {E(result.Assessment)}<br>采集目录：{E(result.CaptureFolder)}</p>");
        h.Append("</body></html>");
        await File.WriteAllTextAsync(html, h.ToString(), new UTF8Encoding(true), ct);
        return [json, csv, html];
    }
}
