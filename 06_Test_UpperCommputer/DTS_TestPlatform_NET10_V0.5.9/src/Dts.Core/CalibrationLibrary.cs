using System.Security.Cryptography;
using System.Text.Json;

namespace Dts.Core;

/// <summary>Data selection is global to one run. Raw, ambient and thermal are mutually exclusive.</summary>
public enum CalibrationMode { Raw, Ambient, Thermal }

/// <summary>Immutable per-run snapshot: file bytes are parsed before starting, never reloaded mid-run.</summary>
public sealed record CalibrationRun(CalibrationMode Mode, CalibrationSet? Files, bool ConfirmedFilenameOnly)
{
    public static CalibrationRun Raw { get; } = new(CalibrationMode.Raw, null, false);
    public IReadOnlyList<CalibrationSource> Sources => Mode switch
    {
        CalibrationMode.Ambient => new CalibrationSource?[]{Files?.Acc, Files?.Gyro}.OfType<CalibrationSource>().ToArray(),
        CalibrationMode.Thermal => new CalibrationSource?[]{Files?.ThermalAcc, Files?.ThermalGyro}.OfType<CalibrationSource>().ToArray(),
        _ => Array.Empty<CalibrationSource>()
    };
    public string IdentityProof => Mode == CalibrationMode.Raw ? "RAW_NO_CALIBRATION" :
        Sources.All(s => s.FullUidVerified) ? "FULL_UID_MATCH" : "DTS_FILENAME_ONLY_OPERATOR_CONFIRMED";

    public void Validate(DeviceIdentity hardware)
    {
        if (Mode == CalibrationMode.Raw) return;
        if (Files is null || Files.Identity != hardware)
            throw new InvalidDataException("当前标定文件与实际读取的完整 MCU UID 不一致");
        if (Sources.Count != 2)
            throw new InvalidDataException(Mode == CalibrationMode.Ambient ?
                "常温模式必须同时找到当前UID的 ACC 与 Gyro 常温标定文件" :
                "全温模式必须同时找到当前UID的 ACC 与 Gyro 全温标定文件");
        if (Sources.Any(s => s.IsSimulation))
            throw new InvalidDataException("检测到 simulation_only 标定模板：禁止在真实硬件采集时加载");
        if (!Sources.All(s => s.FullUidVerified) && !ConfirmedFilenameOnly)
            throw new InvalidDataException("文件仅凭 DTS 短编号匹配，需先确认其确实属于当前 PCB（无需手动逐个选文件）");
    }
}

/// <summary>Files can be absent per mode; the chosen mode is validated just before capture.</summary>
public sealed record CalibrationSet(DeviceIdentity Identity, CalibrationMatrix? Acc, CalibrationMatrix? Gyro)
{
    public ThermalCalibration? ThermalAcc {get;init;}
    public ThermalCalibration? ThermalGyro {get;init;}
    public IReadOnlyList<string> OtherMatchedFiles {get;init;} = Array.Empty<string>();
    public bool HasAny => Acc is not null || Gyro is not null || ThermalAcc is not null || ThermalGyro is not null;
    public bool AllFullUidVerified => new CalibrationSource?[]{Acc,Gyro,ThermalAcc,ThermalGyro}
        .OfType<CalibrationSource>().All(s=>s.FullUidVerified);
    public string OwnershipLabel => AllFullUidVerified ? "完整UID核验" : "至少一个文件只有DTS短编号证据";
    public string Summary => $"常温ACC:{Name(Acc)} Gyro:{Name(Gyro)} | 全温ACC:{Name(ThermalAcc)} Gyro:{Name(ThermalGyro)} | {OwnershipLabel}";
    private static string Name(CalibrationSource? s) => s is null ? "未找到" : Path.GetFileName(s.FilePath);
}

public abstract class CalibrationSource
{
    public required string FilePath {get;init;}
    public required string Sha256 {get;init;}
    public required bool FullUidVerified {get;init;}
    public required bool IsSimulation {get;init;}
    public string RunId {get;init;} = "";
}

