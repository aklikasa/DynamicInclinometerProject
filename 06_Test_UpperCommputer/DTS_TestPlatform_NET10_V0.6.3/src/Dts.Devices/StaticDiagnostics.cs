using System.Globalization;
using System.Text.Json;
using Dts.Core;

namespace Dts.Devices;

/// <summary>
/// Statistics for authentic MCU raw samples. Unknown scale => raw int16 count statistics only.
/// Candidate scales are visibly separated from confirmed MCU scales; no PASS is generated.
/// </summary>
public static class StaticDiagnostics
{
    private sealed class Accumulator
    {
        public long N {get;private set;}
        public double Mean {get;private set;}
        private double _m2;
        public void Add(double v)
        {
            if(!double.IsFinite(v))return;
            N++;
            double d=v-Mean;
            Mean+=d/N;
            _m2+=d*(v-Mean);
        }
        public double? Average => N==0?null:Mean;
        public double? Std => N<2?null:Math.Sqrt(_m2/(N-1));
    }
    public static async Task<string> AnalyzeAsync(AcquisitionResult capture,DeviceIdentity id,
        string testId,CancellationToken ct)
    {
        var physical=Enumerable.Range(0,6).Select(_=>new Accumulator()).ToArray();
        var raw=Enumerable.Range(0,6).Select(_=>new Accumulator()).ToArray();
        int[] verified=new int[2],candidate=new int[2];
        long n=0;
        await using var file=new FileStream(Path.Combine(capture.Folder,"imu_raw.csv"),FileMode.Open,FileAccess.Read,FileShare.Read);
        using var reader=new StreamReader(file);
        var header=await reader.ReadLineAsync(ct)??throw new InvalidDataException("原始CSV缺少表头");
        string[] cols=header.Split(',');
        int Col(string name)=>Array.FindIndex(cols,n=>string.Equals(n,name,StringComparison.OrdinalIgnoreCase));
        string[] needed=["ax_g","ay_g","az_g","gx_dps","gy_dps","gz_dps","raw_ax","raw_ay","raw_az","raw_gx","raw_gy","raw_gz","acc_scale_source","gyro_scale_source"];
        int[] positions=needed.Select(Col).ToArray();
        if(positions.Any(i=>i<0))throw new InvalidDataException("原始CSV字段不完整，不能分析");
        string? line;
        while((line=await reader.ReadLineAsync(ct)) is not null)
        {
            ct.ThrowIfCancellationRequested();
            string[] cells=line.Split(',');
            if(cells.Length<cols.Length)throw new InvalidDataException($"原始CSV第{n+2}行长度错误");
            for(int i=0;i<6;i++)
            {
                if(double.TryParse(cells[positions[i]],NumberStyles.Float,CultureInfo.InvariantCulture,out var value))
                    physical[i].Add(value);
                if(double.TryParse(cells[positions[6+i]],NumberStyles.Float,CultureInfo.InvariantCulture,out var count))
                    raw[i].Add(count);
            }
            var a=cells[positions[12]];var g=cells[positions[13]];
            if(a=="MCU_VERIFIED")verified[0]++;
            if(g=="MCU_VERIFIED")verified[1]++;
            if(a=="CAL_FILE_UNVERIFIED")candidate[0]++;
            if(g=="CAL_FILE_UNVERIFIED")candidate[1]++;
            n++;
        }
        if(n<50||n!=capture.Samples)throw new InvalidDataException($"原始采样不足或不匹配：{n} / {capture.Samples}");
        var report=new
        {
            schema_version=2,test_id=testId,uid_raw_12_bytes=id.UidHex,dts_id=id.DtsId,
            raw_sample_count=n,source="REAL_MCU_SIGNED_INT16",assessment="DIAGNOSTIC_ONLY_NO_PASS",
            raw_counts_mean=raw.Select(a=>a.Average).ToArray(),
            raw_counts_std=raw.Select(a=>a.Std).ToArray(),
            estimated_physical_mean=physical.Select(a=>a.Average).ToArray(),
            estimated_physical_std=physical.Select(a=>a.Std).ToArray(),
            physical_units = new string[] { "g", "g", "g", "deg/s", "deg/s", "deg/s" },
            accel_rows_with_verified_mcu_scale=verified[0],gyro_rows_with_verified_mcu_scale=verified[1],
            accel_rows_with_unverified_file_scale=candidate[0],gyro_rows_with_unverified_file_scale=candidate[1],
            warning=candidate.Any(x=>x>0)
                ? "含 CAL_FILE_UNVERIFIED 试算，仅依据标定JSON中的量程提示，不作为正式准确度或零偏性能验收"
                : verified.Any(x=>x==0)
                    ? "MCU未报告有效量程，仅提供原始计数统计；不能报告g或deg/s零偏精度"
                    : "仅为常温诊断子项，非产品验收；标定参数另列，不代表已经写入固件"
        };
        string outFile=Path.Combine(capture.Folder,"static_diagnostics.json");
        await File.WriteAllTextAsync(outFile,JsonSerializer.Serialize(report,new JsonSerializerOptions{WriteIndented=true}),ct);
        return outFile;
    }
}
