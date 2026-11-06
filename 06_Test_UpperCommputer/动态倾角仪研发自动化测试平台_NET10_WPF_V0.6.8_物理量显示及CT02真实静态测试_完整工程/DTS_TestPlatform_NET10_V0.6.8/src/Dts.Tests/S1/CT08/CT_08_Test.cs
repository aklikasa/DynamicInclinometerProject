using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Dts.Core;
using Dts.TestEngine;
using Dts.Tests.S1.CT08;

namespace Dts.Tests.S1;

/// <summary>CT-08 outer-axis direction-specific approach hysteresis at identical mechanical target.</summary>
public sealed class CT_08_Test : TestModuleBase
{
    public override string TestId => "CT-08";
    public override bool IsExecutable => true;
    public override string Purpose => "真实2TD外轴从正反两个方向接近相同角度，量化路径相关的ACC残差与转台反馈差";
    public override string Procedure => "内轴固定→外轴从小角度正向接近→采样→从大角度反向接近→采样→重复全部目标→配对统计→图文报告";
    public override string Priority => "P0";
    public override string ImplementationNote => "输出整个系统回程差诊断，不能分离纯IMU、夹具、转台机械回差；不自动判PASS";

    public override async Task<TestExecutionResult> ExecuteAsync(TestExecutionContext context,CancellationToken ct)
    {
        if(context.Hardware is not IStaticAngleHardware hw)
            throw new InvalidOperationException("CT-08要求具备2TD双轴反馈与真实FIFO采集的硬件接口");
        if(context.Parameters is not Ct08Settings s)
            throw new InvalidOperationException("CT-08缺少独立窗口传入的参数");
        if(!hw.IsTwoTdConnected)throw new InvalidOperationException("2TD未连接/使能");
        var id=hw.CurrentIdentity??throw new InvalidOperationException("IMU未连接或UID尚未读取");
        var run=s.Calibration;
        if(run.Mode!=CalibrationMode.Ambient)
            throw new InvalidOperationException("CT-08要求主窗口使用常温标定模型");
        run.Validate(id);
        var acc=run.Files?.Acc??throw new InvalidDataException("缺少ACC常温参数JSON");
        var gyro=run.Files?.Gyro??throw new InvalidDataException("缺少Gyro常温参数JSON");
        if(acc.FsHint is null||gyro.FsHint is null)
            throw new InvalidDataException("历史JSON缺少拟合输入量程");
        var scale=CalibrationInputScalePolicy.Resolve(acc.FsHint,gyro.FsHint,0,0)
            ??throw new InvalidDataException("不支持的输入量程");
        int sign=ReadGravitySignAndAxisModel(acc.FilePath);
        var plan=Ct08Algorithm.BuildPlan(s);
        Ct08Algorithm.Validate(s,plan);
        ValidateCalibrationHashes(run);
        await hw.VerifyImuForPrecisionTestAsync(ct);
        var initial=await hw.ReadTwoTdAsync(ct);
        VerifyAxisState(initial,false);
        if(!WithinApproved(initial.Inner.PositionDeg,s)||!WithinApproved(initial.Outer.PositionDeg,s))
            throw new InvalidOperationException("当前转台位置超出已批准行程");
        string reportRoot=Path.GetFullPath(s.OutputRoot);
        if(!Directory.Exists(reportRoot))throw new DirectoryNotFoundException("报告根目录不存在："+reportRoot);
        string folder=Path.Combine(reportRoot,$"{id.DtsId}_{id.UidHex}",
            $"{DateTime.Now:yyyyMMdd_HHmmss_fff}_CT-08");
        Directory.CreateDirectory(folder);
        var visits=new List<Ct08Visit>();var pairs=new List<Ct08Pair>();
        string started=DateTimeOffset.UtcNow.ToString("O"),state="RUNNING",reason="";
        string stopProblem="",reportProblem="";
        IReadOnlyList<string> reportFiles=[];
        bool motionRequested=false;
        string uid=id.UidHex;
        Ct08ReportData Snapshot()=>new("CT-08","正反路径回程差","S1",id.DtsId,uid,
            started,DateTimeOffset.UtcNow.ToString("O"),state,reason,
            "研发诊断/待验收：输出正反路径下的系统残差差值；未规定产品判据，不自动判PASS",
            sign,"outer_x_inner_z，重力参考使用每次真实内外轴反馈计算，外轴主扫描",
            Path.GetFileName(acc.FilePath),acc.Sha256,Path.GetFileName(gyro.FilePath),gyro.Sha256,
            "历史校准JSON拟合输入量程："+scale.Display+"，物理量只换算一次，后续减零偏乘矩阵",
            new Ct08SettingsSnapshot(s.InnerPositionsText,s.OuterTargetsText,s.ApproachOffsetDeg,
                s.PairsPerTarget,s.SpeedDps,s.SettleSeconds,s.SampleSeconds,s.PositionToleranceDeg,
                s.AllowedMinDeg,s.AllowedMaxDeg,s.MinValidSamples,s.MaxOutlierFraction),
            plan.ToArray(),visits.ToArray(),pairs.ToArray(),Ct08Algorithm.Summarize(pairs,visits),
            "成对数据必须是同目标、真实反馈确认、分别从小/大角度进入，交替先后顺序以降低慢漂。"+
            "结果=(正向ACC校正值-正向编码器重力参考)-(反向ACC校正值-反向编码器重力参考)。"+
            "这一数值包含真实IMU、转台编码器误差、夹具回差和热/时间漂移；不能直接认定为IMU固有迟滞。"+
            "测试全程必须人员现场监护，软件软停车不能代替实体急停。");
        try
        {
            await File.WriteAllTextAsync(Path.Combine(folder,"calibration_identity.json"),
                JsonSerializer.Serialize(new{id.DtsId,id.UidHex,gravity_sign=sign,
                    axis_model="outer_x_inner_z",acc=new{acc.FilePath,acc.Sha256,acc.RunId,acc.FsHint},
                    gyro=new{gyro.FilePath,gyro.Sha256,gyro.RunId,gyro.FsHint},
                    note="每站重新核验完整UID及常温JSON SHA256"},
                    new JsonSerializerOptions{WriteIndented=true}),ct);
            motionRequested=true;
            foreach(var pose in plan)
            {
                ct.ThrowIfCancellationRequested();
                if(hw.CurrentIdentity?.UidHex!=uid)throw new InvalidDataException("本次IMU完整UID发生变化");
                ValidateCalibrationHashes(run);
                context.Progress?.Report($"CT-08 [{pose.Index}/{plan.Count}] " +
                    $"内轴{pose.InnerTargetDeg:F2}° 外轴从{pose.OuterDepartDeg:F2}° {pose.Side}到{pose.OuterTargetDeg:F2}°");
                // Move to departure via the approved sequence: outer 0 before changing inner,
                // then outer departure. Final move to target is ONLY the outer axis.
                await MoveToAsync(hw,pose.InnerTargetDeg,pose.OuterDepartDeg,s,ct);
                await MoveAxisAsync(hw,2,pose.OuterTargetDeg,s,ct);
                await Task.Delay(TimeSpan.FromSeconds(s.SettleSeconds),ct);
                var before=await hw.ReadTwoTdAsync(ct);
                VerifyPose(before,pose.InnerTargetDeg,pose.OuterTargetDeg,s);
                string physical=Path.Combine(folder,$"visit_{pose.Index:D3}_physical.csv");
                string corrected=Path.Combine(folder,$"visit_{pose.Index:D3}_corrected.csv");
                var capture=await hw.CaptureStaticPointAsync(physical,
                    TimeSpan.FromSeconds(s.SampleSeconds),context.Progress,ct);
                var after=await hw.ReadTwoTdAsync(ct);
                VerifyPose(after,pose.InnerTargetDeg,pose.OuterTargetDeg,s);
                if(Ct08Algorithm.Distance(before.Inner.PositionDeg,after.Inner.PositionDeg)>s.PositionToleranceDeg||
                   Ct08Algorithm.Distance(before.Outer.PositionDeg,after.Outer.PositionDeg)>s.PositionToleranceDeg)
                    throw new InvalidDataException("采样期间真实转台角度变化超容差，拒绝该点");
                ValidateCalibrationHashes(run);
                VerifyPhysicalCsvScale(physical,scale.AccFullScaleG,scale.GyroFullScaleDps);
                var analyzed=Ct08Algorithm.Analyze(pose,before,after,capture,
                    v=>acc.Apply(v[0],v[1],v[2]),v=>gyro.Apply(v[0],v[1],v[2]),
                    s,sign,physical,corrected);
                await SaveCorrectedFramesAsync(corrected,capture,analyzed.Accepted,
                    analyzed.Acc,analyzed.Gyro,ct);
                visits.Add(analyzed.Visit);
                if(visits.Count>=2 && visits[^1].PairIndex==visits[^2].PairIndex)
                {
                    var p=Ct08Algorithm.Pair(visits[^2],visits[^1]);
                    pairs.Add(p);
                    context.Progress?.Report($"CT-08 [{pose.Index}/{plan.Count}] 配对{p.PairIndex}完成："+
                        $"ACC残差路径差={p.HysteresisMagnitudeMg:F3}mg，"+
                        $"编码器外轴差={p.OuterActualDifferenceDeg:F5}°");
                }
                await Ct08Report.SaveCheckpointAsync(folder,Snapshot(),ct);
            }
            state="COMPLETED_PENDING_ACCEPTANCE";
            reason=$"完成{pairs.Count}个真实正反路径配对；自动生成报告，尚无产品合格判据";
        }
        catch(OperationCanceledException)
        {
            state="CANCELLED_PARTIAL";reason="用户取消，已完成的配对与逐帧证据保留";throw;
        }
        catch(Exception ex)
        {
            state="FAILED_PARTIAL";reason=ex.Message;throw;
        }
        finally
        {
            if(motionRequested)
            {
                try{await hw.StopTwoTdBothAsync(CancellationToken.None);}
                catch(Exception ex)
                {
                    stopProblem=ex.Message;state="STOP_NOT_CONFIRMED";
                    reason+="；双轴软停车未确认："+stopProblem;
                    context.Progress?.Report("危险：软停车反馈异常，请现场确认并必要时使用实体急停");
                }
            }
            try{reportFiles=await Ct08Report.ExportAsync(folder,Snapshot(),CancellationToken.None);}
            catch(Exception ex)
            {
                reportProblem=ex.Message;
                context.Progress?.Report("CT-08报告导出异常："+ex.Message+"，请保留现场CSV："+folder);
            }
        }
        if(stopProblem.Length>0)throw new IOException("双轴软停车反馈异常："+stopProblem);
        if(reportProblem.Length>0)throw new IOException("导出报告失败："+reportProblem);
        var metrics=Ct08Algorithm.Summarize(pairs,visits)
            ??throw new InvalidDataException("未形成有效正反配对");
        return new TestExecutionResult(TestId,TestOutcome.PendingAcceptance,
            $"CT-08完成{metrics.CompletedPairs}对，ACC路径残差差值RMS="+
            $"{metrics.RmsHysteresisMg:F3}mg，最大={metrics.MaxHysteresisMg:F3}mg；"+
            $"外轴实际反馈差RMS={metrics.OuterFeedbackDifferenceRmsDeg:F5}°，待验收。",
            null,reportFiles);
    }

