using System.Globalization;
using System.Text;
using Dts.Core;
using Dts.TestEngine;

namespace Dts.Tests.S1.CT14;

public static class Ct14Algorithm
{
    private const double Rad = Math.PI / 180d;

    public static void Validate(Ct14Settings s, bool safetyRequired = true)
    {
        if (s.MountIndex < 1 || s.MountIndex > s.PlannedMounts || s.PlannedMounts is < 2 or > 10)
            throw new InvalidDataException("独立装夹次数应为2～10次，当前轮次必须位于计划范围内。");
        if (string.IsNullOrWhiteSpace(s.MountingProcedureNote) || s.MountingProcedureNote.Trim().Length < 3 ||
            s.MountingProcedureNote.Length > 500)
            throw new InvalidDataException("请记录真实装夹SOP、定位基准、紧固方式/扭矩及线缆布置（3～500字符）。");
        if (s.Poses.Count is < 3 or > 8 || s.Poses.Select(p => p.Index).Distinct().Count() != s.Poses.Count)
            throw new InvalidDataException("姿态数量应为3～8个，且姿态编号不能重复。");
        if (s.RepeatsPerPose is < 2 or > 5)
            throw new InvalidDataException("每个姿态重复采集次数应为2～5次。");
        if (!double.IsFinite(s.MotionSpeedDps) || s.MotionSpeedDps < 0.1 || s.MotionSpeedDps > 5)
            throw new InvalidDataException("转台定位速度应为0.1～5°/s。");
        if (!double.IsFinite(s.WarmupSeconds) || s.WarmupSeconds < 0 || s.WarmupSeconds > 1800 ||
            !double.IsFinite(s.SettleSeconds) || s.SettleSeconds < 2 || s.SettleSeconds > 300 ||
            !double.IsFinite(s.SampleSeconds) || s.SampleSeconds < 5 || s.SampleSeconds > 600)
            throw new InvalidDataException("预热0～1800秒、姿态静置2～300秒、采集5～600秒。");
        if (!double.IsFinite(s.PositionToleranceDeg) || s.PositionToleranceDeg <= 0 || s.PositionToleranceDeg > 0.5)
            throw new InvalidDataException("转台到位容差应在(0,0.5]°。");
        if (!double.IsFinite(s.AllowedMinDeg) || !double.IsFinite(s.AllowedMaxDeg) ||
            s.AllowedMinDeg < 0 || s.AllowedMaxDeg > 360 || s.AllowedMinDeg >= s.AllowedMaxDeg ||
            s.AllowedMinDeg > 0 || s.AllowedMaxDeg < 0)
            throw new InvalidDataException("允许行程须覆盖外轴0°停车位，且位于0～360°。");
        if (s.MinValidSamples is < 50 or > 1_000_000 ||
            !double.IsFinite(s.MaxOutlierFraction) || s.MaxOutlierFraction is < 0 or > 0.30)
            throw new InvalidDataException("最少有效帧应≥50，最大异常剔除比例应为0～0.30。");
        if (!s.Poses.Any(p => Math.Abs(Wrap(p.InnerDeg)) < 1e-9 && Math.Abs(Wrap(p.OuterDeg)) < 1e-9))
            throw new InvalidDataException("姿态计划必须包含内轴0°/外轴0°基准姿态。");
        foreach (var p in s.Poses)
            if (!double.IsFinite(p.InnerDeg) || !double.IsFinite(p.OuterDeg) ||
                p.InnerDeg < s.AllowedMinDeg || p.InnerDeg > s.AllowedMaxDeg ||
                p.OuterDeg < s.AllowedMinDeg || p.OuterDeg > s.AllowedMaxDeg)
                throw new InvalidDataException($"姿态{p.Index}超出声明的允许行程。");
        if (safetyRequired && (!s.DirectionAndCablingApproved || !s.HardwareSafetyConfirmed))
            throw new InvalidOperationException("开始前必须确认装夹定位、轴向、线缆、真实限位及实体急停。");
    }

