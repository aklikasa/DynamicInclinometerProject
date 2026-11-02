using System;
using System.IO;
using System.Numerics;
using System.Collections.Generic;
using DynamicInclinometer.Core;
using DynamicInclinometer.Devices;
using System.Text.Json.Nodes;

void Assert(bool ok,string title)
{
    if(!ok)throw new Exception("FAILED: "+title);
    Console.WriteLine("PASS: "+title);
}
string file=args.Length>0?args[0]:Path.GetFullPath("samples/accel_calibration_device_0002.json");
var cal=CalibrationProfile.Load(file);
Assert(cal.DeviceSerial=="0002","ACC calibration is bound to device 0002");
Assert(cal.Verdict=="PILOT_PASS_NOT_RELEASED","pilot verdict is preserved");
Assert(!cal.ApprovedForProduction,"pilot cannot be released");
Assert(!cal.HasGyro,"ACC calibration does not impersonate gyro calibration");
var c=cal.CorrectAcc(new Vector3(0.02802529f,0.00551707f,1.00923300f));
Assert((c-Vector3.UnitZ).Length()<0.02,"ACC frame correction gives reference gravity");
var id=MatrixMath.Apply(cal.AccMatrix,MatrixMath.Apply(MatrixMath.Inverse(cal.AccMatrix),new Vector3(.2f,.3f,.4f)));
Assert((id-new Vector3(.2f,.3f,.4f)).Length()<1e-5,"matrix inverse roundtrip");
Assert(ImuProtocol.Request(1).Length==8,"Modbus RTU frame length");
var req=ImuProtocol.Request(1); Assert(ImuProtocol.Crc(req)==0,"Modbus CRC appended correctly");
var level=TiltMath.FromAcceleration(Vector3.UnitZ);
Assert(Math.Abs(level.roll)<1e-8&&Math.Abs(level.pitch)<1e-8,"level tilt zero");
var e=new AttitudeEngine {Mode=ProcessingMode.Eskf};
var state=e.Update(new ImuSample(0,0,Vector3.UnitZ,Vector3.Zero,25,true,true,false),cal);
Assert(!state.IsSixAxis,"gyro calibration gate disables ESKF");

// ABS/REL display reference: never change the underlying fused ABS record.
var zeroQ=Quaternion.CreateFromAxisAngle(Vector3.UnitX,(float)(10*Math.PI/180));
var newerQ=Quaternion.CreateFromAxisAngle(Vector3.UnitX,(float)(15*Math.PI/180));
var zeroAbs=new AttitudeState(zeroQ,10,0,0,true,"ESKF");
var newerAbs=new AttitudeState(newerQ,15,0,0,true,"ESKF");
var relZero=TiltReferenceMath.RelativeTo(zeroAbs,zeroQ);
var relFive=TiltReferenceMath.RelativeTo(newerAbs,zeroQ);
Assert(Math.Abs(relZero.RollDeg)<.0001 && Math.Abs(relZero.PitchDeg)<.0001,
    "REL reference pose becomes zero without resetting ESKF");
Assert(Math.Abs(relFive.RollDeg-5)<.002 && Math.Abs(relFive.PitchDeg)<.002,
    "ABS 10° reference then ABS 15° produces REL +5°");
Assert(newerAbs.RollDeg==15 && Math.Abs(newerAbs.Quaternion.X-newerQ.X)<1e-8,
    "REL output does not modify ABS state or original quaternion");
try {TiltReferenceMath.RelativeTo(newerAbs,new Quaternion(0,0,0,0));throw new Exception("zero quaternion must fail");}
catch(ArgumentException){Console.WriteLine("PASS: invalid relative reference quaternion is rejected");}
var pitchRef=Quaternion.CreateFromAxisAngle(Vector3.UnitY,(float)(-10*Math.PI/180));
var pitchNew=Quaternion.CreateFromAxisAngle(Vector3.UnitY,(float)(-5*Math.PI/180));
var relPitch=TiltReferenceMath.RelativeTo(new AttitudeState(pitchNew,0,-5,0,true,"ESKF"),pitchRef);
Assert(Math.Abs(relPitch.PitchDeg-5)<.002,"REL pitch responds to positive 5° increment");


