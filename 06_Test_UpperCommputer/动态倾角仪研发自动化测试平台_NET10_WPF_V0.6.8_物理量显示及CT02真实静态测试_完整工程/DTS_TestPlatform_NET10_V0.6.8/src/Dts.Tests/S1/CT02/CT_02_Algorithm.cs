using System.Globalization;

namespace Dts.Tests.S1.CT02;

/// <summary>
/// Compute a stationary zero-reference residual in the calibrated platform P frame.
/// No synthetic samples, no smoothing of a failing data stream and no automatic PASS.
/// </summary>
public static class Ct02Algorithm
{
    private sealed class OnlineMoments
    {
        public long N { get; private set; }
        public double Mean { get; private set; }
        private double _m2;
        public void Add(double v)
        {
            if (!double.IsFinite(v)) throw new InvalidDataException("采样中包含非有限物理量");
            N++;
            double d = v - Mean;
            Mean += d / N;
            _m2 += d * (v - Mean);
        }
        public double Std => N < 2 ? 0 : Math.Sqrt(Math.Max(0, _m2 / (N - 1)));
    }

    public static Ct02Metrics Analyze(IEnumerable<Ct02Measurement> measurements, int referenceSign)
    {
        if (referenceSign is not (1 or -1))
            throw new ArgumentOutOfRangeException(nameof(referenceSign), "必须明确指定参考重力方向 +Z 或 -Z");
        var moments = Enumerable.Range(0, 7).Select(_ => new OnlineMoments()).ToArray();
        var ticks = new HashSet<uint>();
        int count = 0;
        foreach (var m in measurements)
        {
            double[] values = [m.AxG, m.AyG, m.AzG, m.GxDps, m.GyDps, m.GzDps, m.TemperatureC];
            for (int i = 0; i < values.Length; i++) moments[i].Add(values[i]);
            ticks.Add(m.McuTickMs);
            count++;
        }
        if (count < 50 || ticks.Count < 2)
            throw new InvalidDataException($"CT-02 真实采样不足或时间戳未变化：{count}帧/{ticks.Count}批；不得输出测试结果");
        var means = moments.Take(6).Select(m => m.Mean).ToArray();
        var std = moments.Take(6).Select(m => m.Std).ToArray();
        double ax = means[0], ay = means[1], az = means[2];
        double accNorm = Math.Sqrt(ax * ax + ay * ay + az * az);
        if (!double.IsFinite(accNorm) || accNorm < 1e-9)
            throw new InvalidDataException("ACC 三轴均值幅值为零/无效，不能计算静态零位角度");
        // Roll/pitch are small-angle residual components around the operator-confirmed
        // reference (0,0,sign) in the calibration's platform P coordinates.
        // This sign-aware convention yields zero for both +Z and -Z references.
        double roll = Math.Atan2(ay, referenceSign * az) * 180d / Math.PI;
        double pitch = Math.Atan2(-ax, Math.Sqrt(ay * ay + az * az)) * 180d / Math.PI;
        double direction = Math.Acos(Math.Clamp(referenceSign * az / accNorm, -1d, 1d)) * 180d / Math.PI;
        double gyroNorm = Math.Sqrt(means[3] * means[3] + means[4] * means[4] + means[5] * means[5]);
        return new Ct02Metrics(count, ticks.Count, means, std, roll, pitch,
            direction, accNorm, accNorm - 1d, gyroNorm, moments[6].Mean);
    }

    public static async Task<Ct02Metrics> AnalyzeSelectedCsvAsync(string file, int referenceSign,
        CancellationToken ct)
    {
        if (!File.Exists(file)) throw new FileNotFoundException("缺少实时补偿流 imu_selected.csv", file);
        using var reader = new StreamReader(file);
        string header = await reader.ReadLineAsync(ct) ?? throw new InvalidDataException("选定数据 CSV 为空");
        string[] columns = header.TrimStart('\uFEFF').Split(',');
        int Get(string key)
        {
            int index = Array.FindIndex(columns, col => col.Equals(key, StringComparison.OrdinalIgnoreCase));
            if (index < 0) throw new InvalidDataException($"选定数据 CSV 缺少字段 {key}");
            return index;
        }
        int ixMode = Get("mode"), ixStatus = Get("source_status"), ixTick = Get("mcu_tick_ms"),
            ixTemp = Get("temp_c");
        int[] ix = [Get("ax"), Get("ay"), Get("az"), Get("gx"), Get("gy"), Get("gz")];
        var measurements = new List<Ct02Measurement>();
        string? line;
        while ((line = await reader.ReadLineAsync(ct)) is not null)
        {
            ct.ThrowIfCancellationRequested();
            var cells = line.Split(',');
            if (cells.Length != columns.Length ||
                !cells[ixMode].Equals("AMBIENT", StringComparison.OrdinalIgnoreCase) ||
                !(cells[ixStatus].StartsWith("CALIBRATED_", StringComparison.Ordinal) ||
                  cells[ixStatus] == "MCU_SCALE_VERIFIED_CALIBRATED"))
                throw new InvalidDataException("CT-02 所选记录混入非常温/未计算数据，拒绝出具残差结果");
            double[] values = ix.Select(j => double.Parse(cells[j], NumberStyles.Float,
                CultureInfo.InvariantCulture)).ToArray();
            double temp = double.Parse(cells[ixTemp], NumberStyles.Float, CultureInfo.InvariantCulture);
            uint tick = uint.Parse(cells[ixTick], CultureInfo.InvariantCulture);
            measurements.Add(new Ct02Measurement(values[0], values[1], values[2],
                values[3], values[4], values[5], temp, tick));
        }
        return Analyze(measurements, referenceSign);
    }
}
