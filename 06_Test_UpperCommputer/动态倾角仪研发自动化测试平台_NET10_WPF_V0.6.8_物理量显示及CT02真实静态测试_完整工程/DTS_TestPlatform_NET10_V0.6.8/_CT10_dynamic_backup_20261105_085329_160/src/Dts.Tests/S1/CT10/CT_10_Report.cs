using System.Globalization;
using System.IO.Compression;
using System.Net;
using System.Security;
using System.Text;
using System.Text.Json;

namespace Dts.Tests.S1.CT10;

public static class Ct10Report
{
    private static readonly CultureInfo Ci = CultureInfo.InvariantCulture;
    private static readonly JsonSerializerOptions Opt = new() { WriteIndented = true };
    private static string F(double x, string fmt = "F5") => x.ToString(fmt, Ci);
    private static string H(string? s) => WebUtility.HtmlEncode(s ?? "");
    private static string Q(string? s) => "\"" + (s ?? "").Replace("\"", "\"\"") + "\"";
    private static Ct10ReportData Compact(Ct10ReportData d) => d with
    {
        Sweeps = d.Sweeps.Select(s => s with
        {
            Samples = Array.Empty<Ct10MatchedFrame>()
        }).ToArray()
    };

    public static async Task SaveCheckpointAsync(string directory, Ct10ReportData data, CancellationToken ct)
    {
        Directory.CreateDirectory(directory);
        string file = Path.Combine(directory, "CT-10_checkpoint.json"), temporary = file + ".tmp";
        await File.WriteAllTextAsync(temporary, JsonSerializer.Serialize(Compact(data), Opt),
            new UTF8Encoding(false), ct);
        File.Move(temporary, file, true);
    }

    public static async Task WriteSweepCsvAsync(string file, Ct10SweepResult sweep, CancellationToken ct)
    {
        await using var stream = new FileStream(file, FileMode.CreateNew, FileAccess.Write,
            FileShare.Read, 64 * 1024, FileOptions.Asynchronous);
        await using var writer = new StreamWriter(stream, new UTF8Encoding(true));
        await writer.WriteLineAsync("timestamp_ticks,time_s,accepted,reason,encoder_rate_dps,commanded_signed_dps,gyro_measured_axis_dps,residual_dps,gyro_x_corrected_dps,gyro_y_corrected_dps,gyro_z_corrected_dps,encoder_deg,temp_c");
        foreach (var v in sweep.Samples)
        {
            ct.ThrowIfCancellationRequested();
            await writer.WriteLineAsync(string.Join(",", new[] {
                v.TimestampTicks.ToString(Ci),F(v.TimeSeconds,"G17"),v.Accepted?"1":"0",Q(v.RejectionReason),
                F(v.ReferenceRateDps,"G17"),F(v.CommandedRateDps,"G17"),F(v.GyroAxisMeasuredDps,"G17"),
                F(v.ResidualDps,"G17"),F(v.GyroXCorrectedDps,"G17"),F(v.GyroYCorrectedDps,"G17"),
                F(v.GyroZCorrectedDps,"G17"),F(v.AxisEncoderDeg,"G17"),F(v.TemperatureC,"G17") }));
        }
        await writer.FlushAsync(ct);
    }

