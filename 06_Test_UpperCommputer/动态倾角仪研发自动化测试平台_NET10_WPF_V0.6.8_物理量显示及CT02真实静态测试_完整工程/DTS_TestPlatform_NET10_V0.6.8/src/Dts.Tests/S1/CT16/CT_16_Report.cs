using System.Globalization;
using System.IO.Compression;
using System.Net;
using System.Security;
using System.Text;
using System.Text.Json;

namespace Dts.Tests.S1.CT16;

/// <summary>Independent native JSON, UTF-8 CSV, self-contained SVG HTML and OOXML XLSX reports.</summary>
public static class Ct16Report
{
    private static readonly CultureInfo Ci=CultureInfo.InvariantCulture;
    private static readonly JsonSerializerOptions Options=new(){WriteIndented=true};
    private static string F(double v,string format="F5")=>v.ToString(format,Ci);
    private static string H(string? v)=>WebUtility.HtmlEncode(v??"");
    private static string Quoted(string? v)=>"\""+(v??"").Replace("\"","\"\"")+"\"";
    public static async Task SaveCheckpointAsync(string folder,Ct16ReportData data,CancellationToken ct)
    {
        string target=Path.Combine(folder,"CT-16_checkpoint.json");
        string tmp=target+".tmp";
        await File.WriteAllTextAsync(tmp,JsonSerializer.Serialize(data,Options),new UTF8Encoding(false),ct);
        File.Move(tmp,target,true);
    }
    public static async Task<IReadOnlyList<string>> ExportAsync(string folder,Ct16ReportData data,CancellationToken ct)
    {
        Directory.CreateDirectory(folder);
        string json=Path.Combine(folder,"CT-16_result.json"),
               csv=Path.Combine(folder,"CT-16_recovery_bins.csv"),
               cycleCsv=Path.Combine(folder,"CT-16_cycles.csv"),
               html=Path.Combine(folder,"CT-16_report.html"),
               xlsx=Path.Combine(folder,"CT-16_report.xlsx");
        await SaveCheckpointAsync(folder,data,ct);
        await File.WriteAllTextAsync(json,JsonSerializer.Serialize(data,Options),new UTF8Encoding(false),ct);
        var rows=new List<string>{"cycle,bin,is_baseline,since_stop_seconds,started_utc,finished_utc,inner_feedback_deg,outer_feedback_deg,acc_x_g,acc_y_g,acc_z_g,gyro_x_dps,gyro_y_dps,gyro_z_dps,signed_tilt_proxy_deg,angular_displacement_deg,samples,batches,duplicates,temp_c,physical_csv"};
        foreach(var v in data.Bins)
        {
            var values=new List<string>{v.CycleIndex.ToString(Ci),v.BinIndex.ToString(Ci),v.Baseline?"1":"0",F(v.SinceStopSeconds,"G17"),Quoted(v.StartedUtc),Quoted(v.FinishedUtc),F(v.InnerFeedbackDeg,"G17"),F(v.OuterFeedbackDeg,"G17")};
            values.AddRange(v.AccCorrectedMeanG.Select(x=>F(x,"G17")));
            values.AddRange(v.GyroCorrectedMeanDps.Select(x=>F(x,"G17")));
            values.AddRange(new[]{v.SignedTiltProxyDeg,v.AngularDisplacementDeg}.Select(x=>F(x,"G17")));
            values.AddRange([v.Samples.ToString(Ci),v.Batches.ToString(Ci),v.DuplicateBatches.ToString(Ci),F(v.TemperatureC,"G17"),Quoted(v.PhysicalCsv)]);
            rows.Add(string.Join(",",values));
        }
        await File.WriteAllLinesAsync(csv,rows,new UTF8Encoding(true),ct);
        var cycles=new List<string>{"cycle,speed_dps,direction,home_deg,excursion_target_deg,stop_confirmed_utc,inner_stop_feedback_deg,outer_stop_feedback_deg,observed_post_stop_peak_deg,peak_signed_proxy_deg,final_signed_offset_deg,final_angular_offset_deg,recovered_by_seconds,recovery_windows,interpretation"};
        foreach(var c in data.Cycles)
            cycles.Add(string.Join(",",new[]{c.Index.ToString(Ci),F(c.SpeedDps,"G17"),Quoted(c.Direction),
                F(c.HomeDeg,"G17"),F(c.ExcursionTargetDeg,"G17"),Quoted(c.StopConfirmedUtc),
                F(c.InnerStopFeedbackDeg,"G17"),F(c.OuterStopFeedbackDeg,"G17"),
                F(c.PeakObservedAfterStopDeg,"G17"),F(c.PeakSignedProxyDeg,"G17"),
                F(c.FinalSignedOffsetDeg,"G17"),F(c.FinalAngularOffsetDeg,"G17"),
                c.RecoveredBySeconds is double t?F(t,"G17"):"",c.RecoveryBins.ToString(Ci),Quoted(c.RecoveryInterpretation)}));
        await File.WriteAllLinesAsync(cycleCsv,cycles,new UTF8Encoding(true),ct);
        await File.WriteAllTextAsync(html,BuildHtml(data),new UTF8Encoding(false),ct);
        WriteXlsx(xlsx,data);
        return [json,csv,cycleCsv,html,xlsx,Path.Combine(folder,"CT-16_checkpoint.json")];
    }
    private static string Chart(IReadOnlyList<Ct16Bin> values,string label,bool signed)
    {
        if(values.Count==0)return "<p>尚未采集到有效恢复窗口</p>";
        const double left=72,top=24,spanX=750,spanY=190;
        var points=values.Select(v=>(X:v.SinceStopSeconds,Y:signed?v.SignedTiltProxyDeg:v.AngularDisplacementDeg)).ToArray();
        double xmax=Math.Max(1,points.Max(p=>p.X));
        double ymin=points.Min(p=>p.Y),ymax=points.Max(p=>p.Y);
        double pad=Math.Max(0.01,(ymax-ymin)*0.12);
        ymin-=pad;ymax+=pad;
        string C(double n)=>F(n,"F2");
        var s=new StringBuilder("<svg viewBox='0 0 870 260' role='img' aria-label='"+H(label)+"'>");
        for(int k=0;k<=4;k++)
        {
            double y=top+spanY*k/4;
            s.Append($"<line x1='{C(left)}' y1='{C(y)}' x2='{C(left+spanX)}' y2='{C(y)}' stroke='#e2ecf5'/>"+
                     $"<text x='3' y='{C(y+4)}' font-size='12' fill='#657b90'>{C(ymax-k*(ymax-ymin)/4)}°</text>");
        }
        string poly=string.Join(" ",points.Select(p=>$"{C(left+spanX*p.X/xmax)},{C(top+spanY*(ymax-p.Y)/(ymax-ymin))}"));
        s.Append($"<polyline points='{poly}' stroke='#246ec4' stroke-width='2.5' fill='none'/>"+
                 "<text x='720' y='248' font-size='12' fill='#657b90'>停车确认后秒数</text>");
        foreach(var p in points)
        {
            double x=left+spanX*p.X/xmax,y=top+spanY*(ymax-p.Y)/(ymax-ymin);
            s.Append($"<circle cx='{C(x)}' cy='{C(y)}' r='3.5' fill='#246ec4'><title>{F(p.X,"F3")}s, {F(p.Y,"F6")}°</title></circle>");
        }
        return s.Append("</svg>").ToString();
    }
    private static string BuildHtml(Ct16ReportData d)
    {
        var s=new StringBuilder("<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'/><title>CT-16 低速运动后归零</title>"+
            "<style>body{background:#f4f8fc;color:#223f60;font:14px 'Microsoft YaHei',sans-serif;max-width:1160px;margin:25px auto;padding:0 18px}.card{background:#fff;border-radius:11px;border:1px solid #dce7f0;margin:14px 0;padding:18px}h1,h2{color:#21649b}table{border-collapse:collapse;width:100%;font-size:12px}th,td{border:1px solid #dce7f0;padding:7px;text-align:right}th{background:#eaf3fb}th:first-child,td:first-child{text-align:left}svg{max-width:100%;height:auto}.warning{border-left:4px solid #d69b42;padding-left:12px}@media print{.card{break-inside:avoid}}</style></head><body><h1>CT-16 · 低速运动后归零与恢复</h1>");
        s.Append($"<div class='card'><p><b>设备：</b>{H(d.DeviceNumber)}　<b>完整UID：</b>{H(d.UidHex)}　<b>状态：</b>{H(d.State)}</p>"+
                 $"<p>开始：{H(d.StartedUtc)}<br/>结束：{H(d.FinishedUtc)}</p>"+
                 $"<p>{H(d.Reason)}</p><p class='warning'><b>{H(d.Conclusion)}</b></p></div>");
        s.Append($"<div class='card'><h2>扫描参数与数据溯源</h2>"+
                 $"<p>低速档位：{H(d.Settings.SpeedsDps)} °/s；每方向重复{d.Settings.Repeats}次；"+
                 $"固定内轴{F(d.Settings.InnerFixedDeg)}°，外轴零位{F(d.Settings.OuterHomeDeg)}°，单侧往返幅度±{F(d.Settings.ExcursionDeg)}°。</p>"+
                 $"<p>基线采样{F(d.Settings.BaselineSeconds)}s；停车后观察{F(d.Settings.RecoverySeconds)}s；"+
                 $"每窗{F(d.Settings.BinSeconds)}s；恢复阈值{F(d.Settings.RecoveryThresholdDeg)}°，连续窗口{d.Settings.ConsecutiveBins}。</p>"+
                 $"<p>模型：{H(d.ModelDescription)}；输入量纲：{H(d.ScaleDescription)}</p>"+
                 $"<p>ACC：{H(d.AccFile)}<br/>SHA256：{H(d.AccSha256)}<br/>Gyro：{H(d.GyroFile)}<br/>SHA256：{H(d.GyroSha256)}</p></div>");
        if(d.Aggregate is { } a)
        {
            s.Append($"<div class='card'><h2>总体工程诊断</h2><p>完成周期：{a.CompletedCycles}；观察到恢复的周期：{a.RecoveryObservedCycles}；"+
                     $"停车后ACC代理最大偏离：{F(a.MaximumObservedPostStopPeakDeg)}°；"+
                     $"最终角度偏离均值：{F(a.MeanFinalAngularOffsetDeg)}°；"+
                     $"恢复时间上界均值：{(a.MeanObservedRecoveryUpperBoundSeconds is double t?F(t)+"s":"未确认")}。</p></div>");
        }
        foreach(var c in d.Cycles)
        {
            var recovery=d.Bins.Where(b=>b.CycleIndex==c.Index&&!b.Baseline).ToArray();
            s.Append($"<div class='card'><h2>周期{c.Index} · {F(c.SpeedDps)}°/s · {H(c.Direction)}</h2>"+
                     $"<p>停车后观测峰值{F(c.PeakObservedAfterStopDeg)}°，最后偏差{F(c.FinalSignedOffsetDeg)}°；"+
                     $"恢复时间上界：{(c.RecoveredBySeconds is double sec?F(sec)+"s":"未确认恢复")}。</p>"+
                     Chart(recovery,"恢复曲线",true)+"<p>曲线为相对静态基线的ACC推算外轴切向倾角（°），非设备融合倾角。</p>"+
                     Chart(recovery,"三维方向偏差",false)+"</div>");
        }
        s.Append("<div class='card'><h2>周期汇总</h2><table><tr><th>周期</th><th>速度°/s</th><th>运动方向</th><th>观测峰值°</th><th>最终偏差°</th><th>恢复上界s</th><th>恢复窗数</th></tr>");
        foreach(var c in d.Cycles)
            s.Append($"<tr><td>{c.Index}</td><td>{F(c.SpeedDps)}</td><td>{H(c.Direction)}</td>"+
                     $"<td>{F(c.PeakObservedAfterStopDeg)}</td><td>{F(c.FinalSignedOffsetDeg)}</td>"+
                     $"<td>{(c.RecoveredBySeconds is double t?F(t):"—")}</td><td>{c.RecoveryBins}</td></tr>");
        s.Append("</table></div><div class='card'><h2>测量限制</h2><p class='warning'>"+H(d.Caveat)+
                 "</p><p>原始逐窗CSV和JSON提供全部采样溯源；没有融合角信号时不能给完整CT-16产品验收结果。</p></div></body></html>");
        return s.ToString();
    }
    private static string X(string value)=>SecurityElement.Escape(value)??"";
    private static string ExcelCell(int row,int column,object? value)
    {
        string addr=$"{(char)('A'+column-1)}{row}";
        if(value is null)return "";
        if(value is double or int or long)
            return $"<c r='{addr}'><v>{Convert.ToString(value,Ci)}</v></c>";
        return $"<c r='{addr}' t='inlineStr'><is><t>{X(value.ToString()??"")}</t></is></c>";
    }
    private static string Worksheet(IEnumerable<object?[]> rows)
    {
        var s=new StringBuilder("<?xml version='1.0' encoding='utf-8'?><worksheet xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'><sheetData>");
        int row=0;
        foreach(var values in rows)
        {
            ++row;s.Append($"<row r='{row}'>");
            for(int c=0;c<values.Length;c++)s.Append(ExcelCell(row,c+1,values[c]));
            s.Append("</row>");
        }
        return s.Append("</sheetData></worksheet>").ToString();
    }
    private static void Add(ZipArchive zip,string name,string body)
    {
        var entry=zip.CreateEntry(name,CompressionLevel.Optimal);
        using var writer=new StreamWriter(entry.Open(),new UTF8Encoding(false));writer.Write(body);
    }
    private static void WriteXlsx(string file,Ct16ReportData d)
    {
        var summary=new List<object?[]>{new object?[]{"字段","值"},new object?[]{"编号","CT-16"},
            new object?[]{"类型","ACC倾角代理诊断，不是融合输出"},new object?[]{"设备",d.DeviceNumber},
            new object?[]{"完整UID",d.UidHex},new object?[]{"状态",d.State},
            new object?[]{"完成循环",d.Cycles.Count},new object?[]{"观察到恢复",d.Aggregate?.RecoveryObservedCycles},
            new object?[]{"最大停车后观测峰值(°)",d.Aggregate?.MaximumObservedPostStopPeakDeg},
            new object?[]{"最终角度偏差均值(°)",d.Aggregate?.MeanFinalAngularOffsetDeg},
            new object?[]{"ACC SHA256",d.AccSha256},new object?[]{"Gyro SHA256",d.GyroSha256},
            new object?[]{"报告限制",d.Caveat}};
        var cycles=new List<object?[]>{new object?[]{"周期","低速°/s","运动方向","零位°","离位目标°","停稳外轴°","停车后观测峰值°","最终有符号偏差°","最终方向偏差°","恢复时间上界(s)","状态"}};
        foreach(var c in d.Cycles)
            cycles.Add(new object?[]{c.Index,c.SpeedDps,c.Direction,c.HomeDeg,c.ExcursionTargetDeg,
                c.OuterStopFeedbackDeg,c.PeakObservedAfterStopDeg,c.FinalSignedOffsetDeg,
                c.FinalAngularOffsetDeg,c.RecoveredBySeconds,c.RecoveryInterpretation});
        var data=new List<object?[]>{new object?[]{"周期","窗口","基线","停车后秒数","ACC切向偏差°","ACC方向差°","内轴反馈°","外轴反馈°","ACC X g","ACC Y g","ACC Z g","Gyro X °/s","Gyro Y °/s","Gyro Z °/s","真实帧","温度℃","原始CSV"}};
        foreach(var v in d.Bins)
            data.Add(new object?[]{v.CycleIndex,v.BinIndex,v.Baseline?"是":"否",v.SinceStopSeconds,
                v.SignedTiltProxyDeg,v.AngularDisplacementDeg,v.InnerFeedbackDeg,v.OuterFeedbackDeg,
                v.AccCorrectedMeanG[0],v.AccCorrectedMeanG[1],v.AccCorrectedMeanG[2],
                v.GyroCorrectedMeanDps[0],v.GyroCorrectedMeanDps[1],v.GyroCorrectedMeanDps[2],
                v.Samples,v.TemperatureC,v.PhysicalCsv});
        using var zip=ZipFile.Open(file,ZipArchiveMode.Create);
        var types=new StringBuilder("<?xml version='1.0' encoding='utf-8'?><Types xmlns='http://schemas.openxmlformats.org/package/2006/content-types'>"+
            "<Default Extension='rels' ContentType='application/vnd.openxmlformats-package.relationships+xml'/>"+
            "<Default Extension='xml' ContentType='application/xml'/>"+
            "<Override PartName='/xl/workbook.xml' ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml'/>");
        for(int i=1;i<=3;i++)types.Append($"<Override PartName='/xl/worksheets/sheet{i}.xml' ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml'/>");
        Add(zip,"[Content_Types].xml",types.Append("</Types>").ToString());
        Add(zip,"_rels/.rels","<?xml version='1.0' encoding='utf-8'?><Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'>"+
            "<Relationship Id='rId1' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument' Target='xl/workbook.xml'/></Relationships>");
        Add(zip,"xl/workbook.xml","<?xml version='1.0' encoding='utf-8'?><workbook xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main' xmlns:r='http://schemas.openxmlformats.org/officeDocument/2006/relationships'>"+
            "<sheets><sheet name='Summary' sheetId='1' r:id='rId1'/><sheet name='Cycles' sheetId='2' r:id='rId2'/><sheet name='Recovery' sheetId='3' r:id='rId3'/></sheets></workbook>");
        var rels=new StringBuilder("<?xml version='1.0' encoding='utf-8'?><Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'>");
        for(int i=1;i<=3;i++)rels.Append($"<Relationship Id='rId{i}' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet' Target='worksheets/sheet{i}.xml'/>");
        Add(zip,"xl/_rels/workbook.xml.rels",rels.Append("</Relationships>").ToString());
        Add(zip,"xl/worksheets/sheet1.xml",Worksheet(summary));
        Add(zip,"xl/worksheets/sheet2.xml",Worksheet(cycles));
        Add(zip,"xl/worksheets/sheet3.xml",Worksheet(data));
    }
}
