using System.IO;
using System.Security.Cryptography;
using System.Text.Json;
using Dts.Core;
using Dts.TestEngine;
using Dts.Tests.S1.CT12A;

namespace Dts.Tests.S1;

/// <summary>CT-12A continuous stationary real FIFO recording with audited batch-time Allan proxy.</summary>
public sealed class CT_12A_Test : TestModuleBase
{
    public override string TestId=>"CT-12A";
    public override bool IsExecutable=>true;
    public override bool RequiresStaticBench=>true;
    public override string Priority=>"P1";
    public override string Purpose=>"对常温静止Gyro X/Y/Z进行Allan方差、随机稳定性、时标质量与FIFO连续性诊断";
    public override string Procedure=>"静置确认→持续真实FIFO采集→逐帧来源核验→批次连续性/时标审核→重叠Allan曲线→报告";
    public override string ImplementationNote=>"主机批次时标无逐帧精确时间戳；不通过连续性检查时只存真实数据与质量报告，不发布噪声系数或PASS";

    private static void ValidateHashes(CalibrationRun run)
    {
        foreach(var source in run.Sources)
        {
            if(!File.Exists(source.FilePath)||
               !Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(source.FilePath)))
                .Equals(source.Sha256,StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("标定文件缺失或SHA256发生变化："+source.FilePath);
        }
    }
    private static void ValidateManifest(string manifestPath,CalibrationRun run,DeviceIdentity id,
        CaptureArtifacts capture)
    {
        using var document=JsonDocument.Parse(File.ReadAllText(manifestPath));
        var root=document.RootElement;
        string Get(string name)=>root.GetProperty(name).GetString()??"";
        if(Get("hardware_mode")!="REAL_MCU_HARDWARE"||Get("test_id")!="CT-12A"||
           Get("result_status")!="COMPLETED"||Get("processing_mode")!="AMBIENT")
            throw new InvalidDataException("采集清单显示非真实、非完整或非常温模式数据");
        if(!Get("uid_raw_12_bytes").Equals(id.UidHex,StringComparison.OrdinalIgnoreCase)||
           Get("device_dts_id")!=id.DtsId)
            throw new InvalidDataException("真实采集清单的完整UID与本次测试不一致");
        var hashes=root.GetProperty("calibration_files").EnumerateArray()
            .Select(x=>x.GetProperty("sha256").GetString()??"")
            .ToHashSet(StringComparer.OrdinalIgnoreCase);
        if(hashes.Count!=2||!hashes.SetEquals(run.Sources.Select(x=>x.Sha256)))
            throw new InvalidDataException("采集期间使用的校准JSON与本次冻结源不一致");
        if(root.GetProperty("samples").GetInt32()!=capture.Samples)
            throw new InvalidDataException("采集manifest记录帧数与CaptureArtifacts不匹配");
    }

