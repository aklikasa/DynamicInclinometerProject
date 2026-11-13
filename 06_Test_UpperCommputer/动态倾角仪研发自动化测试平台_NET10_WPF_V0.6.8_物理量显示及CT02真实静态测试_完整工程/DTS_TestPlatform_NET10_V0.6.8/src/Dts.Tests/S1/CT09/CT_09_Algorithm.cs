using System.Globalization;
using System.Text;
using Dts.Core;
using Dts.TestEngine;

namespace Dts.Tests.S1.CT09;

public static class Ct09Algorithm
{
    public static void Validate(Ct09Settings s, bool safetyRequired = true)
    {
        if (s.Poses.Count < 3 || s.Poses.Count > 12)
            throw new InvalidDataException("姿态数量应为3～12个。");
        if (s.Poses.Select(p => p.Index).Distinct().Count() != s.Poses.Count)
            throw new InvalidDataException("姿态编号重复。");
        if (s.RepeatsPerPose is < 2 or > 10)
            throw new InvalidDataException("每个姿态重复采集次数应为2～10次。");
        if (!double.IsFinite(s.MotionSpeedDps) || s.MotionSpeedDps < 0.1 || s.MotionSpeedDps > 5)
            throw new InvalidDataException("姿态定位速度应为0.1～5°/s。");
        if (!double.IsFinite(s.SettleSeconds) || s.SettleSeconds < 2 || s.SettleSeconds > 300 ||
            !double.IsFinite(s.SampleSeconds) || s.SampleSeconds < 5 || s.SampleSeconds > 600)
            throw new InvalidDataException("静置时间应为2～300秒，采集时间应为5～600秒。");
        if (!double.IsFinite(s.PositionToleranceDeg) || s.PositionToleranceDeg <= 0 || s.PositionToleranceDeg > 0.5)
            throw new InvalidDataException("转台到位容差应在(0,0.5]°。");
        if (!double.IsFinite(s.AllowedMinDeg) || !double.IsFinite(s.AllowedMaxDeg) ||
            s.AllowedMinDeg < 0 || s.AllowedMaxDeg > 360 || s.AllowedMinDeg >= s.AllowedMaxDeg)
            throw new InvalidDataException("声明的转台允许行程须位于0～360°。");
        if (s.MinValidSamples is < 50 or > 1_000_000 ||
            !double.IsFinite(s.MaxOutlierFraction) || s.MaxOutlierFraction is < 0 or > 0.30)
            throw new InvalidDataException("最少有效帧应≥50，最大剔除比例应为0～0.30。");
        if (!s.Poses.Any(p => Math.Abs(Wrap(p.InnerDeg)) < 1e-9 && Math.Abs(Wrap(p.OuterDeg)) < 1e-9))
            throw new InvalidDataException("姿态计划必须包含内轴0°/外轴0°基准姿态。");
        foreach (var p in s.Poses)
        {
            if (!double.IsFinite(p.InnerDeg) || !double.IsFinite(p.OuterDeg) ||
                p.InnerDeg < s.AllowedMinDeg || p.InnerDeg > s.AllowedMaxDeg ||
                p.OuterDeg < s.AllowedMinDeg || p.OuterDeg > s.AllowedMaxDeg)
                throw new InvalidDataException($"姿态{p.Index}超出声明的机械允许行程。");
        }
        if (safetyRequired && (!s.DirectionAndCablingApproved || !s.HardwareSafetyConfirmed))
            throw new InvalidOperationException("开始前必须确认轴向、夹具/线缆路径、真实限位和实体急停。");
    }

    public static double Wrap(double a) => ((a % 360) + 360) % 360;
    public static double Distance(double a, double b)
    {
        double d = Math.Abs(Wrap(a) - Wrap(b));
        return Math.Min(d, 360 - d);
    }

