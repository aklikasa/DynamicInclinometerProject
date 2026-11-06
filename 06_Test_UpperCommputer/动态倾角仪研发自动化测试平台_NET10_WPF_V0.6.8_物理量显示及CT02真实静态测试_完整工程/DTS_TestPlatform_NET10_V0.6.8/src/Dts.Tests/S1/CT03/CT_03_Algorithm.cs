using Dts.TestEngine;
using System.Text.Json;

namespace Dts.Tests.S1.CT03;

/// <summary>
/// CT-03 三维重力参考计算与鲁棒统计。与 Python form_imu_calibration.py 保持一致：
/// R = Rx(outer) @ Rz(inner)，reference_P = R.T @ [0,0,gravity_sign]。
/// 测试使用实时反馈角度，不能用发送的目标角冒充参考角。
/// </summary>
public static class Ct03Algorithm
{
    public const string GridPlan = "自定义360°等分网格";
    private const int MaxGridPoints = 144;
    private const double Rad = Math.PI / 180d;

    public static IReadOnlyList<Ct03Pose> BuildPlan(string kind,
        int innerDivisions = 6, int outerDivisions = 6,
        double innerStartDeg = 0, double outerStartDeg = 0)
    {
        double[] inner;
        double[] outer;
        switch (kind)
        {
            case GridPlan:
                if (innerDivisions is < 2 or > 12 || outerDivisions is < 2 or > 12 ||
                    innerDivisions * outerDivisions > MaxGridPoints)
                    throw new InvalidDataException("自定义等分数每轴为2~12，最多144工位");
                if (!double.IsFinite(innerStartDeg) || !double.IsFinite(outerStartDeg) ||
                    innerStartDeg < 0 || innerStartDeg >= 360 ||
                    outerStartDeg < 0 || outerStartDeg >= 360)
                    throw new InvalidDataException("起始角必须为0~360°之间（不含360°）");
                // 360° / N, 不重复360°终点；每组交替外轴顺序以减少往返。
                // 具体运动轨迹仍由硬件层逐轴检查，不允许绕开安全限制。
                var innerAngles = Enumerable.Range(0, innerDivisions)
                    .Select(k => Normalize360(innerStartDeg + k * 360.0 / innerDivisions)).ToArray();
                var outerAngles = Enumerable.Range(0, outerDivisions)
                    .Select(k => Normalize360(outerStartDeg + k * 360.0 / outerDivisions)).ToArray();
                var grid = new List<Ct03Pose>(innerDivisions * outerDivisions);
                for (int i = 0; i < innerAngles.Length; ++i)
                {
                    var sweep = i % 2 == 0 ? outerAngles : outerAngles.Reverse();
                    foreach (var o in sweep)
                        grid.Add(new Ct03Pose(grid.Count + 1, innerAngles[i], o,
                            $"I{innerAngles[i]:0.###}_O{o:0.###}"));
                }
                return grid;
            case "局部12点(0~90°)":
                // 用于行程验证前的局部检查，不代表全空间验证。
                inner = [12, 36, 60, 84];
                outer = [18, 42, 66];
                break;
            case "全向24点(0~360°)":
                // 与历史 ACC 拟合12点和验证12点均不重合；覆盖多个象限。
                inner = [18, 78, 138, 198, 258, 318];
                outer = [25, 65, 115, 155];
                break;
            default:
                throw new ArgumentException("不支持的 CT-03 扫描计划：" + kind);
        }
        var points = new List<Ct03Pose>();
        // 每个内轴角完成一个外轴扫描，再退回外轴0°，再改变内轴角度。
        for (int i = 0; i < inner.Length; i++)
        {
            var sweep = i % 2 == 0 ? outer : outer.Reverse().ToArray();
            foreach (double o in sweep)
                points.Add(new Ct03Pose(points.Count + 1, inner[i], o,
                    $"I{inner[i]:0}_O{o:0}"));
        }
        return points;
    }

    public static IReadOnlyList<Ct03Pose> BuildPlan(Ct03Settings settings) =>
        BuildPlan(settings.PlanKind, settings.InnerDivisions, settings.OuterDivisions,
            settings.InnerStartDeg, settings.OuterStartDeg);

    private static double Normalize360(double degrees)
    {
        double value = (degrees % 360 + 360) % 360;
        return value >= 360 - 1e-9 ? 0 : value;
    }

