using System.Globalization;
using System.IO.Compression;
using System.Net;
using System.Security;
using System.Text;
using System.Text.Json;

namespace Dts.Tests.S1.CT06;

/// <summary>CT-06 报告：JSON、逐点CSV、残余耦合矩阵、带SVG的HTML、原生XLSX。</summary>
public static class Ct06Report
{
    private static readonly CultureInfo Ci = CultureInfo.InvariantCulture;
    private static readonly JsonSerializerOptions Json = new() { WriteIndented = true };
    private static string F(double x, string format = "F5") => x.ToString(format, Ci);
    private static string H(string? s) => WebUtility.HtmlEncode(s ?? "");
    private static string Q(string? s) => "\"" + (s ?? "").Replace("\"", "\"\"") + "\"";

    public static async Task SaveCheckpointAsync(string directory, Ct06ReportData data, CancellationToken ct)
    {
        string path = Path.Combine(directory, "CT-06_checkpoint.json");
        string temp = path + ".tmp";
        await File.WriteAllTextAsync(temp, JsonSerializer.Serialize(data, Json), new UTF8Encoding(false), ct);
        File.Move(temp, path, true);
    }

    public static async Task<IReadOnlyList<string>> ExportAsync(string directory, Ct06ReportData data, CancellationToken ct)
    {
        Directory.CreateDirectory(directory);
        string json = Path.Combine(directory,"CT-06_result.json");
        string pointCsv = Path.Combine(directory,"CT-06_points.csv");
        string couplingCsv = Path.Combine(directory,"CT-06_coupling.csv");
        string html = Path.Combine(directory,"CT-06_report.html");
        string xlsx = Path.Combine(directory,"CT-06_report.xlsx");
        await SaveCheckpointAsync(directory,data,ct);
        await File.WriteAllTextAsync(json,JsonSerializer.Serialize(data,Json),new UTF8Encoding(false),ct);
        var rows = new List<string> {
            "index,label,inner_target_deg,outer_target_deg,inner_actual_deg,outer_actual_deg,reference_x_g,reference_y_g,reference_z_g,corrected_x_g,corrected_y_g,corrected_z_g,error_x_g,error_y_g,error_z_g,transverse_error_mg,parallel_error_mg,vector_error_mg,direction_error_deg,norm_error_mg,accepted_frames,total_frames,rejected_fraction,chip_temp_c,physical_csv,corrected_csv"
        };
        foreach(var p in data.Points)
        {
            var v = new List<string> {p.Index.ToString(Ci),Q(p.Label),F(p.InnerCommandDeg,"G17"),F(p.OuterCommandDeg,"G17"),F(p.InnerActualDeg,"G17"),F(p.OuterActualDeg,"G17")};
            v.AddRange(p.ReferenceG.Select(x=>F(x,"G17")));
            v.AddRange(p.CorrectedMeanG.Select(x=>F(x,"G17")));
            v.AddRange(p.AxisErrorG.Select(x=>F(x,"G17")));
            v.AddRange(new [] {Ct06Algorithm.TransverseErrorMg(p),Ct06Algorithm.ParallelErrorG(p)*1000,p.VectorErrorG*1000,p.DirectionErrorDeg,p.NormErrorG*1000}.Select(x=>F(x,"G17")));
            v.Add(p.AcceptedSamples.ToString(Ci));v.Add(p.TotalSamples.ToString(Ci));v.Add(F(p.RejectedFraction,"G17"));
            v.Add(F(p.MeanTemperatureC,"G17"));v.Add(Q(p.RawCsv));v.Add(Q(p.CorrectedCsv));
            rows.Add(string.Join(",",v));
        }
        await File.WriteAllLinesAsync(pointCsv,rows,new UTF8Encoding(true),ct);
        var fitRows = new List<string> {"output_axis,offset_mg,coeff_from_ref_X_percent,coeff_from_ref_Y_percent,coeff_from_ref_Z_percent,residual_rmse_mg"};
        if(data.CouplingFit is { } fit)
            for(int axis=0;axis<3;axis++)
                fitRows.Add(string.Join(",",new[]{"XYZ"[axis].ToString(),F(fit.BiasG[axis]*1000,"G17")}
                    .Concat(fit.ResidualMatrix[axis].Select(x=>F(x*100,"G17")))
                    .Concat(new[]{F(fit.AxisResidualRmseMg[axis],"G17")})));
        await File.WriteAllLinesAsync(couplingCsv,fitRows,new UTF8Encoding(true),ct);
        await File.WriteAllTextAsync(html,BuildHtml(data),new UTF8Encoding(false),ct);
        WriteWorkbook(xlsx,data);
        return new[] {json,pointCsv,couplingCsv,html,xlsx,Path.Combine(directory,"CT-06_checkpoint.json")};
    }

