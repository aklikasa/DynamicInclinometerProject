using System.Globalization;
using System.Text;
using System.Text.Json;
using Dts.Core;

namespace Dts.Devices;

public sealed record AcquisitionResult(string Folder,int Batches,int Samples,int SkippedDuplicates,
    double? MeanGx,double? MeanGy,double? MeanGz,DateTimeOffset Start,DateTimeOffset End,
    string Status="COMPLETED",int UnknownScaleBatches=0,int CandidateScaleBatches=0,
    CalibrationMode SelectedMode=CalibrationMode.Raw,int ProcessedSamples=0,int SensorUnverifiedBatches=0);

public sealed record LiveImuReading(int Samples,double TemperatureC,string AccSource,string GyroSource,
    double[]? AccRawUnits,double[]? GyroRawUnits,double[]? AccCalibrated,double[]? GyroCalibrated,
    int AccFsReg=0,int GyroFsReg=0,int OdrReg=0,
    int[]? AccCounts=null,int[]? GyroCounts=null,CalibrationMode Mode=CalibrationMode.Raw,
    bool SensorOk=false,string ProcessingStatus="");

/// <summary>
/// Raw counts are NEVER modified. Selected ambient/thermal values are a second stream,
/// with MCU-reported verified sensitivities only. No fallback FS or synthetic samples.
/// </summary>
public static class Acquisition
{
    public static async Task<AcquisitionResult> CollectAsync(RealImu imu,TimeSpan? duration,
        string testId,IProgress<string>? progress,CancellationToken ct,string? selectedRoot=null,
        CalibrationRun? calibrationRun=null,bool finishOnManualStop=false,IProgress<LiveImuReading>? live=null,
        IProgress<IReadOnlyList<SelectedImuFrame>>? liveRows=null)
    {
        if(!imu.Connected||imu.Identity is null)throw new InvalidOperationException("必须连接真实IMU并获取完整UID");
        if(duration is { } limit && (limit<=TimeSpan.Zero||limit>TimeSpan.FromHours(24)))
            throw new ArgumentOutOfRangeException(nameof(duration),"定时采集须在1秒至24小时之间");
        var run=calibrationRun??CalibrationRun.Raw;
        var id=imu.Identity;
        run.Validate(id);
        // A calibration selected on the UI must still be the same file on disk at
        // capture start; never silently combine old in-memory coefficients with a
        // newer file at the recorded path.
        foreach (var source in run.Sources)
        {
            if (!File.Exists(source.FilePath) ||
                !Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(File.ReadAllBytes(source.FilePath)))
                    .Equals(source.Sha256,StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("当前标定文件已被移动或修改，请重新加载标定总目录后再采集：" + source.FilePath);
        }
        string root=Path.Combine(selectedRoot??Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments),
            "DTS_RealData"),id.DtsId+"_"+id.UidHex,DateTime.UtcNow.ToString("yyyyMMdd_HHmmss_fff")+"_"+testId);
        Directory.CreateDirectory(root);
        // Freeze a physical copy of the exact source JSON into each test dataset.
        // The originals in the user-selected library are never modified.
        if (run.Sources.Count != 0)
        {
            var snapshotDirectory=Path.Combine(root,"calibration_snapshots");
            Directory.CreateDirectory(snapshotDirectory);
            foreach(var source in run.Sources)
            {
                string snapshot=Path.Combine(snapshotDirectory,Path.GetFileName(source.FilePath));
                File.Copy(source.FilePath,snapshot,overwrite:false);
                string copiedHash=Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(File.ReadAllBytes(snapshot)));
                if (!copiedHash.Equals(source.Sha256,StringComparison.OrdinalIgnoreCase))
                    throw new IOException("标定快照复制时内容发生变化；不允许开始采集：" + source.FilePath);
            }
        }
        var start=DateTimeOffset.UtcNow;
        var watch=System.Diagnostics.Stopwatch.StartNew();
        int batches=0,samples=0,duplicates=0,unknown=0,processedSamples=0,sensorUnverified=0,validGyro=0;
        double gxSum=0,gySum=0,gzSum=0;
        uint? lastTick=null;
        long lastUiUpdateMs=-100000;
        string status="COMPLETED";string? failure=null;
        string rawPath=Path.Combine(root,"imu_raw.csv");
        string processedPath=Path.Combine(root,"imu_selected.csv");
        await using var rawStream=new FileStream(rawPath,FileMode.CreateNew,FileAccess.Write,FileShare.Read,65536,FileOptions.Asynchronous);
        await using var rawWriter=new StreamWriter(rawStream,new UTF8Encoding(true));
        StreamWriter? selectedWriter=null;
        try
        {
            await rawWriter.WriteLineAsync("host_utc,mcu_tick_ms,sample_index,acc_fs_g,gyro_fs_dps,odr_hz,fifo_flags,temp_c,"+
                "ax_g,ay_g,az_g,gx_dps,gy_dps,gz_dps,raw_ax,raw_ay,raw_az,raw_gx,raw_gy,raw_gz,"+
                "acc_scale_source,gyro_scale_source,cal_ax_g,cal_ay_g,cal_az_g,cal_gx_dps,cal_gy_dps,cal_gz_dps");
            // The main recording always reflects the selected view, including raw mode.
            selectedWriter=new StreamWriter(new FileStream(processedPath,FileMode.CreateNew,FileAccess.Write,
                FileShare.Read,65536,FileOptions.Asynchronous),new UTF8Encoding(true));
            await selectedWriter.WriteLineAsync(SelectedImuFrame.CsvHeader);
            try
            {
                while(duration is null || watch.Elapsed<duration.Value)
                {
                    ct.ThrowIfCancellationRequested();
                    // Diagnostic raw capture records authentic counts even if the firmware has not
                    // asserted SENSOR_OK; never classify those frames as valid physical measurements.
                    // Hardware authenticity is still checked inside ReadBatchAsync (SIM_MODE rejected).
                    // SENSOR_OK is evaluated per frame below so diagnostics can archive
                    // authentic counts without falsely emitting a calibrated value.
                    ImuBatch batch=await imu.ReadBatchAsync(ct,requireSensorOk:false);
                    if(batch.FifoUnread==0||lastTick==batch.McuTickMs)
                    {duplicates++;await Task.Delay(12,ct);continue;}
                    lastTick=batch.McuTickMs;batches++;
                    bool sensorOk=(batch.FifoFlags&0x0001)!=0;
                    if(!sensorOk)sensorUnverified++;
                    bool scaleOk=batch.AllUnitsValid;
                    if(run.Mode!=CalibrationMode.Raw&&!scaleOk)unknown++;
                    var currentBatchRows=new List<SelectedImuFrame>(batch.Samples.Count);
                    for(int i=0;i<batch.Samples.Count;i++)
                    {
                        var s=batch.Samples[i];
                        // Identical conversion and formatting feeds BOTH DataGrid and CSV.
                        var frame=SelectedImuFrame.FromSample(batch,s,i,run);
                        currentBatchRows.Add(frame);
                        if(frame.HasValidCalibration)
                        {
                            processedSamples++;
                            validGyro++;
                            gxSum+=frame.CalibratedGyro![0];gySum+=frame.CalibratedGyro[1];gzSum+=frame.CalibratedGyro[2];
                        }
                        samples++;
                        // Immutable raw backup: always contains signed int16 counts.
                        await rawWriter.WriteLineAsync(string.Join(",",batch.HostTimeUtc.ToString("O"),batch.McuTickMs,i,
                            batch.AccFsG,batch.GyroFsDps,batch.OdrHz,batch.FifoFlags,F(batch.TemperatureC),
                            Join(frame.PhysicalAcc),Join(frame.PhysicalGyro),s.RawAx,s.RawAy,s.RawAz,s.RawGx,s.RawGy,s.RawGz,
                            frame.Status,frame.Status,Join(frame.CalibratedAcc),Join(frame.CalibratedGyro)));
                        await selectedWriter.WriteLineAsync(frame.ToSelectedCsvLine());
                    }
                    // Throttle ONLY UI notification. All frames are written to both CSVs.
                    if(watch.ElapsedMilliseconds-lastUiUpdateMs>=220)
                    {
                        lastUiUpdateMs=watch.ElapsedMilliseconds;
                        if(liveRows is not null)liveRows.Report(currentBatchRows);
                        if(live is not null && currentBatchRows.Count>0)
                        {
                            var f=currentBatchRows[^1];
                            live.Report(new LiveImuReading(samples,batch.TemperatureC,f.Status,f.Status,
                                f.PhysicalAcc,f.PhysicalGyro,f.CalibratedAcc,f.CalibratedGyro,
                                batch.AccFsG,batch.GyroFsDps,batch.OdrHz,
                                new[]{(int)f.RawAx,f.RawAy,f.RawAz},
                                new[]{(int)f.RawGx,f.RawGy,f.RawGz},run.Mode,sensorOk,f.Status));
                        }
                    }
                    if(batches%200==0)CheckFreeSpace(root);
                    if(batches%25==0)
                    {
                        await rawWriter.FlushAsync(CancellationToken.None);
                        if(selectedWriter is not null)await selectedWriter.FlushAsync(CancellationToken.None);
                        progress?.Report($"实际采集{batches}批/{samples}帧，补偿有效{processedSamples}帧，模式{run.Mode}");
                    }
                    await Task.Delay(10,ct);
                }
            }
            catch(OperationCanceledException) when(finishOnManualStop){status="STOPPED_BY_OPERATOR";}
            catch(OperationCanceledException){status="CANCELLED";throw;}
            catch(Exception e){status="FAILED";failure=e.Message;throw;}
        }
        finally
        {
            await rawWriter.FlushAsync(CancellationToken.None);
            if(selectedWriter is not null)
            {await selectedWriter.FlushAsync(CancellationToken.None);await selectedWriter.DisposeAsync();}
            var manifest=new
            {
                schema_version=3,hardware_mode="REAL_MCU_HARDWARE",test_id=testId,
                uid_raw_12_bytes=id.UidHex,device_dts_id=id.DtsId,
                started_utc=start,ended_utc=DateTimeOffset.UtcNow,
                result_status=status,failure_message=failure,
                processing_mode=run.Mode.ToString().ToUpperInvariant(),
                capture_duration_mode=duration is null?"UNTIL_MANUAL_STOP":"TIMED",
                requested_duration_seconds=duration?.TotalSeconds,
                batches,samples,processed_samples=processedSamples,skipped_duplicates=duplicates,
                unknown_scale_batches=unknown,sensor_unverified_batches=sensorUnverified,
                raw_file="imu_raw.csv",selected_file="imu_selected.csv",
                selected_file_is_primary=true,selected_stream_units=run.Mode==CalibrationMode.Raw?"count/count":"g/deg/s",
                calibration_identity_proof=run.IdentityProof,
                calibration_snapshot_folder=run.Sources.Count == 0? null : "calibration_snapshots",
                calibration_files=run.Sources.Select(s=>new{file_name=Path.GetFileName(s.FilePath),source_path=s.FilePath,
                    sha256=s.Sha256,full_uid_verified=s.FullUidVerified,run_id=s.RunId}).ToArray(),
                warning="imu_selected.csv为所选模式主记录，与实时表格使用同一换算及六位小数格式。imu_raw.csv为始终保留的原始备份。-- 表示补偿无效不可用于验收。host_utc为批次时间，不是每帧同步时戳。"
            };
            await File.WriteAllTextAsync(Path.Combine(root,"manifest.json"),
                JsonSerializer.Serialize(manifest,new JsonSerializerOptions{WriteIndented=true}),CancellationToken.None);
        }
        return new AcquisitionResult(root,batches,samples,duplicates,
            validGyro>0?gxSum/validGyro:null,validGyro>0?gySum/validGyro:null,validGyro>0?gzSum/validGyro:null,
            start,DateTimeOffset.UtcNow,status,unknown,0,run.Mode,processedSamples,sensorUnverified);
    }

    public static IReadOnlyList<SelectedImuFrame> PreviewBatch(ImuBatch batch,CalibrationRun? calibrationRun)
    {
        var run=calibrationRun??CalibrationRun.Raw;
        var rows=new List<SelectedImuFrame>(batch.Samples.Count);
        for(int i=0;i<batch.Samples.Count;i++)
            rows.Add(SelectedImuFrame.FromSample(batch,batch.Samples[i],i,run));
        return rows;
    }

    public static LiveImuReading Preview(ImuBatch batch,CalibrationRun? calibrationRun)
    {
        var row=PreviewBatch(batch,calibrationRun)[^1];
        return new LiveImuReading(batch.Samples.Count,batch.TemperatureC,row.Status,row.Status,
            row.PhysicalAcc,row.PhysicalGyro,row.CalibratedAcc,row.CalibratedGyro,
            batch.AccFsG,batch.GyroFsDps,batch.OdrHz,
            new[]{(int)row.RawAx,row.RawAy,row.RawAz},
            new[]{(int)row.RawGx,row.RawGy,row.RawGz},row.Mode,
            (batch.FifoFlags&0x0001)!=0,row.Status);
    }
    private static void CheckFreeSpace(string folder)
    {
        var driveRoot=Path.GetPathRoot(folder);if(string.IsNullOrWhiteSpace(driveRoot))return;
        try
        {
            var drive=new DriveInfo(driveRoot);
            if(drive.IsReady&&drive.AvailableFreeSpace<256L*1024*1024)
                throw new IOException("剩余磁盘空间不足256MiB：停止采集并保存清单");
        }
        catch(ArgumentException){}
        catch(DriveNotFoundException){}
    }
    private static string F(double x)=>double.IsFinite(x)?x.ToString("G17",CultureInfo.InvariantCulture):"";
    private static string Join(double[]? v)=>v is null ? ",," : string.Join(",",v.Select(F));
}
