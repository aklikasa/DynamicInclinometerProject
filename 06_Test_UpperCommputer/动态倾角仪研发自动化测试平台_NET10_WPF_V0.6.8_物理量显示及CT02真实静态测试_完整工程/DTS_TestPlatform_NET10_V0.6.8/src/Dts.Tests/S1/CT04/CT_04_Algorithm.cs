using Dts.TestEngine;
using System.Text.Json;

namespace Dts.Tests.S1.CT04;

/// <summary>
/// CT-04 三维重力参考计算与鲁棒统计。与 Python form_imu_calibration.py 保持一致：
/// R = Rx(outer) @ Rz(inner)，reference_P = R.T @ [0,0,gravity_sign]。
/// 测试使用实时反馈角度，不能用发送的目标角冒充参考角。
/// </summary>
public static class Ct04Algorithm
{
    public const string GridPlan = "自定义对向NxM网格";
    private const int MaxGridPoints = 144;
    private const double Rad = Math.PI / 180d;

    /// <summary>所有方案强制组成外轴相差180°的对向组；单姿态的参考重力模长始终1g。</summary>
    public static IReadOnlyList<Ct04Pose> BuildPlan(string kind,
        int innerDivisions = 6, int outerDivisions = 6,
        double innerStartDeg = 0, double outerStartDeg = 0)
    {
        double[] inner, outer;
        if (kind == GridPlan)
        {
            if (innerDivisions is < 2 or > 12 || outerDivisions is < 2 or > 12 ||
                outerDivisions % 2 != 0 || innerDivisions * outerDivisions > MaxGridPoints)
                throw new InvalidDataException("内轴2~12等分；外轴必须为偶数2~12等分；总工位不超过144");
            if (!double.IsFinite(innerStartDeg) || !double.IsFinite(outerStartDeg) ||
                innerStartDeg < 0 || innerStartDeg >= 360 ||
                outerStartDeg < 0 || outerStartDeg >= 360)
                throw new InvalidDataException("内外轴起始角都必须在[0,360)°");
            inner = Enumerable.Range(0, innerDivisions)
                .Select(k => Normalize360(innerStartDeg + 360d * k / innerDivisions)).ToArray();
            outer = Enumerable.Range(0, outerDivisions)
                .Select(k => Normalize360(outerStartDeg + 360d * k / outerDivisions)).ToArray();
        }
        else if (kind == "标准12点(6对对向)")
        {
            inner = [17, 77, 137];
            outer = [25, 75, 205, 255];
        }
        else if (kind == "增强24点(12对对向)")
        {
            inner = [19, 79, 139, 199];
            outer = [21, 81, 141, 201, 261, 321];
        }
        else throw new ArgumentException("不支持的CT-04扫描方案：" + kind);
        var result = new List<Ct04Pose>();
        for (int i = 0; i < inner.Length; i++)
        {
            var sweep = i % 2 == 0 ? outer : outer.Reverse();
            foreach (double o in sweep)
                result.Add(new Ct04Pose(result.Count + 1, inner[i], o,
                    $"I{inner[i]:0.###}_O{o:0.###}"));
        }
        return result;
    }

    public static IReadOnlyList<Ct04Pose> BuildPlan(Ct04Settings settings) =>
        BuildPlan(settings.PlanKind, settings.InnerDivisions, settings.OuterDivisions,
            settings.InnerStartDeg, settings.OuterStartDeg);

    private static double Normalize360(double degrees)
    {
        double value = (degrees % 360 + 360) % 360;
        return value >= 360 - 1e-9 ? 0 : value;
    }

