using Dts.TestEngine;

namespace Dts.Tests.S1.CT07;

public static class Ct07Algorithm
{
    private const double Rad = Math.PI / 180.0;
    public static IReadOnlyList<Ct07Pose> BuildPlan(Ct07Settings s)
    {
        var poses = new List<Ct07Pose>(Math.Clamp(s.RepeatCount, 0, 50));
        for (int i = 0; i < s.RepeatCount && i < 50; i++)
        {
            // Opposite approach sides are measured separately; neither is a distinct test posture.
            double direction = s.AlternateApproach && (i % 2 == 1) ? 1 : -1;
            poses.Add(new Ct07Pose(i + 1,
                s.InnerTargetDeg + direction * s.InnerExcursionDeg,
                s.OuterTargetDeg + direction * s.OuterExcursionDeg,
                s.InnerTargetDeg, s.OuterTargetDeg, direction > 0 ? "从正侧回位" : "从负侧回位"));
        }
        return poses;
    }

    public static void Validate(Ct07Settings s, IReadOnlyList<Ct07Pose> poses, bool safetyRequired = true)
    {
        if (s.RepeatCount is < 3 or > 40 || poses.Count != s.RepeatCount)
            throw new InvalidDataException("重复回位次数应为3～40次");
        if (!double.IsFinite(s.SpeedDps) || s.SpeedDps < 0.01 || s.SpeedDps > 5)
            throw new InvalidDataException("扫描运动速度应为0.01～5°/s");
        if (!double.IsFinite(s.SettleSeconds) || s.SettleSeconds < 1 || s.SettleSeconds > 120 ||
            !double.IsFinite(s.SampleSeconds) || s.SampleSeconds < 2 || s.SampleSeconds > 120)
            throw new InvalidDataException("静置1～120秒；采集2～120秒");
        if (!double.IsFinite(s.PositionToleranceDeg) || s.PositionToleranceDeg <= 0 || s.PositionToleranceDeg > 0.5)
            throw new InvalidDataException("到位容差必须在(0,0.5]°");
        if (!double.IsFinite(s.AllowedMinDeg) || !double.IsFinite(s.AllowedMaxDeg) ||
            s.AllowedMinDeg < 0 || s.AllowedMaxDeg > 360 || s.AllowedMinDeg >= s.AllowedMaxDeg)
            throw new InvalidDataException("声明的机械绝对行程须在0～360°内且下界小于上界");
        if (!double.IsFinite(s.InnerTargetDeg) || !double.IsFinite(s.OuterTargetDeg) ||
            !double.IsFinite(s.InnerExcursionDeg) || !double.IsFinite(s.OuterExcursionDeg) ||
            s.InnerExcursionDeg < 0 || s.OuterExcursionDeg < 0 ||
            (s.InnerExcursionDeg == 0 && s.OuterExcursionDeg == 0) ||
            s.InnerExcursionDeg > 90 || s.OuterExcursionDeg > 90)
            throw new InvalidDataException("目标角必须有效；离开幅度0～90°，至少一轴的幅度大于0");
        if (s.MinValidSamples is < 50 or > 1000000 ||
            !double.IsFinite(s.MaxOutlierFraction) || s.MaxOutlierFraction is < 0 or > 0.30)
            throw new InvalidDataException("有效样本数至少50帧，最大剔除比例0～0.30");
        if (s.AllowedMinDeg > 0 || s.AllowedMaxDeg < 0)
            throw new InvalidDataException("内轴移动前需先把外轴停在0°；允许行程必须覆盖外轴0°");
        if (poses.Any(p => new[]{p.InnerDepartDeg,p.OuterDepartDeg,p.InnerReturnDeg,p.OuterReturnDeg}
            .Any(v => !double.IsFinite(v) || v < s.AllowedMinDeg || v > s.AllowedMaxDeg)))
            throw new InvalidDataException("重复扫描目标角或离开角超出声明的机械允许行程");
        if (safetyRequired && (!s.DirectionAndCablingApproved || !s.HardwareSafetyConfirmed))
            throw new InvalidOperationException("请先在现场确认实际行程、急停、线缆及正反向运动安全");
    }

    public static double Wrap(double deg) => ((deg + 180) % 360 + 360) % 360 - 180;
    public static double Distance(double a, double b) => Math.Abs(Wrap(a-b));
    public static double Midpoint(double a, double b) => (a + Wrap(b-a)/2 + 360) % 360;

