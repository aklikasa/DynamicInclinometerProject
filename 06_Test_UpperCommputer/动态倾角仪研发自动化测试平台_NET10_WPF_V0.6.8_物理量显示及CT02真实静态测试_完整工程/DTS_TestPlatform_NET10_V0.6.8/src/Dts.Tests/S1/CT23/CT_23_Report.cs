using System.Globalization;
using System.IO;
using System.IO.Compression;
using System.Net;
using System.Security;
using System.Text;
using System.Text.Json;
using Dts.Tests.S1.CT10;

namespace Dts.Tests.S1.CT23;

public static class Ct23Report
{
    private static readonly CultureInfo Ci=CultureInfo.InvariantCulture;
    private static readonly JsonSerializerOptions JsonOpts=new(){WriteIndented=true};
    private static string F(double d,string pattern="F5")=>d.ToString(pattern,Ci);
    private static string H(string? s)=>WebUtility.HtmlEncode(s??"");
    private static string C(string? s)=>"\""+(s??"").Replace("\"","\"\"")+"\"";
    public static async Task SaveCheckpointAsync(string folder,Ct23ReportData data,CancellationToken ct)
    {
        string file=Path.Combine(folder,"CT-23_checkpoint.json"),temporary=file+".tmp";
        await File.WriteAllTextAsync(temporary,JsonSerializer.Serialize(data,JsonOpts),new UTF8Encoding(false),ct);
        File.Move(temporary,file,true);
    }
    public static async Task SaveRawMotionAsync(string rawGyro,string encoderPath,
        Ct10Capture capture,CancellationToken ct)
    {
        // Persist unmodified REAL dynamic evidence immediately, before any scientific filtering.
        var raw=new List<string>{"host_ticks,gyro_input_x_dps,gyro_input_y_dps,gyro_input_z_dps,temp_c,raw_gx,raw_gy,raw_gz"};
        foreach(var f in capture.GyroFrames)
            raw.Add(string.Join(",",f.TimestampTicks.ToString(Ci),F(f.InputX_Dps,"G17"),
                F(f.InputY_Dps,"G17"),F(f.InputZ_Dps,"G17"),F(f.TemperatureC,"G17"),
                f.RawCountX?.ToString(Ci)??"",f.RawCountY?.ToString(Ci)??"",
                f.RawCountZ?.ToString(Ci)??""));
        await File.WriteAllLinesAsync(rawGyro,raw,new UTF8Encoding(true),ct);
        var enc=new List<string>{"host_ticks,inner_actual_deg,outer_actual_deg,inner_normal,outer_normal,inner_enabled,outer_enabled"};
        foreach(var e in capture.EncoderFrames)
            enc.Add(string.Join(",",e.TimestampTicks.ToString(Ci),F(e.InnerDeg,"G17"),F(e.OuterDeg,"G17"),
                e.InnerNormal?"1":"0",e.OuterNormal?"1":"0",e.InnerEnabled?"1":"0",e.OuterEnabled?"1":"0"));
        await File.WriteAllLinesAsync(encoderPath,enc,new UTF8Encoding(true),ct);
    }
    public static async Task SaveDynamicEvidenceAsync(string gyroPath,
        IReadOnlyList<Ct23TracePoint> frames,CancellationToken ct)
    {
        var list=new List<string>{"host_ticks,elapsed_s,gyro_x_cal_dps,gyro_y_cal_dps,gyro_z_cal_dps,predicted_acc_x_g,predicted_acc_y_g,predicted_acc_z_g,temp_c,raw_gx,raw_gy,raw_gz"};
        foreach(var v in frames)
        {
            list.Add(string.Join(",",new[]{v.HostTicks.ToString(Ci),F(v.TimeSeconds,"G17"),
                F(v.GyroXCorrectedDps,"G17"),F(v.GyroYCorrectedDps,"G17"),F(v.GyroZCorrectedDps,"G17"),
                F(v.PredictedGravityX,"G17"),F(v.PredictedGravityY,"G17"),F(v.PredictedGravityZ,"G17"),
                F(v.TemperatureC,"G17"),v.RawGyroX?.ToString(Ci)??"",v.RawGyroY?.ToString(Ci)??"",
                v.RawGyroZ?.ToString(Ci)??""}));
        }
        await File.WriteAllLinesAsync(gyroPath,list,new UTF8Encoding(true),ct);
    }
    public static async Task<IReadOnlyList<string>> ExportAsync(string folder,Ct23ReportData data,CancellationToken ct)
    {
        Directory.CreateDirectory(folder);
        string json=Path.Combine(folder,"CT-23_result.json"),
               csv=Path.Combine(folder,"CT-23_trials.csv"),
               html=Path.Combine(folder,"CT-23_report.html"),
               excel=Path.Combine(folder,"CT-23_report.xlsx");
        await SaveCheckpointAsync(folder,data,ct);
        await File.WriteAllTextAsync(json,JsonSerializer.Serialize(data,JsonOpts),new UTF8Encoding(false),ct);
        var table=new List<string>{"index,trajectory,repetition,outer_command_start_deg,outer_command_end_deg,outer_actual_start_deg,outer_actual_end_deg,closure_angle_deg,acc_start_reference_deg,acc_end_reference_deg,encoder_travel_deg,gyro_integrated_x_deg,gyro_x_encoder_diff_deg,gyro_integrated_vector_norm_deg,gyro_frames,static_start_frames,static_end_frames,dynamic_s,max_gyro_gap_s,temp_c,raw_start_csv,raw_end_csv,gyro_trace_csv,encoder_trace_csv,raw_dynamic_gyro_csv"};
        foreach(var p in data.Trials)
        {
            table.Add(string.Join(",",new[]{p.Index.ToString(Ci),p.TrajectoryIndex.ToString(Ci),p.Repetition.ToString(Ci),
                F(p.OuterStartCommandDeg,"G17"),F(p.OuterEndCommandDeg,"G17"),F(p.OuterStartActualDeg,"G17"),
                F(p.OuterEndActualDeg,"G17"),F(p.ClosureAngleDeg,"G17"),F(p.StartReferenceErrorDeg,"G17"),
                F(p.EndReferenceErrorDeg,"G17"),F(p.EncoderTravelDeg,"G17"),F(p.IntegratedGyroXDeg,"G17"),
                F(p.XAxisVsEncoderDifferenceDeg,"G17"),F(p.IntegratedGyroMagnitudeDeg,"G17"),
                p.DynamicFrames.ToString(Ci),p.StaticStartFrames.ToString(Ci),p.StaticEndFrames.ToString(Ci),
                F(p.DynamicDurationSeconds,"G17"),F(p.MaxGyroGapSeconds,"G17"),F(p.MeanTemperatureC,"G17"),
                C(p.StaticStartCsv),C(p.StaticEndCsv),C(p.GyroTraceCsv),C(p.EncoderCsv),C(p.RawDynamicGyroCsv)}));
        }
        await File.WriteAllLinesAsync(csv,table,new UTF8Encoding(true),ct);
        await File.WriteAllTextAsync(html,BuildHtml(data),new UTF8Encoding(false),ct);
        BuildExcel(excel,data);
        return [json,csv,html,excel,Path.Combine(folder,"CT-23_checkpoint.json")];
    }
    private static string Svg(IEnumerable<double> input,string unit,string stroke)
    {
        var values=input.ToArray();if(values.Length==0)return "<p>暂无完成的实测轨迹</p>";
        double lo=values.Min(),hi=values.Max(),pad=Math.Max(0.001,(hi-lo)*0.2);
        lo-=pad;hi+=pad;
        var sb=new StringBuilder("<svg viewBox='0 0 850 250' role='img' aria-label='闭合误差轨迹'>");
        for(int k=0;k<5;k++)
        {
            double y=25+k*42;
            sb.Append($"<line x1='65' y1='{F(y)}' x2='835' y2='{F(y)}' stroke='#dde5ef'/>");
            sb.Append($"<text x='5' y='{F(y+4)}' font-size='12' fill='#64748b'>{F(hi-k*(hi-lo)/4,"F3")}{H(unit)}</text>");
        }
        var points=new List<string>();
        for(int i=0;i<values.Length;i++)
        {
            double x=65+(i+.5)*770/values.Length,y=25+(hi-values[i])/(hi-lo)*168;
            points.Add(F(x,"F2")+","+F(y,"F2"));
            sb.Append($"<circle cx='{F(x,"F2")}' cy='{F(y,"F2")}' r='4' fill='{stroke}'><title>#{i+1} = {F(values[i],"F6")}{H(unit)}</title></circle>");
            sb.Append($"<text x='{F(x,"F2")}' y='231' text-anchor='middle' fill='#64748b' font-size='11'>{i+1}</text>");
        }
        // Render line before dots as well; order does not affect evidence.
        sb.Append($"<polyline fill='none' stroke='{stroke}' stroke-width='2.5' points='{string.Join(" ",points)}'/>");
        return sb.Append("</svg>").ToString();
    }
    private static string BuildHtml(Ct23ReportData data)
    {
        var sb=new StringBuilder("<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'/><title>CT-23 ACC↔Gyro重力闭合报告</title>");
        sb.Append("<style>body{font:14px 'Microsoft YaHei',sans-serif;background:#f5f8fc;color:#25455f;max-width:1180px;margin:22px auto;padding:0 16px}h1,h2{color:#15588c}.card{background:white;border:1px solid #d9e7f0;border-radius:12px;padding:18px;margin:14px 0}table{width:100%;border-collapse:collapse;font-size:12px}td,th{border:1px solid #dae4ee;padding:8px}th{background:#ebf2fa}svg{max-width:100%}.warn{color:#8a5a18;font-weight:bold}@media print{body{background:white}}</style></head><body>");
        sb.Append("<h1>CT-23 · ACC↔Gyro 六轴联合对齐：重力闭合诊断</h1>");
        sb.Append($"<div class='card'><p><b>设备：</b>{H(data.DeviceNumber)}　<b>UID：</b>{H(data.UidHex)}</p>"+
            $"<p><b>状态：</b>{H(data.State)}　开始：{H(data.StartedUtc)}　结束：{H(data.FinishedUtc)}</p>"+
            $"<p>{H(data.FailureReason)}</p><p class='warn'>{H(data.Conclusion)}</p></div>");
        if(data.Metrics is { } m)
            sb.Append($"<div class='card'><h2>测试统计</h2><p>轨迹数：{m.CompletedTrajectories}；累计完成次数：{m.CompletedTrials}；"+
                $"重力闭合RMS：{F(m.ClosureRmsDeg)}°；最大：{F(m.ClosureMaxDeg)}°；平均：{F(m.ClosureMeanDeg)}°。</p>"+
                $"<p>Gyro X累计角与真实编码器变化的差值RMS：{F(m.GyroVsEncoderRmsDeg)}°。</p>"+
                $"<p class='warn'>可观测性：{H(m.Observability)}。{H(m.Conclusion)}</p></div>");
        sb.Append("<div class='card'><h2>图一 · Gyro传播与停车后ACC之间的角度闭合误差</h2>")
            .Append(Svg(data.Trials.Select(t=>t.ClosureAngleDeg),"°","#246fbb")).Append("</div>");
        sb.Append("<div class='card'><h2>图二 · Gyro累计X轴角度减编码器运动角度</h2>")
            .Append(Svg(data.Trials.Select(t=>t.XAxisVsEncoderDifferenceDeg),"°","#b66b29")).Append("</div>");
        sb.Append("<div class='card'><h2>逐轨迹实测汇总</h2><table><tr><th>#</th><th>起点°</th><th>终点°</th><th>闭合误差°</th><th>ACC初态参考差°</th><th>ACC终态参考差°</th><th>Gyro X累计角°</th><th>编码器变化°</th><th>动态帧</th></tr>");
        foreach(var p in data.Trials)
            sb.Append($"<tr><td>{p.Index}</td><td>{F(p.OuterStartActualDeg,"F3")}</td>"+
                $"<td>{F(p.OuterEndActualDeg,"F3")}</td><td>{F(p.ClosureAngleDeg)}</td>"+
                $"<td>{F(p.StartReferenceErrorDeg)}</td><td>{F(p.EndReferenceErrorDeg)}</td>"+
                $"<td>{F(p.IntegratedGyroXDeg)}</td><td>{F(p.EncoderTravelDeg)}</td><td>{p.DynamicFrames}</td></tr>");
        sb.Append("</table></div><div class='card'><h2>设置与校准溯源</h2>");
        sb.Append($"<p>轨迹：{H(data.Settings.Trajectories)}；运动速度{F(data.Settings.SpeedDps)}°/s；"+
            $"重复{data.Settings.Repetitions}次；静态采集{F(data.Settings.StaticCaptureSeconds)}秒；"+
            $"允许行程[{F(data.Settings.AllowedMinDeg)},{F(data.Settings.AllowedMaxDeg)}]°。</p>");
        sb.Append($"<p>参考系：{H(data.ReferenceModel)}；gravity_sign={data.GravitySign}</p>"+
            $"<p>ACC文件：{H(data.AccFile)} SHA256={H(data.AccSha256)}<br/>"+
            $"Gyro文件：{H(data.GyroFile)} SHA256={H(data.GyroSha256)}</p></div>");
        sb.Append($"<div class='card'><h2>时间质量与观测边界</h2><p>{H(data.DynamicAdapterDescription)}</p>"+
            $"<p class='warn'>{H(data.Limitations)}</p></div></body></html>");
        return sb.ToString();
    }
    private static string Cell(int row,int col,object? value)
    {
        if(value is null)return "";
        string address=$"{(char)('A'+col-1)}{row}";
        if(value is double or int or long)
            return $"<c r='{address}'><v>{Convert.ToString(value,Ci)}</v></c>";
        return $"<c r='{address}' t='inlineStr'><is><t>{SecurityElement.Escape(value.ToString())}</t></is></c>";
    }
    private static string Sheet(IEnumerable<object?[]> rows)
    {
        var sb=new StringBuilder("<?xml version='1.0' encoding='UTF-8'?><worksheet xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'><sheetData>");
        int index=0;
        foreach(var row in rows)
        {
            index++;sb.Append($"<row r='{index}'>");
            for(int j=0;j<row.Length;j++)sb.Append(Cell(index,j+1,row[j]));
            sb.Append("</row>");
        }
        return sb.Append("</sheetData></worksheet>").ToString();
    }
    private static void Add(ZipArchive zip,string name,string body)
    {
        var item=zip.CreateEntry(name,CompressionLevel.Optimal);
        using var writer=new StreamWriter(item.Open(),new UTF8Encoding(false));writer.Write(body);
    }
    private static void BuildExcel(string file,Ct23ReportData d)
    {
        var overview=new List<object?[]>{
            new object?[]{"字段","数值"},new object?[]{"TestId","CT-23"},
            new object?[]{"UID",d.UidHex},new object?[]{"设备编号",d.DeviceNumber},
            new object?[]{"状态",d.State},new object?[]{"失败原因",d.FailureReason},
            new object?[]{"重力闭合RMS_deg",d.Metrics?.ClosureRmsDeg},
            new object?[]{"重力闭合最大_deg",d.Metrics?.ClosureMaxDeg},
            new object?[]{"完成轨迹数",d.Metrics?.CompletedTrajectories},
            new object?[]{"可观测性",d.Metrics?.Observability??"没有完成轨迹"},
            new object?[]{"ACC SHA256",d.AccSha256},new object?[]{"Gyro SHA256",d.GyroSha256},
            new object?[]{"测量局限",d.Limitations}};
        var trials=new List<object?[]>{new object?[]{"次序","轨迹","重复","外轴起点_deg","外轴终点_deg",
            "闭合角度_deg","ACC起始参考_deg","ACC终点参考_deg","Gyro累计X_deg","真实编码器_deg",
            "GyroX-编码器_deg","采集帧数","最长帧间隔_s","均温_C"}};
        foreach(var t in d.Trials)
            trials.Add(new object?[]{t.Index,t.TrajectoryIndex,t.Repetition,t.OuterStartActualDeg,
                t.OuterEndActualDeg,t.ClosureAngleDeg,t.StartReferenceErrorDeg,t.EndReferenceErrorDeg,
                t.IntegratedGyroXDeg,t.EncoderTravelDeg,t.XAxisVsEncoderDifferenceDeg,
                t.DynamicFrames,t.MaxGyroGapSeconds,t.MeanTemperatureC});
        using var zip=ZipFile.Open(file,ZipArchiveMode.Create);
        Add(zip,"[Content_Types].xml","<?xml version='1.0'?><Types xmlns='http://schemas.openxmlformats.org/package/2006/content-types'>"+
            "<Default Extension='rels' ContentType='application/vnd.openxmlformats-package.relationships+xml'/>"+
            "<Default Extension='xml' ContentType='application/xml'/>"+
            "<Override PartName='/xl/workbook.xml' ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml'/>"+
            "<Override PartName='/xl/worksheets/sheet1.xml' ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml'/>"+
            "<Override PartName='/xl/worksheets/sheet2.xml' ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml'/></Types>");
        Add(zip,"_rels/.rels","<?xml version='1.0'?><Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'>"+
            "<Relationship Id='rId1' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument' Target='xl/workbook.xml'/></Relationships>");
        Add(zip,"xl/workbook.xml","<?xml version='1.0'?><workbook xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main' xmlns:r='http://schemas.openxmlformats.org/officeDocument/2006/relationships'>"+
            "<sheets><sheet name='Summary' sheetId='1' r:id='rId1'/><sheet name='Trajectories' sheetId='2' r:id='rId2'/></sheets></workbook>");
        Add(zip,"xl/_rels/workbook.xml.rels","<?xml version='1.0'?><Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'>"+
            "<Relationship Id='rId1' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet' Target='worksheets/sheet1.xml'/>"+
            "<Relationship Id='rId2' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet' Target='worksheets/sheet2.xml'/></Relationships>");
        Add(zip,"xl/worksheets/sheet1.xml",Sheet(overview));Add(zip,"xl/worksheets/sheet2.xml",Sheet(trials));
    }
}
