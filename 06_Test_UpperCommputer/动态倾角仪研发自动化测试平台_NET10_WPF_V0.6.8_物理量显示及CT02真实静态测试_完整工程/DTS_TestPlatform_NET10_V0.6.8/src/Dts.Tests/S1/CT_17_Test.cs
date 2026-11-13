using System.Security.Cryptography;
using System.Runtime.ExceptionServices;
using System.Text.Json;
using Dts.Core;
using Dts.TestEngine;
using Dts.Tests.S1.CT10;
using Dts.Tests.S1.CT12A;
using Dts.Tests.S1.CT17;

namespace Dts.Tests.S1;

/// <summary>
/// CT-17: real FIFO batch timing audit plus small, guarded bidirectional motion.
/// Uses the already commissioned CT-10 real dynamic adapter and its shared table lock.
/// Never treats host receipt time as the sensor's hardware sample instant.
/// </summary>
public sealed class CT_17_Test : TestModuleBase
{
    public override string TestId=>"CT-17";
    public override bool IsExecutable=>true;
    public override string Name=>"数据时间对齐与延迟诊断";
    public override string Purpose=>"核验IMU真实ODR、16帧FIFO批次、主机输出时序，并用小幅正反向运动估计编码器与Gyro的表观时间偏移和动态响应延迟";
    public override string Procedure=>"UID/常温JSON核验→静止FIFO时间基采集→核验16帧/ODR/主机批次频率/MCU tick→小幅正反向往复→记录命令调用、编码器起动与Gyro响应→时延/抖动/疑似漏批报告";
    public override string Priority=>"P1";
    public override string ImplementationNote=>"需要已核验的CT-10真实动态适配器与ct10_machine_profile.json；时间戳均为主机时钟，Gyro为FIFO最新槽位主机接收时标，属于工程级表观时延诊断，不是硬件同步认证。";

    private static void VerifyHashes(CalibrationRun run)
    {
        foreach(var f in run.Sources)
            if(!File.Exists(f.FilePath)||
               !Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(f.FilePath))).Equals(f.Sha256,StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("常温标定文件缺失或SHA256不匹配："+f.FilePath);
    }
    private static void VerifyManifest(CaptureArtifacts c,DeviceIdentity id,CalibrationRun run)
    {
        using var doc=JsonDocument.Parse(File.ReadAllText(c.ManifestFile));
        var r=doc.RootElement;
        string S(string key)=>r.GetProperty(key).GetString()??"";
        if(S("hardware_mode")!="REAL_MCU_HARDWARE"||S("test_id")!="CT-17"||
           S("result_status")!="COMPLETED"||S("processing_mode")!="AMBIENT")
            throw new InvalidDataException("静态时间基采集manifest不是完整真实硬件常温数据");
        if(!S("uid_raw_12_bytes").Equals(id.UidHex,StringComparison.OrdinalIgnoreCase)||S("device_dts_id")!=id.DtsId)
            throw new InvalidDataException("静态时间基数据UID与当前设备不一致");
        if(r.GetProperty("samples").GetInt32()!=c.Samples||r.GetProperty("batches").GetInt32()!=c.Batches)
            throw new InvalidDataException("manifest帧数/批次数与采集返回值不一致");
        if(r.GetProperty("sensor_unverified_batches").GetInt32()!=0)
            throw new InvalidDataException("静态时间基采集包含SENSOR_OK未确认批次，拒绝与动态参考时序混合分析");
        var hashes=r.GetProperty("calibration_files").EnumerateArray()
            .Select(x=>x.GetProperty("sha256").GetString()??"").ToHashSet(StringComparer.OrdinalIgnoreCase);
        if(hashes.Count!=run.Sources.Count||!hashes.SetEquals(run.Sources.Select(x=>x.Sha256)))
            throw new InvalidDataException("manifest中的常温标定SHA256与本次冻结源不一致");
    }
    private static void VerifyStage(Ct10StageStatus f,Ct10Settings s)
    {
        if(!f.InnerEnabled||!f.OuterEnabled||!f.InnerNormal||!f.OuterNormal||
           !f.InnerStationary||!f.OuterStationary)
            throw new IOException("转台未处于双轴使能、正常且静止状态："+f.Detail);
        if(f.InnerPositionDeg<s.ApprovedMinDeg-0.3||f.InnerPositionDeg>s.ApprovedMaxDeg+0.3||
           f.OuterPositionDeg<s.ApprovedMinDeg-0.3||f.OuterPositionDeg>s.ApprovedMaxDeg+0.3)
            throw new IOException("转台当前位置超出现场批准行程");
    }