    public static void ValidatePlan(Ct04Settings s, IReadOnlyList<Ct04Pose> plan)
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
        // +g/-g pairs require at least 180° separation on outer axis.
        // Every CT-04 plan is a full-range plan; never infer permission from a check box alone.
        if (!s.FullRangeApproved)
            throw new InvalidOperationException("CT-04对向扫描须现场批准包含180°对向的全范围行程和电缆安全");
        if (plan.Any(p => p.InnerTargetDeg < s.AllowedMinDeg || p.InnerTargetDeg > s.AllowedMaxDeg ||
                          p.OuterTargetDeg < s.AllowedMinDeg || p.OuterTargetDeg > s.AllowedMaxDeg))
            throw new InvalidOperationException("计划有目标超出已批准的绝对角度行程");
        if (0 < s.AllowedMinDeg || 0 > s.AllowedMaxDeg)
            throw new InvalidOperationException("逐组扫描需要外轴可安全到0°作为内轴切换前的过渡位置");
        if (plan.Select(p => (p.InnerTargetDeg, p.OuterTargetDeg)).Distinct().Count() != plan.Count)
            throw new InvalidOperationException("测试计划包含重复姿态");
        if (CountTargetPairs(plan) * 2 != plan.Count)
            throw new InvalidOperationException("计划未形成完整的反向重力配对；请修改起始角或等分数");
    }

    /// <summary>
    /// 某些不同的机械角度对只有相同重力矢量（例如外轴为0°）。
    /// 使用0.05°角距离消除同向量重复；与运动位置去重是两回事。
    /// </summary>
    public static int CountDistinctGravityDirections(IReadOnlyList<Ct04Pose> plan,
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
    public static int? CountHistoricalGravityOverlaps(IReadOnlyList<Ct04Pose> plan, string accJson,
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
    public static (Ct04PointResult Point, bool[] Accepted, double[][] Corrected)
        Analyze(Ct04Pose pose, RealTableFeedback before, RealTableFeedback after,
            StaticPointSamples capture, Func<double[], double[]> calibrate, Ct04Settings settings,
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
        return (new Ct04PointResult(pose.Index, pose.Label, pose.InnerTargetDeg, pose.OuterTargetDeg,
            inner, outer, reference, rawMean, correctedMean, error, std,
            VectorError(correctedMean, reference), DirectionError(correctedMean, reference),
            norm, norm - 1, raw.Length, valid, rejectedFraction,
            capture.Batches, capture.DuplicateBatches, temperature,
            rawCsv, correctedCsv, capture.StartedUtc, capture.EndedUtc), accepted, corrected);
    }

    public static Ct04Metrics Summarize(IReadOnlyList<Ct04PointResult> points)
    {
        if (points.Count == 0) throw new InvalidOperationException("无实测数据不能计算结果");
        static double Rms(IEnumerable<double> x) => Math.Sqrt(x.Average(v => v * v));
        double[] bias = Enumerable.Range(0, 3).Select(j => points.Average(p => p.AxisErrorG[j])).ToArray();
        double[] rmse = Enumerable.Range(0, 3).Select(j => Rms(points.Select(p => p.AxisErrorG[j]))).ToArray();
        double[] max = Enumerable.Range(0, 3).Select(j => points.Max(p => Math.Abs(p.AxisErrorG[j]))).ToArray();
        return new Ct04Metrics(points.Count, points.Sum(p => p.AcceptedSamples), bias, rmse, max,
            Rms(points.Select(p => p.VectorErrorG)), points.Max(p => p.VectorErrorG),
            Rms(points.Select(p => p.DirectionErrorDeg)), points.Max(p => p.DirectionErrorDeg),
            Rms(points.Select(p => p.NormErrorG)), points.Max(p => Math.Abs(p.NormErrorG)),
            points.Min(p => p.MeanTemperatureC), points.Max(p => p.MeanTemperatureC));
    }
    /// <summary>按相同内轴、外轴目标相差180°生成唯一对向配对；不靠扫描序号配对。</summary>
    public static int CountTargetPairs(IReadOnlyList<Ct04Pose> plan)
    {
        var paired = new HashSet<int>();
        int count = 0;
        foreach (var a in plan)
        {
            if (paired.Contains(a.Index)) continue;
            var b = plan.FirstOrDefault(x => x.Index != a.Index && !paired.Contains(x.Index) &&
                Distance(x.InnerTargetDeg, a.InnerTargetDeg) < 0.00001 &&
                Math.Abs(Distance(x.OuterTargetDeg, a.OuterTargetDeg) - 180d) < 0.00001);
            if (b is null) continue;
            paired.Add(a.Index); paired.Add(b.Index); count++;
        }
        return count;
    }

    /// <summary>正负向误差偶分量 (e+ + e-)/2；误差奇分量 (e+ - e-)/2；e=a_cal-g_feedback。</summary>
    public static IReadOnlyList<Ct04PairResult> PairDiagnostics(IReadOnlyList<Ct04PointResult> points)
    {
        var paired = new HashSet<int>();
        var result = new List<Ct04PairResult>();
        foreach (var a in points.OrderBy(p => p.Index))
        {
            if (paired.Contains(a.Index)) continue;
            var b = points.FirstOrDefault(p => p.Index != a.Index && !paired.Contains(p.Index) &&
                Distance(p.InnerCommandDeg, a.InnerCommandDeg) < 0.00001 &&
                Math.Abs(Distance(p.OuterCommandDeg, a.OuterCommandDeg) - 180d) < 0.00001);
            if (b is null) continue; // Partial interrupted run may contain only one half of a pair.
            double dot = Enumerable.Range(0,3).Sum(j => a.ReferenceG[j]*b.ReferenceG[j]);
            if (dot > -Math.Cos(1 * Rad))
                throw new InvalidDataException($"对向工位{a.Index}/{b.Index}的实际反馈重力不是相反方向");
            // Subtract each actual-feedback reference before parity decomposition.
            // Otherwise small but permitted positioning asymmetry contaminates the bias estimate.
            double[] even = Enumerable.Range(0,3).Select(j =>
                (a.CorrectedMeanG[j]-a.ReferenceG[j] + b.CorrectedMeanG[j]-b.ReferenceG[j])/2).ToArray();
            double[] odd = Enumerable.Range(0,3).Select(j =>
                (a.CorrectedMeanG[j]-a.ReferenceG[j] - b.CorrectedMeanG[j]+b.ReferenceG[j])/2).ToArray();
            result.Add(new Ct04PairResult(result.Count+1, a.Index, b.Index,
                a.ReferenceG.ToArray(), even, Norm(even)*1000, odd,
                Norm(odd)*1000, Math.Abs(a.MeanTemperatureC-b.MeanTemperatureC)));
            paired.Add(a.Index); paired.Add(b.Index);
        }
        return result;
    }

    /// <summary>
    /// 仅作为[-1g,1g]静态重力投影的方向相关曲率代理：逐轴二次拟合与最佳一次拟合差。
    /// 不等同真实多幅值加速度量程非线性；包含潜在交叉轴/装配/姿态影响。
    /// </summary>
    public static IReadOnlyList<Ct04NonlinearityProxy> NonlinearityDiagnostics(
        IReadOnlyList<Ct04PointResult> points)
    {
        var result = new List<Ct04NonlinearityProxy>();
        if (points.Count < 8) return result;
        for (int axis = 0; axis < 3; axis++)
        {
            double[] x = points.Select(p => p.ReferenceG[axis]).ToArray();
            double[] y = points.Select(p => p.CorrectedMeanG[axis]).ToArray();
            if (x.Max()-x.Min() < 0.6) continue;
            double mx=x.Average(), my=y.Average();
            double denom=x.Sum(v => (v-mx)*(v-mx));
            if (denom < 1e-6) continue;
            double lineSlope=Enumerable.Range(0,x.Length).Sum(i => (x[i]-mx)*(y[i]-my))/denom;
            double lineIntercept=my-lineSlope*mx;
            var a=new double[3,4];
            for (int i=0;i<x.Length;i++)
            {
                double[] v=[1,x[i],x[i]*x[i]];
                for(int r=0;r<3;r++)
                {
                    for(int c=0;c<3;c++) a[r,c]+=v[r]*v[c];
                    a[r,3]+=v[r]*y[i];
                }
            }
            bool solvable=true;
            for(int col=0;col<3;col++)
            {
                int pivot=col;
                for(int r=col+1;r<3;r++) if(Math.Abs(a[r,col])>Math.Abs(a[pivot,col])) pivot=r;
                if(Math.Abs(a[pivot,col])<1e-9) { solvable=false; break; }
                for(int c=col;c<4;c++)
                {
                    double swap=a[pivot,c]; a[pivot,c]=a[col,c]; a[col,c]=swap;
                }
                double div=a[col,col];
                for(int c=col;c<4;c++) a[col,c]/=div;
                for(int r=0;r<3;r++) if(r!=col)
                {
                    double factor=a[r,col];
                    for(int c=col;c<4;c++) a[r,c]-=factor*a[col,c];
                }
            }
            if (!solvable) continue;
            double[] deviations=x.Select(v => (a[0,3]+a[1,3]*v+a[2,3]*v*v)-
                (lineIntercept+lineSlope*v)).ToArray();
            result.Add(new Ct04NonlinearityProxy("XYZ"[axis].ToString(), points.Count,
                x.Min(), x.Max(), a[2,3], deviations.Max(d => Math.Abs(d))*1000,
                Math.Sqrt(deviations.Average(d => d*d))*1000));
        }
        return result;
    }

}
