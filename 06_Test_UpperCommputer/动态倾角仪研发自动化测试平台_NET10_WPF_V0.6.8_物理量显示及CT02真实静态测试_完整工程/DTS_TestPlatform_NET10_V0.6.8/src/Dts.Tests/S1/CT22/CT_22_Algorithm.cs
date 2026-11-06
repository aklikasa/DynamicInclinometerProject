using System.IO;
using System.Globalization;

namespace Dts.Tests.S1.CT22;

/// <summary>
/// Authenticated 16-frame FIFO batch means integrated across real MCU batch deltas.
/// The firmware does NOT provide independently timed frames; results are ENGINEERING proxies.
/// </summary>
public static class Ct22Algorithm
{
    private static readonly CultureInfo Ci=CultureInfo.InvariantCulture;

    public static void Validate(Ct22Settings s, bool confirmations=true)
    {
        if(!double.IsFinite(s.DurationMinutes)||s.DurationMinutes<2||s.DurationMinutes>120)
            throw new InvalidDataException("连续采集时长应为2～120分钟（推荐31分钟覆盖10/30分钟检查点）");
        if(s.MinimumBatches is <100 or >100000)
            throw new InvalidDataException("最少完整FIFO批次数应为100～100000");
        if(!double.IsFinite(s.MaxHostJitterPercent)||s.MaxHostJitterPercent<2||s.MaxHostJitterPercent>50||
           !double.IsFinite(s.MaxMcuJitterPercent)||s.MaxMcuJitterPercent<2||s.MaxMcuJitterPercent>50||
           !double.IsFinite(s.MaxFifoSpanErrorPercent)||s.MaxFifoSpanErrorPercent<2||s.MaxFifoSpanErrorPercent>50)
            throw new InvalidDataException("周期/帧跨度P95容差应为2%～50%");
        if(!double.IsFinite(s.MaxHostMcuSpanMismatchPercent)||
           s.MaxHostMcuSpanMismatchPercent<0.1||s.MaxHostMcuSpanMismatchPercent>20)
            throw new InvalidDataException("主机与MCU总时长差容差应为0.1%～20%");
        if(!double.IsFinite(s.MaxTemperatureRangeC)||s.MaxTemperatureRangeC<0.05||s.MaxTemperatureRangeC>50||
           !double.IsFinite(s.MaxAccDirectionChangeDeg)||s.MaxAccDirectionChangeDeg<0.01||s.MaxAccDirectionChangeDeg>20)
            throw new InvalidDataException("温度变化和ACC静止检查容差无效");
        if(!double.IsFinite(s.PlotIntervalSeconds)||s.PlotIntervalSeconds<0.2||s.PlotIntervalSeconds>60)
            throw new InvalidDataException("报告绘图采样间隔应为0.2～60秒");
        if(confirmations && (!s.StationaryConfirmed||!s.ThermalEnvironmentConfirmed||!s.TimebaseLimitAccepted))
            throw new InvalidOperationException("请确认全程静止、温度环境及FIFO批次时标限制");
    }
    private static double Parse(string value,string col)
    {
        if(!double.TryParse(value,NumberStyles.Float,Ci,out var number)||!double.IsFinite(number))
            throw new InvalidDataException("CSV存在无效物理量："+col);
        return number;
    }
    private static int ParseInt(string v,string col)
    {
        if(!int.TryParse(v,NumberStyles.Integer,Ci,out int num))
            throw new InvalidDataException("CSV存在无效计数："+col);
        return num;
    }
    private static int Col(string[] header,string name)
    {
        int n=Array.IndexOf(header,name);
        if(n<0)throw new InvalidDataException("真实数据CSV缺少字段："+name);
        return n;
    }
    private static double Median(IEnumerable<double> input)
    {
        var values=input.OrderBy(x=>x).ToArray();
        if(values.Length==0)throw new InvalidDataException("无法估计空序列的批次周期");
        return values.Length%2==0 ? (values[values.Length/2-1]+values[values.Length/2])/2:
            values[values.Length/2];
    }
    private static double P95(IEnumerable<double> input)
    {
        var values=input.OrderBy(x=>x).ToArray();
        return values.Length==0?double.NaN:values[(int)Math.Floor((values.Length-1)*0.95)];
    }