var f=new ErrorStateKalmanFilter();
const double dt=.005,rate=10.0;
for(int k=0;k<1001;k++)
{
    double angle=k*dt*rate*Math.PI/180;
    var quat=Quaternion.CreateFromAxisAngle(Vector3.UnitX,(float)angle);
    var gravity=Vector3.Transform(Vector3.UnitZ,Quaternion.Inverse(quat));
    f.Step(gravity,new Vector3((float)(rate*Math.PI/180),0,0),dt);
}
var q=f.Orientation;
var roll=Math.Atan2(2*(q.W*q.X+q.Y*q.Z),1-2*(q.X*q.X+q.Y*q.Y))*180/Math.PI;
Assert(Math.Abs(roll-50)<1,"ESKF follows 50° rotation from consistent rate and gravity");
Assert(Math.Abs(q.Length()-1)<1e-5,"ESKF quaternion remains unit norm");

var refs=new List<AnglePoint>();
for(int i=0;i<60;i++)refs.Add(new(i*.01,5,10));
var samples=new List<AnglePoint>{new(.155,5.03,9.98),new(.205,4.98,10.01)};
var m=AngleEvaluator.Evaluate(samples,refs);
Assert(m.Count==2,"reference interpolation matches timestamp pairs");
Assert(m.RollMaxAbsDeg<.04&&m.PitchMaxAbsDeg<.04,"angle error metrics correctly computed");
var window=new List<AnglePoint>();for(int i=0;i<=600;i++)window.Add(new(i*.01,5.02,9.99));
var sm=StaticWindowEvaluator.EvaluateLastSeconds(window,5,10);
Assert(sm.Samples>400&&sm.Errors.RollRmseDeg<.03,"5-second static evaluation");
// No-motor regression: verify zero reference vs zero position and safe staged route.
var nearHalfTurn=AxisZeroPositionPlanner.Plan(179.87,0,20);
Assert(nearHalfTurn.Count==9 && nearHalfTurn[^1]==0.0 &&
       Math.Abs(AxisZeroPositionPlanner.TotalTravel(179.87,nearHalfTurn)-179.87)<1e-8,
       "179.87° -> 0° is staged (not rejected by the old 90° limit)");
Assert(AxisZeroPositionPlanner.Plan(359.87,0).Count==0 &&
       AxisZeroPositionPlanner.AngularDistance(359.87,0)<.20,
       "359.87° is equivalent to zero and requires no motion");
var forward=AxisZeroPositionPlanner.Plan(250,0);
Assert(forward.Count==6 && Math.Abs(forward[^1]-359.85)<.00001 &&
       AxisZeroPositionPlanner.AngularDistance(forward[^1],0)<.20,
       "250° -> 0° approaches 360° from below rather than issuing a 250° ambiguous move");
var small=AxisZeroPositionPlanner.Plan(18,0);
Assert(small.Count==1 && small[0]==0,"small move goes to 0° directly");
try { AxisZeroPositionPlanner.Plan(359.0,90);throw new Exception("must block wrap crossing"); }
catch(InvalidOperationException){Console.WriteLine("PASS: ambiguous 360° -> 90° boundary blocked");}
Console.WriteLine("All smoke tests passed (algorithm tests are not metrological validation)");

// Compatibility with the real full-precision gyroscope calibration exported by the legacy tool.
string gyroFile = args.Length > 1 ? args[1] : Path.GetFullPath("samples/gyro_calibration_device_0002.json");
if (File.Exists(gyroFile))
{
    var gcal = cal.WithGyro(gyroFile);
    Assert(gcal.HasGyro && gcal.DeviceSerial == "0002", "GYRO V3 import and device binding");
    Assert(gcal.GyroVerdict == "PILOT_PASS_NOT_RELEASED" && !gcal.GyroApprovedForProduction,
        "GYRO pilot verdict retained without false product approval");
    var measured = new Vector3(4.0724657f, -7.4040926f, 4.0393907f);
    var corrected = gcal.CorrectGyro(measured);
    Assert(Math.Abs(corrected.Z - 1.0f) < 0.03 && Math.Abs(corrected.X) < 0.03 && Math.Abs(corrected.Y) < 0.03,
        "GYRO real measured rotation maps to platform reference");

    // An arbitrary schema number or type label must not reject valid calibration data.
    string temporary = Path.Combine(Path.GetTempPath(), "wpf_calibration_test_" + Guid.NewGuid().ToString("N") + ".json");
    try
    {
        var json = JsonNode.Parse(File.ReadAllText(gyroFile))!.AsObject();
        json["schema_version"] = 999;
        json["calibration_type"] = "another_internal_name";
        File.WriteAllText(temporary, json.ToJsonString());
        Assert(cal.WithGyro(temporary).HasGyro, "version and descriptive type are not rejection gates");
        json.Remove("schema_version");
        json["device_serial"] = "0003";
        File.WriteAllText(temporary, json.ToJsonString());
        try { cal.WithGyro(temporary); throw new Exception("must reject device mismatch"); }
        catch (InvalidDataException) { Console.WriteLine("PASS: cross-device GYRO rejected"); }

        json["device_serial"] = "0002";
        json["raw_to_platform_matrix"] = JsonNode.Parse("[[1,2],[3],[4]]");
        File.WriteAllText(temporary, json.ToJsonString());
        try { cal.WithGyro(temporary); throw new Exception("must reject invalid matrix"); }
        catch (InvalidDataException) { Console.WriteLine("PASS: malformed 3x3 matrix rejected"); }
    }
    finally { try { File.Delete(temporary); } catch { } }
}
else Console.WriteLine("WARN: gyro example missing, extended JSON acceptance regression skipped");
Console.WriteLine("Calibration compatibility regressions passed");

