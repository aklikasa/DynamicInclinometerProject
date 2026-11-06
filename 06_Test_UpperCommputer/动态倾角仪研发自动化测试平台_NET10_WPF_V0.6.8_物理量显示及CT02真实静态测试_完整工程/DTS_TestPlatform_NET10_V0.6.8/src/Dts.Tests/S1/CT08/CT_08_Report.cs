using System.Globalization;
using System.IO.Compression;
using System.Net;
using System.Security;
using System.Text;
using System.Text.Json;

namespace Dts.Tests.S1.CT08;

/// <summary>CT-08 evidence is always generated from actual completed visits and direction pairs.</summary>
public static class Ct08Report
{
    private static readonly CultureInfo Ci=CultureInfo.InvariantCulture;
    private static readonly JsonSerializerOptions Options=new(){WriteIndented=true};
    private static string F(double n,string fmt="F5")=>n.ToString(fmt,Ci);
    private static string H(string? s)=>WebUtility.HtmlEncode(s??"");
    private static string Q(string? s)=>"\""+(s??"").Replace("\"","\"\"")+"\"";

    public static async Task SaveCheckpointAsync(string folder,Ct08ReportData data,CancellationToken ct)
    {
        string file=Path.Combine(folder,"CT-08_checkpoint.json"),tmp=file+".tmp";
        await File.WriteAllTextAsync(tmp,JsonSerializer.Serialize(data,Options),new UTF8Encoding(false),ct);
        File.Move(tmp,file,true);
    }
    public static async Task<IReadOnlyList<string>> ExportAsync(string folder,Ct08ReportData data,CancellationToken ct)
    {
        Directory.CreateDirectory(folder);
        string json=Path.Combine(folder,"CT-08_result.json"),
            visits=Path.Combine(folder,"CT-08_visits.csv"),
            pairs=Path.Combine(folder,"CT-08_direction_pairs.csv"),
            targets=Path.Combine(folder,"CT-08_target_summary.csv"),
            html=Path.Combine(folder,"CT-08_report.html"),
            excel=Path.Combine(folder,"CT-08_report.xlsx");
        await SaveCheckpointAsync(folder,data,ct);
        await File.WriteAllTextAsync(json,JsonSerializer.Serialize(data,Options),new UTF8Encoding(false),ct);
        var vrows=new List<string>{"index,pair,cycle,approach,inner_target_deg,outer_target_deg,outer_depart_deg,inner_encoder_deg,outer_encoder_deg,reference_x_g,reference_y_g,reference_z_g,acc_x_cal_g,acc_y_cal_g,acc_z_cal_g,error_x_g,error_y_g,error_z_g,gyro_x_dps,gyro_y_dps,gyro_z_dps,angle_error_deg,acc_norm_g,temperature_c,accepted,total,removed_fraction,raw_physical_csv,corrected_csv"};
        foreach(var v in data.Visits)
        {
            var cells=new List<string>{v.Index.ToString(Ci),v.PairIndex.ToString(Ci),v.Cycle.ToString(Ci),Q(v.Side)};
            cells.AddRange(new[]{v.InnerTargetDeg,v.OuterTargetDeg,v.OuterDepartDeg,v.InnerActualDeg,v.OuterActualDeg}.Select(x=>F(x,"G17")));
            cells.AddRange(v.ReferenceG.Select(x=>F(x,"G17")));
            cells.AddRange(v.AccCorrectedMeanG.Select(x=>F(x,"G17")));
            cells.AddRange(v.AccErrorG.Select(x=>F(x,"G17")));
            cells.AddRange(v.GyroCorrectedMeanDps.Select(x=>F(x,"G17")));
            cells.AddRange(new[]{v.ReferenceDirectionErrorDeg,v.AccNormG,v.MeanTemperatureC}.Select(x=>F(x,"G17")));
            cells.Add(v.AcceptedSamples.ToString(Ci));cells.Add(v.TotalSamples.ToString(Ci));
            cells.Add(F(v.RejectedFraction,"G17"));cells.Add(Q(v.PhysicalCsv));cells.Add(Q(v.CorrectedCsv));
            vrows.Add(string.Join(",",cells));
        }
        await File.WriteAllLinesAsync(visits,vrows,new UTF8Encoding(true),ct);
        var prows=new List<string>{"pair,cycle,inner_deg,outer_deg,forward_visit,reverse_visit,delta_error_x_mg,delta_error_y_mg,delta_error_z_mg,delta_error_norm_mg,direction_hysteresis_deg,outer_feedback_forward_minus_reverse_deg,inner_feedback_forward_minus_reverse_deg,chip_temperature_forward_minus_reverse_c,gyro_x_diff_dps,gyro_y_diff_dps,gyro_z_diff_dps"};
        foreach(var p in data.Pairs)
        {
            var cells=new List<string>{p.PairIndex.ToString(Ci),p.Cycle.ToString(Ci),F(p.InnerTargetDeg,"G17"),F(p.OuterTargetDeg,"G17"),p.ForwardIndex.ToString(Ci),p.ReverseIndex.ToString(Ci)};
            cells.AddRange(p.HysteresisErrorMg.Select(x=>F(x,"G17")));
            cells.AddRange(new[]{p.HysteresisMagnitudeMg,p.DirectionHysteresisDeg,p.OuterActualDifferenceDeg,p.InnerActualDifferenceDeg,p.TemperatureDifferenceC}.Select(x=>F(x,"G17")));
            cells.AddRange(p.GyroZeroDifferenceDps.Select(x=>F(x,"G17")));
            prows.Add(string.Join(",",cells));
        }
        await File.WriteAllLinesAsync(pairs,prows,new UTF8Encoding(true),ct);
        var trows=new List<string>{"inner_deg,outer_deg,paired_rounds,mean_error_delta_norm_mg,rms_error_delta_norm_mg,max_error_delta_norm_mg,mean_direction_delta_deg,mean_outer_encoder_diff_deg"};
        foreach(var t in data.Metrics?.ByTarget??[])
            trows.Add(string.Join(",",new[]{t.InnerDeg,t.OuterDeg,(double)t.Pairs,t.MeanMagnitudeMg,t.RmsMagnitudeMg,t.MaxMagnitudeMg,t.MeanAngleHysteresisDeg,t.MeanOuterFeedbackDeltaDeg}.Select(x=>F(x,"G17"))));
        await File.WriteAllLinesAsync(targets,trows,new UTF8Encoding(true),ct);
        await File.WriteAllTextAsync(html,BuildHtml(data),new UTF8Encoding(false),ct);
        BuildXlsx(excel,data);
        return new[]{json,visits,pairs,targets,html,excel,Path.Combine(folder,"CT-08_checkpoint.json")};
    }
    private static string Svg(IReadOnlyList<double> values,string title,string unit,string color)
    {
        if(values.Count==0)return "<p>尚无完整正反路径配对</p>";
        const double width=900,height=260,left=80,top=20,plotWidth=790,plotHeight=195;
        double min=values.Min(),max=values.Max(),margin=Math.Max((max-min)*.15,.001);
        min-=margin;max+=margin;
        string P(double n)=>F(n,"F2");
        var b=new StringBuilder($"<svg viewBox='0 0 {width} {height}' role='img' aria-label='{H(title)}'>");
        for(int k=0;k<5;k++)
        {
            double y=top+plotHeight*k/4;
            b.Append($"<line x1='{P(left)}' y1='{P(y)}' x2='{P(left+plotWidth)}' y2='{P(y)}' stroke='#d8e6f3'/>"+
                $"<text x='5' y='{P(y+5)}' font-size='12' fill='#63809c'>{P(max-(max-min)*k/4)} {H(unit)}</text>");
        }
        var pts=string.Join(" ",values.Select((v,i)=>$"{P(left+(i+.5)*plotWidth/values.Count)},{P(top+(max-v)/(max-min)*plotHeight)}"));
        b.Append($"<polyline points='{pts}' fill='none' stroke='{color}' stroke-width='2.4'/>");
        for(int i=0;i<values.Count;i++)
        {
            double x=left+(i+.5)*plotWidth/values.Count,y=top+(max-values[i])/(max-min)*plotHeight;
            b.Append($"<circle cx='{P(x)}' cy='{P(y)}' r='3.5' fill='{color}'><title>配对{i+1}: {F(values[i],"F6")}{H(unit)}</title></circle>");
        }
        return b.Append("</svg>").ToString();
    }
    private static string BuildHtml(Ct08ReportData d)
    {
        var sb=new StringBuilder("<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><title>CT-08 正反路径回程差</title>");
        sb.Append("<style>body{font:14px 'Microsoft YaHei',sans-serif;max-width:1180px;margin:25px auto;padding:0 20px;color:#203b53;background:#f4f8fc}h1,h2{color:#216098}.card{border:1px solid #d6e5f1;border-radius:13px;padding:18px;margin:14px 0;background:#fff}table{width:100%;border-collapse:collapse;font-size:12px}th,td{border:1px solid #d8e4ee;padding:8px;text-align:right}th{background:#eaf3fa}td:first-child,th:first-child{text-align:left}svg{width:100%;height:auto}.muted{color:#5f7588}@media print{body{background:white}.card{break-inside:avoid}}</style></head><body>");
        sb.Append($"<h1>CT-08 · 正反路径回程差</h1><div class='card'><p><b>设备：</b>{H(d.DeviceNumber)}　<b>UID：</b>{H(d.UidHex)}</p><p><b>状态：</b>{H(d.State)}　<b>开始：</b>{H(d.StartedUtc)}　<b>结束：</b>{H(d.FinishedUtc)}</p><p>{H(d.FailureReason)}</p><p><b>结论：</b>{H(d.Conclusion)}</p></div>");
        sb.Append($"<div class='card'><h2>测试条件与参数来源</h2><p>内轴姿态：{H(d.Settings.InnerPositions)}；外轴目标：{H(d.Settings.OuterTargets)}；外轴接近偏移 ±{F(d.Settings.ApproachOffsetDeg)}°；每目标 {d.Settings.PairsPerTarget} 对。</p>"+
            $"<p>速度 {F(d.Settings.SpeedDps)}°/s，静置 {F(d.Settings.SettleSeconds)}s，采样 {F(d.Settings.SampleSeconds)}s；到位容差 {F(d.Settings.PositionToleranceDeg)}°；批准范围 [{F(d.Settings.AllowedMinDeg)},{F(d.Settings.AllowedMaxDeg)}]°。</p>"+
            $"<p>参考：{H(d.ReferenceModel)}，gravity_sign={d.GravitySign}；{H(d.InputScaleDescription)}</p>"+
            $"<p>ACC：{H(d.AccJsonFile)} (SHA256 {H(d.AccJsonSha256)})<br/>Gyro：{H(d.GyroJsonFile)} (SHA256 {H(d.GyroJsonSha256)})</p></div>");
        if(d.Metrics is { } m)
            sb.Append($"<div class='card'><h2>正反路径差异统计</h2><p><b>完成配对：</b>{m.CompletedPairs}　<b>有效真实帧：</b>{m.AcceptedFrames}</p>"+
                $"<p><b>ACC校正残差正反差 RMS：</b>{F(m.RmsHysteresisMg,"F4")} mg　<b>最大：</b>{F(m.MaxHysteresisMg,"F4")} mg</p>"+
                $"<p>正反误差三轴平均有符号差：{string.Join(" / ",m.MeanSignedErrorDifferenceMg.Select(x=>F(x,"F4")))} mg；方向差均值：{F(m.MeanDirectionHysteresisDeg,"F5")}°。</p>"+
                $"<p>外轴编码器正反到位差 RMS：{F(m.OuterFeedbackDifferenceRmsDeg,"F6")}°；内轴 RMS：{F(m.InnerFeedbackDifferenceRmsDeg,"F6")}°。芯片温度 {F(m.TemperatureMinC,"F2")}～{F(m.TemperatureMaxC,"F2")}℃。</p></div>");
        sb.Append("<div class='card'><h2>图一：各配对 ACC 参考残差差模长（mg）</h2>")
            .Append(Svg(d.Pairs.Select(p=>p.HysteresisMagnitudeMg).ToArray(),"回程误差模长","mg","#236eb4"))
            .Append("</div><div class='card'><h2>图二：外轴编码器正反到位差（°）</h2>")
            .Append(Svg(d.Pairs.Select(p=>p.OuterActualDifferenceDeg).ToArray(),"实际到位差","°","#c87425"))
            .Append("</div><div class='card'><h2>图三：正反路径 ACC X 有符号残差差（mg）</h2>")
            .Append(Svg(d.Pairs.Select(p=>p.HysteresisErrorMg[0]).ToArray(),"X轴残差差","mg","#8170b4")).Append("</div>");
        sb.Append("<div class='card'><h2>完整正反配对结果</h2><table><tr><th>配对</th><th>内轴目标°</th><th>外轴目标°</th><th>正/反原始访问</th><th>ΔX mg</th><th>ΔY mg</th><th>ΔZ mg</th><th>Δ矢量 mg</th><th>方向差°</th><th>外轴反馈差°</th><th>温差°C</th></tr>");
        foreach(var p in d.Pairs)
            sb.Append($"<tr><td>{p.PairIndex}</td><td>{F(p.InnerTargetDeg,"F3")}</td><td>{F(p.OuterTargetDeg,"F3")}</td><td>{p.ForwardIndex}/{p.ReverseIndex}</td>"+
                $"<td>{F(p.HysteresisErrorMg[0],"F4")}</td><td>{F(p.HysteresisErrorMg[1],"F4")}</td><td>{F(p.HysteresisErrorMg[2],"F4")}</td>"+
                $"<td>{F(p.HysteresisMagnitudeMg,"F4")}</td><td>{F(p.DirectionHysteresisDeg,"F5")}</td>"+
                $"<td>{F(p.OuterActualDifferenceDeg,"F6")}</td><td>{F(p.TemperatureDifferenceC,"F4")}</td></tr>");
        sb.Append("</table></div><div class='card'><h2>按目标角汇总</h2><table><tr><th>内轴°</th><th>外轴°</th><th>配对数</th><th>回程差 RMS mg</th><th>最大差 mg</th><th>方向差均值°</th></tr>");
        foreach(var t in d.Metrics?.ByTarget??[])
            sb.Append($"<tr><td>{F(t.InnerDeg,"F3")}</td><td>{F(t.OuterDeg,"F3")}</td><td>{t.Pairs}</td><td>{F(t.RmsMagnitudeMg,"F4")}</td><td>{F(t.MaxMagnitudeMg,"F4")}</td><td>{F(t.MeanAngleHysteresisDeg,"F5")}</td></tr>");
        sb.Append("</table></div><div class='card'><h2>测量定义、局限与追溯</h2><p>").Append(H(d.MeasurementCaveat))
            .Append("</p><p class='muted'>逐帧物理量和标定结果分开归档，未完成的正反半对不进入统计。所有判据需由研发人员确定，不自动判产品合格。</p></div></body></html>");
        return sb.ToString();
    }
    private static string Xml(string x)=>SecurityElement.Escape(x)??"";
    private static string Cell(int row,int col,object? value)
    {
        string cell=$"{(char)('A'+col-1)}{row}";
        if(value is null)return "";
        if(value is double or int or long)
            return $"<c r='{cell}'><v>{Convert.ToString(value,Ci)}</v></c>";
        return $"<c r='{cell}' t='inlineStr'><is><t>{Xml(value.ToString()??"")}</t></is></c>";
    }
    private static string Sheet(IEnumerable<object?[]> values)
    {
        var b=new StringBuilder("<?xml version='1.0' encoding='utf-8'?><worksheet xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'><sheetData>");
        int i=0;
        foreach(var row in values)
        {
            ++i;b.Append($"<row r='{i}'>");
            for(int j=0;j<row.Length;j++)b.Append(Cell(i,j+1,row[j]));
            b.Append("</row>");
        }
        return b.Append("</sheetData></worksheet>").ToString();
    }
    private static void Add(ZipArchive archive,string name,string content)
    {
        var e=archive.CreateEntry(name,CompressionLevel.Optimal);
        using var w=new StreamWriter(e.Open(),new UTF8Encoding(false));w.Write(content);
    }
    private static void BuildXlsx(string path,Ct08ReportData d)
    {
        var overview=new List<object?[]> {
            new object?[]{"字段","数值"},new object?[]{"测试","CT-08 正反路径回程差"},
            new object?[]{"设备",d.DeviceNumber},new object?[]{"UID",d.UidHex},
            new object?[]{"状态",d.State},new object?[]{"完成配对",d.Pairs.Count},
            new object?[]{"残差差RMS mg",d.Metrics?.RmsHysteresisMg},
            new object?[]{"最大路径差mg",d.Metrics?.MaxHysteresisMg},
            new object?[]{"外轴反馈差RMS°",d.Metrics?.OuterFeedbackDifferenceRmsDeg},
            new object?[]{"输入量程",d.InputScaleDescription},new object?[]{"ACC SHA256",d.AccJsonSha256},
            new object?[]{"Gyro SHA256",d.GyroJsonSha256},new object?[]{"结论",d.Conclusion}
        };
        var pairs=new List<object?[]> {new object?[]{"配对","轮次","内轴目标°","外轴目标°","正向访问","反向访问","ΔX mg","ΔY mg","ΔZ mg","Δ矢量 mg","方向差°","外轴反馈差°","内轴反馈差°","温差°C"}};
        foreach(var p in d.Pairs)
            pairs.Add(new object?[]{p.PairIndex,p.Cycle,p.InnerTargetDeg,p.OuterTargetDeg,p.ForwardIndex,p.ReverseIndex,
                p.HysteresisErrorMg[0],p.HysteresisErrorMg[1],p.HysteresisErrorMg[2],p.HysteresisMagnitudeMg,
                p.DirectionHysteresisDeg,p.OuterActualDifferenceDeg,p.InnerActualDifferenceDeg,p.TemperatureDifferenceC});
        using var zip=ZipFile.Open(path,ZipArchiveMode.Create);
        Add(zip,"[Content_Types].xml","<?xml version='1.0' encoding='utf-8'?><Types xmlns='http://schemas.openxmlformats.org/package/2006/content-types'>"+
            "<Default Extension='rels' ContentType='application/vnd.openxmlformats-package.relationships+xml'/>"+
            "<Default Extension='xml' ContentType='application/xml'/>"+
            "<Override PartName='/xl/workbook.xml' ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml'/>"+
            "<Override PartName='/xl/worksheets/sheet1.xml' ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml'/>"+
            "<Override PartName='/xl/worksheets/sheet2.xml' ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml'/></Types>");
        Add(zip,"_rels/.rels","<?xml version='1.0' encoding='utf-8'?><Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'>"+
            "<Relationship Id='rId1' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument' Target='xl/workbook.xml'/></Relationships>");
        Add(zip,"xl/workbook.xml","<?xml version='1.0' encoding='utf-8'?><workbook xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main' xmlns:r='http://schemas.openxmlformats.org/officeDocument/2006/relationships'>"+
            "<sheets><sheet name='Summary' sheetId='1' r:id='rId1'/><sheet name='Pairs' sheetId='2' r:id='rId2'/></sheets></workbook>");
        Add(zip,"xl/_rels/workbook.xml.rels","<?xml version='1.0' encoding='utf-8'?><Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'>"+
            "<Relationship Id='rId1' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet' Target='worksheets/sheet1.xml'/>"+
            "<Relationship Id='rId2' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet' Target='worksheets/sheet2.xml'/></Relationships>");
        Add(zip,"xl/worksheets/sheet1.xml",Sheet(overview));
        Add(zip,"xl/worksheets/sheet2.xml",Sheet(pairs));
    }
}