    public static async Task<IReadOnlyList<string>> ExportAsync(string directory, Ct10ReportData data,
        CancellationToken ct)
    {
        Directory.CreateDirectory(directory);
        string json = Path.Combine(directory, "CT-10_result.json");
        string csv = Path.Combine(directory, "CT-10_speed_pairs.csv");
        string sweeps = Path.Combine(directory, "CT-10_sweep_summary.csv");
        string html = Path.Combine(directory, "CT-10_report.html");
        string xlsx = Path.Combine(directory, "CT-10_report.xlsx");
        await SaveCheckpointAsync(directory, data, ct);
        await File.WriteAllTextAsync(json, JsonSerializer.Serialize(Compact(data), Opt),
            new UTF8Encoding(false), ct);
        var pairCsv = new List<string> { "axis,speed_dps,complete_pairs,forward_residual_dps,reverse_residual_dps,forward_minus_reverse_residual_dps,forward_ratio_percent,reverse_ratio_percent,mean_residual_rmse_dps" };
        foreach (var v in data.SpeedPairs)
            pairCsv.Add(string.Join(",", new[] { v.Axis.ToString(),F(v.SpeedDps,"G17"),v.PairCount.ToString(Ci),
                F(v.ForwardMeanResidualDps,"G17"), F(v.ReverseMeanResidualDps,"G17"),
                F(v.SignedDirectionDifferenceDps,"G17"), F(v.ForwardMeanRatioPercent,"G17"),
                F(v.ReverseMeanRatioPercent,"G17"), F(v.MeanResidualRmseDps,"G17") }));
        await File.WriteAllLinesAsync(csv, pairCsv, new UTF8Encoding(true), ct);
        var sweepCsv = new List<string> { "axis,direction,repeat,command_dps,reference_signed_dps,gyro_signed_dps,residual_mean_dps,residual_rmse_dps,residual_std_dps,ratio_percent,valid_frames,total_frames,encoder_frames,temp_c,frame_csv" };
        foreach (var s in data.Sweeps)
            sweepCsv.Add(string.Join(",", new[] { s.Axis.ToString(),s.Direction.ToString(),
                s.Repetition.ToString(Ci),F(s.CommandSpeedDps,"G17"), F(s.MeanReferenceSignedDps,"G17"),
                F(s.MeanGyroSignedDps,"G17"),F(s.MeanResidualDps,"G17"),F(s.ResidualRmseDps,"G17"),
                F(s.ResidualStdDps,"G17"),F(s.ScaleRatioPercent,"G17"),
                s.AcceptedFrames.ToString(Ci),s.TotalGyroFrames.ToString(Ci),s.EncoderFrames.ToString(Ci),
                F(s.MeanTemperatureC,"G17"),Q(s.CsvFile) }));
        await File.WriteAllLinesAsync(sweeps, sweepCsv, new UTF8Encoding(true), ct);
        await File.WriteAllTextAsync(html, BuildHtml(data), new UTF8Encoding(false), ct);
        WriteExcel(xlsx, data);
        return new[] { json, csv, sweeps, html, xlsx,
            Path.Combine(directory, "CT-10_checkpoint.json") };
    }

    private static string Chart(IReadOnlyList<Ct10SpeedPairResult> data)
    {
        if (data.Count == 0) return "<p>暂无完整正反配对。</p>";
        var values = data.Select(p => new { p.SpeedDps, Axis = p.Axis.ToString(),
            Positive = p.ForwardMeanResidualDps, Negative = p.ReverseMeanResidualDps }).ToArray();
        const int w = 910, h = 300;
        double peak = Math.Max(0.01, values.Max(v => Math.Max(Math.Abs(v.Positive), Math.Abs(v.Negative))) * 1.2);
        var sb = new StringBuilder($"<svg role='img' aria-label='正反向陀螺仪残差' viewBox='0 0 {w} {h}' xmlns='http://www.w3.org/2000/svg'>");
        double centerY = 137, scale = 107 / peak, space = 810d / values.Length;
        sb.Append($"<line x1='45' x2='880' y1='{F(centerY)}' y2='{F(centerY)}' stroke='#667c96'/>");
        for (int i = 0; i < values.Length; ++i)
        {
            var v = values[i]; double x = 65 + (i + .5) * space;
            foreach (var item in new[] { (y:v.Positive,dx:-10,color:"#2275bc",name:"正向"),
                (y:v.Negative,dx:10,color:"#db8e3f",name:"反向") })
            {
                double hh = Math.Abs(item.y * scale), top = item.y >= 0 ? centerY - hh : centerY;
                sb.Append($"<rect x='{F(x+item.dx-8)}' y='{F(top)}' width='15' height='{F(hh)}' fill='{item.color}'><title>{H(v.Axis)} {F(v.SpeedDps)}°/s {item.name} {F(item.y)}°/s</title></rect>");
            }
            sb.Append($"<text x='{F(x)}' y='277' font-size='11' text-anchor='middle'>{H(v.Axis)} {F(v.SpeedDps,"F1")}</text>");
        }
        sb.Append($"<text x='10' y='20' font-size='12'>±{F(peak,"F3")} °/s</text>");
        return sb.Append("</svg><p class='hint'>蓝色：正向；橙色：反向；横轴为轴/目标速度档位，纵轴为有符号平均残差（°/s）。</p>").ToString();
    }

