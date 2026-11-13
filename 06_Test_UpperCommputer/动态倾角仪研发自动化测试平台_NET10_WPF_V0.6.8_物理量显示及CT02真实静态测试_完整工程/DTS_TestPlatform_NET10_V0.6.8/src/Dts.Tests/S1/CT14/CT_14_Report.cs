using System.Globalization;
using System.IO.Compression;
using System.Net;
using System.Security;
using System.Text;
using System.Text.Json;

namespace Dts.Tests.S1.CT14;

public static class Ct14Report
{
    private static readonly CultureInfo Ci = CultureInfo.InvariantCulture;
    private static readonly JsonSerializerOptions JsonOptions = new() { WriteIndented = true };
    private static string F(double x, string fmt = "F6") => double.IsFinite(x) ? x.ToString(fmt, Ci) : "";
    private static string H(string? s) => WebUtility.HtmlEncode(s ?? "");
    private static string Q(string? s) => "\"" + (s ?? "").Replace("\"", "\"\"") + "\"";

    public static async Task SaveMountCheckpointAsync(string folder, Ct14ReportData data, CancellationToken ct)
    {
        Directory.CreateDirectory(folder);
        string path = Path.Combine(folder, "CT-14_checkpoint.json");
        string temp = path + ".tmp";
        await File.WriteAllTextAsync(temp, JsonSerializer.Serialize(data, JsonOptions), new UTF8Encoding(false), ct);
        File.Move(temp, path, true);
    }

    public static async Task<IReadOnlyList<string>> ExportMountAsync(
        string folder, Ct14ReportData data, CancellationToken ct)
    {
        Directory.CreateDirectory(folder);
        string json = Path.Combine(folder, $"CT-14_mount_{data.MountIndex:D2}_result.json");
        string csv = Path.Combine(folder, "CT-14_mount_visits.csv");
        string html = Path.Combine(folder, "CT-14_mount_report.html");
        await SaveMountCheckpointAsync(folder, data, ct);
        await File.WriteAllTextAsync(json, JsonSerializer.Serialize(data, JsonOptions), new UTF8Encoding(false), ct);
        await WriteVisitsCsvAsync(csv, data.Visits, ct);
        await File.WriteAllTextAsync(html, BuildHtml(data, false), new UTF8Encoding(false), ct);
        return new[] { json, csv, html, Path.Combine(folder, "CT-14_checkpoint.json") };
    }

    public static async Task SaveSessionCheckpointAsync(string folder, Ct14ReportData data, CancellationToken ct)
    {
        Directory.CreateDirectory(folder);
        string path = Path.Combine(folder, "CT-14_checkpoint.json");
        string temp = path + ".tmp";
        await File.WriteAllTextAsync(temp, JsonSerializer.Serialize(data, JsonOptions), new UTF8Encoding(false), ct);
        File.Move(temp, path, true);
    }

    public static async Task<IReadOnlyList<string>> ExportSessionAsync(
        string folder, Ct14ReportData data, CancellationToken ct)
    {
        Directory.CreateDirectory(folder);
        string json = Path.Combine(folder, "CT-14_result.json");
        string csv = Path.Combine(folder, "CT-14_mounting_comparison.csv");
        string poseCsv = Path.Combine(folder, "CT-14_mount_pose_summary.csv");
        string html = Path.Combine(folder, "CT-14_report.html");
        string xlsx = Path.Combine(folder, "CT-14_report.xlsx");
        await SaveSessionCheckpointAsync(folder, data, ct);
        await File.WriteAllTextAsync(json, JsonSerializer.Serialize(data, JsonOptions), new UTF8Encoding(false), ct);
        await WriteVisitsCsvAsync(csv, data.Visits, ct);
        await WritePoseCsvAsync(poseCsv, data.Metrics?.MountPoseSummaries ?? Array.Empty<Ct14MountPoseSummary>(), ct);
        await File.WriteAllTextAsync(html, BuildHtml(data, true), new UTF8Encoding(false), ct);
        BuildXlsx(xlsx, data);
        return new[] { json, csv, poseCsv, html, xlsx, Path.Combine(folder, "CT-14_checkpoint.json") };
    }

