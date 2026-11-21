using System.Globalization;
using Dts.Tests.S1.CT10;

namespace Dts.Tests.S1.CT19;

public static class Ct19Algorithm
{
    public static readonly double[] DefaultRates = [4.5, 6, 7.5, 10, 15, 20, 30, 45, 60];

    public static double[] ParseRates(string raw)
    {
        var parts = (raw ?? "").Split(new[] { ',', '，', ';', '；', ' ', '\n', '\t' },
            StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
        if (parts.Length is < 1 or > 12)
            throw new InvalidDataException("CT-19支持设置1～12档速率");
        var rates = new List<double>();
        foreach (var part in parts)
        {
            if (!double.TryParse(part, NumberStyles.Float, CultureInfo.InvariantCulture, out double rate) ||
                !double.IsFinite(rate) || rate <= 0 || rate > 60)
                throw new InvalidDataException("速率必须大于0且不超过60°/s：" + part);
            if (rates.Any(x => Math.Abs(x-rate) < 1e-8))
                throw new InvalidDataException("速率档不能重复：" + part);
            rates.Add(rate);
        }
        return rates.ToArray();
    }

    public static IReadOnlyList<Ct10SweepRequest> PreviewPlan(Ct19Settings s)
    {
        var baseSettings = s.ToCt10Settings();
        return ParseRates(s.SpeedsCsv).SelectMany(rate =>
            Ct10Algorithm.PreviewPlan(baseSettings with
            {
                SpeedsCsv = rate.ToString("G17", CultureInfo.InvariantCulture)
            })).ToArray();
    }

    public static IReadOnlyList<Ct10SweepRequest> BuildPlan(Ct19Settings s, ICt10DynamicHardware hardware)
    {
        var baseSettings = s.ToCt10Settings();
        return ParseRates(s.SpeedsCsv).SelectMany(rate =>
            Ct10Algorithm.BuildPlan(baseSettings with
            {
                SpeedsCsv = rate.ToString("G17", CultureInfo.InvariantCulture)
            }, hardware)).ToArray();
    }

    public static void Validate(Ct19Settings s)
    {
        if (!Directory.Exists(s.OutputRoot))
            throw new DirectoryNotFoundException("报告目录不存在：" + s.OutputRoot);
        if (!s.TestInner && !s.TestOuter)
            throw new InvalidDataException("至少选择一个有真实编码器参考的轴：内轴/Gyro Z 或外轴/Gyro X");
        var preview = PreviewPlan(s);
        if (preview.Count == 0) throw new InvalidDataException("没有生成有效动态测试计划");
        foreach (var rate in ParseRates(s.SpeedsCsv))
        {
            if ((s.TravelMaxDeg - s.TravelMinDeg) / rate * 2.5 + 40 > 900)
                throw new InvalidDataException($"{rate:F3}°/s在当前扫描行程下预计超过15分钟安全超时，请提高速率或缩短扫描行程");
        }
        if (s.Calibration.Mode != Dts.Core.CalibrationMode.Ambient)
            throw new InvalidDataException("CT-19要求主界面选择当前UID匹配的常温ACC/Gyro JSON");
    }

    public static IReadOnlyList<Ct19GroupRow> Group(IReadOnlyList<Ct19RunRow> runs) =>
        runs.GroupBy(x => new { x.GyroAxis, x.RateDps, x.Direction })
            .Select(g => new Ct19GroupRow(g.Key.GyroAxis, g.Key.RateDps, g.Key.Direction,
                g.Count(), Mean(g.Select(x => x.MeanGyroDps)), Std(g.Select(x => x.MeanGyroDps)),
                Mean(g.Select(x => x.MeanResidualDps)), Std(g.Select(x => x.MeanResidualDps)),
                Mean(g.Select(x => x.MeanReferenceDps)), Std(g.Select(x => x.MeanReferenceDps)),
                g.Count() >= 2 ? "研发待验收" : "重复次数不足"))
            .OrderBy(x => x.GyroAxis).ThenBy(x => x.RateDps).ThenBy(x => x.Direction).ToArray();

    public static IReadOnlyList<Ct19DirectionPairRow> Pair(IReadOnlyList<Ct19RunRow> runs) =>
        runs.GroupBy(x => new { x.GyroAxis, x.RateDps })
            .Select(g =>
            {
                var f = g.Where(x => x.Direction == "Forward").ToDictionary(x => x.Repeat);
                var r = g.Where(x => x.Direction == "Reverse").ToDictionary(x => x.Repeat);
                var keys = f.Keys.Intersect(r.Keys).ToArray();
                if (keys.Length == 0)
                    return new Ct19DirectionPairRow(g.Key.GyroAxis, g.Key.RateDps, 0,
                        double.NaN, double.NaN, double.NaN, double.NaN);
                double fm = Mean(keys.Select(k => f[k].MeanResidualDps));
                double rm = Mean(keys.Select(k => r[k].MeanResidualDps));
                return new Ct19DirectionPairRow(g.Key.GyroAxis, g.Key.RateDps, keys.Length,
                    fm, rm, fm-rm, Mean(keys.Select(k => (f[k].ResidualRmseDps+r[k].ResidualRmseDps)/2)));
            }).OrderBy(x => x.GyroAxis).ThenBy(x => x.RateDps).ToArray();

    public static double Mean(IEnumerable<double> xs)
    {
        var a = xs.Where(double.IsFinite).ToArray();
        return a.Length == 0 ? double.NaN : a.Average();
    }
    public static double Std(IEnumerable<double> xs)
    {
        var a = xs.Where(double.IsFinite).ToArray();
        if (a.Length < 2) return double.NaN;
        double m = a.Average();
        return Math.Sqrt(a.Sum(x => (x-m)*(x-m))/(a.Length-1));
    }
}
