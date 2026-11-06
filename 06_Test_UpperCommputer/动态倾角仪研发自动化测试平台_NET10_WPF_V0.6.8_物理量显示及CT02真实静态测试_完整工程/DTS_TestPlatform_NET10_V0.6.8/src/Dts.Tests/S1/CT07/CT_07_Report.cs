using System.Globalization;
using System.IO.Compression;
using System.Net;
using System.Security;
using System.Text;
using System.Text.Json;

namespace Dts.Tests.S1.CT07;

/// <summary>Real visit evidence and publication: JSON + CSV + self-contained HTML/SVG + native XLSX.</summary>
public static class Ct07Report
{
    private static readonly CultureInfo Ci=CultureInfo.InvariantCulture;
    private static readonly JsonSerializerOptions Options=new() {WriteIndented=true};
    private static string F(double x,string fmt="F5")=>x.ToString(fmt,Ci);
    private static string H(string? s)=>WebUtility.HtmlEncode(s??"");
    private static string Q(string? s)=>"\""+(s??"").Replace("\"","\"\"")+"\"";

    public static async Task SaveCheckpointAsync(string folder,Ct07ReportData data,CancellationToken ct)
    {
        string path=Path.Combine(folder,"CT-07_checkpoint.json");
        string tmp=path+".tmp";
        await File.WriteAllTextAsync(tmp,JsonSerializer.Serialize(data,Options),new UTF8Encoding(false),ct);
        File.Move(tmp,path,true);
    }
    public static async Task<IReadOnlyList<string>> ExportAsync(string folder,Ct07ReportData data,CancellationToken ct)
    {
        Directory.CreateDirectory(folder);
        string json=Path.Combine(folder,"CT-07_result.json"),
               csv=Path.Combine(folder,"CT-07_visits.csv"),
               html=Path.Combine(folder,"CT-07_report.html"),
               xlsx=Path.Combine(folder,"CT-07_report.xlsx");
        await SaveCheckpointAsync(folder,data,ct);
        await File.WriteAllTextAsync(json,JsonSerializer.Serialize(data,Options),new UTF8Encoding(false),ct);
        var rows=new List<string> {"round,approach,inner_depart_deg,outer_depart_deg,inner_target_deg,outer_target_deg,inner_actual_deg,outer_actual_deg,acc_x_g,acc_y_g,acc_z_g,acc_std_x_g,acc_std_y_g,acc_std_z_g,gyro_x_dps,gyro_y_dps,gyro_z_dps,gyro_std_x_dps,gyro_std_y_dps,gyro_std_z_dps,reference_error_mg,direction_error_deg,acc_norm_g,chip_temp_c,accepted_frames,total_frames,rejection_fraction,physical_csv,corrected_csv"};
        foreach(var v in data.Visits)
        {
            var cells=new List<string> {v.Index.ToString(Ci),Q(v.Approach),F(v.InnerDepartDeg,"G17"),F(v.OuterDepartDeg,"G17"),
                F(v.InnerTargetDeg,"G17"),F(v.OuterTargetDeg,"G17"),F(v.InnerActualDeg,"G17"),F(v.OuterActualDeg,"G17")};
            cells.AddRange(v.AccCorrectedMeanG.Select(x=>F(x,"G17")));
            cells.AddRange(v.AccWithinStdG.Select(x=>F(x,"G17")));
            cells.AddRange(v.GyroCorrectedMeanDps.Select(x=>F(x,"G17")));
            cells.AddRange(v.GyroWithinStdDps.Select(x=>F(x,"G17")));
            cells.AddRange(new[]{v.VectorReferenceErrorMg,v.DirectionReferenceErrorDeg,v.AccNormG,v.MeanTemperatureC}.Select(x=>F(x,"G17")));
            cells.Add(v.AcceptedSamples.ToString(Ci));cells.Add(v.TotalSamples.ToString(Ci));
            cells.Add(F(v.RejectedFraction,"G17"));cells.Add(Q(v.PhysicalCsv));cells.Add(Q(v.CorrectedCsv));
            rows.Add(string.Join(",",cells));
        }
        await File.WriteAllLinesAsync(csv,rows,new UTF8Encoding(true),ct);
        await File.WriteAllTextAsync(html,BuildHtml(data),new UTF8Encoding(false),ct);
        BuildXlsx(xlsx,data);
        return new[]{json,csv,html,xlsx,Path.Combine(folder,"CT-07_checkpoint.json")};
    }