    private static async Task WriteVisitsCsvAsync(string path, IReadOnlyList<Ct14Visit> visits, CancellationToken ct)
    {
        var b = new StringBuilder("mount_index,visit_index,pose_index,repeat,inner_target_deg,outer_target_deg,inner_actual_deg,outer_actual_deg,acc_x_g,acc_y_g,acc_z_g,gyro_x_dps,gyro_y_dps,gyro_z_dps,acc_reference_error_mg,acc_direction_error_deg,acc_norm_g,temp_c,total_samples,accepted_samples,rejected_fraction,batches,physical_csv,corrected_csv\r\n");
        foreach (var v in visits)
        {
            var cells = new[]
            {
                v.MountIndex.ToString(Ci), v.VisitIndex.ToString(Ci), v.PoseIndex.ToString(Ci), v.Repeat.ToString(Ci),
                F(v.InnerTargetDeg), F(v.OuterTargetDeg), F(v.InnerActualDeg), F(v.OuterActualDeg),
                F(v.AccCorrectedMeanG[0]), F(v.AccCorrectedMeanG[1]), F(v.AccCorrectedMeanG[2]),
                F(v.GyroCorrectedMeanDps[0]), F(v.GyroCorrectedMeanDps[1]), F(v.GyroCorrectedMeanDps[2]),
                F(v.VectorReferenceErrorMg), F(v.DirectionReferenceErrorDeg), F(v.AccNormG), F(v.MeanTemperatureC),
                v.TotalSamples.ToString(Ci), v.AcceptedSamples.ToString(Ci), F(v.RejectedFraction), v.Batches.ToString(Ci),
                Q(v.PhysicalCsv), Q(v.CorrectedCsv)
            };
            b.AppendLine(string.Join(",", cells));
        }
        await File.WriteAllTextAsync(path, b.ToString(), new UTF8Encoding(true), ct);
    }

    private static async Task WritePoseCsvAsync(string path, IReadOnlyList<Ct14MountPoseSummary> rows, CancellationToken ct)
    {
        var b = new StringBuilder("mount_index,pose_index,inner_deg,outer_deg,repeats,acc_x_g,acc_y_g,acc_z_g,gyro_x_dps,gyro_y_dps,gyro_z_dps,acc_norm_g,mean_temperature_c\r\n");
        foreach (var v in rows)
            b.AppendLine(string.Join(",", v.MountIndex, v.PoseIndex, F(v.InnerDeg), F(v.OuterDeg), v.Repeats,
                F(v.AccMeanG[0]), F(v.AccMeanG[1]), F(v.AccMeanG[2]),
                F(v.GyroMeanDps[0]), F(v.GyroMeanDps[1]), F(v.GyroMeanDps[2]),
                F(v.AccVectorNormG), F(v.MeanTemperatureC)));
        await File.WriteAllTextAsync(path, b.ToString(), new UTF8Encoding(true), ct);
    }