    private static double Median(IEnumerable<double> values)
    {
        var v = values.OrderBy(x => x).ToArray();
        if (v.Length == 0) throw new InvalidDataException("没有可用样本。");
        return v.Length % 2 == 1 ? v[v.Length / 2] : (v[v.Length / 2 - 1] + v[v.Length / 2]) / 2;
    }

    public static (Ct09Visit Visit, bool[] Accepted, double[][] CorrectedGyro) Analyze(
        Ct09Pose pose, int repeat, RealTableFeedback before, RealTableFeedback after,
        StaticPointSamples capture, Func<double, double, double, double[]> compensate,
        Ct09Settings settings, string physicalCsv, string correctedCsv)
    {
        var samples = capture.Samples;
        if (samples.Count < settings.MinValidSamples || capture.Batches < 3)
            throw new InvalidDataException($"姿态{pose.Index}重复{repeat}采样不足：{samples.Count}帧/{capture.Batches}批。");
        var raw = samples.Select(v => new[] { v.GxDps, v.GyDps, v.GzDps }).ToArray();
        if (raw.Any(v => v.Any(x => !double.IsFinite(x))))
            throw new InvalidDataException("Gyro真实样本含NaN或无穷值。");

        var med = Enumerable.Range(0, 3).Select(j => Median(raw.Select(v => v[j]))).ToArray();
        var mad = Enumerable.Range(0, 3).Select(j =>
            Math.Max(0.005, 1.4826 * Median(raw.Select(v => Math.Abs(v[j] - med[j]))))).ToArray();
        var accepted = raw.Select(v => Enumerable.Range(0, 3)
            .All(j => Math.Abs(v[j] - med[j]) <= 4.5 * mad[j])).ToArray();
        var keep = Enumerable.Range(0, raw.Length).Where(i => accepted[i]).ToArray();
        double reject = 1 - keep.Length / (double)raw.Length;
        if (keep.Length < settings.MinValidSamples || reject > settings.MaxOutlierFraction)
            throw new InvalidDataException($"姿态{pose.Index}重复{repeat}异常值比例过高或有效帧不足：保留{keep.Length}/{raw.Length}。");

        var corrected = raw.Select(v => compensate(v[0], v[1], v[2])).ToArray();
        if (corrected.Any(v => v.Length != 3 || v.Any(x => !double.IsFinite(x))))
            throw new InvalidDataException("Gyro矩阵补偿结果无效。");
        var acceptedCorrected = keep.Select(i => corrected[i]).ToArray();
        double[] mean = Enumerable.Range(0, 3).Select(j => acceptedCorrected.Average(v => v[j])).ToArray();
        double[] std = Enumerable.Range(0, 3).Select(j => SampleStd(acceptedCorrected.Select(v => v[j]))).ToArray();
        var temps = keep.Select(i => samples[i].TemperatureC).Where(double.IsFinite).ToArray();
        double? temp = temps.Length == 0 ? null : temps.Average();
        var visit = new Ct09Visit(0, pose.Index, repeat, pose.InnerDeg, pose.OuterDeg,
            before.Inner.PositionDeg, before.Outer.PositionDeg, mean, std,
            Math.Sqrt(mean.Sum(x => x * x)), temp, raw.Length, keep.Length, reject,
            physicalCsv, correctedCsv, capture.StartedUtc, capture.EndedUtc);
        return (visit, accepted, corrected);
    }

    public static double SampleStd(IEnumerable<double> source)
    {
        var v = source.Where(double.IsFinite).ToArray();
        if (v.Length < 2) return double.NaN;
        double m = v.Average();
        return Math.Sqrt(v.Sum(x => (x - m) * (x - m)) / (v.Length - 1));
    }