    public static void ValidatePlan(Ct03Settings s, IReadOnlyList<Ct03Pose> plan)
    {
        var expected = BuildPlan(s);
        if (plan.Count != expected.Count ||
            !plan.Zip(expected).All(pair => pair.First.InnerTargetDeg == pair.Second.InnerTargetDeg &&
                pair.First.OuterTargetDeg == pair.Second.OuterTargetDeg))
            throw new InvalidDataException("扫描方案与冻结的参数不一致，请重新预览");
        if (!double.IsFinite(s.SpeedDps) || s.SpeedDps < 0.01 || s.SpeedDps > 5)
            throw new InvalidDataException("自动扫描速度应在 0.01~5 °/s 内");
        if (!double.IsFinite(s.SettleSeconds) || s.SettleSeconds < 1 || s.SettleSeconds > 120)
            throw new InvalidDataException("静置时间应为 1~120 秒");
        if (!double.IsFinite(s.SampleSeconds) || s.SampleSeconds < 2 || s.SampleSeconds > 120)
            throw new InvalidDataException("每姿态采样时长应为 2~120 秒");
        if (!double.IsFinite(s.PositionToleranceDeg) || s.PositionToleranceDeg <= 0 || s.PositionToleranceDeg > 0.5)
            throw new InvalidDataException("到位误差应为 0~0.5° 之间的正数");
        if (!double.IsFinite(s.AllowedMinDeg) || !double.IsFinite(s.AllowedMaxDeg) ||
            s.AllowedMinDeg < 0 || s.AllowedMaxDeg > 360 || s.AllowedMaxDeg <= s.AllowedMinDeg)
            throw new InvalidDataException("绝对角度行程必须在 0~360° 且上限大于下限");
        if (s.MinValidSamples < 50 || s.MinValidSamples > 1000000)
            throw new InvalidDataException("最小有效帧数应为 50~1000000");
        if (!double.IsFinite(s.MaxOutlierFraction) || s.MaxOutlierFraction < 0 || s.MaxOutlierFraction > 0.3)
            throw new InvalidDataException("最大剔除比例应为 0~0.3");
        if (!s.HardwareSafetyConfirmed || !s.DirectionAndCablingApproved)
            throw new InvalidOperationException("未完成真实机械急停、限位、线缆与绝对定位方向的现场确认");
        if ((s.PlanKind == "全向24点(0~360°)" || s.PlanKind == GridPlan) &&
            !s.FullRangeApproved)
            throw new InvalidOperationException("全向/自定义360°等分计划须额外确认机械行程和电缆绕转安全");
        if (plan.Any(p => p.InnerTargetDeg < s.AllowedMinDeg || p.InnerTargetDeg > s.AllowedMaxDeg ||
                          p.OuterTargetDeg < s.AllowedMinDeg || p.OuterTargetDeg > s.AllowedMaxDeg))
            throw new InvalidOperationException("计划有目标超出已批准的绝对角度行程");
        if (0 < s.AllowedMinDeg || 0 > s.AllowedMaxDeg)
            throw new InvalidOperationException("逐组扫描需要外轴可安全到0°作为内轴切换前的过渡位置");
        if (plan.Select(p => (p.InnerTargetDeg, p.OuterTargetDeg)).Distinct().Count() != plan.Count)
            throw new InvalidOperationException("测试计划包含重复姿态");
        // 旧12/24点预设用于独立验证，故避开历史正交标定姿态。
        // 用户指定的网格可包含这些姿态，但必须在预览/报告中明确标记重叠，
        // 不能把网格工位总数冒称为独立重力方向数。
        if (s.PlanKind != GridPlan && plan.Any(p =>
            p.InnerTargetDeg is 0 or 90 or 180 or 270 ||
            p.OuterTargetDeg is 0 or 90 or 180 or 270))
            throw new InvalidOperationException("独立预设计划不能复用标准正交标定姿态");
    }

    /// <summary>
    /// 某些不同的机械角度对只有相同重力矢量（例如外轴为0°）。
    /// 使用0.05°角距离消除同向量重复；与运动位置去重是两回事。
    /// </summary>
    public static int CountDistinctGravityDirections(IReadOnlyList<Ct03Pose> plan,
        int gravitySign = 1)
    {
        var uniques = new List<double[]>();
        foreach (var pose in plan)
        {
            var v = ReferenceGravity(pose.InnerTargetDeg, pose.OuterTargetDeg, gravitySign);
            if (!uniques.Any(u => SameDirection(u, v))) uniques.Add(v);
        }
        return uniques.Count;
    }

