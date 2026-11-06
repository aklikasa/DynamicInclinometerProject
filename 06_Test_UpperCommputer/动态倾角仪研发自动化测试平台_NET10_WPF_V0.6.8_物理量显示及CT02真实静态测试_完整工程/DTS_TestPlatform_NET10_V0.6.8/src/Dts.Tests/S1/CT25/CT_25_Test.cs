using System.IO;
using System.Security.Cryptography;
using System.Text.Json;
using Dts.Core;
using Dts.TestEngine;
using Dts.Tests.S1.CT25;

namespace Dts.Tests.S1;

/// <summary>
/// CT-25 is NOT a collection of stepwise static set-points. It requires a certified
/// true-sine trajectory and time-aligned real device fused tilt X/Y versus 2TD feedback.
/// Without that driver the window previews the plan and this test MUST NOT move anything.
/// </summary>
public sealed class CT_25_Test : TestModuleBase
{
    public override string TestId=>"CT-25";
    public override bool IsExecutable=>true;
    public override string Priority=>"P0";
    public override string Purpose=>"常温小幅低频真实正弦运动下整机动态倾角的幅值、相位、Bias、RMSE与回零基线";
    public override string Procedure=>"验证真实正弦控制及融合角同步接口→生成X/Y幅频计划→自动剔除超速/超加速度档位→逐档采集→正弦幅相拟合→报告";
    public override string ImplementationNote=>"当前V0.6.8缺少已认证正弦轨迹和设备融合倾角源；未接通ICt25DynamicTiltHardware时禁止自动运动；不生成PASS。";