    private static string Svg(IReadOnlyList<double> values,string title,string suffix,string color)
    {
        if(values.Count==0)return "<p>暂无已完成轮次</p>";
        const double w=860,h=265,left=70,top=25,pw=755,ph=192;
        double min=values.Min(),max=values.Max();
        double margin=Math.Max((max-min)*0.2,0.005);min-=margin;max+=margin;
        string P(double x)=>F(x,"F2");
        var b=new StringBuilder($"<svg viewBox='0 0 {w} {h}' role='img' aria-label='{H(title)}'>");
        for(int k=0;k<=4;k++)
        {
            double y=top+ph*k/4;
            b.Append($"<line x1='{P(left)}' y1='{P(y)}' x2='{P(left+pw)}' y2='{P(y)}' stroke='#dae6f2'/>"+
                     $"<text x='6' y='{P(y+4)}' fill='#647c95' font-size='12'>{P(max-(max-min)*k/4)}{H(suffix)}</text>");
        }
        string pts=string.Join(" ",values.Select((v,i)=>$"{P(left+(i+.5)*pw/values.Count)},{P(top+(max-v)/(max-min)*ph)}"));
        b.Append($"<polyline points='{pts}' fill='none' stroke='{color}' stroke-width='2.5'/>");
        for(int i=0;i<values.Count;i++)
        {
            double x=left+(i+.5)*pw/values.Count,y=top+(max-values[i])/(max-min)*ph;
            b.Append($"<circle cx='{P(x)}' cy='{P(y)}' r='4' fill='{color}'><title>第{i+1}轮：{F(values[i],"F6")}{H(suffix)}</title></circle>");
            b.Append($"<text x='{P(x)}' y='252' text-anchor='middle' fill='#60758a' font-size='11'>{i+1}</text>");
        }
        return b.Append("</svg>").ToString();
    }
    private static string BuildHtml(Ct07ReportData d)
    {
        var sb=new StringBuilder("<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'/><title>CT-07 同姿态测量重复性</title>");
        sb.Append("<style>body{font:14px 'Microsoft YaHei',sans-serif;color:#19354f;background:#f4f8fc;max-width:1180px;margin:22px auto;padding:0 18px}h1,h2{color:#195b94}.card{background:#fff;border:1px solid #dbe7f1;padding:19px;border-radius:12px;margin:16px 0}table{width:100%;border-collapse:collapse;font-size:12px}td,th{border:1px solid #d7e4f0;padding:8px;text-align:right}th:first-child,td:first-child{text-align:left}th{background:#eaf2fa}.muted{color:#63788a}svg{max-width:100%;height:auto}@media print{body{background:white}.card{break-inside:avoid}}</style></head><body>");
        sb.Append("<h1>CT-07 · 同姿态测量重复性</h1>");
        sb.Append($"<div class='card'><p><b>设备：</b>{H(d.DeviceNumber)}　<b>完整UID：</b>{H(d.UidHex)}　<b>状态：</b>{H(d.State)}</p><p>开始：{H(d.StartedUtc)}<br/>结束：{H(d.FinishedUtc)}</p><p>{H(d.FailureReason)}</p><p>{H(d.Conclusion)}</p></div>");
        sb.Append($"<div class='card'><h2>参数与校准溯源</h2><p>目标：内轴 {F(d.Settings.InnerTargetDeg)}° / 外轴 {F(d.Settings.OuterTargetDeg)}°；离开幅度：内轴 ±{F(d.Settings.InnerExcursionDeg)}°、外轴 ±{F(d.Settings.OuterExcursionDeg)}°；计划 {d.Settings.RepeatCount} 轮，完成 {d.Visits.Count} 轮。"+
            $"{(d.Settings.AlternateApproach?"交替方向回位":"相同方向回位")}。</p>"+
            $"<p>运动速度 {F(d.Settings.SpeedDps)}°/s；静置 {F(d.Settings.SettleSeconds)}s；每轮采集 {F(d.Settings.SampleSeconds)}s；到位容差 {F(d.Settings.PositionToleranceDeg)}°；声明允许行程 [{F(d.Settings.AllowedMinDeg)},{F(d.Settings.AllowedMaxDeg)}]°。</p>"+
            $"<p>参考姿态模型：{H(d.ReferenceModel)}，gravity_sign={d.GravitySign}。输入换算：{H(d.InputScaleDescription)}</p>"+
            $"<p>ACC：{H(d.AccJsonFile)}<br/>SHA256：{H(d.AccJsonSha256)}<br/>Gyro：{H(d.GyroJsonFile)}<br/>SHA256：{H(d.GyroJsonSha256)}</p></div>");
        if(d.Metrics is { } m)
            sb.Append($"<div class='card'><h2>重复性结果（跨轮均值统计）</h2>"+
                $"<p><b>ACC三维矢量离散RMS：</b>{F(m.AccBetweenVectorRmsMg,"F3")}mg　<b>最大偏离：</b>{F(m.AccBetweenMaxVectorMg,"F3")}mg　"+
                $"<b>角度离散RMS：</b>{F(m.DirectionBetweenRmsDeg,"F5")}°　<b>最大角度偏离：</b>{F(m.DirectionBetweenMaxDeg,"F5")}°</p>"+
                $"<p>跨轮ACC X/Y/Z 标准差：{string.Join(" / ",m.AccBetweenStdMg.Select(x=>F(x,"F4")))} mg；"+
                $"轮内ACC池化标准差：{string.Join(" / ",m.AccPooledWithinStdMg.Select(x=>F(x,"F4")))} mg。</p>"+
                $"<p>跨轮Gyro X/Y/Z零速均值标准差：{string.Join(" / ",m.GyroBetweenStdDps.Select(x=>F(x,"F5")))}°/s；"+
                $"轮内Gyro池化标准差：{string.Join(" / ",m.GyroPooledWithinStdDps.Select(x=>F(x,"F5")))}°/s。</p>"+
                $"<p>实际内/外轴回位标准差：{F(m.InnerReturnStdDeg,"F5")}° / {F(m.OuterReturnStdDeg,"F5")}°；芯片温度：{F(m.TemperatureMinC,"F2")}～{F(m.TemperatureMaxC,"F2")}℃。</p></div>");
        sb.Append("<div class='card'><h2>图一 · 各轮 ACC 相对于转台参考矢量的误差（mg）</h2>")
          .Append(Svg(d.Visits.Select(v=>v.VectorReferenceErrorMg).ToArray(),"ACC参考矢量误差","mg","#136ec4"))
          .Append("</div><div class='card'><h2>图二 · 外轴回位实际反馈偏差（°，相对目标）</h2>")
          .Append(Svg(d.Visits.Select(v=>Ct07Algorithm.Wrap(v.OuterActualDeg-d.Settings.OuterTargetDeg)).ToArray(),"外轴回位偏差","°","#c47720"))
          .Append("</div><div class='card'><h2>图三 · Gyro 校正后 X 轴静态均值（°/s）</h2>")
          .Append(Svg(d.Visits.Select(v=>v.GyroCorrectedMeanDps[0]).ToArray(),"陀螺仪静态均值","°/s","#7f61b2")).Append("</div>");
        sb.Append("<div class='card'><h2>逐轮真实采样汇总</h2><table><tr><th>轮次</th><th>返回方向</th><th>内轴°</th><th>外轴°</th><th>ACC X/Y/Z (g)</th><th>Gyro X/Y/Z (°/s)</th><th>参考误差 mg</th><th>方向差 °</th><th>有效帧</th></tr>");
        foreach(var v in d.Visits)
            sb.Append($"<tr><td>{v.Index}</td><td>{H(v.Approach)}</td><td>{F(v.InnerActualDeg,"F4")}</td><td>{F(v.OuterActualDeg,"F4")}</td>"+
                $"<td>{string.Join(" / ",v.AccCorrectedMeanG.Select(x=>F(x,"F5")))}</td>"+
                $"<td>{string.Join(" / ",v.GyroCorrectedMeanDps.Select(x=>F(x,"F5")))}</td>"+
                $"<td>{F(v.VectorReferenceErrorMg,"F3")}</td><td>{F(v.DirectionReferenceErrorDeg,"F5")}</td><td>{v.AcceptedSamples}</td></tr>");
        sb.Append("</table></div><div class='card'><h2>解释与安全说明</h2><p>").Append(H(d.MeasurementCaveat))
          .Append("</p><p class='muted'>只有采集到真实FIFO并通过数据检查的轮次才计算；CSV保留逐帧值和实际转台反馈。"+
                  "方向离散度是相对于各轮平均方向的角度离散，不是绝对倾角精度。标定参数只读，不自动生成产品 PASS。</p></div></body></html>");
        return sb.ToString();
    }

