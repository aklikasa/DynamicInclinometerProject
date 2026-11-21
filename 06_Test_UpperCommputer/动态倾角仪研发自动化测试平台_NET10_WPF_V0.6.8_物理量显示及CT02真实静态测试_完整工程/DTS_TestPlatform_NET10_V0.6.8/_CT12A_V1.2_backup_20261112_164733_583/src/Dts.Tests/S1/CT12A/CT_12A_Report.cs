using System.Globalization;
using System.IO;
using System.IO.Compression;
using System.Net;
using System.Security;
using System.Text;
using System.Text.Json;

namespace Dts.Tests.S1.CT12A;

/// <summary>Self-contained JSON / curve CSV / quality CSV / HTML+3-axis SVG / native XLSX.</summary>
public static class Ct12aReport
{
    private static readonly CultureInfo Ci=CultureInfo.InvariantCulture;
    private static readonly JsonSerializerOptions Options=new(){WriteIndented=true};
    private static string F(double x,string fmt="F5")=>x.ToString(fmt,Ci);
    private static string F(double? x,string fmt="F5")=>x is null?"N/A":F(x.Value,fmt);
    private static string H(string? v)=>WebUtility.HtmlEncode(v??"");
    private static string Xml(string? v)=>SecurityElement.Escape(v??"")??"";
    private static string Q(string? v)=>"\""+(v??"").Replace("\"","\"\"")+"\"";

    public static async Task<IReadOnlyList<string>> ExportAsync(string folder,Ct12aReportData d,CancellationToken ct)
    {
        Directory.CreateDirectory(folder);
        string json=Path.Combine(folder,"CT-12A_result.json");
        string curve=Path.Combine(folder,"CT-12A_allan_curve.csv");
        string quality=Path.Combine(folder,"CT-12A_quality.csv");
        string html=Path.Combine(folder,"CT-12A_report.html");
        string excel=Path.Combine(folder,"CT-12A_report.xlsx");
        await File.WriteAllTextAsync(json,JsonSerializer.Serialize(d,Options),new UTF8Encoding(false),ct);
        var cr=new List<string>{"tau_seconds,cluster_batches,overlap_differences,gyro_x_adev_dps,gyro_y_adev_dps,gyro_z_adev_dps,acc_x_adev_g,acc_y_adev_g,acc_z_adev_g,gyro_x_avar_dps2,gyro_y_avar_dps2,gyro_z_avar_dps2,acc_x_avar_g2,acc_y_avar_g2,acc_z_avar_g2,quality"};
        if(d.Analysis is { } a)
        foreach(var c in a.Curves)
            cr.Add(string.Join(",",F(c.TauSeconds,"G17"),c.ClusterBatches.ToString(Ci),
                c.OverlappingDifferences.ToString(Ci),F(c.GxAllanDeviationDps,"G17"),
                F(c.GyAllanDeviationDps,"G17"),F(c.GzAllanDeviationDps,"G17"),
                F(c.AxAllanDeviationG,"G17"),F(c.AyAllanDeviationG,"G17"),F(c.AzAllanDeviationG,"G17"),
                F(c.GxAllanDeviationDps*c.GxAllanDeviationDps,"G17"),
                F(c.GyAllanDeviationDps*c.GyAllanDeviationDps,"G17"),
                F(c.GzAllanDeviationDps*c.GzAllanDeviationDps,"G17"),
                F(c.AxAllanDeviationG*c.AxAllanDeviationG,"G17"),
                F(c.AyAllanDeviationG*c.AyAllanDeviationG,"G17"),
                F(c.AzAllanDeviationG*c.AzAllanDeviationG,"G17"),
                Q(a.TimeQuality.Classification)));
        await File.WriteAllLinesAsync(curve,cr,new UTF8Encoding(true),ct);
        var qr=new List<string>{"metric,value,unit_or_note"};
        if(d.Analysis is { } analysis)
        {
            var q=analysis.TimeQuality;
            qr.Add($"classification,{Q(q.Classification)},batch-level only");
            qr.Add($"continuous_qualified,{q.ContinuousSequenceQualified},no individual frame timestamp");
            qr.Add($"frames,{q.Frames},frames");qr.Add($"batches,{q.Batches},batches");
            qr.Add($"gaps_or_overlaps,{q.GapsOrOverlaps},FIFO window continuity errors");
            qr.Add($"skipped_unchanged_polls,{q.SkippedUnchangedPolls},not automatically a data gap");
            qr.Add($"host_period_median,{F(q.MedianBatchPeriodSeconds,"G17")},seconds");
            qr.Add($"mcu_period_median,{F(q.MedianMcuPeriodSeconds,"G17")},seconds");
            qr.Add($"host_jitter_p95,{F(q.HostCadenceJitterP95Percent,"G17")},percent");
            qr.Add($"mcu_jitter_p95,{F(q.McuCadenceJitterP95Percent,"G17")},percent");
            qr.Add($"fifo_span_error_p95,{F(q.FifoSpanErrorP95Percent,"G17")},percent");
            qr.Add($"coefficient_released,{analysis.CoefficientsReleased},engineering only");
            foreach(string w in q.Warnings)qr.Add("warning,"+Q(w)+",quality audit");
        }
        else qr.Add("analysis_failed,"+Q(d.FailureReason)+",see JSON");
        await File.WriteAllLinesAsync(quality,qr,new UTF8Encoding(true),ct);
        await File.WriteAllTextAsync(html,Html(d),new UTF8Encoding(false),ct);
        Excel(excel,d);
        return [json,curve,quality,html,excel];
    }

