using System.IO;
using System.Security.Cryptography;
using System.Text.Json;
using Dts.Core;
using Dts.TestEngine;
using Dts.Tests.S1.CT22;

namespace Dts.Tests.S1;

/// <summary>CT-22 long stationary unfused Gyro integration, batch-level MCU time audit.</summary>
public sealed class CT_22_Test : TestModuleBase
{
    public override string TestId=>"CT-22";
    public override bool IsExecutable=>true;
    public override bool RequiresStaticBench=>true;
    public override string Priority=>"P1";
    public override string Purpose=>"验证真实Gyro在静止10/30分钟时未融合积分漂移和每分钟漂移斜率";
    public override string Procedure=>"静止确认→真实FIFO连续采集→UID/校准/帧序列/时标核验→使用MCU批次真实Δt积分→报告";
    public override string ImplementationNote=>"无逐帧独立时间戳，仅16帧批均值与真实MCU批次时间差的工程诊断；不自动判PASS";

    private static void VerifyHashes(CalibrationRun run)
    {
        foreach(var src in run.Sources)
            if(!File.Exists(src.FilePath)||
               !Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(src.FilePath)))
                   .Equals(src.Sha256,StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("校准文件缺失/内容哈希变化："+src.FilePath);
    }
    private static JsonDocument VerifyManifest(CaptureArtifacts capture,DeviceIdentity id,CalibrationRun run)
    {
        var doc=JsonDocument.Parse(File.ReadAllText(capture.ManifestFile));
        try
        {
            var m=doc.RootElement;
            string Get(string name)=>m.GetProperty(name).GetString()??"";
            if(Get("hardware_mode")!="REAL_MCU_HARDWARE"||Get("test_id")!="CT-22"||
               Get("result_status")!="COMPLETED"||Get("processing_mode")!="AMBIENT")
                throw new InvalidDataException("不是完整真实常温Gyro采集记录");
            if(!Get("uid_raw_12_bytes").Equals(id.UidHex,StringComparison.OrdinalIgnoreCase)||
               Get("device_dts_id")!=id.DtsId)
                throw new InvalidDataException("真实采集完整UID或设备编号与启动时不一致");
            var hashes=m.GetProperty("calibration_files").EnumerateArray()
                .Select(x=>x.GetProperty("sha256").GetString()??"")
                .ToHashSet(StringComparer.OrdinalIgnoreCase);
            if(hashes.Count!=2||!hashes.SetEquals(run.Sources.Select(x=>x.Sha256)))
                throw new InvalidDataException("采集manifest中的两份标定哈希不是本次指定的UID文件");
            if(m.GetProperty("samples").GetInt32()!=capture.Samples)
                throw new InvalidDataException("manifest与真实采集对象帧数不一致");
            return doc;
        }
        catch {doc.Dispose();throw;}
    }
    private static async Task CheckStationaryAsync(ITestHardware hardware,CancellationToken ct)
    {
        if(hardware is not IStaticAngleHardware table||!table.IsTwoTdConnected)return;
        var f=await table.ReadTwoTdAsync(ct);
        if(!f.Inner.Normal||!f.Outer.Normal||
            !double.IsFinite(f.Inner.SpeedDps)||!double.IsFinite(f.Outer.SpeedDps)||
            Math.Abs(f.Inner.SpeedDps)>0.05||Math.Abs(f.Outer.SpeedDps)>0.05)
            throw new InvalidOperationException("连接的2TD转台当前未静止；CT-22不发送任何转台运动命令");
    }
    public override async Task<TestExecutionResult> ExecuteAsync(TestExecutionContext context,CancellationToken ct)
    {
        if(context.Parameters is not Ct22Settings settings)
            throw new InvalidOperationException("CT-22未从独立窗口接收到积分测试参数");
        Ct22Algorithm.Validate(settings);
        var identity=context.Hardware.CurrentIdentity
            ??throw new InvalidOperationException("真实IMU未连接，或没有读取完整UID");
        var run=settings.Calibration;
        if(run.Mode!=CalibrationMode.Ambient)
            throw new InvalidOperationException("CT-22要求主窗口选用常温标定，不支持把原始计数冒充已补偿Gyro");
        run.Validate(identity);
        var gyro=run.Files?.Gyro??throw new InvalidDataException("缺少UID匹配Gyro JSON");
        var acc=run.Files?.Acc??throw new InvalidDataException("缺少UID匹配ACC JSON");
        if(gyro.FsHint is null||acc.FsHint is null||
           CalibrationInputScalePolicy.Resolve(acc.FsHint,gyro.FsHint,0,0) is null)
            throw new InvalidDataException("匹配标定JSON没有可确认的历史物理量输入量程");
        VerifyHashes(run);
        if(!Directory.Exists(settings.ReportRoot))
            throw new DirectoryNotFoundException("报告根目录不存在："+settings.ReportRoot);
        await CheckStationaryAsync(context.Hardware,ct);
        context.Progress?.Report($"CT-22真实静态Gyro采集：{settings.DurationMinutes:F2}分钟；不执行任何转台运动");
        // Long capture streams raw signed int16 and ambient-calibrated physical data to disk.
        CaptureArtifacts capture=await context.Hardware.CaptureStaticImuAsync(TestId,
            TimeSpan.FromMinutes(settings.DurationMinutes),false,context.Progress,ct);
        string selected=Path.Combine(capture.Folder,"imu_selected.csv");
        string reportFolder=Path.Combine(Path.GetFullPath(settings.ReportRoot),
            identity.DtsId+"_"+identity.UidHex,Path.GetFileName(capture.Folder)+"_CT22Report");
        Directory.CreateDirectory(reportFolder);
        string state="ANALYSIS_INCOMPLETE",reason="",started="",ended="";
        Ct22Analysis? analysis=null;
        try
        {
            VerifyHashes(run);
            if(context.Hardware.CurrentIdentity?.UidHex!=identity.UidHex)
                throw new InvalidDataException("记录期间IMU完整UID改变");
            using var manifest=VerifyManifest(capture,identity,run);
            var m=manifest.RootElement;
            started=m.GetProperty("started_utc").GetString()??"";
            ended=m.GetProperty("ended_utc").GetString()??"";
            await CheckStationaryAsync(context.Hardware,ct);
            var batches=await Ct22Algorithm.ReadRealBatchMeansAsync(selected,capture.CsvFile,ct);
            analysis=Ct22Algorithm.Analyze(batches,settings,capture.Samples,
                m.GetProperty("skipped_duplicates").GetInt32(),
                m.GetProperty("sensor_unverified_batches").GetInt32());
            state=analysis.MetricsReleased?"ENGINEERING_DRIFT_PENDING_ACCEPTANCE":
                "TIMEBASE_OR_STATIONARITY_UNQUALIFIED";
            reason=analysis.TimeQuality.Warnings.Count==0?"":
                string.Join("；",analysis.TimeQuality.Warnings);
        }
        catch(OperationCanceledException){throw;}
        catch(Exception ex)
        {
            state="ANALYSIS_REJECTED";reason=ex.Message;
            context.Progress?.Report("CT-22时标/数据来源校验失败，仍保存真实原始记录与原因："+ex.Message);
        }
        var report=new Ct22ReportData("CT-22","Gyro 静止积分漂移","S1",identity.DtsId,identity.UidHex,
            state,reason,started,ended,
            new Ct22SettingsSnapshot(settings.DurationMinutes,settings.MinimumBatches,
                settings.MaxHostJitterPercent,settings.MaxMcuJitterPercent,
                settings.MaxFifoSpanErrorPercent,settings.MaxHostMcuSpanMismatchPercent,
                settings.MaxTemperatureRangeC,settings.MaxAccDirectionChangeDeg,
                settings.PlotIntervalSeconds,settings.StationaryConfirmed,
                settings.ThermalEnvironmentConfirmed,settings.TimebaseLimitAccepted),
            Path.GetFileName(acc.FilePath),acc.Sha256,Path.GetFileName(gyro.FilePath),gyro.Sha256,
            capture.Folder,capture.CsvFile,selected,capture.ManifestFile,analysis,
            "研发工程诊断，不自动判PASS；10/30分钟指标需要真实时间跨度覆盖对应检查点",
            "这是补偿后的三轴Gyro未融合积分角度，不是设备的融合倾角或外部精密角度真值。"+
            "原始FIFO没有逐帧时间戳，只能按真实MCU 16帧批次时间差对批均值积分；"+
            "不能借助本测试调整/抵消本次采样均值，否则会隐藏真实漂移。"+
            "转台未连接时静止由现场人员负责，连接转台时只检查前后运动反馈，不能证明全程无振动。"+
            "原始采集CSV、校正CSV、manifest和标定快照在采集目录，图文报告另行归档。");
        var reportFiles=await Ct22Report.ExportAsync(reportFolder,report,CancellationToken.None);
        var files=new List<string>{capture.CsvFile,selected,capture.ManifestFile};
        files.AddRange(reportFiles);
        string summary=analysis is null?"真实数据已采集，但时标/数据质量分析失败，禁止发布漂移结果":
            analysis.MetricsReleased?
            $"真实FIFO {capture.Samples}帧；MCU实际积分{analysis.TimeQuality.McuDurationSeconds/60:F3}分钟，"+
            $"三轴末端漂移模长{analysis.FinalVectorMagnitudeDeg:F5}°；工程诊断，待验收":
            $"真实FIFO {capture.Samples}帧；存在时间/静止质量问题，不发布漂移指标，已保留报告";
        context.Progress?.Report("CT-22："+summary);
        return new TestExecutionResult(TestId,TestOutcome.DiagnosticOnly,summary,capture,files);
    }
}
