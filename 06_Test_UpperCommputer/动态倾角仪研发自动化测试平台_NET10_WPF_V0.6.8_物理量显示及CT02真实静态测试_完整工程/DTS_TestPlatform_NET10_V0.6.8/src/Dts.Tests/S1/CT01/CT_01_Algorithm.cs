using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using System.Security.Cryptography;
using System.Text.Json;
using Dts.Core;
using Dts.TestEngine;

namespace Dts.Tests.S1.CT01;

public static class Ct01Algorithm
{
    private sealed class Accumulator
    {
        public long N { get; private set; }
        public double Mean { get; private set; }
        private double _m2, _sumSquares;
        public double MaxAbs { get; private set; }
        public void Add(double value)
        {
            if (!double.IsFinite(value)) throw new InvalidDataException("CT-01 检测到 NaN/Infinity。");
            N++;
            double d = value - Mean;
            Mean += d / N;
            _m2 += d * (value - Mean);
            _sumSquares += value * value;
            MaxAbs = Math.Max(MaxAbs, Math.Abs(value));
        }
        public double Std => N > 1 ? Math.Sqrt(_m2 / (N - 1)) : 0d;
        public double Rms => N > 0 ? Math.Sqrt(_sumSquares / N) : 0d;
    }

    private static readonly string[] AxisNames = ["Ax", "Ay", "Az", "Gx", "Gy", "Gz"];
    private static readonly string[] Units = ["g", "g", "g", "deg/s", "deg/s", "deg/s"];
    private static readonly string[] PhysicalColumns = ["ax_g", "ay_g", "az_g", "gx_dps", "gy_dps", "gz_dps"];
    private static readonly string[] CorrectedColumns = ["cal_ax_g", "cal_ay_g", "cal_az_g", "cal_gx_dps", "cal_gy_dps", "cal_gz_dps"];
    private const double PhysicalTolerance = 1e-10;
    private const double RecomputeTolerance = 1e-8;

