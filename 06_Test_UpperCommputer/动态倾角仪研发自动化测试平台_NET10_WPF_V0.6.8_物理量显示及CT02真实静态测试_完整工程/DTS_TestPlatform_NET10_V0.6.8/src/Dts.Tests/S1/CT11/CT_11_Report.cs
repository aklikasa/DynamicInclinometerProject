using System.Globalization;
using System.IO;
using System.IO.Compression;
using System.Net;
using System.Security;
using System.Text;
using System.Text.Json;

namespace Dts.Tests.S1.CT11;

public static class Ct11Report
{
    private static readonly CultureInfo Ci=CultureInfo.InvariantCulture;
    private static readonly JsonSerializerOptions Options=new() {WriteIndented=true};
    private static string F(double x,string fmt="F5")=>x.ToString(fmt,Ci);
    private static string H(string? s)=>WebUtility.HtmlEncode(s??"");
    private static string Q(string? s)=>"\""+(s??"").Replace("\"","\"\"")+"\"";

    public static async Task SaveCheckpointAsync(string folder,Ct11ReportData data,CancellationToken ct)
    {
        Directory.CreateDirectory(folder);
        string output=Path.Combine(folder,"CT-11_checkpoint.json"),tmp=output+".tmp";
        await File.WriteAllTextAsync(tmp,JsonSerializer.Serialize(data,Options),new UTF8Encoding(false),ct);
        File.Move(tmp,output,true);
    }
    public static async Task<IReadOnlyList<string>> ExportAsync(string folder,Ct11ReportData d,CancellationToken ct)
    {
        Directory.CreateDirectory(folder);
        string json=Path.Combine(folder,"CT-11_result.json"),
               summary=Path.Combine(folder,"CT-11_sweep_summary.csv"),
               coupling=Path.Combine(folder,"CT-11_coupling_fits.csv"),
               html=Path.Combine(folder,"CT-11_report.html"),
               excel=Path.Combine(folder,"CT-11_report.xlsx");
        await SaveCheckpointAsync(folder,d,ct);
        await File.WriteAllTextAsync(json,JsonSerializer.Serialize(d,Options),new UTF8Encoding(false),ct);
        var rows=new List<string>{"axis,direction,repeat,command_dps,reference_actual_dps,gyro_x_cal_dps,gyro_y_cal_dps,gyro_z_cal_dps,gyro_x_std_dps,gyro_y_std_dps,gyro_z_std_dps,main_axis_dps,main_axis_residual_dps,temperature_c,accepted_frames,total_frames,encoder_frames,evidence_csv"};
        foreach(var s in d.Sweeps)
        {
            var cells=new List<string>{s.Axis.ToString(),s.Direction.ToString(),s.Repetition.ToString(Ci),F(s.CommandSpeedDps,"G17"),F(s.ReferenceSignedDps,"G17")};
            cells.AddRange(s.GyroMeanDps.Select(x=>F(x,"G17")));
            cells.AddRange(s.GyroWithinStdDps.Select(x=>F(x,"G17")));
            cells.AddRange(new[]{s.MainAxisSignedDps,s.MainAxisResidualDps,s.MeanTemperatureC}.Select(x=>F(x,"G17")));
            cells.Add(s.AcceptedFrames.ToString(Ci));cells.Add(s.TotalFrames.ToString(Ci));cells.Add(s.EncoderFrames.ToString(Ci));
            cells.Add(Q(s.FrameCsv));rows.Add(string.Join(",",cells));
        }
        await File.WriteAllLinesAsync(summary,rows,new UTF8Encoding(true),ct);
        var fits=new List<string>{"drive_axis,gyro_axis,main_axis,points,intercept_dps,slope_dps_per_dps,coupling_percent,rms_residual_dps,max_abs_residual_dps,r_squared,main_gain_error_percent,max_nonlinearity_percent"};
        foreach(var axis in d.AxisSummaries)
        foreach(var f in axis.Fits)
            fits.Add(string.Join(",",new[]{axis.DriveAxis.ToString(),f.GyroAxisLabel,
                f.GyroAxisLabel==axis.MainGyroAxis?"1":"0",f.Points.ToString(Ci),
                F(f.InterceptDps,"G17"),F(f.Slope,"G17"),F(f.Slope*100,"G17"),
                F(f.ResidualRmsDps,"G17"),F(f.MaxAbsoluteResidualDps,"G17"),F(f.RSquared,"G17"),
                F(axis.MainGainErrorPercent,"G17"),F(axis.NonlinearityMaxPercentOfMaxTestSpeed,"G17")}));
        await File.WriteAllLinesAsync(coupling,fits,new UTF8Encoding(true),ct);
        await File.WriteAllTextAsync(html,BuildHtml(d),new UTF8Encoding(false),ct);
        WriteExcel(excel,d);
        return new[]{json,summary,coupling,html,excel,Path.Combine(folder,"CT-11_checkpoint.json")};
    }