    private static bool SameDirection(IReadOnlyList<double> a, IReadOnlyList<double> b) =>
        Enumerable.Range(0, 3).Sum(j => a[j] * b[j]) >= Math.Cos(0.05 * Rad);

    /// <summary>与既有ACC JSON历史姿态的重力方向重合数，缺少记录时返回null。</summary>
    public static int? CountHistoricalGravityOverlaps(IReadOnlyList<Ct03Pose> plan, string accJson,
        int gravitySign = 1)
    {
        using var document = JsonDocument.Parse(File.ReadAllText(accJson));
        if (!document.RootElement.TryGetProperty("position_measurements", out var history) ||
            history.ValueKind != JsonValueKind.Array) return null;
        var references = new List<double[]>();
        foreach (var measurement in history.EnumerateArray())
        {
            if (measurement.TryGetProperty("inner_actual_mean_deg", out var inner) &&
                measurement.TryGetProperty("outer_actual_mean_deg", out var outer) &&
                inner.TryGetDouble(out var i) && outer.TryGetDouble(out var o) &&
                double.IsFinite(i) && double.IsFinite(o))
                references.Add(ReferenceGravity(i, o, gravitySign));
        }
        if (references.Count == 0) return null;
        return plan.Count(p =>
        {
            var v = ReferenceGravity(p.InnerTargetDeg, p.OuterTargetDeg, gravitySign);
            return references.Any(h => SameDirection(v, h));
        });
    }

    public static double Wrap(double deg) => ((deg + 180) % 360 + 360) % 360 - 180;
    public static double Distance(double a, double b) => Math.Abs(Wrap(a - b));
    public static double CircularMidpoint(double a, double b) => (a + Wrap(b - a) / 2 + 360) % 360;

    public static double[] ReferenceGravity(double innerDeg, double outerDeg, int sign)
    {
        if (sign is not (1 or -1)) throw new ArgumentException("重力符号只能是+1或-1");
        double i = innerDeg * Rad, o = outerDeg * Rad;
        // Rz(-inner) * Rx(-outer) * [0,0,sign].
        return [sign * Math.Sin(i) * Math.Sin(o),
                sign * Math.Cos(i) * Math.Sin(o),
                sign * Math.Cos(o)];
    }

    public static double Norm(IReadOnlyList<double> v) => Math.Sqrt(v.Sum(x => x * x));
    public static double VectorError(IReadOnlyList<double> measured, IReadOnlyList<double> reference) =>
        Math.Sqrt(Enumerable.Range(0, 3).Sum(j => Math.Pow(measured[j] - reference[j], 2)));
    public static double DirectionError(IReadOnlyList<double> measured, IReadOnlyList<double> reference)
    {
        double n = Norm(measured) * Norm(reference);
        if (!double.IsFinite(n) || n < 0.5) throw new InvalidDataException("向量模长不足以计算有效方向角");
        double dot = Enumerable.Range(0, 3).Sum(j => measured[j] * reference[j]);
        return Math.Acos(Math.Clamp(dot / n, -1, 1)) / Rad;
    }
    private static double Median(IEnumerable<double> values)
    {
        var a = values.OrderBy(v => v).ToArray();
        if (a.Length == 0) throw new InvalidDataException("没有可用样本");
        return a.Length % 2 == 1 ? a[a.Length / 2] : (a[a.Length / 2 - 1] + a[a.Length / 2]) / 2;
    }