    public static async Task<Ct01VerificationResult> AnalyzeAsync(
        CaptureArtifacts capture, DeviceIdentity identity, CalibrationRun expectedRun, CancellationToken ct)
    {
        if (capture.UidHex != identity.UidHex || capture.DeviceNumber != identity.DtsId)
            throw new InvalidDataException("采集返回的 UID/DTS 编号与当前真实设备身份不一致。");
        if (expectedRun.Mode is not (CalibrationMode.Ambient or CalibrationMode.Thermal))
            throw new InvalidDataException("CT-01 仅接受 AMBIENT 或 THERMAL 标定模式。");
        expectedRun.Validate(identity);

        string manifestPath = RequireFile(capture.ManifestFile, "manifest.json");
        using var manifestDoc = JsonDocument.Parse(await File.ReadAllTextAsync(manifestPath, ct));
        var manifest = manifestDoc.RootElement;

        string StringProp(JsonElement e, string name) =>
            e.TryGetProperty(name, out var v) && v.ValueKind == JsonValueKind.String
                ? v.GetString() ?? "" : throw new InvalidDataException($"manifest 缺少字符串字段 {name}");

        if (StringProp(manifest, "hardware_mode") != "REAL_MCU_HARDWARE")
            throw new InvalidDataException("manifest 不是真实 MCU 硬件采集记录。");
        if (!StringProp(manifest, "result_status").Equals("COMPLETED", StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("采集不是完整记录，不能生成 CT-01 完成报告。");
        string mode = StringProp(manifest, "processing_mode");
        string uid = StringProp(manifest, "uid_raw_12_bytes");
        string dts = StringProp(manifest, "device_dts_id");
        string proof = StringProp(manifest, "calibration_identity_proof");
        if (mode != expectedRun.Mode.ToString().ToUpperInvariant())
            throw new InvalidDataException($"采集模式 {mode} 与打开 CT-01 时冻结的模式 {expectedRun.Mode} 不一致；请重新打开测试窗口。");
        if (!uid.Equals(identity.UidHex, StringComparison.OrdinalIgnoreCase) ||
            !dts.Equals(identity.DtsId, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("manifest 中的完整 MCU UID 或 DTS 短编号与当前设备不一致。");
        if (proof != expectedRun.IdentityProof)
            throw new InvalidDataException("manifest 的标定文件身份核验等级与本次选定标定快照不一致。");

        int manifestSamples = manifest.GetProperty("samples").GetInt32();
        int manifestBatches = manifest.GetProperty("batches").GetInt32();
        int processedSamples = manifest.GetProperty("processed_samples").GetInt32();
        string snapshotRel = StringProp(manifest, "calibration_snapshot_folder");
        if (string.IsNullOrWhiteSpace(snapshotRel) || Path.IsPathRooted(snapshotRel))
            throw new InvalidDataException("manifest 没有有效的相对标定快照目录。");

        string captureRoot = Path.GetFullPath(capture.Folder);
        string snapshotRoot = Path.GetFullPath(Path.Combine(captureRoot, snapshotRel));
        if (!snapshotRoot.StartsWith(captureRoot + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("标定快照目录越界，拒绝读取。");
        if (!Directory.Exists(snapshotRoot))
            throw new DirectoryNotFoundException("本次采集缺少冻结的 calibration_snapshots 目录。");

        var manifestSources = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        var sourceArray = manifest.GetProperty("calibration_files");
        if (sourceArray.ValueKind != JsonValueKind.Array || sourceArray.GetArrayLength() != 2)
            throw new InvalidDataException("manifest 必须记录当前模式的 ACC/Gyro 两份标定文件。");
        foreach (var item in sourceArray.EnumerateArray())
        {
            string name = item.GetProperty("file_name").GetString() ?? "";
            string hash = item.GetProperty("sha256").GetString() ?? "";
            if (string.IsNullOrWhiteSpace(name) || hash.Length != 64 || !hash.All(Uri.IsHexDigit) ||
                !manifestSources.TryAdd(name, hash))
                throw new InvalidDataException("manifest 标定文件名或 SHA256 记录无效/重复。");
        }

        if (expectedRun.Sources.Count != 2)
            throw new InvalidDataException("选定的标定快照不是 ACC+Gyro 两份文件。");
        foreach (var source in expectedRun.Sources)
        {
            string name = Path.GetFileName(source.FilePath);
            if (!manifestSources.TryGetValue(name, out var expectedHash) ||
                !expectedHash.Equals(source.Sha256, StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException($"采集使用的标定文件与 CT-01 冻结选择不一致：{name}");
            string snapshot = Path.Combine(snapshotRoot, name);
            if (!File.Exists(snapshot))
                throw new FileNotFoundException("缺少本次采集的标定快照：" + name);
            string actualHash = Convert.ToHexString(SHA256.HashData(await File.ReadAllBytesAsync(snapshot, ct)));
            if (!actualHash.Equals(expectedHash, StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException($"标定快照 SHA256 不匹配：{name}");
        }

        CalibrationSet snapshotSet = CalibrationLibrary.Load(snapshotRoot, identity);
        var snapshotRun = new CalibrationRun(expectedRun.Mode, snapshotSet, ConfirmedFilenameOnly: true);
        snapshotRun.Validate(identity);
        if (snapshotRun.Sources.Count != 2 ||
            snapshotRun.Sources.Any(s => !manifestSources.TryGetValue(Path.GetFileName(s.FilePath), out var h) ||
                !h.Equals(s.Sha256, StringComparison.OrdinalIgnoreCase)))
            throw new InvalidDataException("从冻结快照重新加载的标定参数与 manifest 记录不一致。");
        if (expectedRun.Mode == CalibrationMode.Ambient &&
            (snapshotSet.Acc is null || snapshotSet.Gyro is null))
            throw new InvalidDataException("常温快照缺少 ACC 或 Gyro 矩阵。");
        if (expectedRun.Mode == CalibrationMode.Thermal &&
            (snapshotSet.ThermalAcc is null || snapshotSet.ThermalGyro is null))
            throw new InvalidDataException("全温快照缺少 ACC 或 Gyro 温度模型。");

        string rawPath = RequireFile(Path.Combine(captureRoot, "imu_raw.csv"), "imu_raw.csv");
        var before = Enumerable.Range(0, 6).Select(_ => new Accumulator()).ToArray();
        var after = Enumerable.Range(0, 6).Select(_ => new Accumulator()).ToArray();
        var shift = Enumerable.Range(0, 6).Select(_ => new Accumulator()).ToArray();
        var recomputeError = new double[6];
        double maxPhysicalError = 0, maxRecomputeError = 0;
        int samples = 0, sensorOk = 0, sensorUnverified = 0;
        var distinctTicks = new HashSet<uint>();

        using (var reader = new StreamReader(rawPath))
        {
            string headerLine = await reader.ReadLineAsync(ct) ?? throw new InvalidDataException("imu_raw.csv 缺少表头。");
            string[] headers = headerLine.Split(',');
            int Col(string name)
            {
                int i = Array.FindIndex(headers, h => h.Equals(name, StringComparison.OrdinalIgnoreCase));
                return i >= 0 ? i : throw new InvalidDataException($"imu_raw.csv 缺少字段 {name}。");
            }
            int[] physicalCols = PhysicalColumns.Select(Col).ToArray();
            int[] correctedCols = CorrectedColumns.Select(Col).ToArray();
            int[] rawCols = new[] { "raw_ax", "raw_ay", "raw_az", "raw_gx", "raw_gy", "raw_gz" }.Select(Col).ToArray();
            int accFsCol = Col("acc_fs_g"), gyroFsCol = Col("gyro_fs_dps");
            int tickCol = Col("mcu_tick_ms"), flagsCol = Col("fifo_flags"), tempCol = Col("temp_c");
            string? line;
            while ((line = await reader.ReadLineAsync(ct)) is not null)
            {
                ct.ThrowIfCancellationRequested();
                if (string.IsNullOrWhiteSpace(line)) continue;
                string[] cells = line.Split(',');
                if (cells.Length != headers.Length)
                    throw new InvalidDataException($"imu_raw.csv 第 {samples + 2} 行列数错误。");
                double ParseDouble(int index, string name)
                {
                    if (!double.TryParse(cells[index], NumberStyles.Float, CultureInfo.InvariantCulture, out double v) ||
                        !double.IsFinite(v))
                        throw new InvalidDataException($"第 {samples + 2} 行 {name} 为空或不是有限数值。");
                    return v;
                }
                int ParseInt(int index, string name)
                {
                    if (!int.TryParse(cells[index], NumberStyles.Integer, CultureInfo.InvariantCulture, out int v))
                        throw new InvalidDataException($"第 {samples + 2} 行 {name} 无效。");
                    return v;
                }

                int accFs = ParseInt(accFsCol, "acc_fs_g");
                int gyroFs = ParseInt(gyroFsCol, "gyro_fs_dps");
                int flags = ParseInt(flagsCol, "fifo_flags");
                if (!uint.TryParse(cells[tickCol], NumberStyles.Integer, CultureInfo.InvariantCulture, out uint tick))
                    throw new InvalidDataException($"第 {samples + 2} 行 mcu_tick_ms 无效。");
                double temp = ParseDouble(tempCol, "temp_c");
                var rawCounts = rawCols.Select((c, i) => ParseInt(c, $"raw_{AxisNames[i]}")).ToArray();
                var physical = physicalCols.Select((c, i) => ParseDouble(c, PhysicalColumns[i])).ToArray();
                var corrected = correctedCols.Select((c, i) => ParseDouble(c, CorrectedColumns[i])).ToArray();

                double[] expectedPhysical = new double[6];
                if (expectedRun.Mode == CalibrationMode.Ambient)
                {
                    var scale = CalibrationInputScalePolicy.Resolve(
                        snapshotSet.Acc!.FsHint, snapshotSet.Gyro!.FsHint, accFs, gyroFs)
                        ?? throw new InvalidDataException("无法从标定 JSON/MCU 量程元数据确定常温输入换算系数。");
                    for (int i = 0; i < 3; i++) expectedPhysical[i] = rawCounts[i] * scale.AccGPerLsb;
                    for (int i = 3; i < 6; i++) expectedPhysical[i] = rawCounts[i] * scale.GyroDpsPerLsb;
                }
                else
                {
                    if (!Asm330Codec.TryAccMg(accFs, out double accMg) ||
                        !Asm330Codec.TryGyroMdps(gyroFs, out double gyroMdps))
                        throw new InvalidDataException("全温模式的 MCU ACC/Gyro 量程无效，不能独立复核物理单位换算。");
                    for (int i = 0; i < 3; i++) expectedPhysical[i] = rawCounts[i] * accMg / 1000d;
                    for (int i = 3; i < 6; i++) expectedPhysical[i] = rawCounts[i] * gyroMdps / 1000d;
                }

                for (int i = 0; i < 6; i++)
                {
                    double error = Math.Abs(physical[i] - expectedPhysical[i]);
                    maxPhysicalError = Math.Max(maxPhysicalError, error);
                    if (error > PhysicalTolerance)
                        throw new InvalidDataException($"第 {samples + 2} 行 {AxisNames[i]} 输入量程换算与冻结标定文件/MCU元数据不一致，差值 {error:G6}。");
                }

                double[] expectedAcc, expectedGyro;
                if (expectedRun.Mode == CalibrationMode.Ambient)
                {
                    expectedAcc = snapshotSet.Acc!.Apply(physical[0], physical[1], physical[2]);
                    expectedGyro = snapshotSet.Gyro!.Apply(physical[3], physical[4], physical[5]);
                }
                else
                {
                    expectedAcc = snapshotSet.ThermalAcc!.Apply(physical[0], physical[1], physical[2], temp);
                    expectedGyro = snapshotSet.ThermalGyro!.Apply(physical[3], physical[4], physical[5], temp);
                }
                var expectedCorrected = expectedAcc.Concat(expectedGyro).ToArray();

                for (int i = 0; i < 6; i++)
                {
                    double error = Math.Abs(corrected[i] - expectedCorrected[i]);
                    recomputeError[i] = Math.Max(recomputeError[i], error);
                    maxRecomputeError = Math.Max(maxRecomputeError, error);
                    if (error > RecomputeTolerance)
                        throw new InvalidDataException($"第 {samples + 2} 行 {AxisNames[i]} 主程序补偿值与冻结 JSON 独立重算不一致，差值 {error:G6}。可能存在参数未生效、重复补偿或数据流错配。");
                    before[i].Add(physical[i]);
                    after[i].Add(corrected[i]);
                    shift[i].Add(corrected[i] - physical[i]);
                }
                if ((flags & 0x0001) != 0) sensorOk++; else sensorUnverified++;
                distinctTicks.Add(tick);
                samples++;
            }
        }

        if (samples < 50) throw new InvalidDataException($"有效采样不足50帧：{samples}。");
        if (samples != capture.Samples || samples != manifestSamples)
            throw new InvalidDataException($"采样数量不一致：CSV={samples}，采集对象={capture.Samples}，manifest={manifestSamples}。");
        if (capture.Batches != manifestBatches || manifestBatches < 1)
            throw new InvalidDataException("FIFO批次数量与 manifest 不一致。");
        if (processedSamples != samples)
            throw new InvalidDataException($"补偿有效帧数 {processedSamples} 与真实采样帧数 {samples} 不一致；存在未成功计算的样本。");

        string selectedPath = RequireFile(Path.Combine(captureRoot, "imu_selected.csv"), "imu_selected.csv");
        await VerifySelectedStreamAsync(selectedPath, rawPath, expectedRun.Mode, samples, ct);

        var metrics = Enumerable.Range(0, 6).Select(i => new Ct01AxisMetric(
            AxisNames[i], Units[i], before[i].N,
            before[i].Mean, before[i].Std,
            after[i].Mean, after[i].Std,
            after[i].Mean - before[i].Mean,
            shift[i].Rms, shift[i].MaxAbs, recomputeError[i])).ToArray();

        string assessment = sensorUnverified == 0
            ? "PARAMETER_APPLICATION_VERIFIED_SENSOR_OK_REPORTED"
            : "PARAMETER_APPLICATION_VERIFIED_SOURCE_STATUS_PARTLY_UNVERIFIED";
        string limitation = "本测试验证 UID/标定快照/输入量程/主程序补偿输出与独立重算的一致性；没有外部角度或角速度参考，因此不能据此判断补偿后精度是否提高，也不生成产品 PASS/FAIL。";
        string started = manifest.TryGetProperty("started_utc", out var st) ? st.ToString() : "";
        string ended = manifest.TryGetProperty("ended_utc", out var en) ? en.ToString() : "";

        return new Ct01VerificationResult(
            "CT-01", identity.UidHex, identity.DtsId, expectedRun.Mode.ToString().ToUpperInvariant(),
            proof, captureRoot, started, ended, samples, manifestBatches, distinctTicks.Count,
            sensorOk, sensorUnverified, processedSamples, maxPhysicalError, maxRecomputeError,
            metrics, assessment, limitation);
    }

    private static async Task VerifySelectedStreamAsync(
        string selectedPath, string rawPath, CalibrationMode mode, int expectedRows, CancellationToken ct)
    {
        using var rawReader = new StreamReader(rawPath);
        using var selectedReader = new StreamReader(selectedPath);
        string[] rawHeaders = (await rawReader.ReadLineAsync(ct) ?? throw new InvalidDataException("imu_raw.csv 缺少表头。")).Split(',');
        string[] selectedHeaders = (await selectedReader.ReadLineAsync(ct) ?? throw new InvalidDataException("imu_selected.csv 缺少表头。")).Split(',');
        int RawCol(string name)
        {
            int i = Array.FindIndex(rawHeaders, h => h.Equals(name, StringComparison.OrdinalIgnoreCase));
            return i >= 0 ? i : throw new InvalidDataException($"imu_raw.csv 缺少字段 {name}。");
        }
        int SelCol(string name)
        {
            int i = Array.FindIndex(selectedHeaders, h => h.Equals(name, StringComparison.OrdinalIgnoreCase));
            return i >= 0 ? i : throw new InvalidDataException($"imu_selected.csv 缺少字段 {name}。");
        }
        int modeCol = SelCol("mode");
        int[] selectedCols = new[] { "ax", "ay", "az", "gx", "gy", "gz" }.Select(SelCol).ToArray();
        int[] correctedCols = CorrectedColumns.Select(RawCol).ToArray();
        int row = 0;
        while (true)
        {
            ct.ThrowIfCancellationRequested();
            string? rawLine = await rawReader.ReadLineAsync(ct);
            string? selectedLine = await selectedReader.ReadLineAsync(ct);
            if (rawLine is null || selectedLine is null)
            {
                if (rawLine is not null || selectedLine is not null)
                    throw new InvalidDataException("imu_selected.csv 与 imu_raw.csv 行数不一致。");
                break;
            }
            if (string.IsNullOrWhiteSpace(rawLine) && string.IsNullOrWhiteSpace(selectedLine)) continue;
            if (string.IsNullOrWhiteSpace(rawLine) || string.IsNullOrWhiteSpace(selectedLine))
                throw new InvalidDataException("两个 CSV 出现不对齐的空行。");
            string[] rc = rawLine.Split(','), sc = selectedLine.Split(',');
            if (rc.Length != rawHeaders.Length || sc.Length != selectedHeaders.Length || row >= expectedRows)
                throw new InvalidDataException("CSV 行数/列数与 manifest 不一致。");
            if (sc[modeCol] != mode.ToString().ToUpperInvariant())
                throw new InvalidDataException($"imu_selected.csv 第 {row + 2} 行补偿模式不一致。");
            for (int i = 0; i < 6; i++)
            {
                if (!double.TryParse(rc[correctedCols[i]], NumberStyles.Float, CultureInfo.InvariantCulture, out double expected) ||
                    !double.TryParse(sc[selectedCols[i]], NumberStyles.Float, CultureInfo.InvariantCulture, out double actual) ||
                    !double.IsFinite(expected) || !double.IsFinite(actual))
                    throw new InvalidDataException($"CSV 第 {row + 2} 行 {AxisNames[i]} 无效。");
                if (Math.Abs(expected - actual) > 0.00000051)
                    throw new InvalidDataException($"主程序 imu_selected.csv 与 imu_raw.csv 的补偿值在第 {row + 2} 行 {AxisNames[i]} 不一致。");
            }
            row++;
        }
        if (row != expectedRows)
            throw new InvalidDataException($"两个 CSV 只有 {row} 行，manifest 声明 {expectedRows} 帧。");
    }

    private static string RequireFile(string path, string name)
    {
        if (!File.Exists(path)) throw new FileNotFoundException("缺少 " + name, path);
        return path;
    }
}