    private static string Svg(Ct12aReportData report,bool acceleration)
    {
        var pts=report.Analysis?.Curves;
        if(pts is not { Count:>1 })
            return "<p>时标/连续性或采样时长未满足条件，本次不提供未经验证的Allan曲线。</p>";
        double loX=Math.Log10(pts.Min(v=>v.TauSeconds)),hiX=Math.Log10(pts.Max(v=>v.TauSeconds));
        var all=pts.SelectMany(v=>acceleration?
            new[]{v.AxAllanDeviationG,v.AyAllanDeviationG,v.AzAllanDeviationG}:
            new[]{v.GxAllanDeviationDps,v.GyAllanDeviationDps,v.GzAllanDeviationDps})
            .Where(x=>double.IsFinite(x)&&x>0).ToArray();
        if(all.Length==0)return "<p>数据不足以展示有效对数曲线</p>";
        double loY=Math.Log10(all.Min()),hiY=Math.Log10(all.Max());
        if(hiX-loX<1e-12||hiY-loY<1e-12)hiY=loY+0.1;
        double X(double t)=>82+690*(Math.Log10(t)-loX)/(hiX-loX);
        double Y(double v)=>28+300*(hiY-Math.Log10(Math.Max(v,1e-30)))/(hiY-loY);
        string N(double v)=>v.ToString("F2",Ci);
        var sb=new StringBuilder("<svg viewBox='0 0 900 390' role='img' xmlns='http://www.w3.org/2000/svg'>");
        for(int i=0;i<=4;i++)
        {
            double x=82+i*690/4d,y=28+i*300/4d;
            sb.Append($"<line x1='{N(x)}' x2='{N(x)}' y1='28' y2='328' stroke='#deebf5'/>"+
                      $"<line x1='82' x2='772' y1='{N(y)}' y2='{N(y)}' stroke='#deebf5'/>");
            sb.Append($"<text x='{N(x)}' y='352' font-size='11' text-anchor='middle'>"+
                      $"{F(Math.Pow(10,loX+(hiX-loX)*i/4),"G3")}s</text>");
            sb.Append($"<text x='4' y='{N(y+4)}' font-size='11'>"+
                      $"{F(Math.Pow(10,hiY-(hiY-loY)*i/4),"G3")}</text>");
        }
        string[] colors=["#186fc1","#d47b20","#469260"];
        for(int j=0;j<3;j++)
        {
            double Value(Ct12aCurvePoint p)=>acceleration
                ? (j switch{0=>p.AxAllanDeviationG,1=>p.AyAllanDeviationG,_=>p.AzAllanDeviationG})
                : (j switch{0=>p.GxAllanDeviationDps,1=>p.GyAllanDeviationDps,_=>p.GzAllanDeviationDps});
            string positions=string.Join(" ",pts.Where(p=>Value(p)>0)
                .Select(p=>$"{N(X(p.TauSeconds))},{N(Y(Value(p)))}"));
            sb.Append($"<polyline points='{positions}' fill='none' stroke='{colors[j]}' stroke-width='2.6'/>");
            sb.Append($"<text x='804' y='{35+j*25}' fill='{colors[j]}' font-size='14'>{(acceleration?"ACC":"Gyro")}-{(char)('X'+j)}</text>");
        }
        return sb.Append("<text x='420' y='383' text-anchor='middle' font-size='13'>平均时间 τ (s) · 对数坐标</text></svg>").ToString();
    }
    private static string Html(Ct12aReportData d)
    {
        var b=new StringBuilder("<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><title>CT-12A Allan方差/随机稳定性</title>");
        b.Append("<style>body{font:14px 'Microsoft YaHei',sans-serif;color:#18364c;background:#f3f7fb;max-width:1150px;margin:22px auto;padding:0 14px}h1,h2{color:#145c98}.card{padding:19px;border:1px solid #deebf5;background:white;border-radius:13px;margin:13px 0}table{border-collapse:collapse;width:100%;font-size:12px}th,td{border:1px solid #dae5ef;padding:8px;text-align:right}th:first-child,td:first-child{text-align:left}th{background:#ecf3f8}.warning{color:#985e1a}svg{max-width:100%;height:auto}@media print{body{background:white}.card{break-inside:avoid}}</style></head><body>");
        b.Append($"<h1>CT-12A · Allan 方差／随机稳定性表征</h1><div class='card'><p><b>设备：</b>{H(d.DeviceNumber)}　<b>完整UID：</b>{H(d.UidHex)}</p>"+
            $"<p><b>状态：</b>{H(d.State)}　<b>开始：</b>{H(d.StartedUtc)}　<b>结束：</b>{H(d.FinishedUtc)}</p>"+
            $"<p class='warning'>{H(d.FailureReason)}</p><p>{H(d.Conclusion)}</p></div>");
        b.Append($"<div class='card'><h2>采集参数与标定溯源</h2>"+
            $"<p>持续时间 {F(d.Settings.DurationMinutes,"F1")} 分钟；τ范围 {F(d.Settings.TauMinSeconds,"F2")}～{F(d.Settings.TauMaxSeconds,"F1")} 秒；每十倍程 {d.Settings.PointsPerDecade} 点。</p>"+
            $"<p>主机批次周期P95抖动阈值 {F(d.Settings.MaxHostCadenceJitterPercent,"F1")}%；MCU周期阈值 {F(d.Settings.MaxMcuCadenceJitterPercent,"F1")}%；FIFO跨度阈值 {F(d.Settings.MaxFifoSpanErrorPercent,"F1")}%；最少批数 {d.Settings.MinimumBatches}；温度变化限值 {F(d.Settings.MaxTemperatureRangeC,"F2")}°C。</p>"+
            $"<p>ACC源：{H(d.CalibrationAccFile)}　SHA256：{H(d.CalibrationAccSha256)}<br/>"+
            $"Gyro源：{H(d.CalibrationGyroFile)}　SHA256：{H(d.CalibrationGyroSha256)}</p>"+
            $"<p>原始数据目录：{H(d.AcquisitionFolder)}<br/>原始CSV：{H(d.RawCsvPath)}<br/>已校正CSV：{H(d.SelectedCsvPath)}</p></div>");
        if(d.Analysis is { } a)
        {
            var q=a.TimeQuality;
            b.Append($"<div class='card'><h2>时间质量与真实FIFO连续性</h2>"+
                $"<p><b>分类：</b>{H(q.Classification)}　采集 {q.Frames} 帧 / {q.Batches} 批；"+
                $"断点或重叠 {q.GapsOrOverlaps} 处。</p><p>主机批次中位周期 {F(q.MedianBatchPeriodSeconds,"F5")}s，MCU批次中位周期 {F(q.MedianMcuPeriodSeconds,"F5")}s；"+
                $"主机P95抖动 {F(q.HostCadenceJitterP95Percent,"F2")}%、MCU P95抖动 {F(q.McuCadenceJitterP95Percent,"F2")}%。</p>"+
                $"<p>温度 {F(a.TemperatureMinC,"F2")}～{F(a.TemperatureMaxC,"F2")}℃；"+
                $"<b>参数发布：</b>{(a.CoefficientsReleased?"仅工程估计（未硬件同步认证）":"否；禁止解读未通过的系数")}</p>");
            foreach(string w in q.Warnings)b.Append($"<p class='warning'>• {H(w)}</p>");
            b.Append("</div>");
            b.Append("<div class='card'><h2>Gyro 三轴 Allan 偏差 (°/s) · 对数曲线</h2>").Append(Svg(d,false)).Append("</div>");
            b.Append("<div class='card'><h2>ACC 三轴 Allan 偏差 (g) · 对数曲线</h2>").Append(Svg(d,true)).Append("</div>");
            b.Append("<div class='card'><h2>六轴随机稳定性指标</h2><table><tr><th>轴</th><th>数据单位</th><th>均值</th><th>批次均值STD</th><th>最小ADEV</th><th>最小处τ (s)</th><th>ARW / VRW代理</th><th>Bias代理</th></tr>");
            foreach(var x in a.Axes)
                b.Append($"<tr><td>{H(x.Axis)}</td><td>{H(x.Unit)}</td><td>{F(x.Mean,"F7")}</td>"+
                    $"<td>{F(x.StandardDeviation,"F7")}</td><td>{F(x.MinAllanDeviation,"G6")}</td>"+
                    $"<td>{F(x.TauAtMinimumSeconds,"F3")}</td>"+
                    $"<td>{F(x.WhiteNoiseCoefficient,"F6")} {H(x.WhiteNoiseCoefficientUnit)}</td>"+
                    $"<td>{F(x.BiasInstabilityProxy,"F5")} {H(x.BiasInstabilityUnit)}</td></tr>");
            b.Append("</table><p>“N/A”代表没有满足相应噪声模型证据，不代表零噪声。</p></div>");
            b.Append($"<div class='card'><h2>方法说明</h2><p>{H(a.MethodDescription)}</p></div>");
        }
        else b.Append("<div class='card'><h2>分析未完成</h2><p>原始采集已保存，拒绝生成无效曲线或编造指标。</p></div>");
        b.Append($"<div class='card'><h2>计量局限</h2><p class='warning'>{H(d.ScientificCaveat)}</p></div></body></html>");
        return b.ToString();
    }