    public static async Task<IReadOnlyList<Ct22Batch>> ReadRealBatchMeansAsync(
        string selectedCsv,string rawCsv,CancellationToken ct)
    {
        using var selected=new StreamReader(selectedCsv);
        using var raw=new StreamReader(rawCsv);
        var sh=(await selected.ReadLineAsync(ct)??throw new InvalidDataException("选定CSV为空"))
            .TrimStart('\uFEFF').Split(',');
        var rh=(await raw.ReadLineAsync(ct)??throw new InvalidDataException("原始CSV为空"))
            .TrimStart('\uFEFF').Split(',');
        int shost=Col(sh,"host_utc"),stick=Col(sh,"mcu_tick_ms"),sindex=Col(sh,"sample_index"),
            sgx=Col(sh,"gx"),sgy=Col(sh,"gy"),sgz=Col(sh,"gz"),
            sax=Col(sh,"ax"),say=Col(sh,"ay"),saz=Col(sh,"az"),
            stemp=Col(sh,"temp_c"),smode=Col(sh,"mode"),sunit=Col(sh,"gyro_unit"),
            sstatus=Col(sh,"source_status");
        int rhost=Col(rh,"host_utc"),rtick=Col(rh,"mcu_tick_ms"),rindex=Col(rh,"sample_index"),
            rodr=Col(rh,"odr_hz"),rflags=Col(rh,"fifo_flags"),
            rgx=Col(rh,"cal_gx_dps"),rgy=Col(rh,"cal_gy_dps"),rgz=Col(rh,"cal_gz_dps"),
            rax=Col(rh,"cal_ax_g"),ray=Col(rh,"cal_ay_g"),raz=Col(rh,"cal_az_g"),
            rtemp=Col(rh,"temp_c");
        var batches=new List<Ct22Batch>();
        long count=0;int batchFrames=0,odr=0;uint currentTick=0;
        double sumX=0,sumY=0,sumZ=0,sumT=0,host=0;
        double sumAx=0,sumAy=0,sumAz=0;
        void Flush()
        {
            if(batchFrames==0)return;
            if(batchFrames!=16)
                throw new InvalidDataException($"FIFO批次不完整：{batchFrames}帧，要求完整16帧；禁止拼接缺帧数据");
            batches.Add(new Ct22Batch(host,currentTick,odr,batchFrames,
                sumX/batchFrames,sumY/batchFrames,sumZ/batchFrames,sumT/batchFrames,
                sumAx/batchFrames,sumAy/batchFrames,sumAz/batchFrames));
            batchFrames=0;sumX=sumY=sumZ=sumT=sumAx=sumAy=sumAz=0;
        }
        while(true)
        {
            ct.ThrowIfCancellationRequested();
            string? sl=await selected.ReadLineAsync(ct);
            string? rl=await raw.ReadLineAsync(ct);
            if(sl is null&&rl is null)break;
            if(sl is null||rl is null)throw new InvalidDataException("原始CSV与选定CSV帧数不一致");
            if(string.IsNullOrWhiteSpace(sl)||string.IsNullOrWhiteSpace(rl))
                throw new InvalidDataException("采集CSV存在空行，拒绝错误的帧顺序");
            var sv=sl.Split(',');var rv=rl.Split(',');
            if(sv.Length!=sh.Length||rv.Length!=rh.Length)
                throw new InvalidDataException("原始/选定CSV列数异常");
            if(sv[smode]!="AMBIENT"||sv[sunit]!="deg/s"||
               !sv[sstatus].Contains("CALIBRATED",StringComparison.Ordinal))
                throw new InvalidDataException("非常温校正Gyro数据，禁止计算CT-22积分漂移");
            uint tick=uint.Parse(sv[stick],Ci);
            if(tick!=uint.Parse(rv[rtick],Ci)||sv[shost]!=rv[rhost]||sv[sindex]!=rv[rindex])
                throw new InvalidDataException("原始与校正CSV对应不上同一真实FIFO帧");
            int index=ParseInt(sv[sindex],"sample_index");
            int rawOdr=ParseInt(rv[rodr],"odr_hz");
            int flags=ParseInt(rv[rflags],"fifo_flags");
            if((flags&0x0003)!=0x0001)
                throw new InvalidDataException("SENSOR_OK未确认或FIFO模拟标志置位，拒绝CT-22积分漂移");
            if(rawOdr<1||rawOdr>10000)
                throw new InvalidDataException("MCU未提供合法ODR，禁止宣称有可靠采样间隔");
            if(batchFrames==0)
            {
                currentTick=tick;odr=rawOdr;
                if(!DateTimeOffset.TryParse(sv[shost],Ci,DateTimeStyles.None,out var stamp))
                    throw new InvalidDataException("主机批次UTC无效");
                host=stamp.ToUnixTimeMilliseconds()/1000.0;
            }
            else if(tick!=currentTick)
            {
                Flush();currentTick=tick;odr=rawOdr;
                if(!DateTimeOffset.TryParse(sv[shost],Ci,DateTimeStyles.None,out var stamp))
                    throw new InvalidDataException("主机批次UTC无效");
                host=stamp.ToUnixTimeMilliseconds()/1000.0;
            }
            if(index!=batchFrames||rawOdr!=odr||tick!=currentTick)
                throw new InvalidDataException("FIFO批次frame_index不连续或ODR跨帧改变");
            batchFrames++;count++;
            // Use full-precision raw-CSV calibrated columns (G17), not six-decimal UI rows.
            // Selected and raw must still correspond to the same physical sample.
            double[] corrected=[Parse(rv[rax],"cal_ax_g"),Parse(rv[ray],"cal_ay_g"),
                Parse(rv[raz],"cal_az_g"),Parse(rv[rgx],"cal_gx_dps"),
                Parse(rv[rgy],"cal_gy_dps"),Parse(rv[rgz],"cal_gz_dps")];
            int[] displayedColumns=[sax,say,saz,sgx,sgy,sgz];
            for(int j=0;j<6;j++)
            {
                double displayed=Parse(sv[displayedColumns[j]],"selected physical value");
                if(Math.Abs(displayed-corrected[j])>1.1e-6)
                    throw new InvalidDataException("真实原始/显示补偿值不一致，拒绝混合不同来源的帧");
            }
            double preciseTemp=Parse(rv[rtemp],"raw temp_c");
            if(Math.Abs(preciseTemp-Parse(sv[stemp],"selected temp_c"))>0.011)
                throw new InvalidDataException("真实原始/显示温度不一致");
            sumAx+=corrected[0];sumAy+=corrected[1];sumAz+=corrected[2];
            sumX+=corrected[3];sumY+=corrected[4];sumZ+=corrected[5];
            sumT+=preciseTemp;
            if(count>50_000_000)
                throw new InvalidDataException("记录超过安全上限5000万帧，请拆分测试");
        }
        Flush();
        if(batches.Count<2)throw new InvalidDataException("真实FIFO批次不足");
        return batches;
    }