    private static string BuildHtml(Ct10ReportData d)
    {
        var sb = new StringBuilder("<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'/><title>CT-10 GYRO多速率正反向残差报告</title>");
        sb.Append("<style>body{font:14px 'Microsoft YaHei',sans-serif;background:#f3f7fc;color:#17344c;max-width:1180px;padding:20px;margin:auto}.card{padding:20px;background:white;border:1px solid #dce7f1;border-radius:11px;margin:16px 0}h1,h2{color:#235f93}table{border-collapse:collapse;width:100%}td,th{border:1px solid #dbe5ee;padding:9px;text-align:right}td:first-child,th:first-child{text-align:left}th{background:#eaf2fb}svg{max-width:100%;height:auto}.hint{color:#5d748a}.warn{color:#a95628}@media print{body{background:white}}</style></head><body>");
        sb.Append("<h1>CT-10 · GYRO 多速率正反向残差</h1><div class='card'>");
        sb.Append($"<p><b>UID：</b>{H(d.UidHex)}　<b>状态：</b>{H(d.State)}</p><p>开始UTC：{H(d.StartedUtc)}<br/>结束UTC：{H(d.FinishedUtc)}</p><p>{H(d.FailureReason)}</p><p>{H(d.Conclusion)}</p></div>");
        sb.Append("<div class='card'><h2>测试设置与溯源</h2>");
        sb.Append($"<p>轴：{(d.Settings.TestInner?"内":"")}{(d.Settings.TestOuter?" 外":"")}；档位 {H(d.Settings.SpeedsCsv)}°/s；配对重复 {d.Settings.Repetitions} 次；扫描 [{F(d.Settings.TravelMinDeg)}, {F(d.Settings.TravelMaxDeg)}]°；现场批准范围 [{F(d.Settings.ApprovedMinDeg)}, {F(d.Settings.ApprovedMaxDeg)}]°。</p>");
        sb.Append($"<p>有效匀速判据：参考速度偏差≤{F(d.Settings.SpeedToleranceFraction*100,"F1")}%，参考编码器微分窗口 {F(d.Settings.EncoderDerivativeWindowSeconds,"F2")} s；每段至少 {d.Settings.MinAcceptedFrames} 帧。</p>");
        sb.Append($"<p>Gyro历史输入量程：±{d.GyroInputFullScaleDps}°/s；Gyro JSON：{H(d.GyroJsonPath)} SHA256 {H(d.GyroJsonSha256)}；ACC JSON：{H(d.AccJsonPath)} SHA256 {H(d.AccJsonSha256)}</p>");
        sb.Append($"<p>真实动态数据源：{H(d.DynamicAdapterDescription)}</p></div>");
        sb.Append("<div class='card'><h2>正反向平均残差趋势</h2>").Append(Chart(d.SpeedPairs)).Append("</div>");
        sb.Append("<div class='card'><h2>按速度档位配对</h2><table><tr><th>轴</th><th>目标速率 °/s</th><th>有效对数</th><th>正向残差 °/s</th><th>反向残差 °/s</th><th>正−反 °/s</th><th>正向比例偏差 %</th><th>反向比例偏差 %</th></tr>");
        foreach (var p in d.SpeedPairs)
            sb.Append($"<tr><td>{p.Axis}</td><td>{F(p.SpeedDps)}</td><td>{p.PairCount}</td><td>{F(p.ForwardMeanResidualDps)}</td><td>{F(p.ReverseMeanResidualDps)}</td><td>{F(p.SignedDirectionDifferenceDps)}</td><td>{F(p.ForwardMeanRatioPercent)}</td><td>{F(p.ReverseMeanRatioPercent)}</td></tr>");
        sb.Append("</table></div><div class='card'><h2>逐段真实运动证据</h2><table><tr><th>轴</th><th>方向</th><th>重复</th><th>参考实测速率 °/s</th><th>Gyro实测速率 °/s</th><th>RMSE °/s</th><th>有效帧/全部帧</th><th>逐帧文件</th></tr>");
        foreach (var s in d.Sweeps)
            sb.Append($"<tr><td>{s.Axis}</td><td>{s.Direction}</td><td>{s.Repetition}</td><td>{F(s.MeanReferenceSignedDps)}</td><td>{F(s.MeanGyroSignedDps)}</td><td>{F(s.ResidualRmseDps)}</td><td>{s.AcceptedFrames}/{s.TotalGyroFrames}</td><td>{H(s.CsvFile)}</td></tr>");
        sb.Append("</table></div><div class='card'><h2>测量限制、安全与结论</h2><p class='warn'>").Append(H(d.SafetyAndUncertaintyNotes))
          .Append("</p><p class='hint'>所有速度均以同一单调时间基准的真实编码器位置微分为参考。运动指令速度不充当真值。动态数据未接通或同步失败时禁止生成伪实测结果；本报告不替代计量溯源，也不自动判定PASS。</p></div></body></html>");
        return sb.ToString();
    }