    private static string Graph(IReadOnlyList<Ct11SweepResult> sweeps,int gyroAxis,string title)
    {
        if(sweeps.Count==0)return "<p>尚无真实动态数据</p>";
        var sorted=sweeps.OrderBy(s=>s.ReferenceSignedDps).ToArray();
        double maxAbsX=Math.Max(0.1,sorted.Max(s=>Math.Abs(s.ReferenceSignedDps))*1.2);
        double maxAbsY=Math.Max(0.1,sorted.Max(s=>Math.Abs(s.GyroMeanDps[gyroAxis]))*1.2);
        const double x0=440,y0=142,sx=370,sy=120;
        string n(double x)=>F(x,"F2");
        var b=new StringBuilder($"<svg viewBox='0 0 880 320' xmlns='http://www.w3.org/2000/svg' role='img' aria-label='{H(title)}'>");
        b.Append("<line x1='45' x2='825' y1='142' y2='142' stroke='#9db0c6'/>"+
                 "<line x1='440' x2='440' y1='18' y2='273' stroke='#9db0c6'/>");
        for(int j=0;j<5;j++)
        {
            double g=(j-2)/2d;double x=x0+g*sx,y=y0-g*sy;
            b.Append($"<line x1='{n(x)}' x2='{n(x)}' y1='18' y2='273' stroke='#e2ebf4'/>");
            b.Append($"<text x='{n(x)}' y='296' font-size='11' fill='#637d93' text-anchor='middle'>{F(g*maxAbsX,"F2")}</text>");
            b.Append($"<text x='8' y='{n(y+4)}' font-size='11' fill='#637d93'>{F(g*maxAbsY,"F2")}</text>");
        }
        string pts=string.Join(" ",sorted.Select(s=>$"{n(x0+s.ReferenceSignedDps/maxAbsX*sx)},{n(y0-s.GyroMeanDps[gyroAxis]/maxAbsY*sy)}"));
        b.Append($"<polyline points='{pts}' fill='none' stroke='#2874b2' stroke-width='2'/>");
        foreach(var s in sorted)
        {
            double x=x0+s.ReferenceSignedDps/maxAbsX*sx,y=y0-s.GyroMeanDps[gyroAxis]/maxAbsY*sy;
            b.Append($"<circle cx='{n(x)}' cy='{n(y)}' r='4' fill='#d68934'><title>{s.Axis}/{s.Direction} 参考={F(s.ReferenceSignedDps)}°/s，输出={F(s.GyroMeanDps[gyroAxis])}°/s</title></circle>");
        }
        return b.Append("<text x='440' y='315' text-anchor='middle' font-size='12'>真实编码器参考速率 (°/s)</text></svg>").ToString();
    }