    public static double Wrap(double deg) => ((deg + 180) % 360 + 360) % 360 - 180;
    public static double Distance(double a, double b) => Math.Abs(Wrap(a - b));
    public static double Norm(IReadOnlyList<double> v) => Math.Sqrt(v.Sum(x => x * x));

    public static double[] Gravity(double innerDeg, double outerDeg, int sign)
    {
        if (sign is not (1 or -1)) throw new InvalidDataException("ACC JSON gravity_sign必须为±1。");
        double i = innerDeg * Rad, o = outerDeg * Rad;
        return [sign * Math.Sin(i) * Math.Sin(o),
                sign * Math.Cos(i) * Math.Sin(o),
                sign * Math.Cos(o)];
    }

    public static double Angle(IReadOnlyList<double> a, IReadOnlyList<double> b)
    {
        double d = Norm(a) * Norm(b);
        if (d < 1e-12) throw new InvalidDataException("加速度模长不足，无法计算方向差。");
        double dot = Enumerable.Range(0, 3).Sum(i => a[i] * b[i]);
        return Math.Acos(Math.Clamp(dot / d, -1, 1)) / Rad;
    }

    private static double Median(IEnumerable<double> source)
    {
        var a = source.OrderBy(x => x).ToArray();
        if (a.Length == 0) throw new InvalidDataException("无有效样本。");
        return a.Length % 2 == 1 ? a[a.Length / 2] : (a[a.Length / 2 - 1] + a[a.Length / 2]) / 2;
    }

    public static (Ct14Visit Visit, bool[] Accepted, double[][] Acc, double[][] Gyro) Analyze(
        Ct14Settings s, Ct14Pose pose, int repeat,
        RealTableFeedback before, RealTableFeedback after, StaticPointSamples capture,
        Func<double, double, double, double[]> accApply,
        Func<double, double, double, double[]> gyroApply,
        int gravitySign, string physicalCsv, string correctedCsv)
    {
        var samples = capture.Samples;
        if (samples.Count < s.MinValidSamples || capture.Batches < 3)
            throw new InvalidDataException($"装夹{s.MountIndex}姿态{pose.Index}采样不足：{samples.Count}帧/{capture.Batches}批。");
        var raw = samples.Select(v => new[] { v.AxG, v.AyG, v.AzG, v.GxDps, v.GyDps, v.GzDps }).ToArray();
        if (raw.Any(v => v.Any(x => !double.IsFinite(x))))
            throw new InvalidDataException("真实六轴样本含NaN或无穷值。");

        var med = Enumerable.Range(0, 6).Select(j => Median(raw.Select(v => v[j]))).ToArray();
        var mad = Enumerable.Range(0, 6).Select(j =>
            Math.Max(j < 3 ? 0.00015 : 0.14,
                1.4826 * Median(raw.Select(v => Math.Abs(v[j] - med[j]))))).ToArray();
        var accepted = raw.Select(v => Enumerable.Range(0, 6)
            .All(j => Math.Abs(v[j] - med[j]) <= 4.5 * mad[j])).ToArray();
        var keep = Enumerable.Range(0, raw.Length).Where(i => accepted[i]).ToArray();
        double rejected = 1 - keep.Length / (double)raw.Length;
        if (keep.Length < s.MinValidSamples || rejected > s.MaxOutlierFraction)
            throw new InvalidDataException($"装夹{s.MountIndex}姿态{pose.Index}有效帧不足或异常剔除率过高：{keep.Length}/{raw.Length}，剔除{rejected:P2}。");

        var acc = raw.Select(v => accApply(v[0], v[1], v[2])).ToArray();
        var gyro = raw.Select(v => gyroApply(v[3], v[4], v[5])).ToArray();
        if (acc.Any(v => v.Length != 3 || v.Any(x => !double.IsFinite(x))) ||
            gyro.Any(v => v.Length != 3 || v.Any(x => !double.IsFinite(x))))
            throw new InvalidDataException("ACC/Gyro标定矩阵输出无效。");

        double[] Mean(double[][] x) => Enumerable.Range(0, 3).Select(j => keep.Average(i => x[i][j])).ToArray();
        double[] Std(double[][] x, double[] m) => Enumerable.Range(0, 3)
            .Select(j => Math.Sqrt(keep.Sum(i => Math.Pow(x[i][j] - m[j], 2)) / Math.Max(1, keep.Length - 1))).ToArray();
        var am = Mean(acc); var gm = Mean(gyro);
        var ast = Std(acc, am); var gst = Std(gyro, gm);
        double inner = (before.Inner.PositionDeg + Wrap(after.Inner.PositionDeg - before.Inner.PositionDeg) / 2 + 360) % 360;
        double outer = (before.Outer.PositionDeg + Wrap(after.Outer.PositionDeg - before.Outer.PositionDeg) / 2 + 360) % 360;
        var reference = Gravity(inner, outer, gravitySign);
        double norm = Norm(am);
        if (norm < 0.7 || norm > 1.3)
            throw new InvalidDataException($"校正ACC模长{norm:F5}g超出0.7～1.3g诊断范围。");
        double[] diff = Enumerable.Range(0, 3).Select(j => am[j] - reference[j]).ToArray();
        var temps = keep.Select(i => samples[i].TemperatureC).Where(double.IsFinite).ToArray();
        double temp = temps.Length > 0 ? temps.Average() : capture.TemperatureC;
        if (!double.IsFinite(temp)) throw new InvalidDataException("采集结果没有有效芯片温度。");

        var visit = new Ct14Visit(s.MountIndex, 0, pose.Index, repeat,
            pose.InnerDeg, pose.OuterDeg, inner, outer, reference, am, ast, gm, gst,
            Norm(diff) * 1000, Angle(am, reference), norm, temp,
            raw.Length, keep.Length, rejected, capture.Batches, capture.DuplicateBatches,
            physicalCsv, correctedCsv, capture.StartedUtc, capture.EndedUtc);
        return (visit, accepted, acc, gyro);
    }