public static class CalibrationLibrary
{
    public static CalibrationSet Load(string folder, DeviceIdentity hardware)
    {
        if (!Directory.Exists(folder)) throw new DirectoryNotFoundException("标定文件夹不存在：" + folder);
        if (hardware.UidHex.Length != 24) throw new InvalidDataException("尚未读取有效完整 MCU UID");
        var ap = Find(folder,hardware,"accel_calibration.json");
        var gp = Find(folder,hardware,"gyro_calibration.json");
        var at = Find(folder,hardware,"thermal_acc_candidate.json");
        var gt = Find(folder,hardware,"thermal_gyro_candidate.json");
        if (ap is null && gp is null && at is null && gt is null)
            throw new FileNotFoundException($"标定总目录及其子文件夹中未找到 {hardware.DtsId}_ 开头的四类标定文件");
        var acc=ap is null?null:CalibrationMatrix.Load(ap,hardware,"raw_accel_bias_g");
        var gyro=gp is null?null:CalibrationMatrix.Load(gp,hardware,"raw_gyro_bias_dps");
        // Optional alignment/pilot references are not currently applied to ACC/Gyro
        // compensation. Multiple archived versions must not block the 4 active models.
        var extra = new[]{"alignment.json","imu_calibration_pilot_candidate.json"}
            .SelectMany(s=>FindReferences(folder,hardware,s)).ToArray();
        return new CalibrationSet(hardware,acc,gyro)
        {
            ThermalAcc=at is null?null:ThermalCalibration.Load(at,hardware,"acc"),
            ThermalGyro=gt is null?null:ThermalCalibration.Load(gt,hardware,"gyro"),
            OtherMatchedFiles=extra
        };
    }

    private static IEnumerable<string> FindReferences(string folder, DeviceIdentity hardware, string suffix)
    {
        var allowed = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {hardware.DtsId + "_" + suffix, hardware.UidHex + "_" + suffix};
        var options = new EnumerationOptions
        {RecurseSubdirectories=true,IgnoreInaccessible=true,
            AttributesToSkip=FileAttributes.ReparsePoint, MatchCasing=MatchCasing.CaseInsensitive};
        return Directory.EnumerateFiles(folder,"*.json",options)
            .Where(f=>allowed.Contains(Path.GetFileName(f)))
            .OrderBy(f=>f,StringComparer.OrdinalIgnoreCase).ToArray();
    }

    /// <summary>
    /// Search the single user-selected calibration ROOT recursively. Folder names do not
    /// establish identity: only exact UID/DTS file names and verified JSON metadata do.
    /// Reparse points are skipped to avoid traversing symlinks/junctions out of the root.
    /// Different versions of the same UID and type fail closed (no timestamp-based selection).
    /// </summary>
    public static string? Find(string folder,DeviceIdentity hardware,string suffix)
    {
        if (!Directory.Exists(folder)) return null;
        var names = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            hardware.DtsId + "_" + suffix,
            hardware.UidHex + "_" + suffix
        };
        var options = new EnumerationOptions
        {
            RecurseSubdirectories = true,
            IgnoreInaccessible = true,
            AttributesToSkip = FileAttributes.ReparsePoint,
            MatchCasing = MatchCasing.CaseInsensitive,
            ReturnSpecialDirectories = false
        };
        var hits = Directory.EnumerateFiles(folder, "*.json", options)
            .Where(f => names.Contains(Path.GetFileName(f)))
            .OrderBy(f => f, StringComparer.OrdinalIgnoreCase)
            .ToArray();
        if (hits.Length == 0) return null;
        if (hits.Length == 1) return hits[0];

        // A byte-for-byte duplicate is not a different calibration version. Prefer the
        // shortest relative path to make selection stable; real conflicts remain blocking.
        var hashes = hits.Select(f => Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(f))))
            .Distinct(StringComparer.OrdinalIgnoreCase).ToArray();
        if (hashes.Length > 1)
            throw new InvalidDataException($"设备 {hardware.DtsId} 的 {suffix} 在标定总目录下发现多个不同版本。" +
                "请移走旧版、建立唯一有效版本后重新加载，程序不会自动选最新文件：" +
                string.Join("；", hits));
        return hits.OrderBy(f => Path.GetRelativePath(folder, f).Count(c => c == Path.DirectorySeparatorChar))
            .ThenBy(f => f, StringComparer.OrdinalIgnoreCase).First();
    }
}

