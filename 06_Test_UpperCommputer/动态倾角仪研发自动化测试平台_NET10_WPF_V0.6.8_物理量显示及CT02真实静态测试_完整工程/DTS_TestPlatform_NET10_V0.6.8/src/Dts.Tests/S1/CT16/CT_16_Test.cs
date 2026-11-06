using System.Globalization;
using System.Security.Cryptography;
using System.Text.Json;
using Dts.Core;
using Dts.TestEngine;
using Dts.Tests.S1.CT16;

namespace Dts.Tests.S1;

/// <summary>Motion → confirmed stillness → real ACC-derived tilt recovery. Fusion output unavailable.</summary>
public sealed class CT_16_Test : TestModuleBase
{
    public override string TestId => "CT-16";
    public override bool IsExecutable => true;
    public override string Purpose => "低速正反往返后回到同一机械零位，观察真实加速度推算倾角的停车后回零与恢复";
    public override string Procedure => "零位采集基线→外轴正/反低速离位并回零→双轴停车确认→分窗真实FIFO采样→诊断恢复过程→图文报告";
    public override string Priority => "P1";
    public override string ImplementationNote => "仅ACC推算倾角工程诊断；现有驱动未提供融合角，不能冒称融合回零/完整CT-16验收；与CT-27 Gyro零偏恢复不同。";

