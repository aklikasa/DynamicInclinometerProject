using System.Numerics;

namespace DynamicInclinometer.Core;

/// <summary>
/// 6-error-state attitude ESKF: [right attitude error(rad), residual gyro bias(rad/s)].
/// Nominal body-to-world quaternion; observed specific-force direction +Z at rest.
/// No translational position or velocity claims. Single-precision sensor vectors, double-precision covariance.
/// </summary>
public sealed class ErrorStateKalmanFilter
{
    private Quaternion _q = Quaternion.Identity;
    private Vector3 _bias = Vector3.Zero;
    private double[,] _p = new double[6, 6];
    private bool _initialized;
    public double GyroNoiseRadPerSqrtSecond { get; set; } = 0.003;
    public double GyroBiasRandomWalkRadPerSqrtSecond { get; set; } = 0.00015;
    public double GravityDirectionNoise { get; set; } = 0.012;
    public double MaxGravityNormDeparture { get; set; } = 0.12;
    public double MaxNis { get; set; } = 16.27; // 99.9% chi-square, 3-dimensional innovation
    public Quaternion Orientation => _q;
    public Vector3 ResidualGyroBiasRadPerSecond => _bias;
    public double RollSigmaDeg => Math.Sqrt(Math.Max(0, _p[0, 0])) * 180 / Math.PI;
    public double PitchSigmaDeg => Math.Sqrt(Math.Max(0, _p[1, 1])) * 180 / Math.PI;
    public bool LastGravityUpdateAccepted { get; private set; }
    public double LastNis { get; private set; } = double.NaN;

    public void Reset()
    {
        _initialized = false; _q = Quaternion.Identity; _bias = Vector3.Zero;
        _p = new double[6, 6]; LastNis = double.NaN;
        LastGravityUpdateAccepted = false;
        for (int i = 0; i < 3; i++) _p[i, i] = Math.Pow(8 * Math.PI / 180, 2);
        for (int i = 3; i < 6; i++) _p[i, i] = Math.Pow(0.5 * Math.PI / 180, 2);
    }
    public ErrorStateKalmanFilter() { Reset(); }

    public void Initialize(Vector3 correctedAcceleration)
    {
        var (roll, pitch) = TiltMath.FromAcceleration(correctedAcceleration);
        if (!double.IsFinite(roll) || !double.IsFinite(pitch)) throw new ArgumentException("Invalid gravity vector");
        _q = TiltMath.FromTilt(roll, pitch);
        _initialized = true;
        for (int i = 0; i < 3; i++) _p[i, i] = Math.Pow(2.5 * Math.PI / 180, 2);
    }

    public void Step(Vector3 accG, Vector3 gyroRadPerSec, double dt)
    {
        if (!_initialized) { Initialize(accG); return; }
        if (!(dt > 0 && dt <= 0.1) || !double.IsFinite(dt)) throw new ArgumentOutOfRangeException(nameof(dt));
        if (!Valid(accG) || !Valid(gyroRadPerSec)) throw new ArgumentException("Nonfinite sensor sample");
        var omega = gyroRadPerSec - _bias;
        var dtheta = omega * (float)dt;
        _q = Quaternion.Normalize(Quaternion.Multiply(_q, Exp(dtheta)));

        // First-order right-error propagation F=[I-[omega]x*dt, -I*dt; 0,I].
        var f = Identity(6);
        var w = Skew(omega);
        for (int r = 0; r < 3; r++)
          for (int c = 0; c < 3; c++) f[r, c] -= w[r, c] * dt;
        for (int i = 0; i < 3; i++) f[i, i + 3] = -dt;
        var next = Mul(Mul(f, _p), Transpose(f));
        for (int i = 0; i < 3; i++)
        {
            next[i, i] += GyroNoiseRadPerSqrtSecond * GyroNoiseRadPerSqrtSecond * dt;
            next[i+3, i+3] += GyroBiasRandomWalkRadPerSqrtSecond * GyroBiasRandomWalkRadPerSqrtSecond * dt;
        }
        _p = Symmetrize(next);
        LastGravityUpdateAccepted = false; LastNis = double.NaN;

        double n = accG.Length();
        if (n < 0.5 || Math.Abs(n - 1) > MaxGravityNormDeparture) return;
        var z = Vector3.Normalize(accG);
        var h = PredictedGravity(_q);
        var residual = new[] { (double)z.X - h.X, (double)z.Y - h.Y, (double)z.Z - h.Z };
        // Use derivative of predicted observation w.r.t. right-attitude perturbation;
        // numerical Jacobian fixes sign/convention and avoids reusing wrong body/world Jacobians.
        const float eps = 0.0001f;
        var H = new double[3, 6];
        for (int j = 0; j < 3; j++)
        {
            var d = j == 0 ? new Vector3(eps, 0, 0) : j == 1 ? new Vector3(0, eps, 0) : new Vector3(0, 0, eps);
            var hp = PredictedGravity(Quaternion.Normalize(Quaternion.Multiply(_q, Exp(d))));
            var hm = PredictedGravity(Quaternion.Normalize(Quaternion.Multiply(_q, Exp(-d))));
            H[0, j] = (hp.X-hm.X)/(2*eps);
            H[1, j] = (hp.Y-hm.Y)/(2*eps);
            H[2, j] = (hp.Z-hm.Z)/(2*eps);
        }
        var ht = Transpose(H);
        var R = Identity(3);
        // Inflate covariance as norm departs from 1g. Norm test alone cannot detect all linear accelerations.
        double sigma = GravityDirectionNoise * (1 + 15 * Math.Abs(n - 1));
        for (int i = 0; i < 3; i++) R[i, i] = sigma*sigma;
        var S = Add(Mul(Mul(H, _p), ht), R);
        if (!Inverse3(S, out var Sinv)) return;
        var nisVector = Mul(Sinv, residual);
        LastNis = Dot(residual, nisVector);
        if (!double.IsFinite(LastNis) || LastNis > MaxNis) return;
        var K = Mul(Mul(_p, ht), Sinv); // 6x3
        var delta = Mul(K, residual);
        _q = Quaternion.Normalize(Quaternion.Multiply(_q, Exp(new Vector3((float)delta[0], (float)delta[1], (float)delta[2]))));
        _bias += new Vector3((float)delta[3], (float)delta[4], (float)delta[5]);
        // Physical gyro residuals should be small; clamp fault-induced covariance divergence.
        if (_bias.Length() > 15 * Math.PI / 180) _bias = Vector3.Normalize(_bias) * (float)(15 * Math.PI / 180);
        // Joseph covariance update: (I-KH)P(I-KH)^T + KRK^T
        var A = Sub(Identity(6), Mul(K, H));
        _p = Symmetrize(Add(Mul(Mul(A, _p), Transpose(A)), Mul(Mul(K, R), Transpose(K))));
        LastGravityUpdateAccepted = true;
    }

