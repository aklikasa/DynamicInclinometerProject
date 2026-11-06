namespace Dts.Devices;

/// <summary>
/// Read-only safety policy for 2TD startup. The vendor's "Normal" bit may be
/// false until servo enable; it is therefore checked AFTER enabling, not as an
/// enable prerequisite. Fault flags and motion still block energizing.
/// </summary>
public static class TdConnectionPolicy
{
    public static bool Stopped(TableSnapshot value) =>
        double.IsFinite(value.Inner.SpeedDps) && double.IsFinite(value.Outer.SpeedDps) &&
        Math.Abs(value.Inner.SpeedDps) <= 0.05 && Math.Abs(value.Outer.SpeedDps) <= 0.05;

    public static bool CanRequestEnable(TableSnapshot value) =>
        double.IsFinite(value.Inner.PositionDeg) && double.IsFinite(value.Outer.PositionDeg) &&
        value.Inner.Fault == false && value.Outer.Fault == false && Stopped(value);

    public static bool CanOperate(TableSnapshot value) =>
        value.Inner.Fault == false && value.Outer.Fault == false &&
        value.Inner.Normal && value.Outer.Normal &&
        value.Inner.Enabled && value.Outer.Enabled && Stopped(value);

    // Maintained for older call sites; use CanRequestEnable for new code.
    public static bool CanAutoEnable(TableSnapshot value) => CanRequestEnable(value);

    public static string ExplainEnableBlock(TableSnapshot? value)
    {
        if (value is null) return "未取得有效的双轴反馈";
        if (value.Inner.Fault != false || value.Outer.Fault != false)
            return $"故障/限位状态未确认为无故障：内轴={value.Inner.Fault?.ToString() ?? "未知"}，外轴={value.Outer.Fault?.ToString() ?? "未知"}";
        if (!double.IsFinite(value.Inner.PositionDeg) || !double.IsFinite(value.Outer.PositionDeg))
            return "位置反馈无效";
        if (!Stopped(value))
            return $"双轴未确认静止：内轴={value.Inner.SpeedDps:F4}°/s，外轴={value.Outer.SpeedDps:F4}°/s";
        return "允许申请使能；使能结果仍需验证";
    }
}