    public static Ct09Metrics? Summarize(IReadOnlyList<Ct09Visit> visits)
    {
        if (visits.Count < 2) return null;
        var groups = visits.GroupBy(v => v.PoseIndex).OrderBy(g => g.Key).ToArray();
        var poseSummaries = new List<Ct09PoseSummary>();
        foreach (var g in groups)
        {
            var first = g.First();
            var mean = Enumerable.Range(0, 3).Select(j => g.Average(v => v.GyroCorrectedMeanDps[j])).ToArray();
            double?[] between = Enumerable.Range(0, 3).Select(j =>
                g.Count() >= 2 ? SampleStd(g.Select(v => v.GyroCorrectedMeanDps[j])) : (double?)null).ToArray();
            var poseTemps = g.Where(v => v.MeanTemperatureC.HasValue && double.IsFinite(v.MeanTemperatureC.Value))
                .Select(v => v.MeanTemperatureC!.Value).ToArray();
            double? poseTempMean = poseTemps.Length == 0 ? null : poseTemps.Average();
            poseSummaries.Add(new Ct09PoseSummary(g.Key, first.InnerTargetDeg, first.OuterTargetDeg,
                g.Count(), mean, between, Math.Sqrt(mean.Sum(x => x * x)), poseTempMean));
        }
        var grand = Enumerable.Range(0, 3).Select(j => poseSummaries.Average(p => p.MeanGyroDps[j])).ToArray();
        var range = Enumerable.Range(0, 3).Select(j => poseSummaries.Max(p => p.MeanGyroDps[j]) - poseSummaries.Min(p => p.MeanGyroDps[j])).ToArray();
        var pooled = Enumerable.Range(0, 3).Select(j =>
        {
            double numerator = 0, denominator = 0;
            foreach (var v in visits)
            {
                double sd = v.GyroWithinStdDps[j];
                if (!double.IsFinite(sd) || v.AcceptedSamples < 2) continue;
                numerator += (v.AcceptedSamples - 1) * sd * sd;
                denominator += v.AcceptedSamples - 1;
            }
            return denominator > 0 ? Math.Sqrt(numerator / denominator) : double.NaN;
        }).ToArray();
        double maxPoseVector = poseSummaries.Max(p =>
            Math.Sqrt(Enumerable.Range(0, 3).Sum(j => Math.Pow(p.MeanGyroDps[j] - grand[j], 2))));
        double maxPoseNorm = poseSummaries.Max(p => p.ZeroRateNormDps);
        var t = visits.Where(v => v.MeanTemperatureC.HasValue && double.IsFinite(v.MeanTemperatureC.Value))
            .Select(v => v.MeanTemperatureC!.Value).ToArray();
        return new Ct09Metrics(groups.Length, visits.Count, visits.Sum(v => v.AcceptedSamples),
            grand, range, pooled, maxPoseVector, maxPoseNorm,
            t.Length == 0 ? null : t.Min(), t.Length == 0 ? null : t.Max(),
            poseSummaries);
    }

    public static async Task SaveCorrectedCsvAsync(string file, StaticPointSamples capture,
        bool[] accepted, double[][] corrected, CancellationToken ct)
    {
        await using var stream = new FileStream(file, FileMode.CreateNew, FileAccess.Write,
            FileShare.Read, 32768, FileOptions.Asynchronous);
        await using var writer = new StreamWriter(stream, new UTF8Encoding(true));
        await writer.WriteLineAsync("index,accepted,gyro_x_corrected_dps,gyro_y_corrected_dps,gyro_z_corrected_dps,temperature_c");
        var ci = CultureInfo.InvariantCulture;
        for (int i = 0; i < corrected.Length; i++)
        {
            ct.ThrowIfCancellationRequested();
            var sample = capture.Samples[i];
            string line = string.Join(",", i.ToString(ci), accepted[i] ? "1" : "0",
                corrected[i][0].ToString("G17", ci), corrected[i][1].ToString("G17", ci),
                corrected[i][2].ToString("G17", ci), sample.TemperatureC.ToString("G17", ci));
            await writer.WriteLineAsync(line);
        }
        await writer.FlushAsync(ct);
    }
}
