using System.Globalization;
using System.IO.Compression;
using System.Net;
using System.Security;
using System.Text;
using System.Text.Json;

namespace Dts.Tests.S1.CT03;

/// <summary>CT-03 报告独立模块：可打印HTML（含SVG矢量图）、结果JSON、逐点CSV、原生XLSX、检查点。</summary>
public static class Ct03Report
{
    private static readonly JsonSerializerOptions JsonOptions = new() { WriteIndented = true };
    private static readonly CultureInfo Ci = CultureInfo.InvariantCulture;
    private static string F(double d, string format = "F6") => d.ToString(format, Ci);
    private static string H(string? text) => WebUtility.HtmlEncode(text ?? "");
    private static string CsvText(string? s) => "\"" + (s ?? "").Replace("\"", "\"\"") + "\"";

    public static async Task SaveCheckpointAsync(string folder, Ct03ReportData data, CancellationToken ct)
    {
        string path = Path.Combine(folder, "CT-03_checkpoint.json");
        string temp = path + ".partial";
        await File.WriteAllTextAsync(temp, JsonSerializer.Serialize(data, JsonOptions), new UTF8Encoding(false), ct);
        File.Move(temp, path, overwrite: true);
    }

    public static async Task<IReadOnlyList<string>> ExportAsync(string folder, Ct03ReportData data, CancellationToken ct)
    {
        Directory.CreateDirectory(folder);
        var json = Path.Combine(folder, "CT-03_result.json");
        var csv = Path.Combine(folder, "CT-03_points.csv");
        var html = Path.Combine(folder, "CT-03_report.html");
        var xlsx = Path.Combine(folder, "CT-03_report.xlsx");
        await SaveCheckpointAsync(folder, data, ct);
        await File.WriteAllTextAsync(json, JsonSerializer.Serialize(data, JsonOptions), new UTF8Encoding(false), ct);
        var lines = new List<string> {
            "index,label,inner_target_deg,outer_target_deg,inner_actual_deg,outer_actual_deg,ref_ax_g,ref_ay_g,ref_az_g,cal_ax_g,cal_ay_g,cal_az_g,err_x_g,err_y_g,err_z_g,vector_err_g,direction_err_deg,norm_g,norm_err_g,accepted_frames,total_frames,reject_fraction,temp_c,raw_csv,corrected_csv"
        };
        foreach (var p in data.Points)
        {
            var a = new List<string> { p.Index.ToString(Ci), CsvText(p.Label), F(p.InnerCommandDeg, "G17"),
                F(p.OuterCommandDeg, "G17"), F(p.InnerActualDeg, "G17"), F(p.OuterActualDeg, "G17") };
            a.AddRange(p.ReferenceG.Select(v => F(v, "G17")));
            a.AddRange(p.CorrectedMeanG.Select(v => F(v, "G17")));
            a.AddRange(p.AxisErrorG.Select(v => F(v, "G17")));
            a.AddRange(new[] { p.VectorErrorG, p.DirectionErrorDeg, p.NormG, p.NormErrorG }
                .Select(v => F(v, "G17")));
            a.Add(p.AcceptedSamples.ToString(Ci));
            a.Add(p.TotalSamples.ToString(Ci));
            a.Add(F(p.RejectedFraction, "G17"));
            a.Add(F(p.MeanTemperatureC, "G17"));
            a.Add(CsvText(p.RawCsv));
            a.Add(CsvText(p.CorrectedCsv));
            lines.Add(string.Join(",", a));
        }
        await File.WriteAllLinesAsync(csv, lines, new UTF8Encoding(true), ct);
        await File.WriteAllTextAsync(html, BuildHtml(data), new UTF8Encoding(false), ct);
        ExportXlsx(xlsx, data);
        return [json, csv, html, xlsx, Path.Combine(folder, "CT-03_checkpoint.json")];
    }