    /// <summary>从已采集的真实物理量做 MAD 过滤，每一有效帧只应用一次 ACC JSON 矩阵。</summary>
    public static (Ct03PointResult Point, bool[] Accepted, double[][] Corrected)
        Analyze(Ct03Pose pose, RealTableFeedback before, RealTableFeedback after,
            StaticPointSamples capture, Func<double[], double[]> calibrate, Ct03Settings settings,
            int gravitySign, string rawCsv, string correctedCsv)
    {
        var samples = capture.Samples;
        if (samples.Count < settings.MinValidSamples || capture.Batches < 3)
            throw new InvalidDataException($"姿态{pose.Index}真实帧不足（{samples.Count}帧/{capture.Batches}批）");
        var raw = samples.Select(s => new[] { s.AxG, s.AyG, s.AzG }).ToArray();
        if (raw.Any(v => v.Any(x => !double.IsFinite(x))))
            throw new InvalidDataException($"姿态{pose.Index}包含无效加速度数据");
        double[] center = Enumerable.Range(0, 3).Select(j => Median(raw.Select(v => v[j]))).ToArray();
        double[] sigma = Enumerable.Range(0, 3).Select(j =>
            Math.Max(0.00015, 1.4826 * Median(raw.Select(v => Math.Abs(v[j] - center[j]))))).ToArray();
        bool[] accepted = raw.Select(v => Enumerable.Range(0, 3)
            .All(j => Math.Abs(v[j] - center[j]) <= 3.5 * sigma[j])).ToArray();
        int valid = accepted.Count(x => x);
        double rejectedFraction = 1.0 - valid / (double)raw.Length;
        if (valid < settings.MinValidSamples || rejectedFraction > settings.MaxOutlierFraction)
            throw new InvalidDataException($"姿态{pose.Index}有效帧{valid}或剔除比例{rejectedFraction:P2}不满足参数要求");
        var corrected = new double[raw.Length][];
        for (int k = 0; k < raw.Length; k++)
        {
            corrected[k] = calibrate(raw[k]);
            if (corrected[k] is not { Length: 3 } || corrected[k].Any(x => !double.IsFinite(x)))
                throw new InvalidDataException("ACC JSON 校正结果无效");
        }
        var kept = Enumerable.Range(0, corrected.Length).Where(k => accepted[k]).ToArray();
        double[] correctedMean = Enumerable.Range(0, 3).Select(j => kept.Average(k => corrected[k][j])).ToArray();
        double[] rawMean = Enumerable.Range(0, 3).Select(j => kept.Average(k => raw[k][j])).ToArray();
        double[] std = Enumerable.Range(0, 3).Select(j => Math.Sqrt(
            kept.Sum(k => Math.Pow(corrected[k][j] - correctedMean[j], 2)) / Math.Max(1, kept.Length - 1))).ToArray();
        double inner = CircularMidpoint(before.Inner.PositionDeg, after.Inner.PositionDeg);
        double outer = CircularMidpoint(before.Outer.PositionDeg, after.Outer.PositionDeg);
        var reference = ReferenceGravity(inner, outer, gravitySign);
        double norm = Norm(correctedMean);
        if (norm < 0.7 || norm > 1.3)
            throw new InvalidDataException($"姿态{pose.Index}校正后ACC模长{norm:F6}g超出0.7~1.3g诊断范围");
        var error = Enumerable.Range(0, 3).Select(j => correctedMean[j] - reference[j]).ToArray();
        double temperature = kept.Average(k => samples[k].TemperatureC);
        if (!double.IsFinite(temperature)) throw new InvalidDataException("没有有效芯片温度");
        return (new Ct03PointResult(pose.Index, pose.Label, pose.InnerTargetDeg, pose.OuterTargetDeg,
            inner, outer, reference, rawMean, correctedMean, error, std,
            VectorError(correctedMean, reference), DirectionError(correctedMean, reference),
            norm, norm - 1, raw.Length, valid, rejectedFraction,
            capture.Batches, capture.DuplicateBatches, temperature,
            rawCsv, correctedCsv, capture.StartedUtc, capture.EndedUtc), accepted, corrected);
    }

    public static Ct03Metrics Summarize(IReadOnlyList<Ct03PointResult> points)
    {
        if (points.Count == 0) throw new InvalidOperationException("无实测数据不能计算结果");
        static double Rms(IEnumerable<double> x) => Math.Sqrt(x.Average(v => v * v));
        double[] bias = Enumerable.Range(0, 3).Select(j => points.Average(p => p.AxisErrorG[j])).ToArray();
        double[] rmse = Enumerable.Range(0, 3).Select(j => Rms(points.Select(p => p.AxisErrorG[j]))).ToArray();
        double[] max = Enumerable.Range(0, 3).Select(j => points.Max(p => Math.Abs(p.AxisErrorG[j]))).ToArray();
        return new Ct03Metrics(points.Count, points.Sum(p => p.AcceptedSamples), bias, rmse, max,
            Rms(points.Select(p => p.VectorErrorG)), points.Max(p => p.VectorErrorG),
            Rms(points.Select(p => p.DirectionErrorDeg)), points.Max(p => p.DirectionErrorDeg),
            Rms(points.Select(p => p.NormErrorG)), points.Max(p => Math.Abs(p.NormErrorG)),
            points.Min(p => p.MeanTemperatureC), points.Max(p => p.MeanTemperatureC));
    }
}
