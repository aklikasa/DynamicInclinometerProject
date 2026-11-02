using System;
using System.Numerics;

namespace DynamicInclinometer.Core;

/// <summary>
/// Display/reference transform. The ESKF always estimates its original gravity-based attitude;
/// changing ABS/REL never changes calibration, filters, or the raw experimental record.
/// </summary>
public static class TiltReferenceMath
{
    public static AttitudeState RelativeTo(AttitudeState absolute, Quaternion reference)
    {
        Validate(reference);
        Validate(absolute.Quaternion);
        // q maps device/body coordinates into the world frame; reference^-1 * current
        // describes the device orientation in the manually zeroed reference frame.
        var refUnit = Quaternion.Normalize(reference);
        var now = Quaternion.Normalize(absolute.Quaternion);
        var relative = Quaternion.Normalize(Quaternion.Multiply(Quaternion.Conjugate(refUnit), now));
        var sinr = 2.0 * (relative.W * relative.X + relative.Y * relative.Z);
        var cosr = 1.0 - 2.0 * (relative.X * relative.X + relative.Y * relative.Y);
        var sinp = 2.0 * (relative.W * relative.Y - relative.Z * relative.X);
        var siny = 2.0 * (relative.W * relative.Z + relative.X * relative.Y);
        var cosy = 1.0 - 2.0 * (relative.Y * relative.Y + relative.Z * relative.Z);
        const double radToDeg = 180.0 / Math.PI;
        return new AttitudeState(relative,
            Math.Atan2(sinr, cosr) * radToDeg,
            Math.Asin(Math.Clamp(sinp, -1.0, 1.0)) * radToDeg,
            Math.Atan2(siny, cosy) * radToDeg,
            absolute.IsSixAxis, absolute.Quality + " · 用户相对零点");
    }

    public static bool IsValid(Quaternion q)
        => float.IsFinite(q.X) && float.IsFinite(q.Y) && float.IsFinite(q.Z) &&
           float.IsFinite(q.W) && q.LengthSquared() > 0.0001f;

    private static void Validate(Quaternion q)
    {
        if (!IsValid(q)) throw new ArgumentException("姿态四元数无效，不能设置或计算相对倾角");
    }
}