internal static class CalibrationJson
{
    public static void CheckIdentity(JsonElement root,string file,DeviceIdentity hw)
    {
        if(root.TryGetProperty("simulation_only",out var sim) && sim.ValueKind==JsonValueKind.True)
            throw new InvalidDataException($"{Path.GetFileName(file)} 是 simulation_only 模板，不得用于真实 IMU 补偿");
        if(root.TryGetProperty("device_serial",out var serial) && serial.ValueKind==JsonValueKind.String)
        {
            var num=serial.GetString()??"";
            if(num.StartsWith("DTS",StringComparison.OrdinalIgnoreCase) &&
               !string.Equals(num,hw.DtsId,StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("标定JSON device_serial 与当前设备不一致");
        }
    }
    public static bool VerifiedUid(JsonElement root,DeviceIdentity hw)
    {
        bool found=false;
        foreach(var key in new[]{"uid_raw_12_bytes","device_uid_raw","raw_uid","uid_hex","mcu_uid_hex"})
        {
            if(!root.TryGetProperty(key,out var e) || e.ValueKind==JsonValueKind.Null)continue;
            if(e.ValueKind!=JsonValueKind.String)throw new InvalidDataException($"标定UID字段 {key} 类型不正确");
            string s=(e.GetString()??"").Replace(" ","").Replace("-","");
            if(s.Length!=24 || !s.All(Uri.IsHexDigit))throw new InvalidDataException($"{key} 不是12字节UID");
            if(!s.Equals(hw.UidHex,StringComparison.OrdinalIgnoreCase))throw new InvalidDataException($"{key} 与当前实际IMU UID不匹配");
            found=true;
        }
        return found;
    }
    public static double[] Vector(JsonElement p,int n)
    {
        if(p.ValueKind!=JsonValueKind.Array||p.GetArrayLength()!=n)
            throw new InvalidDataException($"标定矢量必须包含 {n} 个元素");
        var vals=p.EnumerateArray().Select(v=>v.GetDouble()).ToArray();
        if(vals.Any(v=>!double.IsFinite(v)))throw new InvalidDataException("标定数值出现 NaN/Infinity");
        return vals;
    }
    public static double[][] Matrix(JsonElement p)
    {
        if(p.ValueKind!=JsonValueKind.Array || p.GetArrayLength()!=3)throw new InvalidDataException("矩阵必须是3x3");
        return p.EnumerateArray().Select(x=>Vector(x,3)).ToArray();
    }
    public static string Hash(string file)=>Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(file)));
    public static double Determinant(double[][] a)=>
        a[0][0]*(a[1][1]*a[2][2]-a[1][2]*a[2][1])-
        a[0][1]*(a[1][0]*a[2][2]-a[1][2]*a[2][0])+
        a[0][2]*(a[1][0]*a[2][1]-a[1][1]*a[2][0]);
    public static double[] Multiply(double[][] m,double[] centered)
    {
        var result=new double[3];
        for(int i=0;i<3;i++)for(int j=0;j<3;j++)result[i]+=m[i][j]*centered[j];
        return result;
    }
    // Partial pivoting; rejects nearly singular fitted F(T) instead of emitting extreme outputs.
    public static double[][] Inverse3(double[][] input)
    {
        var a=new double[3,6];
        for(int i=0;i<3;i++){for(int j=0;j<3;j++)a[i,j]=input[i][j];a[i,i+3]=1;}
        for(int col=0;col<3;col++)
        {
            int pivot=col;
            for(int i=col+1;i<3;i++)if(Math.Abs(a[i,col])>Math.Abs(a[pivot,col]))pivot=i;
            if(Math.Abs(a[pivot,col])<1e-9)throw new InvalidDataException("F(T) 在当前温度不可逆，拒绝补偿");
            for(int j=0;j<6;j++)(a[col,j],a[pivot,j])=(a[pivot,j],a[col,j]);
            var denom=a[col,col];for(int j=0;j<6;j++)a[col,j]/=denom;
            for(int i=0;i<3;i++)if(i!=col){var factor=a[i,col];for(int j=0;j<6;j++)a[i,j]-=factor*a[col,j];}
        }
        return Enumerable.Range(0,3).Select(i=>Enumerable.Range(0,3).Select(j=>a[i,j+3]).ToArray()).ToArray();
    }
}

public sealed class CalibrationMatrix : CalibrationSource
{
    public required double[] Bias {get;init;}
    public required double[][] Matrix {get;init;}
    public int? FsHint {get;init;}
    public bool McuRangeVerifiedByFile {get;init;}
    public double[] Apply(double x,double y,double z)=>CalibrationJson.Multiply(Matrix,new[]{x-Bias[0],y-Bias[1],z-Bias[2]});

    public static CalibrationMatrix Load(string file,DeviceIdentity hw,string biasName)
    {
        using var doc=JsonDocument.Parse(File.ReadAllText(file));var root=doc.RootElement;
        CalibrationJson.CheckIdentity(root,file,hw);
        if(!root.TryGetProperty(biasName,out var b)||!root.TryGetProperty("raw_to_platform_matrix",out var m))
            throw new InvalidDataException("常温JSON缺少 "+biasName+" / raw_to_platform_matrix");
        var bias=CalibrationJson.Vector(b,3);var mat=CalibrationJson.Matrix(m);
        if(Math.Abs(CalibrationJson.Determinant(mat))<1e-9)throw new InvalidDataException("常温校准矩阵不可逆");
        int? fs=null;bool verified=false;
        if(root.TryGetProperty("sensor_configuration",out var cfg)&&cfg.ValueKind==JsonValueKind.Object)
        {
            var key=biasName=="raw_accel_bias_g"?"acc_fs_g":"gyro_fs_dps";
            if(cfg.TryGetProperty(key,out var f)&&f.TryGetInt32(out var n))fs=n;
            var vkey=biasName=="raw_accel_bias_g"?"acc_full_scale_mcu_verified":"gyro_full_scale_mcu_verified";
            verified=cfg.TryGetProperty(vkey,out var v)&&v.ValueKind==JsonValueKind.True;
        }
        return new CalibrationMatrix{FilePath=file,Sha256=CalibrationJson.Hash(file),
            FullUidVerified=CalibrationJson.VerifiedUid(root,hw),IsSimulation=false,
            Bias=bias,Matrix=mat,FsHint=fs,McuRangeVerifiedByFile=verified,
            RunId=root.TryGetProperty("run_id",out var run)?run.ToString():""};
    }
}

