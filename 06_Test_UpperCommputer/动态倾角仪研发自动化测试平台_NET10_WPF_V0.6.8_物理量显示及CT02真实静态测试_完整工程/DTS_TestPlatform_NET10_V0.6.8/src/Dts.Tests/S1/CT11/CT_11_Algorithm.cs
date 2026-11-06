using System.Globalization;
using System.IO;
using Dts.Tests.S1.CT10;

namespace Dts.Tests.S1.CT11;

/// <summary>Dynamic, three-axis GYRO coupling and low-speed linearity. Only actual encoder speed is a reference.</summary>
public static class Ct11Algorithm
{
    public static Ct10Settings ToCt10Settings(Ct11Settings s) => new(
        s.OutputRoot, s.LowSpeedsCsv, s.TestInner, s.TestOuter,
        s.Repetitions, s.TravelMinDeg, s.TravelMaxDeg,
        s.ApprovedMinDeg, s.ApprovedMaxDeg, s.SetupSpeedDps,
        s.SettleSeconds, s.SpeedToleranceFraction,
        s.EncoderDerivativeWindowSeconds, s.MinAcceptedFrames,
        s.InnerGyroSign, s.OuterGyroSign,
        s.MotionAndCablingApproved, s.EmergencyStopConfirmed,
        s.SensorAxisMappingVerified, s.Calibration);

    /// <summary>No hardware required. Never interprets a preview as a certified speed check.</summary>
    public static IReadOnlyList<Ct10SweepRequest> Preview(Ct11Settings s)
    {
        ValidateSpeedLevels(s);
        return Ct10Algorithm.PreviewPlan(ToCt10Settings(s));
    }
    public static IReadOnlyList<Ct10SweepRequest> Plan(Ct11Settings s, ICt10DynamicHardware live)
    {
        ValidateSpeedLevels(s);
        return Ct10Algorithm.BuildPlan(ToCt10Settings(s), live);
    }
    private static void ValidateSpeedLevels(Ct11Settings s)
    {
        var speeds = Ct10Algorithm.ParseSpeeds(s.LowSpeedsCsv);
        if (speeds.Length < 3) throw new InvalidDataException("CT-11至少设置三个不同低速档位，才能分析非线性");
        if (speeds.Max() / speeds.Min() < 1.5)
            throw new InvalidDataException("低速档位跨度不足：最高与最低速度之比至少1.5");
    }

    public static Ct11SweepResult FromCt10Sweep(Ct10SweepResult s)
    {
        var accepted = s.Samples.Where(x => x.Accepted).ToArray();
        if (accepted.Length != s.AcceptedFrames || accepted.Length < 20)
            throw new InvalidDataException("CT-11有效三轴动态帧数与CT-10运动结果不一致");
        double[] mean = new[] {
            accepted.Average(x=>x.GyroXCorrectedDps),
            accepted.Average(x=>x.GyroYCorrectedDps),
            accepted.Average(x=>x.GyroZCorrectedDps)
        };
        double[] stdev = new[] {
            Std(accepted.Select(x=>x.GyroXCorrectedDps)),
            Std(accepted.Select(x=>x.GyroYCorrectedDps)),
            Std(accepted.Select(x=>x.GyroZCorrectedDps))
        };
        return new Ct11SweepResult(s.Axis,s.Direction,s.Repetition,
            s.CommandSpeedDps,s.MeanReferenceSignedDps,mean,stdev,
            s.MeanGyroSignedDps,s.MeanResidualDps,s.MeanTemperatureC,
            s.AcceptedFrames,s.TotalGyroFrames,s.EncoderFrames,s.CsvFile,
            s.AcquisitionTimeQuality,s.EvidenceSource);
    }

    private static double Std(IEnumerable<double> values)
    {
        var a=values.ToArray();double m=a.Average();
        return Math.Sqrt(a.Sum(v=>(v-m)*(v-m))/Math.Max(1,a.Length-1));
    }