    // Inline-string OpenXML avoids an external Excel library dependency in the user's Windows build.
    private static string Column(int n)
    {
        string s="";
        while(n>0){n--;s=(char)('A'+n%26)+s;n/=26;}
        return s;
    }
    private static string Cell(int row,int col,object? value)
    {
        string pos=Column(col)+row;
        if(value is double or float or int or long)
            return $"<c r='{pos}'><v>{Convert.ToString(value,Ci)}</v></c>";
        return $"<c r='{pos}' t='inlineStr'><is><t>{Xml(value?.ToString())}</t></is></c>";
    }
    private static string Sheet(IEnumerable<object?[]> rows)
    {
        var b=new StringBuilder("<?xml version='1.0' encoding='UTF-8'?><worksheet xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'><sheetData>");
        int row=0;
        foreach(var values in rows)
        {
            row++;b.Append($"<row r='{row}'>");
            for(int j=0;j<values.Length;j++)b.Append(Cell(row,j+1,values[j]));
            b.Append("</row>");
        }
        return b.Append("</sheetData></worksheet>").ToString();
    }
    private static void Add(ZipArchive z,string name,string body)
    {
        var item=z.CreateEntry(name,CompressionLevel.Optimal);
        using var w=new StreamWriter(item.Open(),new UTF8Encoding(false));w.Write(body);
    }
    private static void Excel(string path,Ct12aReportData d)
    {
        var rows=new List<object?[]> {new object?[]{"Metric","Value"},
            new object?[]{"Test","CT-12A Allan"},new object?[]{"UID",d.UidHex},
            new object?[]{"Device",d.DeviceNumber},new object?[]{"State",d.State},
            new object?[]{"Failure / quality",d.FailureReason},
            new object?[]{"Duration min",d.Settings.DurationMinutes},
            new object?[]{"Acc SHA256",d.CalibrationAccSha256},
            new object?[]{"Gyro SHA256",d.CalibrationGyroSha256},
            new object?[]{"Raw directory",d.AcquisitionFolder},
            new object?[]{"Scientific caveat",d.ScientificCaveat}};
        var curves=new List<object?[]>{new object?[]{"Tau s","Window batches","Overlapping differences","Gyro-X ADEV dps","Gyro-Y ADEV dps","Gyro-Z ADEV dps","ACC-X ADEV g","ACC-Y ADEV g","ACC-Z ADEV g","Gyro-X AVAR dps²","Gyro-Y AVAR dps²","Gyro-Z AVAR dps²","ACC-X AVAR g²","ACC-Y AVAR g²","ACC-Z AVAR g²"}};
        var axes=new List<object?[]>{new object?[]{"Axis","Signal unit","Mean","Batch STD","Min ADEV","Tau at minimum s","ARW/VRW","ARW/VRW unit","Bias proxy","Bias unit","Note"}};
        if(d.Analysis is { } a)
        {
            rows.Add(new object?[]{"Time quality",a.TimeQuality.Classification});
            rows.Add(new object?[]{"Batches",a.TimeQuality.Batches});
            rows.Add(new object?[]{"Continuity gaps",a.TimeQuality.GapsOrOverlaps});
            rows.Add(new object?[]{"MCU interval seconds",a.TimeQuality.MedianMcuPeriodSeconds});
            rows.Add(new object?[]{"Coefficient release",a.CoefficientsReleased.ToString()});
            foreach(var c in a.Curves)
                curves.Add(new object?[]{c.TauSeconds,c.ClusterBatches,c.OverlappingDifferences,
                    c.GxAllanDeviationDps,c.GyAllanDeviationDps,c.GzAllanDeviationDps,
                    c.AxAllanDeviationG,c.AyAllanDeviationG,c.AzAllanDeviationG,
                    c.GxAllanDeviationDps*c.GxAllanDeviationDps,
                    c.GyAllanDeviationDps*c.GyAllanDeviationDps,
                    c.GzAllanDeviationDps*c.GzAllanDeviationDps,
                    c.AxAllanDeviationG*c.AxAllanDeviationG,
                    c.AyAllanDeviationG*c.AyAllanDeviationG,
                    c.AzAllanDeviationG*c.AzAllanDeviationG});
            foreach(var x in a.Axes)
                axes.Add(new object?[]{x.Axis,x.Unit,x.Mean,x.StandardDeviation,x.MinAllanDeviation,
                    x.TauAtMinimumSeconds,x.WhiteNoiseCoefficient,x.WhiteNoiseCoefficientUnit,
                    x.BiasInstabilityProxy,x.BiasInstabilityUnit,x.QualificationNote});
        }
        using var zip=ZipFile.Open(path,ZipArchiveMode.Create);
        Add(zip,"[Content_Types].xml","<?xml version='1.0' encoding='UTF-8'?><Types xmlns='http://schemas.openxmlformats.org/package/2006/content-types'>"+
            "<Default Extension='rels' ContentType='application/vnd.openxmlformats-package.relationships+xml'/>"+
            "<Default Extension='xml' ContentType='application/xml'/>"+
            "<Override PartName='/xl/workbook.xml' ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml'/>"+
            "<Override PartName='/xl/worksheets/sheet1.xml' ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml'/>"+
            "<Override PartName='/xl/worksheets/sheet2.xml' ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml'/>"+
            "<Override PartName='/xl/worksheets/sheet3.xml' ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml'/></Types>");
        Add(zip,"_rels/.rels","<?xml version='1.0' encoding='UTF-8'?><Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'>"+
            "<Relationship Id='rId1' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument' Target='xl/workbook.xml'/></Relationships>");
        Add(zip,"xl/workbook.xml","<?xml version='1.0' encoding='UTF-8'?><workbook xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main' xmlns:r='http://schemas.openxmlformats.org/officeDocument/2006/relationships'>"+
            "<sheets><sheet name='Summary' sheetId='1' r:id='rId1'/><sheet name='AllanCurve' sheetId='2' r:id='rId2'/><sheet name='SixAxes' sheetId='3' r:id='rId3'/></sheets></workbook>");
        Add(zip,"xl/_rels/workbook.xml.rels","<?xml version='1.0' encoding='UTF-8'?><Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'>"+
            "<Relationship Id='rId1' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet' Target='worksheets/sheet1.xml'/>"+
            "<Relationship Id='rId2' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet' Target='worksheets/sheet2.xml'/>"+
            "<Relationship Id='rId3' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet' Target='worksheets/sheet3.xml'/></Relationships>");
        Add(zip,"xl/worksheets/sheet1.xml",Sheet(rows));
        Add(zip,"xl/worksheets/sheet2.xml",Sheet(curves));
        Add(zip,"xl/worksheets/sheet3.xml",Sheet(axes));
    }
}