    // No extra package: write a minimal, standards-based XLSX containing Overview + Visits sheets.
    private static string Xml(string s)=>SecurityElement.Escape(s)??"";
    private static string Cell(int row,int col,object? value)
    {
        string address=$"{(char)('A'+col-1)}{row}";
        if(value is null) return "";
        if(value is double or int or long)
            return $"<c r='{address}'><v>{Convert.ToString(value,Ci)}</v></c>";
        return $"<c r='{address}' t='inlineStr'><is><t>{Xml(value.ToString()??"")}</t></is></c>";
    }
    private static string Sheet(IEnumerable<object?[]> data)
    {
        var sb=new StringBuilder("<?xml version='1.0' encoding='utf-8'?><worksheet xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'><sheetData>");
        int row=0;
        foreach(var values in data)
        {
            ++row;sb.Append($"<row r='{row}'>");
            for(int col=0;col<values.Length;col++) sb.Append(Cell(row,col+1,values[col]));
            sb.Append("</row>");
        }
        return sb.Append("</sheetData></worksheet>").ToString();
    }
    private static void Add(ZipArchive zip,string entry,string content)
    {
        var e=zip.CreateEntry(entry,CompressionLevel.Optimal);
        using var writer=new StreamWriter(e.Open(),new UTF8Encoding(false));
        writer.Write(content);
    }
    private static void BuildXlsx(string path,Ct07ReportData d)
    {
        var overview=new List<object?[]> {
            new object?[]{"字段","数值"},new object?[]{"测试编号","CT-07"},
            new object?[]{"设备编号",d.DeviceNumber},new object?[]{"完整UID",d.UidHex},
            new object?[]{"状态",d.State},new object?[]{"失败原因",d.FailureReason},
            new object?[]{"完成轮数",d.Visits.Count},
            new object?[]{"跨轮ACC矢量RMS(mg)",d.Metrics?.AccBetweenVectorRmsMg},
            new object?[]{"角度离散RMS(deg)",d.Metrics?.DirectionBetweenRmsDeg},
            new object?[]{"内轴回位标准差(deg)",d.Metrics?.InnerReturnStdDeg},
            new object?[]{"外轴回位标准差(deg)",d.Metrics?.OuterReturnStdDeg},
            new object?[]{"ACC SHA256",d.AccJsonSha256},new object?[]{"Gyro SHA256",d.GyroJsonSha256},
            new object?[]{"输入量程说明",d.InputScaleDescription},new object?[]{"结论",d.Conclusion}
        };
        var visits=new List<object?[]> { new object?[]{"轮次","回位方向","内轴实际°","外轴实际°","ACC X g","ACC Y g","ACC Z g","Gyro X °/s","Gyro Y °/s","Gyro Z °/s","参考矢量误差mg","参考方向误差°","有效帧","总帧数","温度°C"} };
        foreach(var v in d.Visits)
            visits.Add(new object?[]{v.Index,v.Approach,v.InnerActualDeg,v.OuterActualDeg,
                v.AccCorrectedMeanG[0],v.AccCorrectedMeanG[1],v.AccCorrectedMeanG[2],
                v.GyroCorrectedMeanDps[0],v.GyroCorrectedMeanDps[1],v.GyroCorrectedMeanDps[2],
                v.VectorReferenceErrorMg,v.DirectionReferenceErrorDeg,v.AcceptedSamples,v.TotalSamples,
                v.MeanTemperatureC});
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
            "<sheets><sheet name='Summary' sheetId='1' r:id='rId1'/><sheet name='Visits' sheetId='2' r:id='rId2'/></sheets></workbook>");
        Add(zip,"xl/_rels/workbook.xml.rels","<?xml version='1.0' encoding='utf-8'?><Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'>"+
            "<Relationship Id='rId1' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet' Target='worksheets/sheet1.xml'/>"+
            "<Relationship Id='rId2' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet' Target='worksheets/sheet2.xml'/></Relationships>");
        Add(zip,"xl/worksheets/sheet1.xml",Sheet(overview));
        Add(zip,"xl/worksheets/sheet2.xml",Sheet(visits));
    }
}