    private static string BuildHtml(Ct11ReportData d)
    {
        var b=new StringBuilder("<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'/><title>CT-11 GYRO轴间耦合与低速线性</title>");
        b.Append("<style>body{font:14px 'Microsoft YaHei',sans-serif;color:#17374f;background:#f4f8fc;max-width:1200px;margin:20px auto;padding:0 15px}h1,h2{color:#216397}.card{background:white;padding:20px;margin:15px 0;border:1px solid #dce7f1;border-radius:12px}table{border-collapse:collapse;width:100%;font-size:12px}th,td{border:1px solid #dce7f1;padding:8px;text-align:right}td:first-child,th:first-child{text-align:left}th{background:#edf4fa}svg{max-width:100%;height:auto}.notice{color:#936633}@media print{body{background:white}.card{break-inside:avoid}}</style></head><body>");
        b.Append("<h1>CT-11 · GYRO 轴间耦合与低速线性</h1>");
        b.Append($"<div class='card'><p>设备：{H(d.DeviceNumber)}　UID：{H(d.UidHex)}　状态：{H(d.State)}</p>"+
            $"<p>时间：{H(d.StartedUtc)} → {H(d.FinishedUtc)}</p><p>{H(d.FailureReason)}</p><p><b>{H(d.Conclusion)}</b></p></div>");
        b.Append($"<div class='card'><h2>配置及标定溯源</h2><p>低速档位：{H(d.Settings.LowSpeedsCsv)} °/s；"+
            $"配对重复：{d.Settings.Repetitions}；角度行程：{F(d.Settings.TravelMinDeg)}°～{F(d.Settings.TravelMaxDeg)}°；"+
            $"静置：{F(d.Settings.SettleSeconds)}s；准备速度：{F(d.Settings.SetupSpeedDps)}°/s。</p>"+
            $"<p>Gyro历史拟合量程：±{d.GyroInputScaleDps}°/s，源JSON：{H(d.GyroJsonName)}，SHA256：{H(d.GyroJsonSha256)}</p>"+
            $"<p>ACC溯源：{H(d.AccJsonName)}，SHA256：{H(d.AccJsonSha256)}</p>"+
            $"<p>动态采集适配器：{H(d.DynamicSource)}</p></div>");
        foreach(var axis in d.AxisSummaries)
        {
            int main=axis.MainGyroAxis=="X"?0:2;
            b.Append($"<div class='card'><h2>{axis.DriveAxis} 旋转轴：低速线性与三轴耦合</h2>"+
                $"<p><b>主轴 Gyro-{axis.MainGyroAxis} 增益：</b>{F(axis.MainGain,"F6")}；"+
                $"<b>增益偏差：</b>{F(axis.MainGainErrorPercent,"F4")}%；"+
                $"<b>低速非线性最大偏离：</b>{F(axis.LowSpeedNonlinearityMaxDps,"F5")}°/s " +
                $"（测试最高实测速度的 {F(axis.NonlinearityMaxPercentOfMaxTestSpeed,"F4")}%）。</p>"+
                $"<p><b>非驱动轴最大耦合斜率：</b>{F(axis.MaximumCrossAxisCouplingPercent,"F4")}%（系统代理）</p>"+
                $"<p>{H(axis.Interpretation)}</p>");
            var axisSweeps=d.Sweeps.Where(x=>x.Axis==axis.DriveAxis).ToArray();
            for(int gyroAxis=0;gyroAxis<3;gyroAxis++)
            {
                string label=new[]{"X","Y","Z"}[gyroAxis];
                b.Append($"<h3>Gyro-{label} 相对真实转速的响应曲线{(gyroAxis==main?"（主轴）":"（非驱动轴）")}</h3>");
                b.Append(Graph(axisSweeps,gyroAxis,"Gyro-"+label+"动态响应"));
            }
            b.Append("<table><tr><th>Gyro轴</th><th>拟合点</th><th>常值截距°/s</th><th>斜率</th><th>RMS偏差°/s</th><th>最大偏差°/s</th><th>R²</th></tr>");
            foreach(var fit in axis.Fits)
                b.Append($"<tr><td>{fit.GyroAxisLabel}</td><td>{fit.Points}</td><td>{F(fit.InterceptDps)}</td>"+
                    $"<td>{F(fit.Slope,"F7")}</td><td>{F(fit.ResidualRmsDps)}</td>"+
                    $"<td>{F(fit.MaxAbsoluteResidualDps)}</td><td>{F(fit.RSquared,"F4")}</td></tr>");
            b.Append("</table></div>");
        }
        b.Append("<div class='card'><h2>真实运动采样段</h2><table><tr><th>转台轴</th><th>方向</th><th>速率档°/s</th><th>真实参考°/s</th><th>Gyro-X°/s</th><th>Gyro-Y°/s</th><th>Gyro-Z°/s</th><th>有效帧</th><th>逐帧证据</th></tr>");
        foreach(var s in d.Sweeps)
            b.Append($"<tr><td>{s.Axis}</td><td>{s.Direction}</td><td>{F(s.CommandSpeedDps)}</td>"+
                $"<td>{F(s.ReferenceSignedDps)}</td>"+
                string.Join("",s.GyroMeanDps.Select(x=>$"<td>{F(x)}</td>"))+
                $"<td>{s.AcceptedFrames}/{s.TotalFrames}</td><td>{H(s.FrameCsv)}</td></tr>");
        b.Append("</table></div><div class='card'><h2>测量限制与安全说明</h2><p class='notice'>");
        b.Append(H(d.EvidenceNotes));
        b.Append("</p><p>本测试不能仅凭低速曲线确认IMU内部本征交叉轴耦合。正反方向都需要正常采集，报告未生成的拟合项不应被解释为零误差。</p></div></body></html>");
        return b.ToString();
    }