    private static string Xml(string? value) => SecurityElement.Escape(value ?? "") ?? "";
    private static string Col(int c)
    {
        string s = "";
        while (c > 0) { c--; s = (char)('A' + (c % 26)) + s; c /= 26; }
        return s;
    }
    private static string Cell(int row, int col, object? value)
    {
        string pos = Col(col) + row;
        if (value is double or float or int or long)
            return $"<c r='{pos}'><v>{Convert.ToString(value, Ci)}</v></c>";
        return $"<c r='{pos}' t='inlineStr'><is><t>{Xml(value?.ToString())}</t></is></c>";
    }
    private static string Sheet(IReadOnlyList<object?[]> rows)
    {
        var b = new StringBuilder("<?xml version='1.0' encoding='utf-8'?><worksheet xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'><sheetData>");
        for (int r = 0; r < rows.Count; r++)
        {
            b.Append($"<row r='{r+1}'>");
            for (int c = 0; c < rows[r].Length; c++) b.Append(Cell(r+1, c+1, rows[r][c]));
            b.Append("</row>");
        }
        return b.Append("</sheetData></worksheet>").ToString();
    }
    private static void Add(ZipArchive z, string name, string content)
    {
        var e = z.CreateEntry(name, CompressionLevel.Optimal);
        using var w = new StreamWriter(e.Open(), new UTF8Encoding(false)); w.Write(content);
    }
    private static void WriteExcel(string file, Ct10ReportData d)
    {
        var overview = new List<object?[]> {
            new object?[]{"字段","数值"},new object?[]{"测试编号",d.TestId},
            new object?[]{"UID",d.UidHex},new object?[]{"状态",d.State},
            new object?[]{"错误",d.FailureReason},new object?[]{"速度档位",d.Settings.SpeedsCsv},
            new object?[]{"Gyro量程",d.GyroInputFullScaleDps},new object?[]{"Gyro SHA256",d.GyroJsonSha256},
            new object?[]{"真实动态源",d.DynamicAdapterDescription},new object?[]{"结论",d.Conclusion}
        };
        var pairs = new List<object?[]> {new object?[]{"轴","目标速度°/s","配对数","正向残差°/s","反向残差°/s","正-反°/s","正向比例误差%","反向比例误差%"}};
        foreach (var p in d.SpeedPairs) pairs.Add(new object?[]{p.Axis.ToString(),p.SpeedDps,p.PairCount,
            p.ForwardMeanResidualDps,p.ReverseMeanResidualDps,p.SignedDirectionDifferenceDps,
            p.ForwardMeanRatioPercent,p.ReverseMeanRatioPercent});
        var sweeps = new List<object?[]> {new object?[]{"轴","方向","重复次数","目标速率°/s","参考实测速率°/s","Gyro实测速率°/s","残差均值°/s","残差RMSE°/s","有效帧","总帧","证据CSV"}};
        foreach (var s in d.Sweeps) sweeps.Add(new object?[]{s.Axis.ToString(),s.Direction.ToString(),s.Repetition,
            s.CommandSpeedDps,s.MeanReferenceSignedDps,s.MeanGyroSignedDps,s.MeanResidualDps,
            s.ResidualRmseDps,s.AcceptedFrames,s.TotalGyroFrames,s.CsvFile});
        using var z = ZipFile.Open(file, ZipArchiveMode.Create);
        Add(z,"[Content_Types].xml","<?xml version='1.0' encoding='utf-8'?><Types xmlns='http://schemas.openxmlformats.org/package/2006/content-types'>"+
            "<Default Extension='rels' ContentType='application/vnd.openxmlformats-package.relationships+xml'/>"+
            "<Default Extension='xml' ContentType='application/xml'/>"+
            "<Override PartName='/xl/workbook.xml' ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml'/>"+
            "<Override PartName='/xl/worksheets/sheet1.xml' ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml'/>"+
            "<Override PartName='/xl/worksheets/sheet2.xml' ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml'/>"+
            "<Override PartName='/xl/worksheets/sheet3.xml' ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml'/></Types>");
        Add(z,"_rels/.rels","<?xml version='1.0' encoding='utf-8'?><Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'>"+
            "<Relationship Id='rId1' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument' Target='xl/workbook.xml'/></Relationships>");
        Add(z,"xl/workbook.xml","<?xml version='1.0' encoding='utf-8'?><workbook xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main' xmlns:r='http://schemas.openxmlformats.org/officeDocument/2006/relationships'>"+
            "<sheets><sheet name='Summary' sheetId='1' r:id='rId1'/><sheet name='SpeedPairs' sheetId='2' r:id='rId2'/><sheet name='Sweeps' sheetId='3' r:id='rId3'/></sheets></workbook>");
        Add(z,"xl/_rels/workbook.xml.rels","<?xml version='1.0' encoding='utf-8'?><Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'>"+
            "<Relationship Id='rId1' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet' Target='worksheets/sheet1.xml'/>"+
            "<Relationship Id='rId2' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet' Target='worksheets/sheet2.xml'/>"+
            "<Relationship Id='rId3' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet' Target='worksheets/sheet3.xml'/></Relationships>");
        Add(z,"xl/worksheets/sheet1.xml",Sheet(overview));
        Add(z,"xl/worksheets/sheet2.xml",Sheet(pairs));
        Add(z,"xl/worksheets/sheet3.xml",Sheet(sweeps));
    }
}