    public override async Task<TestExecutionResult> ExecuteAsync(TestExecutionContext context,CancellationToken ct)
    {
        if(context.Hardware is not IStaticAngleHardware host)
            throw new NotSupportedException("CT-25需要实际IMU及双轴转台宿主接口");
        if(context.Parameters is not Ct25Settings s)
            throw new InvalidOperationException("CT-25必须通过独立窗口传入参数");
        var provider=Ct25DynamicBridge.Resolve(host);
        if(provider is null||!provider.IsReadyForTrueSineAndFusedTilt)
            throw new NotSupportedException("当前V0.6.8缺少已验收的真实正弦轨迹+同步设备融合倾角适配接口；仅允许预览计划，不允许启动运动");
        Ct25Algorithm.Validate(s,Ct25Algorithm.BuildPlan(s,provider));
        var plan=Ct25Algorithm.BuildPlan(s,provider);
        var selected=plan.Where(p=>p.Eligible).ToArray();
        if(selected.Length==0)throw new InvalidOperationException("全部组合超出认证速度/加速度/频率或行程，拒绝启动");
        var id=host.CurrentIdentity??throw new InvalidOperationException("尚未连接IMU或读取完整UID");
        if(!host.IsTwoTdConnected)throw new InvalidOperationException("真实双轴2TD未连接");
        if(!string.Equals(provider.CurrentUidHex,id.UidHex,StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("动态融合角适配器的UID与当前IMU不一致");
        var cal=s.Calibration;
        if(cal.Mode!=CalibrationMode.Ambient)throw new InvalidOperationException("请先在主窗口选择常温标定");
        cal.Validate(id);
        var acc=cal.Files?.Acc??throw new InvalidDataException("缺少常温ACC校准JSON");
        var gyro=cal.Files?.Gyro??throw new InvalidDataException("缺少常温Gyro校准JSON");
        VerifyCalibrationFiles(cal);
        await host.VerifyImuForPrecisionTestAsync(ct);
        string root=Path.GetFullPath(s.OutputRoot);
        if(!Directory.Exists(root))throw new DirectoryNotFoundException("报告根目录不存在："+root);
        string folder=Path.Combine(root,$"{id.DtsId}_{id.UidHex}",
            $"{DateTime.Now:yyyyMMdd_HHmmss_fff}_CT-25");
        Directory.CreateDirectory(folder);
        var results=new List<Ct25Result>();
        var started=DateTimeOffset.UtcNow.ToString("O");string state="RUNNING",error="";
        string stopError="",reportError="";
        IReadOnlyList<string> exported=[];
        bool motionRequested=false;
        var snapshot=new Ct25SettingsSnapshot(s.AmplitudesCsv,s.FrequenciesCsv,
            s.TestX,s.TestY,s.Cycles,s.Repeats,s.InnerCenterDeg,s.OuterCenterDeg,
            s.ApprovedMinDeg,s.ApprovedMaxDeg,s.SetupSpeedDps,s.SettleSeconds,
            s.RecoverySeconds,s.PhaseClockToleranceMs,s.MaximumGapSeconds,
            s.MinimumSteadyFrames,s.EncoderWaveformMinR2,s.AmplitudeToleranceFraction,
            s.AxisXSign,s.AxisYSign);
        Ct25ReportData Report()=>new("CT-25",state,error,id.UidHex,id.DtsId,started,
            DateTimeOffset.UtcNow.ToString("O"),provider.SourceDescription,
            Path.GetFileName(acc.FilePath),acc.Sha256,
            Path.GetFileName(gyro.FilePath),gyro.Sha256,
            "真实设备融合倾角必须由独立驱动提供，不能由ACC或Gyro离线代理。"+
            "同一经确认的时钟对齐后使用2TD实际编码器角拟合参考；每档须至少6完整稳态周期。"+
            "分析值是相对测试前静止基线的动态Bias、RMSE、幅值增益、相位和回零残差。"+
            "超速/超加速度/超频/超行程组合自动跳过并保留原因。"+
            "仍需机械校准与时间同步不确定度核验，不自动判定产品PASS；软件停车不替代实体急停。",
            snapshot,plan.ToArray(),results.ToArray());
        try
        {
            await File.WriteAllTextAsync(Path.Combine(folder,"CT-25_identity.json"),
                JsonSerializer.Serialize(new{
                    DeviceId=id.DtsId,DeviceUid=id.UidHex,
                    AccName=Path.GetFileName(acc.FilePath),AccSha256=acc.Sha256,
                    GyroName=Path.GetFileName(gyro.FilePath),GyroSha256=gyro.Sha256,
                    DeviceFusedTiltSource=provider.SourceDescription,
                    Note="融合倾角由设备独立提供；不把ACC/Gyro补偿值二次当成融合倾角"},
                    new JsonSerializerOptions{WriteIndented=true}),ct);
            await Ct25Report.SaveCheckpointAsync(folder,Report(),ct);
            for(int index=0;index<selected.Length;index++)
            {
                ct.ThrowIfCancellationRequested();
                VerifyCalibrationFiles(cal);
                if(!string.Equals(provider.CurrentUidHex,id.UidHex,StringComparison.OrdinalIgnoreCase))
                    throw new InvalidDataException("测试中融合源的设备完整UID改变");
                var p=selected[index];
                context.Progress?.Report($"CT-25 [{index+1}/{selected.Length}] {p.Axis} ±{p.AmplitudeDeg:F2}° / {p.FrequencyHz:F3}Hz / {p.Cycles}周期");
                double timeout=Math.Max(60,p.DurationSeconds*2+s.SettleSeconds+s.RecoverySeconds+90);
                var request=new Ct25SineRequest(p.Axis,p.CenterDeg,p.AmplitudeDeg,p.FrequencyHz,
                    p.Cycles,p.Repeat,s.SetupSpeedDps,s.SettleSeconds,s.RecoverySeconds,
                    s.ApprovedMinDeg,s.ApprovedMaxDeg,timeout);
                using var deadline=CancellationTokenSource.CreateLinkedTokenSource(ct);
                deadline.CancelAfter(TimeSpan.FromSeconds(timeout));
                motionRequested=true;
                Ct25Capture cap;
                try{cap=await provider.ExecuteTrueSineAsync(request,context.Progress,deadline.Token);}
                catch(OperationCanceledException) when(!ct.IsCancellationRequested)
                {throw new TimeoutException($"CT-25 正弦段#{p.Index}超过安全超时，需要停车");}
                if(!string.Equals(cap.FullUidHex,id.UidHex,StringComparison.OrdinalIgnoreCase))
                    throw new InvalidDataException("采集返回的完整UID与当前设备不一致");
                VerifyCalibrationFiles(cal);
                string frameCsv=Path.Combine(folder,$"sine_{p.Index:D3}_{p.Axis}_A{p.AmplitudeDeg.ToString("0.###",System.Globalization.CultureInfo.InvariantCulture)}_F{p.FrequencyHz.ToString("0.###",System.Globalization.CultureInfo.InvariantCulture)}.csv");
                // Preserve authentic raw aligned frames BEFORE potentially rejecting the analysis.
                await Ct25Report.SaveRawFramesAsync(frameCsv,cap,ct);
                var analyzed=Ct25Algorithm.Analyze(p,cap,s,frameCsv);
                results.Add(analyzed.Result);
                await Ct25Report.SaveCheckpointAsync(folder,Report(),ct);
                context.Progress?.Report($"CT-25 [{index+1}/{selected.Length}] 增益{analyzed.Result.Gain:F5}，相位{analyzed.Result.PhaseLagDegrees:F3}°，RMSE {analyzed.Result.DynamicRmseDeg:F4}°");
            }
            state="COMPLETED_PENDING_ACCEPTANCE";
            error=$"完成{results.Count}项真实正弦/融合倾角测量；尚无产品验收判据";
        }
        catch(OperationCanceledException){state="CANCELLED_PARTIAL";error="用户取消，保留已采集证据";throw;}
        catch(Exception ex){state="FAILED_PARTIAL";error=ex.Message;throw;}
        finally
        {
            if(motionRequested)
            {
                using var stopCts=new CancellationTokenSource(TimeSpan.FromSeconds(5));
                try{await provider.StopBothAxesAsync(stopCts.Token);}
                catch(Exception ex)
                {
                    stopError=ex.Message;state="STOP_NOT_CONFIRMED";
                    error+="；软件停车未确认："+stopError;
                    context.Progress?.Report("危险：软件停车未确认，现场确认并必要时使用实体急停！");
                }
            }
            try{exported=await Ct25Report.ExportAsync(folder,Report(),CancellationToken.None);}
            catch(Exception ex){reportError=ex.Message;context.Progress?.Report("CT-25报告导出失败："+ex.Message);}
        }
        if(stopError.Length!=0)throw new IOException("软件停车未确认："+stopError);
        if(reportError.Length!=0)throw new IOException("报告导出失败："+reportError);
        return new TestExecutionResult(TestId,TestOutcome.PendingAcceptance,
            $"CT-25完成{results.Count}项真实小幅正弦动态倾角基线，报告待验收，数据源{provider.SourceDescription}",
            null,exported);
    }
    private static void VerifyCalibrationFiles(CalibrationRun run)
    {
        foreach(var file in run.Sources)
        {
            if(!File.Exists(file.FilePath)||
                !Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(file.FilePath)))
                    .Equals(file.Sha256,StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("CT-25运行期间标定文件改变："+file.FilePath);
        }
    }
}
