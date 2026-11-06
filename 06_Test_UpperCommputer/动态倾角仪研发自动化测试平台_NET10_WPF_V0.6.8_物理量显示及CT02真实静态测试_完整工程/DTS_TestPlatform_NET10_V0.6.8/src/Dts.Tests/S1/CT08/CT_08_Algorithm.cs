using Dts.TestEngine;
using System.Globalization;

namespace Dts.Tests.S1.CT08;

public static class Ct08Algorithm
{
    private const double Rad = Math.PI / 180.0;
    public static double Wrap(double deg) => ((deg + 180) % 360 + 360) % 360 - 180;
    public static double Distance(double a, double b) => Math.Abs(Wrap(a-b));
    public static double Midpoint(double a, double b) => (a + Wrap(b-a)/2 + 360)%360;
    public static double Norm(IReadOnlyList<double> v) => Math.Sqrt(v.Sum(x=>x*x));
    public static double[] Sub(IReadOnlyList<double> a,IReadOnlyList<double> b) =>
        Enumerable.Range(0,3).Select(j=>a[j]-b[j]).ToArray();
    public static double[] Gravity(double inner,double outer,int sign)
    {
        if(sign is not (1 or -1)) throw new InvalidDataException("gravity_sign不是±1");
        double i=inner*Rad,o=outer*Rad;
        return [sign*Math.Sin(i)*Math.Sin(o),sign*Math.Cos(i)*Math.Sin(o),sign*Math.Cos(o)];
    }
    public static double Angle(IReadOnlyList<double> a,IReadOnlyList<double> b)
    {
        double norm=Norm(a)*Norm(b);
        if(norm<1e-12)throw new InvalidDataException("姿态矢量模长不足");
        return Math.Acos(Math.Clamp(Enumerable.Range(0,3).Sum(j=>a[j]*b[j])/norm,-1,1))/Rad;
    }
    public static double[] ParseAngles(string input,string label)
    {
        if(string.IsNullOrWhiteSpace(input)) throw new InvalidDataException(label+"不能为空");
        var parts=input.Split(new[]{',','，',';','；',' ','\n','\r','\t'},
            StringSplitOptions.RemoveEmptyEntries|StringSplitOptions.TrimEntries);
        if(parts.Length is <1 or >12)throw new InvalidDataException(label+"须设置1～12个角度");
        var values=new List<double>();
        foreach(string p in parts)
        {
            if(!double.TryParse(p,NumberStyles.Float,CultureInfo.InvariantCulture,out var v)||
                !double.IsFinite(v)) throw new InvalidDataException(label+"存在无效角度："+p);
            if(values.Any(x=>Distance(x,v)<1e-6))throw new InvalidDataException(label+"包含重复角度："+p);
            values.Add(v);
        }
        return values.ToArray();
    }
    public static IReadOnlyList<Ct08Pose> BuildPlan(Ct08Settings s)
    {
        double[] inners=ParseAngles(s.InnerPositionsText,"内轴固定姿态");
        double[] targets=ParseAngles(s.OuterTargetsText,"外轴目标角");
        if(s.PairsPerTarget is <1 or >12)throw new InvalidDataException("每目标配对轮数须为1～12");
        var plan=new List<Ct08Pose>();int pair=0,index=0;
        foreach(double inner in inners)
        foreach(double outer in targets)
        for(int round=1;round<=s.PairsPerTarget;round++)
        {
            pair++;
            // Alternate the order on each cycle to mitigate temperature/time drift.
            var dirs=round%2==1?new[]{-1,1}:new[]{1,-1};
            foreach(int dir in dirs)
                plan.Add(new Ct08Pose(++index,pair,round,dir<0?"正向接近":"反向接近",
                    inner,outer,outer+dir*s.ApproachOffsetDeg));
        }
        return plan;
    }
    public static void Validate(Ct08Settings s,IReadOnlyList<Ct08Pose> plan,bool safetyRequired=true)
    {
        if(plan.Count is <2 or >288 || plan.Count%2!=0)
            throw new InvalidDataException("自动计划须有成对的正反路径，最多288次采样");
        if(!double.IsFinite(s.ApproachOffsetDeg)||s.ApproachOffsetDeg<1||s.ApproachOffsetDeg>60)
            throw new InvalidDataException("接近方向偏移量1～60°，必须大于到位容差");
        if(!double.IsFinite(s.SpeedDps)||s.SpeedDps<0.01||s.SpeedDps>5)
            throw new InvalidDataException("测试速度0.01～5°/s");
        if(!double.IsFinite(s.SettleSeconds)||s.SettleSeconds<1||s.SettleSeconds>120||
            !double.IsFinite(s.SampleSeconds)||s.SampleSeconds<2||s.SampleSeconds>120)
            throw new InvalidDataException("静置1～120s，真实采样2～120s");
        if(!double.IsFinite(s.PositionToleranceDeg)||s.PositionToleranceDeg<=0||
            s.PositionToleranceDeg>0.5||s.ApproachOffsetDeg<5*s.PositionToleranceDeg)
            throw new InvalidDataException("容差在(0,0.5]°且偏移量至少为容差5倍");
        if(!double.IsFinite(s.AllowedMinDeg)||!double.IsFinite(s.AllowedMaxDeg)||
            s.AllowedMinDeg<0||s.AllowedMaxDeg>360||s.AllowedMinDeg>=s.AllowedMaxDeg)
            throw new InvalidDataException("绝对角度批准区间应满足0≤下界<上界≤360");
        if(s.AllowedMinDeg>0) throw new InvalidDataException("内轴换位需要外轴安全停靠0°，允许行程必须包含0°");
        if(s.MinValidSamples is <50 or >1000000 || !double.IsFinite(s.MaxOutlierFraction)||
            s.MaxOutlierFraction<0||s.MaxOutlierFraction>0.30)
            throw new InvalidDataException("有效帧下界至少50，允许剔除比例0～0.30");
        if(plan.Any(p=>p.InnerTargetDeg<s.AllowedMinDeg||p.InnerTargetDeg>s.AllowedMaxDeg||
            p.OuterTargetDeg<s.AllowedMinDeg||p.OuterTargetDeg>s.AllowedMaxDeg||
            p.OuterDepartDeg<s.AllowedMinDeg||p.OuterDepartDeg>s.AllowedMaxDeg))
            throw new InvalidDataException("计划目标/正反接近起点超过批准的绝对行程范围；禁止跨零点绕行");
        if(safetyRequired&&(!s.DirectionAndCablingApproved||!s.HardwareSafetyConfirmed))
            throw new InvalidOperationException("需确认每一段机械路径、线缆、限位、监护与实体急停");
    }
    private static double Median(IEnumerable<double> values)
    {
        var x=values.OrderBy(v=>v).ToArray();
        if(x.Length==0)throw new InvalidDataException("没有有效采集样本");
        return x.Length%2!=0?x[x.Length/2]:(x[x.Length/2]+x[x.Length/2-1])/2;
    }
    public static (Ct08Visit Visit,bool[] Accepted,double[][] Acc,double[][] Gyro)
        Analyze(Ct08Pose pose,RealTableFeedback before,RealTableFeedback after,
        StaticPointSamples capture,Func<double[],double[]> accCal,Func<double[],double[]> gyroCal,
        Ct08Settings s,int gravitySign,string physicalCsv,string correctedCsv)
    {
        var samples=capture.Samples;
        if(samples.Count<s.MinValidSamples||capture.Batches<3)
            throw new InvalidDataException($"第{pose.Index}站真实帧不足：{samples.Count}帧/{capture.Batches}批");
        var raw=samples.Select(v=>new[]{v.AxG,v.AyG,v.AzG,v.GxDps,v.GyDps,v.GzDps}).ToArray();
        if(raw.Any(v=>v.Any(x=>!double.IsFinite(x))))throw new InvalidDataException("FIFO含无效六轴数值");
        var med=Enumerable.Range(0,6).Select(j=>Median(raw.Select(v=>v[j]))).ToArray();
        var mad=Enumerable.Range(0,6).Select(j=>Math.Max(j<3?0.00015:0.14,
            1.4826*Median(raw.Select(v=>Math.Abs(v[j]-med[j]))))).ToArray();
        var accepted=raw.Select(v=>Enumerable.Range(0,6).All(j=>Math.Abs(v[j]-med[j])<=4.5*mad[j])).ToArray();
        int[] keep=Enumerable.Range(0,raw.Length).Where(i=>accepted[i]).ToArray();
        double rejection=1-keep.Length/(double)raw.Length;
        if(keep.Length<s.MinValidSamples||rejection>s.MaxOutlierFraction)
            throw new InvalidDataException($"第{pose.Index}站有效帧{keep.Length}，剔除率{rejection:P2}未达标");
        var acc=raw.Select(v=>accCal([v[0],v[1],v[2]])).ToArray();
        var gyr=raw.Select(v=>gyroCal([v[3],v[4],v[5]])).ToArray();
        if(acc.Any(v=>v is not {Length:3}||v.Any(x=>!double.IsFinite(x)))||
           gyr.Any(v=>v is not {Length:3}||v.Any(x=>!double.IsFinite(x))))
            throw new InvalidDataException("标定计算得到非有限数值");
        double[] Mean(double[][] x)=>Enumerable.Range(0,3).Select(j=>keep.Average(i=>x[i][j])).ToArray();
        double[] Std(double[][] x,double[] mean)=>Enumerable.Range(0,3).Select(j=>
            Math.Sqrt(keep.Sum(i=>Math.Pow(x[i][j]-mean[j],2))/Math.Max(1,keep.Length-1))).ToArray();
        var accMean=Mean(acc);var gyroMean=Mean(gyr);
        var accStd=Std(acc,accMean);var gyroStd=Std(gyr,gyroMean);
        double inner=Midpoint(before.Inner.PositionDeg,after.Inner.PositionDeg);
        double outer=Midpoint(before.Outer.PositionDeg,after.Outer.PositionDeg);
        var reference=Gravity(inner,outer,gravitySign);double norm=Norm(accMean);
        if(norm<0.7||norm>1.3)throw new InvalidDataException("ACC已校正模长不在合理诊断范围(0.7,1.3)g");
        double temp=keep.Average(i=>samples[i].TemperatureC);
        if(!double.IsFinite(temp))throw new InvalidDataException("无有效芯片温度");
        return (new Ct08Visit(pose.Index,pose.PairIndex,pose.Cycle,pose.Side,
            pose.InnerTargetDeg,pose.OuterTargetDeg,pose.OuterDepartDeg,inner,outer,
            reference,accMean,accStd,gyroMean,gyroStd,Sub(accMean,reference),
            Angle(accMean,reference),norm,temp,raw.Length,keep.Length,rejection,
            capture.Batches,capture.DuplicateBatches,physicalCsv,correctedCsv,
            capture.StartedUtc,capture.EndedUtc),accepted,acc,gyr);
    }
    public static Ct08Pair Pair(Ct08Visit a,Ct08Visit b)
    {
        if(a.PairIndex!=b.PairIndex||a.Side==b.Side||
            Distance(a.InnerTargetDeg,b.InnerTargetDeg)>1e-6||
            Distance(a.OuterTargetDeg,b.OuterTargetDeg)>1e-6)
            throw new InvalidDataException("正反路径不是相同目标姿态，不能配对");
        var forward=a.Side=="正向接近"?a:b;
        var reverse=a.Side=="反向接近"?a:b;
        // Remove the actual encoder-derived gravity vector before differencing.
        // Delta then describes path-dependent SYSTEM residual, not simply a pose-position error.
        var d=Sub(forward.AccErrorG,reverse.AccErrorG);
        double outerDelta=Wrap(forward.OuterActualDeg-reverse.OuterActualDeg);
        double innerDelta=Wrap(forward.InnerActualDeg-reverse.InnerActualDeg);
        var center=Gravity(forward.InnerTargetDeg,forward.OuterTargetDeg,1);
        double projection=Enumerable.Range(0,3).Sum(j=>d[j]*center[j]);
        var tangential=Enumerable.Range(0,3).Select(j=>d[j]-projection*center[j]).ToArray();
        return new Ct08Pair(a.PairIndex,a.Cycle,a.InnerTargetDeg,a.OuterTargetDeg,
            forward.Index,reverse.Index,forward.AccCorrectedMeanG,reverse.AccCorrectedMeanG,
            forward.AccErrorG,reverse.AccErrorG,d.Select(x=>x*1000).ToArray(),
            Norm(d)*1000,Math.Atan2(Norm(tangential),1.0)/Rad,
            outerDelta,innerDelta,forward.MeanTemperatureC-reverse.MeanTemperatureC,
            Sub(forward.GyroCorrectedMeanDps,reverse.GyroCorrectedMeanDps));
    }
    public static Ct08Metrics? Summarize(IReadOnlyList<Ct08Pair> pairs,IReadOnlyList<Ct08Visit> visits)
    {
        if(pairs.Count==0)return null;
        static double Rms(IEnumerable<double> values)=>Math.Sqrt(values.Average(x=>x*x));
        var targets=pairs.GroupBy(p=>(p.InnerTargetDeg,p.OuterTargetDeg))
            .Select(g=>new Ct08TargetSummary(g.Key.InnerTargetDeg,g.Key.OuterTargetDeg,
                g.Count(),g.Average(p=>p.HysteresisMagnitudeMg),Rms(g.Select(p=>p.HysteresisMagnitudeMg)),
                g.Max(p=>p.HysteresisMagnitudeMg),g.Average(p=>p.DirectionHysteresisDeg),
                g.Average(p=>p.OuterActualDifferenceDeg))).ToArray();
        return new Ct08Metrics(pairs.Count,visits.Count,visits.Sum(v=>v.AcceptedSamples),
            Enumerable.Range(0,3).Select(j=>pairs.Average(p=>p.HysteresisErrorMg[j])).ToArray(),
            Rms(pairs.Select(p=>p.HysteresisMagnitudeMg)),pairs.Max(p=>p.HysteresisMagnitudeMg),
            pairs.Average(p=>p.DirectionHysteresisDeg),pairs.Max(p=>p.DirectionHysteresisDeg),
            Rms(pairs.Select(p=>p.OuterActualDifferenceDeg)),
            Rms(pairs.Select(p=>p.InnerActualDifferenceDeg)),
            visits.Min(v=>v.MeanTemperatureC),visits.Max(v=>v.MeanTemperatureC),targets);
    }
}
