using System.Globalization;
using System.IO.Compression;
using System.Security;
using System.Text;
using System.Text.Json;

namespace Dts.Tests.S1.CT05;

/// <summary>CT-05 独立报告模块。每点原始CSV + JSON + HTML + Excel XLSX；异常中断保留部分检查点。</summary>
public static class Ct05Report
{
    private static readonly JsonSerializerOptions JsonOptions=new(){WriteIndented=true};
    public static async Task SaveCheckpointAsync(string folder,Ct05Summary value,CancellationToken ct)
    {
        Directory.CreateDirectory(folder);
        var json=JsonSerializer.Serialize(value,JsonOptions);
        string temp=Path.Combine(folder,"checkpoint.partial.json");
        await File.WriteAllTextAsync(temp,json,Encoding.UTF8,ct);
        File.Move(temp,Path.Combine(folder,"checkpoint.json"),true);
    }
    public static async Task<IReadOnlyList<string>> ExportAsync(string folder,Ct05Summary value,CancellationToken ct)
    {
        Directory.CreateDirectory(folder);
        string json=Path.Combine(folder,"CT-05_result.json");
        string csv=Path.Combine(folder,"CT-05_points.csv");
        string html=Path.Combine(folder,"CT-05_report.html");
        string xlsx=Path.Combine(folder,"CT-05_report.xlsx");
        await File.WriteAllTextAsync(json,JsonSerializer.Serialize(value,JsonOptions),Encoding.UTF8,ct);
        var lines=new List<string>{"index,channel,inner_cmd_deg,outer_cmd_deg,inner_actual_deg,outer_actual_deg,reference_deg,measured_deg,error_deg,norm_g,raw_ax_g,raw_ay_g,raw_az_g,corr_x_g,corr_y_g,corr_z_g,valid_samples,reject_ratio,temperature_c,raw_csv"};
        foreach(var p in value.Points)
        {
            var nums=new[]{(double)p.Index,p.InnerCommandDeg,p.OuterCommandDeg,p.InnerActualDeg,p.OuterActualDeg,
               p.ReferenceDeg,p.MeasuredDeg,p.ErrorDeg,p.NormG};
            var cells=new List<string>{p.Index.ToString(),p.Channel};
            cells.AddRange(nums.Skip(1).Select(x=>x.ToString("G17",CultureInfo.InvariantCulture)));
            cells.AddRange(p.RawG.Select(x=>x.ToString("G17",CultureInfo.InvariantCulture)));
            cells.AddRange(p.CorrectedG.Select(x=>x.ToString("G17",CultureInfo.InvariantCulture)));
            cells.Add(p.AcceptedSamples.ToString());
            cells.Add(p.RejectedFraction.ToString("G17",CultureInfo.InvariantCulture));
            cells.Add(p.TemperatureC.ToString("G17",CultureInfo.InvariantCulture));
            cells.Add("\""+p.RawCsvFile.Replace("\"","\"\"")+"\"");
            lines.Add(string.Join(",",cells));
        }
        await File.WriteAllLinesAsync(csv,lines,Encoding.UTF8,ct);
        await File.WriteAllTextAsync(html,BuildHtml(value),Encoding.UTF8,ct);
        BuildXlsx(xlsx,value);
        return new[]{json,csv,html,xlsx};
    }
    private static string H(string? s)=>System.Net.WebUtility.HtmlEncode(s??"");
    private static string F(double? v)=>v is double n?n.ToString("F6",CultureInfo.InvariantCulture):"—";
    private static string BuildHtml(Ct05Summary r)
    {
        var sb=new StringBuilder();
        sb.Append("<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><title>CT-05 静态角度检测报告</title>");
        sb.Append("<style>body{font-family:'Microsoft YaHei',Arial,sans-serif;color:#213650;margin:38px;background:#fff}header{padding:24px;background:#eaf3ff;border-left:7px solid #2369c8}h1{margin:0;font-size:28px}small{color:#678}table{border-collapse:collapse;width:100%;margin-top:17px;font-size:12px}td,th{border:1px solid #d4dfeb;padding:7px;text-align:left}th{background:#edf4fe} .kpis{display:flex;gap:15px;margin:24px 0}.box{padding:15px;border:1px solid #d2e3f4;flex:1}.num{font-size:23px;font-weight:700;color:#1d579a}.warn{background:#fff5e8;padding:12px;margin-top:20px}.muted{color:#7b8795}svg{max-width:100%}@media print{body{margin:12mm}.warn{break-inside:avoid}}</style></head><body>");
        sb.Append("<header><small>DYNAMIC INCLINOMETER · RESEARCH TEST REPORT</small><h1>CT-05 静态角度精度检测</h1><p>真实 IMU 数据 + 2TD-600 实际位置反馈</p></header>");
        sb.Append($"<p><b>设备：</b>{H(r.DtsId)}　<b>原始 UID：</b>{H(r.UidRaw)}<br/><b>状态：</b>{H(r.Status)}　<b>开始：</b>{H(r.StartedUtc)}　<b>结束：</b>{H(r.CompletedUtc)}<br/><b>标定 JSON：</b>{H(r.CalibrationFile)}<br/><b>标定 SHA-256：</b>{H(r.CalibrationSha256)}</p>");
        sb.Append($"<div class='kpis'><div class='box'>已采点数<div class='num'>{r.Points.Count}</div></div><div class='box'>Bias (°)<div class='num'>{F(r.BiasDeg)}</div></div><div class='box'>RMSE (°)<div class='num'>{F(r.RmseDeg)}</div></div><div class='box'>Max |Error| (°)<div class='num'>{F(r.MaxAbsErrorDeg)}</div></div></div>");
        sb.Append("<h2>逐姿态角度误差</h2>");
        if(r.Points.Count>0)
        {
            int width=800,height=240;double max=Math.Max(.001,r.Points.Max(p=>Math.Abs(p.ErrorDeg))*1.25);
            var positions=r.Points.Select((p,i)=> (x:40d+i*(width-70d)/Math.Max(1,r.Points.Count-1),y:height/2d-p.ErrorDeg*(height-55d)/2/max)).ToArray();
            sb.Append($"<svg viewBox='0 0 {width} {height}' xmlns='http://www.w3.org/2000/svg' role='img' aria-label='各点误差趋势'>");
            sb.Append($"<line x1='40' y1='{height/2}' x2='{width-25}' y2='{height/2}' stroke='#bccbdc' stroke-dasharray='4,4'/>");
            sb.Append($"<text x='1' y='18' font-size='12'>{F(max)}°</text><text x='2' y='{height-10}' font-size='12'>{F(-max)}°</text>");
            sb.Append("<polyline fill='none' stroke='#2065b5' stroke-width='2' points='");
            sb.Append(string.Join(" ",positions.Select(x=>$"{x.x.ToString("F1",CultureInfo.InvariantCulture)},{x.y.ToString("F1",CultureInfo.InvariantCulture)}")));
            sb.Append("'/></svg>");
        }
        sb.Append("<h2>按测量轴统计</h2><table><tr><th>检测轴</th><th>检测点数</th><th>Bias (°)</th><th>MAE (°)</th><th>RMSE (°)</th><th>Max |Error| (°)</th></tr>");
        foreach(var group in r.Points.GroupBy(p=>p.Channel).OrderBy(x=>x.Key))
        {
            var a=group.ToArray();
            sb.Append($"<tr><td>{H(group.Key)}</td><td>{a.Length}</td><td>{F(a.Average(x=>x.ErrorDeg))}</td><td>{F(a.Average(x=>Math.Abs(x.ErrorDeg)))}</td><td>{F(Math.Sqrt(a.Average(x=>x.ErrorDeg*x.ErrorDeg)))}</td><td>{F(a.Max(x=>Math.Abs(x.ErrorDeg)))}</td></tr>");
        }
        sb.Append("</table><h2>逐点数据</h2><table><tr><th>#</th><th>轴</th><th>内轴实测°</th><th>外轴实测°</th><th>参考°</th><th>测量°</th><th>误差°</th><th>模长g</th><th>有效帧</th></tr>");
        foreach(var p in r.Points)sb.Append($"<tr><td>{p.Index}</td><td>{H(p.Channel)}</td><td>{F(p.InnerActualDeg)}</td><td>{F(p.OuterActualDeg)}</td><td>{F(p.ReferenceDeg)}</td><td>{F(p.MeasuredDeg)}</td><td>{F(p.ErrorDeg)}</td><td>{F(p.NormG)}</td><td>{p.AcceptedSamples}</td></tr>");
        sb.Append("</table><h2>测试配置</h2><p>");
        sb.Append($"模式：{H(r.Settings.PlanKind)}；速度 {F(r.Settings.SpeedDps)} °/s；静置 {F(r.Settings.SettleSeconds)} s；采样 {F(r.Settings.CaptureSeconds)} s；到位容差 ±{F(r.Settings.PositionToleranceDeg)} °；批准行程 [{F(r.Settings.AllowedTravelMinDeg)}, {F(r.Settings.AllowedTravelMaxDeg)}] °</p>");
        sb.Append($"<div class='warn'><b>研发测试免责声明：</b>{H(r.Evaluation)}。软件仅依据记录产生统计，未证明转台参考计量溯源与全系统不确定度；未签署验收判据之前不得作为出厂合格证明。<p>{H(r.ErrorMessage)}</p></div>");
        return sb.Append("</body></html>").ToString();
    }
    private static string Xml(string s)=>SecurityElement.Escape(s)??"";
    private static void Add(ZipArchive zip,string path,string content)
    {
        var entry=zip.CreateEntry(path,CompressionLevel.Optimal);
        using var w=new StreamWriter(entry.Open(),new UTF8Encoding(false));w.Write(content);
    }
    private static string Cell(string column,int row,object? value)
    {
        string refc=column+row;
        if(value is double or int or long)
            return $"<c r='{refc}'><v>{Convert.ToString(value,CultureInfo.InvariantCulture)}</v></c>";
        return $"<c r='{refc}' t='inlineStr'><is><t>{Xml(value?.ToString()??"")}</t></is></c>";
    }
    private static string Col(int number)
    {
        string r="";
        for(int x=number;x>0;x=(x-1)/26)r=(char)('A'+(x-1)%26)+r;
        return r;
    }
    private static string Sheet(IEnumerable<object?[]> rows)
    {
        var sb=new StringBuilder("<?xml version='1.0' encoding='UTF-8'?><worksheet xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'><sheetData>");
        int row=0;
        foreach(var cells in rows)
        {
            row++;sb.Append($"<row r='{row}'>");
            for(int j=0;j<cells.Length;j++)sb.Append(Cell(Col(j+1),row,cells[j]));
            sb.Append("</row>");
        }
        return sb.Append("</sheetData></worksheet>").ToString();
    }
    // Standalone OOXML XLSX writer: no Python, Excel interop or third-party NuGet dependency.
    private static void BuildXlsx(string file,Ct05Summary r)
    {
        var detail=new List<object?[]>{new object?[]{"序号","轴","内轴实际(°)","外轴实际(°)","参考角(°)","测量角(°)","误差(°)","ACC模长(g)","有效帧","剔除率","芯片温度(°C)","原始CSV"}};
        detail.AddRange(r.Points.Select(x=>new object?[]{x.Index,x.Channel,x.InnerActualDeg,x.OuterActualDeg,x.ReferenceDeg,x.MeasuredDeg,x.ErrorDeg,x.NormG,x.AcceptedSamples,x.RejectedFraction,x.TemperatureC,x.RawCsvFile}));
        var summary=new List<object?[]>
        {
            new object?[]{"项目","结果"},new object?[]{"项目","CT-05"},
            new object?[]{"设备号",r.DtsId},new object?[]{"原始UID",r.UidRaw},
            new object?[]{"状态",r.Status},new object?[]{"标定文件",r.CalibrationFile},
            new object?[]{"标定SHA256",r.CalibrationSha256},new object?[]{"开始",r.StartedUtc},
            new object?[]{"结束",r.CompletedUtc},new object?[]{"测试点数",r.Points.Count},
            new object?[]{"Bias(°)",r.BiasDeg},new object?[]{"RMSE(°)",r.RmseDeg},
            new object?[]{"MaxAbs(°)",r.MaxAbsErrorDeg},new object?[]{"说明",r.Evaluation},
            new object?[]{"异常",r.ErrorMessage}
        };
        foreach(var group in r.Points.GroupBy(p=>p.Channel).OrderBy(g=>g.Key))
        {
            var points=group.ToArray();
            summary.Add(new object?[]{group.Key+"轴 Bias(°)",points.Average(x=>x.ErrorDeg)});
            summary.Add(new object?[]{group.Key+"轴 RMSE(°)",Math.Sqrt(points.Average(x=>x.ErrorDeg*x.ErrorDeg))});
            summary.Add(new object?[]{group.Key+"轴 MaxAbs(°)",points.Max(x=>Math.Abs(x.ErrorDeg))});
        }
        string temp=file+".tmp";
        using(var fs=new FileStream(temp,FileMode.Create,FileAccess.Write,FileShare.None))
        using(var zip=new ZipArchive(fs,ZipArchiveMode.Create))
        {
            Add(zip,"[Content_Types].xml","<?xml version='1.0' encoding='UTF-8'?><Types xmlns='http://schemas.openxmlformats.org/package/2006/content-types'><Default Extension='rels' ContentType='application/vnd.openxmlformats-package.relationships+xml'/><Default Extension='xml' ContentType='application/xml'/><Override PartName='/xl/workbook.xml' ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml'/><Override PartName='/xl/worksheets/sheet1.xml' ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml'/><Override PartName='/xl/worksheets/sheet2.xml' ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml'/></Types>");
            Add(zip,"_rels/.rels","<?xml version='1.0' encoding='UTF-8'?><Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'><Relationship Id='rId1' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument' Target='xl/workbook.xml'/></Relationships>");
            Add(zip,"xl/workbook.xml","<?xml version='1.0' encoding='UTF-8'?><workbook xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main' xmlns:r='http://schemas.openxmlformats.org/officeDocument/2006/relationships'><sheets><sheet name='测试汇总' sheetId='1' r:id='rId1'/><sheet name='逐点结果' sheetId='2' r:id='rId2'/></sheets></workbook>");
            Add(zip,"xl/_rels/workbook.xml.rels","<?xml version='1.0' encoding='UTF-8'?><Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'><Relationship Id='rId1' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet' Target='worksheets/sheet1.xml'/><Relationship Id='rId2' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet' Target='worksheets/sheet2.xml'/></Relationships>");
            Add(zip,"xl/worksheets/sheet1.xml",Sheet(summary));Add(zip,"xl/worksheets/sheet2.xml",Sheet(detail));
        }
        File.Move(temp,file,true);
    }
}