    public override async Task<TestExecutionResult> ExecuteAsync(TestExecutionContext context,CancellationToken ct)
    {
        if(context.Parameters is not Ct12aSettings s)
            throw new InvalidOperationException("CT-12A需要专属窗口的Allan参数快照");
        Ct12aAlgorithm.Validate(s);
        var id=context.Hardware.CurrentIdentity??throw new InvalidOperationException("真实IMU未连接或尚未获取UID");
        var run=s.Calibration;
        if(run.Mode!=CalibrationMode.Ambient)
            throw new InvalidOperationException("CT-12A当前要求主窗口选择常温补偿，不支持把原始值冒充已校正Gyro");
        run.Validate(id);
        var acc=run.Files?.Acc??throw new InvalidDataException("缺少UID匹配ACC常温JSON");
        var gyro=run.Files?.Gyro??throw new InvalidDataException("缺少UID匹配Gyro常温JSON");
        if(acc.FsHint is null||gyro.FsHint is null||
           CalibrationInputScalePolicy.Resolve(acc.FsHint,gyro.FsHint,0,0) is null)
            throw new InvalidDataException("历史标定输入量程无法判定，禁止计算Gyro Allan");
        ValidateHashes(run);
        if(!Directory.Exists(s.ReportRoot))
            throw new DirectoryNotFoundException("报告根目录不存在："+s.ReportRoot);
        // No table movement is needed. If a live 2TD exists, verify both axes are static.
        if(context.Hardware is IStaticAngleHardware table && table.IsTwoTdConnected)
        {
            var feedback=await table.ReadTwoTdAsync(ct);
            if(!feedback.Inner.Normal||!feedback.Outer.Normal||
               Math.Abs(feedback.Inner.SpeedDps)>0.05||Math.Abs(feedback.Outer.SpeedDps)>0.05)
                throw new InvalidOperationException("转台未静止，拒绝Allan稳定性采集；本测试不发送运动指令");
        }
        context.Progress?.Report($"CT-12A 开始真实连续采集 {s.DurationMinutes:F1}分钟，测试不会发送任何转台移动命令");
        // Existing platform capture is streamed to disk (not full FIFO in RAM) and freezes UID JSON snapshots.
        CaptureArtifacts capture=await context.Hardware.CaptureStaticImuAsync(TestId,
            TimeSpan.FromMinutes(s.DurationMinutes),false,context.Progress,ct);
        string selected=Path.Combine(capture.Folder,"imu_selected.csv");
        string reportFolder=Path.Combine(Path.GetFullPath(s.ReportRoot),
            id.DtsId+"_"+id.UidHex,Path.GetFileName(capture.Folder)+"_AllanReport");
        Directory.CreateDirectory(reportFolder);
        string state="ANALYSIS_INCOMPLETE",error="";
        string startedUtc="",finishedUtc="";
        Ct12aAnalysis? analysis=null;
        try
        {
            ValidateHashes(run);
            if(context.Hardware.CurrentIdentity?.UidHex!=id.UidHex)
                throw new InvalidDataException("采集结束时IMU UID已经改变");
            ValidateManifest(capture.ManifestFile,run,id,capture);
            using var manifestDoc=JsonDocument.Parse(File.ReadAllText(capture.ManifestFile));
            var manifest=manifestDoc.RootElement;
            startedUtc=manifest.GetProperty("started_utc").GetString()??"";
            finishedUtc=manifest.GetProperty("ended_utc").GetString()??"";
            if(context.Hardware is IStaticAngleHardware checkTable && checkTable.IsTwoTdConnected)
            {
                var finalState=await checkTable.ReadTwoTdAsync(ct);
                if(!finalState.Inner.Normal||!finalState.Outer.Normal||
                   Math.Abs(finalState.Inner.SpeedDps)>0.05||Math.Abs(finalState.Outer.SpeedDps)>0.05)
                    throw new InvalidDataException("采集结束检查发现转台仍有运动，无法作为静态Allan");
            }
            var batches=await Ct12aAlgorithm.ReadRealBatchMeansAsync(selected,capture.CsvFile,ct);
            analysis=Ct12aAlgorithm.Analyze(batches,s,capture.Samples,
                manifest.GetProperty("skipped_duplicates").GetInt32(),
                manifest.GetProperty("sensor_unverified_batches").GetInt32());
            state=analysis.CoefficientsReleased?"ENGINEERING_ALLAN_UNCERTIFIED":
                analysis.TimeQuality.ContinuousSequenceQualified?
                    "TAU_COVERAGE_INSUFFICIENT":"TIMEBASE_UNQUALIFIED";
            error=analysis.TimeQuality.Warnings.Count>0?
                string.Join("；",analysis.TimeQuality.Warnings):"";
        }
        catch(OperationCanceledException){throw;}
        catch(Exception ex)
        {
            state="ANALYSIS_REJECTED";error=ex.Message;
            context.Progress?.Report("CT-12A数据质量核验未通过，保存真实原始记录并出具错误报告："+ex.Message);
        }
        var report=new Ct12aReportData("CT-12A","Allan方差/随机稳定性表征","S1",id.DtsId,id.UidHex,
            state,error,startedUtc,finishedUtc,
            new Ct12aSettingsSnapshot(s.DurationMinutes,s.TauMinSeconds,s.TauMaxSeconds,
                s.PointsPerDecade,s.MaxHostCadenceJitterPercent,s.MaxMcuCadenceJitterPercent,
                s.MaxFifoSpanErrorPercent,s.MaxTemperatureRangeC,s.MinimumBatches,s.StationaryConfirmed,
                s.ThermalEnvironmentConfirmed,s.TimebaseLimitAccepted),
            Path.GetFileName(acc.FilePath),acc.Sha256,Path.GetFileName(gyro.FilePath),gyro.Sha256,
            capture.Folder,capture.CsvFile,selected,capture.ManifestFile,analysis,
            "研发工程诊断，不自动判PASS；时标/连续性异常时噪声指标无资格发布",
            "MCU只给16帧数据包的时标和ODR，无逐帧硬件时间戳；"+
            "通过连续性检查也仅是工程代理Allan，不能作为硬件同步计量级Allan或产品规格结论。"+
            "静止条件由现场人员确认，程序仅在转台连接时检查采集前后的静止反馈，不能证明全程无外部振动。"+
            "采集在系统指定的原始采集根目录保存，报告在此模块所选的报告根目录输出。");
        var reportFiles=await Ct12aReport.ExportAsync(reportFolder,report,CancellationToken.None);
        // Keep files of the raw evidence together with report handles; do not duplicate GB-scale CSV.
        var files=new List<string>{capture.CsvFile,selected,capture.ManifestFile};
        files.AddRange(reportFiles);
        string message=analysis is null?"真实采集完成，Allan数据质量核验失败，请查看报告原因":
            analysis.CoefficientsReleased?
            $"真实采集{capture.Samples}帧，完成工程级批次Allan曲线{analysis.Curves.Count}点；没有逐帧同步证明，待验收":
            $"真实采集{capture.Samples}帧，时标连续性/τ覆盖未达发布条件，已保存质量报告并拒绝发布噪声系数";
        context.Progress?.Report("CT-12A："+message);
        return new TestExecutionResult(TestId,TestOutcome.DiagnosticOnly,message,capture,files);
    }
}
