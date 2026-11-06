using System.Globalization;
using System.Net;
using System.Text;
using System.Text.Json;

namespace Dts.Tests.S1.CT02;

public static class Ct02Report
{
    public static async Task<string[]> ExportAsync(string folder, Ct02ReportData report, CancellationToken ct)
    {
        string json = Path.Combine(folder, "CT-02_result.json");
        string csv = Path.Combine(folder, "CT-02_metrics.csv");
        string html = Path.Combine(folder, "CT-02_report.html");
        await File.WriteAllTextAsync(json, JsonSerializer.Serialize(report,
            new JsonSerializerOptions { WriteIndented = true }), new UTF8Encoding(false), ct);
        var ci = CultureInfo.InvariantCulture;
        var names = new[] { "ACC_X_g", "ACC_Y_g", "ACC_Z_g", "GYRO_X_dps", "GYRO_Y_dps", "GYRO_Z_dps" };
        var csvContent = new StringBuilder("metric,mean,std,unit\n");
        for (int i = 0; i < 6; i++)
        {
            var unit = i < 3 ? "g" : "deg/s";
            csvContent.Append(names[i]).Append(',').Append(report.Metrics.Means[i].ToString("G17", ci))
                .Append(',').Append(report.Metrics.StandardDeviations[i].ToString("G17", ci))
                .Append(',').Append(unit).Append('\n');
        }
        void Metric(string name, double value, string unit) => csvContent.Append(name)
            .Append(',').Append(value.ToString("G17", ci)).Append(",,").Append(unit).Append('\n');
        Metric("roll_zero_error", report.Metrics.RollZeroDeg, "deg");
        Metric("pitch_zero_error", report.Metrics.PitchZeroDeg, "deg");
        Metric("gravity_direction_error", report.Metrics.TotalGravityDirectionErrorDeg, "deg");
        Metric("gravity_norm_residual", report.Metrics.AccNormResidualG, "g");
        Metric("gyro_zero_vector_norm", report.Metrics.GyroZeroVectorNormDps, "deg/s");
        await File.WriteAllTextAsync(csv, csvContent.ToString(), new UTF8Encoding(true), ct);
        string E(string text) => WebUtility.HtmlEncode(text);
        string F(double x) => x.ToString("F6", ci);
        var tableRows = new StringBuilder();
        for (int i = 0; i < 6; i++)
            tableRows.Append("<tr><td>").Append(names[i]).Append("</td><td>")
                .Append(F(report.Metrics.Means[i])).Append("</td><td>")
                .Append(F(report.Metrics.StandardDeviations[i])).Append("</td></tr>");
        string page = $$"""
        <!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>CT-02 常温零位与静态零速残差</title>
        <style>body{font:15px/1.65 'Microsoft YaHei',sans-serif;max-width:960px;margin:42px auto;color:#18324c}
        h1{color:#123d68}h2{margin-top:32px}table{border-collapse:collapse;width:100%}td,th{padding:9px 13px;border-bottom:1px solid #dce6f0;text-align:left}
        .notice{background:#fff6e9;padding:15px;border-left:4px solid #d48b2f}small{color:#647b8f}</style></head><body>
        <h1>CT-02 常温零位与静态零速残差</h1><p class="notice">{{E(report.Conclusion)}}。采样过程未发送转台运动命令。</p>
        <p>设备：{{E(report.DtsId)}}　完整UID：{{E(report.UidHex)}}<br>日期：{{E(report.StartedUtc)}} — {{E(report.EndedUtc)}}</p>
        <p>参考重力：{{E(report.ReferenceDescription)}}；样本数：{{report.Metrics.Samples}}；独立MCU批次：{{report.Metrics.DistinctMcuTicks}}；温度均值：{{F(report.Metrics.MeanTemperatureC)}}℃</p>
        <h2>测量残差</h2><table><tr><th>指标</th><th>数值</th></tr>
        <tr><td>Roll 零位分量</td><td>{{F(report.Metrics.RollZeroDeg)}}°</td></tr>
        <tr><td>Pitch 零位分量</td><td>{{F(report.Metrics.PitchZeroDeg)}}°</td></tr>
        <tr><td>三维重力方向误差</td><td>{{F(report.Metrics.TotalGravityDirectionErrorDeg)}}°</td></tr>
        <tr><td>加速度模长</td><td>{{F(report.Metrics.AccNormG)}} g</td></tr>
        <tr><td>加速度模长残差</td><td>{{F(report.Metrics.AccNormResidualG)}} g</td></tr>
        <tr><td>陀螺仪零速矢量模长</td><td>{{F(report.Metrics.GyroZeroVectorNormDps)}} °/s</td></tr></table>
        <h2>六轴均值与样本标准差</h2><table><tr><th>轴</th><th>均值</th><th>标准差</th></tr>{{tableRows}}</table>
        <h2>计算依据与追溯</h2><p>当前模型：常温标定；先按 JSON 拟合输入量程做物理量换算，再应用零偏与 3×3 矩阵；<strong>不重复乘系数</strong>。</p>
        <p>换算策略：{{E(report.InputScalePolicy)}}<br>ACC：{{E(report.CalibrationAccFile)}}<br>SHA256：{{E(report.CalibrationAccSha256)}}
        <br>Gyro：{{E(report.CalibrationGyroFile)}}<br>SHA256：{{E(report.CalibrationGyroSha256)}}</p>
        <p><small>{{E(report.SamplingDescription)}}。时戳是MCU批次级，不表示逐帧硬件同步；需要正式零位精度结论时还应补充工装调平参考及不确定度。</small></p>
        </body></html>
        """;
        await File.WriteAllTextAsync(html, page, new UTF8Encoding(false), ct);
        return [json, csv, html];
    }
}
