using System.Globalization;
using System.Text.Json;
using Dts.Core;

namespace Dts.Devices;

/// <summary>
/// Scientific descriptive statistics on the actual CSV collected from the MCU.
/// Only diagnostics are produced: never sets PASS/FAIL or claims that calibration has been applied.
/// Streaming Welford calculation avoids loading full captures into memory.
/// </summary>
public static class StaticDiagnostics
{
    private sealed class Accumulator
    {
        public long N { get; private set; }
        public double Mean { get; private set; }
        private double _m2;
        public void Add(double x)
        {
            N++;
            double delta=x-Mean;
            Mean+=delta/N;
            _m2+=delta*(x-Mean);
        }
        public double Std => N>=2 ? Math.Sqrt(_m2/(N-1)):double.NaN;
    }

    public static async Task<string> AnalyzeAsync(AcquisitionResult capture,DeviceIdentity identity,
        string testId,CancellationToken token)
    {
        string input=Path.Combine(capture.Folder,"imu_raw.csv");
        var axes=Enumerable.Range(0,6).Select(_=>new Accumulator()).ToArray();
        var early=Enumerable.Range(0,3).Select(_=>new Accumulator()).ToArray();
        var late=Enumerable.Range(0,3).Select(_=>new Accumulator()).ToArray();
        long n=0;
        using var reader=new StreamReader(input);
        string? header=await reader.ReadLineAsync(token);
        if(header is null||!header.Contains("gx_dps",StringComparison.Ordinal))
            throw new InvalidDataException("原始 CSV 缺少有效表头，停止统计分析");
        string? line;
        while((line=await reader.ReadLineAsync(token)) is not null)
        {
            token.ThrowIfCancellationRequested();
            string[] cells=line.Split(',');
            if(cells.Length<20)throw new InvalidDataException($"CSV 数据第 {n+2} 行字段数不足");
            var values=new double[6];
            for(int i=0;i<6;i++)
            {
                values[i]=double.Parse(cells[8+i],CultureInfo.InvariantCulture);
                if(!double.IsFinite(values[i]))throw new InvalidDataException("数据出现非有限量测");
                axes[i].Add(values[i]);
            }
            if(n<capture.Samples/4)
                for(int i=0;i<3;i++)early[i].Add(values[3+i]);
            if(n>=capture.Samples-capture.Samples/4)
                for(int i=0;i<3;i++)late[i].Add(values[3+i]);
            n++;
        }
        if(n<50 || n!=capture.Samples)
            throw new InvalidDataException($"采样数量无效/不一致：CSV {n}、记录 {capture.Samples}，禁止生成分析结果");
        var data=new
        {
            schema_version=1,
            test_id=testId,
            device_uid_raw_12_bytes=identity.UidHex,
            device_dts_id=identity.DtsId,
            source="REAL_IMU_CAPTURE_CSV",
            capture_file="imu_raw.csv",
            analysis_kind="UNCOMPENSATED_RAW_STATIC_DIAGNOSTIC",
            evaluation="NO_PRODUCT_PASS_FAIL",
            sample_count=n,
            acc_mean_g=axes.Take(3).Select(a=>a.Mean).ToArray(),
            acc_std_mg=axes.Take(3).Select(a=>a.Std*1000).ToArray(),
            gyro_mean_dps=axes.Skip(3).Select(a=>a.Mean).ToArray(),
            gyro_std_dps=axes.Skip(3).Select(a=>a.Std).ToArray(),
            gyro_last_quarter_minus_first_quarter_dps=Enumerable.Range(0,3)
                .Select(i=>late[i].Mean-early[i].Mean).ToArray(),
            limitations=new []
            {
                "仅使用 MCU 返回的真实六轴数据；不做人工合成、无设备不生成分析结果。",
                "当前未加载并应用每台 PCB 的 ACC/Gyro 标定矩阵；此数值为原始量测统计，不是标定后的零偏残差或倾角精度。",
                "本数据不证明 DUT 静止、转台角度参考精度和时间同步；未建立任何产品验收 PASS/FAIL。",
                "CT-09 仅完成单姿态原始零速诊断，姿态相关性专项仍未完成；CT-12 为基础短期噪声统计子项。"
            }
        };
        string file=Path.Combine(capture.Folder,"static_diagnostics.json");
        await File.WriteAllTextAsync(file,JsonSerializer.Serialize(data,new JsonSerializerOptions{WriteIndented=true}),token);
        return file;
    }
}
