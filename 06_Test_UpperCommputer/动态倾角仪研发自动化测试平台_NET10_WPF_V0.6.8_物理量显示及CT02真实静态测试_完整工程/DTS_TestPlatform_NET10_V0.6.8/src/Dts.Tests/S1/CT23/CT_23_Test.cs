using System.Globalization;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Dts.Core;
using Dts.TestEngine;
using Dts.Tests.S1.CT10;
using Dts.Tests.S1.CT23;

namespace Dts.Tests.S1;

/// <summary>
/// CT-23: stationary ACC gravity before/after REAL dynamic GYRO propagation.
/// Existing CT-10 bridge supports only zero other-axis angle; classify as single-axis
/// partial observability, NEVER as complete 3D ACC/GYRO alignment.
/// </summary>
public sealed class CT_23_Test : TestModuleBase
{
    public override string TestId=>"CT-23";
    public override bool IsExecutable=>true;
    public override string Priority=>"P0";
    public override string Purpose=>"倾斜初始姿态经实际旋转后，Gyro积分传播的重力方向与停车后ACC重力比较";
    public override string Procedure=>"多条非退化外轴轨迹：定位→静态ACC+零速Gyro→实时运动Gyro+2TD反馈→停车后静态ACC→重力方向闭合→图文报告";
    public override string ImplementationNote=>"使用CT-10已核验实时动态桥；当前另一轴保持0°，只能给出单驱动轴闭合诊断，不声称完整三维轴系对齐；绝不自动判PASS。";

