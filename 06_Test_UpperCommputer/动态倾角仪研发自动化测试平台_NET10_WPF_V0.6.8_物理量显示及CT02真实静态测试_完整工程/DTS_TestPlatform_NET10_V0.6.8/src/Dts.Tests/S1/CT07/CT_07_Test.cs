using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Dts.Core;
using Dts.TestEngine;
using Dts.Tests.S1.CT07;

namespace Dts.Tests.S1;

/// <summary>CT-07: leave a FIXED pose, return automatically, collect real FIFO, estimate between-return repeatability.</summary>
public sealed class CT_07_Test : TestModuleBase
{
    public override string TestId => "CT-07";
    public override bool IsExecutable => true;
    public override string Purpose => "自动回位同一姿态，区分重复定位后的ACC角度/向量重复性与静止噪声";
    public override string Procedure => "离开目标姿态→自动返回→连续3次反馈确认→静置→真实采样→重复多轮→统计/图文报告";
    public override string Priority => "P0";
    public override string ImplementationNote => "重复性含2TD回位、装夹和环境影响；不是纯IMU固有重复性；不自动判PASS。";

    public override async Task<TestExecutionResult> ExecuteAsync(TestExecutionContext context, CancellationToken ct)
    {
        if (context.Hardware is not IStaticAngleHardware hw)
            throw new InvalidOperationException("CT-07需要支持2TD反馈和真实FIFO采集的硬件接口");
        if (context.Parameters is not Ct07Settings settings)
            throw new InvalidOperationException("CT-07缺少专属窗口参数快照");
        if (!hw.IsTwoTdConnected) throw new InvalidOperationException("2TD未连接/未使能");
        var id=hw.CurrentIdentity ?? throw new InvalidOperationException("IMU未连接或未获取UID");
        var run=settings.Calibration;
        if(run.Mode!=CalibrationMode.Ambient)
            throw new InvalidOperationException("CT-07当前要求常温ACC/Gyro标定，先在主界面选择常温标定");
        run.Validate(id);
        var acc=run.Files?.Acc ?? throw new InvalidDataException("缺少UID匹配的ACC JSON");
        var gyro=run.Files?.Gyro ?? throw new InvalidDataException("缺少UID匹配的Gyro JSON");
        if(acc.FsHint is null || gyro.FsHint is null)
            throw new InvalidDataException("两份JSON未记录拟合输入量程");
        var scale=CalibrationInputScalePolicy.Resolve(acc.FsHint,gyro.FsHint,0,0)
            ?? throw new InvalidDataException("历史拟合输入量程不受支持");
        int sign=ReadGravitySignAndAxisModel(acc.FilePath);
        var plan=Ct07Algorithm.BuildPlan(settings);
        Ct07Algorithm.Validate(settings,plan);
        ValidateCalibrationHashes(run);
        await hw.VerifyImuForPrecisionTestAsync(ct);
        var first=await hw.ReadTwoTdAsync(ct);
        VerifyAxisState(first,false);
        if(!WithinApproved(first.Inner.PositionDeg,settings) || !WithinApproved(first.Outer.PositionDeg,settings))
            throw new InvalidOperationException("当前转台位置不在允许行程内；程序不会自动跨越未批准区间");
        string reportRoot=Path.GetFullPath(settings.OutputRoot);
        if(!Directory.Exists(reportRoot)) throw new DirectoryNotFoundException("报告根目录不存在："+reportRoot);
        string folder=Path.Combine(reportRoot,$"{id.DtsId}_{id.UidHex}",
            $"{DateTime.Now:yyyyMMdd_HHmmss_fff}_CT-07");
        Directory.CreateDirectory(folder);
        var visits=new List<Ct07Visit>();
        string started=DateTimeOffset.UtcNow.ToString("O"),state="RUNNING",reason="";
        string stopProblem="",reportProblem="";
        IReadOnlyList<string> reportFiles=[];
        bool motionRequested=false;
        string uid=id.UidHex;
        Ct07ReportData Snapshot() => new("CT-07","同姿态测量重复性","S1",id.DtsId,uid,
            started,DateTimeOffset.UtcNow.ToString("O"),state,reason,
            "研发诊断/待验收：跨轮误差包含转台重复定位、夹具、温度和IMU噪声，不自动判PASS",
            sign,"Python outer_x_inner_z，R=Rx(outer)Rz(inner)，重力参考基于每次实际到位反馈",
            Path.GetFileName(acc.FilePath),acc.Sha256,Path.GetFileName(gyro.FilePath),gyro.Sha256,
            "来自历史匹配JSON的输入量程："+scale.Display+"；六轴物理量只换算一次，分别应用对应矩阵",
            new Ct07SettingsSnapshot(settings.InnerTargetDeg,settings.OuterTargetDeg,
                settings.InnerExcursionDeg,settings.OuterExcursionDeg,settings.RepeatCount,
                settings.AlternateApproach,settings.SpeedDps,settings.SettleSeconds,
                settings.SampleSeconds,settings.PositionToleranceDeg,settings.AllowedMinDeg,
                settings.AllowedMaxDeg,settings.MinValidSamples,settings.MaxOutlierFraction,
                settings.DirectionAndCablingApproved),visits.ToArray(),Ct07Algorithm.Summarize(visits),
            "跨轮重复性反映整个测量系统；单轮标准差代表短期噪声；转台实际回位误差独立列示。"+
            "运动仍须现场监护实体急停；取消/故障只请求软停车，不能替代实体急停。");
        try
        {
            await File.WriteAllTextAsync(Path.Combine(folder,"calibration_identity.json"),
                JsonSerializer.Serialize(new { id.DtsId,id.UidHex,gravity_sign=sign,axis_model="outer_x_inner_z",
                    acc=new {acc.FilePath,acc.Sha256,acc.RunId,acc.FsHint},
                    gyro=new {gyro.FilePath,gyro.Sha256,gyro.RunId,gyro.FsHint},
                    note="当前标定文件只读，逐轮重检SHA256和UID" },
                    new JsonSerializerOptions {WriteIndented=true}),ct);
            motionRequested=true;
            for(int i=0;i<plan.Count;i++)
            {
                ct.ThrowIfCancellationRequested();
                if(hw.CurrentIdentity?.UidHex!=uid) throw new InvalidDataException("IMU UID变化，停止");
                ValidateCalibrationHashes(run);
                var pose=plan[i];
                context.Progress?.Report($"CT-07 [{i+1}/{plan.Count}] 离开目标姿态：内{pose.InnerDepartDeg:F2}° / 外{pose.OuterDepartDeg:F2}°");
                await MoveToAsync(hw,pose.InnerDepartDeg,pose.OuterDepartDeg,settings,ct);
                context.Progress?.Report($"CT-07 [{i+1}/{plan.Count}] {pose.Approach}：回到内{pose.InnerReturnDeg:F2}° / 外{pose.OuterReturnDeg:F2}°");
                await MoveToAsync(hw,pose.InnerReturnDeg,pose.OuterReturnDeg,settings,ct);
                await Task.Delay(TimeSpan.FromSeconds(settings.SettleSeconds),ct);
                var before=await hw.ReadTwoTdAsync(ct);
                VerifyPose(before,pose.InnerReturnDeg,pose.OuterReturnDeg,settings);
                string physical=Path.Combine(folder,$"visit_{pose.Index:D3}_physical.csv");
                string corrected=Path.Combine(folder,$"visit_{pose.Index:D3}_corrected.csv");
                context.Progress?.Report($"CT-07 [{i+1}/{plan.Count}] 同姿态真实FIFO采集{settings.SampleSeconds:F1}s");
                var capture=await hw.CaptureStaticPointAsync(physical,
                    TimeSpan.FromSeconds(settings.SampleSeconds),context.Progress,ct);
                var after=await hw.ReadTwoTdAsync(ct);
                VerifyPose(after,pose.InnerReturnDeg,pose.OuterReturnDeg,settings);
                if(Ct07Algorithm.Distance(before.Inner.PositionDeg,after.Inner.PositionDeg)>settings.PositionToleranceDeg ||
                   Ct07Algorithm.Distance(before.Outer.PositionDeg,after.Outer.PositionDeg)>settings.PositionToleranceDeg)
                    throw new InvalidDataException("采样期间真实转台位置变化超容差，拒绝本轮数据");
                ValidateCalibrationHashes(run);
                VerifyPhysicalCsvScale(physical,scale.AccFullScaleG,scale.GyroFullScaleDps);
                var analyzed=Ct07Algorithm.Analyze(pose,before,after,capture,
                    v=>acc.Apply(v[0],v[1],v[2]),v=>gyro.Apply(v[0],v[1],v[2]),
                    settings,sign,physical,corrected);
                await SaveCorrectedFramesAsync(corrected,capture,analyzed.Accepted,
                    analyzed.Acc,analyzed.Gyro,ct);
                visits.Add(analyzed.Visit);
                await Ct07Report.SaveCheckpointAsync(folder,Snapshot(),ct);
                context.Progress?.Report($"CT-07 [{i+1}/{plan.Count}] 完成回位，ACC参考误差"+
                    $"{analyzed.Visit.VectorReferenceErrorMg:F3}mg，有效{analyzed.Visit.AcceptedSamples}帧");
            }
            state="COMPLETED_PENDING_ACCEPTANCE";
            reason=$"完成{visits.Count}次真实离位-回位-采集，已自动计算重复性，需独立判据验收";
        }
        catch(OperationCanceledException)
        {
            state="CANCELLED_PARTIAL";reason="用户取消，保留已完成轮次的记录";throw;
        }
        catch(Exception ex)
        {
            state="FAILED_PARTIAL";reason=ex.Message;throw;
        }
        finally
        {
            if(motionRequested)
            {
                try { await hw.StopTwoTdBothAsync(CancellationToken.None); }
                catch(Exception ex)
                {
                    stopProblem=ex.Message;state="STOP_NOT_CONFIRMED";
                    reason += "；软停车反馈未确认："+stopProblem;
                    context.Progress?.Report("警告：软停车没有确认成功，现场立即检查，必要时使用实体急停");
                }
            }
            try {reportFiles=await Ct07Report.ExportAsync(folder,Snapshot(),CancellationToken.None);}
            catch(Exception ex)
            {
                reportProblem=ex.Message;
                context.Progress?.Report("CT-07报告写入失败："+ex.Message+"；请保存现场采样CSV："+folder);
            }
        }
        if(stopProblem.Length>0) throw new IOException("软停车未确认："+stopProblem);
        if(reportProblem.Length>0) throw new IOException("完整报告保存失败："+reportProblem);
        var metrics=Ct07Algorithm.Summarize(visits) ?? throw new InvalidDataException("重复轮次不足，无法统计");
        return new TestExecutionResult(TestId,TestOutcome.PendingAcceptance,
            $"CT-07完成{metrics.Visits}次真实回位，跨轮ACC矢量RMS={metrics.AccBetweenVectorRmsMg:F3}mg，"+
            $"方向RMS={metrics.DirectionBetweenRmsDeg:F5}°；内/外轴回位标准差"+
            $"{metrics.InnerReturnStdDeg:F5}°/{metrics.OuterReturnStdDeg:F5}°，待验收。",null,reportFiles);
    }

