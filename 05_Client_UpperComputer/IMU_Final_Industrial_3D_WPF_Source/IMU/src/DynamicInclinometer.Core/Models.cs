using System.Numerics;
namespace DynamicInclinometer.Core;

public readonly record struct ImuSample(long Sequence, double TimeSeconds, Vector3 AccG, Vector3 GyroDps, double TemperatureC, bool ScaleVerified, bool TimingVerified, bool Synthetic, long HostArrivalTicks = 0);
public readonly record struct AttitudeState(Quaternion Quaternion, double RollDeg, double PitchDeg, double YawRelativeDeg, bool IsSixAxis, string Quality);
public enum ProcessingMode { AccelerometerOnly, Mahony, Eskf }

public static class TiltMath
{
    public static (double roll, double pitch) FromAcceleration(Vector3 a)
    {
        // RPY convention: body-to-world, XYZ intrinsic; axis sign must be verified against PCB reference.
        if (a.LengthSquared() < 1e-10f) return (double.NaN,double.NaN);
        return (Math.Atan2(a.Y, a.Z)*180/Math.PI,
                Math.Atan2(-a.X, Math.Sqrt(a.Y*a.Y+a.Z*a.Z))*180/Math.PI);
    }
    public static Quaternion FromTilt(double rollDeg, double pitchDeg)
        => Quaternion.CreateFromYawPitchRoll(0f, (float)(pitchDeg*Math.PI/180), (float)(rollDeg*Math.PI/180));
}

public static class MatrixMath
{
    public static Vector3 Apply(double[][] m, Vector3 v)
      => new((float)(m[0][0]*v.X + m[0][1]*v.Y + m[0][2]*v.Z),
             (float)(m[1][0]*v.X + m[1][1]*v.Y + m[1][2]*v.Z),
             (float)(m[2][0]*v.X + m[2][1]*v.Y + m[2][2]*v.Z));
    public static double[][] Inverse(double[][] a)
    {
        var det=Determinant(a); if(!double.IsFinite(det)||Math.Abs(det)<1e-8)throw new ArgumentException("矩阵不可逆");
        return new [] {
          new[]{(a[1][1]*a[2][2]-a[1][2]*a[2][1])/det,(a[0][2]*a[2][1]-a[0][1]*a[2][2])/det,(a[0][1]*a[1][2]-a[0][2]*a[1][1])/det},
          new[]{(a[1][2]*a[2][0]-a[1][0]*a[2][2])/det,(a[0][0]*a[2][2]-a[0][2]*a[2][0])/det,(a[0][2]*a[1][0]-a[0][0]*a[1][2])/det},
          new[]{(a[1][0]*a[2][1]-a[1][1]*a[2][0])/det,(a[0][1]*a[2][0]-a[0][0]*a[2][1])/det,(a[0][0]*a[1][1]-a[0][1]*a[1][0])/det}
        };
    }
    public static double Determinant(double[][] a) => a[0][0]*(a[1][1]*a[2][2]-a[1][2]*a[2][1])-a[0][1]*(a[1][0]*a[2][2]-a[1][2]*a[2][0])+a[0][2]*(a[1][0]*a[2][1]-a[1][1]*a[2][0]);
}