    public override async Task<TestExecutionResult> ExecuteAsync(TestExecutionContext context,CancellationToken ct)
    {
        if(context.Parameters is not Ct23Settings s)throw new InvalidOperationException("CT-23缺少专属窗口设置快照");
        if(context.Hardware is not IStaticAngleHardware hw)throw new InvalidOperationException("需要真实IMU/2TD公共设备接口");
        var live=Ct10DynamicBridge.Resolve(hw);
        if(live is null||!live.IsRealDynamicCaptureReady)
            throw new NotSupportedException("必须先完成CT-10真实动态采集适配、FIFO时序和转台速度核验；无此条件不能自动旋转");
        var id=hw.CurrentIdentity??throw new InvalidOperationException("未连接真实IMU或没有读取完整UID");
        if(!hw.IsTwoTdConnected||!string.Equals(live.CurrentUidHex,id.UidHex,StringComparison.OrdinalIgnoreCase))
            throw new IOException("转台未连接或动态采集IMU与主窗口完整UID不一致");
        var cal=s.Calibration;
        if(cal.Mode!=CalibrationMode.Ambient)throw new InvalidOperationException("CT-23要求UID匹配的常温ACC和Gyro标定");
        cal.Validate(id);
        var acc=cal.Files?.Acc??throw new InvalidDataException("缺少匹配ACC JSON");
        var gyro=cal.Files?.Gyro??throw new InvalidDataException("缺少匹配Gyro JSON");
        int sign=ReadGravitySign(acc.FilePath);
        int gyroFs=gyro.FsHint??throw new InvalidDataException("Gyro JSON缺少历史输入量程");
        if(acc.FsHint is null || CalibrationInputScalePolicy.Resolve(acc.FsHint,gyroFs,0,0) is null)
            throw new InvalidDataException("ACC/Gyro历史标定的输入量程不可用");
        var plan=Ct23Algorithm.BuildPlan(s);Ct23Algorithm.Validate(s,plan,live);
        CheckHashes(cal);
        await hw.VerifyImuForPrecisionTestAsync(ct);
        var initial=await live.ReadStageAsync(ct);
        VerifyStage(initial,s,true);
        var root=Path.GetFullPath(s.OutputRoot);
        if(!Directory.Exists(root))throw new DirectoryNotFoundException("报告输出根目录不存在："+root);
        string folder=Path.Combine(root,id.DtsId+"_"+id.UidHex,
            DateTime.Now.ToString("yyyyMMdd_HHmmss_fff",CultureInfo.InvariantCulture)+"_CT-23");
        Directory.CreateDirectory(folder);
        var trials=new List<Ct23Trial>();string started=DateTimeOffset.UtcNow.ToString("O");
        string state="RUNNING",failure="",stopFailure="",reportFailure="";
        IReadOnlyList<string> reports=[];bool motionStarted=false;
        Ct23ReportData Snapshot()=>new("CT-23","ACC↔Gyro 六轴联合对齐",id.DtsId,id.UidHex,
            started,DateTimeOffset.UtcNow.ToString("O"),state,failure,
            "单轴动态重力闭合：工程诊断/待验收；不能宣称三维六轴完全对齐或PASS",
            sign,new Ct23SettingsSnapshot(s.TrajectoriesText,s.MotionSpeedDps,s.SetupSpeedDps,
                s.Repetitions,s.SettleSeconds,s.StaticCaptureSeconds,s.MinStaticFrames,
                s.MinDynamicFrames,s.MaxGyroGapSeconds,s.MaxStartEndClockSkewSeconds,
                s.AllowedMinDeg,s.AllowedMaxDeg,s.PositionToleranceDeg,
                s.MaxEncoderGyroAngleDiscrepancyDeg),
            Path.GetFileName(acc.FilePath),acc.Sha256,Path.GetFileName(gyro.FilePath),gyro.Sha256,
            "R=Rx(outer)Rz(inner)，取每次编码器真实反馈，outer驱动、inner=0°",
            live.HardwareSourceDescription,plan.ToArray(),trials.ToArray(),
            Ct23Algorithm.Summarize(trials),
            "CT-23原始清单要求多条非退化已知轴旋转+Gyro姿态传播+ACC重力闭合。"+
            "当前CT-10动态采集仅支持固定另一轴=0°，完成外轴旋转子项，但3D相对轴系中的某些自由度不可观测。"+
            "使用主机接收时间而非IMU硬件采样时间；无计量级同步保证。"+
            "回程误差混合IMU对齐、传感器校准、夹具、转台和时间延迟；不得直接当作纯传感器错轴角度。"+
            "所有转动必须由人员现场监护并配备实体急停，软停车无法替代实体急停。");
        try
        {
            await File.WriteAllTextAsync(Path.Combine(folder,"CT-23_calibration_identity.json"),
                JsonSerializer.Serialize(new {
                    DeviceNumber=id.DtsId,UidHex=id.UidHex,
                    AccPath=acc.FilePath,AccSha256=acc.Sha256,AccFs=acc.FsHint,
                    GyroPath=gyro.FilePath,GyroSha256=gyro.Sha256,GyroFs=gyroFs,
                    DynamicSource=live.HardwareSourceDescription,
                    Note="每次扫描校验完整UID、常温参数哈希和真实编码器运动"},
                    new JsonSerializerOptions{WriteIndented=true}),ct);
            for(int p=0;p<plan.Count;p++)
            {
                ct.ThrowIfCancellationRequested();CheckHashes(cal);
                if(!string.Equals(id.UidHex,live.CurrentUidHex,StringComparison.OrdinalIgnoreCase))
                    throw new InvalidDataException("运行中IMU UID发生变化，终止");
                var item=plan[p];
                context.Progress?.Report($"CT-23 [{p+1}/{plan.Count}] 准备外轴起点{item.OuterStartDeg:F2}°");
                motionStarted=true;
                await live.MoveToSafeStartAsync(Ct10Axis.Outer,item.OuterStartDeg,
                    s.SetupSpeedDps,s.AllowedMinDeg,s.AllowedMaxDeg,ct);
                await Task.Delay(TimeSpan.FromSeconds(s.SettleSeconds),ct);
                var before=await live.ReadStageAsync(ct);
                VerifyStage(before,s,true);
                VerifyPosition(before,item.OuterStartDeg,s);
                string beginCsv=Path.Combine(folder,$"trial_{item.Index:D3}_start_physical.csv");
                var startSamples=await hw.CaptureStaticPointAsync(beginCsv,TimeSpan.FromSeconds(s.StaticCaptureSeconds),
                    context.Progress,ct);
                var postStart=await live.ReadStageAsync(ct);
                VerifyStage(postStart,s,true);VerifyPosition(postStart,item.OuterStartDeg,s);
                if(Math.Abs(before.OuterPositionDeg-postStart.OuterPositionDeg)>s.PositionToleranceDeg)
                    throw new IOException("运动前静止采样期间转台偏移，拒绝使用");
                CheckHashes(cal);
                var g0=Ct23Algorithm.Unit(Ct23Algorithm.MeanCorrected(startSamples,s.MinStaticFrames,
                    v=>acc.Apply(v[0],v[1],v[2]),false));
                var gyroZero=Ct23Algorithm.MeanCorrected(startSamples,s.MinStaticFrames,
                    v=>gyro.Apply(v[0],v[1],v[2]),true);
                var expectedStart=Ct23Algorithm.Gravity(0,postStart.OuterPositionDeg,sign);
                double startError=Ct23Algorithm.Angle(g0,expectedStart);
                if(startError>25)throw new InvalidDataException("起始ACC重力与转台模型差距>25°；请检查装夹、轴映射和标定");
                var direction=item.OuterEndDeg>item.OuterStartDeg?Ct10Direction.Forward:Ct10Direction.Reverse;
                double timeout=Math.Min(900,Math.Max(45,Math.Abs(item.OuterEndDeg-item.OuterStartDeg)
                    /item.SpeedDps*2.7+45));
                var request=new Ct10SweepRequest(Ct10Axis.Outer,direction,item.Repetition,
                    item.SpeedDps,item.OuterStartDeg,item.OuterEndDeg,0,
                    s.AllowedMinDeg,s.AllowedMaxDeg,timeout);
                context.Progress?.Report($"CT-23 [{p+1}/{plan.Count}] 真实动态采集："+
                    $"外轴{item.OuterStartDeg:F1}°→{item.OuterEndDeg:F1}°，{item.SpeedDps:F2}°/s");
                using var timeoutCts=CancellationTokenSource.CreateLinkedTokenSource(ct);
                timeoutCts.CancelAfter(TimeSpan.FromSeconds(timeout+20));
                Ct10Capture motion;
                try {motion=await live.ExecuteSynchronizedSweepAsync(request,context.Progress,timeoutCts.Token);}
                catch(OperationCanceledException) when(!ct.IsCancellationRequested)
                {throw new TimeoutException("CT-23动态采集超时，已请求软停车");}
                string rawDynamic=Path.Combine(folder,$"trial_{item.Index:D3}_raw_dynamic_gyro.csv");
                string rawEncoder=Path.Combine(folder,$"trial_{item.Index:D3}_encoder.csv");
                await Ct23Report.SaveRawMotionAsync(rawDynamic,rawEncoder,motion,ct);
                if(!string.Equals(motion.FullUidHex,id.UidHex,StringComparison.OrdinalIgnoreCase))
                    throw new InvalidDataException("动态采集记录UID与真实设备不匹配");
                CheckHashes(cal);
                var integrated=Ct23Algorithm.Integrate(motion,g0,gyroZero,
                    v=>gyro.Apply(v[0],v[1],v[2]),gyroFs,item,s);
                double diff=integrated.IntegratedGyroDegrees[0]-(integrated.ActualEndDeg-integrated.ActualStartDeg);
                if(Math.Abs(diff)>s.MaxEncoderGyroAngleDiscrepancyDeg)
                    throw new InvalidDataException($"Gyro X轴累计角与编码器差{diff:F3}°超出安全映射阈值；拒绝轴向不确定数据");
                var afterStage=await live.ReadStageAsync(ct);
                VerifyStage(afterStage,s,true);VerifyPosition(afterStage,item.OuterEndDeg,s);
                await Task.Delay(TimeSpan.FromSeconds(s.SettleSeconds),ct);
                string endCsv=Path.Combine(folder,$"trial_{item.Index:D3}_end_physical.csv");
                var endSamples=await hw.CaptureStaticPointAsync(endCsv,
                    TimeSpan.FromSeconds(s.StaticCaptureSeconds),context.Progress,ct);
                var after=await live.ReadStageAsync(ct);
                VerifyStage(after,s,true);VerifyPosition(after,item.OuterEndDeg,s);
                if(Math.Abs(afterStage.OuterPositionDeg-after.OuterPositionDeg)>s.PositionToleranceDeg)
                    throw new IOException("停止后采样期间转台反馈发生移动");
                CheckHashes(cal);
                var g1=Ct23Algorithm.Unit(Ct23Algorithm.MeanCorrected(endSamples,s.MinStaticFrames,
                    v=>acc.Apply(v[0],v[1],v[2]),false));
                double endError=Ct23Algorithm.Angle(g1,Ct23Algorithm.Gravity(0,after.OuterPositionDeg,sign));
                double closure=Ct23Algorithm.Angle(g1,integrated.Predicted);
                string traceFile=Path.Combine(folder,$"trial_{item.Index:D3}_gyro_trace.csv");
                string encFile=rawEncoder;
                await Ct23Report.SaveDynamicEvidenceAsync(traceFile,integrated.Points,ct);
                var trial=new Ct23Trial(item.Index,item.TrajectoryIndex,item.Repetition,
                    item.OuterStartDeg,item.OuterEndDeg,integrated.ActualStartDeg,integrated.ActualEndDeg,
                    g0,g1,integrated.Predicted,expectedStart,
                    Ct23Algorithm.Gravity(0,after.OuterPositionDeg,sign),
                    closure,startError,endError,integrated.ActualEndDeg-integrated.ActualStartDeg,
                    integrated.IntegratedGyroDegrees[0],Ct23Algorithm.Norm(integrated.IntegratedGyroDegrees),
                    diff,integrated.ElapsedSeconds,integrated.MaxGapSeconds,
                    startSamples.Samples.Count,endSamples.Samples.Count,integrated.Points.Count,
                    integrated.Points.Average(x=>x.TemperatureC),
                    Ct23Algorithm.Angle(g0,new double[]{1d,0d,0d}),beginCsv,endCsv,traceFile,encFile,
                    motion.HardwareNotes,
                    "主机接收时钟Stopwatch统一时间基，非硬件同步；每批FIFO取经固件核验的真实最新槽位",rawDynamic);
                trials.Add(trial);
                await Ct23Report.SaveCheckpointAsync(folder,Snapshot(),ct);
                context.Progress?.Report($"CT-23 [{p+1}/{plan.Count}] 闭合误差{closure:F5}°，"+
                    $"Gyro X与编码器累计角差{diff:F5}°，真实动态帧{integrated.Points.Count}");
            }
            state="COMPLETED_SINGLE_AXIS_DIAGNOSTIC";
            failure=$"完成{trials.Count}条真实外轴运动-ACC闭合；完整三维六轴对齐未达到可观测条件";
        }
        catch(OperationCanceledException)
        {state="CANCELLED_PARTIAL";failure="用户取消，保留所有已完成证据";throw;}
        catch(Exception ex)
        {state="FAILED_PARTIAL";failure=ex.Message;throw;}
        finally
        {
            if(motionStarted)
            {
                using var stop=new CancellationTokenSource(TimeSpan.FromSeconds(8));
                try{await live.StopBothAxesAsync(stop.Token);}
                catch(Exception ex)
                {
                    stopFailure=ex.Message;state="STOP_NOT_CONFIRMED";
                    failure+="；软停车反馈未确认："+stopFailure;
                    context.Progress?.Report("危险：双轴软停车未确认，必要时立即使用实体急停");
                }
            }
            try{reports=await Ct23Report.ExportAsync(folder,Snapshot(),CancellationToken.None);}
            catch(Exception ex)
            {reportFailure=ex.Message;context.Progress?.Report("CT-23报告保存失败："+ex.Message);}
        }
        if(stopFailure.Length>0)throw new IOException("CT-23软停车失败："+stopFailure);
        if(reportFailure.Length>0)throw new IOException("CT-23报告导出失败："+reportFailure);
        var summary=Ct23Algorithm.Summarize(trials)??throw new InvalidDataException("没有形成有效的闭合轨迹");
        return new TestExecutionResult(TestId,TestOutcome.DiagnosticOnly,
            $"外轴多轨迹ACC↔Gyro重力闭合完成{summary.CompletedTrials}次；"+
            $"闭合RMS={summary.ClosureRmsDeg:F5}°，最大={summary.ClosureMaxDeg:F5}°；"+
            "完整三维六轴对齐不可观测，研发诊断，不判PASS。",null,reports);
    }
    private static int ReadGravitySign(string file)
    {
        using var doc=JsonDocument.Parse(File.ReadAllText(file));var obj=doc.RootElement;
        if(!obj.TryGetProperty("axis_model",out var axis)||axis.GetString()!="outer_x_inner_z" ||
           !obj.TryGetProperty("gravity_sign",out var sign)||!sign.TryGetInt32(out int n)||n is not (1 or -1))
            throw new InvalidDataException("当前常温ACC JSON缺少匹配的outer_x_inner_z轴模型和gravity_sign±1");
        return n;
    }
    private static void CheckHashes(CalibrationRun run)
    {
        foreach(var file in run.Sources)
            if(!File.Exists(file.FilePath)||
               !Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(file.FilePath)))
                   .Equals(file.Sha256,StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("运行期间UID标定文件被修改或丢失："+file.FilePath);
    }
    private static void VerifyStage(Ct10StageStatus f,Ct23Settings s,bool stationary)
    {
        if(!f.InnerEnabled||!f.OuterEnabled||!f.InnerNormal||!f.OuterNormal||
           (stationary&&(!f.InnerStationary||!f.OuterStationary))||
           !double.IsFinite(f.InnerPositionDeg)||!double.IsFinite(f.OuterPositionDeg)||
           f.InnerPositionDeg<s.AllowedMinDeg-0.3||f.InnerPositionDeg>s.AllowedMaxDeg+0.3||
           f.OuterPositionDeg<s.AllowedMinDeg-0.3||f.OuterPositionDeg>s.AllowedMaxDeg+0.3)
            throw new IOException("转台状态异常、失能或越过批准行程："+f.Detail);
    }
    private static void VerifyPosition(Ct10StageStatus f,double outerDeg,Ct23Settings s)
    {
        if(Math.Abs(f.InnerPositionDeg)>s.PositionToleranceDeg+0.15||
           Math.Abs(f.OuterPositionDeg-outerDeg)>s.PositionToleranceDeg+0.15)
            throw new IOException("外轴未实际到目标角或内轴未保持0°，拒绝采样");
    }
}
