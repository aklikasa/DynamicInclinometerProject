using System.Diagnostics;
using System.Globalization;

namespace Dts.Tests.S1.CT10;

/// <summary>Dynamic rate residual: gyro (JSON calibrated once) vs REAL timestamped encoder rate.</summary>
public static class Ct10Algorithm
{
    public static double[] ParseSpeeds(string raw)
    {
        var parts = (raw ?? "").Split(new[] { ',', '，', ';', '；', ' ', '\n', '\t' },
            StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
        if (parts.Length is < 1 or > 8) throw new InvalidDataException("请设置1～8档角速度");
        var speeds = new List<double>();
        foreach (var part in parts)
        {
            if (!double.TryParse(part, NumberStyles.Float, CultureInfo.InvariantCulture, out double value) ||
                !double.IsFinite(value) || value <= 0)
                throw new InvalidDataException("非法角速度：" + part);
            if (speeds.Any(x => Math.Abs(x - value) <= 1e-8))
                throw new InvalidDataException("存在重复速度：" + part);
            speeds.Add(value);
        }
        return speeds.ToArray();
    }

    /// <summary>
    /// Offline plan preview: validates all user-entered parameters and the proposed route,
    /// but does not claim to have checked device speed limits or granted permission to move.
    /// The actual run MUST call BuildPlan with a verified live adapter.
    /// </summary>
    public static IReadOnlyList<Ct10SweepRequest> PreviewPlan(Ct10Settings s) =>
        BuildPlanCore(s, null, previewOnly: true);

    public static IReadOnlyList<Ct10SweepRequest> BuildPlan(Ct10Settings s, ICt10DynamicHardware hw) =>
        BuildPlanCore(s, hw ?? throw new ArgumentNullException(nameof(hw)), previewOnly: false);

    private static IReadOnlyList<Ct10SweepRequest> BuildPlanCore(
        Ct10Settings s, ICt10DynamicHardware? hw, bool previewOnly)
    {
        if (s.Repetitions is < 1 or > 6 || (!s.TestOuter && !s.TestInner))
            throw new InvalidDataException("至少选择一个轴，每个速度的正反配对重复1～6次");
        if (!double.IsFinite(s.TravelMinDeg) || !double.IsFinite(s.TravelMaxDeg) ||
            s.TravelMinDeg < 0 || s.TravelMaxDeg > 360 || s.TravelMaxDeg - s.TravelMinDeg < 20 ||
            s.TravelMaxDeg - s.TravelMinDeg > 360)
            throw new InvalidDataException("本版试验单段行程须在0～360°内，行程长度20～360°，不得隐式绕360°");
        if (!double.IsFinite(s.ApprovedMinDeg) || !double.IsFinite(s.ApprovedMaxDeg) ||
            s.ApprovedMinDeg < 0 || s.ApprovedMaxDeg > 360 ||
            s.ApprovedMinDeg > 0 || s.ApprovedMaxDeg < s.TravelMaxDeg ||
            s.TravelMinDeg < s.ApprovedMinDeg)
            throw new InvalidDataException("实际已批准行程必须包含外轴安全0°及所有扫描起终点，范围在0～360°内");
        if (!double.IsFinite(s.SetupSpeedDps) || s.SetupSpeedDps <= 0 ||
            !double.IsFinite(s.SettleSeconds) || s.SettleSeconds is < 1 or > 60 ||
            !double.IsFinite(s.SpeedToleranceFraction) || s.SpeedToleranceFraction is < 0.03 or > 0.40 ||
            !double.IsFinite(s.EncoderDerivativeWindowSeconds) || s.EncoderDerivativeWindowSeconds is < 0.2 or > 2.0 ||
            s.MinAcceptedFrames is < 20 or > 1000000)
            throw new InvalidDataException("准备速度/静置时间/速率稳定门限/时间窗口/样本数不合法");
        if (s.InnerGyroSign is not (1 or -1) || s.OuterGyroSign is not (1 or -1))
            throw new InvalidDataException("Gyro轴方向映射必须是+1或-1");
        if (!previewOnly && (!s.MotionAndCablingApproved || !s.EmergencyStopConfirmed ||
            !s.SensorAxisMappingVerified))
            throw new InvalidOperationException("未确认机械行程、线缆、实体急停及Gyro轴方向映射，禁止运动");
        var speeds = ParseSpeeds(s.SpeedsCsv);
        var selected = new List<Ct10Axis>();
        if (s.TestInner) selected.Add(Ct10Axis.Inner);
        if (s.TestOuter) selected.Add(Ct10Axis.Outer);
        if (!previewOnly)
        {
            if (hw is null || !hw.IsRealDynamicCaptureReady)
                throw new NotSupportedException("真实动态采集适配器尚未通过设备核验，禁止自动运动");
            foreach (var axis in selected)
            {
                double certified = hw.MaximumCertifiedSpeedDps(axis);
                if (!double.IsFinite(certified) || certified <= 0)
                    throw new InvalidOperationException($"{axis}轴未报告经过确认的转速上限，禁止自动试验");
                if (s.SetupSpeedDps > certified || speeds.Any(x => x > certified))
                    throw new InvalidDataException($"{axis}轴配置速度超过已确认的设备上限 {certified:F3}°/s");
            }
        }
        var result = new List<Ct10SweepRequest>();
        foreach (var axis in selected)
        foreach (var speed in speeds)
        for (int repetition = 1; repetition <= s.Repetitions; repetition++)
        {
            double travel = s.TravelMaxDeg - s.TravelMinDeg;
            // Motion safety timeout is an upper bound, never a promise of hardware response.
            double timeout = Math.Max(40, Math.Min(900, travel / speed * 2.5 + 40));
            result.Add(new Ct10SweepRequest(axis, Ct10Direction.Forward, repetition, speed,
                s.TravelMinDeg, s.TravelMaxDeg, 0, s.ApprovedMinDeg, s.ApprovedMaxDeg, timeout));
            result.Add(new Ct10SweepRequest(axis, Ct10Direction.Reverse, repetition, speed,
                s.TravelMaxDeg, s.TravelMinDeg, 0, s.ApprovedMinDeg, s.ApprovedMaxDeg, timeout));
        }
        return result;
    }

    public static Ct10SweepResult Analyze(
        Ct10SweepRequest plan, Ct10Capture capture, Ct10Settings settings,
        Func<double, double, double, double[]> applyGyroCalibration,
        int expectedGyroFullScaleDps, string outputCsv)
    {
        if (string.IsNullOrWhiteSpace(capture.DataSource) ||
            string.IsNullOrWhiteSpace(capture.FullUidHex))
            throw new InvalidDataException("动态采集未提供真实设备来源或完整UID");
        if (capture.MotionCompletedNormally != true ||
            capture.GyroCalibrationInputFullScaleDps != expectedGyroFullScaleDps)
            throw new InvalidDataException("真实运动没有正常结束，或Gyro校准输入量程不匹配");
        if (capture.TimestampFrequency != Stopwatch.Frequency)
            throw new InvalidDataException("动态IMU和转台反馈时间基准必须为同一进程的Stopwatch ticks");
        var e = capture.EncoderFrames.OrderBy(x => x.TimestampTicks).ToArray();
        var frames = capture.GyroFrames.OrderBy(x => x.TimestampTicks).ToArray();
        if (e.Length < 10 || frames.Length < settings.MinAcceptedFrames)
            throw new InvalidDataException("运动期间真实转台反馈或Gyro帧不足");
        if (e.Zip(e.Skip(1)).Any(pair => pair.First.TimestampTicks >= pair.Second.TimestampTicks) ||
            frames.Zip(frames.Skip(1)).Any(pair => pair.First.TimestampTicks >= pair.Second.TimestampTicks))
            throw new InvalidDataException("时间戳重复或倒退，无法可靠对齐真实运动数据");
        if (e.Any(x => !x.InnerNormal || !x.OuterNormal || !x.InnerEnabled || !x.OuterEnabled))
            throw new InvalidDataException("运动期间出现转台未使能或状态异常");
        double Position(Ct10EncoderFrame x) => plan.Axis == Ct10Axis.Inner ? x.InnerDeg : x.OuterDeg;
        double OtherPosition(Ct10EncoderFrame x) => plan.Axis == Ct10Axis.Inner ? x.OuterDeg : x.InnerDeg;
        if (e.Any(x => !double.IsFinite(Position(x)) ||
                Position(x) < plan.AllowedMinDeg - 0.5 || Position(x) > plan.AllowedMaxDeg + 0.5 ||
                !double.IsFinite(OtherPosition(x)) || Math.Abs(OtherPosition(x) - plan.OtherAxisHoldDeg) > 0.5))
            throw new InvalidDataException("转台运动越过批准行程，或另一轴没有保持零位");
        if (Math.Abs(Position(e[0]) - plan.StartDeg) > 2 ||
            Math.Abs(Position(e[^1]) - plan.EndDeg) > 1)
            throw new InvalidDataException("真实轨迹没有覆盖请求的运动起点/终点");
        int intendedSign = (int)plan.Direction;
        for (int k = 1; k < e.Length; k++)
        {
            double d = Position(e[k]) - Position(e[k - 1]);
            if (d * intendedSign < -0.25)
                throw new InvalidDataException("实际转台反馈出现明显反向运动，禁止计算速率残差");
        }
        double freq = capture.TimestampFrequency;
        long startTicks = e[0].TimestampTicks;
        double duration = (e[^1].TimestampTicks - startTicks) / freq;
        if (duration <= 1.5) throw new InvalidDataException("运动数据时间不足");
        double window = settings.EncoderDerivativeWindowSeconds;
        double minMargin = Math.Max(window, Math.Min(1.0, duration * 0.04));
        int gyroAxis = plan.Axis == Ct10Axis.Inner ? 2 : 0;
        int projectionSign = plan.Axis == Ct10Axis.Inner ? settings.InnerGyroSign : settings.OuterGyroSign;
        var aligned = new List<Ct10MatchedFrame>(frames.Length);
        foreach (var sample in frames)
        {
            double t = (sample.TimestampTicks - startTicks) / freq;
            string why = "";
            double rate = double.NaN, position = double.NaN;
            if (t < minMargin || t > duration - minMargin) why = "加速/减速端点保护区";
            else
            {
                // Derivative across a centered real encoder window. No commanded-speed substitution.
                long leftTicks = sample.TimestampTicks - (long)(window / 2 * freq);
                long rightTicks = sample.TimestampTicks + (long)(window / 2 * freq);
                int left = LastAtOrBefore(e, leftTicks), right = FirstAtOrAfter(e, rightTicks);
                if (left < 0 || right < 0 || right <= left) why = "编码器时间窗口不完整";
                else
                {
                    double dt = (e[right].TimestampTicks - e[left].TimestampTicks) / freq;
                    if (dt < window * 0.9 || dt > window * 2.0) why = "转台反馈时间间隔异常";
                    else
                    {
                        rate = (Position(e[right]) - Position(e[left])) / dt;
                        position = Position(e[left]) + (Position(e[right]) - Position(e[left])) *
                            (sample.TimestampTicks - e[left].TimestampTicks) / (double)
                            (e[right].TimestampTicks - e[left].TimestampTicks);
                        if (rate * intendedSign <= 0 ||
                            Math.Abs(Math.Abs(rate) / plan.CommandDps - 1) > settings.SpeedToleranceFraction)
                            why = "未达到设定速率的匀速区间";
                    }
                }
            }
            if (!double.IsFinite(sample.InputX_Dps) || !double.IsFinite(sample.InputY_Dps) ||
                !double.IsFinite(sample.InputZ_Dps) || !double.IsFinite(sample.TemperatureC))
                throw new InvalidDataException("Gyro真实帧包含非有限数据");
            ValidateRawConsistency(sample, expectedGyroFullScaleDps);
            double[] calibrated = applyGyroCalibration(sample.InputX_Dps, sample.InputY_Dps, sample.InputZ_Dps);
            if (calibrated.Length != 3 || calibrated.Any(v => !double.IsFinite(v)))
                throw new InvalidDataException("Gyro标定计算得到无效结果");
            double measured = calibrated[gyroAxis] * projectionSign;
            double residual = double.IsFinite(rate) ? measured - rate : double.NaN;
            aligned.Add(new Ct10MatchedFrame(sample.TimestampTicks, t, rate,
                intendedSign * plan.CommandDps, measured, residual,
                calibrated[0], calibrated[1], calibrated[2], sample.TemperatureC,
                position, why.Length == 0, why,
                sample.RawCountX, sample.RawCountY, sample.RawCountZ));
        }
        var good = aligned.Where(x => x.Accepted).ToArray();
        if (good.Length < settings.MinAcceptedFrames ||
            good.Max(x => x.TimeSeconds) - good.Min(x => x.TimeSeconds) < 0.5)
            throw new InvalidDataException($"有效匀速区间不足，{good.Length}帧（需{settings.MinAcceptedFrames}帧）");
        double meanRate = good.Average(x => x.ReferenceRateDps);
        double meanMeasured = good.Average(x => x.GyroAxisMeasuredDps);
        double meanResidual = good.Average(x => x.ResidualDps);
        double rmse = Math.Sqrt(good.Average(x => x.ResidualDps * x.ResidualDps));
        double stdev = Math.Sqrt(good.Sum(x => Math.Pow(x.ResidualDps - meanResidual, 2)) /
            Math.Max(1, good.Length - 1));
        if (Math.Abs(meanRate) < 0.000001) throw new InvalidDataException("编码器参考角速度接近零");
        return new Ct10SweepResult(plan.Axis, plan.Direction, plan.Repetition,
            plan.CommandDps, plan.StartDeg, plan.EndDeg, frames.Length, good.Length, e.Length,
            meanRate, meanMeasured, meanResidual, rmse, stdev,
            (meanMeasured / meanRate - 1.0) * 100.0,
            good.Average(x => x.TemperatureC), outputCsv, capture.DataSource,
            aligned, capture.HardwareNotes);
    }

    private static void ValidateRawConsistency(Ct10GyroFrame s, int fs)
    {
        if (s.RawCountX is null && s.RawCountY is null && s.RawCountZ is null) return;
        if (s.RawCountX is null || s.RawCountY is null || s.RawCountZ is null)
            throw new InvalidDataException("真实Gyro帧仅包含部分int16原始计数，拒绝使用");
        double mdps = fs switch
        {
            125 => 4.375, 250 => 8.75, 500 => 17.5, 1000 => 35.0, 2000 => 70.0,
            _ => throw new InvalidDataException("不支持的历史Gyro标定输入量程：" + fs)
        };
        double factor = mdps / 1000;
        if (Math.Abs(s.InputX_Dps - s.RawCountX.Value * factor) > 0.000001 ||
            Math.Abs(s.InputY_Dps - s.RawCountY.Value * factor) > 0.000001 ||
            Math.Abs(s.InputZ_Dps - s.RawCountZ.Value * factor) > 0.000001)
            throw new InvalidDataException("Gyro物理量与历史量程的原始计数换算不一致");
    }
    private static int LastAtOrBefore(Ct10EncoderFrame[] frames, long ticks)
    {
        int lo = 0, hi = frames.Length - 1, found = -1;
        while (lo <= hi)
        {
            int m = lo + (hi - lo) / 2;
            if (frames[m].TimestampTicks <= ticks) { found = m; lo = m + 1; }
            else hi = m - 1;
        }
        return found;
    }
    private static int FirstAtOrAfter(Ct10EncoderFrame[] frames, long ticks)
    {
        int lo = 0, hi = frames.Length - 1, found = -1;
        while (lo <= hi)
        {
            int m = lo + (hi - lo) / 2;
            if (frames[m].TimestampTicks >= ticks) { found = m; hi = m - 1; }
            else lo = m + 1;
        }
        return found;
    }

    public static IReadOnlyList<Ct10SpeedPairResult> Pair(IReadOnlyList<Ct10SweepResult> sweeps)
    {
        var results = new List<Ct10SpeedPairResult>();
        foreach (var group in sweeps.GroupBy(s => new { s.Axis, s.CommandSpeedDps }))
        {
            var forward = group.Where(x => x.Direction == Ct10Direction.Forward)
                .ToDictionary(x => x.Repetition);
            var reverse = group.Where(x => x.Direction == Ct10Direction.Reverse)
                .ToDictionary(x => x.Repetition);
            var complete = forward.Keys.Intersect(reverse.Keys).OrderBy(k => k).ToArray();
            if (complete.Length == 0) continue;
            results.Add(new Ct10SpeedPairResult(group.Key.Axis, group.Key.CommandSpeedDps,
                complete.Length, complete.Average(i => forward[i].MeanResidualDps),
                complete.Average(i => reverse[i].MeanResidualDps),
                complete.Average(i => forward[i].MeanResidualDps - reverse[i].MeanResidualDps),
                complete.Average(i => forward[i].ScaleRatioPercent),
                complete.Average(i => reverse[i].ScaleRatioPercent),
                Math.Sqrt(complete.Average(i => (
                    forward[i].ResidualRmseDps * forward[i].ResidualRmseDps +
                    reverse[i].ResidualRmseDps * reverse[i].ResidualRmseDps) / 2))));
        }
        return results;
    }
}
