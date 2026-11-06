using System.Globalization;
using System.IO;

namespace Dts.Tests.S1.CT25;

public static class Ct25Algorithm
{
    private const double TwoPi=2*Math.PI;
    public static double[] ParseCsv(string csv,string label)
    {
        var words=csv.Split([',','，',';','；',' ','\r','\n','\t'],
            StringSplitOptions.RemoveEmptyEntries|StringSplitOptions.TrimEntries);
        if(words.Length is <1 or >12) throw new InvalidDataException(label+"必须输入1～12个数值");
        var values=new List<double>();
        foreach(var word in words)
        {
            if(!double.TryParse(word,NumberStyles.Float,CultureInfo.InvariantCulture,out double v)||
                !double.IsFinite(v)||v<=0) throw new InvalidDataException(label+"无效数值："+word);
            if(values.Any(x=>Math.Abs(x-v)<1e-9)) throw new InvalidDataException(label+"不可有重复值："+word);
            values.Add(v);
        }
        return values.ToArray();
    }
    public static IReadOnlyList<Ct25Plan> BuildPlan(Ct25Settings s,
        ICt25DynamicTiltHardware? device=null)
    {
        if(!s.TestX&&!s.TestY)throw new InvalidDataException("至少选择一根测试轴");
        if(s.Cycles is <6 or >30||s.Repeats is <1 or >10)
            throw new InvalidDataException("每档至少6周期，最多30周期；重复次数1～10");
        var amplitudes=ParseCsv(s.AmplitudesCsv,"幅值");
        var frequencies=ParseCsv(s.FrequenciesCsv,"频率");
        if(amplitudes.Any(a=>a>10)||frequencies.Any(f=>f<0.01||f>2))
            throw new InvalidDataException("幅值不得超过±10°，频率须在0.01～2Hz（并受实际设备认证能力限制）");
        var plan=new List<Ct25Plan>();int index=0;
        foreach(var axis in new[]{Ct25Axis.OuterX,Ct25Axis.InnerY})
        {
            if(axis==Ct25Axis.OuterX&&!s.TestX||axis==Ct25Axis.InnerY&&!s.TestY)continue;
            double center=axis==Ct25Axis.OuterX?s.OuterCenterDeg:s.InnerCenterDeg;
            foreach(double a in amplitudes)
            foreach(double f in frequencies)
            for(int rep=1;rep<=s.Repeats;rep++)
            {
                double v=TwoPi*f*a,acc=TwoPi*TwoPi*f*f*a;
                string reason="";
                if(center-a<s.ApprovedMinDeg||center+a>s.ApprovedMaxDeg)
                    reason="正弦完整行程超过批准的机械位置上下界";
                else if(device is not null)
                {
                    if(!device.IsReadyForTrueSineAndFusedTilt)reason="真实正弦和设备融合倾角接口未就绪";
                    else if(!double.IsFinite(device.MaximumCertifiedSpeedDps(axis))||
                            device.MaximumCertifiedSpeedDps(axis)<=0||v>device.MaximumCertifiedSpeedDps(axis))
                        reason="正弦峰值速度超过实际设备已认证限速";
                    else if(!double.IsFinite(device.MaximumCertifiedAccelerationDps2(axis))||
                            device.MaximumCertifiedAccelerationDps2(axis)<=0||
                            acc>device.MaximumCertifiedAccelerationDps2(axis))
                        reason="正弦峰值加速度超过实际设备已认证限加速度";
                    else if(!double.IsFinite(device.MinimumCertifiedFrequencyHz(axis))||
                            !double.IsFinite(device.MaximumCertifiedFrequencyHz(axis))||
                            f<device.MinimumCertifiedFrequencyHz(axis)||
                            f>device.MaximumCertifiedFrequencyHz(axis))
                        reason="频率超出设备已认证的正弦跟踪范围";
                }
                plan.Add(new Ct25Plan(++index,axis,a,f,rep,s.Cycles,center,v,acc,s.Cycles/f,
                    reason.Length==0,reason));
            }
        }
        if(plan.Count>250)throw new InvalidDataException("参数组合过多，最多250项");
        return plan;
    }
    public static void Validate(Ct25Settings s,IReadOnlyList<Ct25Plan> plan,bool safety=true)
    {
        if(plan.Count==0)throw new InvalidDataException("测试计划为空");
        if(!double.IsFinite(s.ApprovedMinDeg)||!double.IsFinite(s.ApprovedMaxDeg)||
            s.ApprovedMinDeg<0||s.ApprovedMaxDeg>360||s.ApprovedMinDeg>=s.ApprovedMaxDeg||
            s.ApprovedMinDeg>0)throw new InvalidDataException("批准行程须在0～360°内并包含0°（内轴换位需外轴归0）");
        if(!double.IsFinite(s.InnerCenterDeg)||!double.IsFinite(s.OuterCenterDeg)||
            s.InnerCenterDeg<s.ApprovedMinDeg||s.InnerCenterDeg>s.ApprovedMaxDeg||
            s.OuterCenterDeg<s.ApprovedMinDeg||s.OuterCenterDeg>s.ApprovedMaxDeg)
            throw new InvalidDataException("中心角必须在批准行程内");
        if(!double.IsFinite(s.SetupSpeedDps)||s.SetupSpeedDps<=0||s.SetupSpeedDps>5||
            !double.IsFinite(s.SettleSeconds)||s.SettleSeconds<1||s.SettleSeconds>60||
            !double.IsFinite(s.RecoverySeconds)||s.RecoverySeconds<2||s.RecoverySeconds>120)
            throw new InvalidDataException("定位速度应为(0,5]°/s，静置1～60s，回零观察2～120s");
        if(!double.IsFinite(s.PhaseClockToleranceMs)||s.PhaseClockToleranceMs<=0||
            s.PhaseClockToleranceMs>30||
            !double.IsFinite(s.MaximumGapSeconds)||s.MaximumGapSeconds<=0||
            s.MaximumGapSeconds>0.25||
            s.MinimumSteadyFrames<100||s.MinimumSteadyFrames>1000000||
            !double.IsFinite(s.EncoderWaveformMinR2)||s.EncoderWaveformMinR2<0.9||
            s.EncoderWaveformMinR2>=1||
            !double.IsFinite(s.AmplitudeToleranceFraction)||
            s.AmplitudeToleranceFraction<0.01||s.AmplitudeToleranceFraction>0.25)
            throw new InvalidDataException("时间精度/间隙、最少样本、正弦R²和幅值容差设置无效");
        if(s.AxisXSign is not (1 or -1)||s.AxisYSign is not (1 or -1))
            throw new InvalidDataException("两轴方向映射须为+1或-1");
        if(safety&&(!s.MechanicalSafetyApproved||!s.PhysicalEstopConfirmed||!s.FusionMappingVerified))
            throw new InvalidOperationException("未确认机械路径、物理急停和真实设备融合倾角轴向映射");
    }

