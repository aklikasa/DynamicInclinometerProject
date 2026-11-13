using System.Security.Cryptography;
using System.Text.Json;

namespace Dts.Tests.S1.CT12A;

/// <summary>
/// Read-only reanalysis of a completed CT-12A capture. Never writes to the acquisition
/// folder or edits the original report; every run gets a new report output directory.
/// </summary>
public static class Ct12aOffline
{
    private static string GetString(JsonElement json,string key) =>
        json.GetProperty(key).GetString()??throw new InvalidDataException("manifest字段缺失："+key);

    public static async Task<string> ReanalyzeAsync(string manifestPath,Ct12aSettings settings,
        CancellationToken ct,IProgress<string>? progress=null)
    {
        Ct12aAlgorithm.Validate(settings,confirmations:false);
        manifestPath=Path.GetFullPath(manifestPath);
        if(!File.Exists(manifestPath)||!Path.GetFileName(manifestPath).Equals("manifest.json",StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("请选择原CT-12A采集目录内的manifest.json");
        string captureFolder=Path.GetDirectoryName(manifestPath)!;
        using var doc=JsonDocument.Parse(await File.ReadAllTextAsync(manifestPath,ct));
        var manifest=doc.RootElement;
        if(GetString(manifest,"hardware_mode")!="REAL_MCU_HARDWARE"||
            GetString(manifest,"test_id")!="CT-12A"||
            GetString(manifest,"result_status")!="COMPLETED"||
            GetString(manifest,"processing_mode")!="AMBIENT")
            throw new InvalidDataException("只允许对完整、真实硬件采集、常温补偿的CT-12A历史数据离线重算");
        string uid=GetString(manifest,"uid_raw_12_bytes");
        string device=GetString(manifest,"device_dts_id");
        if(uid.Length!=24||!uid.All(Uri.IsHexDigit)||string.IsNullOrWhiteSpace(device))
            throw new InvalidDataException("manifest中的完整UID或设备编号无效");
        if(GetString(manifest,"raw_file")!="imu_raw.csv"||
            GetString(manifest,"selected_file")!="imu_selected.csv")
            throw new InvalidDataException("原始/校正CSV文件名与当前受支持的采集格式不一致");
        string raw=Path.Combine(captureFolder,"imu_raw.csv");
        string selected=Path.Combine(captureFolder,"imu_selected.csv");
        if(!File.Exists(raw)||!File.Exists(selected))
            throw new FileNotFoundException("历史采集目录缺少imu_raw.csv或imu_selected.csv");

        var files=manifest.GetProperty("calibration_files").EnumerateArray().ToArray();
        if(files.Length!=2)throw new InvalidDataException("历史采集清单需要ACC/Gyro两份校准源");
        var hashes=new List<(string Name,string Hash)>();
        foreach(var file in files)
        {
            string name=GetString(file,"file_name"),hash=GetString(file,"sha256");
            if(Path.GetFileName(name)!=name||name.IndexOfAny(Path.GetInvalidFileNameChars())>=0||
                hash.Length!=64||!hash.All(Uri.IsHexDigit))
                throw new InvalidDataException("标定快照文件名或SHA256异常");
            string snapshot=Path.Combine(captureFolder,"calibration_snapshots",name);
            if(!File.Exists(snapshot)||
               !Convert.ToHexString(SHA256.HashData(await File.ReadAllBytesAsync(snapshot,ct)))
                   .Equals(hash,StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("冻结的校准JSON快照不存在或SHA256不匹配："+name);
            hashes.Add((name,hash));
        }
        if(!hashes.Any(x=>x.Name.Contains("acc",StringComparison.OrdinalIgnoreCase))||
           !hashes.Any(x=>x.Name.Contains("gyro",StringComparison.OrdinalIgnoreCase)))
            throw new InvalidDataException("无法从历史清单明确识别ACC与Gyro校准源");
        var acc=hashes.First(x=>x.Name.Contains("acc",StringComparison.OrdinalIgnoreCase));
        var gyro=hashes.First(x=>x.Name.Contains("gyro",StringComparison.OrdinalIgnoreCase));
        int samples=manifest.GetProperty("samples").GetInt32();
        int batchCount=manifest.GetProperty("batches").GetInt32();
        int skipped=manifest.GetProperty("skipped_duplicates").GetInt32();
        int unverified=manifest.GetProperty("sensor_unverified_batches").GetInt32();
        if(samples<32||batchCount<2||skipped<0||unverified<0||unverified>batchCount)
            throw new InvalidDataException("manifest采样计数明显不合理");
        progress?.Report($"历史数据核查：{device} / {uid}，登记{samples}帧；正在按真实CSV流式复核...");
        string reportRoot=Path.GetFullPath(settings.ReportRoot);
        if(!Directory.Exists(reportRoot))throw new DirectoryNotFoundException("报告根目录不存在："+reportRoot);
        Ct12aAnalysis? analysis=null;
        string state="ANALYSIS_INCOMPLETE",error="";
        try
        {
            var batches=await Ct12aAlgorithm.ReadRealBatchMeansAsync(selected,raw,ct);
            if(batches.Count!=batchCount || batches.Count*16!=samples)
                throw new InvalidDataException($"CSV中{batches.Count}批与manifest {batchCount}批/{samples}帧不匹配");
            analysis=Ct12aAlgorithm.Analyze(batches,settings,samples,skipped,unverified);
            state=analysis.CoefficientsReleased?"ENGINEERING_ALLAN_UNCERTIFIED":
                analysis.TimeQuality.ContinuousSequenceQualified && analysis.Curves.Count>=4 &&
                analysis.TimeQuality.SensorUnverifiedBatches>0?"ENGINEERING_ALLAN_SENSOR_UNVERIFIED":
                analysis.TimeQuality.ContinuousSequenceQualified?"TAU_COVERAGE_INSUFFICIENT":
                "TIMEBASE_UNQUALIFIED";
            error=string.Join("；",analysis.TimeQuality.Warnings);
        }
        catch(OperationCanceledException){throw;}
        catch(Exception ex)
        {
            state="ANALYSIS_REJECTED";error=ex.Message;
            progress?.Report("历史文件核验失败，出具原因报告："+ex.Message);
        }
        string outputFolder=Path.Combine(reportRoot,device+"_"+uid,
            Path.GetFileName(captureFolder)+"_AllanReanalysis_"+DateTime.Now.ToString("yyyyMMdd_HHmmss_fff"));
        Directory.CreateDirectory(outputFolder);
        var snap=new Ct12aSettingsSnapshot(settings.DurationMinutes,settings.TauMinSeconds,
            settings.TauMaxSeconds,settings.PointsPerDecade,settings.MaxHostCadenceJitterPercent,
            settings.MaxMcuCadenceJitterPercent,settings.MaxFifoSpanErrorPercent,
            settings.MaxTemperatureRangeC,settings.MinimumBatches,settings.StationaryConfirmed,
            settings.ThermalEnvironmentConfirmed,settings.TimebaseLimitAccepted);
        var report=new Ct12aReportData("CT-12A","历史CSV离线Allan重算","S1",device,uid,
            state,error,GetString(manifest,"started_utc"),GetString(manifest,"ended_utc"),snap,
            acc.Name,acc.Hash,gyro.Name,gyro.Hash,captureFolder,raw,selected,manifestPath,analysis,
            "对原始只读数据重新计算的研发诊断结果；用户可修改本次τ/质量门槛，原采集和原报告不变；不自动判PASS",
            "离线计算基于冻结的历史原始/补偿CSV和JSON哈希。SENSOR_OK未确认仅允许显示未核实来源的研发曲线。"+
            "SIM_MODE=1、FIFO缺帧、时标或标定来源不一致仍将拒绝。"+
            "无逐帧硬件时标，不能作为正式计量级Allan。重算不证明实际硬件状态已修复。" );
        await Ct12aReport.ExportAsync(outputFolder,report,ct);
        progress?.Report("历史CSV重算完成；状态："+state+"；报告："+outputFolder);
        return Path.Combine(outputFolder,"CT-12A_result.json");
    }
}