    public override async Task<TestExecutionResult> ExecuteAsync(TestExecutionContext context,CancellationToken ct)
    {
        if(context.Hardware is not IStaticAngleHardware host)
            throw new InvalidOperationException("CT-17需要主平台真实静态IMU/转台硬件接口");
        if(context.Parameters is not Ct17Settings s)throw new InvalidOperationException("CT-17缺少专用参数快照");
        Ct17Algorithm.Validate(s);
        var id=host.CurrentIdentity??throw new InvalidOperationException("IMU未连接或未读取完整UID");
        if(!host.IsTwoTdConnected)throw new InvalidOperationException("CT-17动态往复需要真实2TD-600双轴连接");
        var dynamicHw=Ct10DynamicBridge.Resolve(host);
        if(dynamicHw is null||!dynamicHw.IsRealDynamicCaptureReady)
            throw new NotSupportedException("CT-17需要CT-10已核验的真实动态适配器；请先核验IMU/2TD和ct10_machine_profile.json");
        if(dynamicHw is not ICt17TimingTelemetry timing)
            throw new NotSupportedException("动态适配器缺少CT-17命令调用时标/运动前基线扩展，请安装对应CT17适配器扩展");
        if(!dynamicHw.CurrentUidHex.Equals(id.UidHex,StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("动态适配器UID与主界面IMU UID不一致");
        if(s.Calibration.Mode!=CalibrationMode.Ambient)
            throw new InvalidOperationException("CT-17必须使用当前UID匹配的常温ACC/Gyro标定");
        s.Calibration.Validate(id);
        var acc=s.Calibration.Files?.Acc??throw new InvalidDataException("UID匹配ACC常温JSON缺失");
        var gyro=s.Calibration.Files?.Gyro??throw new InvalidDataException("UID匹配Gyro常温JSON缺失");
        if(gyro.FsHint is null)throw new InvalidDataException("Gyro JSON缺少拟合输入量程，无法校验动态原始计数");
        VerifyHashes(s.Calibration);
        if(!Directory.Exists(s.OutputRoot))throw new DirectoryNotFoundException("报告根目录不存在："+s.OutputRoot);
        foreach(var axis in new[]{(Enabled:s.TestInner,Axis:Ct10Axis.Inner),(Enabled:s.TestOuter,Axis:Ct10Axis.Outer)})
            if(axis.Enabled&&(s.CommandSpeedDps>dynamicHw.MaximumCertifiedSpeedDps(axis.Axis)||
               s.SetupSpeedDps>dynamicHw.MaximumCertifiedSpeedDps(axis.Axis)))
                throw new InvalidOperationException($"{axis.Axis}轴测试速率超过已核验设备限速 {dynamicHw.MaximumCertifiedSpeedDps(axis.Axis):F2}°/s");
        await host.VerifyImuForPrecisionTestAsync(ct);
        var stage=await dynamicHw.ReadStageAsync(ct);
        var ct10Guard=new Ct10Settings(s.OutputRoot,"",s.TestInner,s.TestOuter,1,
            s.CenterDeg-s.AmplitudeDeg,s.CenterDeg+s.AmplitudeDeg,s.ApprovedMinDeg,s.ApprovedMaxDeg,
            s.SetupSpeedDps,s.SettleSeconds,0.2,s.EncoderDerivativeWindowSeconds,8,
            s.InnerGyroSign,s.OuterGyroSign,true,true,true,s.Calibration);
        VerifyStage(stage,ct10Guard);

        var started=DateTimeOffset.UtcNow;
        context.Progress?.Report($"CT-17静态时基采集开始：{s.StaticCaptureSeconds:F0}s，目标主机批次输出{s.ExpectedHostBatchHz:F1}Hz");
        var staticCapture=await host.CaptureStaticImuAsync(TestId,TimeSpan.FromSeconds(s.StaticCaptureSeconds),
            false,context.Progress,ct);
        VerifyManifest(staticCapture,id,s.Calibration);
        string selected=Path.Combine(staticCapture.Folder,"imu_selected.csv");
        if(!File.Exists(selected)||!File.Exists(staticCapture.CsvFile))throw new FileNotFoundException("CT-17静态时间基原始/校正CSV不完整");
        var batches=await Ct12aAlgorithm.ReadRealBatchMeansAsync(selected,staticCapture.CsvFile,ct);
        var staticTiming=Ct17Algorithm.AnalyzeStatic(batches,s);
        var afterStatic=await dynamicHw.ReadStageAsync(ct);
        VerifyStage(afterStatic,ct10Guard);

        string state="RUNNING",failure="";
        var sweeps=new List<Ct17SweepResult>();
        bool motionIssued=false;
        Exception? runError=null;
        string axisName(Ct10Axis a)=>a==Ct10Axis.Inner?"INNER":"OUTER";
        try
        {
            int total=((s.TestInner?1:0)+(s.TestOuter?1:0))*s.Repetitions*2;
            int idx=0;
            foreach(var axis in new[]{Ct10Axis.Inner,Ct10Axis.Outer}.Where(a=>a==Ct10Axis.Inner?s.TestInner:s.TestOuter))
            {
                int gyroSign=axis==Ct10Axis.Inner?s.InnerGyroSign:s.OuterGyroSign;
                foreach(int rep in Enumerable.Range(1,s.Repetitions))
                foreach(var direction in new[]{Ct10Direction.Forward,Ct10Direction.Reverse})
                {
                    ct.ThrowIfCancellationRequested();
                    VerifyHashes(s.Calibration);
                    if(host.CurrentIdentity?.UidHex!=id.UidHex||dynamicHw.CurrentUidHex!=id.UidHex)
                        throw new InvalidDataException("动态测试期间设备UID发生变化");
                    double startDeg=direction==Ct10Direction.Forward?s.CenterDeg-s.AmplitudeDeg:s.CenterDeg+s.AmplitudeDeg;
                    double endDeg=direction==Ct10Direction.Forward?s.CenterDeg+s.AmplitudeDeg:s.CenterDeg-s.AmplitudeDeg;
                    context.Progress?.Report($"CT-17 [{idx+1}/{total}] {axisName(axis)} {direction} R{rep}：安全定位到{startDeg:F2}°");
                    motionIssued=true;
                    await dynamicHw.MoveToSafeStartAsync(axis,startDeg,s.SetupSpeedDps,
                        s.ApprovedMinDeg,s.ApprovedMaxDeg,ct);
                    await Task.Delay(TimeSpan.FromSeconds(s.SettleSeconds),ct);
                    var ready=await dynamicHw.ReadStageAsync(ct);
                    VerifyStage(ready,ct10Guard);
                    double actual=axis==Ct10Axis.Inner?ready.InnerPositionDeg:ready.OuterPositionDeg;
                    if(Math.Abs(actual-startDeg)>0.5)throw new IOException("运动前起点反馈与目标位置不一致");
                    timing.Ct17PreMotionDwell=TimeSpan.FromSeconds(s.PreMotionDwellSeconds);
                    var request=new Ct10SweepRequest(axis,direction,rep,s.CommandSpeedDps,startDeg,endDeg,0,
                        s.ApprovedMinDeg,s.ApprovedMaxDeg,Math.Max(30,Math.Abs(endDeg-startDeg)/s.CommandSpeedDps*4+20));
                    Ct10Capture capture;
                    try{capture=await dynamicHw.ExecuteSynchronizedSweepAsync(request,context.Progress,ct);}
                    finally{timing.Ct17PreMotionDwell=TimeSpan.Zero;}
                    if(capture.TimestampFrequency!=timing.Ct17TimestampFrequency)
                        throw new InvalidDataException("动态采集与命令调用时标不是同一Stopwatch频率");
                    if(!capture.FullUidHex.Equals(id.UidHex,StringComparison.OrdinalIgnoreCase))
                        throw new InvalidDataException("动态采集返回UID与当前设备不一致");
                    VerifyHashes(s.Calibration);
                    long commandStart=timing.Ct17CommandCallStartTicks;
                    long commandReturn=timing.Ct17CommandCallReturnTicks;
                    string csv=Path.Combine(staticCapture.Folder,
                        $"sweep_{idx+1:D3}_{axisName(axis)}_{direction}_R{rep:D2}.csv");
                    var result=Ct17Algorithm.AnalyzeSweep(idx+1,axis,direction,rep,s.CommandSpeedDps,
                        startDeg,endDeg,gyroSign,capture,commandStart,commandReturn,
                        s.EncoderDerivativeWindowSeconds,s.MaxLagSearchMs,gyro.Apply,csv);
                    sweeps.Add(result);
                    await Ct17Report.WriteSweepCsvAsync(csv,result,ct);
                    idx++;
                    context.Progress?.Report($"CT-17 [{idx}/{total}] {axisName(axis)} {direction}：命令至编码器起动"+
                        $"{result.CommandToEncoderOnsetMs?.ToString("F1")??"N/A"}ms；编码器至Gyro响应"+
                        $"{result.EncoderToGyroOnsetMs?.ToString("F1")??"N/A"}ms；互相关时延"+
                        $"{result.CrossCorrelationLagMs?.ToString("F1")??"N/A"}ms");
                }
            }
            state="COMPLETED_PENDING_ACCEPTANCE";
            failure="";
        }
        catch(Exception ex)
        {
            runError=ex;
            state=ex is OperationCanceledException?"CANCELLED_PARTIAL":"FAILED_PARTIAL";
            failure=ex.Message;
        }
        finally
        {
            timing.Ct17PreMotionDwell=TimeSpan.Zero;
            if(motionIssued)
            {
                using var stop=new CancellationTokenSource(TimeSpan.FromSeconds(6));
                try{await dynamicHw.StopBothAxesAsync(stop.Token);}
                catch(Exception ex){state="STOP_NOT_CONFIRMED";failure+="；双轴软停车未确认："+ex.Message;}
            }
        }
        var snapshot=new Ct17SettingsSnapshot(s.StaticCaptureSeconds,s.ExpectedHostBatchHz,s.HostRateTolerancePercent,
            s.PreMotionDwellSeconds,s.SettleSeconds,s.TestInner,s.TestOuter,s.Repetitions,s.CenterDeg,s.AmplitudeDeg,
            s.CommandSpeedDps,s.SetupSpeedDps,s.ApprovedMinDeg,s.ApprovedMaxDeg,s.EncoderDerivativeWindowSeconds,
            s.MaxLagSearchMs,s.InnerGyroSign,s.OuterGyroSign);
        string conclusion=runError is null?
            $"完成静态时间基审核（{staticTiming.Batches}个完整FIFO批次）和{sweeps.Count}段真实小幅往复运动；结果为研发诊断，需结合时标不确定度评估。":
            $"已保留静态时间基采集及{sweeps.Count}段已完成动态运动数据；本次未完整完成："+runError.Message;
        var report=new Ct17ReportData(TestId,Name,id.DtsId,id.UidHex,started,DateTimeOffset.UtcNow,state,failure,snapshot,
            Path.GetFileName(acc.FilePath),acc.Sha256,Path.GetFileName(gyro.FilePath),gyro.Sha256,
            staticCapture.Folder,staticCapture.CsvFile,selected,staticCapture.ManifestFile,staticTiming,sweeps,conclusion,
            "静态部分：MCU仅提供批次级tick及每批16帧sample_index，没有跨批次逐帧全局序号；host_utc为整批主机接收时间，不是16帧各自的采样时刻。"+
            "动态部分：Gyro使用固件核验的FIFO最新槽位，时间戳为主机接收Stopwatch时标；编码器时间戳为主机读取区间中点。"+
            "命令时标是主机调用2TD运动接口的起止包络，不是控制器内部硬件触发时刻。命令到运动、编码器到Gyro的延迟均包含串口/Modbus轮询、FIFO排队、驱动和机械响应，属于端到端表观时延，不是传感器本征延迟或硬件同步认证。");
        var exported=await Ct17Report.ExportAsync(staticCapture.Folder,report,batches,CancellationToken.None);
        if(state=="STOP_NOT_CONFIRMED")throw new IOException("CT-17测试结束后双轴软停车未确认，请现场确认并使用实体急停。");
        if(runError is OperationCanceledException oce)ExceptionDispatchInfo.Capture(oce).Throw();
        if(runError is not null)throw new IOException("CT-17未完整完成，部分数据和诊断报告已保存："+runError.Message,runError);
        return new TestExecutionResult(TestId,TestOutcome.PendingAcceptance,
            $"CT-17完成：{staticTiming.Batches}批静态时基、{sweeps.Count}段动态往复；时延结果仅作工程诊断，不自动PASS。",
            staticCapture,exported);
    }
}