    // Python: R=Rx(outer)Rz(inner), gravity_P=R.T*[0,0,sign]
    public static double[] Gravity(double inner, double outer, int sign)
    {
        if (sign is not (1 or -1)) throw new InvalidDataException("ACC gravity_sign非±1");
        double i = inner * Rad, o = outer * Rad;
        return [sign*Math.Sin(i)*Math.Sin(o),sign*Math.Cos(i)*Math.Sin(o),sign*Math.Cos(o)];
    }
    public static double Norm(IReadOnlyList<double> v) => Math.Sqrt(v.Sum(x => x*x));
    public static double Angle(IReadOnlyList<double> a, IReadOnlyList<double> b)
    {
        var n=Norm(a)*Norm(b);
        if (n < 1e-12) throw new InvalidDataException("加速度模长不足，无法计算夹角");
        double dot=Enumerable.Range(0,3).Sum(j=>a[j]*b[j]);
        return Math.Acos(Math.Clamp(dot/n,-1,1))/Rad;
    }
    private static double Median(IEnumerable<double> values)
    {
        var v=values.OrderBy(x=>x).ToArray();
        if(v.Length==0) throw new InvalidDataException("没有真实样本");
        return v.Length%2==1?v[v.Length/2]:(v[v.Length/2-1]+v[v.Length/2])/2;
    }
    public static (Ct07Visit Visit, bool[] Accepted, double[][] Acc, double[][] Gyro)
        Analyze(Ct07Pose pose, RealTableFeedback before, RealTableFeedback after,
            StaticPointSamples capture, Func<double[],double[]> accCalibration,
            Func<double[],double[]> gyroCalibration, Ct07Settings s, int gravitySign,
            string physicalCsv, string correctedCsv)
    {
        var samples=capture.Samples;
        if(samples.Count<s.MinValidSamples || capture.Batches<3)
            throw new InvalidDataException($"第{pose.Index}轮真实采样不足：{samples.Count}帧/{capture.Batches}批");
        var raw=samples.Select(v=>new[]{v.AxG,v.AyG,v.AzG,v.GxDps,v.GyDps,v.GzDps}).ToArray();
        if(raw.Any(v=>v.Any(x=>!double.IsFinite(x))))
            throw new InvalidDataException("检测到非有限真实六轴数据");
        var med=Enumerable.Range(0,6).Select(j=>Median(raw.Select(v=>v[j]))).ToArray();
        var mad=Enumerable.Range(0,6).Select(j=>Math.Max(j<3?0.00015:0.14,
            1.4826*Median(raw.Select(v=>Math.Abs(v[j]-med[j]))))).ToArray();
        var accepted=raw.Select(v=>Enumerable.Range(0,6)
            .All(j=>Math.Abs(v[j]-med[j])<=4.5*mad[j])).ToArray();
        var keep=Enumerable.Range(0,raw.Length).Where(i=>accepted[i]).ToArray();
        double rejection=1-keep.Length/(double)raw.Length;
        if(keep.Length<s.MinValidSamples || rejection>s.MaxOutlierFraction)
            throw new InvalidDataException($"第{pose.Index}轮有效样本{keep.Length}或剔除率{rejection:P2}未达标");
        var acc=raw.Select(v=>accCalibration([v[0],v[1],v[2]])).ToArray();
        var gyr=raw.Select(v=>gyroCalibration([v[3],v[4],v[5]])).ToArray();
        if(acc.Any(v=>v is not {Length:3} || v.Any(x=>!double.IsFinite(x))) ||
           gyr.Any(v=>v is not {Length:3} || v.Any(x=>!double.IsFinite(x))))
            throw new InvalidDataException("校正模型返回无效六轴数值");
        static double[] Mean(double[][] x,int[] idx) => Enumerable.Range(0,3)
            .Select(j=>idx.Average(i=>x[i][j])).ToArray();
        static double[] Std(double[][] x,int[] idx,double[] mean) => Enumerable.Range(0,3)
            .Select(j=>Math.Sqrt(idx.Sum(i=>Math.Pow(x[i][j]-mean[j],2))/Math.Max(1,idx.Length-1))).ToArray();
        var aMean=Mean(acc,keep);var gMean=Mean(gyr,keep);
        var aStd=Std(acc,keep,aMean);var gStd=Std(gyr,keep,gMean);
        double inner=Midpoint(before.Inner.PositionDeg,after.Inner.PositionDeg);
        double outer=Midpoint(before.Outer.PositionDeg,after.Outer.PositionDeg);
        var reference=Gravity(inner,outer,gravitySign);
        double norm=Norm(aMean);
        if(norm<0.7 || norm>1.3)
            throw new InvalidDataException($"第{pose.Index}轮校正ACC模长{norm:F6}g超出诊断合理区间");
        double temp=keep.Average(i=>samples[i].TemperatureC);
        if(!double.IsFinite(temp)) throw new InvalidDataException("没有有效芯片温度");
        return (new Ct07Visit(pose.Index,pose.Approach,pose.InnerDepartDeg,pose.OuterDepartDeg,
            pose.InnerReturnDeg,pose.OuterReturnDeg,inner,outer,reference,aMean,aStd,gMean,gStd,
            Norm(Enumerable.Range(0,3).Select(j=>aMean[j]-reference[j]).ToArray())*1000,
            Angle(aMean,reference),norm,temp,raw.Length,keep.Length,rejection,
            capture.Batches,capture.DuplicateBatches,physicalCsv,correctedCsv,capture.StartedUtc,capture.EndedUtc),
            accepted,acc,gyr);
    }