    private static string BuildHtml(Ct14ReportData d, bool session)
    {
        var sb = new StringBuilder("<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'/><title>CT-14 重复装夹报告</title>");
        sb.Append("<style>body{font:14px 'Microsoft YaHei',Arial,sans-serif;color:#20364a;background:#f4f7fb;max-width:1200px;margin:24px auto;padding:0 18px}h1,h2{color:#195b94}.card{background:#fff;border:1px solid #d9e4ee;border-radius:10px;padding:18px;margin:14px 0}table{border-collapse:collapse;width:100%;font-size:12px}th,td{border:1px solid #d5e0e9;padding:7px;text-align:right}th:first-child,td:first-child{text-align:left}th{background:#eaf2fa}.note{color:#65798b}</style></head><body>");
        sb.Append("<h1>CT-14 · 重复装夹与复测一致性</h1>");
        string mountLabel = session ? "全试验汇总" : d.MountIndex.ToString(Ci);
        sb.Append($"<div class='card'><p><b>设备：</b>{H(d.DeviceNumber)}　<b>完整UID：</b>{H(d.UidHex)}　<b>装夹轮次：</b>{H(mountLabel)}　<b>状态：</b>{H(d.State)}</p>");
        sb.Append($"<p>开始：{H(d.StartedUtc.ToString("O"))}<br/>结束：{H(d.FinishedUtc.ToString("O"))}</p><p>{H(d.FailureReason)}</p><p>{H(d.Conclusion)}</p></div>");
        sb.Append($"<div class='card'><h2>试验参数与标定溯源</h2><p>计划独立装夹：{d.Settings.PlannedMounts}次；实际完成：{d.Visits.Select(v => v.MountIndex).Distinct().Count()}次；每姿态重复：{d.Settings.RepeatsPerPose}次；姿态数：{d.Settings.Poses.Count}。</p>");
        sb.Append($"<p>预热：{F(d.Settings.WarmupSeconds)}s；定位速度：{F(d.Settings.MotionSpeedDps)}°/s；静置：{F(d.Settings.SettleSeconds)}s；采集：{F(d.Settings.SampleSeconds)}s；到位容差：{F(d.Settings.PositionToleranceDeg)}°；声明行程：[{F(d.Settings.AllowedMinDeg)},{F(d.Settings.AllowedMaxDeg)}]°。</p>");
        sb.Append($"<p>装夹SOP/定位/紧固/线缆记录：{H(d.Settings.MountingProcedureNote)}</p><p>ACC JSON：{H(d.AccJsonFile)} / SHA256：{H(d.AccJsonSha256)}<br/>Gyro JSON：{H(d.GyroJsonFile)} / SHA256：{H(d.GyroJsonSha256)}</p><p>{H(d.InputScaleDescription)}</p><p>重力参考：{H(d.ReferenceModel)}；gravity_sign={d.GravitySign}。</p></div>");
        if (d.Metrics is { } m)
        {
            sb.Append("<div class='card'><h2>跨装夹核心指标</h2>");
            sb.Append($"<p>有数据的装夹轮次：{m.MountsWithData}次；姿态：{m.Poses}个；采集单元：{m.Visits}；有效帧：{m.AcceptedFrames}。</p>");
            sb.Append($"<p><b>ACC跨装夹标准差 X/Y/Z：</b>{F(m.AccMountingStdMg[0])} / {F(m.AccMountingStdMg[1])} / {F(m.AccMountingStdMg[2])} mg</p>");
            sb.Append($"<p><b>ACC跨装夹矢量RMS：</b>{F(m.AccMountingVectorRmsMg)} mg；最大偏离：{F(m.AccMountingVectorMaxMg)} mg；方向差RMS：{F(m.AccMountingAngleRmsDeg)}°</p>");
            sb.Append($"<p><b>Gyro跨装夹标准差 X/Y/Z：</b>{F(m.GyroMountingStdDps[0])} / {F(m.GyroMountingStdDps[1])} / {F(m.GyroMountingStdDps[2])} °/s</p>");
            sb.Append($"<p>单次采集轮内ACC池化STD：{string.Join(" / ",m.AccWithinVisitPooledStdMg.Select(x=>F(x)))} mg；单次采集轮内Gyro池化STD：{string.Join(" / ",m.GyroWithinVisitPooledStdDps.Select(x=>F(x)))} °/s。</p>");
            sb.Append($"<p>芯片温度范围：{F(m.TemperatureMinC,"F2")}～{F(m.TemperatureMaxC,"F2")} ℃</p></div>");
            sb.Append("<div class='card'><h2>各装夹、各姿态均值</h2><table><tr><th>装夹</th><th>姿态</th><th>内轴°</th><th>外轴°</th><th>重复</th><th>ACC X/Y/Z (g)</th><th>Gyro X/Y/Z (°/s)</th><th>ACC模长g</th><th>温度℃</th></tr>");
            foreach (var v in m.MountPoseSummaries)
                sb.Append($"<tr><td>{v.MountIndex}</td><td>{v.PoseIndex}</td><td>{F(v.InnerDeg)}</td><td>{F(v.OuterDeg)}</td><td>{v.Repeats}</td><td>{string.Join(" / ",v.AccMeanG.Select(x=>F(x,"F7")))}</td><td>{string.Join(" / ",v.GyroMeanDps.Select(x=>F(x,"F6")))}</td><td>{F(v.AccVectorNormG)}</td><td>{F(v.MeanTemperatureC,"F2")}</td></tr>");
            sb.Append("</table></div>");
        }
        sb.Append("<div class='card'><h2>逐次采集记录</h2><table><tr><th>装夹</th><th>序号</th><th>姿态</th><th>重复</th><th>ACC参考误差mg</th><th>方向差°</th><th>Gyro X/Y/Z °/s</th><th>有效帧</th><th>温度℃</th></tr>");
        foreach (var v in d.Visits)
            sb.Append($"<tr><td>{v.MountIndex}</td><td>{v.VisitIndex}</td><td>{v.PoseIndex}</td><td>{v.Repeat}</td><td>{F(v.VectorReferenceErrorMg)}</td><td>{F(v.DirectionReferenceErrorDeg)}</td><td>{string.Join(" / ",v.GyroCorrectedMeanDps.Select(x=>F(x)))}</td><td>{v.AcceptedSamples}/{v.TotalSamples}</td><td>{F(v.MeanTemperatureC,"F2")}</td></tr>");
        sb.Append("</table></div>");
        sb.Append("<div class='card'><h2>结果解释与限制</h2><p>跨装夹差异按相同转台姿态分别比较不同装夹轮次的校正后均值，避免把不同姿态间的重力投影差异误算为装夹误差。轮内噪声与跨装夹离散分别报告。</p>");
        sb.Append("<p>本测试评估的是当前夹具、装配基准、紧固方式、线缆布置及预热条件下的重复装夹一致性。若每次装夹伴随断电重启，观测差异仍可能包含启动后温漂；统一预热时间并结合CT13/CT20结果解释。单一水平姿态无法辨识绕重力方向的旋转；多个非共线重力方向可提高对三轴安装方向变化的敏感性，但仍依赖转台轴模型、夹具基准及参考姿态准确度，不能替代独立的完整安装姿态标定。</p>");
        sb.Append("<p class='note'>本报告为研发诊断，不自动判定产品PASS/FAIL。必须结合产品技术指标、参考不确定度、机械装配规范和独立验证制定验收限值。</p></div></body></html>");
        return sb.ToString();
    }

