using System.Globalization;
using System.IO;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace DynamicInclinometer.Core;

public enum SweepAxis { Roll, Pitch }

/// <summary>
/// A *planned* single-axis sine run. Commanded/ideal reference is NOT encoder
/// feedback and must never be used as the ground truth for real-device accuracy.
/// Rest=1s and one period raised-cosine ramp at each end.
/// </summary>
public sealed record SineSweepPlan(SweepAxis Axis, double AmplitudeDeg, double FrequencyHz,
    int Cycles, double CenterDeg, int SampleHz)
{
    public const double RestSeconds = 1.0;
    public double PeriodSeconds => 1.0 / FrequencyHz;
    public double DurationSeconds => 2*RestSeconds + Cycles*PeriodSeconds;
    public double PeakSpeedUpperBoundDps => 2*Math.PI*FrequencyHz*AmplitudeDeg +
        AmplitudeDeg*Math.PI/PeriodSeconds; // conservative ramp envelope derivative bound
    public double PeakAccelSinusoidDps2 => Math.Pow(2*Math.PI*FrequencyHz,2)*AmplitudeDeg;

    public void Validate()
    {
        if (!double.IsFinite(AmplitudeDeg) || AmplitudeDeg<=0 || AmplitudeDeg>180)
            throw new ArgumentOutOfRangeException(nameof(AmplitudeDeg),"幅值需在 0～180° 内");
        if (!double.IsFinite(CenterDeg)||Math.Abs(CenterDeg)+AmplitudeDeg>180)
            throw new ArgumentOutOfRangeException(nameof(CenterDeg),"中心角和幅值之和不可超过 ±180°");
        if (!double.IsFinite(FrequencyHz)||FrequencyHz<0.005||FrequencyHz>2)
            throw new ArgumentOutOfRangeException(nameof(FrequencyHz),"频率需在 0.005～2 Hz 之间");
        if (Cycles<3||Cycles>200)throw new ArgumentOutOfRangeException(nameof(Cycles),"至少 3 周期，以便首尾平滑启停");
        if (SampleHz<20||SampleHz>2000)throw new ArgumentOutOfRangeException(nameof(SampleHz),"仿真采样率需要 20～2000 Hz");
        if (DurationSeconds>3600)throw new ArgumentOutOfRangeException(nameof(FrequencyHz),"试验总时长不能超过 60 分钟");
        if ((long)Math.Ceiling(DurationSeconds*SampleHz)>500_000)throw new InvalidOperationException("本轮输出采样点数超过限制");
    }

    public double AngleAt(double t)
    {
        if(t<0 || t>DurationSeconds)return CenterDeg;
        double active=t-RestSeconds;
        if(active<=0 || active>=Cycles*PeriodSeconds)return CenterDeg;
        double envelope=1;
        if(active<PeriodSeconds)envelope=.5-.5*Math.Cos(Math.PI*active/PeriodSeconds);
        else if(active>(Cycles-1)*PeriodSeconds)
        {
            var exit=(Cycles*PeriodSeconds-active)/PeriodSeconds;
            envelope=.5-.5*Math.Cos(Math.PI*exit);
        }
        return CenterDeg+AmplitudeDeg*envelope*Math.Sin(2*Math.PI*FrequencyHz*active);
    }
    public double RateAt(double t)
    {
        var step=Math.Min(.001, .0001*PeriodSeconds);
        return (AngleAt(t+step)-AngleAt(t-step))/(2*step);
    }
    public (double roll,double pitch) AnglesAt(double t)
       => Axis==SweepAxis.Roll ? (AngleAt(t),0d) : (0d,AngleAt(t));

    public void WritePlan(string dir)
    {
        Validate();Directory.CreateDirectory(dir);
        File.WriteAllText(Path.Combine(dir,"sine_plan.json"),
           JsonSerializer.Serialize(this,new JsonSerializerOptions{WriteIndented=true,Converters={new JsonStringEnumConverter()}}),Encoding.UTF8);
        using var w=new StreamWriter(Path.Combine(dir,"reference_planned_NOT_ENCODER.csv"),false,new UTF8Encoding(false));
        w.WriteLine("time_s,roll_deg,pitch_deg");
        var c=CultureInfo.InvariantCulture;
        int n=(int)Math.Ceiling(DurationSeconds*SampleHz);
        for(int i=0;i<=n;i++)
        {
            double t=Math.Min(DurationSeconds,(double)i/SampleHz);
            var (r,p)=AnglesAt(t);
            w.WriteLine(string.Join(",",t.ToString("R",c),r.ToString("R",c),p.ToString("R",c)));
        }
    }
}

/// <summary>A configurable static-test *plan*, not a turntable motion driver.</summary>
public sealed record StaticScanPlan(double StartDeg,double EndDeg,double StepDeg,
    double SettleSeconds,double AcquireSeconds)
{
    public void WritePlan(string dir)
    {
        if(!double.IsFinite(StartDeg)||!double.IsFinite(EndDeg)||StartDeg < -180||EndDeg >180||EndDeg <= StartDeg)
            throw new ArgumentOutOfRangeException(nameof(StartDeg),"静态角度需满足 -180≤起点<终点≤180");
        if(!double.IsFinite(StepDeg)||StepDeg<.1||StepDeg>90)throw new ArgumentOutOfRangeException(nameof(StepDeg));
        if(!double.IsFinite(SettleSeconds)||SettleSeconds<0||SettleSeconds>300)throw new ArgumentOutOfRangeException(nameof(SettleSeconds));
        if(!double.IsFinite(AcquireSeconds)||AcquireSeconds<1||AcquireSeconds>300)throw new ArgumentOutOfRangeException(nameof(AcquireSeconds));
        Directory.CreateDirectory(dir);
        using var writer=new StreamWriter(Path.Combine(dir,"static_positions_NOT_EXECUTED.csv"),false,new UTF8Encoding(false));
        writer.WriteLine("step_id,channel,inner_deg,outer_deg,settle_s,acquire_s");
        int id=0;
        foreach(var (inner,channel) in new[]{(0,"Y"),(90,"X")})
            for(double a=StartDeg;a<=EndDeg+1e-8;a+=StepDeg)
            {
                id++;if(id>2000)throw new InvalidOperationException("扫描点数过多");
                writer.WriteLine(string.Join(",",id,channel,inner,a.ToString("R",CultureInfo.InvariantCulture),
                    SettleSeconds.ToString("R",CultureInfo.InvariantCulture),AcquireSeconds.ToString("R",CultureInfo.InvariantCulture)));
            }
    }
}
