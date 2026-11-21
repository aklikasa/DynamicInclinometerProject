
using System.Globalization;
using Dts.Tests.S1.CT12A;
namespace Dts.Tests.S1.CT20;
public static class Ct20Algorithm
{
    private static readonly CultureInfo Ci=CultureInfo.InvariantCulture;
    public static void Validate(Ct20Settings s,bool confirmations=true)
    {
        if(s.PowerOnUtc==default)throw new InvalidDataException("必须填写人工记录的真实上电时间");
        if(s.PowerOnUtc>DateTimeOffset.UtcNow.AddSeconds(5))throw new InvalidDataException("上电时间不能晚于当前时间");
        if(!double.IsFinite(s.DurationMinutes)||s.DurationMinutes<5||s.DurationMinutes>120)throw new InvalidDataException("单次冷启动采集时长应为5～120分钟");
        if(!double.IsFinite(s.WindowSeconds)||s.WindowSeconds<30||s.WindowSeconds>600)throw new InvalidDataException("统计窗口应为30～600秒");
        if(!double.IsFinite(s.StableWindowSeconds)||s.StableWindowSeconds<60||s.StableWindowSeconds>1800)throw new InvalidDataException("稳定持续窗口应为60～1800秒");
        if(!double.IsFinite(s.BiasToleranceDps)||s.BiasToleranceDps<=0||s.BiasToleranceDps>1)throw new InvalidDataException("零偏均值容差应为(0,1]°/s");
        if(!double.IsFinite(s.DriftToleranceDpsPerMin)||s.DriftToleranceDpsPerMin<=0||s.DriftToleranceDpsPerMin>0.1)throw new InvalidDataException("漂移率容差应为(0,0.1]°/min");
        if(s.MinimumBatches<30||s.MinimumBatches>100000)throw new InvalidDataException("最低有效FIFO批次数应为30～100000");
        if(confirmations&&(!s.StationaryConfirmed||!s.ColdStartConfirmed||!s.TemperatureRecorded))throw new InvalidOperationException("请确认冷启动、转台静止及温度记录条件");
    }
    private static double Mean(IEnumerable<double> x)=>x.Average();
    private static double Std(IEnumerable<double> x){var a=x.ToArray();double m=Mean(a);return Math.Sqrt(a.Sum(v=>(v-m)*(v-m))/Math.Max(1,a.Length-1));}
    private static double Slope(IReadOnlyList<double> t,IReadOnlyList<double> y)
    {double mt=Mean(t),my=Mean(y);double den=t.Sum(v=>(v-mt)*(v-mt));return den<=0?double.NaN:t.Select((v,i)=>(v-mt)*(y[i]-my)).Sum()/den*60.0;}
    public static Ct20Analysis Analyze(IReadOnlyList<Ct12aBatch> batches,Ct20Settings s)
    {
        if(batches.Count<s.MinimumBatches)throw new InvalidDataException($"完整FIFO批次数不足：{batches.Count}/{s.MinimumBatches}");
        var warnings=new List<string>();
        if(batches.Any(b=>b.Frames!=16))warnings.Add("存在非16帧完整FIFO批次");
        if(batches.Any(b=>b.OdrHz!=batches[0].OdrHz))warnings.Add("采集期间ODR发生变化");
        double powerOnUnix=s.PowerOnUtc.ToUnixTimeMilliseconds()/1000.0;
        var t=batches.Select(b=>b.HostUtcSeconds-powerOnUnix).ToArray();
        if(t[0]<-0.005)throw new InvalidDataException("采集批次时间早于人工记录的上电时间；请核对上电时间和电脑时钟");
        double[] periods=t.Zip(t.Skip(1),(a,b)=>b-a).ToArray();
        if(periods.Any(d=>d<=0))throw new InvalidDataException("批次时间戳重复或逆序");
        double[] orderedPeriods=periods.OrderBy(v=>v).ToArray();
        double medianBatchPeriod=orderedPeriods.Length%2==0
            ?(orderedPeriods[orderedPeriods.Length/2-1]+orderedPeriods[orderedPeriods.Length/2])/2
            :orderedPeriods[orderedPeriods.Length/2];
        double duration=(t[^1]-t[0])/60;
        double captureStartDelay=t[0];
        if(captureStartDelay>60)warnings.Add($"上电至首个有效FIFO批次延迟{captureStartDelay:F1}s；稳定时间已按人工上电时刻计时，但启动空档内没有采样数据");
        if(duration<s.DurationMinutes*0.90)warnings.Add("实际记录时长低于计划时长的90%");
        double[] gx=batches.Select(b=>b.GxDps).ToArray(),gy=batches.Select(b=>b.GyDps).ToArray(),gz=batches.Select(b=>b.GzDps).ToArray();
        double[] temp=batches.Select(b=>b.TemperatureC).ToArray();
        double[] allMean=[Mean(gx),Mean(gy),Mean(gz)],allStd=[Std(gx),Std(gy),Std(gz)];
        double[] allPp=[gx.Max()-gx.Min(),gy.Max()-gy.Min(),gz.Max()-gz.Min()];
        var rows=new List<Ct20WindowRow>();
        double step=s.WindowSeconds;
        for(double start=0;start+step<=t[^1]+1e-9;start+=step)
        {
            int[] ix=Enumerable.Range(0,t.Length).Where(i=>t[i]>=start&&t[i]<start+step).ToArray();
            if(ix.Length<5)continue;
            // Only accept fully observed windows. The initial power-on-to-capture gap must
            // not be silently treated as stable or as a complete first statistical window.
            double edgeTolerance=2*medianBatchPeriod;
            if(t[ix[0]]>start+edgeTolerance || t[ix[^1]]<start+step-edgeTolerance)continue;
            double[] x=ix.Select(i=>gx[i]).ToArray(),y=ix.Select(i=>gy[i]).ToArray(),z=ix.Select(i=>gz[i]).ToArray();
            double[] tt=ix.Select(i=>temp[i]).ToArray(),tm=ix.Select(i=>t[i]).ToArray();
            double mx=Mean(x),my=Mean(y),mz=Mean(z),sx=Std(x),sy=Std(y),sz=Std(z);
            double dx=Slope(tm,x),dy=Slope(tm,y),dz=Slope(tm,z);
            bool stable=Math.Abs(mx)<=s.BiasToleranceDps&&Math.Abs(my)<=s.BiasToleranceDps&&Math.Abs(mz)<=s.BiasToleranceDps&&
                Math.Abs(dx)<=s.DriftToleranceDpsPerMin&&Math.Abs(dy)<=s.DriftToleranceDpsPerMin&&Math.Abs(dz)<=s.DriftToleranceDpsPerMin;
            rows.Add(new Ct20WindowRow(start/60,(start+step)/60,ix.Length,mx,my,mz,sx,sy,sz,Mean(tt),tt.Min(),tt.Max(),dx,dy,dz,stable,stable?"满足本窗口判据":"未满足本窗口判据"));
        }
        double? stableStart=null,stableDuration=null;
        if(rows.Count>0)
        {
            int needed=(int)Math.Ceiling(s.StableWindowSeconds/s.WindowSeconds);
            for(int i=0;i+needed<=rows.Count;i++)
            {
                var group=rows.Skip(i).Take(needed).ToArray();
                bool contiguous=group.Zip(group.Skip(1),(a,b)=>Math.Abs(a.EndMinute-b.StartMinute)<1e-6).All(v=>v);
                if(contiguous&&group.All(r=>r.Stable)){stableStart=group[0].StartMinute;stableDuration=needed*step/60;break;}
            }
        }
        if(rows.Count==0)warnings.Add("未形成完整统计窗口");
        if(stableStart is null)warnings.Add("本次记录期间未达到连续稳定判据");
        return new Ct20Analysis(batches.Count,(long)batches.Count*16,duration,captureStartDelay,temp.Min(),temp.Max(),temp.Max()-temp.Min(),
            allMean,allStd,allPp,rows,stableStart,stableDuration,
            $"连续{ s.StableWindowSeconds:F0}s内，按{step:F0}s不重叠窗口检查：XYZ零偏均值绝对值≤{s.BiasToleranceDps:G4}°/s，且各轴线性漂移率绝对值≤{s.DriftToleranceDpsPerMin:G4}°/min。",
            warnings.Count==0&&stableStart is not null?"满足本次工程稳定判据（非产品验收）":"未满足或数据质量/时长不足；不得宣称稳定时间已确定",warnings);
    }
}