    private static string VectorChart(IReadOnlyList<Ct03PointResult> points)
    {
        if (points.Count == 0) return "<p>暂无完成点位；仅保存部分测试记录。</p>";
        const double width = 920, height = 270, left = 62, right = 20, top = 28, bottom = 44;
        double plotW = width - left - right, plotH = height - top - bottom;
        double max = Math.Max(0.1, points.Max(p => p.VectorErrorG * 1000) * 1.15);
        var dots = points.Select((p, i) => new
        {
            x = left + (i + 0.5) * plotW / points.Count,
            y = top + plotH - (p.VectorErrorG * 1000 / max) * plotH,
            value = p.VectorErrorG * 1000
        }).ToArray();
        var s = new StringBuilder($"<svg role='img' aria-label='各姿态三维ACC矢量误差（mg）' viewBox='0 0 {width} {height}' xmlns='http://www.w3.org/2000/svg'>");
        for (int i = 0; i <= 4; i++)
        {
            double y = top + plotH * i / 4;
            double v = max * (1 - i / 4d);
            s.Append($"<line x1='{F(left, "F1")}' y1='{F(y, "F1")}' x2='{F(width-right, "F1")}' y2='{F(y, "F1")}' stroke='#d9e6f2'/>" +
                     $"<text x='7' y='{F(y+4,"F1")}' font-size='12' fill='#617c94'>{F(v,"F2")}</text>");
        }
        s.Append("<polyline fill='none' stroke='#2568be' stroke-width='2.8' points='");
        s.Append(string.Join(" ", dots.Select(d => $"{F(d.x, "F2")},{F(d.y, "F2")}")));
        s.Append("'/>");
        for (int i = 0; i < dots.Length; i++)
        {
            var d = dots[i];
            s.Append($"<circle cx='{F(d.x, "F2")}' cy='{F(d.y, "F2")}' r='4' fill='#2063b4'><title>点 {i+1}: {F(d.value,"F3")} mg</title></circle>");
            // 大网格避免将全部点号挤在图表底部；逐点tooltip仍完整保留。
            int labelEvery = Math.Max(1, (int)Math.Ceiling(dots.Length / 24.0));
            if (i % labelEvery == 0 || i == dots.Length - 1)
                s.Append($"<text x='{F(d.x,"F2")}' y='{height-18}' text-anchor='middle' font-size='10' fill='#70849a'>{i+1}</text>");
        }
        return s.Append("</svg>").ToString();
    }

    private static string ThreeAxisChart(Ct03Metrics? m)
    {
        if (m is null) return "";
        double max = Math.Max(0.01, m.AxisRmseG.Max() * 1000 * 1.25);
        string[] names = ["X", "Y", "Z"];
        string[] colors = ["#1761a0", "#1a9b8c", "#ed934e"];
        var sb = new StringBuilder("<svg role='img' aria-label='三轴RMSE对比（mg）' viewBox='0 0 500 180' xmlns='http://www.w3.org/2000/svg'>");
        for (int j = 0; j < 3; j++)
        {
            double val = m.AxisRmseG[j] * 1000;
            sb.Append($"<text x='14' y='{34+j*54}' font-size='14' fill='#33475e'>{names[j]}</text>");
            sb.Append($"<rect x='50' y='{16+j*54}' width='{F(340*val/max,"F2")}' height='25' rx='5' fill='{colors[j]}' />");
            sb.Append($"<text x='405' y='{34+j*54}' font-size='14' fill='#273f5c'>{F(val,"F3")} mg</text>");
        }
        return sb.Append("</svg>").ToString();
    }

