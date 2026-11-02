using System;
using System.Collections.Generic;

namespace DynamicInclinometer.Core;

/// <summary>
/// Pure path preview for the 2TD-600 0°/360° periodic position indicator.
/// Planning is not a safety certification: native controller direction and fixture clearance
/// must be approved on site before any physical motion.
/// </summary>
public static class AxisZeroPositionPlanner
{
    // Normalize only for comparison/reporting. It does not imply that the native
    // controller has a known direction or safe physical route across this seam.
    public static double Normalize360(double degrees)
    {
        if(!double.IsFinite(degrees))throw new ArgumentOutOfRangeException(nameof(degrees));
        return ((degrees % 360) + 360) % 360;
    }
    public static double SignedShortDelta(double from,double to)
    {
        double delta=Normalize360(to)-Normalize360(from);
        return ((delta+540)%360)-180;
    }
    public static double AngularDistance(double actual,double target)
    {
        if(!double.IsFinite(actual)||!double.IsFinite(target))return double.PositiveInfinity;
        return Math.Abs(SignedShortDelta(target,actual));
    }
    public static IReadOnlyList<double> Plan(double actual,double target,double maxStep=20.0)
    {
        if(!double.IsFinite(actual)||actual<0||actual>360||!double.IsFinite(target)||
           (target!=0 && target!=90) || !double.IsFinite(maxStep)||maxStep<=0||maxStep>20)
            throw new ArgumentOutOfRangeException(nameof(actual),
                "自动定位须提供0≤反馈角<360、目标0°或90°、单段步长≤20°；异常角度不得推测方向");
        if(AngularDistance(actual,target)<=.30)return Array.Empty<double>();
        if(actual==360)actual=0; // exact 360° feedback is valid and equivalent to 0°
        double endpoint=target;
        // Approach 360° from below and stop at a calibrated 0°-equivalent position.
        // Do not command a single ambiguous absolute position 0° from e.g. 250°.
        if(target==0 && actual>180)endpoint=359.85;
        // Moving from a 360°-side position to 90° would require crossing a wrap boundary;
        // the vendor's choice of motion direction has not been validated, so do not infer a route.
        if(target==90 && actual>340)
            throw new InvalidOperationException("跨0°/360°的轴向运动必须走带现场确认与编码器反馈的相对增量专用流程；不可作为普通绝对定位规划");
        double distance=Math.Abs(endpoint-actual);
        if(distance<.001)return Array.Empty<double>();
        int count=(int)Math.Ceiling(distance/maxStep);
        var result=new List<double>(count);
        for(int i=1;i<=count;i++)result.Add(actual+(endpoint-actual)*i/count);
        return result;
    }
    public static double TotalTravel(double start,IReadOnlyList<double> waypoints)
    {
        double distance=0,previous=start;
        foreach(double waypoint in waypoints)
        {
            distance+=Math.Abs(waypoint-previous);
            previous=waypoint;
        }
        return distance;
    }
}