    private static void BuildXlsx(string path, Ct14ReportData d)
    {
        var summary = new List<object?[]> {
            new object?[]{"项目","结果"}, new object?[]{"测试编号","CT-14"},
            new object?[]{"设备编号",d.DeviceNumber}, new object?[]{"完整UID",d.UidHex},
            new object?[]{"状态",d.State}, new object?[]{"有数据的装夹轮次",d.Visits.Select(v=>v.MountIndex).Distinct().Count()},
            new object?[]{"完成采集单元",d.Visits.Count}, new object?[]{"有效帧",d.Metrics?.AcceptedFrames},
            new object?[]{"装夹SOP/紧固/线缆记录",d.Settings.MountingProcedureNote},
            new object?[]{"ACC跨装夹矢量RMS(mg)",d.Metrics?.AccMountingVectorRmsMg},
            new object?[]{"ACC方向差RMS(deg)",d.Metrics?.AccMountingAngleRmsDeg},
            new object?[]{"ACC跨装夹STD X(mg)",d.Metrics?.AccMountingStdMg[0]},
            new object?[]{"ACC跨装夹STD Y(mg)",d.Metrics?.AccMountingStdMg[1]},
            new object?[]{"ACC跨装夹STD Z(mg)",d.Metrics?.AccMountingStdMg[2]},
            new object?[]{"Gyro跨装夹STD X(deg/s)",d.Metrics?.GyroMountingStdDps[0]},
            new object?[]{"Gyro跨装夹STD Y(deg/s)",d.Metrics?.GyroMountingStdDps[1]},
            new object?[]{"Gyro跨装夹STD Z(deg/s)",d.Metrics?.GyroMountingStdDps[2]},
            new object?[]{"单次采集ACC轮内池化STD X(mg)",d.Metrics?.AccWithinVisitPooledStdMg[0]},
            new object?[]{"单次采集ACC轮内池化STD Y(mg)",d.Metrics?.AccWithinVisitPooledStdMg[1]},
            new object?[]{"单次采集ACC轮内池化STD Z(mg)",d.Metrics?.AccWithinVisitPooledStdMg[2]},
            new object?[]{"单次采集Gyro轮内池化STD X(deg/s)",d.Metrics?.GyroWithinVisitPooledStdDps[0]},
            new object?[]{"单次采集Gyro轮内池化STD Y(deg/s)",d.Metrics?.GyroWithinVisitPooledStdDps[1]},
            new object?[]{"单次采集Gyro轮内池化STD Z(deg/s)",d.Metrics?.GyroWithinVisitPooledStdDps[2]},
            new object?[]{"温度最小值(°C)",d.Metrics?.TemperatureMinC},
            new object?[]{"温度最大值(°C)",d.Metrics?.TemperatureMaxC},
            new object?[]{"ACC JSON SHA256",d.AccJsonSha256},new object?[]{"Gyro JSON SHA256",d.GyroJsonSha256},
            new object?[]{"结论",d.Conclusion}
        };
        var details = new List<object?[]> {
            new object?[]{"装夹","序号","姿态","重复","内轴°","外轴°","ACC X g","ACC Y g","ACC Z g","Gyro X °/s","Gyro Y °/s","Gyro Z °/s","参考误差mg","方向差°","温度°C","有效帧","总帧"}
        };
        foreach (var v in d.Visits)
            details.Add(new object?[]{v.MountIndex,v.VisitIndex,v.PoseIndex,v.Repeat,v.InnerActualDeg,v.OuterActualDeg,
                v.AccCorrectedMeanG[0],v.AccCorrectedMeanG[1],v.AccCorrectedMeanG[2],
                v.GyroCorrectedMeanDps[0],v.GyroCorrectedMeanDps[1],v.GyroCorrectedMeanDps[2],
                v.VectorReferenceErrorMg,v.DirectionReferenceErrorDeg,v.MeanTemperatureC,v.AcceptedSamples,v.TotalSamples});
        var poseRows = new List<object?[]> {
            new object?[]{"装夹","姿态","内轴°","外轴°","重复","ACC X g","ACC Y g","ACC Z g","Gyro X °/s","Gyro Y °/s","Gyro Z °/s","温度°C"}
        };
        foreach (var v in d.Metrics?.MountPoseSummaries ?? Array.Empty<Ct14MountPoseSummary>())
            poseRows.Add(new object?[]{v.MountIndex,v.PoseIndex,v.InnerDeg,v.OuterDeg,v.Repeats,
                v.AccMeanG[0],v.AccMeanG[1],v.AccMeanG[2],v.GyroMeanDps[0],v.GyroMeanDps[1],v.GyroMeanDps[2],v.MeanTemperatureC});
        if (File.Exists(path)) File.Delete(path);
        using var zip = ZipFile.Open(path, ZipArchiveMode.Create);
        Add(zip,"[Content_Types].xml","<?xml version='1.0' encoding='utf-8'?><Types xmlns='http://schemas.openxmlformats.org/package/2006/content-types'><Default Extension='rels' ContentType='application/vnd.openxmlformats-package.relationships+xml'/><Default Extension='xml' ContentType='application/xml'/><Override PartName='/xl/workbook.xml' ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml'/><Override PartName='/xl/worksheets/sheet1.xml' ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml'/><Override PartName='/xl/worksheets/sheet2.xml' ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml'/><Override PartName='/xl/worksheets/sheet3.xml' ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml'/></Types>");
        Add(zip,"_rels/.rels","<?xml version='1.0' encoding='utf-8'?><Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'><Relationship Id='rId1' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument' Target='xl/workbook.xml'/></Relationships>");
        Add(zip,"xl/workbook.xml","<?xml version='1.0' encoding='utf-8'?><workbook xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main' xmlns:r='http://schemas.openxmlformats.org/officeDocument/2006/relationships'><sheets><sheet name='Summary' sheetId='1' r:id='rId1'/><sheet name='Visits' sheetId='2' r:id='rId2'/><sheet name='MountPose' sheetId='3' r:id='rId3'/></sheets></workbook>");
        Add(zip,"xl/_rels/workbook.xml.rels","<?xml version='1.0' encoding='utf-8'?><Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'><Relationship Id='rId1' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet' Target='worksheets/sheet1.xml'/><Relationship Id='rId2' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet' Target='worksheets/sheet2.xml'/><Relationship Id='rId3' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet' Target='worksheets/sheet3.xml'/></Relationships>");
        Add(zip,"xl/worksheets/sheet1.xml",Sheet(summary));
        Add(zip,"xl/worksheets/sheet2.xml",Sheet(details));
        Add(zip,"xl/worksheets/sheet3.xml",Sheet(poseRows));
    }