    private static string TrendChart(IReadOnlyList<Ct06PointResult> points)
    {
        if(points.Count==0)return "<p>尚无完成工位。</p>";
        const double w=900,h=270,left=65,top=20,pw=810,ph=210;
        var values=points.Select(Ct06Algorithm.TransverseErrorMg).ToArray();
        double max=Math.Max(0.1,values.Max()*1.15);
        var sb=new StringBuilder($"<svg viewBox='0 0 {w} {h}' xmlns='http://www.w3.org/2000/svg' role='img' aria-label='交叉轴横向误差趋势mg'>");
        for(int i=0;i<=4;i++)
        {
            double y=top+ph*i/4d;
            sb.Append($"<line x1='{F(left)}' y1='{F(y)}' x2='{F(left+pw)}' y2='{F(y)}' stroke='#dde8f3'/>"+
                $"<text x='8' y='{F(y+4)}' font-size='12' fill='#526d89'>{F(max*(1-i/4d),"F2")}</text>");
        }
        string path=string.Join(" ",values.Select((v,i)=>$"{F(left+pw*(i+.5)/values.Length,"F2")},{F(top+ph*(1-v/max),"F2")}"));
        sb.Append($"<polyline fill='none' stroke='#1769b2' stroke-width='2.5' points='{path}'/>");
        for(int i=0;i<values.Length;i++)
        {
            double x=left+pw*(i+.5)/values.Length,y=top+ph*(1-values[i]/max);
            sb.Append($"<circle cx='{F(x,"F2")}' cy='{F(y,"F2")}' r='3.2' fill='#1769b2'><title>点{i+1}：{F(values[i],"F3")}mg</title></circle>");
            if(i % Math.Max(1,(int)Math.Ceiling(values.Length/20d))==0)
                sb.Append($"<text x='{F(x,"F2")}' y='253' text-anchor='middle' font-size='11' fill='#647c95'>{i+1}</text>");
        }
        return sb.Append("</svg>").ToString();
    }

    private static string MatrixTable(Ct06CouplingFit? fit)
    {
        if(fit is null)return "<p>有效姿态不足或几何欠激励，残余耦合矩阵不可辨识。</p>";
        var sb=new StringBuilder("<table><thead><tr><th>误差输出</th><th>零偏残差 mg</th><th>参考 X → 输出 (%)</th><th>参考 Y → 输出 (%)</th><th>参考 Z → 输出 (%)</th><th>拟合残差 RMSE mg</th></tr></thead><tbody>");
        for(int i=0;i<3;i++)
        {
            sb.Append($"<tr><th>{"XYZ"[i]}</th><td>{F(fit.BiasG[i]*1000,"F4")}</td>");
            for(int j=0;j<3;j++)
                sb.Append($"<td class='{(i==j?"diagonal":"cross")}'>{F(fit.ResidualMatrix[i][j]*100,"F5")}</td>");
            sb.Append($"<td>{F(fit.AxisResidualRmseMg[i],"F4")}</td></tr>");
        }
        return sb.Append("</tbody></table>").ToString();
    }

