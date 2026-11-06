using System.IO;
using System.Security.Cryptography;
using System.Text.Json;
using Dts.Core;
using Dts.TestEngine;
using Dts.Tests.S1.CT10;
using Dts.Tests.S1.CT11;

namespace Dts.Tests.S1;

/// <summary>CT-11: low-speed linearity and off-axis gyro response in real motion, no static-data substitution.</summary>
public sealed class CT_11_Test : TestModuleBase
{
    public override string TestId => "CT-11";
    public override bool IsExecutable => true;
    public override string Purpose => "GYRO三轴低速响应、非驱动轴耦合斜率和线性残差真实动态诊断";
    public override string Procedure => "UID与常温Gyro模型匹配→预置真实动态采集→多档低速正反旋转→三轴逐帧分析→回归斜率→图文报告";
    public override string Priority => "P0";
    public override string ImplementationNote => "共享CT-10真实动态采集接口，仅在已核验的实时数据条件下运行；不自动判PASS；只测被选定转台旋转轴。";

    public override async Task<TestExecutionResult> ExecuteAsync(TestExecutionContext context,CancellationToken ct)
    {
        if(context.Hardware is not IStaticAngleHardware host)
            throw new InvalidOperationException("CT-11需要真实双轴硬件对象");
        if(context.Parameters is not Ct11Settings s)
            throw new InvalidOperationException("CT-11缺少专用窗口参数");
        var live=Ct10DynamicBridge.Resolve(host);
        if(live is null || !live.IsRealDynamicCaptureReady)
            throw new NotSupportedException("CT-11依赖已核验的CT-10真实动态采集桥；当前设备尚未就绪，禁止实测");
        var id=host.CurrentIdentity ?? throw new InvalidOperationException("未读取IMU完整UID");
        if(!host.IsTwoTdConnected)throw new InvalidOperationException("2TD未连接/使能");
        if(!string.Equals(live.CurrentUidHex,id.UidHex,StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("动态采集源与主窗口IMU UID不一致");
        var calibration=s.Calibration;
        if(calibration.Mode!=CalibrationMode.Ambient)
            throw new InvalidOperationException("CT-11当前要求主窗口选择UID匹配的常温标定");
        calibration.Validate(id);
        var gyro=calibration.Files?.Gyro ?? throw new InvalidDataException("Gyro常温JSON缺失");
        var acc=calibration.Files?.Acc ?? throw new InvalidDataException("ACC常温JSON缺失");
        int gyroFs=gyro.FsHint ?? throw new InvalidDataException("Gyro历史拟合输入量程缺失");
        var plan=Ct11Algorithm.Plan(s,live); // includes safety confirmations & vendor-verified speed limit
        CheckHashes(calibration);
        await host.VerifyImuForPrecisionTestAsync(ct);
        var initial=await live.ReadStageAsync(ct);
        VerifyStage(initial,s,requireStationary:true);
        string root=Path.GetFullPath(s.OutputRoot);
        if(!Directory.Exists(root))throw new DirectoryNotFoundException("报告根目录不存在："+root);
        string directory=Path.Combine(root,id.DtsId+"_"+id.UidHex,
            DateTime.Now.ToString("yyyyMMdd_HHmmss_fff")+"_CT-11");
        Directory.CreateDirectory(directory);
        var sweeps=new List<Ct11SweepResult>();
        string started=DateTimeOffset.UtcNow.ToString("O"),state="RUNNING",failure="";
        string stopFailure="",reportFailure="";
        bool motionIssued=false;
        IReadOnlyList<string> files=[];
        var settings=new Ct11SettingsSnapshot(s.LowSpeedsCsv,s.TestInner,s.TestOuter,
            s.Repetitions,s.TravelMinDeg,s.TravelMaxDeg,s.ApprovedMinDeg,s.ApprovedMaxDeg,
            s.SetupSpeedDps,s.SettleSeconds,s.SpeedToleranceFraction,
            s.EncoderDerivativeWindowSeconds,s.MinAcceptedFrames,s.InnerGyroSign,s.OuterGyroSign);
        Ct11ReportData Snapshot()=>new("CT-11","GYRO轴间耦合与低速线性",id.DtsId,id.UidHex,
            started,DateTimeOffset.UtcNow.ToString("O"),state,failure,
            "仅研发诊断/待验收；未提供产品判据及同步不确定度预算，不自动判PASS",
            settings,Path.GetFileName(gyro.FilePath),gyro.Sha256,
            Path.GetFileName(acc.FilePath),acc.Sha256,live.HardwareSourceDescription,
            gyroFs,sweeps.ToArray(),Ct11Algorithm.Summarize(sweeps,s.InnerGyroSign,s.OuterGyroSign),
            "动态采集复用CT-10真实IMU FIFO与2TD实际编码器位置，使用同一进程Stopwatch主机时标；"+
            "该时标不等于硬件同步采样时刻。三轴耦合是装夹/转台/IMU共同构成的系统代理，"+
            "参考速度由转台编码器差分得出，不能用命令速率冒充真值。"+
            "量化、热漂、转台回差、机械振动及采样延迟对低速结果影响显著。"+
            "全程需现场监护并保证实体急停；软停车不是实体急停。失败及取消保留已有真实证据。" );
        try
        {
            await File.WriteAllTextAsync(Path.Combine(directory,"CT-11_calibration_identity.json"),
                JsonSerializer.Serialize(new {
                    id.DtsId,id.UidHex,
                    GyroFilePath=gyro.FilePath,GyroSha256=gyro.Sha256,GyroInputFs=gyroFs,
                    AccFilePath=acc.FilePath,AccSha256=acc.Sha256,
                    DynamicSource=live.HardwareSourceDescription,
                    Note="本文件只保存溯源，测试期间每段复核SHA256与UID"},
                    new JsonSerializerOptions{WriteIndented=true}),ct);
            for(int i=0;i<plan.Count;i++)
            {
                ct.ThrowIfCancellationRequested();CheckHashes(calibration);
                if(!string.Equals(live.CurrentUidHex,id.UidHex,StringComparison.OrdinalIgnoreCase))
                    throw new InvalidDataException("测试期间UID发生变化");
                var request=plan[i];
                context.Progress?.Report($"CT-11 [{i+1}/{plan.Count}] {request.Axis} " +
                    $"{request.CommandDps:F3}°/s {request.Direction}，预定位起点");
                motionIssued=true;
                await live.MoveToSafeStartAsync(request.Axis,request.StartDeg,
                    s.SetupSpeedDps,s.ApprovedMinDeg,s.ApprovedMaxDeg,ct);
                await Task.Delay(TimeSpan.FromSeconds(s.SettleSeconds),ct);
                var stage=await live.ReadStageAsync(ct);
                VerifyStage(stage,s,requireStationary:true);
                double position=request.Axis==Ct10Axis.Inner?stage.InnerPositionDeg:stage.OuterPositionDeg;
                double other=request.Axis==Ct10Axis.Inner?stage.OuterPositionDeg:stage.InnerPositionDeg;
                if(Math.Abs(position-request.StartDeg)>0.5 || Math.Abs(other)>0.5)
                    throw new IOException("真实转台未到达请求起点或固定轴不在0°");
                using var timed=CancellationTokenSource.CreateLinkedTokenSource(ct);
                timed.CancelAfter(TimeSpan.FromSeconds(request.SafetyTimeoutSeconds));
                Ct10Capture capture;
                try
                {
                    capture=await live.ExecuteSynchronizedSweepAsync(request,context.Progress,timed.Token);
                }
                catch(OperationCanceledException) when(!ct.IsCancellationRequested)
                {
                    throw new TimeoutException("CT-11该段真实动态扫描超时，正在请求软停车");
                }
                if(!string.Equals(capture.FullUidHex,id.UidHex,StringComparison.OrdinalIgnoreCase))
                    throw new InvalidDataException("真实采集源UID与设备UID不匹配");
                CheckHashes(calibration);
                string csv=Path.Combine(directory,$"sweep_{i+1:D3}_{request.Axis}_{request.CommandDps.ToString("0.###",System.Globalization.CultureInfo.InvariantCulture)}_{request.Direction}.csv");
                var analyzed=Ct10Algorithm.Analyze(request,capture,Ct11Algorithm.ToCt10Settings(s),
                    (x,y,z)=>gyro.Apply(x,y,z),gyroFs,csv);
                await Ct10Report.WriteSweepCsvAsync(csv,analyzed,ct);
                sweeps.Add(Ct11Algorithm.FromCt10Sweep(analyzed));
                await Ct11Report.SaveCheckpointAsync(directory,Snapshot(),ct);
                context.Progress?.Report($"CT-11 [{i+1}/{plan.Count}] 已采集{analyzed.AcceptedFrames}帧，"+
                    $"真实参考速率{analyzed.MeanReferenceSignedDps:F4}°/s，主轴残差{analyzed.MeanResidualDps:F5}°/s");
            }
            var fit=Ct11Algorithm.Summarize(sweeps,s.InnerGyroSign,s.OuterGyroSign);
            int expectedAxes=(s.TestInner?1:0)+(s.TestOuter?1:0);
            if(fit.Count!=expectedAxes)
                throw new InvalidDataException("有效速度/正反扫描未形成完整拟合，禁止标记完成");
            state="COMPLETED_PENDING_ACCEPTANCE";
            failure=$"完成{sweeps.Count}次真实动态扫描，{fit.Count}个轴完成低速回归和耦合估计";
        }
        catch(OperationCanceledException)
        {
            state="CANCELLED_PARTIAL";failure="用户取消，保留已完成真实动态扫描数据";throw;
        }
        catch(Exception ex)
        {
            state="FAILED_PARTIAL";failure=ex.Message;throw;
        }
        finally
        {
            if(motionIssued)
            {
                using var stopCts=new CancellationTokenSource(TimeSpan.FromSeconds(6));
                try {await live.StopBothAxesAsync(stopCts.Token);}
                catch(Exception ex)
                {
                    state="STOP_NOT_CONFIRMED";stopFailure=ex.Message;
                    failure+="；双轴软停车未确认："+stopFailure;
                    context.Progress?.Report("危险：软停车反馈未确认，必要时立即使用实体急停");
                }
            }
            try {files=await Ct11Report.ExportAsync(directory,Snapshot(),CancellationToken.None);}
            catch(Exception ex)
            {
                reportFailure=ex.Message;
                context.Progress?.Report("CT-11报告导出失败："+ex.Message);
            }
        }
        if(stopFailure.Length>0)throw new IOException("CT-11双轴软停车未确认："+stopFailure);
        if(reportFailure.Length>0)throw new IOException("CT-11完整报告保存失败："+reportFailure);
        var summaries=Ct11Algorithm.Summarize(sweeps,s.InnerGyroSign,s.OuterGyroSign);
        return new TestExecutionResult(TestId,TestOutcome.PendingAcceptance,
            $"CT-11真实动态扫描{sweeps.Count}段；"+
            string.Join("；",summaries.Select(x=>$"{x.DriveAxis}主轴增益偏差{x.MainGainErrorPercent:F3}%，"+
                $"最大轴间耦合{x.MaximumCrossAxisCouplingPercent:F3}%"))+"；待验收",null,files);
    }

    private static void VerifyStage(Ct10StageStatus s,Ct11Settings settings,bool requireStationary)
    {
        if(!s.InnerEnabled || !s.OuterEnabled || !s.InnerNormal || !s.OuterNormal ||
            (requireStationary && (!s.InnerStationary || !s.OuterStationary)) ||
            !double.IsFinite(s.InnerPositionDeg) || !double.IsFinite(s.OuterPositionDeg) ||
            s.InnerPositionDeg<settings.ApprovedMinDeg-0.3 || s.InnerPositionDeg>settings.ApprovedMaxDeg+0.3 ||
            s.OuterPositionDeg<settings.ApprovedMinDeg-0.3 || s.OuterPositionDeg>settings.ApprovedMaxDeg+0.3)
            throw new IOException("转台未使能、未静止或反馈越界："+s.Detail);
    }
    private static void CheckHashes(CalibrationRun run)
    {
        foreach(var f in run.Sources)
        {
            if(!File.Exists(f.FilePath) ||
               !Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(f.FilePath)))
                   .Equals(f.Sha256,StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("Gyro/ACC标定源文件在测试期间发生变化："+f.FilePath);
        }
    }
}