    private static string Xml(string? s)=>SecurityElement.Escape(s??"")??"";
    private static string Col(int n)
    {
        string v="";
        while(n>0){n--;v=(char)('A'+n%26)+v;n/=26;}
        return v;
    }
    private static string Cell(int row,int col,object? obj)
    {
        string coord=Col(col)+row;
        if(obj is double or float or int or long)
            return $"<c r='{coord}'><v>{Convert.ToString(obj,Ci)}</v></c>";
        return $"<c r='{coord}' t='inlineStr'><is><t>{Xml(obj?.ToString())}</t></is></c>";
    }
    private static string Sheet(IReadOnlyList<object?[]> rows)
    {
        var b=new StringBuilder("<?xml version='1.0' encoding='utf-8'?><worksheet xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'><sheetData>");
        for(int i=0;i<rows.Count;i++)
        {
            b.Append($"<row r='{i+1}'>");
            for(int j=0;j<rows[i].Length;j++)b.Append(Cell(i+1,j+1,rows[i][j]));
            b.Append("</row>");
        }
        return b.Append("</sheetData></worksheet>").ToString();
    }
    private static void Add(ZipArchive z,string entry,string body)
    {
        var e=z.CreateEntry(entry,CompressionLevel.Optimal);
        using var w=new StreamWriter(e.Open(),new UTF8Encoding(false));w.Write(body);
    }
    private static void WriteExcel(string path,Ct11ReportData d)
    {
        var summary=new List<object?[]> {
            new object?[]{"字段","数值"},new object?[]{"测试编号","CT-11"},
            new object?[]{"设备编号",d.DeviceNumber},new object?[]{"UID",d.UidHex},
            new object?[]{"状态",d.State},new object?[]{"异常说明",d.FailureReason},
            new object?[]{"低速档位",d.Settings.LowSpeedsCsv},new object?[]{"完成动态扫描数",d.Sweeps.Count},
            new object?[]{"Gyro JSON SHA256",d.GyroJsonSha256},
            new object?[]{"动态数据源",d.DynamicSource},new object?[]{"结论",d.Conclusion}
        };
        var sweeps=new List<object?[]> {new object?[]{"转台轴","正反方向","轮次","设定速率°/s","真实参考°/s","Gyro-X°/s","Gyro-Y°/s","Gyro-Z°/s","有效帧","完整帧","证据CSV"}};
        foreach(var s in d.Sweeps)
            sweeps.Add(new object?[]{s.Axis.ToString(),s.Direction.ToString(),s.Repetition,s.CommandSpeedDps,
                s.ReferenceSignedDps,s.GyroMeanDps[0],s.GyroMeanDps[1],s.GyroMeanDps[2],
                s.AcceptedFrames,s.TotalFrames,s.FrameCsv});
        var fitRows=new List<object?[]> {new object?[]{"转台轴","Gyro轴","样本点","截距°/s","斜率","RMSE°/s","最大偏差°/s","R²","主轴增益误差%","最大非主轴耦合%"}};
        foreach(var a in d.AxisSummaries)
        foreach(var f in a.Fits)
            fitRows.Add(new object?[]{a.DriveAxis.ToString(),f.GyroAxisLabel,f.Points,f.InterceptDps,
                f.Slope,f.ResidualRmsDps,f.MaxAbsoluteResidualDps,f.RSquared,
                a.MainGainErrorPercent,a.MaximumCrossAxisCouplingPercent});
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
            "<sheets><sheet name='Summary' sheetId='1' r:id='rId1'/><sheet name='Sweeps' sheetId='2' r:id='rId2'/><sheet name='Fits' sheetId='3' r:id='rId3'/></sheets></workbook>");
        Add(z,"xl/_rels/workbook.xml.rels","<?xml version='1.0' encoding='utf-8'?><Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'>"+
            "<Relationship Id='rId1' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet' Target='worksheets/sheet1.xml'/>"+
            "<Relationship Id='rId2' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet' Target='worksheets/sheet2.xml'/>"+
            "<Relationship Id='rId3' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet' Target='worksheets/sheet3.xml'/></Relationships>");
        Add(z,"xl/worksheets/sheet1.xml",Sheet(summary));
        Add(z,"xl/worksheets/sheet2.xml",Sheet(sweeps));
        Add(z,"xl/worksheets/sheet3.xml",Sheet(fitRows));
    }
}