    private static string BuildHtml(Ct06ReportData data)
    {
        var sb=new StringBuilder("<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'/><title>CT-06 复合姿态与交叉轴误差</title>");
        sb.Append("<style>body{font:14px 'Microsoft YaHei',sans-serif;color:#183650;background:#f4f8fc;max-width:1180px;margin:24px auto;padding:0 18px}h1,h2{color:#195b94}.card{background:white;border:1px solid #dbe7f1;padding:20px;border-radius:12px;margin:16px 0}table{border-collapse:collapse;width:100%;font-size:12px}th,td{border:1px solid #dae5f0;padding:8px;text-align:right}th:first-child,td:first-child{text-align:left}th{background:#eaf2fa}.cross{background:#fff0d7}.diagonal{background:#e7f5e8}.muted{color:#667c93}.bad{color:#b04d30}svg{max-width:100%;height:auto}@media print{body{background:white}.card{break-inside:avoid}}</style></head><body>");
        sb.Append("<h1>CT-06 复合姿态与交叉轴误差 · 研发诊断报告</h1>");
        sb.Append($"<div class='card'><b>设备：</b>{H(data.DeviceNumber)}　<b>UID：</b>{H(data.UidHex)}　<b>状态：</b>{H(data.State)}<p>开始 UTC：{H(data.StartedUtc)}<br/>结束 UTC：{H(data.FinishedUtc)}</p><p class='bad'>{H(data.FailureReason)}</p><p>{H(data.Conclusion)}</p></div>");
        sb.Append($"<div class='card'><h2>参数与溯源</h2><p>计划：{H(data.Settings.PlanKind)}；完成 {data.Points.Count} 工位；计划不同重力方向 {data.PlannedUniqueGravityDirections}；历史重合 {data.HistoricalGravityOverlaps?.ToString() ?? "未知"}。</p>");
        sb.Append($"<p>内轴 {data.Settings.InnerDivisions} 等分/起始 {F(data.Settings.InnerStartDeg)}°；外轴 {data.Settings.OuterDivisions} 等分/起始 {F(data.Settings.OuterStartDeg)}°。速度 {F(data.Settings.SpeedDps)}°/s；静置 {F(data.Settings.SettleSeconds)}s；采样 {F(data.Settings.SampleSeconds)}s；到位容差 {F(data.Settings.PositionToleranceDeg)}°；声明行程 [{F(data.Settings.AllowedMinDeg)},{F(data.Settings.AllowedMaxDeg)}]°。</p>");
        sb.Append($"<p>参考模型：{H(data.ReferenceModel)}；输入换算：{H(data.InputScaleDescription)}</p><p>ACC：{H(data.AccJsonFile)}<br/>SHA256：{H(data.AccJsonSha256)}<br/>Gyro：{H(data.GyroJsonFile)}<br/>SHA256：{H(data.GyroJsonSha256)}</p></div>");
        if(data.Metrics is { } m)
            sb.Append($"<div class='card'><h2>汇总</h2><p><b>横向误差 RMSE：</b>{F(m.TransverseRmseMg,"F3")} mg　<b>最大横向误差：</b>{F(m.TransverseMaxMg,"F3")} mg　<b>纵向 RMSE：</b>{F(m.ParallelRmseMg,"F3")} mg　<b>方向 RMSE：</b>{F(m.DirectionRmseDeg,"F5")}°　有效帧：{m.SampleCount}</p></div>");
        sb.Append("<div class='card'><h2>逐点交叉轴横向误差 (mg)</h2>").Append(TrendChart(data.Points)).Append("</div>");
        sb.Append("<div class='card'><h2>残余3×3耦合矩阵（系统级诊断）</h2>").Append(MatrixTable(data.CouplingFit));
        if(data.CouplingFit is { } fit)
            sb.Append($"<p>非对角绝对最大值：{F(fit.MaxOffDiagonalPercent,"F5")}%；联合拟合残差 RMSE：{F(fit.FitRmseMg,"F4")}mg。</p>");
        sb.Append("<p class='muted'>模型：e = a_cal - g_reference = b + B·g_reference。矩阵元素是按参考重力各方向拟合得到的残余误差系数，非对角元素属于系统级交叉轴代理。它可能含有安装旋转、转台定位、参考坐标系和实际IMU误差，不能只据此判定芯片固有交叉轴灵敏度；此诊断不重新生成或修改ACC标定参数。</p></div>");
        sb.Append("<div class='card'><h2>逐姿态实测结果</h2><table><tr><th>#</th><th>内轴°</th><th>外轴°</th><th>参考 X/Y/Z (g)</th><th>误差 X/Y/Z (mg)</th><th>横向 mg</th><th>纵向 mg</th><th>方向°</th><th>有效帧</th></tr>");
        foreach(var p in data.Points)
            sb.Append($"<tr><td>{p.Index}</td><td>{F(p.InnerActualDeg,"F2")}</td><td>{F(p.OuterActualDeg,"F2")}</td>"+
                $"<td>{string.Join(" / ",p.ReferenceG.Select(x=>F(x,"F4")))}</td><td>{string.Join(" / ",p.AxisErrorG.Select(x=>F(x*1000,"F3")))}</td>"+
                $"<td>{F(Ct06Algorithm.TransverseErrorMg(p),"F3")}</td><td>{F(Ct06Algorithm.ParallelErrorG(p)*1000,"F3")}</td><td>{F(p.DirectionErrorDeg,"F5")}</td><td>{p.AcceptedSamples}</td></tr>");
        sb.Append("</table></div><div class='card'><h2>解释与安全</h2><p>").Append(H(data.MotionSafetyNote)).Append("</p><p>报告只对真实已完成的姿态点做统计。独立姿态、转台实际角度、UID、输入量程和逐帧CSV均保存；中止时保存部分报告。无明确验收标准和计量溯源时结论为待验收，不自动给出PASS。</p></div></body></html>");
        return sb.ToString();
    }

