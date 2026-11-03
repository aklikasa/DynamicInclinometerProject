namespace Dts.Devices;

/// <summary>Pure safety decision logic for read-only startup telemetry.
/// A successful serial OpenPort never implies the axes are safe to energize.
/// </summary>
public static class TdConnectionPolicy
{
    public static bool Stopped(TableSnapshot value) =>
        double.IsFinite(value.Inner.SpeedDps) && double.IsFinite(value.Outer.SpeedDps) &&
        Math.Abs(value.Inner.SpeedDps) <= 0.05 && Math.Abs(value.Outer.SpeedDps) <= 0.05;

    public static bool CanAutoEnable(TableSnapshot value) =>
        value.Inner.Normal && value.Outer.Normal &&
        value.Inner.Fault == false && value.Outer.Fault == false &&
        Stopped(value);
}
