namespace Dts.Tests.S1.CT13;

/// <summary>Statistics are calculated from per-cycle diagnostic JSON only when its schema is known.</summary>
public static class Ct13Algorithm
{
    public static double? SampleStd(IEnumerable<double> source)
    {
        var v = source.Where(double.IsFinite).ToArray();
        if (v.Length < 2) return null;
        double mean = v.Average();
        return Math.Sqrt(v.Sum(x => (x - mean) * (x - mean)) / (v.Length - 1));
    }

    public static Ct13Summary Summarize(IReadOnlyList<Ct13Cycle> cycles)
    {
        // Do not infer calibrated bias from raw CSV. The current platform's static
        // diagnostics JSON schema is version-dependent; the report explicitly
        // records the per-cycle files and defers cross-cycle axis statistics until
        // a validated parser is bound to that schema.
        var temps = cycles.Where(c => c.TemperatureC.HasValue && double.IsFinite(c.TemperatureC.Value))
            .Select(c => c.TemperatureC!.Value).ToArray();
        return new Ct13Summary(cycles.Count, null, null,
            temps.Length == 0 ? null : temps.Min(),
            temps.Length == 0 ? null : temps.Max(),
            "已完成的每次上电原始CSV及静态诊断文件均已关联归档。当前版本不从未经确认的诊断JSON字段推导六轴跨周期均值；需基于实测文件复核后再形成数值结论。");
    }
}
