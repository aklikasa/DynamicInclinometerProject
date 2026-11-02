using System.IO;
using System.Numerics;
using System.Text.Json;

namespace DynamicInclinometer.Core;

/// <summary>
/// Calibration parsing is based on semantic fields, never an arbitrary JSON schema version.
/// ACC and GYRO remain independent; their device_serial must match exactly.
/// Pilot/release status is preserved, not silently promoted to production approval.
/// </summary>
public sealed class CalibrationProfile
{
    public string DeviceSerial { get; init; } = "";
    public string Verdict { get; init; } = "未提供验收结论";
    public bool ApprovedForProduction { get; init; }
    public string Frame { get; init; } = "";
    public double[] AccBias { get; init; } = Array.Empty<double>();
    public double[][] AccMatrix { get; init; } = Array.Empty<double[]>();
    public double[]? GyroBiasDps { get; init; }
    public double[][]? GyroMatrix { get; init; }
    public string GyroVerdict { get; init; } = "未加载";
    public bool GyroApprovedForProduction { get; init; }
    public string GyroFrame { get; init; } = "";
    public bool HasGyro => GyroBiasDps is { Length: 3 } && GyroMatrix is { Length: 3 };

    public static CalibrationProfile Load(string path)
    {
        using var document = JsonDocument.Parse(File.ReadAllText(path));
        var root = RequireObject(document.RootElement);
        string serial = ReadSerial(root);
        var bias = ReadVector(root, "raw_accel_bias_g", "acc_bias_g");
        var matrix = ReadMatrix(root, "raw_to_platform_matrix", "acc_to_platform_matrix");
        Check(bias, matrix, "ACC");
        var (verdict, approved) = ReadQuality(root);
        return new CalibrationProfile
        {
            DeviceSerial = serial,
            Verdict = verdict,
            ApprovedForProduction = approved,
            Frame = ReadString(root, "coordinate_frame"),
            AccBias = bias,
            AccMatrix = matrix
        };
    }

