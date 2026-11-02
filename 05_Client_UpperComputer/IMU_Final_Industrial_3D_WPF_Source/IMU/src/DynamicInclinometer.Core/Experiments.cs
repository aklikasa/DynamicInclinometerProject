using System.Globalization;
using System.IO;
using System.Text;
using System.Text.Json;

namespace DynamicInclinometer.Core;

public readonly record struct AnglePoint(double Seconds,double RollDeg,double PitchDeg);
public sealed record ExperimentMetrics(int Count,double RollRmseDeg,double PitchRmseDeg,double RollMaxAbsDeg,double PitchMaxAbsDeg,double RollBiasDeg,double PitchBiasDeg);

/// <summary>Independent angle/error statistics. No automatic time alignment is inferred.</summary>
public static class AngleEvaluator
{
    public static double Wrap180(double x) { x=(x+180)%360;if(x<0)x+=360;return x-180; }
    public static ExperimentMetrics Evaluate(IReadOnlyList<AnglePoint> measured,IReadOnlyList<AnglePoint> reference,double maxAgeSeconds=0.03)
    {
        if(reference.Count<2)throw new InvalidDataException("参考数据至少需要 2 个时刻，且必须经过时间同步");
        var referenceSorted=reference.OrderBy(x=>x.Seconds).ToArray();
        var er=new List<double>();var ep=new List<double>();
        foreach(var item in measured)
        {
            int j=Array.BinarySearch(referenceSorted,new AnglePoint(item.Seconds,0,0),Comparer<AnglePoint>.Create((a,b)=>a.Seconds.CompareTo(b.Seconds)));
            if(j<0)j=~j;
            if(j<=0||j>=referenceSorted.Length)continue;
            var a=referenceSorted[j-1];var b=referenceSorted[j];
            if(b.Seconds<=a.Seconds||item.Seconds-a.Seconds>maxAgeSeconds||b.Seconds-item.Seconds>maxAgeSeconds)continue;
            double u=(item.Seconds-a.Seconds)/(b.Seconds-a.Seconds);
            double rr=a.RollDeg+Wrap180(b.RollDeg-a.RollDeg)*u;
            double rp=a.PitchDeg+Wrap180(b.PitchDeg-a.PitchDeg)*u;
            er.Add(Wrap180(item.RollDeg-rr));ep.Add(Wrap180(item.PitchDeg-rp));
        }
        if(er.Count==0)throw new InvalidDataException("没有足够同步参考点；请检查时钟对齐、反馈频率、延迟和参考角定义");
        double Rmse(List<double> v)=>Math.Sqrt(v.Average(x=>x*x));
        return new(er.Count,Rmse(er),Rmse(ep),er.Max(x=>Math.Abs(x)),ep.Max(x=>Math.Abs(x)),er.Average(),ep.Average());
    }
}

public static class ExperimentReport
{
    public static string WriteMetrics(string directory,ExperimentMetrics m,string note)
    {
        Directory.CreateDirectory(directory);
        var p=Path.Combine(directory,"angle_metrics.json");
        File.WriteAllText(p,JsonSerializer.Serialize(new {timestamp_utc=DateTimeOffset.UtcNow,metrics=m,note},new JsonSerializerOptions {WriteIndented=true}),Encoding.UTF8);
        return p;
    }
}

public sealed record StaticWindowMetrics(double DurationSeconds,int Samples,ExperimentMetrics Errors,double RollStdDeg,double PitchStdDeg);
public static class StaticWindowEvaluator
{
    public static StaticWindowMetrics EvaluateLastSeconds(IReadOnlyList<AnglePoint> all,double refRollDeg,double refPitchDeg,double seconds=5)
    {
        if(all.Count<5)throw new InvalidDataException("静态数据不足");
        var end=all.Max(x=>x.Seconds);
        var measured=all.Where(x=>x.Seconds>=end-seconds && x.Seconds<=end).OrderBy(x=>x.Seconds).ToArray();
        if(measured.Length<5 || measured[^1].Seconds-measured[0].Seconds < seconds*.90)
            throw new InvalidDataException("最后一个静态采样窗口不足 90% 指定时长");
        double[] er=measured.Select(x=>AngleEvaluator.Wrap180(x.RollDeg-refRollDeg)).ToArray();
        double[] ep=measured.Select(x=>AngleEvaluator.Wrap180(x.PitchDeg-refPitchDeg)).ToArray();
        static double Rmse(double[] v)=>Math.Sqrt(v.Average(x=>x*x));
        static double Sd(double[] v){double avg=v.Average();return Math.Sqrt(v.Sum(x=>(x-avg)*(x-avg))/Math.Max(1,v.Length-1));}
        return new StaticWindowMetrics(measured[^1].Seconds-measured[0].Seconds,measured.Length,
            new ExperimentMetrics(measured.Length,Rmse(er),Rmse(ep),er.Max(x=>Math.Abs(x)),ep.Max(x=>Math.Abs(x)),er.Average(),ep.Average()),Sd(er),Sd(ep));
    }
}