    public static Ct07Metrics? Summarize(IReadOnlyList<Ct07Visit> visits)
    {
        if(visits.Count<2) return null;
        static double Std(IEnumerable<double> x)
        {
            var a=x.ToArray(); double m=a.Average();
            return Math.Sqrt(a.Sum(v=>(v-m)*(v-m))/(a.Length-1));
        }
        static double Rms(IEnumerable<double> x) => Math.Sqrt(x.Average(v=>v*v));
        var center=Enumerable.Range(0,3).Select(j=>visits.Average(v=>v.AccCorrectedMeanG[j])).ToArray();
        var between=Enumerable.Range(0,3).Select(j=>Std(visits.Select(v=>v.AccCorrectedMeanG[j]))*1000).ToArray();
        var deviations=visits.Select(v=>Norm(Enumerable.Range(0,3)
            .Select(j=>v.AccCorrectedMeanG[j]-center[j]).ToArray())*1000).ToArray();
        var dirs=visits.Select(v=>Angle(v.AccCorrectedMeanG,center)).ToArray();
        var gyro=Enumerable.Range(0,3).Select(j=>Std(visits.Select(v=>v.GyroCorrectedMeanDps[j]))).ToArray();
        // Pooled within-visit variance: use accepted-frame weighting and n-1 denominators.
        double Pooled(Func<Ct07Visit,double> get) => Math.Sqrt(visits.Sum(v=>
            (v.AcceptedSamples-1)*Math.Pow(get(v),2)) / Math.Max(1,visits.Sum(v=>v.AcceptedSamples-1)));
        var accNoise=Enumerable.Range(0,3).Select(j=>Pooled(v=>v.AccWithinStdG[j])*1000).ToArray();
        var gyroNoise=Enumerable.Range(0,3).Select(j=>Pooled(v=>v.GyroWithinStdDps[j])).ToArray();
        var innerReturn=visits.Select(v=>Wrap(v.InnerActualDeg-visits[0].InnerActualDeg)).ToArray();
        var outerReturn=visits.Select(v=>Wrap(v.OuterActualDeg-visits[0].OuterActualDeg)).ToArray();
        double iMean=innerReturn.Average(),oMean=outerReturn.Average();
        return new Ct07Metrics(visits.Count,visits.Sum(v=>v.AcceptedSamples),between,
            Rms(deviations),deviations.Max(),Rms(dirs),dirs.Max(),accNoise,gyro,gyroNoise,
            Std(innerReturn),Std(outerReturn),innerReturn.Max(v=>Math.Abs(v-iMean)),
            outerReturn.Max(v=>Math.Abs(v-oMean)),visits.Average(v=>v.VectorReferenceErrorMg),
            visits.Max(v=>v.VectorReferenceErrorMg),visits.Min(v=>v.MeanTemperatureC),
            visits.Max(v=>v.MeanTemperatureC));
    }
}