    public CalibrationProfile WithGyro(string path)
    {
        using var document = JsonDocument.Parse(File.ReadAllText(path));
        var root = RequireObject(document.RootElement);
        string serial = ReadSerial(root);
        if (!string.Equals(serial, DeviceSerial, StringComparison.Ordinal))
            throw new InvalidDataException($"设备编号不匹配：ACC={DeviceSerial}，GYRO={serial}。请使用同一台设备的校准文件。");

        // Support real gyroscope_production_ambient V3 and the older gyroscope_ambient V1.
        // Do not use schema_version or calibration_type as a rejection condition.
        var bias = ReadVector(root, "raw_gyro_bias_dps", "gyro_bias_dps");
        var matrix = ReadMatrix(root, "raw_to_platform_matrix", "gyro_to_platform_matrix");
        Check(bias, matrix, "GYRO");
        string units = ReadString(root, "units");
        if (!string.IsNullOrEmpty(units) && units is not ("dps" or "deg/s" or "°/s"))
            throw new InvalidDataException($"GYRO 单位声明为 {units}；本处理链要求 °/s，禁止未经确认的单位换算。");
        string gyroFrame = ReadString(root, "coordinate_frame");
        if (!string.IsNullOrEmpty(Frame) && !string.IsNullOrEmpty(gyroFrame))
        {
            bool bothPlatform = Frame.Contains('P') && gyroFrame.Contains('P');
            if (!bothPlatform && !string.Equals(Frame, gyroFrame, StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("ACC/GYRO 声明的校准坐标系不一致，不能直接进行六轴融合。");
        }
        var (verdict, approved) = ReadQuality(root);
        // An explicitly marked demo/template is not a real calibration even if its serial is edited.
        if (verdict.Contains("TEMPLATE", StringComparison.OrdinalIgnoreCase) ||
            verdict.Contains("NOT_CALIBRATED", StringComparison.OrdinalIgnoreCase) ||
            (root.TryGetProperty("quality_gate", out var gate) && gate.ValueKind == JsonValueKind.Object &&
             gate.TryGetProperty("verified_for_research", out var verified) && verified.ValueKind == JsonValueKind.False))
            throw new InvalidDataException("当前 GYRO 文件明确标记为未标定模板，不能用于真实融合；请加载实际试验获得的校准数据。");
        return new CalibrationProfile
        {
            DeviceSerial = DeviceSerial, Verdict = Verdict, ApprovedForProduction = ApprovedForProduction,
            Frame = Frame, AccBias = AccBias, AccMatrix = AccMatrix,
            GyroBiasDps = bias, GyroMatrix = matrix,
            GyroVerdict = verdict, GyroApprovedForProduction = approved, GyroFrame = gyroFrame
        };
    }

    private static JsonElement RequireObject(JsonElement root)
    {
        if (root.ValueKind != JsonValueKind.Object)
            throw new InvalidDataException("校准 JSON 根节点必须是对象。");
        return root;
    }

    private static string ReadSerial(JsonElement root)
    {
        var id = ReadString(root, "device_serial").Trim();
        if (string.IsNullOrEmpty(id)) throw new InvalidDataException("校准文件缺少非空 device_serial，无法绑定设备。");
        return id;
    }

    private static string ReadString(JsonElement root, string name)
        => root.TryGetProperty(name, out var prop) && prop.ValueKind == JsonValueKind.String
            ? (prop.GetString() ?? "") : "";

    private static JsonElement Required(JsonElement root, params string[] candidates)
    {
        foreach (var key in candidates)
            if (root.TryGetProperty(key, out var value)) return value;
        throw new InvalidDataException($"未找到校准字段：{string.Join(" / ", candidates)}。请加载包含零偏和三轴校正矩阵的真实校准文件。");
    }

    private static double[] ReadVector(JsonElement root, params string[] candidates)
    {
        var v = Required(root, candidates);
        if (v.ValueKind != JsonValueKind.Array) throw new InvalidDataException($"{candidates[0]} 必须是长度为 3 的数值数组。");
        return v.EnumerateArray().Select(ReadNumber).ToArray();
    }

    private static double[][] ReadMatrix(JsonElement root, params string[] candidates)
    {
        var m = Required(root, candidates);
        if (m.ValueKind != JsonValueKind.Array) throw new InvalidDataException($"{candidates[0]} 必须是 3×3 数值矩阵。");
        return m.EnumerateArray().Select(row =>
        {
            if (row.ValueKind != JsonValueKind.Array) throw new InvalidDataException("校正矩阵的每行必须是数组。");
            return row.EnumerateArray().Select(ReadNumber).ToArray();
        }).ToArray();
    }

    private static double ReadNumber(JsonElement v)
    {
        if (v.ValueKind != JsonValueKind.Number || !v.TryGetDouble(out var value) || !double.IsFinite(value))
            throw new InvalidDataException("校准参数包含非数值或无穷大/NaN。");
        return value;
    }

    private static (string verdict, bool approved) ReadQuality(JsonElement root)
    {
        if (!root.TryGetProperty("quality_gate", out var gate) || gate.ValueKind != JsonValueKind.Object)
            return ("未提供验收结论", false);
        string verdict = ReadString(gate, "verdict");
        bool approved = gate.TryGetProperty("approved_for_production", out var p) && p.ValueKind == JsonValueKind.True;
        return (string.IsNullOrWhiteSpace(verdict) ? "未提供验收结论" : verdict, approved);
    }

    private static void Check(double[] bias, double[][] matrix, string type)
    {
        if (bias.Length != 3 || matrix.Length != 3 || matrix.Any(row => row.Length != 3))
            throw new InvalidDataException($"{type} 零偏必须包含 3 个元素，校正矩阵必须为 3×3。");
        if (bias.Any(v => !double.IsFinite(v)) || matrix.SelectMany(x => x).Any(v => !double.IsFinite(v)))
            throw new InvalidDataException($"{type} 校准参数存在非有限数值。");
        double determinant = MatrixMath.Determinant(matrix);
        if (!double.IsFinite(determinant) || Math.Abs(determinant) < 1e-9)
            throw new InvalidDataException($"{type} 校正矩阵不可逆或病态，禁止使用。");
    }

    public Vector3 CorrectAcc(Vector3 raw) => MatrixMath.Apply(AccMatrix,
        raw - new Vector3((float)AccBias[0], (float)AccBias[1], (float)AccBias[2]));

    public Vector3 CorrectGyro(Vector3 raw)
    {
        if (!HasGyro) throw new InvalidOperationException("陀螺仪校准尚未加载。");
        return MatrixMath.Apply(GyroMatrix!,
            raw - new Vector3((float)GyroBiasDps![0], (float)GyroBiasDps[1], (float)GyroBiasDps[2]));
    }
}