    private sealed record FitResult(double Dc,double Sin,double Cos,double Amplitude,
        double PhaseRadians,double R2);
    private static FitResult Fit(double[] time,double[] value,double hz)
    {
        var sums=new double[3,4];double[] phi=new double[3];
        for(int i=0;i<time.Length;i++)
        {
            phi[0]=1;phi[1]=Math.Sin(TwoPi*hz*time[i]);phi[2]=Math.Cos(TwoPi*hz*time[i]);
            for(int r=0;r<3;r++)
            {
                for(int c=0;c<3;c++)sums[r,c]+=phi[r]*phi[c];
                sums[r,3]+=phi[r]*value[i];
            }
        }
        for(int k=0;k<3;k++)
        {
            int best=k;
            for(int r=k+1;r<3;r++)if(Math.Abs(sums[r,k])>Math.Abs(sums[best,k]))best=r;
            if(Math.Abs(sums[best,k])<1e-10)throw new InvalidDataException("采样时刻分布退化，无法拟合幅相");
            if(best!=k)for(int j=k;j<4;j++)(sums[k,j],sums[best,j])=(sums[best,j],sums[k,j]);
            double scale=sums[k,k];for(int j=k;j<4;j++)sums[k,j]/=scale;
            for(int r=0;r<3;r++)if(r!=k)
            {
                double factor=sums[r,k];
                for(int j=k;j<4;j++)sums[r,j]-=factor*sums[k,j];
            }
        }
        double dc=sums[0,3],sin=sums[1,3],cos=sums[2,3];
        double avg=value.Average();double total=0,resid=0;
        for(int i=0;i<time.Length;i++)
        {
            double predicted=dc+sin*Math.Sin(TwoPi*hz*time[i])+cos*Math.Cos(TwoPi*hz*time[i]);
            total+=Math.Pow(value[i]-avg,2);resid+=Math.Pow(value[i]-predicted,2);
        }
        return new FitResult(dc,sin,cos,Math.Sqrt(sin*sin+cos*cos),
            Math.Atan2(cos,sin),total<1e-12?0:1-resid/total);
    }
    public static (Ct25Result Result,IReadOnlyList<Ct25TraceRow> Trace) Analyze(
        Ct25Plan plan,Ct25Capture capture,Ct25Settings s,string traceFile)
    {
        if(!capture.MotionCompletedNormally||!capture.TrueSinusoidalMotionVerified||
            !capture.DeviceFusionOutputVerified||string.IsNullOrWhiteSpace(capture.Source))
            throw new InvalidDataException("没有被证实的真实正弦运动和真实设备融合倾角输出");
        if(capture.ClockFrequency<=0||!double.IsFinite(capture.AlignmentBoundMs)||
            capture.AlignmentBoundMs<0||capture.AlignmentBoundMs>s.PhaseClockToleranceMs)
            throw new InvalidDataException("设备融合倾角与2TD编码器的时标同步误差超过批准阈值");
        var f=capture.Frames;
        if(f.Count<130)throw new InvalidDataException("原始数据量不足");
        for(int i=0;i<f.Count;i++)
        {
            if(f[i].Ticks<=0||(i>0&&f[i].Ticks<=f[i-1].Ticks))
                throw new InvalidDataException("真实融合角/编码器时间戳不单调");
            var v=f[i];
            if(new[]{v.InnerEncoderDeg,v.OuterEncoderDeg,v.DeviceFusedTiltXDeg,
                 v.DeviceFusedTiltYDeg,v.TemperatureC}.Any(x=>!double.IsFinite(x)))
                throw new InvalidDataException("非有限真实角度或温度");
        }
        for(int i=1;i<f.Count;i++)
            if((int)f[i].Phase<(int)f[i-1].Phase)
                throw new InvalidDataException("动态数据Baseline/Steady/Recovery时序不连续，拒绝插值");
        var baseline=f.Where(v=>v.Phase==Ct25Phase.Baseline).ToArray();
        var steady=f.Where(v=>v.Phase==Ct25Phase.Steady).ToArray();
        var recovery=f.Where(v=>v.Phase==Ct25Phase.Recovery).ToArray();
        if(baseline.Length<10||recovery.Length<10||steady.Length<s.MinimumSteadyFrames)
            throw new InvalidDataException("缺少静止基线/回零数据或稳态有效帧不足");
        static double AxisEncoder(Ct25MeasuredFrame v,Ct25Axis a)=>
            a==Ct25Axis.OuterX?v.OuterEncoderDeg:v.InnerEncoderDeg;
        static double AxisFused(Ct25MeasuredFrame v,Ct25Axis a)=>
            a==Ct25Axis.OuterX?v.DeviceFusedTiltXDeg:v.DeviceFusedTiltYDeg;
        if(baseline.Max(v=>AxisEncoder(v,plan.Axis))-baseline.Min(v=>AxisEncoder(v,plan.Axis))>0.05 ||
           recovery.Max(v=>AxisEncoder(v,plan.Axis))-recovery.Min(v=>AxisEncoder(v,plan.Axis))>0.05)
            throw new InvalidDataException("静态基线或回零窗口中实际2TD仍在明显运动，拒绝将其作为静态零位");
        double t0=steady[0].Ticks;
        var time=steady.Select(v=>(v.Ticks-t0)/capture.ClockFrequency).ToArray();
        double duration=time[^1];
        if(duration<plan.DurationSeconds*0.95||duration>plan.DurationSeconds*1.2)
            throw new InvalidDataException("正弦稳态采集未覆盖计划的全部6个或更多周期");
        for(int i=1;i<time.Length;i++)
            if(time[i]-time[i-1]>s.MaximumGapSeconds)
                throw new InvalidDataException("稳态数据存在过大采样缺口，不能计算相位");
        double maxGap=time.Zip(time.Skip(1),(a,b)=>b-a).Max();
        int sign=plan.Axis==Ct25Axis.OuterX?s.AxisXSign:s.AxisYSign;
        double baseRef=baseline.Average(v=>sign*AxisEncoder(v,plan.Axis));
        double baseDev=baseline.Average(v=>AxisFused(v,plan.Axis));
        var refVals=steady.Select(v=>sign*AxisEncoder(v,plan.Axis)-baseRef).ToArray();
        var fusedVals=steady.Select(v=>AxisFused(v,plan.Axis)-baseDev).ToArray();
        var refFit=Fit(time,refVals,plan.FrequencyHz);
        var fusedFit=Fit(time,fusedVals,plan.FrequencyHz);
        if(refFit.R2<s.EncoderWaveformMinR2||
            Math.Abs(refFit.Amplitude-plan.AmplitudeDeg)>s.AmplitudeToleranceFraction*plan.AmplitudeDeg)
            throw new InvalidDataException($"2TD真实轨迹不符合正弦基线：R²={refFit.R2:F4}，实际幅值={refFit.Amplitude:F4}°");
        if(fusedFit.Amplitude<=1e-10)
            throw new InvalidDataException("设备融合角没有可观测动态响应，无法求增益/相位");
        double phaseDiff=fusedFit.PhaseRadians-refFit.PhaseRadians;
        phaseDiff=Math.Atan2(Math.Sin(phaseDiff),Math.Cos(phaseDiff));
        double gain=fusedFit.Amplitude/refFit.Amplitude;
        double meanErr=refVals.Zip(fusedVals,(r,d)=>d-r).Average();
        double rmse=Math.Sqrt(refVals.Zip(fusedVals,(r,d)=>Math.Pow(d-r,2)).Average());
        double afterZero=recovery.Average(v=>AxisFused(v,plan.Axis))-baseDev;
        double afterRef=recovery.Average(v=>sign*AxisEncoder(v,plan.Axis))-baseRef;
        double finalReturnResidual=afterZero-afterRef;
        var trace=f.Select(v=>new Ct25TraceRow((v.Ticks-t0)/capture.ClockFrequency,v.Phase.ToString(),
            sign*AxisEncoder(v,plan.Axis)-baseRef,AxisFused(v,plan.Axis)-baseDev,
            AxisFused(v,plan.Axis)-baseDev-(sign*AxisEncoder(v,plan.Axis)-baseRef),
            v.InnerEncoderDeg,v.OuterEncoderDeg,v.TemperatureC)).ToArray();
        return(new Ct25Result(plan.Index,plan.Axis.ToString(),plan.AmplitudeDeg,plan.FrequencyHz,
            plan.Repeat,steady.Length,baseline.Length,recovery.Length,
            refFit.Amplitude,refFit.R2,fusedFit.Amplitude,gain,(gain-1)*100,
            phaseDiff*180/Math.PI,-phaseDiff/(TwoPi*plan.FrequencyHz),
            meanErr,rmse,baseDev,afterZero,finalReturnResidual,
            f.Average(v=>v.TemperatureC),maxGap,traceFile,capture.Source,capture.AlignmentBoundMs),trace);
    }
}
