using System.Numerics;
namespace DynamicInclinometer.Core;

public sealed class AttitudeEngine
{
    private Quaternion _q=Quaternion.Identity;
    private Vector3 _integral=Vector3.Zero;
    private double? _lastTime;
    private bool _initialized;
    private readonly ErrorStateKalmanFilter _eskf = new();
    public ProcessingMode Mode {get;set;}=ProcessingMode.AccelerometerOnly;
    public bool AllowResearchFusionWithUnverifiedConfiguration { get;set;} = false;
    public double Kp {get;set;}=1.8;
    public double Ki {get;set;}=0.02;
    public ErrorStateKalmanFilter Eskf => _eskf;
    public void Reset(){_q=Quaternion.Identity;_integral=Vector3.Zero;_lastTime=null;_initialized=false;_eskf.Reset();}
    public AttitudeState Update(ImuSample input, CalibrationProfile cal)
    {
        var acc=cal.CorrectAcc(input.AccG);
        var (accRoll,accPitch)=TiltMath.FromAcceleration(acc);
        if(!double.IsFinite(accRoll)||!double.IsFinite(accPitch))return new(_q,0,0,0,false,"ACC 数据无效");
        if(Mode==ProcessingMode.AccelerometerOnly || !cal.HasGyro || (!input.TimingVerified && !AllowResearchFusionWithUnverifiedConfiguration) || (!input.ScaleVerified && !AllowResearchFusionWithUnverifiedConfiguration))
        {
            _q=TiltMath.FromTilt(accRoll,accPitch);
            _lastTime=input.TimeSeconds;_initialized=false;
            return new(_q,accRoll,accPitch,0,false,"ACC 静态倾角 · 融合未启用");
        }
        double dt=_lastTime.HasValue?input.TimeSeconds-_lastTime.Value:0;
        _lastTime=input.TimeSeconds;
        if (!_initialized)
        {
            _q=TiltMath.FromTilt(accRoll,accPitch);
            _eskf.Initialize(acc);
            _initialized=true;
            return State(_q,true,"姿态初始化 · 等待下一有效样本");
        }
        if (!(dt>0 && dt<=0.1) || !double.IsFinite(dt))
        {
            Reset();return new(TiltMath.FromTilt(accRoll,accPitch),accRoll,accPitch,0,false,"时间戳跳变：融合重置");
        }
        var gyro=cal.CorrectGyro(input.GyroDps)*(float)(Math.PI/180);
        if (Mode == ProcessingMode.Eskf)
        {
            _eskf.Step(acc,gyro,dt);
            _q=_eskf.Orientation;
            return State(_q,true,_eskf.LastGravityUpdateAccepted?"ESKF · 重力更新有效":"ESKF · 仅惯性预测 / 观测拒绝");
        }
        var norm=acc.Length();
        if(norm>0.8f&&norm<1.2f)
        {
            var measured=Vector3.Normalize(acc);
            var estimated=Vector3.Transform(Vector3.UnitZ,Quaternion.Inverse(_q));
            var error=Vector3.Cross(measured,estimated);
            _integral+=error*(float)(Ki*dt);
            gyro+=(float)Kp*error+_integral;
        }
        var dq=ErrorStateKalmanFilter.Exp(gyro*(float)dt);
        _q=Quaternion.Normalize(Quaternion.Multiply(_q,dq));
        return State(_q,true,"Mahony · 六轴姿态");
    }
    private static AttitudeState State(Quaternion q,bool fused,string label)
    {
        var sinr=2*(q.W*q.X+q.Y*q.Z);
        var cosr=1-2*(q.X*q.X+q.Y*q.Y);
        var sinp=2*(q.W*q.Y-q.Z*q.X);
        var yaw=Math.Atan2(2*(q.W*q.Z+q.X*q.Y),1-2*(q.Y*q.Y+q.Z*q.Z));
        return new(q,Math.Atan2(sinr,cosr)*180/Math.PI,Math.Asin(Math.Clamp(sinp,-1,1))*180/Math.PI,yaw*180/Math.PI,fused,label);
    }
}