    public override async Task<TestExecutionResult> ExecuteAsync(TestExecutionContext context,CancellationToken ct)
    {
        if(context.Hardware is not IStaticAngleHardware hw)
            throw new InvalidOperationException("CT-16需要真实2TD反馈及FIFO采集接口");
        if(context.Parameters is not Ct16Settings s)
            throw new InvalidOperationException("CT-16缺少专属窗口参数");
        if(!hw.IsTwoTdConnected)throw new InvalidOperationException("CT-16需要连接并使能真实2TD");
        var id=hw.CurrentIdentity??throw new InvalidOperationException("IMU未连接或未取得完整UID");
        var run=s.Calibration;
        if(run.Mode!=CalibrationMode.Ambient)throw new InvalidOperationException("CT-16当前只接受完整UID匹配的常温ACC/Gyro标定");
        run.Validate(id);
        var acc=run.Files?.Acc??throw new InvalidDataException("缺少匹配的ACC常温JSON");
        var gyro=run.Files?.Gyro??throw new InvalidDataException("缺少匹配的Gyro常温JSON");
        if(acc.FsHint is null||gyro.FsHint is null)throw new InvalidDataException("标定JSON未指定历史输入量程");
        var scale=CalibrationInputScalePolicy.Resolve(acc.FsHint,gyro.FsHint,0,0)
            ??throw new InvalidDataException("不支持的标定输入量程");
        int gravitySign=GetGravitySign(acc.FilePath);
        var plan=Ct16Algorithm.BuildPlan(s);
        Ct16Algorithm.Validate(s,plan);
        VerifyCalibrationFiles(run);
        await hw.VerifyImuForPrecisionTestAsync(ct);
        var first=await hw.ReadTwoTdAsync(ct);
        VerifyStationaryFeedback(first,false);
        if(!InRange(first.Inner.PositionDeg,s)||!InRange(first.Outer.PositionDeg,s))
            throw new InvalidOperationException("设备当前实际角度超出批准运动范围");
        string root=Path.GetFullPath(s.OutputRoot);
        if(!Directory.Exists(root))throw new DirectoryNotFoundException("报告根目录不存在："+root);
        string folder=Path.Combine(root,$"{id.DtsId}_{id.UidHex}",
            $"{DateTime.Now:yyyyMMdd_HHmmss_fff}_CT-16");
        Directory.CreateDirectory(folder);
        var bins=new List<Ct16Bin>();var cycles=new List<Ct16Cycle>();
        string started=DateTimeOffset.UtcNow.ToString("O"),state="RUNNING",reason="";
        string stopError="",reportError="";IReadOnlyList<string> outputs=[];
        bool moved=false;
        Ct16ReportData Snapshot()=>new("CT-16","低速运动后归零与恢复（ACC代理角诊断）",
            id.DtsId,id.UidHex,started,DateTimeOffset.UtcNow.ToString("O"),state,reason,
            "工程诊断（DiagnosticOnly）：仅评价已观测的ACC倾角代理量；未获取设备融合角，不允许判定融合回零PASS",
            "ACC_CALIBRATED_TILT_PROXY_NOT_FUSED_OUTPUT",
            "outer_x_inner_z; Rx(outer)Rz(inner); 零位ACC单位重力矢量与外轴切向投影；逐窗为批次采集时间",
            Path.GetFileName(acc.FilePath),acc.Sha256,Path.GetFileName(gyro.FilePath),gyro.Sha256,
            "历史JSON输入量程："+scale.Display+"；真实原始计数→物理量→ACC/Gyro矩阵各应用一次",
            new Ct16Snapshot(s.SpeedsDps,s.Repeats,s.InnerFixedDeg,s.OuterHomeDeg,s.ExcursionDeg,
                s.PrepareSpeedDps,s.BaselineSeconds,s.RecoverySeconds,s.BinSeconds,
                s.RecoveryThresholdDeg,s.ConsecutiveBins,s.PositionToleranceDeg,
                s.AllowedMinDeg,s.AllowedMaxDeg,s.MinValidSamplesPerBin),
            plan.ToArray(),bins.ToArray(),cycles.ToArray(),Ct16Algorithm.Summarize(cycles),
            "不能声称测到了融合输出、真实机械超调峰值或毫秒级恢复。"+
            "停止时刻为软件确认已静止时刻，实际停止早于此刻；采样窗是批次级主机时标。"+
            "返回的恢复时间仅是连续稳定条件首次被观察到的结束时刻上界；无恢复则为null。"+
            "2TD反馈仅在各窗前后核验；结果受转台回位误差、装夹、温度及ACC噪声影响。"+
            "此项不是CT-27的陀螺仪零偏恢复。现场必须监护和准备实体急停。");
        try
        {
            await File.WriteAllTextAsync(Path.Combine(folder,"calibration_identity.json"),
                JsonSerializer.Serialize(new{id.DtsId,id.UidHex,ACC=new{acc.FilePath,acc.Sha256,acc.RunId,acc.FsHint},
                    Gyro=new{gyro.FilePath,gyro.Sha256,gyro.RunId,gyro.FsHint},gravity_sign=gravitySign,
                    angle_source="calibrated_accel_proxy_not_device_fusion"},
                    new JsonSerializerOptions{WriteIndented=true}),ct);
            moved=true;
            context.Progress?.Report("CT-16 设置固定内轴及外轴零位（调整内轴前先将外轴回0°）");
            await PrepareHomeAsync(hw,s,ct);
            for(int i=0;i<plan.Count;i++)
            {
                ct.ThrowIfCancellationRequested();VerifyIdentity(hw,id.UidHex,run);
                var p=plan[i];
                context.Progress?.Report($"CT-16 [{i+1}/{plan.Count}] 零位真实ACC基线，速度{p.SpeedDps:F2}°/s，{p.Direction}");
                await MoveAxisAsync(hw,2,p.HomeDeg,s.PrepareSpeedDps,s,ct);
                await hw.StopTwoTdBothAsync(ct);
                var b0=await hw.ReadTwoTdAsync(ct);VerifyPose(b0,s);
                string baselineCsv=Path.Combine(folder,$"cycle_{p.Index:D3}_baseline_physical.csv");
                var baseline=await hw.CaptureStaticPointAsync(baselineCsv,TimeSpan.FromSeconds(s.BaselineSeconds),context.Progress,ct);
                var b1=await hw.ReadTwoTdAsync(ct);VerifyPose(b1,s);
                if(Ct16Algorithm.Distance(b0.Outer.PositionDeg,b1.Outer.PositionDeg)>s.PositionToleranceDeg)
                    throw new InvalidDataException("基线采集过程中外轴角度变化超容差");
                VerifyPhysicalCsvScale(baselineCsv,scale.AccFullScaleG,scale.GyroFullScaleDps);
                var mean=Ct16Algorithm.MeanStatic(baseline,
                    v=>acc.Apply(v[0],v[1],v[2]),v=>gyro.Apply(v[0],v[1],v[2]),s.MinValidSamplesPerBin);
                double[] baseAcc=mean.Acc;
                var tangent=Ct16Algorithm.Tangent(baseAcc,p.InnerDeg,p.HomeDeg,gravitySign);
                bins.Add(new Ct16Bin(p.Index,0,true,0,baseline.StartedUtc.ToString("O"),baseline.EndedUtc.ToString("O"),
                    b1.Inner.PositionDeg,b1.Outer.PositionDeg,baseAcc,mean.Gyro,0,0,
                    mean.Count,baseline.Batches,baseline.DuplicateBatches,mean.Temp,baselineCsv));
                await Ct16Report.SaveCheckpointAsync(folder,Snapshot(),ct);
                context.Progress?.Report($"CT-16 [{i+1}/{plan.Count}] {p.Direction}，离位至{p.ExcursionTargetDeg:F2}°");
                await MoveAxisAsync(hw,2,p.ExcursionTargetDeg,p.SpeedDps,s,ct);
                await MoveAxisAsync(hw,2,p.HomeDeg,p.SpeedDps,s,ct);
                // The origin of recovery is the LAST observed stationary confirmation, not inferred motor-stop instant.
                await hw.StopTwoTdBothAsync(ct);
                var stopped=await hw.ReadTwoTdAsync(ct);VerifyPose(stopped,s);
                DateTimeOffset stopConfirmed=DateTimeOffset.UtcNow;
                int count=(int)Math.Ceiling(s.RecoverySeconds/s.BinSeconds);
                var recovery=new List<Ct16Bin>();
                for(int j=1;j<=count;j++)
                {
                    ct.ThrowIfCancellationRequested();VerifyIdentity(hw,id.UidHex,run);
                    var before=await hw.ReadTwoTdAsync(ct);VerifyPose(before,s);
                    string physical=Path.Combine(folder,$"cycle_{p.Index:D3}_recovery_{j:D3}_physical.csv");
                    var cap=await hw.CaptureStaticPointAsync(physical,TimeSpan.FromSeconds(s.BinSeconds),context.Progress,ct);
                    var after=await hw.ReadTwoTdAsync(ct);VerifyPose(after,s);
                    if(Ct16Algorithm.Distance(before.Inner.PositionDeg,after.Inner.PositionDeg)>s.PositionToleranceDeg||
                       Ct16Algorithm.Distance(before.Outer.PositionDeg,after.Outer.PositionDeg)>s.PositionToleranceDeg)
                        throw new InvalidDataException("恢复采样窗开始/结束2TD反馈偏移超容差");
                    VerifyPhysicalCsvScale(physical,scale.AccFullScaleG,scale.GyroFullScaleDps);
                    var current=Ct16Algorithm.MeanStatic(cap,
                        v=>acc.Apply(v[0],v[1],v[2]),v=>gyro.Apply(v[0],v[1],v[2]),s.MinValidSamplesPerBin);
                    double signed=Ct16Algorithm.SignedTilt(current.Acc,baseAcc,tangent);
                    double angular=Ct16Algorithm.Angle(current.Acc,baseAcc);
                    var bin=new Ct16Bin(p.Index,j,false,
                        Math.Max(0,(cap.EndedUtc-stopConfirmed).TotalSeconds),
                        cap.StartedUtc.ToString("O"),cap.EndedUtc.ToString("O"),
                        after.Inner.PositionDeg,after.Outer.PositionDeg,
                        current.Acc,current.Gyro,signed,angular,current.Count,
                        cap.Batches,cap.DuplicateBatches,current.Temp,physical);
                    bins.Add(bin);recovery.Add(bin);
                    if(j==1||j==count||j%3==0)
                        context.Progress?.Report($"CT-16 [{i+1}/{plan.Count}] 停车后{bin.SinceStopSeconds:F1}s：ACC倾角代理偏离{angular:F5}°");
                    await Ct16Report.SaveCheckpointAsync(folder,Snapshot(),ct);
                }
                var stats=Ct16Algorithm.SummarizeRecovery(recovery,s.RecoveryThresholdDeg,s.ConsecutiveBins);
                cycles.Add(new Ct16Cycle(p.Index,p.SpeedDps,p.Direction,p.HomeDeg,p.ExcursionTargetDeg,
                    stopConfirmed.ToString("O"),stopped.Inner.PositionDeg,stopped.Outer.PositionDeg,
                    stats.Peak,stats.PeakSigned,stats.FinalSigned,stats.FinalAngle,stats.RecoveredBy,
                    recovery.Count,stats.RecoveredBy is null?"未在观察窗内确认稳定" :
                    "已观测达到门限；时间为窗结束相对停稳确认的上界"));
                await Ct16Report.SaveCheckpointAsync(folder,Snapshot(),ct);
            }
            state="COMPLETED_DIAGNOSTIC_ONLY";
            reason=$"完成{cycles.Count}次低速往返及停车后真实ACC代理角恢复，融合角未接入，待设备侧进一步验收";
        }
        catch(OperationCanceledException)
        {
            state="CANCELLED_PARTIAL";reason="用户取消，保留已完成数据；不可判断恢复通过";throw;
        }
        catch(Exception ex)
        {
            state="FAILED_PARTIAL";reason=ex.Message;throw;
        }
        finally
        {
            if(moved)
            {
                try{await hw.StopTwoTdBothAsync(CancellationToken.None);}
                catch(Exception ex)
                {
                    stopError=ex.Message;state="STOP_NOT_CONFIRMED";
                    reason+="；软停车未确认："+stopError;
                    context.Progress?.Report("危险：双轴软停车未确认，请现场检查或使用实体急停");
                }
            }
            try{outputs=await Ct16Report.ExportAsync(folder,Snapshot(),CancellationToken.None);}
            catch(Exception ex)
            {
                reportError=ex.Message;
                context.Progress?.Report("报告导出失败，请保留采集CSV："+folder+"；"+reportError);
            }
        }
        if(stopError.Length>0)throw new IOException("双轴停车未确认："+stopError);
        if(reportError.Length>0)throw new IOException("CT-16报告生成失败："+reportError);
        var summary=Ct16Algorithm.Summarize(cycles)
            ??throw new InvalidDataException("无完整恢复循环，不能报告成功");
        return new TestExecutionResult(TestId,TestOutcome.DiagnosticOnly,
            $"CT-16诊断完成{summary.CompletedCycles}次；最大观测到的停车后ACC倾角偏离"+
            $"{summary.MaximumObservedPostStopPeakDeg:F4}°，确认恢复{summary.RecoveryObservedCycles}次。"+
            "仅ACC代理角、非设备融合角，不自动判PASS。",null,outputs);
    }

