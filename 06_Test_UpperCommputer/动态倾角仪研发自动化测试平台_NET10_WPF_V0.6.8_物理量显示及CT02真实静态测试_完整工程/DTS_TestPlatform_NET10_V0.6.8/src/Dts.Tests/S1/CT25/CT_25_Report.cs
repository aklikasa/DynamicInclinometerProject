using System.Globalization;
using System.IO;
using System.IO.Compression;
using System.Net;
using System.Security;
using System.Text;
using System.Text.Json;

namespace Dts.Tests.S1.CT25;

public static class Ct25Report
{
    private static readonly CultureInfo C=CultureInfo.InvariantCulture;
    private static readonly JsonSerializerOptions JsonOptions=new(){WriteIndented=true};
    private static string F(double x)=>x.ToString("G17",C);
    private static string H(object? o)=>WebUtility.HtmlEncode(o?.ToString()??"");
    private static string Quoted(string? s)=>"\""+(s??"").Replace("\"","\"\"")+"\"";

    public static async Task SaveCheckpointAsync(string folder,Ct25ReportData data,CancellationToken ct)
    {
        string target=Path.Combine(folder,"CT-25_checkpoint.json");
        string temp=target+".partial";
        await File.WriteAllTextAsync(temp,JsonSerializer.Serialize(data,JsonOptions),new UTF8Encoding(false),ct);
        File.Move(temp,target,true);
    }
    public static async Task SaveRawFramesAsync(string file,Ct25Capture cap,CancellationToken ct)
    {
        await using var stream=new FileStream(file,FileMode.CreateNew,FileAccess.Write,FileShare.Read,65536,FileOptions.Asynchronous);
        await using var writer=new StreamWriter(stream,new UTF8Encoding(true));
        await writer.WriteLineAsync("clock_ticks,clock_frequency_hz,phase,encoder_inner_deg,encoder_outer_deg,device_fused_tilt_x_deg,device_fused_tilt_y_deg,temperature_c,alignment_bound_ms,full_uid,source");
        foreach(var row in cap.Frames)
        {
            ct.ThrowIfCancellationRequested();
            await writer.WriteLineAsync(string.Join(",",new[]{
                row.Ticks.ToString(C),cap.ClockFrequency.ToString(C),row.Phase.ToString(),
                F(row.InnerEncoderDeg),F(row.OuterEncoderDeg),
                F(row.DeviceFusedTiltXDeg),F(row.DeviceFusedTiltYDeg),F(row.TemperatureC),
                F(cap.AlignmentBoundMs),Quoted(cap.FullUidHex),Quoted(cap.Source)}));
        }
        await writer.FlushAsync(ct);
    }
    public static async Task<IReadOnlyList<string>> ExportAsync(string folder,Ct25ReportData data,CancellationToken ct)
    {
        Directory.CreateDirectory(folder);
        await SaveCheckpointAsync(folder,data,ct);
        string json=Path.Combine(folder,"CT-25_result.json");
        string csv=Path.Combine(folder,"CT-25_summary.csv");
        string plan=Path.Combine(folder,"CT-25_plan.csv");
        string html=Path.Combine(folder,"CT-25_report.html");
        string xlsx=Path.Combine(folder,"CT-25_report.xlsx");
        await File.WriteAllTextAsync(json,JsonSerializer.Serialize(data,JsonOptions),new UTF8Encoding(false),ct);
        var lines=new List<string>{"index,axis,amplitude_command_deg,frequency_hz,repeat,actual_encoder_amplitude_deg,device_fused_amplitude_deg,gain,gain_error_percent,phase_diff_deg,delay_seconds,bias_deg,rmse_deg,base_output_deg,return_shift_deg,final_return_residual_deg,encoder_sine_r2,aligned_clock_bound_ms,steady_frames,source,frame_csv"};
        foreach(var r in data.Results)
            lines.Add(string.Join(",",new[]{r.Index.ToString(C),Quoted(r.Axis),F(r.AmplitudeCommandDeg),
                F(r.FrequencyCommandHz),r.Repeat.ToString(C),F(r.ActualEncoderAmplitudeDeg),
                F(r.DeviceAmplitudeDeg),F(r.Gain),F(r.GainErrorPercent),F(r.PhaseLagDegrees),
                F(r.DelaySeconds),F(r.DynamicBiasDeg),F(r.DynamicRmseDeg),F(r.BeforeZeroBiasDeg),
                F(r.AfterZeroDifferenceDeg),F(r.FinalReturnResidualDeg),F(r.EncoderWaveformR2),
                F(r.AlignmentBoundMs),r.CapturedSteadyFrames.ToString(C),Quoted(r.Source),Quoted(r.TraceCsv)}));
        await File.WriteAllLinesAsync(csv,lines,new UTF8Encoding(true),ct);
        var planLines=new List<string>{"index,axis,amplitude_deg,frequency_hz,repeat,cycles,center_deg,peak_speed_dps,peak_acceleration_dps2,duration_s,eligible,reason"};
        foreach(var p in data.Plan)
            planLines.Add(string.Join(",",new[]{p.Index.ToString(C),Quoted(p.Axis.ToString()),F(p.AmplitudeDeg),
                F(p.FrequencyHz),p.Repeat.ToString(C),p.Cycles.ToString(C),F(p.CenterDeg),
                F(p.PeakSpeedDps),F(p.PeakAccelerationDps2),F(p.DurationSeconds),
                p.Eligible?"1":"0",Quoted(p.ExclusionReason)}));
        await File.WriteAllLinesAsync(plan,planLines,new UTF8Encoding(true),ct);
        await File.WriteAllTextAsync(html,Html(data),new UTF8Encoding(false),ct);
        BuildXlsx(xlsx,data);
        return new[]{json,csv,plan,html,xlsx,Path.Combine(folder,"CT-25_checkpoint.json")}
            .Concat(Directory.EnumerateFiles(folder,"sine_*.csv")).ToArray();
    }
    private static string Graph(string title,IReadOnlyList<Ct25Result> results,Func<Ct25Result,double> y,string units,string color)
    {
        if(results.Count==0)return "<p>尚无真实数据；未连接同步融合角接口时不会伪造图表。</p>";
        var a=results.Select(y).ToArray();double min=a.Min(),max=a.Max();double m=Math.Max((max-min)*0.15,0.001);
        min-=m;max+=m;
        string N(double x)=>x.ToString("F2",C);
        var sb=new StringBuilder($"<h3>{H(title)}</h3><svg viewBox='0 0 840 230' role='img' aria-label='{H(title)}'>");
        for(int i=0;i<=4;i++)
        {
            double py=22+154*i/4;
            sb.Append($"<line x1='65' y1='{N(py)}' x2='815' y2='{N(py)}' stroke='#d8e5f2'/>"+
                $"<text x='3' y='{N(py+4)}' font-size='11' fill='#526880'>{N(max-i*(max-min)/4)} {H(units)}</text>");
        }
        string points=string.Join(" ",a.Select((v,i)=>$"{N(65+(i+.5)*750/a.Length)},{N(22+(max-v)/(max-min)*154)}"));
        sb.Append($"<polyline points='{points}' stroke='{color}' fill='none' stroke-width='2.5'/>");
        for(int i=0;i<a.Length;i++)
        {
            double x=65+(i+.5)*750/a.Length;
            double yy=22+(max-a[i])/(max-min)*154;
            sb.Append($"<circle cx='{N(x)}' cy='{N(yy)}' r='4' fill='{color}'><title>#{results[i].Index} / {N(a[i])} {H(units)}</title></circle>");
            sb.Append($"<text x='{N(x)}' y='209' font-size='10' text-anchor='middle' fill='#526880'>{results[i].Index}</text>");
        }
        return sb.Append("</svg>").ToString();
    }
    private static string Html(Ct25ReportData d)
    {
        var b=new StringBuilder("<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'/><title>CT-25 动态倾角基线</title>");
        b.Append("<style>body{font:14px 'Microsoft YaHei',Arial;color:#173854;background:#f2f6fa;max-width:1100px;margin:20px auto;padding:15px}h1,h2{color:#2466a3}.card{background:white;padding:20px;border:1px solid #d9e5ee;border-radius:12px;margin:12px 0}table{border-collapse:collapse;width:100%;font-size:12px}th,td{border:1px solid #d6e3ed;padding:8px;text-align:right}th{background:#eaf2f9}th:first-child,td:first-child{text-align:left}svg{width:100%;height:auto}</style></head><body>");
        b.Append($"<h1>CT-25 · 常温小幅低频动态倾角基线</h1><div class='card'><p>UID：{H(d.UidHex)} ｜ 设备：{H(d.DeviceNumber)}</p>"+
            $"<p>状态：<b>{H(d.State)}</b> ｜ 完成 {d.Results.Count} 项 ｜ 计划 {d.Plan.Count} 项</p>"+
            $"<p>开始：{H(d.StartUtc)} ｜ 结束：{H(d.EndUtc)}</p><p>{H(d.Error)}</p></div>");
        b.Append("<div class='card'><h2>真实数据源与标定溯源</h2>"+
            $"<p>来源：{H(d.Source)}</p><p>ACC: {H(d.AccCalibrationName)} / {H(d.AccCalibrationSha256)}<br/>"+
            $"Gyro: {H(d.GyroCalibrationName)} / {H(d.GyroCalibrationSha256)}</p><p>{H(d.Notes)}</p></div>");
        b.Append("<div class='card'><h2>幅频试验计划及剔除理由</h2><table><tr><th>编号</th><th>轴</th><th>幅值 °</th><th>频率 Hz</th><th>峰值速度 °/s</th><th>峰值加速度 °/s²</th><th>结果</th></tr>");
        foreach(var p in d.Plan)
            b.Append($"<tr><td>{p.Index}</td><td>{H(p.Axis)}</td><td>{p.AmplitudeDeg:F3}</td><td>{p.FrequencyHz:F3}</td>"+
                $"<td>{p.PeakSpeedDps:F3}</td><td>{p.PeakAccelerationDps2:F3}</td><td>{H(p.Eligible?"候选/允许":"剔除："+p.ExclusionReason)}</td></tr>");
        b.Append("</table></div>");
        b.Append("<div class='card'><h2>已完成真实试验结果</h2><table><tr><th>编号</th><th>轴</th><th>频率 Hz</th><th>增益</th><th>相位 °</th><th>Bias °</th><th>RMSE °</th><th>回零残差 °</th></tr>");
        foreach(var r in d.Results)
            b.Append($"<tr><td>{r.Index}</td><td>{H(r.Axis)}</td><td>{r.FrequencyCommandHz:F3}</td><td>{r.Gain:F5}</td>"+
                $"<td>{r.PhaseLagDegrees:F3}</td><td>{r.DynamicBiasDeg:F5}</td><td>{r.DynamicRmseDeg:F5}</td><td>{r.FinalReturnResidualDeg:F5}</td></tr>");
        b.Append("</table></div><div class='card'>").Append(Graph("真实动态增益",d.Results,r=>r.Gain,"比值","#256baf"))
            .Append(Graph("设备融合倾角相位差",d.Results,r=>r.PhaseLagDegrees,"°","#a76f20"))
            .Append(Graph("动态RMSE",d.Results,r=>r.DynamicRmseDeg,"°","#7c59bd"))
            .Append("</div></body></html>");
        return b.ToString();
    }
    private static string X(string s)=>SecurityElement.Escape(s)??"";
    private static string ExcelCell(int row,int col,object? value)
    {
        string c="";int n=col;
        while(n>0){n--;c=(char)('A'+(n%26))+c;n/=26;}
        string id=c+row.ToString(C);
        if(value is null)return "";
        if(value is double or int or long)return $"<c r='{id}'><v>{Convert.ToString(value,C)}</v></c>";
        return $"<c r='{id}' t='inlineStr'><is><t>{X(value.ToString()??"")}</t></is></c>";
    }
    private static string Sheet(IEnumerable<object?[]> rows)
    {
        var b=new StringBuilder("<?xml version='1.0' encoding='utf-8'?><worksheet xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'><sheetData>");
        int i=0;
        foreach(var row in rows)
        {
            b.Append($"<row r='{++i}'>");
            for(int j=0;j<row.Length;j++)b.Append(ExcelCell(i,j+1,row[j]));
            b.Append("</row>");
        }
        return b.Append("</sheetData></worksheet>").ToString();
    }
    private static void ZipText(ZipArchive zip,string name,string content)
    {
        var entry=zip.CreateEntry(name,CompressionLevel.Optimal);
        using var w=new StreamWriter(entry.Open(),new UTF8Encoding(false));w.Write(content);
    }
    private static void BuildXlsx(string path,Ct25ReportData d)
    {
        var overview=new List<object?[]>{new object?[]{"名称","数值"},new object?[]{"测试项目","CT-25"},
            new object?[]{"状态",d.State},new object?[]{"UID",d.UidHex},
            new object?[]{"真实融合倾角来源",d.Source},new object?[]{"完成项目",d.Results.Count},
            new object?[]{"开始时间",d.StartUtc},new object?[]{"完成时间",d.EndUtc},
            new object?[]{"结论",d.Notes}};
        var plan=new List<object?[]>{new object?[]{"编号","测试轴","幅值°","频率Hz","重复","峰值速度°/s","峰值加速度°/s²","允许","原因"}};
        plan.AddRange(d.Plan.Select(p=>new object?[]{p.Index,p.Axis.ToString(),p.AmplitudeDeg,p.FrequencyHz,
            p.Repeat,p.PeakSpeedDps,p.PeakAccelerationDps2,p.Eligible?"是":"否",p.ExclusionReason}));
        var results=new List<object?[]>{new object?[]{"编号","测试轴","幅值°","频率Hz","真实转台幅值°","融合倾角幅值°","增益","相位差°","时延s","Bias°","RMSE°","回零残差°","时间对齐上界ms","源文件"}};
        results.AddRange(d.Results.Select(r=>new object?[]{r.Index,r.Axis,r.AmplitudeCommandDeg,r.FrequencyCommandHz,
            r.ActualEncoderAmplitudeDeg,r.DeviceAmplitudeDeg,r.Gain,r.PhaseLagDegrees,r.DelaySeconds,
            r.DynamicBiasDeg,r.DynamicRmseDeg,r.FinalReturnResidualDeg,r.AlignmentBoundMs,r.TraceCsv}));
        using var zip=ZipFile.Open(path,ZipArchiveMode.Create);
        var overrides=string.Concat(Enumerable.Range(1,3).Select(i=>$"<Override PartName='/xl/worksheets/sheet{i}.xml' ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml'/>"));
        ZipText(zip,"[Content_Types].xml","<?xml version='1.0' encoding='utf-8'?><Types xmlns='http://schemas.openxmlformats.org/package/2006/content-types'>"+
            "<Default Extension='rels' ContentType='application/vnd.openxmlformats-package.relationships+xml'/>"+
            "<Default Extension='xml' ContentType='application/xml'/>"+
            "<Override PartName='/xl/workbook.xml' ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml'/>"+overrides+"</Types>");
        ZipText(zip,"_rels/.rels","<?xml version='1.0' encoding='utf-8'?><Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'>"+
            "<Relationship Id='rId1' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument' Target='xl/workbook.xml'/></Relationships>");
        ZipText(zip,"xl/workbook.xml","<?xml version='1.0' encoding='utf-8'?><workbook xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main' xmlns:r='http://schemas.openxmlformats.org/officeDocument/2006/relationships'><sheets>"+
            "<sheet name='Overview' sheetId='1' r:id='rId1'/><sheet name='Plan' sheetId='2' r:id='rId2'/><sheet name='Results' sheetId='3' r:id='rId3'/></sheets></workbook>");
        ZipText(zip,"xl/_rels/workbook.xml.rels","<?xml version='1.0' encoding='utf-8'?><Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'>"+
            string.Concat(Enumerable.Range(1,3).Select(i=>$"<Relationship Id='rId{i}' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet' Target='worksheets/sheet{i}.xml'/>"))+"</Relationships>");
        ZipText(zip,"xl/worksheets/sheet1.xml",Sheet(overview));
        ZipText(zip,"xl/worksheets/sheet2.xml",Sheet(plan));
        ZipText(zip,"xl/worksheets/sheet3.xml",Sheet(results));
    }
}
