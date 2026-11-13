using System.IO;
using System.Globalization;

namespace Dts.Tests.S1.CT12A;

/// <summary>
/// Allan deviation on one uniformly spaced SERIES OF 16-FRAME BATCH MEANS.
/// Strictly NOT single-frame timestamp Allan deviation: the firmware supplies no frame timestamps.
/// No interpolation or stitching across detected lost/repeated FIFO windows is permitted.
/// </summary>
public static class Ct12aAlgorithm
{
    private static readonly CultureInfo Ci=CultureInfo.InvariantCulture;
    public static void Validate(Ct12aSettings s,bool confirmations=true)
    {
        if(!double.IsFinite(s.DurationMinutes)||s.DurationMinutes<2||s.DurationMinutes>1440)
            throw new InvalidDataException("采集时长必须在2～1440分钟（最长24小时）");
        if(!double.IsFinite(s.TauMinSeconds)||s.TauMinSeconds<0.05||s.TauMinSeconds>3600||
           !double.IsFinite(s.TauMaxSeconds)||s.TauMaxSeconds<=s.TauMinSeconds||s.TauMaxSeconds>7200)
            throw new InvalidDataException("Allan τ 区间不合理：0.05≤τ_min<τ_max≤7200秒");
        if(s.PointsPerDecade is <3 or >12)
            throw new InvalidDataException("对数曲线每十倍程3～12个采样点");
        if(!double.IsFinite(s.MaxHostCadenceJitterPercent)||s.MaxHostCadenceJitterPercent<2||
           s.MaxHostCadenceJitterPercent>50||
           !double.IsFinite(s.MaxMcuCadenceJitterPercent)||s.MaxMcuCadenceJitterPercent<2||
           s.MaxMcuCadenceJitterPercent>50||
           !double.IsFinite(s.MaxFifoSpanErrorPercent)||s.MaxFifoSpanErrorPercent<2||
           s.MaxFifoSpanErrorPercent>50)
            throw new InvalidDataException("时标质量容差应为2%～50%，不代表额外硬件保证");
        if(!double.IsFinite(s.MaxTemperatureRangeC)||s.MaxTemperatureRangeC<0.05||
           s.MaxTemperatureRangeC>50)
            throw new InvalidDataException("允许温度变化范围在0.05～50°C之间");
        if(s.MinimumBatches is <100 or >100000)
            throw new InvalidDataException("最低有效批数在100～100000之间");
        if(confirmations&&(!s.StationaryConfirmed||!s.ThermalEnvironmentConfirmed||
            !s.TimebaseLimitAccepted))
            throw new InvalidOperationException("请先确认静止环境、温度记录与批次级时标局限");
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

    public static async Task<IReadOnlyList<Ct12aBatch>> ReadRealBatchMeansAsync(
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
        var batches=new List<Ct12aBatch>();
        long count=0;int batchFrames=0,odr=0;uint currentTick=0;
        double sumX=0,sumY=0,sumZ=0,sumT=0,host=0;
        double sumAx=0,sumAy=0,sumAz=0;
        bool batchSensorOk=true;
        void Flush()
        {
            if(batchFrames==0)return;
            if(batchFrames!=16)
                throw new InvalidDataException($"FIFO批次不完整：{batchFrames}帧，要求完整16帧；禁止拼接缺帧数据");
            batches.Add(new Ct12aBatch(host,currentTick,odr,batchFrames,
                sumX/batchFrames,sumY/batchFrames,sumZ/batchFrames,sumT/batchFrames,
                sumAx/batchFrames,sumAy/batchFrames,sumAz/batchFrames,batchSensorOk));
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
                throw new InvalidDataException("非常温校正Gyro数据，禁止计算Allan");
            uint tick=uint.Parse(sv[stick],Ci);
            if(tick!=uint.Parse(rv[rtick],Ci)||sv[shost]!=rv[rhost]||sv[sindex]!=rv[rindex])
                throw new InvalidDataException("原始与校正CSV对应不上同一真实FIFO帧");
            int index=ParseInt(sv[sindex],"sample_index");
            int rawOdr=ParseInt(rv[rodr],"odr_hz");
            int flags=ParseInt(rv[rflags],"fifo_flags");
            // Simulator means counterfeit physical provenance: always reject.
            // SENSOR_OK=0 is an UNVERIFIED hardware state, not evidence of simulation.
            // It may still support explicitly marked, non-certifiable diagnostic curves.
            if((flags&0x0002)!=0)
                throw new InvalidDataException("FIFO的SIM_MODE模拟标志已置位，拒绝Allan");
            bool sensorOk=(flags&0x0001)!=0;
            if(rawOdr<1||rawOdr>10000)
                throw new InvalidDataException("MCU未提供合法ODR，禁止宣称有可靠采样间隔");
            if(batchFrames==0)
            {
                currentTick=tick;odr=rawOdr;batchSensorOk=sensorOk;
                if(!DateTimeOffset.TryParse(sv[shost],Ci,DateTimeStyles.None,out var stamp))
                    throw new InvalidDataException("主机批次UTC无效");
                host=stamp.ToUnixTimeMilliseconds()/1000.0;
            }
            else if(tick!=currentTick)
            {
                Flush();currentTick=tick;odr=rawOdr;batchSensorOk=sensorOk;
                if(!DateTimeOffset.TryParse(sv[shost],Ci,DateTimeStyles.None,out var stamp))
                    throw new InvalidDataException("主机批次UTC无效");
                host=stamp.ToUnixTimeMilliseconds()/1000.0;
            }
            if(batchFrames>0 && sensorOk!=batchSensorOk)
                throw new InvalidDataException("同一个FIFO批次内SENSOR_OK标志发生变化，拒绝拼接");
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

    public static Ct12aAnalysis Analyze(IReadOnlyList<Ct12aBatch> batches,
        Ct12aSettings settings,int manifestSamples,int skippedDuplicates,int sensorUnverified)
    {
        if(batches.Count<2)throw new InvalidDataException("Allan批次不足");
        var warnings=new List<string>();
        int n=batches.Count;
        if(batches.Any(b=>b.OdrHz!=batches[0].OdrHz))warnings.Add("MCU报告的ODR在测试期间改变");
        if(batches.Any(b=>b.Frames!=16))warnings.Add("部分批次帧数不是16");
        if(manifestSamples!=n*16)warnings.Add("采集manifest帧数与原始CSV不符");
        int actualUnverified=batches.Count(b=>!b.SensorOk);
        if(sensorUnverified!=actualUnverified)
            warnings.Add($"清单SENSOR_OK未确认批次={sensorUnverified}，而CSV={actualUnverified}，两者不一致");
        // Record provenance separately; it must never be promoted to certified measurements.
        var provenanceWarnings=new List<string>();
        if(actualUnverified>0)
            provenanceWarnings.Add($"{actualUnverified}个FIFO批次未确认SENSOR_OK；仅允许未核实来源的研发诊断图，不发布正式噪声指标");
        var hostPeriods=new double[n-1];var mcuPeriods=new double[n-1];
        double expectedSpan=16.0/batches[0].OdrHz;
        int gaps=0;
        for(int i=1;i<n;i++)
        {
            hostPeriods[i-1]=batches[i].HostUtcSeconds-batches[i-1].HostUtcSeconds;
            mcuPeriods[i-1]=unchecked(batches[i].McuTickMs-batches[i-1].McuTickMs)/1000.0;
            if(hostPeriods[i-1]<=0||mcuPeriods[i-1]<=0)
                throw new InvalidDataException("发现重复或逆序的批次时间戳，无法计算Allan序列");
            if(Math.Abs(mcuPeriods[i-1]-expectedSpan)/expectedSpan*100>
                settings.MaxFifoSpanErrorPercent)gaps++;
        }
        double host=Median(hostPeriods),mcu=Median(mcuPeriods);
        double hostP95=P95(hostPeriods.Select(v=>Math.Abs(v-host)/host*100));
        double mcuP95=P95(mcuPeriods.Select(v=>Math.Abs(v-mcu)/mcu*100));
        double spanP95=P95(mcuPeriods.Select(v=>Math.Abs(v-expectedSpan)/expectedSpan*100));
        if(hostP95>settings.MaxHostCadenceJitterPercent)
            warnings.Add($"主机接收周期P95抖动{hostP95:F1}%大于设置阈值");
        if(mcuP95>settings.MaxMcuCadenceJitterPercent)
            warnings.Add($"MCU批次时差P95抖动{mcuP95:F1}%大于设置阈值");
        if(gaps!=0)warnings.Add($"{gaps}处MCU时差与16帧/ODR不符：可能丢帧、重叠或采样时标定义不同");
        if(spanP95>settings.MaxFifoSpanErrorPercent)
            warnings.Add($"批次时间跨度与ODR预期偏差P95={spanP95:F1}%");
        if(n<settings.MinimumBatches)warnings.Add("有效完整批次数未达到最低要求");
        double tempMin=batches.Min(b=>b.TemperatureC),tempMax=batches.Max(b=>b.TemperatureC);
        if(tempMax-tempMin>settings.MaxTemperatureRangeC)
            warnings.Add($"实测温度变化{tempMax-tempMin:F2}°C超过设定的{settings.MaxTemperatureRangeC:F2}°C");
        // A polling request that returns an unchanged FIFO is not a lost data batch;
        // it is metadata, not grounds to reject an otherwise continuous sample record.
        // Timing is batch-reception based. This cannot become hardware-grade traceable Allan by parameter choice.
        double effectivePeriod=mcu;
        // Only timebase/continuity/manifest consistency failures block mathematical curves.
        // Unconfirmed SENSOR_OK is a provenance qualifier, not a FIFO gap.
        bool contiguous=warnings.Count==0 && n>=settings.MinimumBatches;
        bool sourceVerified=actualUnverified==0;
        var allWarnings=new List<string>(warnings);
        allWarnings.AddRange(provenanceWarnings);
        double duration=batches[^1].HostUtcSeconds-batches[0].HostUtcSeconds;
        var quality=new Ct12aTimeQuality(
            !contiguous?"TIMEBASE_OR_CONTINUITY_UNQUALIFIED":
                sourceVerified?"ENGINEERING_HOST_BATCH_UNVERIFIED_FRAME_TIME":"ENGINEERING_SENSOR_STATUS_UNVERIFIED",
            !contiguous?"未满足FIFO连续性/时间质量条件；不发布可信Allan系数":
                sourceVerified?"真实16帧批次满足时标门槛，但仍无逐帧硬件时间戳":
                    "时间连续性满足工程门槛，但SENSOR_OK状态未核实；只生成诊断曲线，不发布噪声系数",
            n,(long)n*16,skippedDuplicates,gaps,host,mcu,hostP95,mcuP95,spanP95,
            duration,batches[0].OdrHz,contiguous,allWarnings,actualUnverified);

        var curves=new List<Ct12aCurvePoint>();
        // For non-contiguous captures, DO NOT concatenate broken windows into Allan curve.
        if(contiguous)
        {
            double maxTau=Math.Min(settings.TauMaxSeconds,duration/12.0);
            double minTau=Math.Max(settings.TauMinSeconds,effectivePeriod);
            var windows=new SortedSet<int>();
            for(double tau=minTau;tau<=maxTau*(1+1e-9);tau*=Math.Pow(10,1.0/settings.PointsPerDecade))
            {
                int m=(int)Math.Round(tau/effectivePeriod);
                if(m>=1 && m*12<=n)windows.Add(m);
                if(windows.Count>160)break;
            }
            var gx=batches.Select(b=>b.GxDps).ToArray();
            var gy=batches.Select(b=>b.GyDps).ToArray();
            var gz=batches.Select(b=>b.GzDps).ToArray();
            var ax=batches.Select(b=>b.AxG).ToArray();
            var ay=batches.Select(b=>b.AyG).ToArray();
            var az=batches.Select(b=>b.AzG).ToArray();
            foreach(int m in windows)
            {
                int differences=n-2*m+1;
                if(differences<2)continue;
                curves.Add(new Ct12aCurvePoint(m*effectivePeriod,m,differences,
                    Allan(gx,m),Allan(gy,m),Allan(gz,m),
                    Allan(ax,m),Allan(ay,m),Allan(az,m)));
            }
            if(curves.Count<4)allWarnings.Add("合格τ点不足4个，无法提取噪声参数");
        }
        var axisList=new List<Ct12aAxisSummary>();
        double[][] values=[batches.Select(b=>b.GxDps).ToArray(),
            batches.Select(b=>b.GyDps).ToArray(),batches.Select(b=>b.GzDps).ToArray(),
            batches.Select(b=>b.AxG).ToArray(),batches.Select(b=>b.AyG).ToArray(),
            batches.Select(b=>b.AzG).ToArray()];
        bool released=contiguous && sourceVerified && curves.Count>=4;
        for(int axis=0;axis<6;axis++)
        {
            bool acceleration=axis>=3;
            var arr=values[axis];double mean=arr.Average();
            double std=Math.Sqrt(arr.Sum(v=>(v-mean)*(v-mean))/Math.Max(1,arr.Length-1));
            var points=curves.Select(p=>(tau:p.TauSeconds,sigma:axis switch
            {
                0=>p.GxAllanDeviationDps,1=>p.GyAllanDeviationDps,2=>p.GzAllanDeviationDps,
                3=>p.AxAllanDeviationG,4=>p.AyAllanDeviationG,_=>p.AzAllanDeviationG
            })).ToArray();
            var min=points.Length>0?points.MinBy(p=>p.sigma):(tau:double.NaN,sigma:double.NaN);
            // ARW in deg/sqrt(h); VRW in (m/s)/sqrt(h). Both require near -1/2 slope.
            double? white=null;
            for(int i=0;i+1<Math.Min(points.Length,8);i++)
            {
                var a=points[i];var b=points[i+1];
                if(a.sigma<=0||b.sigma<=0)continue;
                double slope=Math.Log(b.sigma/a.sigma)/Math.Log(b.tau/a.tau);
                if(slope>=-0.70&&slope<=-0.30)
                {
                    double unit=acceleration?9.80665:1;
                    white=0.5*(a.sigma*60*Math.Sqrt(a.tau)+b.sigma*60*Math.Sqrt(b.tau))*unit;
                    break;
                }
            }
            // Flicker plateau proxy is omitted if the Allan log-slope does not flatten.
            double? bias=null;
            for(int i=1;i+1<points.Length;i++)
            {
                var a=points[i-1];var b=points[i+1];var mid=points[i];
                if(a.sigma<=0||b.sigma<=0||mid.sigma<=0)continue;
                double slope=Math.Log(b.sigma/a.sigma)/Math.Log(b.tau/a.tau);
                if(Math.Abs(slope)<0.15 && mid.tau>=2*effectivePeriod)
                {
                    bias=mid.sigma/0.664*(acceleration?1000:3600);
                    break;
                }
            }
            string name=(acceleration?"ACC-":"Gyro-")+"XYZ"[axis%3];
            axisList.Add(new Ct12aAxisSummary(name,acceleration?"g":"°/s",mean,std,
                points.Length>0?min.sigma:null,points.Length>0?min.tau:null,
                released?white:null,acceleration?"(m/s)/√h":"°/√h",
                released?bias:null,acceleration?"mg":"°/h",
                released?"真实16帧批次均值工程代理；缺少逐帧硬件时标":
                    !sourceVerified?"SENSOR_OK未确认：保留诊断曲线，不发布噪声系数":
                    "时标/连续性或热稳态不合格，噪声系数不发布"));
        }
        return new Ct12aAnalysis(quality,curves,axisList,
            tempMin,tempMax,released,
            "六轴真实FIFO按16帧批次分别求均值；根据连续性/时标门槛的MCU批次中位周期构造序列。"+
            "重叠Allan偏差=sqrt[0.5*mean((后m点均值-前m点均值)^2)]，τ=m×批次时间间隔。"+
            "无插值、不跨丢帧断点拼接、不去趋势；τ上限不超过实际记录长度/12。"+
            "Gyro随机游走为ARW (°/√h)，ACC随机游走为VRW ((m/s)/√h)；仅短τ对数斜率约-0.5时拟合。"+
            "偏置不稳定度工程代理仅在Allan平坦区出现时给出，Gyro单位°/h、ACC单位mg。"+
            "只有批次时间戳，没有逐帧硬件时戳，不能用于正式计量认证。");
    }
    public static double Allan(IReadOnlyList<double> values,int m)
    {
        int n=values.Count;if(m<1||2L*m>n)throw new ArgumentOutOfRangeException(nameof(m));
        // Prefix avoids O(n*m) cost and improves numerical stability after subtracting a constant offset.
        double mean=values.Average();var prefix=new double[n+1];
        for(int i=0;i<n;i++)prefix[i+1]=prefix[i]+(values[i]-mean);
        int count=n-2*m+1;double sum=0;
        for(int i=0;i<count;i++)
        {
            double a=(prefix[i+m]-prefix[i])/m;
            double b=(prefix[i+2*m]-prefix[i+m])/m;
            double d=b-a;sum+=d*d;
        }
        return Math.Sqrt(0.5*sum/count);
    }
}
