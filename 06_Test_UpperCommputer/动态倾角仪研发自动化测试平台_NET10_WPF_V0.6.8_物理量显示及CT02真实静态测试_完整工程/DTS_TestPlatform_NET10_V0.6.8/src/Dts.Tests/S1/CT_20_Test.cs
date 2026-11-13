
using System.Security.Cryptography;
using System.Text.Json;
using Dts.Core;
using Dts.TestEngine;
using Dts.Tests.S1.CT12A;
using Dts.Tests.S1.CT20;
namespace Dts.Tests.S1;
public sealed class CT_20_Test : TestModuleBase
{
    public override string TestId => "CT-20";
    public override bool IsExecutable => true;
    public override string Name=>"Gyro冷启动预热零偏稳定性";
    public override string Purpose=>"在PCB冷启动后连续静止采集真实Gyro数据，量化XYZ零偏、短期离散、漂移率、温度变化及达到稳定判据所需时间";
    public override string Procedure=>"人工断电冷却→重新上电并连接→核验UID/常温JSON→静止连续FIFO采集→批次/帧来源审核→分窗均值/STD/漂移率→稳定时间报告";
    public override string Priority=>"P0";
    public override string ImplementationNote=>"供电由操作员手动拔插USB/电源；本模块不控制电源、不移动转台、不把批次主机时间戳冒充逐帧硬件时戳；仅输出工程诊断，不自动PASS。";
    private static void Hashes(CalibrationRun run)
    {
        foreach(var f in run.Sources)
            if(!File.Exists(f.FilePath)||!Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(f.FilePath))).Equals(f.Sha256,StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("常温标定文件缺失或SHA256变化："+f.FilePath);
    }
    private static void Manifest(string file,DeviceIdentity id,CalibrationRun run,CaptureArtifacts c)
    {
        using var d=JsonDocument.Parse(File.ReadAllText(file));var r=d.RootElement;
        string G(string n)=>r.GetProperty(n).GetString()??"";
        if(G("hardware_mode")!="REAL_MCU_HARDWARE"||G("test_id")!="CT-20"||G("result_status")!="COMPLETED"||G("processing_mode")!="AMBIENT")
            throw new InvalidDataException("manifest不是完整真实硬件常温采集");
        if(!G("uid_raw_12_bytes").Equals(id.UidHex,StringComparison.OrdinalIgnoreCase)||G("device_dts_id")!=id.DtsId)
            throw new InvalidDataException("manifest设备身份与本次UID不一致");
        var hashes=r.GetProperty("calibration_files").EnumerateArray().Select(x=>x.GetProperty("sha256").GetString()??"").ToHashSet(StringComparer.OrdinalIgnoreCase);
        if(hashes.Count!=2||!hashes.SetEquals(run.Sources.Select(x=>x.Sha256)))throw new InvalidDataException("manifest标定哈希与冻结标定源不一致");
        if(r.GetProperty("samples").GetInt32()!=c.Samples)throw new InvalidDataException("manifest帧数与采集结果不一致");
    }
    public override async Task<TestExecutionResult> ExecuteAsync(TestExecutionContext context,CancellationToken ct)
    {
        if(context.Parameters is not Ct20Settings s)throw new InvalidOperationException("CT-20缺少窗口参数");
        Ct20Algorithm.Validate(s);
        var id=context.Hardware.CurrentIdentity??throw new InvalidOperationException("IMU未连接或UID不可用");
        if(s.Calibration.Mode!=CalibrationMode.Ambient)throw new InvalidOperationException("CT-20只允许使用当前设备匹配的常温ACC/Gyro标定");
        s.Calibration.Validate(id);
        var acc=s.Calibration.Files?.Acc??throw new InvalidDataException("缺少UID匹配ACC常温JSON");
        var gyro=s.Calibration.Files?.Gyro??throw new InvalidDataException("缺少UID匹配Gyro常温JSON");
        if(acc.FsHint is null||gyro.FsHint is null||CalibrationInputScalePolicy.Resolve(acc.FsHint,gyro.FsHint,0,0) is null)
            throw new InvalidDataException("标定输入量程不可判定，拒绝分析");
        Hashes(s.Calibration);
        if(!Directory.Exists(s.ReportRoot))throw new DirectoryNotFoundException("报告根目录不存在："+s.ReportRoot);
        if(context.Hardware is IStaticAngleHardware table&&table.IsTwoTdConnected)
        {
            var f=await table.ReadTwoTdAsync(ct);
            if(!f.Inner.Normal||!f.Outer.Normal||Math.Abs(f.Inner.SpeedDps)>0.05||Math.Abs(f.Outer.SpeedDps)>0.05)
                throw new InvalidOperationException("转台未静止；CT-20不发送运动指令");
        }
        if(context.Hardware is IStaticAngleHardware precision) await precision.VerifyImuForPrecisionTestAsync(ct);
        var started=DateTimeOffset.UtcNow;
        context.Progress?.Report($"CT-20开始真实冷启动后静止采集，计划{s.DurationMinutes:F1}分钟；本模块不控制供电和转台");
        var capture=await context.Hardware.CaptureStaticImuAsync(TestId,TimeSpan.FromMinutes(s.DurationMinutes),false,context.Progress,ct);
        string folder=Path.Combine(Path.GetFullPath(s.ReportRoot),id.DtsId+"_"+id.UidHex,Path.GetFileName(capture.Folder)+"_CT20");
        Directory.CreateDirectory(folder);
        string state="ANALYSIS_REJECTED",error="";Ct20Analysis? analysis=null;
        try
        {
            Hashes(s.Calibration);
            if(context.Hardware.CurrentIdentity?.UidHex!=id.UidHex)throw new InvalidDataException("采集期间UID发生变化");
            Manifest(capture.ManifestFile,id,s.Calibration,capture);
            using var md=JsonDocument.Parse(File.ReadAllText(capture.ManifestFile));
            if(context.Hardware is IStaticAngleHardware table2&&table2.IsTwoTdConnected)
            {
                var f=await table2.ReadTwoTdAsync(ct);
                if(!f.Inner.Normal||!f.Outer.Normal||Math.Abs(f.Inner.SpeedDps)>0.05||Math.Abs(f.Outer.SpeedDps)>0.05)
                    throw new InvalidDataException("采集结束时转台非静止");
            }
            var batches=await Ct12aAlgorithm.ReadRealBatchMeansAsync(Path.Combine(capture.Folder,"imu_selected.csv"),capture.CsvFile,ct);
            analysis=Ct20Algorithm.Analyze(batches,s);
            state=analysis.StableStartMinute is null?"COMPLETED_NO_STABILIZATION":"COMPLETED_PENDING_ACCEPTANCE";
            error=string.Join("；",analysis.Warnings);
        }
        catch(OperationCanceledException){throw;}
        catch(Exception ex){error=ex.Message;context.Progress?.Report("CT-20数据质量核验失败："+error);}
        var report=new Ct20ReportData(TestId,Name,id.DtsId,id.UidHex,started,DateTimeOffset.UtcNow,state,error,
            new Ct20SettingsSnapshot(s.PowerOnUtc,s.DurationMinutes,s.WindowSeconds,s.StableWindowSeconds,s.BiasToleranceDps,s.DriftToleranceDpsPerMin,s.MinimumBatches,s.StationaryConfirmed,s.ColdStartConfirmed,s.TemperatureRecorded),
            Path.GetFileName(acc.FilePath),acc.Sha256,Path.GetFileName(gyro.FilePath),gyro.Sha256,capture.Folder,capture.CsvFile,
            Path.Combine(capture.Folder,"imu_selected.csv"),capture.ManifestFile,analysis,
            analysis?.Qualification??"真实采集已保存，但分析资格未通过："+error,
            "冷启动由人工断电/上电完成，软件不控制供电。预热时间以操作者填写的人工上电时间为零点，首个有效FIFO批次之前的空档没有采样数据并单独报告。采集记录是16帧FIFO批次均值；当前MCU没有逐帧硬件时间戳，因此漂移率和稳定时间是基于批次主机时间轴的工程估计。温度变化、室温变化、启动时刻误差和机械/环境扰动均可能影响结果。稳定判据是可配置的研发判据，不等同产品验收指标。");
        var files=await Ct20Report.ExportAsync(folder,report,CancellationToken.None);
        return new TestExecutionResult(TestId,TestOutcome.DiagnosticOnly,
            analysis?.Qualification??"采集完成但分析未通过；请查看报告",capture,new[]{capture.CsvFile,report.SelectedCsvPath,capture.ManifestFile}.Concat(files).ToArray());
    }
}