    private static string BuildHtml(Ct03ReportData r)
    {
        var sb = new StringBuilder();
        sb.Append("<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><title>CT-03 ACC三轴矢量独立验证</title>");
        sb.Append("<style>body{font-family:'Microsoft YaHei','Segoe UI',sans-serif;max-width:1150px;margin:36px auto;padding:0 24px;color:#21354d;line-height:1.6;background:#fff}" +
            "header{padding:25px;border-radius:12px;background:#edf5fc;border-left:7px solid #2568be}h1{margin:0;font-size:27px;color:#164980}h2{margin-top:30px;color:#164980}" +
            "table{width:100%;border-collapse:collapse;font-size:12px}th{background:#edf4fd}td,th{padding:8px;border-bottom:1px solid #dbe5ef;text-align:right}td:first-child,th:first-child{text-align:left}" +
            ".meta{margin-top:18px;color:#536c85}.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:20px 0}.kpi{border:1px solid #d7e5f2;border-radius:10px;padding:14px}.kpi strong{font-size:22px;color:#1a589a;display:block}" +
            ".warn{background:#fff4e8;border-left:5px solid #d48b33;padding:14px;margin:22px 0}.ok{background:#edf7f5;border-left:5px solid #33a494;padding:14px}.fine{font-size:12px;color:#61798d}svg{width:100%;height:auto;max-width:920px}" +
            "@media print{body{max-width:none;margin:10mm;padding:0}.kpis{grid-template-columns:repeat(4,1fr)}tr{break-inside:avoid}}</style></head><body>");
        sb.Append("<header><span class='fine'>DYNAMIC INCLINOMETER · S1 / REAL HARDWARE</span><h1>CT-03　ACC 三轴矢量独立验证</h1>" +
            "<p>真实 2TD-600 多姿态反馈 + IMU FIFO 采样 + 常温 ACC 3×3 校正</p></header>");
        sb.Append($"<div class='meta'><b>设备：</b>{H(r.DeviceNumber)}　<b>MCU UID：</b>{H(r.UidHex)}<br>" +
            $"<b>状态：</b>{H(r.State)}　<b>开始：</b>{H(r.StartedUtc)}　<b>结束：</b>{H(r.FinishedUtc)}<br>" +
            $"<b>参考模型：</b>{H(r.ReferenceModel)}</div>");
        sb.Append("<div class='kpis'>");
        sb.Append($"<div class='kpi'>完成工位<strong>{r.Points.Count}</strong></div>");
        sb.Append($"<div class='kpi'>有效真实帧<strong>{r.Metrics?.SampleCount ?? 0}</strong></div>");
        sb.Append($"<div class='kpi'>矢量RMSE<strong>{(r.Metrics is null ? "—" : F(r.Metrics.VectorRmseG * 1000,"F3"))} mg</strong></div>");
        sb.Append($"<div class='kpi'>方向最大误差<strong>{(r.Metrics is null ? "—" : F(r.Metrics.DirectionMaxDeg,"F5"))}°</strong></div></div>");
        sb.Append($"<div class='warn'><b>研发结论：</b>{H(r.Conclusion)}。{H(r.FailureReason)}<br>{H(r.MotionSafetyNote)}</div>");
        sb.Append($"<h2>扫描覆盖度</h2><p>计划：{H(r.Settings.PlanKind)}；" +
            (r.Settings.PlanKind == Ct03Algorithm.GridPlan
                ? $"自定义网格：{r.Settings.InnerDivisions} × {r.Settings.OuterDivisions} 工位；"
                : "固定预设扫描；") +
            $"本次计划涵盖 {r.PlannedUniqueGravityDirections} 个不同重力方向；" +
            $"与历史ACC拟合或验证的重力方向重合工位：{(r.HistoricalGravityOverlaps.HasValue ? r.HistoricalGravityOverlaps.Value.ToString(Ci) : "未能核对")}。</p>");
        sb.Append("<p class='fine'>机械工位不等于独立参考重力方向；存在重复方向的工位可用于重复性观察，" +
            "但不应被宣称为同样数量的独立方向验证。与原ACC标定方向重合者亦非全新独立姿态。</p>");
        sb.Append("<h2>三维矢量误差趋势</h2><p class='fine'>各点的 ||a_cal - g_ref||（mg）；参考向量来自真实双轴反馈，不使用指令角度冒充测量值。</p>");
        sb.Append(VectorChart(r.Points));
        sb.Append("<h2>X/Y/Z 分轴 RMSE</h2><p class='fine'>三轴采用矢量分量误差的均方根，不仅仅验证模长。</p>");
        sb.Append(ThreeAxisChart(r.Metrics));
        if (r.Metrics is { } m)
        {
            sb.Append("<h2>统计汇总</h2><table><tr><th>指标</th><th>X</th><th>Y</th><th>Z</th></tr>");
            void AxisRow(string label, double[] arr) => sb.Append($"<tr><td>{label}</td><td>{F(arr[0]*1000,"F4")}</td><td>{F(arr[1]*1000,"F4")}</td><td>{F(arr[2]*1000,"F4")}</td></tr>");
            AxisRow("分轴 Bias (mg)", m.AxisBiasG);
            AxisRow("分轴 RMSE (mg)", m.AxisRmseG);
            AxisRow("分轴最大绝对误差 (mg)", m.AxisMaxAbsG);
            sb.Append("</table><p>三维矢量RMSE：" + F(m.VectorRmseG * 1000,"F4") + "mg；最大矢量误差：" + F(m.VectorMaxG * 1000,"F4") +
                "mg；方向RMSE：" + F(m.DirectionRmseDeg,"F6") + "°；最大方向误差：" + F(m.DirectionMaxDeg,"F6") +
                "°；模长RMSE：" + F(m.NormRmseG * 1000,"F4") + "mg；最大模长误差：" + F(m.NormMaxAbsG * 1000,"F4") + "mg。</p>");
        }
        sb.Append("<h2>逐姿态实测数据</h2><table><tr><th>#</th><th>内轴实测</th><th>外轴实测</th><th>参考X</th><th>参考Y</th><th>参考Z</th><th>测量X</th><th>测量Y</th><th>测量Z</th><th>矢量误差(mg)</th><th>方向(°)</th><th>模长残差(mg)</th><th>有效帧</th></tr>");
        foreach (var p in r.Points)
            sb.Append($"<tr><td>{p.Index}</td><td>{F(p.InnerActualDeg,"F3")}</td><td>{F(p.OuterActualDeg,"F3")}</td>" +
                string.Concat(p.ReferenceG.Select(v => $"<td>{F(v,"F5")}</td>")) +
                string.Concat(p.CorrectedMeanG.Select(v => $"<td>{F(v,"F5")}</td>")) +
                $"<td>{F(p.VectorErrorG*1000,"F3")}</td><td>{F(p.DirectionErrorDeg,"F5")}</td>" +
                $"<td>{F(p.NormErrorG*1000,"F3")}</td><td>{p.AcceptedSamples}</td></tr>");
        sb.Append("</table><h2>试验条件、校准版本和数据溯源</h2>");
        string gridSettings = r.Settings.PlanKind == Ct03Algorithm.GridPlan
            ? $"内轴等分数 {r.Settings.InnerDivisions}、起始角 {F(r.Settings.InnerStartDeg)}°；" +
              $"外轴等分数 {r.Settings.OuterDivisions}、起始角 {F(r.Settings.OuterStartDeg)}°；"
            : "固定预设扫描；";
        sb.Append($"<p>计划：{H(r.Settings.PlanKind)}；{gridSettings}" +
            $"运动速度 {F(r.Settings.SpeedDps)}°/s；静置 {F(r.Settings.SettleSeconds)} s；" +
            $"每点采样 {F(r.Settings.SampleSeconds)} s；到位容差 ±{F(r.Settings.PositionToleranceDeg)}°；" +
            $"已声明行程 [{F(r.Settings.AllowedMinDeg)}, {F(r.Settings.AllowedMaxDeg)}]°；最少有效帧 {r.Settings.MinValidSamples}；" +
            $"最大允许剔除 {F(r.Settings.MaxOutlierFraction*100,"F1")}%</p>");
        sb.Append($"<p>ACC 标定：{H(r.AccJsonFile)}<br>SHA-256：{H(r.AccJsonSha256)}<br>Gyro 标定：{H(r.GyroJsonFile)}" +
            $"<br>SHA-256：{H(r.GyroJsonSha256)}<br>输入单位：{H(r.InputScaleDescription)}</p>");
        sb.Append("<p class='fine'>CSV列说明：每姿态的physical.csv保存真实帧的原始计数与已按历史标定输入量程转换的g/°s；corrected.csv按行号与physical.csv一一对应，标识MAD剔除、校正向量和误差。" +
            "方向误差 = acos(校正矢量与参考矢量单位化点积)；模长误差 = ||a_cal||-1g。" +
            "报告中统计量为逐姿态均值误差，不等同单帧噪声或完整计量不确定度。局部12点不代表全空间验证；无经过签署的验收阈值则不输出产品PASS。</p>");
        return sb.Append("</body></html>").ToString();
    }