    // A self-contained .xlsx writer. No Excel COM, NuGet or installer dependency.
    private static string Xml(string s) => SecurityElement.Escape(s) ?? "";
    private static string Col(int i)
    {
        string name="";
        for(int v=i;v>0;v=(v-1)/26)name=(char)('A'+(v-1)%26)+name;
        return name;
    }
    private static string Cell(int r,int c,object? v)
    {
        string addr=Col(c)+r;
        if(v is int or long or double or float)
            return $"<c r='{addr}'><v>{Convert.ToString(v,Ci)}</v></c>";
        return $"<c r='{addr}' t='inlineStr'><is><t>{Xml(v?.ToString()??"")}</t></is></c>";
    }
    private static string Sheet(IEnumerable<object?[]> lines)
    {
        var s=new StringBuilder("<?xml version='1.0' encoding='utf-8'?><worksheet xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'><sheetData>");
        int r=0;
        foreach(var line in lines)
        {
            r++;s.Append($"<row r='{r}'>");
            for(int c=0;c<line.Length;c++)s.Append(Cell(r,c+1,line[c]));
            s.Append("</row>");
        }
        return s.Append("</sheetData></worksheet>").ToString();
    }
    private static void Add(ZipArchive zip,string name,string body)
    {
        var entry=zip.CreateEntry(name,CompressionLevel.Optimal);
        using var w=new StreamWriter(entry.Open(),new UTF8Encoding(false));w.Write(body);
    }
    private static void WriteWorkbook(string path,Ct06ReportData data)
    {
        var summary=new List<object?[]> {
            new object?[]{"字段","数值"}, new object?[]{"测试",data.TestId},new object?[]{"设备",data.DeviceNumber},
            new object?[]{"UID",data.UidHex},new object?[]{"状态",data.State},new object?[]{"原因",data.FailureReason},
            new object?[]{"计划",data.Settings.PlanKind},new object?[]{"完成点数",data.Points.Count},
            new object?[]{"横向RMSE(mg)",data.Metrics?.TransverseRmseMg},
            new object?[]{"最大横向误差(mg)",data.Metrics?.TransverseMaxMg},
            new object?[]{"纵向RMSE(mg)",data.Metrics?.ParallelRmseMg},
            new object?[]{"方向RMSE(deg)",data.Metrics?.DirectionRmseDeg},
            new object?[]{"最大非对角残差(%)",data.CouplingFit?.MaxOffDiagonalPercent},
            new object?[]{"ACC文件",data.AccJsonFile},new object?[]{"ACC SHA256",data.AccJsonSha256},
            new object?[]{"Gyro文件",data.GyroJsonFile},new object?[]{"Gyro SHA256",data.GyroJsonSha256},
            new object?[]{"量程换算",data.InputScaleDescription},new object?[]{"结论",data.Conclusion}
        };
        var points=new List<object?[]> {new object?[]{"#","内轴目标(°)","外轴目标(°)","内轴实测(°)","外轴实测(°)","参考X(g)","参考Y(g)","参考Z(g)","校正X(g)","校正Y(g)","校正Z(g)","误差X(mg)","误差Y(mg)","误差Z(mg)","横向误差(mg)","纵向误差(mg)","方向误差(°)","有效帧"}};
        foreach(var p in data.Points)
        {
            var v=new List<object?>{p.Index,p.InnerCommandDeg,p.OuterCommandDeg,p.InnerActualDeg,p.OuterActualDeg};
            v.AddRange(p.ReferenceG.Cast<object?>());v.AddRange(p.CorrectedMeanG.Cast<object?>());
            v.AddRange(p.AxisErrorG.Select(x=>(object?)(x*1000)));
            v.Add(Ct06Algorithm.TransverseErrorMg(p));v.Add(Ct06Algorithm.ParallelErrorG(p)*1000);v.Add(p.DirectionErrorDeg);v.Add(p.AcceptedSamples);
            points.Add(v.ToArray());
        }
        var coupling=new List<object?[]>{new object?[]{"误差输出","拟合零偏(mg)","参考X→输出(%)","参考Y→输出(%)","参考Z→输出(%)","残差RMSE(mg)"}};
        if(data.CouplingFit is { } fit)
            for(int axis=0;axis<3;axis++)
                coupling.Add(new object?[]{"XYZ"[axis].ToString(),fit.BiasG[axis]*1000,
                    fit.ResidualMatrix[axis][0]*100,fit.ResidualMatrix[axis][1]*100,
                    fit.ResidualMatrix[axis][2]*100,fit.AxisResidualRmseMg[axis]});
        using var zip=ZipFile.Open(path,ZipArchiveMode.Create);
        Add(zip,"[Content_Types].xml","<?xml version='1.0' encoding='utf-8'?><Types xmlns='http://schemas.openxmlformats.org/package/2006/content-types'>"+
            "<Default Extension='rels' ContentType='application/vnd.openxmlformats-package.relationships+xml'/><Default Extension='xml' ContentType='application/xml'/>"+
            "<Override PartName='/xl/workbook.xml' ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml'/>"+
            "<Override PartName='/xl/worksheets/sheet1.xml' ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml'/>"+
            "<Override PartName='/xl/worksheets/sheet2.xml' ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml'/>"+
            "<Override PartName='/xl/worksheets/sheet3.xml' ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml'/></Types>");
        Add(zip,"_rels/.rels","<?xml version='1.0' encoding='utf-8'?><Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'>"+
            "<Relationship Id='rId1' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument' Target='xl/workbook.xml'/></Relationships>");
        Add(zip,"xl/workbook.xml","<?xml version='1.0' encoding='utf-8'?><workbook xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main' xmlns:r='http://schemas.openxmlformats.org/officeDocument/2006/relationships'>"+
            "<sheets><sheet name='Summary' sheetId='1' r:id='rId1'/><sheet name='Points' sheetId='2' r:id='rId2'/><sheet name='Coupling' sheetId='3' r:id='rId3'/></sheets></workbook>");
        Add(zip,"xl/_rels/workbook.xml.rels","<?xml version='1.0' encoding='utf-8'?><Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'>"+
            "<Relationship Id='rId1' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet' Target='worksheets/sheet1.xml'/>"+
            "<Relationship Id='rId2' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet' Target='worksheets/sheet2.xml'/>"+
            "<Relationship Id='rId3' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet' Target='worksheets/sheet3.xml'/></Relationships>");
        Add(zip,"xl/worksheets/sheet1.xml",Sheet(summary));
        Add(zip,"xl/worksheets/sheet2.xml",Sheet(points));
        Add(zip,"xl/worksheets/sheet3.xml",Sheet(coupling));
    }
}