    private static int ReadGravitySignAndAxisModel(string jsonPath)
    {
        using var doc=JsonDocument.Parse(File.ReadAllText(jsonPath));
        var root=doc.RootElement;
        if(!root.TryGetProperty("axis_model",out var model) || model.GetString()!="outer_x_inner_z")
            throw new InvalidDataException("只支持Python outer_x_inner_z机械参考模型");
        if(!root.TryGetProperty("gravity_sign",out var sign) || !sign.TryGetInt32(out int n) || n is not (1 or -1))
            throw new InvalidDataException("常温ACC JSON缺少gravity_sign=±1");
        return n;
    }
    private static void ValidateCalibrationHashes(CalibrationRun run)
    {
        foreach(var f in run.Sources)
            if(!File.Exists(f.FilePath) ||
               !Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(f.FilePath)))
                  .Equals(f.Sha256,StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("标定文件发生变化："+f.FilePath);
    }
    private static bool WithinApproved(double a,Ct08Settings s)
    {
        if(!double.IsFinite(a)) return false;
        double x=(a%360+360)%360;
        if(s.AllowedMinDeg<=0 && x>=360-s.PositionToleranceDeg) x=0;
        return x>=s.AllowedMinDeg-s.PositionToleranceDeg &&
               x<=s.AllowedMaxDeg+s.PositionToleranceDeg;
    }
    private static void VerifyAxisState(RealTableFeedback b,bool inPlace)
    {
        if(DateTimeOffset.UtcNow-b.CapturedUtc>TimeSpan.FromSeconds(3))
            throw new IOException("2TD反馈超过3秒未更新");
        static void Axis(RealAxisFeedback a,string name,bool arrived)
        {
            if(!a.Normal || a.Enabled!=true || !double.IsFinite(a.PositionDeg) ||
               !double.IsFinite(a.SpeedDps) || Math.Abs(a.SpeedDps)>0.05 ||
               (arrived && a.InPlace!=true))
                throw new IOException(name+"未正常使能、静止或到位："+a.Detail);
        }
        Axis(b.Inner,"内轴",inPlace);Axis(b.Outer,"外轴",inPlace);
    }
    private static void VerifyPose(RealTableFeedback b,double inner,double outer,Ct08Settings s)
    {
        VerifyAxisState(b,true);
        if(Ct08Algorithm.Distance(b.Inner.PositionDeg,inner)>s.PositionToleranceDeg ||
           Ct08Algorithm.Distance(b.Outer.PositionDeg,outer)>s.PositionToleranceDeg)
            throw new IOException("2TD实际回位反馈不满足到位容差");
    }
    private static async Task MoveToAsync(IStaticAngleHardware hw,double inner,double outer,
        Ct08Settings s,CancellationToken ct)
    {
        var b=await hw.ReadTwoTdAsync(ct);VerifyAxisState(b,false);
        if(!WithinApproved(b.Inner.PositionDeg,s) || !WithinApproved(b.Outer.PositionDeg,s))
            throw new IOException("实际反馈超出声明的允许行程");
        if(Ct08Algorithm.Distance(b.Inner.PositionDeg,inner)>s.PositionToleranceDeg)
        {
            // Keep CT-05/CT-06 route: park outer at 0 before changing inner.
            await MoveAxisAsync(hw,2,0,s,ct);
            await MoveAxisAsync(hw,0,inner,s,ct);
        }
        await MoveAxisAsync(hw,2,outer,s,ct);
    }
    private static async Task MoveAxisAsync(IStaticAngleHardware hw,int axis,double target,
        Ct08Settings s,CancellationToken ct)
    {
        if(target<s.AllowedMinDeg || target>s.AllowedMaxDeg)
            throw new InvalidOperationException("运动目标超过批准的行程范围");
        var b=await hw.ReadTwoTdAsync(ct);VerifyAxisState(b,false);
        var now=axis==0?b.Inner:b.Outer;
        if(!WithinApproved(now.PositionDeg,s)) throw new IOException("运动前轴反馈越界");
        if(Ct08Algorithm.Distance(now.PositionDeg,target)<=s.PositionToleranceDeg && now.InPlace==true) return;
        await hw.SetTwoTdAbsoluteAsync(axis,target,s.SpeedDps,ct);
        double timeout=Math.Min(600,Math.Max(40,Math.Abs(target-now.PositionDeg)/s.SpeedDps*2.5+30));
        var watch=System.Diagnostics.Stopwatch.StartNew();int confirmed=0;
        while(watch.Elapsed.TotalSeconds<timeout)
        {
            ct.ThrowIfCancellationRequested();await Task.Delay(200,ct);
            b=await hw.ReadTwoTdAsync(ct);
            if(DateTimeOffset.UtcNow-b.CapturedUtc>TimeSpan.FromSeconds(3))
                throw new IOException("2TD运动反馈中断");
            var active=axis==0?b.Inner:b.Outer;var partner=axis==0?b.Outer:b.Inner;
            if(!active.Normal || active.Enabled!=true || !double.IsFinite(active.PositionDeg) ||
               !double.IsFinite(active.SpeedDps) || !partner.Normal || partner.Enabled!=true ||
               !double.IsFinite(partner.SpeedDps) || Math.Abs(partner.SpeedDps)>0.05)
                throw new IOException("转台运动轴异常或另一轴正在运动："+active.Detail);
            if(!WithinApproved(active.PositionDeg,s)) throw new IOException("转台运动越界，要求停车");
            bool arrived=Ct08Algorithm.Distance(active.PositionDeg,target)<=s.PositionToleranceDeg &&
                Math.Abs(active.SpeedDps)<=0.05 && active.InPlace==true;
            confirmed=arrived?confirmed+1:0;
            if(confirmed>=3) return;
        }
        throw new TimeoutException($"轴{axis}到位超时：目标{target:F3}°");
    }
    private static void VerifyPhysicalCsvScale(string file,int accFs,int gyroFs)
    {
        using var r=new StreamReader(file);
        var columns=(r.ReadLine()?.TrimStart('\uFEFF') ?? "").Split(',');
        foreach(string col in new[]{"ax_g","gx_dps","raw_ax","raw_gx","acc_input_fs_g","gyro_input_fs_dps"})
            if(!columns.Contains(col,StringComparer.Ordinal)) throw new InvalidDataException("采集CSV缺少字段："+col);
        int I(string name)=>Array.IndexOf(columns,name);
        if(!Asm330Codec.TryAccMg(accFs,out var mg) || !Asm330Codec.TryGyroMdps(gyroFs,out var mdps))
            throw new InvalidDataException("不支持的灵敏度输入量程");
        int count=0;string? line;var ci=CultureInfo.InvariantCulture;
        while((line=r.ReadLine()) is not null)
        {
            if(string.IsNullOrWhiteSpace(line)) continue;
            var v=line.Split(',');
            if(v.Length<columns.Length || !int.TryParse(v[I("acc_input_fs_g")],out var a) ||
               !int.TryParse(v[I("gyro_input_fs_dps")],out var g) || a!=accFs || g!=gyroFs)
                throw new InvalidDataException("真实采集CSV与本次标定输入量程不一致");
            double acc=double.Parse(v[I("ax_g")],ci), rawAcc=double.Parse(v[I("raw_ax")],ci);
            double gyr=double.Parse(v[I("gx_dps")],ci), rawGyr=double.Parse(v[I("raw_gx")],ci);
            if(Math.Abs(acc-rawAcc*mg/1000d)>1e-9 || Math.Abs(gyr-rawGyr*mdps/1000d)>1e-9)
                throw new InvalidDataException("物理量与真实原始计数的换算不匹配");
            count++;
        }
        if(count==0) throw new InvalidDataException("本次采集没有可用CSV帧");
    }
    private static async Task SaveCorrectedFramesAsync(string file,StaticPointSamples cap,
        bool[] accepted,double[][] acc,double[][] gyro,CancellationToken ct)
    {
        await using var stream=new FileStream(file,FileMode.CreateNew,FileAccess.Write,
            FileShare.Read,32768,FileOptions.Asynchronous);
        await using var writer=new StreamWriter(stream,new UTF8Encoding(true));
        await writer.WriteLineAsync("index,accepted,acc_x_cal_g,acc_y_cal_g,acc_z_cal_g,gyro_x_cal_dps,gyro_y_cal_dps,gyro_z_cal_dps,chip_temp_c");
        var ci=CultureInfo.InvariantCulture;
        string F(double v)=>v.ToString("G17",ci);
        for(int i=0;i<acc.Length;i++)
        {
            ct.ThrowIfCancellationRequested();
            var row=new[]{i.ToString(ci),accepted[i]?"1":"0"}
                .Concat(acc[i].Select(F)).Concat(gyro[i].Select(F))
                .Append(F(cap.Samples[i].TemperatureC));
            await writer.WriteLineAsync(string.Join(",",row));
        }
        await writer.FlushAsync(ct);
    }
}
