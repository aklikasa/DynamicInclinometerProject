using System.Globalization;
using Dts.TestEngine;

namespace Dts.Tests.S1.CT16;

public static class Ct16Algorithm
{
    private const double Rad=Math.PI/180.0;
    public static double[] ParseSpeeds(string text)
    {
        var pieces=text.Split([',','，',';','；',' ','\n','\r','\t'],
            StringSplitOptions.RemoveEmptyEntries|StringSplitOptions.TrimEntries);
        if(pieces.Length is <1 or >8)throw new InvalidDataException("设置1～8档低速角速度");
        var speeds=new List<double>();
        foreach(var token in pieces)
        {
            if(!double.TryParse(token,NumberStyles.Float,CultureInfo.InvariantCulture,out var n)||
                !double.IsFinite(n)||n<0.05||n>5)
                throw new InvalidDataException("低速档位须为0.05～5°/s："+token);
            if(speeds.Any(v=>Math.Abs(v-n)<1e-8))throw new InvalidDataException("速度档位不能重复");
            speeds.Add(n);
        }
        return speeds.ToArray();
    }
    public static IReadOnlyList<Ct16PlanItem> BuildPlan(Ct16Settings s)
    {
        var speeds=ParseSpeeds(s.SpeedsDps);
        if(s.Repeats is <1 or >8)throw new InvalidDataException("每档方向重复次数须为1～8");
        var result=new List<Ct16PlanItem>();int index=0;
        foreach(double speed in speeds)
        for(int r=1;r<=s.Repeats;r++)
        {
            int[] dirs=r%2==1?[1,-1]:[-1,1];
            foreach(int dir in dirs)
                result.Add(new Ct16PlanItem(++index,speed,r,dir>0?"正向离位/反向归零":"反向离位/正向归零",
                    s.InnerFixedDeg,s.OuterHomeDeg,s.OuterHomeDeg+dir*s.ExcursionDeg));
        }
        return result;
    }
    public static void Validate(Ct16Settings s,IReadOnlyList<Ct16PlanItem> plan,bool safetyRequired=true)
    {
        if(plan.Count is <2 or >128)throw new InvalidDataException("必须包含正反方向且最多128组");
        double[] nums=[s.InnerFixedDeg,s.OuterHomeDeg,s.ExcursionDeg,s.PrepareSpeedDps,
            s.BaselineSeconds,s.RecoverySeconds,s.BinSeconds,s.RecoveryThresholdDeg,
            s.PositionToleranceDeg,s.AllowedMinDeg,s.AllowedMaxDeg];
        if(nums.Any(n=>!double.IsFinite(n)))throw new InvalidDataException("所有参数必须为有限数值");
        if(s.AllowedMinDeg!=0 || s.AllowedMaxDeg is <=0 or >180)
            throw new InvalidDataException("保守运动路径需批准0°停靠，允许行程下界必须为0°，上界≤180°");
        if(s.InnerFixedDeg<0||s.InnerFixedDeg>s.AllowedMaxDeg||s.OuterHomeDeg<0||s.OuterHomeDeg>s.AllowedMaxDeg||
           s.ExcursionDeg<1||s.ExcursionDeg>60 || plan.Any(p=>p.ExcursionTargetDeg<0||p.ExcursionTargetDeg>s.AllowedMaxDeg))
            throw new InvalidDataException("目标角/正反离开点超出批准的绝对行程或偏移幅度超出1～60°");
        if(s.PrepareSpeedDps<0.05||s.PrepareSpeedDps>5)
            throw new InvalidDataException("准备定位速度为0.05～5°/s");
        if(s.BaselineSeconds<2||s.BaselineSeconds>120||s.RecoverySeconds<6||s.RecoverySeconds>300||
           s.BinSeconds<1||s.BinSeconds>20||s.RecoverySeconds/s.BinSeconds<3||
           s.RecoverySeconds/s.BinSeconds>150)
            throw new InvalidDataException("基线2～120s，恢复6～300s，窗口1～20s，恢复需3～150个窗口");
        if(s.RecoveryThresholdDeg<=0||s.RecoveryThresholdDeg>5||s.ConsecutiveBins is <2 or >10 ||
           s.PositionToleranceDeg<=0||s.PositionToleranceDeg>0.5||s.ExcursionDeg<5*s.PositionToleranceDeg)
            throw new InvalidDataException("恢复阈值(0,5]°，连续窗口2～10，到位容差(0,0.5]°");
        if(s.MinValidSamplesPerBin is <20 or >100000)throw new InvalidDataException("每窗至少20帧有效真实FIFO");
        if(safetyRequired&&(!s.PathAndCablingApproved||!s.EStopAndSupervisionApproved))
            throw new InvalidOperationException("请在现场核验绝对路径、线缆、硬件限位、实体急停及监护");
    }
    public static double Distance(double x,double y)=>Math.Abs(((x-y+180)%360+360)%360-180);
    public static double Norm(IReadOnlyList<double> v)=>Math.Sqrt(v.Sum(x=>x*x));
    public static double[] Gravity(double inner,double outer,int sign)
    {
        if(sign is not (-1 or 1))throw new InvalidDataException("gravity_sign必须为±1");
        double i=inner*Rad,o=outer*Rad;
        return [sign*Math.Sin(i)*Math.Sin(o),sign*Math.Cos(i)*Math.Sin(o),sign*Math.Cos(o)];
    }
    public static double[] Unit(IReadOnlyList<double> v)
    {
        double n=Norm(v);if(n<0.7||n>1.3)throw new InvalidDataException("ACC重力模长不在0.7～1.3g诊断区间");
        return v.Select(x=>x/n).ToArray();
    }
    private static double Dot(IReadOnlyList<double> a,IReadOnlyList<double> b)=>
        Enumerable.Range(0,3).Sum(j=>a[j]*b[j]);
    public static double Angle(IReadOnlyList<double> a,IReadOnlyList<double> b)=>
        Math.Acos(Math.Clamp(Dot(Unit(a),Unit(b)),-1,1))/Rad;
    public static double[] Tangent(IReadOnlyList<double> baseline,double inner,double outer,int sign)
    {
        var refPlus=Gravity(inner,outer+0.05,sign);
        var refMinus=Gravity(inner,outer-0.05,sign);
        var b=Unit(baseline);
        var raw=Enumerable.Range(0,3).Select(j=>refPlus[j]-refMinus[j]).ToArray();
        double projection=Dot(raw,b);
        var perp=Enumerable.Range(0,3).Select(j=>raw[j]-projection*b[j]).ToArray();
        double n=Norm(perp);
        if(n<1e-8)throw new InvalidDataException("参考姿态切向不可辨识");
        return perp.Select(x=>x/n).ToArray();
    }
    public static double SignedTilt(IReadOnlyList<double> acc,IReadOnlyList<double> baseline,IReadOnlyList<double> tangent)
    {
        var v=Unit(acc);var b=Unit(baseline);
        return Math.Atan2(Dot(v,tangent),Dot(v,b))/Rad;
    }
    public static (double[] Acc,double[] Gyro,double Temp,int Count) MeanStatic(
        StaticPointSamples samples,Func<double[],double[]> accCal,Func<double[],double[]> gyroCal,
        int minSamples)
    {
        if(samples.Samples.Count<minSamples||samples.Batches<3)
            throw new InvalidDataException($"有效真实FIFO不足：{samples.Samples.Count}帧/{samples.Batches}批");
        if(samples.Samples.Any(v=>!double.IsFinite(v.AxG)||!double.IsFinite(v.AyG)||!double.IsFinite(v.AzG)||
            !double.IsFinite(v.GxDps)||!double.IsFinite(v.GyDps)||!double.IsFinite(v.GzDps)||
            !double.IsFinite(v.TemperatureC)))throw new InvalidDataException("真实六轴或温度含非有限数值");
        var acc=samples.Samples.Select(v=>accCal([v.AxG,v.AyG,v.AzG])).ToArray();
        var gyr=samples.Samples.Select(v=>gyroCal([v.GxDps,v.GyDps,v.GzDps])).ToArray();
        if(acc.Any(v=>v is not {Length:3}||v.Any(x=>!double.IsFinite(x)))||
           gyr.Any(v=>v is not {Length:3}||v.Any(x=>!double.IsFinite(x))))
            throw new InvalidDataException("标定矩阵返回无效六轴数值");
        int count=acc.Length;
        return (Enumerable.Range(0,3).Select(j=>acc.Average(v=>v[j])).ToArray(),
            Enumerable.Range(0,3).Select(j=>gyr.Average(v=>v[j])).ToArray(),
            samples.Samples.Average(v=>v.TemperatureC),count);
    }
    public static (double Peak,double PeakSigned,double FinalSigned,double FinalAngle,double? RecoveredBy)
        SummarizeRecovery(IReadOnlyList<Ct16Bin> bins,double threshold,int consecutive)
    {
        if(bins.Count<3)throw new InvalidDataException("恢复曲线数据不足");
        double peak=bins.Max(b=>b.AngularDisplacementDeg);
        double signedPeak=bins.OrderByDescending(b=>Math.Abs(b.SignedTiltProxyDeg)).First().SignedTiltProxyDeg;
        double? recovered=null;int count=0;
        for(int i=0;i<bins.Count;i++)
        {
            var b=bins[i];
            bool stable=b.AngularDisplacementDeg<=threshold&&Math.Abs(b.SignedTiltProxyDeg)<=threshold;
            count=stable?count+1:0;
            // Reject a transient threshold crossing that later rebounds above threshold.
            if(count>=consecutive && bins.Skip(i+1).All(x=>
                x.AngularDisplacementDeg<=threshold&&Math.Abs(x.SignedTiltProxyDeg)<=threshold))
            { recovered=b.SinceStopSeconds;break; }
        }
        return (peak,signedPeak,bins[^1].SignedTiltProxyDeg,bins[^1].AngularDisplacementDeg,recovered);
    }
    public static Ct16Aggregate? Summarize(IReadOnlyList<Ct16Cycle> cycles)
    {
        if(cycles.Count==0)return null;
        var t=cycles.Where(x=>x.RecoveredBySeconds is not null).Select(x=>x.RecoveredBySeconds!.Value).ToArray();
        return new Ct16Aggregate(cycles.Count,t.Length,cycles.Max(x=>x.PeakObservedAfterStopDeg),
            cycles.Average(x=>x.FinalAngularOffsetDeg),t.Length==0?null:t.Average());
    }
}
