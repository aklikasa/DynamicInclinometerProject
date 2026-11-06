using System.Globalization;
using System.IO;
using System.IO.Compression;
using System.Net;
using System.Security;
using System.Text;
using System.Text.Json;

namespace Dts.Tests.S1.CT22;

/// <summary>Independent audit-ready JSON / CSV / HTML-SVG / Excel exports (no NuGet additions).</summary>
public static class Ct22Report
{
    private static readonly CultureInfo Ci=CultureInfo.InvariantCulture;
    private static readonly JsonSerializerOptions Options=new(){WriteIndented=true};
    private static string F(double value,string format="F5")=>value.ToString(format,Ci);
    private static string F(double? value,string format="F5")=>value is null?"N/A":F(value.Value,format);
    private static string Q(string? v)=>"\""+(v??"").Replace("\"","\"\"")+"\"";
    private static string H(string? v)=>WebUtility.HtmlEncode(v??"");
    private static string X(string? v)=>SecurityElement.Escape(v??"")??"";

    public static async Task<IReadOnlyList<string>> ExportAsync(string folder,Ct22ReportData data,CancellationToken ct)
    {
        Directory.CreateDirectory(folder);
        string json=Path.Combine(folder,"CT-22_result.json");
        string curve=Path.Combine(folder,"CT-22_drift_curve.csv");
        string summary=Path.Combine(folder,"CT-22_axis_metrics.csv");
        string quality=Path.Combine(folder,"CT-22_time_quality.csv");
        string html=Path.Combine(folder,"CT-22_report.html");
        string xlsx=Path.Combine(folder,"CT-22_report.xlsx");
        await File.WriteAllTextAsync(json,JsonSerializer.Serialize(data,Options),new UTF8Encoding(false),ct);
        var curveRows=new List<string>{"elapsed_mcu_seconds,gyro_x_integrated_deg,gyro_y_integrated_deg,gyro_z_integrated_deg,gyro_x_mean_dps,gyro_y_mean_dps,gyro_z_mean_dps,temperature_c,acc_direction_change_deg,quality"};
        if(data.Analysis is { MetricsReleased:true } a)
            foreach(var p in a.Curve)
                curveRows.Add(string.Join(",",new[]{p.ElapsedSeconds,p.GxDeg,p.GyDeg,p.GzDeg,
                    p.GxRateDps,p.GyRateDps,p.GzRateDps,p.TemperatureC,p.AccAngleFromStartDeg}
                    .Select(v=>F(v,"G17")))+","+Q(a.TimeQuality.Classification));
        await File.WriteAllLinesAsync(curve,curveRows,new UTF8Encoding(true),ct);
        var metrics=new List<string>{"axis,mean_gyro_dps,final_integrated_deg,max_absolute_integrated_deg,linear_drift_slope_deg_per_min,drift_at_10min_deg,drift_at_30min_deg"};
        if(data.Analysis is { MetricsReleased:true } ma)
            foreach(var m in ma.Axes)
                metrics.Add(string.Join(",",Q(m.Axis),F(m.MeanRateDps,"G17"),F(m.FinalAngleDeg,"G17"),
                    F(m.MaxAbsoluteAngleDeg,"G17"),F(m.LeastSquaresSlopeDegPerMinute,"G17"),
                    m.DriftAt10MinutesDeg is null?"":F(m.DriftAt10MinutesDeg.Value,"G17"),
                    m.DriftAt30MinutesDeg is null?"":F(m.DriftAt30MinutesDeg.Value,"G17")));
        await File.WriteAllLinesAsync(summary,metrics,new UTF8Encoding(true),ct);
        var qr=new List<string>{"metric,value,comment"};
        if(data.Analysis is { } a2)
        {
            var q=a2.TimeQuality;
            qr.Add($"classification,{Q(q.Classification)},engineering_batch_time_only");
            qr.Add($"metrics_released,{a2.MetricsReleased},not_product_pass");
            qr.Add($"fifo_batches,{q.Batches},complete_16_frame_batches");
            qr.Add($"real_frames,{q.Frames},frames");
            qr.Add($"unchanged_poll_count,{q.UnchangedPolls},polls_not_frames");
            qr.Add($"gap_or_overlap_intervals,{q.GapOrOverlapIntervals},no_stitching");
            qr.Add($"reported_odr_hz,{q.OdrHz},hertz");
            qr.Add($"mcu_duration_seconds,{F(q.McuDurationSeconds,"G17")},integrated_time_basis");
            qr.Add($"host_duration_seconds,{F(q.HostDurationSeconds,"G17")},independent_cross_check");
            qr.Add($"host_jitter_p95_percent,{F(q.HostJitterP95Percent,"G17")},percent");
            qr.Add($"mcu_jitter_p95_percent,{F(q.McuJitterP95Percent,"G17")},percent");
            qr.Add($"odr_span_error_p95_percent,{F(q.FifoSpanErrorP95Percent,"G17")},percent");
            qr.Add($"host_mcu_span_mismatch_percent,{F(q.HostMcuDurationMismatchPercent,"G17")},percent");
            qr.Add($"temp_min_c,{F(q.TemperatureMinC,"G17")},celsius");
            qr.Add($"temp_max_c,{F(q.TemperatureMaxC,"G17")},celsius");
            qr.Add($"max_acc_direction_change_deg,{F(q.MaxAccDirectionChangeDeg,"G17")},degrees");
            foreach(string w in q.Warnings)qr.Add("warning,"+Q(w)+",quality_gate");
        }
        else qr.Add("analysis_failed,"+Q(data.FailureReason)+",see_result_json");
        await File.WriteAllLinesAsync(quality,qr,new UTF8Encoding(true),ct);
        await File.WriteAllTextAsync(html,Html(data),new UTF8Encoding(false),ct);
        Excel(xlsx,data);
        return [json,curve,summary,quality,xlsx,html];
    }
    private static string Chart(IReadOnlyList<Ct22DriftPoint> samples)
    {
        if(samples.Count<2)return "<p>没有通过时间质量审核的有效积分曲线</p>";
        var maxTime=samples[^1].ElapsedSeconds;
        var vals=samples.SelectMany(p=>new[]{p.GxDeg,p.GyDeg,p.GzDeg}).ToArray();
        double min=vals.Min(),max=vals.Max();
        double range=max-min;
        if(range<1e-12){min-=0.001;max+=0.001;range=max-min;}
        else{double margin=range*0.12;min-=margin;max+=margin;range=max-min;}
        static string N(double v)=>v.ToString("F2",Ci);
        double Xpos(double v)=>82+694*v/maxTime;
        double Ypos(double v)=>25+285*(max-v)/range;
        var sb=new StringBuilder("<svg viewBox='0 0 920 375' xmlns='http://www.w3.org/2000/svg' role='img' aria-label='三轴Gyro静止积分漂移趋势'>");
        for(int k=0;k<=4;k++)
        {
            double x=82+694*k/4.0,y=25+285*k/4.0;
            sb.Append($"<line x1='{N(x)}' x2='{N(x)}' y1='25' y2='310' stroke='#d8e5f1'/>");
            sb.Append($"<line x1='82' x2='776' y1='{N(y)}' y2='{N(y)}' stroke='#d8e5f1'/>");
            sb.Append($"<text x='{N(x)}' y='333' font-size='12' text-anchor='middle'>{F(maxTime*k/240.0,"F1")}</text>");
            sb.Append($"<text x='5' y='{N(y+4)}' font-size='12'>{F(max-range*k/4,"F3")}</text>");
        }
        string[] colors=["#116ec4","#dc7a22","#238b65"];
        for(int axis=0;axis<3;axis++)
        {
            var idx=axis;
            double Value(Ct22DriftPoint p)=>idx switch{0=>p.GxDeg,1=>p.GyDeg,_=>p.GzDeg};
            // SVG point-count capped for very long recordings while CSV keeps all plotted samples.
            int step=Math.Max(1,samples.Count/1800);
            var positions=string.Join(" ",samples.Where((p,i)=>i%step==0||i==samples.Count-1)
                .Select(p=>$"{N(Xpos(p.ElapsedSeconds))},{N(Ypos(Value(p)))}"));
            sb.Append($"<polyline points='{positions}' stroke='{colors[axis]}' stroke-width='2.3' fill='none'/>");
            sb.Append($"<text x='800' y='{36+25*axis}' font-size='14' fill='{colors[axis]}'>Gyro-{(char)('X'+axis)}</text>");
        }
        sb.Append("<text x='438' y='365' font-size='13' text-anchor='middle'>实际MCU批次累计时间 (分钟) · 输出角度 (°)</text></svg>");
        return sb.ToString();
    }
    private static string Html(Ct22ReportData d)
    {
        var b=new StringBuilder("<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><title>CT-22 Gyro静止积分漂移</title>");
        b.Append("<style>body{font:14px 'Microsoft YaHei',sans-serif;background:#f5f8fc;color:#1d3851;max-width:1130px;margin:25px auto;padding:0 18px}h1,h2{color:#175a97}.card{background:white;border:1px solid #dce7f2;border-radius:11px;padding:18px;margin:15px 0}table{width:100%;border-collapse:collapse}td,th{border:1px solid #d7e3ec;padding:8px;text-align:right}td:first-child,th:first-child{text-align:left}th{background:#e9f2f9}svg{width:100%;height:auto}.warning{color:#946131}</style></head><body>");
        b.Append("<h1>CT-22 · Gyro 静止积分漂移</h1>");
        b.Append($"<div class='card'><p><b>设备</b> {H(d.DeviceNumber)}　<b>UID</b> {H(d.UidHex)}</p>"+
            $"<p><b>测试状态</b> {H(d.State)}</p><p>开始：{H(d.StartedUtc)}　结束：{H(d.FinishedUtc)}</p>"+
            $"<p>{H(d.FailureReason)}</p><p>{H(d.Conclusion)}</p></div>");
        b.Append($"<div class='card'><h2>参数与标定溯源</h2><p>设置时长 {F(d.Settings.DurationMinutes,"F2")} 分钟；"+
            $"最少批数 {d.Settings.MinimumBatches}；绘图采样间隔 {F(d.Settings.PlotIntervalSeconds)}s。</p>"+
            $"<p>ACC：{H(d.AccJsonFile)}<br/>SHA256：{H(d.AccSha256)}</p>"+
            $"<p>Gyro：{H(d.GyroJsonFile)}<br/>SHA256：{H(d.GyroSha256)}</p>"+
            $"<p>实际原始采集目录：{H(d.AcquisitionFolder)}</p></div>");
        if(d.Analysis is { } a)
        {
            var q=a.TimeQuality;
            b.Append($"<div class='card'><h2>时标和静止质量</h2><p>判定：{H(q.Classification)}；16帧批数 {q.Batches}，"+
                $"实际记录 {F(q.McuDurationSeconds,"F2")} 秒，批次断点 {q.GapOrOverlapIntervals}。</p>"+
                $"<p>主机时长差：{F(q.HostMcuDurationMismatchPercent)}%；"+
                $"温度 {F(q.TemperatureMinC,"F2")}～{F(q.TemperatureMaxC,"F2")}℃；"+
                $"ACC方向最大变化 {F(q.MaxAccDirectionChangeDeg,"F5")}°。</p>");
            foreach(var w in q.Warnings)b.Append($"<p class='warning'>⚠ {H(w)}</p>");
            b.Append("</div>");
            if(a.MetricsReleased)
            {
                b.Append("<div class='card'><h2>三轴未融合积分漂移</h2><table><tr><th>轴</th><th>10分钟 °</th><th>30分钟 °</th><th>最后角度 °</th><th>最大绝对角度 °</th><th>拟合斜率 °/min</th><th>残余速率 °/s</th></tr>");
                foreach(var m in a.Axes)
                    b.Append($"<tr><td>{H(m.Axis)}</td><td>{F(m.DriftAt10MinutesDeg)}</td><td>{F(m.DriftAt30MinutesDeg)}</td>"+
                        $"<td>{F(m.FinalAngleDeg)}</td><td>{F(m.MaxAbsoluteAngleDeg)}</td>"+
                        $"<td>{F(m.LeastSquaresSlopeDegPerMinute,"F6")}</td><td>{F(m.MeanRateDps,"F7")}</td></tr>");
                b.Append("</table><p>三轴积分向量模长：10分钟 "+F(a.DriftVectorMagnitudeAt10MinutesDeg)+
                    "°；30分钟 "+F(a.DriftVectorMagnitudeAt30MinutesDeg)+"°。</p></div>");
                b.Append("<div class='card'><h2>真实批次时间积分漂移曲线</h2>"+Chart(a.Curve)+"</div>");
            }
            else b.Append("<div class='card'><h2>积分指标未发布</h2><p>记录未通过时标/连续性/静止质量检查，"+
                "故报告不包含不可信的角度漂移或斜率；原始记录仍被保留。</p></div>");
            b.Append($"<div class='card'><h2>计算方法</h2><p>{H(a.MethodDescription)}</p></div>");
        }
        b.Append($"<div class='card'><h2>方法学边界</h2><p>{H(d.ScientificCaveat)}</p></div></body></html>");
        return b.ToString();
    }
    private static string Col(int n)
    {
        string s="";while(n>0){n--;s=(char)('A'+n%26)+s;n/=26;}return s;
    }
    private static string Cell(int row,int col,object? v)
    {
        string addr=Col(col)+row;
        if(v is double or int or long)return $"<c r='{addr}'><v>{Convert.ToString(v,Ci)}</v></c>";
        return $"<c r='{addr}' t='inlineStr'><is><t>{X(v?.ToString())}</t></is></c>";
    }
    private static string Sheet(IEnumerable<object?[]> rows)
    {
        var b=new StringBuilder("<?xml version='1.0' encoding='utf-8'?><worksheet xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'><sheetData>");
        int row=0;foreach(var r in rows){row++;b.Append($"<row r='{row}'>");for(int j=0;j<r.Length;j++)b.Append(Cell(row,j+1,r[j]));b.Append("</row>");}
        return b.Append("</sheetData></worksheet>").ToString();
    }
    private static void Add(ZipArchive zip,string name,string body)
    {
        var e=zip.CreateEntry(name,CompressionLevel.Optimal);
        using var writer=new StreamWriter(e.Open(),new UTF8Encoding(false));writer.Write(body);
    }
    private static void Excel(string path,Ct22ReportData d)
    {
        var overview=new List<object?[]>{new object?[]{"Field","Value"},new object?[]{"Test","CT-22"},
            new object?[]{"Device",d.DeviceNumber},new object?[]{"UID",d.UidHex},
            new object?[]{"State",d.State},new object?[]{"FailureReason",d.FailureReason},
            new object?[]{"DurationMinutes",d.Settings.DurationMinutes},
            new object?[]{"ACC_SHA256",d.AccSha256},new object?[]{"Gyro_SHA256",d.GyroSha256},
            new object?[]{"RawFolder",d.AcquisitionFolder},new object?[]{"Note",d.ScientificCaveat}};
        var axes=new List<object?[]>{new object?[]{"Axis","MeanRateDps","FinalAngleDeg","MaximumAbsDeg","SlopeDegPerMin","Drift10minDeg","Drift30minDeg"}};
        var curve=new List<object?[]>{new object?[]{"MCU_ElapsedSeconds","X_Deg","Y_Deg","Z_Deg","RateX_Dps","RateY_Dps","RateZ_Dps","TempC","AccDirectionChangeDeg"}};
        if(d.Analysis is { } a)
        {
            overview.Add(new object?[]{"TimeQuality",a.TimeQuality.Classification});
            overview.Add(new object?[]{"MCUDurationSeconds",a.TimeQuality.McuDurationSeconds});
            overview.Add(new object?[]{"FIFO_Gaps",a.TimeQuality.GapOrOverlapIntervals});
            overview.Add(new object?[]{"MetricsReleased",a.MetricsReleased.ToString()});
            if(a.MetricsReleased)
            {
                foreach(var m in a.Axes)
                    axes.Add(new object?[]{m.Axis,m.MeanRateDps,m.FinalAngleDeg,m.MaxAbsoluteAngleDeg,
                        m.LeastSquaresSlopeDegPerMinute,m.DriftAt10MinutesDeg,m.DriftAt30MinutesDeg});
                foreach(var p in a.Curve)
                    curve.Add(new object?[]{p.ElapsedSeconds,p.GxDeg,p.GyDeg,p.GzDeg,
                        p.GxRateDps,p.GyRateDps,p.GzRateDps,p.TemperatureC,p.AccAngleFromStartDeg});
            }
        }
        using var z=ZipFile.Open(path,ZipArchiveMode.Create);
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
            "<sheets><sheet name='Summary' sheetId='1' r:id='rId1'/><sheet name='AxisMetrics' sheetId='2' r:id='rId2'/><sheet name='DriftCurve' sheetId='3' r:id='rId3'/></sheets></workbook>");
        Add(z,"xl/_rels/workbook.xml.rels","<?xml version='1.0' encoding='utf-8'?><Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'>"+
            "<Relationship Id='rId1' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet' Target='worksheets/sheet1.xml'/>"+
            "<Relationship Id='rId2' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet' Target='worksheets/sheet2.xml'/>"+
            "<Relationship Id='rId3' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet' Target='worksheets/sheet3.xml'/></Relationships>");
        Add(z,"xl/worksheets/sheet1.xml",Sheet(overview));
        Add(z,"xl/worksheets/sheet2.xml",Sheet(axes));
        Add(z,"xl/worksheets/sheet3.xml",Sheet(curve));
    }
}
