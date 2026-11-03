using Dts.TestEngine;

namespace Dts.Tests.S1.CT05;

public static class Ct05Algorithm
{
    // Python V1.4 scan_plan.py: Y->inner0; X->inner90, outer -180..180 at 10° steps.
    // Narrow plan is suitable for pilot trials before full-circle travel validation.
    public static IReadOnlyList<Ct05PlanPoint> BuildPlan(string kind)
    {
        var signed=kind switch
        {
            "小角度" => new[]{0d,1d,5d,10d},
            "对称小角度" => new[]{-10d,-5d,-1d,0d,1d,5d,10d},
            "全圈74点" => Enumerable.Range(0,37).Select(i=>-180d+10*i).ToArray(),
            _ => throw new ArgumentException("未知静态角度检测计划")
        };
        return (from ch in new[]{"Y","X"}
                from angle in signed
                select new Ct05PlanPoint(ch,ch=="Y"?0d:90d,angle,(angle+360)%360)).ToArray();
    }
    public static void ValidatePlan(Ct05Settings p, IReadOnlyList<Ct05PlanPoint> plan)
    {
        if(plan.Count==0||p.SpeedDps<=0||p.SpeedDps>5||p.SettleSeconds<0||p.CaptureSeconds<1
           ||p.PositionToleranceDeg<=0||p.PositionToleranceDeg>1||p.MinimumValidSamples<50
           ||p.MaxRejectionFraction<0||p.MaxRejectionFraction>0.2)
            throw new ArgumentException("测试参数超出静态扫描允许范围");
        if(!double.IsFinite(p.AllowedTravelMinDeg)||!double.IsFinite(p.AllowedTravelMaxDeg)||
           p.AllowedTravelMaxDeg<=p.AllowedTravelMinDeg)
            throw new ArgumentException("必须声明已验证的角度行程边界");
        if(p.PlanKind=="全圈74点"&&!p.OperatorApprovedFullTravel)
            throw new InvalidOperationException("全圈74点必须由现场确认 0~360° 全行程、夹具及电缆安全；本程序不自动批准");
        if(plan.Any(x=>x.OuterSignedDeg<0)&&!p.ConfirmedActualDirection)
            throw new InvalidOperationException("存在负角度(映射为350°等)：必须先实机验证0/360°附近绝对定位方向后才能运行");
        if(plan.Any(x=>x.InnerTargetDeg<p.AllowedTravelMinDeg||x.InnerTargetDeg>p.AllowedTravelMaxDeg||
                          x.OuterCommandDeg<p.AllowedTravelMinDeg||x.OuterCommandDeg>p.AllowedTravelMaxDeg))
            throw new InvalidOperationException("扫描计划超出现场批准的绝对角度行程；请缩小计划或在完成实机验证后修改行程边界");
    }
    private static double Median(IEnumerable<double> xs)
    {
        var a=xs.OrderBy(x=>x).ToArray();
        if(a.Length==0)throw new InvalidDataException("没有可用样本");
        return a.Length%2==1?a[a.Length/2]:(a[a.Length/2-1]+a[a.Length/2])/2;
    }
    public static Ct05PointResult Analyze(int index,Ct05PlanPoint p,
        RealTableFeedback position,StaticPointSamples capture,Func<double[],double,double[]> calibrate,
        Ct05Settings settings)
    {
        var measurements=capture.Samples.Select(s=>new[]{s.AxG,s.AyG,s.AzG}).ToArray();
        if(measurements.Length<settings.MinimumValidSamples)
            throw new InvalidDataException($"点 {index}: 有效采集帧数不足 {measurements.Length}");
        var center=Enumerable.Range(0,3).Select(j=>Median(measurements.Select(v=>v[j]))).ToArray();
        var scale=Enumerable.Range(0,3).Select(j=>
            Math.Max(1e-6,1.4826*Median(measurements.Select(v=>Math.Abs(v[j]-center[j]))))).ToArray();
        // Reject outliers in the authentic physical ACC readings, then compensate each kept
        // sample with its own measured chip temperature (important for thermal mode).
        var kept=capture.Samples.Where(s=>
        {
            var v=new[]{s.AxG,s.AyG,s.AzG};
            return Enumerable.Range(0,3).All(j=>Math.Abs(v[j]-center[j])<=3*scale[j]);
        }).ToArray();
        double rejected=1d-kept.Length/(double)measurements.Length;
        if(kept.Length<settings.MinimumValidSamples||rejected>settings.MaxRejectionFraction)
            throw new InvalidDataException($"点 {index}: MAD 剔除率 {rejected:P2} 或有效样本数不达标");
        double[] mean=Enumerable.Range(0,3).Select(j=>kept.Average(v=>j switch {0=>v.AxG,1=>v.AyG,_=>v.AzG})).ToArray();
        double[] sd=Enumerable.Range(0,3).Select(j=>Math.Sqrt(kept.Average(v=>Math.Pow(
            (j switch{0=>v.AxG,1=>v.AyG,_=>v.AzG})-mean[j],2)))).ToArray();
        var corrected=kept.Select(v=>calibrate(new[]{v.AxG,v.AyG,v.AzG},v.TemperatureC)).ToArray();
        double[] correction=Enumerable.Range(0,3).Select(j=>corrected.Average(v=>v[j])).ToArray();
        double norm=Math.Sqrt(correction.Sum(x=>x*x));
        if(norm<0.8||norm>1.2)throw new InvalidDataException($"点 {index}: 标定后模长 {norm:F5}g 异常");
        double measured=p.Channel=="Y"?Math.Atan2(correction[1],correction[2])*180/Math.PI:
            Math.Atan2(correction[0],correction[2])*180/Math.PI;
        double reference=Wrap(position.Outer.PositionDeg);
        return new Ct05PointResult(index,p.Channel,p.InnerTargetDeg,p.OuterCommandDeg,
            position.Inner.PositionDeg,position.Outer.PositionDeg,
            reference,Wrap(measured),Wrap(measured-reference),norm,mean,correction,sd,
            measurements.Length,kept.Length,rejected,capture.StartedUtc,capture.EndedUtc,
            capture.CsvPath,capture.TemperatureC);
    }
    public static double Wrap(double deg) => ((deg+180)%360+360)%360-180;
    public static (double Bias,double Rmse,double MaxAbs) Summarize(IReadOnlyList<Ct05PointResult> points)
    {
        if(points.Count==0)throw new InvalidOperationException("无数据不可计算统计量");
        return (points.Average(p=>p.ErrorDeg),
                Math.Sqrt(points.Average(p=>p.ErrorDeg*p.ErrorDeg)),
                points.Max(p=>Math.Abs(p.ErrorDeg)));
    }
}