    private static int ReadGravitySignAndAxisModel(string jsonPath)
    {
        using var doc=JsonDocument.Parse(File.ReadAllText(jsonPath));
        var root=doc.RootElement;
        if(!root.TryGetProperty("axis_model",out var model) || model.GetString()!="outer_x_inner_z")
            throw new InvalidDataException("只支持Python outer_x_inner_z机械参考模型");
        if(!root.TryGetProperty("gravity_sign",out var sign) || !sign.TryGetInt32(out int n) || n is not (1 or -1))
            throw new InvalidDataException("常温ACC JSON缺少gravity_sign=±1");
        return n;
    }
    private static void ValidateCalibrationHashes(CalibrationRun run)
    {
        foreach(var f in run.Sources)
            if(!File.Exists(f.FilePath) ||
               !Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(f.FilePath)))
                  .Equals(f.Sha256,StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("标定文件发生变化："+f.FilePath);
    }
    private static bool WithinApproved(double a,Ct07Settings s)
    {
        if(!double.IsFinite(a)) return false;
        double x=(a%360+360)%360;
        if(s.AllowedMinDeg<=0 && x>=360-s.PositionToleranceDeg) x=0;
        return x>=s.AllowedMinDeg-s.PositionToleranceDeg &&
               x<=s.AllowedMaxDeg+s.PositionToleranceDeg;
    }
    private static void VerifyAxisState(RealTableFeedback b,bool inPlace)
    {
        if(DateTimeOffset.UtcNow-b.CapturedUtc>TimeSpan.FromSeconds(3))
            throw new IOException("2TD反馈超过3秒未更新");
        static void Axis(RealAxisFeedback a,string name,bool arrived)
        {
            if(!a.Normal || a.Enabled!=true || !double.IsFinite(a.PositionDeg) ||
               !double.IsFinite(a.SpeedDps) || Math.Abs(a.SpeedDps)>0.05 ||
               (arrived && a.InPlace!=true))
                throw new IOException(name+"未正常使能、静止或到位："+a.Detail);
        }
        Axis(b.Inner,"内轴",inPlace);Axis(b.Outer,"外轴",inPlace);
    }
    private static void VerifyPose(RealTableFeedback b,double inner,double outer,Ct07Settings s)
    {
        VerifyAxisState(b,true);
        if(Ct07Algorithm.Distance(b.Inner.PositionDeg,inner)>s.PositionToleranceDeg ||
           Ct07Algorithm.Distance(b.Outer.PositionDeg,outer)>s.PositionToleranceDeg)
            throw new IOException("2TD实际回位反馈不满足到位容差");
    }
    private static async Task MoveToAsync(IStaticAngleHardware hw,double inner,double outer,
        Ct07Settings s,CancellationToken ct)
    {
        var b=await hw.ReadTwoTdAsync(ct);VerifyAxisState(b,false);
        if(!WithinApproved(b.Inner.PositionDeg,s) || !WithinApproved(b.Outer.PositionDeg,s))
            throw new IOException("实际反馈超出声明的允许行程");
        if(Ct07Algorithm.Distance(b.Inner.PositionDeg,inner)>s.PositionToleranceDeg)
        {
            // Keep CT-05/CT-06 route: park outer at 0 before changing inner.
            await MoveAxisAsync(hw,2,0,s,ct);
            await MoveAxisAsync(hw,0,inner,s,ct);
        }
        await MoveAxisAsync(hw,2,outer,s,ct);
    }
    private static async Task MoveAxisAsync(IStaticAngleHardware hw,int axis,double target,
        Ct07Settings s,CancellationToken ct)
    {
        if(target<s.AllowedMinDeg || target>s.AllowedMaxDeg)
            throw new InvalidOperationException("运动目标超过批准的行程范围");
        var b=await hw.ReadTwoTdAsync(ct);VerifyAxisState(b,false);
        var now=axis==0?b.Inner:b.Outer;
        if(!WithinApproved(now.PositionDeg,s)) throw new IOException("运动前轴反馈越界");
        if(Ct07Algorithm.Distance(now.PositionDeg,target)<=s.PositionToleranceDeg && now.InPlace==true) return;
        await hw.SetTwoTdAbsoluteAsync(axis,target,s.SpeedDps,ct);
        double timeout=Math.Min(600,Math.Max(40,Math.Abs(target-now.PositionDeg)/s.SpeedDps*2.5+30));
        var watch=System.Diagnostics.Stopwatch.StartNew();int confirmed=0;
        while(watch.Elapsed.TotalSeconds<timeout)
        {
            ct.ThrowIfCancellationRequested();await Task.Delay(200,ct);
            b=await hw.ReadTwoTdAsync(ct);
            if(DateTimeOffset.UtcNow-b.CapturedUtc>TimeSpan.FromSeconds(3))
                throw new IOException("2TD运动反馈中断");
            var active=axis==0?b.Inner:b.Outer;var partner=axis==0?b.Outer:b.Inner;
            if(!active.Normal || active.Enabled!=true || !double.IsFinite(active.PositionDeg) ||
               !double.IsFinite(active.SpeedDps) || !partner.Normal || partner.Enabled!=true ||
               !double.IsFinite(partner.SpeedDps) || Math.Abs(partner.SpeedDps)>0.05)
                throw new IOException("转台运动轴异常或另一轴正在运动："+active.Detail);
            if(!WithinApproved(active.PositionDeg,s)) throw new IOException("转台运动越界，要求停车");
            bool arrived=Ct07Algorithm.Distance(active.PositionDeg,target)<=s.PositionToleranceDeg &&
                Math.Abs(active.SpeedDps)<=0.05 && active.InPlace==true;
            confirmed=arrived?confirmed+1:0;
            if(confirmed>=3) return;
        }
        throw new TimeoutException($"轴{axis}到位超时：目标{target:F3}°");
    }
    private static void VerifyPhysicalCsvScale(string file,int accFs,int gyroFs)
    {
        using var r=new StreamReader(file);
        var columns=(r.ReadLine()?.TrimStart('\uFEFF') ?? "").Split(',');
        foreach(string col in new[]{"ax_g","gx_dps","raw_ax","raw_gx","acc_input_fs_g","gyro_input_fs_dps"})
            if(!columns.Contains(col,StringComparer.Ordinal)) throw new InvalidDataException("采集CSV缺少字段："+col);
        int I(string name)=>Array.IndexOf(columns,name);
        if(!Asm330Codec.TryAccMg(accFs,out var mg) || !Asm330Codec.TryGyroMdps(gyroFs,out var mdps))
            throw new InvalidDataException("不支持的灵敏度输入量程");
        int count=0;string? line;var ci=CultureInfo.InvariantCulture;
        while((line=r.ReadLine()) is not null)
        {
            if(string.IsNullOrWhiteSpace(line)) continue;
            var v=line.Split(',');
            if(v.Length<columns.Length || !int.TryParse(v[I("acc_input_fs_g")],out var a) ||
               !int.TryParse(v[I("gyro_input_fs_dps")],out var g) || a!=accFs || g!=gyroFs)
                throw new InvalidDataException("真实采集CSV与本次标定输入量程不一致");
            double acc=double.Parse(v[I("ax_g")],ci), rawAcc=double.Parse(v[I("raw_ax")],ci);
            double gyr=double.Parse(v[I("gx_dps")],ci), rawGyr=double.Parse(v[I("raw_gx")],ci);
            if(Math.Abs(acc-rawAcc*mg/1000d)>1e-9 || Math.Abs(gyr-rawGyr*mdps/1000d)>1e-9)
                throw new InvalidDataException("物理量与真实原始计数的换算不匹配");
            count++;
        }
        if(count==0) throw new InvalidDataException("本次采集没有可用CSV帧");
    }
    private static async Task SaveCorrectedFramesAsync(string file,StaticPointSamples cap,
        bool[] accepted,double[][] acc,double[][] gyro,CancellationToken ct)
    {
        await using var stream=new FileStream(file,FileMode.CreateNew,FileAccess.Write,
            FileShare.Read,32768,FileOptions.Asynchronous);
        await using var writer=new StreamWriter(stream,new UTF8Encoding(true));
        await writer.WriteLineAsync("index,accepted,acc_x_cal_g,acc_y_cal_g,acc_z_cal_g,gyro_x_cal_dps,gyro_y_cal_dps,gyro_z_cal_dps,chip_temp_c");
        var ci=CultureInfo.InvariantCulture;
        string F(double v)=>v.ToString("G17",ci);
        for(int i=0;i<acc.Length;i++)
        {
            ct.ThrowIfCancellationRequested();
            var row=new[]{i.ToString(ci),accepted[i]?"1":"0"}
                .Concat(acc[i].Select(F)).Concat(gyro[i].Select(F))
                .Append(F(cap.Samples[i].TemperatureC));
            await writer.WriteLineAsync(string.Join(",",row));
        }
        await writer.FlushAsync(ct);
    }
}