    private static string Sheet(List<object?[]> rows)
    {
        var b = new StringBuilder("<?xml version='1.0' encoding='utf-8'?><worksheet xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'><sheetData>");
        for (int r = 0; r < rows.Count; r++)
        {
            b.Append($"<row r='{r + 1}'>");
            for (int c = 0; c < rows[r].Length; c++)
            {
                string cell = Cell(c + 1, r + 1);
                object? value = rows[r][c];
                if (value is null) continue;
                if (value is string text)
                    b.Append($"<c r='{cell}' t='inlineStr'><is><t xml:space='preserve'>{SecurityElement.Escape(text)}</t></is></c>");
                else if (value is IFormattable f)
                    b.Append($"<c r='{cell}'><v>{SecurityElement.Escape(f.ToString(null, Ci) ?? "")}</v></c>");
                else
                    b.Append($"<c r='{cell}' t='inlineStr'><is><t>{SecurityElement.Escape(value.ToString() ?? "")}</t></is></c>");
            }
            b.Append("</row>");
        }
        return b.Append("</sheetData></worksheet>").ToString();
    }

    private static string Cell(int col, int row)
    {
        string letters = "";
        while (col > 0) { col--; letters = (char)('A' + col % 26) + letters; col /= 26; }
        return letters + row;
    }

    private static void Add(ZipArchive zip, string name, string content)
    {
        var entry = zip.CreateEntry(name, CompressionLevel.Optimal);
        using var writer = new StreamWriter(entry.Open(), new UTF8Encoding(false));
        writer.Write(content);
    }
}