// Parameterized sine-plan and static-plan regressions (NO hardware motion).
var sine = new SineSweepPlan(SweepAxis.Roll,5,0.15,4,0,200);
sine.Validate();
Assert(Math.Abs(sine.AnglesAt(0).roll)<1e-8,"sine initial position is neutral");
Assert(Math.Abs(sine.AnglesAt(sine.DurationSeconds).roll)<1e-8,"sine final position is neutral");
Assert(Math.Abs(sine.AnglesAt(2*sine.PeriodSeconds+SineSweepPlan.RestSeconds+.25*sine.PeriodSeconds).roll-5)<.01,
    "sine middle plateau achieves specified amplitude");
var tempRun=Path.Combine(Path.GetTempPath(),"sine-plan-smoke-"+Guid.NewGuid().ToString("N"));
try
{
    sine.WritePlan(tempRun);
    Assert(File.Exists(Path.Combine(tempRun,"sine_plan.json")),"parameterized plan JSON saved");
    Assert(File.Exists(Path.Combine(tempRun,"reference_planned_NOT_ENCODER.csv")),"ideal planned reference is clearly not an encoder measurement");
    new StaticScanPlan(-180,180,10,3,5).WritePlan(tempRun);
    var planLines=File.ReadAllLines(Path.Combine(tempRun,"static_positions_NOT_EXECUTED.csv"));
    Assert(planLines.Length==75,"static report plan produces exactly 74 positions + CSV header");
    try {new SineSweepPlan(SweepAxis.Roll,5,.005,200,0,200).Validate();throw new Exception("must reject unrealistic sample count");}
    catch(ArgumentOutOfRangeException){Console.WriteLine("PASS: too-long or too-large plan rejected");}
}
finally {try {Directory.Delete(tempRun,true);} catch {}}
Console.WriteLine("Experiment plan regressions passed (no real device commands issued)");

// Protocol FRAME PREVIEW ONLY: never transmitted to motor controller.
var preview=TurntableManualFrame.PreviewSwayFrame(true,5,0.3f);
Assert(preview.Length==46 && preview[0]==0xAA && preview[1]==0x55 && preview[4]==0xA2 && preview[31]==0xD3 && preview[45]==0xFE,
    "sway frame prototype uses manual A2/D3 and 46-byte size (not hardware verified)");
int frameSum=0;for(int j=2;j<44;j++)frameSum+=preview[j];
Assert(preview[44]==unchecked((byte)frameSum),"sway preview checksum matches documented additive algorithm");
Console.WriteLine("Motor motion commands were never sent; packet byte order still requires on-site validation");


// Regression for 0/360 boundary: comparison uses circular coordinates, motor
// movement must still have an independently authorised native trajectory.
Assert(AxisZeroPositionPlanner.AngularDistance(360,0)<1e-9,"exact 360° equals 0° for position comparison");
Assert(AxisZeroPositionPlanner.AngularDistance(359.99,0)<.02,"359.99° is near mechanical 0°");
Assert(AxisZeroPositionPlanner.Plan(360,0).Count==0,"360°→0° must not trigger pointless absolute motor command");
Assert(Math.Abs(AxisZeroPositionPlanner.SignedShortDelta(359.9,.9)-1)<1e-8,
    "crossing wrap seam from 359.9° to 0.9° is a positive 1° relative change");
Assert(Math.Abs(AxisZeroPositionPlanner.SignedShortDelta(.9,359.9)+1)<1e-8,
    "reverse seam crossing is a negative 1° relative change");
Console.WriteLine("PASS: 0/360° boundary position arithmetic; no device motion was issued");
