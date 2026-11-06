using System.IO;
using System.Diagnostics;
using System.Globalization;
using Dts.TestEngine;
using Dts.Tests.S1.CT10;

namespace Dts.Tests.S1.CT23;

public static class Ct23Algorithm
{
    private const double D2R=Math.PI/180d;
    public static double[] ParseVector(string text)
    {
        if(string.IsNullOrWhiteSpace(text))throw new InvalidDataException("缺少扫描路径");
        var items=text.Split([';', '；', '\n','\r'],StringSplitOptions.RemoveEmptyEntries|StringSplitOptions.TrimEntries);
        if(items.Length is <2 or >10)throw new InvalidDataException("至少2条且最多10条非退化外轴轨迹");
        var path=new List<double>();
        foreach(string item in items)
        {
            var parts=item.Split([':', '：'],StringSplitOptions.RemoveEmptyEntries|StringSplitOptions.TrimEntries);
            if(parts.Length!=2 || !double.TryParse(parts[0],NumberStyles.Float,CultureInfo.InvariantCulture,out var from) ||
                !double.TryParse(parts[1],NumberStyles.Float,CultureInfo.InvariantCulture,out var to) ||
                !double.IsFinite(from)||!double.IsFinite(to))
                throw new InvalidDataException("轨迹格式应为 50:100;75:125;120:60，使用英文小数点");
            path.Add(from);path.Add(to);
        }
        return path.ToArray();
    }
    public static IReadOnlyList<Ct23Plan> BuildPlan(Ct23Settings s)
    {
        var endpoints=ParseVector(s.TrajectoriesText);
        if(s.Repetitions is <1 or >4)throw new InvalidDataException("每条路径重复次数1～4");
        var path=new List<Ct23Plan>();
        for(int r=1;r<=s.Repetitions;r++)
            for(int t=0;t<endpoints.Length/2;t++)
                path.Add(new Ct23Plan(path.Count+1,t+1,r,endpoints[2*t],endpoints[2*t+1],s.MotionSpeedDps));
        return path;
    }
    public static void Validate(Ct23Settings s,IReadOnlyList<Ct23Plan> path,ICt10DynamicHardware? live=null,bool requireSafety=true)
    {
        if(path.Count<2 || path.Count>40)throw new InvalidDataException("CT-23至少两条非退化轨迹，最多40次扫描");
        if(!double.IsFinite(s.MotionSpeedDps)||s.MotionSpeedDps<=0||s.MotionSpeedDps>10 ||
           !double.IsFinite(s.SetupSpeedDps)||s.SetupSpeedDps<=0||s.SetupSpeedDps>10)
            throw new InvalidDataException("速度必须位于(0,10]°/s，且不得超过实际设备验证限速");
        if(s.MinStaticFrames is <50 or >200000 || s.MinDynamicFrames is <20 or >200000)
            throw new InvalidDataException("静态有效帧至少50，动态帧至少20");
        if(!double.IsFinite(s.StaticCaptureSeconds)||s.StaticCaptureSeconds<2||s.StaticCaptureSeconds>60 ||
           !double.IsFinite(s.SettleSeconds)||s.SettleSeconds<1||s.SettleSeconds>90)
            throw new InvalidDataException("每站静态采样2～60秒，静置1～90秒");
        if(!double.IsFinite(s.MaxGyroGapSeconds)||s.MaxGyroGapSeconds<0.02||s.MaxGyroGapSeconds>1.0||
           !double.IsFinite(s.MaxStartEndClockSkewSeconds)||s.MaxStartEndClockSkewSeconds<0.02||s.MaxStartEndClockSkewSeconds>1)
            throw new InvalidDataException("动态数据空洞和运动边界时差阈值必须在0.02～1秒");
        if(!double.IsFinite(s.AllowedMinDeg)||!double.IsFinite(s.AllowedMaxDeg)||
           s.AllowedMinDeg<0||s.AllowedMinDeg>0||s.AllowedMaxDeg>360||s.AllowedMinDeg>=s.AllowedMaxDeg)
            throw new InvalidDataException("声明允许行程必须覆盖0°并具有有效上界");
        if(!double.IsFinite(s.PositionToleranceDeg)||s.PositionToleranceDeg<0.01||s.PositionToleranceDeg>0.5 ||
           !double.IsFinite(s.MaxEncoderGyroAngleDiscrepancyDeg)||s.MaxEncoderGyroAngleDiscrepancyDeg<1||
           s.MaxEncoderGyroAngleDiscrepancyDeg>90)
            throw new InvalidDataException("到位容差0.01～0.5°；映射异常诊断阈值1～90°");
        if(path.Any(p=>p.OuterStartDeg<s.AllowedMinDeg||p.OuterStartDeg>s.AllowedMaxDeg||
            p.OuterEndDeg<s.AllowedMinDeg||p.OuterEndDeg>s.AllowedMaxDeg||
            Math.Abs(p.OuterEndDeg-p.OuterStartDeg)<20||
            Math.Abs(p.OuterEndDeg-p.OuterStartDeg)>120))
            throw new InvalidDataException("每条外轴轨迹须在机械允许行程内，位移20～120°且不跨越未批准区域");
        if(path.Select(x=>x.OuterStartDeg).Distinct().Count()<2 ||
           path.Select(x=>x.OuterEndDeg).Distinct().Count()<2)
            throw new InvalidDataException("多条轨迹不能共用完全相同起止姿态，否则多姿态可观测性不足");
        if(requireSafety && (!s.SafetyApproved||!s.EmergencyStopConfirmed||!s.AccGyroAxesVerified))
            throw new InvalidOperationException("请确认坐标系、允许行程、线缆、实体急停和现场监护");
        if(live is not null)
        {
            var limit=live.MaximumCertifiedSpeedDps(Ct10Axis.Outer);
            if(!live.IsRealDynamicCaptureReady||!double.IsFinite(limit)||limit<s.MotionSpeedDps||limit<s.SetupSpeedDps)
                throw new InvalidOperationException("CT-10真实动态采集未就绪，或速度超过已核验硬件上限，禁止运动");
        }
    }
    public static double[] Gravity(double innerDeg,double outerDeg,int sign)
    {
        if(sign is not (1 or -1))throw new InvalidDataException("ACC JSON的gravity_sign无效");
        double i=innerDeg*D2R,o=outerDeg*D2R;
        return [sign*Math.Sin(i)*Math.Sin(o),sign*Math.Cos(i)*Math.Sin(o),sign*Math.Cos(o)];
    }
    public static double Norm(IReadOnlyList<double> v)=>Math.Sqrt(v.Sum(x=>x*x));
    public static double[] Unit(IReadOnlyList<double> v)
    {
        double n=Norm(v);if(!double.IsFinite(n)||n<0.5||n>1.5)
            throw new InvalidDataException($"静态ACC重力模长异常：{n:F5}g");
        return v.Select(x=>x/n).ToArray();
    }
    public static double Angle(IReadOnlyList<double> x,IReadOnlyList<double> y)
    {
        double a=Norm(x)*Norm(y);if(a<=1e-12)throw new InvalidDataException("参考矢量无效");
        return Math.Acos(Math.Clamp(Enumerable.Range(0,3).Sum(j=>x[j]*y[j])/a,-1,1))/D2R;
    }
    public static double[] MeanCorrected(StaticPointSamples capture,int minimum,Func<double[],double[]> cal,bool gyro)
    {
        if(capture.Samples.Count<minimum||capture.Batches<3||capture.DuplicateBatches>capture.Batches)
            throw new InvalidDataException($"静态样本不足或重复FIFO批次过多：{capture.Samples.Count}帧");
        double[] sum=new double[3];
        foreach(var v in capture.Samples)
        {
            double[] raw=gyro ? new double[]{v.GxDps,v.GyDps,v.GzDps} : new double[]{v.AxG,v.AyG,v.AzG};
            double[] calibrated=cal(raw);
            if(calibrated is not{Length:3}||calibrated.Any(x=>!double.IsFinite(x)))
                throw new InvalidDataException("常温标定输出存在非有限数值");
            for(int j=0;j<3;j++)sum[j]+=calibrated[j];
        }
        for(int j=0;j<3;j++)sum[j]/=capture.Samples.Count;
        return sum;
    }
    public static (double[] Predicted, double[] IntegratedGyroDegrees,
        double ElapsedSeconds, double MaxGapSeconds, IReadOnlyList<Ct23TracePoint> Points,
        double ActualStartDeg,double ActualEndDeg)
        Integrate(Ct10Capture capture,double[] staticStartGravity,double[] zeroDps,
        Func<double[],double[]> gyroCal,int expectedFs,Ct23Plan requested,Ct23Settings s)
    {
        if(!capture.MotionCompletedNormally||capture.GyroCalibrationInputFullScaleDps!=expectedFs||
           capture.TimestampFrequency!=Stopwatch.Frequency||capture.GyroFrames.Count<s.MinDynamicFrames||capture.EncoderFrames.Count<12)
            throw new InvalidDataException("动态硬件采集不完整/历史Gyro量程不一致");
        var frames=capture.GyroFrames.OrderBy(f=>f.TimestampTicks).ToArray();
        var enc=capture.EncoderFrames.OrderBy(e=>e.TimestampTicks).ToArray();
        if(frames.Zip(frames.Skip(1)).Any(z=>z.First.TimestampTicks>=z.Second.TimestampTicks)||
           enc.Zip(enc.Skip(1)).Any(z=>z.First.TimestampTicks>=z.Second.TimestampTicks))
            throw new InvalidDataException("真实动态时间戳重复或逆序");
        if(enc.Any(e=>!e.InnerNormal||!e.OuterNormal||!e.InnerEnabled||!e.OuterEnabled||
            Math.Abs(e.InnerDeg)>0.3||e.OuterDeg<s.AllowedMinDeg-0.3||e.OuterDeg>s.AllowedMaxDeg+0.3))
            throw new InvalidDataException("运动期间转台失能、报警或固定内轴不在0°");
        double start=enc[0].OuterDeg,end=enc[^1].OuterDeg;
        if(Math.Abs(start-requested.OuterStartDeg)>s.PositionToleranceDeg+0.15||
           Math.Abs(end-requested.OuterEndDeg)>s.PositionToleranceDeg+0.15)
            throw new InvalidDataException("实际编码器运动端点与已批准路径不一致");
        // Require that gyro captures BOTH the departure and arrival; not merely the constant-speed interior.
        var leave=enc.FirstOrDefault(e=>Math.Abs(e.OuterDeg-start)>0.15)
            ??throw new InvalidDataException("编码器未检测到实际离位");
        var reached=enc.FirstOrDefault(e=>Math.Abs(e.OuterDeg-end)<s.PositionToleranceDeg+0.10 &&
            e.TimestampTicks>leave.TimestampTicks)
            ??throw new InvalidDataException("编码器未检测到终点");
        long lag=(long)Math.Round(s.MaxStartEndClockSkewSeconds*capture.TimestampFrequency);
        if(frames[0].TimestampTicks>leave.TimestampTicks+lag||
           frames[^1].TimestampTicks<reached.TimestampTicks-lag)
            throw new InvalidDataException("Gyro真实遥测未覆盖完整运动区间，无法积分闭合");
        // Use the first/last gyro samples within observed feedback domain; pre/post stationary frames
        // may be integrated as zero-bias-corrected estimates, not fabricated samples.
        long t0=Math.Max(frames[0].TimestampTicks,enc[0].TimestampTicks);
        long t1=Math.Min(frames[^1].TimestampTicks,enc[^1].TimestampTicks);
        var active=frames.Where(f=>f.TimestampTicks>=t0&&f.TimestampTicks<=t1).ToArray();
        if(active.Length<s.MinDynamicFrames||active[0].TimestampTicks>leave.TimestampTicks+lag||
           active[^1].TimestampTicks<reached.TimestampTicks-lag)
            throw new InvalidDataException("可积分真实Gyro帧未充分覆盖运动起止");
        var gravity=Unit(staticStartGravity);
        var acc=new double[3];var outFrames=new List<Ct23TracePoint>(active.Length);
        double[] Corrected(Ct10GyroFrame g)
        {
            if(g.RawCountX is null||g.RawCountY is null||g.RawCountZ is null)
                throw new InvalidDataException("动态Gyro缺少原始三轴计数，拒绝六轴联合结论");
            double scale=expectedFs switch{125=>0.004375,250=>0.00875,500=>0.0175,
                1000=>0.035,2000=>0.070,_=>throw new InvalidDataException("不支持的Gyro历史量程")};
            if(Math.Abs(g.InputX_Dps-g.RawCountX.Value*scale)>1e-6||
               Math.Abs(g.InputY_Dps-g.RawCountY.Value*scale)>1e-6||
               Math.Abs(g.InputZ_Dps-g.RawCountZ.Value*scale)>1e-6)
                throw new InvalidDataException("真实计数与物理量不一致，禁止重复换算");
            var gcal=gyroCal([g.InputX_Dps,g.InputY_Dps,g.InputZ_Dps]);
            if(gcal is not{Length:3}||gcal.Any(x=>!double.IsFinite(x)))
                throw new InvalidDataException("Gyro标定存在非法数值");
            return Enumerable.Range(0,3).Select(j=>gcal[j]-zeroDps[j]).ToArray();
        }
        double[][] angular=active.Select(Corrected).ToArray();
        double maxGap=0;
        for(int i=0;i<active.Length;i++)
        {
            if(i>0)
            {
                double dt=(active[i].TimestampTicks-active[i-1].TimestampTicks)/(double)capture.TimestampFrequency;
                maxGap=Math.Max(maxGap,dt);
                if(dt<=0||dt>s.MaxGyroGapSeconds)
                    throw new InvalidDataException($"Gyro采样间隔{dt:F3}s超过允许值{s.MaxGyroGapSeconds:F3}s");
                double[] rate=Enumerable.Range(0,3).Select(j=>(angular[i-1][j]+angular[i][j])/2).ToArray();
                for(int j=0;j<3;j++)acc[j]+=rate[j]*dt;
                // g_body(t+dt) = Exp[-(omega_body cross)dt] * g_body(t).
                gravity=Rotate(gravity,rate.Select(x=>-x*dt*D2R).ToArray());
            }
            var f=active[i];
            outFrames.Add(new Ct23TracePoint((f.TimestampTicks-active[0].TimestampTicks)/(double)capture.TimestampFrequency,
                f.TimestampTicks,angular[i][0],angular[i][1],angular[i][2],gravity[0],gravity[1],gravity[2],
                f.TemperatureC,f.RawCountX,f.RawCountY,f.RawCountZ));
        }
        double elapsed=(active[^1].TimestampTicks-active[0].TimestampTicks)/(double)capture.TimestampFrequency;
        return(gravity,acc,elapsed,maxGap,outFrames,start,end);
    }
    public static double[] Rotate(IReadOnlyList<double> v,IReadOnlyList<double> deltaRad)
    {
        double theta=Norm(deltaRad);
        if(theta<1e-12)return v.ToArray();
        double x=deltaRad[0]/theta,y=deltaRad[1]/theta,z=deltaRad[2]/theta;
        double c=Math.Cos(theta),si=Math.Sin(theta),dot=x*v[0]+y*v[1]+z*v[2];
        return [c*v[0]+si*(y*v[2]-z*v[1])+(1-c)*dot*x,
                c*v[1]+si*(z*v[0]-x*v[2])+(1-c)*dot*y,
                c*v[2]+si*(x*v[1]-y*v[0])+(1-c)*dot*z];
    }
    public static Ct23Metrics? Summarize(IReadOnlyList<Ct23Trial> trials)
    {
        if(trials.Count==0)return null;
        double rms=Math.Sqrt(trials.Average(t=>t.ClosureAngleDeg*t.ClosureAngleDeg));
        double gyroRms=Math.Sqrt(trials.Average(t=>t.XAxisVsEncoderDifferenceDeg*t.XAxisVsEncoderDifferenceDeg));
        return new Ct23Metrics(trials.Select(t=>t.TrajectoryIndex).Distinct().Count(),trials.Count,
            rms,trials.Max(t=>t.ClosureAngleDeg),trials.Average(t=>t.ClosureAngleDeg),
            trials.Average(t=>t.StartReferenceErrorDeg),trials.Average(t=>t.EndReferenceErrorDeg),
            gyroRms,"LIMITED_ONE_DRIVEN_AXIS_NO_3D_ALIGNMENT_MATRIX",
            "单轴多倾角动态重力闭合完成；不能辨识完整ACC/Gyro三维相对旋转矩阵，研发诊断/待验收");
    }
}