    private static double VectorNorm(double a,double b,double c)=>Math.Sqrt(a*a+b*b+c*c);
    private static double AngleDeg(Ct22Batch original,Ct22Batch current)
    {
        double a=VectorNorm(original.AxG,original.AyG,original.AzG);
        double b=VectorNorm(current.AxG,current.AyG,current.AzG);
        if(a<0.7||a>1.3||b<0.7||b>1.3)
            throw new InvalidDataException("静态ACC模长异常，无法核验台面静止参考方向");
        double d=(original.AxG*current.AxG+original.AyG*current.AyG+
            original.AzG*current.AzG)/(a*b);
        return Math.Acos(Math.Clamp(d,-1,1))*180/Math.PI;
    }
    private static double FitSlopePerMinute(IReadOnlyList<Ct22DriftPoint> points,int axis)
    {
        double x0=points.Average(p=>p.ElapsedSeconds/60.0);
        double y0=points.Average(p=>axis switch{0=>p.GxDeg,1=>p.GyDeg,_=>p.GzDeg});
        double cov=0,var=0;
        foreach(var p in points)
        {
            double t=p.ElapsedSeconds/60.0-x0;
            double y=(axis switch{0=>p.GxDeg,1=>p.GyDeg,_=>p.GzDeg})-y0;
            cov+=t*y;var+=t*t;
        }
        return var<1e-16?double.NaN:cov/var;
    }
    public static Ct22Analysis Analyze(IReadOnlyList<Ct22Batch> batches,Ct22Settings s,
        int manifestSamples,int unchangedPolls,int sensorUnverified)
    {
        if(batches.Count<2)throw new InvalidDataException("真实FIFO批次数不足，无法积分");
        var warnings=new List<string>();var n=batches.Count;
        if(batches.Any(b=>b.OdrHz!=batches[0].OdrHz))
            warnings.Add("记录过程中报告的ODR发生变化");
        if(batches.Any(b=>b.Frames!=16))warnings.Add("存在不完整的FIFO批次");
        if(manifestSamples!=n*16)warnings.Add("manifest帧数与原始CSV不一致");
        if(sensorUnverified!=0)warnings.Add("存在未确认SENSOR_OK的批次");
        if(n<s.MinimumBatches)warnings.Add("批次数少于可配置的最小值");
        double expected=16.0/batches[0].OdrHz;
        var host=new double[n-1];var mcu=new double[n-1];int gaps=0;
        for(int i=1;i<n;i++)
        {
            host[i-1]=batches[i].HostUtcSeconds-batches[i-1].HostUtcSeconds;
            mcu[i-1]=unchecked(batches[i].McuTickMs-batches[i-1].McuTickMs)/1000.0;
            if(!double.IsFinite(host[i-1])||host[i-1]<=0||!double.IsFinite(mcu[i-1])||
                mcu[i-1]<=0||mcu[i-1]>3600)
                throw new InvalidDataException("MCU或主机时间发生倒退、重复或无效跳变");
            if(Math.Abs(mcu[i-1]-expected)/expected*100>s.MaxFifoSpanErrorPercent)gaps++;
        }
        double medHost=Median(host),medMcu=Median(mcu);
        double hostP95=P95(host.Select(x=>Math.Abs(x-medHost)/medHost*100));
        double mcuP95=P95(mcu.Select(x=>Math.Abs(x-medMcu)/medMcu*100));
        double spanP95=P95(mcu.Select(x=>Math.Abs(x-expected)/expected*100));
        double totalMcu=mcu.Sum();
        double totalHost=batches[^1].HostUtcSeconds-batches[0].HostUtcSeconds;
        double clockMismatch=Math.Abs(totalHost-totalMcu)/totalMcu*100;
        if(hostP95>s.MaxHostJitterPercent)
            warnings.Add($"主机接收周期P95抖动 {hostP95:F2}% 超标");
        if(mcuP95>s.MaxMcuJitterPercent)
            warnings.Add($"MCU批次周期P95抖动 {mcuP95:F2}% 超标");
        if(gaps>0)warnings.Add($"共有{gaps}处FIFO批次间隔不符合16帧/ODR；拒绝跨断点积分");
        if(spanP95>s.MaxFifoSpanErrorPercent)
            warnings.Add($"MCU批次间隔偏离理论16/ODR的P95={spanP95:F2}%");
        if(clockMismatch>s.MaxHostMcuSpanMismatchPercent)
            warnings.Add($"主机/MCU总时长差 {clockMismatch:F3}% 超标");
        double tempMin=batches.Min(b=>b.TemperatureC),tempMax=batches.Max(b=>b.TemperatureC);
        if(tempMax-tempMin>s.MaxTemperatureRangeC)
            warnings.Add($"记录期间温度变化 {tempMax-tempMin:F3}°C 超标");
        double maxAccAngle=0;
        for(int i=0;i<n;i++)
            maxAccAngle=Math.Max(maxAccAngle,AngleDeg(batches[0],batches[i]));
        if(maxAccAngle>s.MaxAccDirectionChangeDeg)
            warnings.Add($"静止ACC重力方向最大变化 {maxAccAngle:F4}° 超标，可能存在外界运动/振动");
        bool qualified=warnings.Count==0;
        var quality=new Ct22TimeQuality(qualified?
            "ENGINEERING_MCU_BATCH_DELTA_NO_FRAME_TIMESTAMPS":"TIMEBASE_OR_STATIONARITY_UNQUALIFIED",
            qualified,n,(long)n*16,unchangedPolls,gaps,batches[0].OdrHz,totalMcu,
            totalHost,medMcu,hostP95,mcuP95,spanP95,clockMismatch,
            tempMin,tempMax,maxAccAngle,warnings);
        string method="仅用真实FIFO的16帧批均值；以相邻MCU批次tick之差为实际Δt，"+
            "用梯形法在批次时间网格累计Gyro X/Y/Z角度(°)，不融合ACC、不对本次测试求均值去偏置。"+
            "10/30分钟指标仅在实际MCU记录覆盖600/1800秒时插值计算；每分钟漂移斜率按累计角-时间最小二乘。"+
            "没有逐帧硬件时标或MCU-转台绝对同步证明，仅为工程诊断积分；"+
            "若FIFO断点、ODR、温度或静止校验失败，不拼接、不填充、不发布积分指标。";
        if(!qualified)
            return new Ct22Analysis(quality,[],[],null,null,0,false,method);
        var curve=new List<Ct22DriftPoint>();
        double t=0,lastPlotTime=0;
        double[] angle=[0,0,0];double[] maxAbs=[0,0,0];
        double[]? angle10=null,angle30=null;
        var first=batches[0];
        curve.Add(new Ct22DriftPoint(0,0,0,0,first.GxDps,first.GyDps,
            first.GzDps,first.TemperatureC,0));
        for(int i=1;i<n;i++)
        {
            var prev=batches[i-1];var now=batches[i];double dt=mcu[i-1];
            double previousTime=t;double[] before=(double[])angle.Clone();t+=dt;
            double[] p=[prev.GxDps,prev.GyDps,prev.GzDps];
            double[] r=[now.GxDps,now.GyDps,now.GzDps];
            for(int j=0;j<3;j++)
            {
                angle[j]+=0.5*(p[j]+r[j])*dt;
                maxAbs[j]=Math.Max(maxAbs[j],Math.Abs(angle[j]));
            }
            if(angle10 is null&&previousTime<=600&&t>=600)
                angle10=Enumerable.Range(0,3).Select(j=>before[j]+(angle[j]-before[j])*(600-previousTime)/dt).ToArray();
            if(angle30 is null&&previousTime<=1800&&t>=1800)
                angle30=Enumerable.Range(0,3).Select(j=>before[j]+(angle[j]-before[j])*(1800-previousTime)/dt).ToArray();
            if(t-lastPlotTime>=s.PlotIntervalSeconds||i==n-1)
            {
                curve.Add(new Ct22DriftPoint(t,angle[0],angle[1],angle[2],r[0],r[1],r[2],
                    now.TemperatureC,AngleDeg(first,now)));
                lastPlotTime=t;
            }
        }
        var axes=new List<Ct22AxisMetric>(3);
        for(int j=0;j<3;j++)
        {
            double meanRate=angle[j]/t;
            axes.Add(new Ct22AxisMetric("Gyro-"+"XYZ"[j],meanRate,angle[j],maxAbs[j],
                FitSlopePerMinute(curve,j),angle10?[j],angle30?[j]));
        }
        static double? Magnitude(double[]? values)=>values is null?null:
            Math.Sqrt(values.Sum(v=>v*v));
        return new Ct22Analysis(quality,axes,curve,Magnitude(angle10),Magnitude(angle30),
            Math.Sqrt(angle.Sum(v=>v*v)),true,method);
    }

}