    /// <summary>Two-parameter linear regression, with signed real rate as X, measured corrected GYRO as Y.</summary>
    public static Ct11Fit Fit(int gyroAxis,IReadOnlyList<(double X,double Y)> observations)
    {
        if (gyroAxis is < 0 or > 2 || observations.Count < 6)
            throw new InvalidDataException("需要至少6个正反速率点才能拟合三轴响应");
        if (observations.Any(p => !double.IsFinite(p.X) || !double.IsFinite(p.Y)))
            throw new InvalidDataException("回归数据包含非有限量");
        double xbar=observations.Average(p=>p.X),ybar=observations.Average(p=>p.Y);
        double ssx=observations.Sum(p=>Math.Pow(p.X-xbar,2));
        if(ssx < 1e-12) throw new InvalidDataException("实测转速跨度不足，不能拟合低速线性");
        double slope=observations.Sum(p=>(p.X-xbar)*(p.Y-ybar))/ssx;
        double intercept=ybar-slope*xbar;
        double[] residuals=observations.Select(p=>p.Y-(intercept+slope*p.X)).ToArray();
        double sse=residuals.Sum(r=>r*r);
        double ssy=observations.Sum(p=>Math.Pow(p.Y-ybar,2));
        double r2=ssy>1e-12?1-sse/ssy: (sse<1e-12?1:0);
        return new Ct11Fit(gyroAxis,new[]{"X","Y","Z"}[gyroAxis],observations.Count,
            intercept,slope,Math.Sqrt(sse/observations.Count),
            residuals.Max(r=>Math.Abs(r)),r2);
    }

    public static IReadOnlyList<Ct11AxisSummary> Summarize(
        IReadOnlyList<Ct11SweepResult> sweeps,int innerSign,int outerSign)
    {
        var results=new List<Ct11AxisSummary>();
        foreach (var group in sweeps.GroupBy(v=>v.Axis))
        {
            var items=group.ToArray();
            var speeds=items.Select(x=>x.CommandSpeedDps).Distinct().ToArray();
            // Require full +/- pairs for EVERY speed and repetition. Partial runs export sweeps but no fit.
            bool complete=items.GroupBy(x=>(x.CommandSpeedDps,x.Repetition))
                .All(g=>g.Count()==2 && g.Any(v=>v.Direction==Ct10Direction.Forward) &&
                    g.Any(v=>v.Direction==Ct10Direction.Reverse));
            if(speeds.Length<3||!complete||items.Length<6)continue;
            int main=group.Key==Ct10Axis.Inner?2:0;
            int sign=group.Key==Ct10Axis.Inner?innerSign:outerSign;
            if(sign is not (1 or -1))throw new InvalidDataException("Gyro轴映射符号必须是±1");
            var fits=new List<Ct11Fit>();
            for(int j=0;j<3;j++)
            {
                int k=j;
                var data=items.Select(s=>(X:s.ReferenceSignedDps,
                    Y:s.GyroMeanDps[k]*(k==main?sign:1))).ToArray();
                fits.Add(Fit(j,data));
            }
            var mainFit=fits[main];
            double maxReal=items.Max(s=>Math.Abs(s.ReferenceSignedDps));
            double maxCross=fits.Where(f=>f.GyroAxis!=main)
                .Max(f=>Math.Abs(f.Slope))*100;
            results.Add(new Ct11AxisSummary(group.Key,new[]{"X","Y","Z"}[main],items.Length,
                speeds.Length,mainFit.Slope,(mainFit.Slope-1)*100,
                mainFit.InterceptDps,mainFit.ResidualRmsDps,
                mainFit.MaxAbsoluteResidualDps,
                maxReal>0?mainFit.MaxAbsoluteResidualDps/maxReal*100:double.NaN,
                fits,maxCross,
                "主轴拟合 Gyro=offset+gain×真实编码器速率；非主轴斜率是系统级轴间耦合代理，"+
                "可能包含安装偏角、转台机械耦合、编码器误差及时间戳延迟，不归因于单一IMU。"));
        }
        return results;
    }
}