    private static void VerifyIdentity(IStaticAngleHardware hw,string uid,CalibrationRun run)
    {
        if(hw.CurrentIdentity?.UidHex!=uid)throw new InvalidDataException("设备完整UID变化");
        VerifyCalibrationFiles(run);
    }
    private static void VerifyCalibrationFiles(CalibrationRun run)
    {
        foreach(var f in run.Sources)
            if(!File.Exists(f.FilePath)||
               !Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(f.FilePath)))
                   .Equals(f.Sha256,StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("标定JSON在测试中变动："+f.FilePath);
    }
    private static int GetGravitySign(string path)
    {
        using var doc=JsonDocument.Parse(File.ReadAllText(path));var root=doc.RootElement;
        if(!root.TryGetProperty("axis_model",out var model)||model.GetString()!="outer_x_inner_z"||
           !root.TryGetProperty("gravity_sign",out var sign)||!sign.TryGetInt32(out int g)||g is not (1 or -1))
            throw new InvalidDataException("ACC JSON缺少与本测试一致的outer_x_inner_z/gravity_sign参考定义");
        return g;
    }
    private static bool InRange(double angle,Ct16Settings s)
    {
        if(!double.IsFinite(angle))return false;
        // Do not wrap encoder 359.9° into near-zero: that would permit an unapproved route.
        return angle>=s.AllowedMinDeg-s.PositionToleranceDeg&&
               angle<=s.AllowedMaxDeg+s.PositionToleranceDeg;
    }
    private static void VerifyStationaryFeedback(RealTableFeedback b,bool inPlace)
    {
        if(DateTimeOffset.UtcNow-b.CapturedUtc>TimeSpan.FromSeconds(3))throw new IOException("转台反馈超过3秒");
        static void Check(RealAxisFeedback a,string label,bool requireInPlace)
        {
            if(!a.Normal||a.Enabled!=true||!double.IsFinite(a.PositionDeg)||
               !double.IsFinite(a.SpeedDps)||Math.Abs(a.SpeedDps)>0.05||
               (requireInPlace&&a.InPlace!=true))
                throw new IOException("转台"+label+"未确认使能/静止/到位："+a.Detail);
        }
        Check(b.Inner,"内轴",inPlace);Check(b.Outer,"外轴",inPlace);
    }
    private static void VerifyPose(RealTableFeedback b,Ct16Settings s)
    {
        VerifyStationaryFeedback(b,true);
        if(Ct16Algorithm.Distance(b.Inner.PositionDeg,s.InnerFixedDeg)>s.PositionToleranceDeg||
           Ct16Algorithm.Distance(b.Outer.PositionDeg,s.OuterHomeDeg)>s.PositionToleranceDeg)
            throw new IOException("真实2TD未停在已定义零位");
    }
    private static async Task PrepareHomeAsync(IStaticAngleHardware hw,Ct16Settings s,CancellationToken ct)
    {
        var state=await hw.ReadTwoTdAsync(ct);VerifyStationaryFeedback(state,false);
        if(!InRange(state.Inner.PositionDeg,s)||!InRange(state.Outer.PositionDeg,s))
            throw new InvalidOperationException("转台当前角度不在批准行程内");
        if(Ct16Algorithm.Distance(state.Inner.PositionDeg,s.InnerFixedDeg)>s.PositionToleranceDeg)
        {
            await MoveAxisAsync(hw,2,0,s.PrepareSpeedDps,s,ct);
            await MoveAxisAsync(hw,0,s.InnerFixedDeg,s.PrepareSpeedDps,s,ct);
        }
        await MoveAxisAsync(hw,2,s.OuterHomeDeg,s.PrepareSpeedDps,s,ct);
        VerifyPose(await hw.ReadTwoTdAsync(ct),s);
    }
    private static async Task MoveAxisAsync(IStaticAngleHardware hw,int axis,double target,
        double speed,Ct16Settings s,CancellationToken ct)
    {
        if(target<s.AllowedMinDeg||target>s.AllowedMaxDeg)
            throw new InvalidOperationException("运动目标超出现场批准行程");
        var b=await hw.ReadTwoTdAsync(ct);VerifyStationaryFeedback(b,false);
        var current=axis==0?b.Inner:b.Outer;
        if(!InRange(current.PositionDeg,s))throw new IOException("运动前转台反馈越界");
        if(Ct16Algorithm.Distance(current.PositionDeg,target)<=s.PositionToleranceDeg&&current.InPlace==true)return;
        await hw.SetTwoTdAbsoluteAsync(axis,target,speed,ct);
        double timeout=Math.Min(900,Math.Max(40,Math.Abs(target-current.PositionDeg)/speed*2.5+30));
        var sw=System.Diagnostics.Stopwatch.StartNew();int stable=0;
        while(sw.Elapsed.TotalSeconds<timeout)
        {
            ct.ThrowIfCancellationRequested();await Task.Delay(200,ct);
            b=await hw.ReadTwoTdAsync(ct);
            if(DateTimeOffset.UtcNow-b.CapturedUtc>TimeSpan.FromSeconds(3))throw new IOException("2TD运动反馈中断");
            var a=axis==0?b.Inner:b.Outer;var partner=axis==0?b.Outer:b.Inner;
            if(!a.Normal||a.Enabled!=true||!double.IsFinite(a.PositionDeg)||!double.IsFinite(a.SpeedDps)||
               !partner.Normal||partner.Enabled!=true||!double.IsFinite(partner.SpeedDps)||
               Math.Abs(partner.SpeedDps)>0.05)
                throw new IOException("2TD目标轴或非运动轴异常："+a.Detail);
            if(!InRange(a.PositionDeg,s))throw new IOException("运行中超出批准范围，要求停车");
            bool ok=Ct16Algorithm.Distance(a.PositionDeg,target)<=s.PositionToleranceDeg&&
                Math.Abs(a.SpeedDps)<=0.05&&a.InPlace==true;
            stable=ok?stable+1:0;
            if(stable>=3)return;
        }
        throw new TimeoutException($"转台轴{axis}低速运动到位超时，目标{target:F3}°");
    }
    private static void VerifyPhysicalCsvScale(string file,int accFs,int gyroFs)
    {
        using var reader=new StreamReader(file);
        var columns=(reader.ReadLine()?.TrimStart('\uFEFF')??"").Split(',');
        foreach(string field in new[]{"ax_g","gx_dps","raw_ax","raw_gx","acc_input_fs_g","gyro_input_fs_dps"})
            if(!columns.Contains(field,StringComparer.Ordinal))throw new InvalidDataException("真实采样CSV缺少字段："+field);
        int Index(string field)=>Array.IndexOf(columns,field);
        if(!Asm330Codec.TryAccMg(accFs,out var mg)||!Asm330Codec.TryGyroMdps(gyroFs,out var mdps))
            throw new InvalidDataException("校准输入量程不受支持");
        string? line;int count=0;var ci=CultureInfo.InvariantCulture;
        while((line=reader.ReadLine()) is not null)
        {
            if(string.IsNullOrWhiteSpace(line))continue;
            var cols=line.Split(',');
            if(cols.Length<columns.Length||!int.TryParse(cols[Index("acc_input_fs_g")],out int a)||
               !int.TryParse(cols[Index("gyro_input_fs_dps")],out int g)||a!=accFs||g!=gyroFs)
                throw new InvalidDataException("真实FIFO数据与JSON拟合量程不一致");
            double ax=double.Parse(cols[Index("ax_g")],ci),rawAx=double.Parse(cols[Index("raw_ax")],ci),
                gx=double.Parse(cols[Index("gx_dps")],ci),rawGx=double.Parse(cols[Index("raw_gx")],ci);
            if(Math.Abs(ax-rawAx*mg/1000d)>1e-9||Math.Abs(gx-rawGx*mdps/1000d)>1e-9)
                throw new InvalidDataException("真实FIFO原始计数/物理量换算未通过校验");
            count++;
        }
        if(count==0)throw new InvalidDataException("真实物理量CSV无有效行");
    }
}