    public static Ct14Metrics? Summarize(IReadOnlyList<Ct14Visit> visits)
    {
        if (visits.Select(v => v.MountIndex).Distinct().Count() < 2) return null;
        var summaries = new List<Ct14MountPoseSummary>();
        var vectorErrors = new List<double>();
        var angleErrors = new List<double>();
        var accAxisSquares = new double[3]; var accAxisDf = new double[3];
        var gyroAxisSquares = new double[3]; var gyroAxisDf = new double[3];

        foreach (var pg in visits.GroupBy(v => v.PoseIndex).OrderBy(g => g.Key))
        {
            var mountMeans = pg.GroupBy(v => v.MountIndex).OrderBy(g => g.Key).Select(mg =>
            {
                var first = mg.First();
                return new
                {
                    Mount = mg.Key, First = first,
                    Acc = Enumerable.Range(0, 3).Select(j => mg.Average(v => v.AccCorrectedMeanG[j])).ToArray(),
                    Gyro = Enumerable.Range(0, 3).Select(j => mg.Average(v => v.GyroCorrectedMeanDps[j])).ToArray(),
                    Temp = mg.Average(v => v.MeanTemperatureC)
                };
            }).ToArray();
            var centerA = Enumerable.Range(0, 3).Select(j => mountMeans.Average(m => m.Acc[j])).ToArray();

            foreach (var m in mountMeans)
            {
                summaries.Add(new Ct14MountPoseSummary(m.Mount, pg.Key,
                    m.First.InnerTargetDeg, m.First.OuterTargetDeg, pg.Count(v => v.MountIndex == m.Mount),
                    m.Acc, m.Gyro, Norm(m.Acc), m.Temp));
            }
            if (mountMeans.Length >= 2)
            {
                foreach (var m in mountMeans)
                {
                    var da = Enumerable.Range(0, 3).Select(j => m.Acc[j] - centerA[j]).ToArray();
                    vectorErrors.Add(Norm(da) * 1000);
                    angleErrors.Add(Angle(m.Acc, centerA));
                }
                for (int j = 0; j < 3; j++)
                {
                    double av = mountMeans.Average(m => m.Acc[j]);
                    double gv = mountMeans.Average(m => m.Gyro[j]);
                    accAxisSquares[j] += mountMeans.Sum(m => Math.Pow(m.Acc[j] - av, 2)) * 1_000_000;
                    gyroAxisSquares[j] += mountMeans.Sum(m => Math.Pow(m.Gyro[j] - gv, 2));
                    accAxisDf[j] += mountMeans.Length - 1;
                    gyroAxisDf[j] += mountMeans.Length - 1;
                }
            }
        }
        if (vectorErrors.Count == 0) return null;
        var accStd = Enumerable.Range(0, 3).Select(j => Math.Sqrt(accAxisSquares[j] / accAxisDf[j])).ToArray();
        var gyroStd = Enumerable.Range(0, 3).Select(j => Math.Sqrt(gyroAxisSquares[j] / gyroAxisDf[j])).ToArray();
        double Pooled(Func<Ct14Visit, double> get) => Math.Sqrt(visits.Sum(v =>
            (v.AcceptedSamples - 1) * Math.Pow(get(v), 2)) / Math.Max(1, visits.Sum(v => v.AcceptedSamples - 1)));
        var temps = visits.Select(v => v.MeanTemperatureC).Where(double.IsFinite).ToArray();
        return new Ct14Metrics(visits.Select(v => v.MountIndex).Distinct().Count(),
            visits.Select(v => v.PoseIndex).Distinct().Count(), visits.Count,
            visits.Sum(v => v.AcceptedSamples), accStd,
            vectorErrors.Count > 0 ? Math.Sqrt(vectorErrors.Average(x => x * x)) : double.NaN,
            vectorErrors.Count > 0 ? vectorErrors.Max() : double.NaN,
            angleErrors.Count > 0 ? Math.Sqrt(angleErrors.Average(x => x * x)) : double.NaN,
            gyroStd,
            Enumerable.Range(0, 3).Select(j => Pooled(v => v.AccWithinStdG[j]) * 1000).ToArray(),
            Enumerable.Range(0, 3).Select(j => Pooled(v => v.GyroWithinStdDps[j])).ToArray(),
            temps.Length > 0 ? temps.Min() : double.NaN, temps.Length > 0 ? temps.Max() : double.NaN,
            summaries);
    }

    public static async Task SaveCorrectedCsvAsync(string path, StaticPointSamples capture,
        bool[] accepted, double[][] acc, double[][] gyro, CancellationToken ct)
    {
        await using var fs = new FileStream(path, FileMode.CreateNew, FileAccess.Write, FileShare.Read, 32768, FileOptions.Asynchronous);
        await using var w = new StreamWriter(fs, new UTF8Encoding(true));
        await w.WriteLineAsync("index,accepted,acc_x_cal_g,acc_y_cal_g,acc_z_cal_g,gyro_x_cal_dps,gyro_y_cal_dps,gyro_z_cal_dps,chip_temp_c");
        var ci = CultureInfo.InvariantCulture;
        for (int i = 0; i < acc.Length; i++)
        {
            ct.ThrowIfCancellationRequested();
            var row = new[] { i.ToString(ci), accepted[i] ? "1" : "0" }
                .Concat(acc[i].Select(v => v.ToString("G17", ci)))
                .Concat(gyro[i].Select(v => v.ToString("G17", ci)))
                .Append(capture.Samples[i].TemperatureC.ToString("G17", ci));
            await w.WriteLineAsync(string.Join(",", row));
        }
        await w.FlushAsync(ct);
    }
}