    public static Quaternion Exp(Vector3 d)
    {
        float angle = d.Length();
        if (angle < 1e-7f) return Quaternion.Normalize(new Quaternion(d * 0.5f, 1));
        float s = MathF.Sin(angle * .5f) / angle;
        return new Quaternion(d * s, MathF.Cos(angle * .5f));
    }
    private static Vector3 PredictedGravity(Quaternion q) => Vector3.Transform(Vector3.UnitZ, Quaternion.Inverse(q));
    private static bool Valid(Vector3 v) => float.IsFinite(v.X) && float.IsFinite(v.Y) && float.IsFinite(v.Z);
    private static double[,] Identity(int n) { var m = new double[n,n]; for (int i=0;i<n;i++) m[i,i]=1; return m; }
    private static double[,] Skew(Vector3 w) => new double[,] {{0,-w.Z,w.Y},{w.Z,0,-w.X},{-w.Y,w.X,0}};
    private static double[,] Transpose(double[,] a) {int nr=a.GetLength(0),nc=a.GetLength(1);var m=new double[nc,nr];for(int i=0;i<nr;i++)for(int j=0;j<nc;j++)m[j,i]=a[i,j];return m;}
    private static double[,] Mul(double[,] a,double[,] b) {int nr=a.GetLength(0),mid=a.GetLength(1),nc=b.GetLength(1);if(mid!=b.GetLength(0))throw new ArgumentException("matrix dimensions");var m=new double[nr,nc];for(int i=0;i<nr;i++)for(int k=0;k<mid;k++)for(int j=0;j<nc;j++)m[i,j]+=a[i,k]*b[k,j];return m;}
    private static double[] Mul(double[,] a,double[] b) {int nr=a.GetLength(0),nc=a.GetLength(1);if(nc!=b.Length)throw new ArgumentException("matrix dimensions");var v=new double[nr];for(int i=0;i<nr;i++)for(int j=0;j<nc;j++)v[i]+=a[i,j]*b[j];return v;}
    private static double[,] Add(double[,] a,double[,] b) {int nr=a.GetLength(0),nc=a.GetLength(1);var m=new double[nr,nc];for(int i=0;i<nr;i++)for(int j=0;j<nc;j++)m[i,j]=a[i,j]+b[i,j];return m;}
    private static double[,] Sub(double[,] a,double[,] b) {int nr=a.GetLength(0),nc=a.GetLength(1);var m=new double[nr,nc];for(int i=0;i<nr;i++)for(int j=0;j<nc;j++)m[i,j]=a[i,j]-b[i,j];return m;}
    private static double[,] Symmetrize(double[,] a) {int n=a.GetLength(0);for(int i=0;i<n;i++)for(int j=i+1;j<n;j++){var v=(a[i,j]+a[j,i])/2;a[i,j]=a[j,i]=v;}return a;}
    private static double Dot(double[] a,double[] b) {double v=0;for(int i=0;i<a.Length;i++)v+=a[i]*b[i];return v;}
    private static bool Inverse3(double[,] a,out double[,] result)
    {
        result = new double[3,3];
        double det=a[0,0]*(a[1,1]*a[2,2]-a[1,2]*a[2,1])-a[0,1]*(a[1,0]*a[2,2]-a[1,2]*a[2,0])+a[0,2]*(a[1,0]*a[2,1]-a[1,1]*a[2,0]);
        if (!(Math.Abs(det)>1e-15) || !double.IsFinite(det)) return false;
        result[0,0]=(a[1,1]*a[2,2]-a[1,2]*a[2,1])/det;result[0,1]=(a[0,2]*a[2,1]-a[0,1]*a[2,2])/det;result[0,2]=(a[0,1]*a[1,2]-a[0,2]*a[1,1])/det;
        result[1,0]=(a[1,2]*a[2,0]-a[1,0]*a[2,2])/det;result[1,1]=(a[0,0]*a[2,2]-a[0,2]*a[2,0])/det;result[1,2]=(a[0,2]*a[1,0]-a[0,0]*a[1,2])/det;
        result[2,0]=(a[1,0]*a[2,1]-a[1,1]*a[2,0])/det;result[2,1]=(a[0,1]*a[2,0]-a[0,0]*a[2,1])/det;result[2,2]=(a[0,0]*a[1,1]-a[0,1]*a[1,0])/det;
        return true;
    }
}