/// <summary>F(T)=sum forward_coeff[k]*(T-center)^k, b(T) likewise, calibrated=F(T)^-1 (physical-b(T)).</summary>
public sealed class ThermalCalibration : CalibrationSource
{
    public required string Sensor {get;init;}
    public required double CenterC {get;init;}
    public required double MinC {get;init;}
    public required double MaxC {get;init;}
    public required double[][] BiasCoeff {get;init;}
    public required double[][][] ForwardCoeff {get;init;}
    public required int Degree {get;init;}
    public double[] Apply(double x,double y,double z,double temperatureC)
    {
        if(!double.IsFinite(temperatureC)||temperatureC<MinC||temperatureC>MaxC)
            throw new InvalidDataException($"芯片温度 {temperatureC:F2}°C 超出全温模型 [{MinC},{MaxC}]°C，拒绝外推");
        double t=temperatureC-CenterC;
        static double Poly(double[] c,double u)
        {
            double v=0;for(int k=c.Length-1;k>=0;k--)v=v*u+c[k];return v;
        }
        var b=BiasCoeff.Select(c=>Poly(c,t)).ToArray();
        var f=ForwardCoeff.Select(row=>row.Select(c=>Poly(c,t)).ToArray()).ToArray();
        var inverse=CalibrationJson.Inverse3(f);
        return CalibrationJson.Multiply(inverse,new[]{x-b[0],y-b[1],z-b[2]});
    }
    public static ThermalCalibration Load(string file,DeviceIdentity hw,string expectedSensor)
    {
        using var doc=JsonDocument.Parse(File.ReadAllText(file));var r=doc.RootElement;
        CalibrationJson.CheckIdentity(r,file,hw);
        if(!r.TryGetProperty("sensor",out var sens) || !string.Equals(sens.GetString(),expectedSensor,StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("全温JSON sensor 字段与文件类型不符");
        if(!r.TryGetProperty("temperature_variable",out var variable)||
           !variable.ToString().Contains("IMU",StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("全温模型必须声明使用 IMU 芯片温度");
        int degree=r.GetProperty("polynomial_degree").GetInt32();
        if(degree<0||degree>3)throw new InvalidDataException("不支持的全温多项式阶数，仅允许0～3");
        double center=r.GetProperty("temperature_center_c").GetDouble();
        var range=CalibrationJson.Vector(r.GetProperty("fit_temperature_range_c"),2);
        if(!double.IsFinite(center)||range[0]>=range[1]||range[0]<-80||range[1]>150)
            throw new InvalidDataException("全温拟合温度范围无效");
        var bias=r.GetProperty("bias_coeff");
        var forward=r.GetProperty("forward_coeff");
        if(bias.ValueKind!=JsonValueKind.Array || bias.GetArrayLength()!=3 ||
           forward.ValueKind!=JsonValueKind.Array || forward.GetArrayLength()!=3)
            throw new InvalidDataException("全温系数必须有3个轴");
        var bs=bias.EnumerateArray().Select(e=>CalibrationJson.Vector(e,degree+1)).ToArray();
        var fm=forward.EnumerateArray().Select(row=>
        {
            if(row.ValueKind!=JsonValueKind.Array||row.GetArrayLength()!=3)
                throw new InvalidDataException("全温 forward_coeff 必须为3×3×(degree+1)");
            return row.EnumerateArray().Select(e=>CalibrationJson.Vector(e,degree+1)).ToArray();
        }).ToArray();
        var model=new ThermalCalibration{FilePath=file,Sha256=CalibrationJson.Hash(file),
            FullUidVerified=CalibrationJson.VerifiedUid(r,hw),IsSimulation=false,
            Sensor=expectedSensor,CenterC=center,MinC=range[0],MaxC=range[1],Degree=degree,
            BiasCoeff=bs,ForwardCoeff=fm,RunId=r.TryGetProperty("run_id",out var id)?id.ToString():""};
        // Ensure the model is physically solvable in its declared operating interval.
        foreach(double tc in new[]{range[0],(range[0]+range[1])/2,range[1]})
            _=model.Apply(0,0,0,tc);
        return model;
    }
}