    // Minimal valid Office Open XML workbook, no additional NuGet / Excel COM dependency.
    private static string X(string s) => SecurityElement.Escape(s) ?? "";
    private static string Column(int idx)
    {
        var result = "";
        for (int v = idx; v > 0; v = (v - 1) / 26)
            result = (char)('A' + (v - 1) % 26) + result;
        return result;
    }
    private static string Cell(int row, int col, object? value)
    {
        string address = Column(col) + row;
        if (value is int or long or double or float)
            return $"<c r='{address}'><v>{Convert.ToString(value, Ci)}</v></c>";
        return $"<c r='{address}' t='inlineStr'><is><t>{X(value?.ToString() ?? "")}</t></is></c>";
    }
    private static string Sheet(IEnumerable<object?[]> rows)
    {
        var sb = new StringBuilder("<?xml version='1.0' encoding='utf-8'?><worksheet xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'><sheetData>");
        int idx = 0;
        foreach (var cells in rows)
        {
            idx++;
            sb.Append($"<row r='{idx}'>");
            for (int c = 0; c < cells.Length; c++) sb.Append(Cell(idx, c + 1, cells[c]));
            sb.Append("</row>");
        }
        return sb.Append("</sheetData></worksheet>").ToString();
    }
    private static void Add(ZipArchive archive, string name, string content)
    {
        var entry = archive.CreateEntry(name, CompressionLevel.Optimal);
        using var writer = new StreamWriter(entry.Open(), new UTF8Encoding(false));
        writer.Write(content);
    }
    private static void ExportXlsx(string file, Ct03ReportData r)
    {
        var overview = new List<object?[]> {
            new object?[] { "项目", "结果" }, new object?[] { "测试编号", "CT-03" }, new object?[] { "测试名称", "ACC三轴矢量独立验证" },
            new object?[] { "设备DTS", r.DeviceNumber }, new object?[] { "完整UID", r.UidHex }, new object?[] { "状态", r.State },
            new object?[] { "开始UTC", r.StartedUtc }, new object?[] { "结束UTC", r.FinishedUtc },
            new object?[] { "扫描计划", r.Settings.PlanKind }, new object?[] { "完成点数", r.Points.Count },
            new object?[] { "内轴等分数", r.Settings.PlanKind == Ct03Algorithm.GridPlan ? r.Settings.InnerDivisions : null },
            new object?[] { "外轴等分数", r.Settings.PlanKind == Ct03Algorithm.GridPlan ? r.Settings.OuterDivisions : null },
            new object?[] { "内轴起始角°", r.Settings.PlanKind == Ct03Algorithm.GridPlan ? r.Settings.InnerStartDeg : null },
            new object?[] { "外轴起始角°", r.Settings.PlanKind == Ct03Algorithm.GridPlan ? r.Settings.OuterStartDeg : null },
            new object?[] { "计划独立重力方向数", r.PlannedUniqueGravityDirections },
            new object?[] { "历史ACC重力方向重合工位", r.HistoricalGravityOverlaps },
            new object?[] { "有效帧数", r.Metrics?.SampleCount ?? 0 },
            new object?[] { "矢量RMSE(mg)", r.Metrics is null ? null : r.Metrics.VectorRmseG * 1000 },
            new object?[] { "矢量最大误差(mg)", r.Metrics is null ? null : r.Metrics.VectorMaxG * 1000 },
            new object?[] { "方向RMSE(°)", r.Metrics?.DirectionRmseDeg }, new object?[] { "方向最大误差(°)", r.Metrics?.DirectionMaxDeg },
            new object?[] { "模长RMSE(mg)", r.Metrics is null ? null : r.Metrics.NormRmseG * 1000 },
            new object?[] { "ACC标定文件", r.AccJsonFile }, new object?[] { "ACC SHA256", r.AccJsonSha256 },
            new object?[] { "Gyro标定文件", r.GyroJsonFile }, new object?[] { "Gyro SHA256", r.GyroJsonSha256 },
            new object?[] { "输入换算", r.InputScaleDescription }, new object?[] { "状态说明", r.Conclusion }, new object?[] { "异常记录", r.FailureReason }
        };
        var header = new object?[] {
            "#", "内轴目标°", "外轴目标°", "内轴实测°", "外轴实测°",
            "参考X g", "参考Y g", "参考Z g", "校正X g", "校正Y g", "校正Z g",
            "误差X mg", "误差Y mg", "误差Z mg", "矢量误差mg", "方向误差°", "模长残差mg",
            "标准差X mg", "标准差Y mg", "标准差Z mg", "有效帧", "剔除率", "温度°C", "原始数据", "补偿数据"
        };
        var detail = new List<object?[]> { header };
        foreach (var p in r.Points)
        {
            var line = new List<object?> { p.Index, p.InnerCommandDeg, p.OuterCommandDeg, p.InnerActualDeg, p.OuterActualDeg };
            line.AddRange(p.ReferenceG.Cast<object?>());
            line.AddRange(p.CorrectedMeanG.Cast<object?>());
            line.AddRange(p.AxisErrorG.Select(x => (object?)(x * 1000)));
            line.Add(p.VectorErrorG * 1000); line.Add(p.DirectionErrorDeg); line.Add(p.NormErrorG * 1000);
            line.AddRange(p.CorrectedStdG.Select(x => (object?)(x * 1000)));
            line.Add(p.AcceptedSamples); line.Add(p.RejectedFraction); line.Add(p.MeanTemperatureC);
            line.Add(p.RawCsv); line.Add(p.CorrectedCsv);
            detail.Add(line.ToArray());
        }
        using var archive = ZipFile.Open(file, ZipArchiveMode.Create);
        Add(archive, "[Content_Types].xml", "<?xml version='1.0' encoding='utf-8'?><Types xmlns='http://schemas.openxmlformats.org/package/2006/content-types'>" +
            "<Default Extension='rels' ContentType='application/vnd.openxmlformats-package.relationships+xml'/>" +
            "<Default Extension='xml' ContentType='application/xml'/>" +
            "<Override PartName='/xl/workbook.xml' ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml'/>" +
            "<Override PartName='/xl/worksheets/sheet1.xml' ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml'/>" +
            "<Override PartName='/xl/worksheets/sheet2.xml' ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml'/></Types>");
        Add(archive, "_rels/.rels", "<?xml version='1.0' encoding='utf-8'?><Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'>" +
            "<Relationship Id='rId1' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument' Target='xl/workbook.xml'/></Relationships>");
        Add(archive, "xl/workbook.xml", "<?xml version='1.0' encoding='utf-8'?><workbook xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main' xmlns:r='http://schemas.openxmlformats.org/officeDocument/2006/relationships'>" +
            "<sheets><sheet name='Summary' sheetId='1' r:id='rId1'/><sheet name='Points' sheetId='2' r:id='rId2'/></sheets></workbook>");
        Add(archive, "xl/_rels/workbook.xml.rels", "<?xml version='1.0' encoding='utf-8'?><Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'>" +
            "<Relationship Id='rId1' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet' Target='worksheets/sheet1.xml'/>" +
            "<Relationship Id='rId2' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet' Target='worksheets/sheet2.xml'/></Relationships>");
        Add(archive, "xl/worksheets/sheet1.xml", Sheet(overview));
        Add(archive, "xl/worksheets/sheet2.xml", Sheet(detail));
    }
}
