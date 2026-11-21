using System.Globalization;
using System.Diagnostics;
using Dts.Core;
using Dts.Tests.S1.CT10;

namespace Dts.Tests.S1.CT27;

public static class Ct27Algorithm
{
    public static double[] DefaultRates { get; } = new double[] { 3.5, 30.0 };

    public static double[] ParseRates(string raw)
    {
        var parts = (raw ?? string.Empty).Split(
            new[] { ',', '，', ';', '；', ' ', '\n', '\r', '\t' },
            StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
        if (parts.Length is < 1 or > 4)
            throw new InvalidDataException("CT-27支持设置1～4档运动速率");
        var rates = new List<double>();
        foreach (string part in parts)
        {
            if (!double.TryParse(part, NumberStyles.Float, CultureInfo.InvariantCulture, out double rate) ||
                !double.IsFinite(rate) || rate <= 0 || rate > 30)
                throw new InvalidDataException("CT-27运动速率必须大于0且不超过30°/s：" + part);
            if (rates.Any(x => Math.Abs(x - rate) < 1e-8))
                throw new InvalidDataException("CT-27速率档不能重复：" + part);
            rates.Add(rate);
        }
        return rates.ToArray();
    }

    public static void ValidateSettings(Ct27Settings s, bool requireSafety)
    {
        if (s is null) throw new ArgumentNullException(nameof(s));
        if (string.IsNullOrWhiteSpace(s.OutputRoot) || !Directory.Exists(s.OutputRoot))
            throw new DirectoryNotFoundException("CT-27报告根目录不存在：" + s.OutputRoot);
        if (!s.TestInner && !s.TestOuter)
            throw new InvalidDataException("至少选择一个真实转台轴：内轴/Gyro Z 或外轴/Gyro X");
        if (s.Repetitions is < 1 or > 3)
            throw new InvalidDataException("CT-27每个工况重复次数须为1～3");
        _ = ParseRates(s.SpeedsCsv);
        double[] finite = new[]
        {
            s.TravelMinDeg, s.TravelMaxDeg, s.ApprovedMinDeg, s.ApprovedMaxDeg,
            s.SetupSpeedDps, s.SettleSeconds, s.BaselineSeconds, s.RecoverySeconds,
            s.BinSeconds, s.RecoveryBandDps
        };
        if (finite.Any(x => !double.IsFinite(x)))
            throw new InvalidDataException("CT-27参数必须全部为有限数值");
        if (s.TravelMinDeg < 0 || s.TravelMaxDeg > 360 ||
            s.TravelMaxDeg - s.TravelMinDeg < 20 || s.TravelMaxDeg <= s.TravelMinDeg)
            throw new InvalidDataException("运动起终点须在0～360°内，单段行程至少20°，且终点大于起点");
        if (s.ApprovedMinDeg != 0 || s.ApprovedMaxDeg < s.TravelMaxDeg ||
            s.ApprovedMaxDeg > 360)
            throw new InvalidDataException("批准行程须从0°开始并完整包含扫描终点，且不超过360°");
        if (s.SetupSpeedDps <= 0 || s.SetupSpeedDps > 5 ||
            s.SettleSeconds is < 1 or > 60)
            throw new InvalidDataException("准备定位速度须为(0,5]°/s，运动前静置须为1～60s");
        if (s.BaselineSeconds is < 180 or > 300)
            throw new InvalidDataException("运动前零速基线采样须为180～300s（3～5min）");
        if (s.RecoverySeconds is < 60 or > 180)
            throw new InvalidDataException("运动后零偏恢复观察须为60～180s（1～3min）");
        if (s.BinSeconds is < 2 or > 15 ||
            Math.Abs(s.RecoverySeconds / s.BinSeconds - Math.Round(s.RecoverySeconds / s.BinSeconds)) > 1e-8)
            throw new InvalidDataException("恢复窗口须为2～15s，且恢复总时长必须是窗口时长的整数倍");
        if (s.RecoveryBandDps is <= 0.001 or > 1.0)
            throw new InvalidDataException("零偏恢复观察带须大于0.001且不超过1°/s；该值仅为分析门限，不是产品验收指标");
        if (s.ConsecutiveStableBins is < 2 or > 10)
            throw new InvalidDataException("连续稳定窗口数须为2～10");
        if (s.MinSamplesPerBin is < 20 or > 100000)
            throw new InvalidDataException("每个真实恢复窗口至少需要20～100000帧");
        if (s.Calibration.Mode != CalibrationMode.Ambient)
            throw new InvalidDataException("CT-27当前仅支持当前设备UID匹配的常温ACC/Gyro标定文件");
        if (requireSafety && (!s.MotionAndCablingApproved || !s.EmergencyStopConfirmed ||
                              !s.SensorAxisMappingVerified))
            throw new InvalidOperationException("未确认机械行程、线缆、实体急停/现场监护及Gyro轴映射，禁止CT-27运动");
    }

    public static IReadOnlyList<Ct27PlanItem> PreviewPlan(Ct27Settings s)
    {
        ValidateSettings(s, requireSafety: false);
        var axes = new List<Ct10Axis>();
        if (s.TestInner) axes.Add(Ct10Axis.Inner);
        if (s.TestOuter) axes.Add(Ct10Axis.Outer);
        var plan = new List<Ct27PlanItem>();
        int index = 0;
        foreach (Ct10Axis axis in axes)
        foreach (double rate in ParseRates(s.SpeedsCsv))
        for (int repeat = 1; repeat <= s.Repetitions; repeat++)
        {
            plan.Add(CreateItem(++index, axis, rate, repeat, Ct10Direction.Forward, s));
            plan.Add(CreateItem(++index, axis, rate, repeat, Ct10Direction.Reverse, s));
        }
        return plan;
    }

    public static IReadOnlyList<Ct27PlanItem> BuildPlan(Ct27Settings s, ICt10DynamicHardware hardware)
    {
        ValidateSettings(s, requireSafety: true);
        if (hardware is null || !hardware.IsRealDynamicCaptureReady)
            throw new NotSupportedException("CT-27需要已通过profile核验的CT-10真实动态采集桥；禁止用命令速率或静态采样冒充运动数据");
        var plan = PreviewPlan(s);
        foreach (Ct10Axis axis in plan.Select(x => x.Axis).Distinct())
        {
            double max = hardware.MaximumCertifiedSpeedDps(axis);
            if (!double.IsFinite(max) || max <= 0)
                throw new InvalidOperationException($"{axis}轴没有经过核验的最大允许速度");
            if (s.SetupSpeedDps > max || plan.Where(x => x.Axis == axis).Any(x => x.CommandDps > max))
                throw new InvalidDataException($"{axis}轴的定位或测试速率超过profile核验上限{max:F2}°/s");
        }
        return plan;
    }

    private static Ct27PlanItem CreateItem(int index, Ct10Axis axis, double rate, int repeat,
        Ct10Direction direction, Ct27Settings s)
    {
        bool forward = direction == Ct10Direction.Forward;
        double start = forward ? s.TravelMinDeg : s.TravelMaxDeg;
        double end = forward ? s.TravelMaxDeg : s.TravelMinDeg;
        double travel = Math.Abs(end - start);
        double timeout = Math.Max(40, Math.Min(900, travel / rate * 2.5 + 40));
        return new Ct27PlanItem(index, axis, axis == Ct10Axis.Inner ? "Z" : "X", rate,
            repeat, direction, start, end, s.ApprovedMinDeg, s.ApprovedMaxDeg, timeout);
    }

    public static Ct27WindowStats Summarize(StaticPointSamples capture,
        CalibrationMatrix gyro, int minimumSamples)
    {
        if (capture.Samples.Count < minimumSamples || capture.Batches < 3)
            throw new InvalidDataException($"CT-27真实静态采样不足：{capture.Samples.Count}帧/{capture.Batches}批，至少需要{minimumSamples}帧和3批");
        var corrected = new List<double[]>(capture.Samples.Count);
        foreach (RealImuVector sample in capture.Samples)
        {
            if (!double.IsFinite(sample.GxDps) || !double.IsFinite(sample.GyDps) ||
                !double.IsFinite(sample.GzDps) || !double.IsFinite(sample.TemperatureC))
                throw new InvalidDataException("CT-27真实Gyro或温度采样包含非有限值");
            double[] value = gyro.Apply(sample.GxDps, sample.GyDps, sample.GzDps);
            if (value.Length != 3 || value.Any(x => !double.IsFinite(x)))
                throw new InvalidDataException("CT-27常温Gyro矩阵补偿结果无效");
            corrected.Add(value);
        }
        double Mean(int axis) => corrected.Average(x => x[axis]);
        double Std(int axis)
        {
            if (corrected.Count < 2) return double.NaN;
            double mean = Mean(axis);
            return Math.Sqrt(corrected.Sum(x => Math.Pow(x[axis] - mean, 2)) / (corrected.Count - 1));
        }
        return new Ct27WindowStats(Mean(0), Mean(1), Mean(2), Std(0), Std(1), Std(2),
            capture.Samples.Average(x => x.TemperatureC), corrected.Count,
            capture.Batches, capture.DuplicateBatches);
    }

    public static void ValidateMotionCapture(Ct27PlanItem plan, Ct10Capture capture,
        string expectedUid, int expectedGyroFs)
    {
        if (!capture.MotionCompletedNormally || string.IsNullOrWhiteSpace(capture.DataSource) ||
            !string.Equals(capture.FullUidHex, expectedUid, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("CT-27运动未正常完成或运动采集UID与当前IMU不一致");
        if (capture.TimestampFrequency != Stopwatch.Frequency ||
            capture.GyroCalibrationInputFullScaleDps != expectedGyroFs)
            throw new InvalidDataException("CT-27运动采集时基或Gyro输入量程与当前标定文件不一致");
        var enc = capture.EncoderFrames.OrderBy(x => x.TimestampTicks).ToArray();
        var gyro = capture.GyroFrames.OrderBy(x => x.TimestampTicks).ToArray();
        if (enc.Length < 12 || gyro.Length < 20)
            throw new InvalidDataException("CT-27运动过程真实编码器或Gyro帧数不足");
        if (enc.Zip(enc.Skip(1)).Any(x => x.First.TimestampTicks >= x.Second.TimestampTicks) ||
            gyro.Zip(gyro.Skip(1)).Any(x => x.First.TimestampTicks >= x.Second.TimestampTicks))
            throw new InvalidDataException("CT-27运动采集时间戳重复或倒退");
        if (gyro.Any(x => !double.IsFinite(x.InputX_Dps) || !double.IsFinite(x.InputY_Dps) ||
                          !double.IsFinite(x.InputZ_Dps) || !double.IsFinite(x.TemperatureC)))
            throw new InvalidDataException("CT-27运动期间Gyro遥测包含非有限值");
        double Position(Ct10EncoderFrame f) => plan.Axis == Ct10Axis.Inner ? f.InnerDeg : f.OuterDeg;
        double Other(Ct10EncoderFrame f) => plan.Axis == Ct10Axis.Inner ? f.OuterDeg : f.InnerDeg;
        foreach (var f in enc)
        {
            if (!f.InnerNormal || !f.OuterNormal || !f.InnerEnabled || !f.OuterEnabled)
                throw new InvalidDataException("CT-27运动过程中2TD发生报警或失能");
            if (!double.IsFinite(Position(f)) || !double.IsFinite(Other(f)) ||
                Position(f) < plan.AllowedMinDeg - 0.5 || Position(f) > plan.AllowedMaxDeg + 0.5 ||
                Math.Abs(Other(f)) > 0.5)
                throw new InvalidDataException("CT-27运动反馈越过批准行程或固定轴偏离0°");
        }
        if (Math.Abs(Position(enc[0]) - plan.StartDeg) > 2.0 ||
            Math.Abs(Position(enc[enc.Length - 1]) - plan.EndDeg) > 1.0)
            throw new InvalidDataException("CT-27真实编码器轨迹没有覆盖计划起点/终点");
        int sign = (int)plan.Direction;
        for (int i = 1; i < enc.Length; i++)
        {
            double delta = Position(enc[i]) - Position(enc[i - 1]);
            if (delta * sign < -0.25)
                throw new InvalidDataException("CT-27真实编码器反馈出现明显反向运动");
        }
    }

    public static double EstimateMedianEncoderRate(Ct27PlanItem plan, Ct10Capture capture)
    {
        var enc = capture.EncoderFrames.OrderBy(x => x.TimestampTicks).ToArray();
        double low = plan.TravelLow + plan.TravelLength * 0.20;
        double high = plan.TravelHigh - plan.TravelLength * 0.20;
        var speeds = new List<double>();
        for (int i = 1; i < enc.Length; i++)
        {
            double dt = (enc[i].TimestampTicks - enc[i - 1].TimestampTicks) /
                        (double)capture.TimestampFrequency;
            if (dt <= 0) continue;
            double p0 = plan.Axis == Ct10Axis.Inner ? enc[i - 1].InnerDeg : enc[i - 1].OuterDeg;
            double p1 = plan.Axis == Ct10Axis.Inner ? enc[i].InnerDeg : enc[i].OuterDeg;
            double mid = (p0 + p1) / 2;
            double delta = p1 - p0;
            if (mid < low || mid > high || delta * (int)plan.Direction <= 0) continue;
            double rate = Math.Abs(delta / dt);
            if (double.IsFinite(rate) && rate > 0) speeds.Add(rate);
        }
        if (speeds.Count < 3)
            throw new InvalidDataException("CT-27无法从真实编码器中段反馈估计运动速度");
        speeds.Sort();
        int n = speeds.Count;
        return n % 2 == 1 ? speeds[n / 2] : (speeds[n / 2 - 1] + speeds[n / 2]) / 2;
    }

    public static double MaxAbsDelta(Ct27WindowStats value, Ct27WindowStats baseline) =>
        Math.Max(Math.Abs(value.MeanX - baseline.MeanX),
            Math.Max(Math.Abs(value.MeanY - baseline.MeanY), Math.Abs(value.MeanZ - baseline.MeanZ)));

    public static double? FindRecoveryUpperBound(IReadOnlyList<Ct27RecoveryBin> bins,
        double band, int consecutive)
    {
        for (int i = 0; i <= bins.Count - consecutive; i++)
        {
            bool stableRun = bins.Skip(i).Take(consecutive).All(x => x.MaxAbsDeltaDps <= band);
            bool noLaterRebound = bins.Skip(i + consecutive).All(x => x.MaxAbsDeltaDps <= band);
            if (stableRun && noLaterRebound)
                return bins[i + consecutive - 1].SinceStopEndSeconds;
        }
        return null;
    }

    public static Ct27Aggregate? Summarize(IReadOnlyList<Ct27CycleResult> cycles)
    {
        if (cycles.Count == 0) return null;
        var recovered = cycles.Where(x => x.RecoveredBySeconds.HasValue)
            .Select(x => x.RecoveredBySeconds!.Value).ToArray();
        return new Ct27Aggregate(cycles.Count, recovered.Length,
            cycles.Max(x => x.PeakMaxAbsDeltaDps),
            cycles.Average(x => Math.Max(Math.Abs(x.FinalDeltaX),
                Math.Max(Math.Abs(x.FinalDeltaY), Math.Abs(x.FinalDeltaZ)))),
            recovered.Length == 0 ? null : recovered.Average());
    }

    public static int RecoveryBinCount(Ct27Settings s) =>
        checked((int)Math.Round(s.RecoverySeconds / s.BinSeconds));
}

