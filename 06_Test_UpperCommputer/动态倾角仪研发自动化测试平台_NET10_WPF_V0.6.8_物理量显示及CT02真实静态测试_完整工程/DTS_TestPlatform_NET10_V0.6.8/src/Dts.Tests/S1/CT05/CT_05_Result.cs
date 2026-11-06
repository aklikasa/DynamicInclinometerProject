using System.Globalization;
using Dts.Core;
using System.Text.Json;

namespace Dts.Tests.S1.CT05;

/// <summary>CT-05 独立配置和报告数据契约；每次运行冻结一份参数快照。</summary>
public sealed record Ct05Settings(
    string OutputRoot,
    string CalibrationJson,
    double SettleSeconds,
    double CaptureSeconds,
    double SpeedDps,
    double PositionToleranceDeg,
    double AllowedTravelMinDeg,
    double AllowedTravelMaxDeg,
    string PlanKind,
    bool OperatorApprovedFullTravel,
    bool ConfirmedActualDirection,
    bool ConfirmedCalibrationOwnership = false,
    int MinimumValidSamples = 50,
    double MaxRejectionFraction = 0.1,
    CalibrationMode ProcessingMode = CalibrationMode.Ambient)
{
    /// <summary>Single parent calibration folder, which may contain arbitrary subfolders.</summary>
    public string CalibrationRoot {get;init;} = "";
    /// <summary>Locked UID-matched calibration data supplied by the host, not a local picker.</summary>
    [System.Text.Json.Serialization.JsonIgnore]
    public CalibrationRun? RunCalibration {get;init;}
}

public sealed record Ct05PlanPoint(string Channel, double InnerTargetDeg,
    double OuterSignedDeg, double OuterCommandDeg);

public sealed record Ct05PointResult(
    int Index, string Channel, double InnerCommandDeg, double OuterCommandDeg,
    double InnerActualDeg, double OuterActualDeg,
    double ReferenceDeg, double MeasuredDeg, double ErrorDeg,
    double NormG, double[] RawG, double[] CorrectedG,
    double[] StdG, int Samples, int AcceptedSamples, double RejectedFraction,
    DateTimeOffset StartUtc, DateTimeOffset EndUtc, string RawCsvFile, double TemperatureC);

public sealed record Ct05Summary(
    string TestId, string UidRaw, string DtsId,
    string CalibrationFile, string CalibrationSha256,
    string StartedUtc, string CompletedUtc, string Status,
    string ErrorMessage, Ct05Settings Settings,
    IReadOnlyList<Ct05PointResult> Points,
    double? BiasDeg, double? RmseDeg, double? MaxAbsErrorDeg,
    string Evaluation = "研发测量结果，未设置正式验收限值；非产品 PASS");

public sealed class Ct05Calibration
{
    public required double[] Bias {get;init;}
    public required double[][] Matrix {get;init;}
    public string DeviceSerial {get;init;} = "";
    public string RunId {get;init;} = "";
    public double[] Apply(double[] raw)
    {
        var v=new double[3];
        for(int i=0;i<3;i++)
            for(int j=0;j<3;j++)v[i]+=Matrix[i][j]*(raw[j]-Bias[j]);
        return v;
    }
    public static Ct05Calibration Load(string file)
    {
        using var doc=JsonDocument.Parse(File.ReadAllText(file));
        var root=doc.RootElement;
        static double[] Vector(JsonElement el, int n)
        {
            if(el.ValueKind!=JsonValueKind.Array||el.GetArrayLength()!=n)throw new InvalidDataException($"期望 {n} 个数字");
            var a=el.EnumerateArray().Select(x=>x.GetDouble()).ToArray();
            if(a.Any(x=>!double.IsFinite(x)))throw new InvalidDataException("校准值存在无效浮点数");
            return a;
        }
        var bias=Vector(root.GetProperty("raw_accel_bias_g"),3);
        var matrix=root.GetProperty("raw_to_platform_matrix");
        if(matrix.ValueKind!=JsonValueKind.Array||matrix.GetArrayLength()!=3)
            throw new InvalidDataException("raw_to_platform_matrix 必须为 3x3 数组");
        double[][] m=matrix.EnumerateArray().Select(x=>Vector(x,3)).ToArray();
        double determinant=m[0][0]*(m[1][1]*m[2][2]-m[1][2]*m[2][1])
            -m[0][1]*(m[1][0]*m[2][2]-m[1][2]*m[2][0])
            +m[0][2]*(m[1][0]*m[2][1]-m[1][1]*m[2][0]);
        if(Math.Abs(determinant)<1e-9)throw new InvalidDataException("校准矩阵奇异");
        return new Ct05Calibration{Bias=bias,Matrix=m,
            DeviceSerial=root.TryGetProperty("device_serial",out var d)?d.ToString():"",
            RunId=root.TryGetProperty("run_id",out var r)?r.ToString():""};
    }
}
