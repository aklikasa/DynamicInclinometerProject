using System.Security.Cryptography;
using Dts.Core;
using Dts.TestEngine;
using Dts.Tests.S1.CT05;

namespace Dts.Tests.S1;

/// <summary>
/// 由 Python 静态角度检测工作台 V1.4 迁移的真实 CT-05 子测试：逐点定位、稳定采样、
/// 使用2TD实际位置反馈作为角度参考、保留检查点并生成独立报告。
/// 尚未建立产品级验收条件；只有 PendingAcceptance，不输出 PASS。
/// </summary>
public sealed class CT_05_Test : TestModuleBase
{
    public override string TestId => "CT-05";
    public override bool IsExecutable => true;
    public override string ImplementationNote => "真实 2TD/IMU 静态多点检测；独立设置窗口、ACC 校准JSON、真实逐点原始数据、检查点和HTML/Excel报告；未声明产品合格。";
    public override async Task<TestExecutionResult> ExecuteAsync(TestExecutionContext context,CancellationToken ct)
    {
        if(context.Hardware is not IStaticAngleHardware hardware)
            throw new InvalidOperationException("当前设备对象不支持真实静态角度扫描");
        if(context.Parameters is not Ct05Settings settings)
            throw new InvalidOperationException("缺少 CT-05 专用窗口的检测参数");
        var id=hardware.CurrentIdentity ?? throw new InvalidOperationException("请先连接真实 IMU、读取 UID");
        if(!hardware.IsTwoTdConnected)throw new InvalidOperationException("CT-05 当前仅支持已连接的 2TD-600；温控转台需要单独验证轨迹");
        if(settings.ProcessingMode==CalibrationMode.Raw)
            throw new InvalidOperationException("CT-05是标定后角度准确度测试，请在主窗口选择常温或全温补偿；原始数据请使用主窗口采集");
        if(!File.Exists(settings.CalibrationJson))throw new FileNotFoundException("UID自动匹配的标定JSON不存在",settings.CalibrationJson);
        // Receive the exact global UID-matched run snapshot. Do not search ACC's parent
        // folder again: Gyro and thermal models may live in sibling subdirectories.
        var run = settings.RunCalibration
            ?? throw new InvalidOperationException("测试没有收到主窗口冻结的标定参数快照");
        run.Validate(id);
        var matched = run.Files!;
        CalibrationSource selectedSource = settings.ProcessingMode == CalibrationMode.Ambient
            ? matched.Acc! : matched.ThermalAcc!;
        if (!string.Equals(Path.GetFullPath(selectedSource.FilePath),Path.GetFullPath(settings.CalibrationJson),
            StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("测试窗口使用的ACC JSON与当前UID/模式选择不一致");
        // Hash all active calibration files again before hardware motion. If a file has
        // changed since matching, cancel rather than silently mixing parameter versions.
        foreach(var source in run.Sources)
        {
            if (!File.Exists(source.FilePath) ||
                !Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(source.FilePath)))
                    .Equals(source.Sha256,StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("标定文件在加载后发生改变，请停止并重新载入目录：" + source.FilePath);
        }
        Func<double[],double,double[]> transform=settings.ProcessingMode==CalibrationMode.Ambient
            ? (vector,temp)=>matched.Acc!.Apply(vector[0],vector[1],vector[2])
            : (vector,temp)=>matched.ThermalAcc!.Apply(vector[0],vector[1],vector[2],temp);
        var plan=Ct05Algorithm.BuildPlan(settings.PlanKind);
        Ct05Algorithm.ValidatePlan(settings,plan);
        var initial=await hardware.ReadTwoTdAsync(ct);
        CheckAxis(initial.Inner,"内轴");CheckAxis(initial.Outer,"外轴");
        string baseDir=Path.GetFullPath(settings.OutputRoot);
        Directory.CreateDirectory(baseDir);
        string folder=Path.Combine(baseDir,$"{id.DtsId}_{id.UidHex}",
            DateTime.Now.ToString("yyyyMMdd_HHmmss_fff")+"_CT-05");
        Directory.CreateDirectory(folder);
        File.Copy(settings.CalibrationJson,Path.Combine(folder,"calibration_used.json"),overwrite:false);
        string sha=selectedSource.Sha256;
        // Persist both selected matrices and the exact UID-matched file hashes in the run folder.
        await File.WriteAllTextAsync(Path.Combine(folder,"calibration_sources.json"),
            System.Text.Json.JsonSerializer.Serialize(new {mode=settings.ProcessingMode.ToString(),
                uid_raw_12_bytes=id.UidHex,dts_id=id.DtsId,identity_proof=run.IdentityProof,
                files=run.Sources.Select(f=>new{file_name=Path.GetFileName(f.FilePath),source_path=f.FilePath,sha256=f.Sha256,
                    full_uid_verified=f.FullUidVerified})},
                new System.Text.Json.JsonSerializerOptions{WriteIndented=true}),ct);
        string start=DateTimeOffset.UtcNow.ToString("O");
        var rows=new List<Ct05PointResult>();
        string status="执行中",failure="";
        try
        {
            for(int i=0;i<plan.Count;i++)
            {
                ct.ThrowIfCancellationRequested();
                var point=plan[i];
                context.Progress?.Report($"CT-05 [{i+1}/{plan.Count}] {point.Channel} / {point.OuterSignedDeg:+0.##;-0.##;0}°，正在定位");
                var state=await hardware.ReadTwoTdAsync(ct);
                // Python v1.4 safe motion order: outer->0, inner change, outer->target.
                if(Math.Abs(state.Inner.PositionDeg-point.InnerTargetDeg)>settings.PositionToleranceDeg)
                {
                    if(Math.Abs(state.Outer.PositionDeg)>settings.PositionToleranceDeg)
                        await MoveAndVerify(hardware,2,0,settings,ct);
                    await MoveAndVerify(hardware,0,point.InnerTargetDeg,settings,ct);
                }
                await MoveAndVerify(hardware,2,point.OuterCommandDeg,settings,ct);
                await Task.Delay(TimeSpan.FromSeconds(settings.SettleSeconds),ct);
                var at=await hardware.ReadTwoTdAsync(ct);
                VerifyReference(at,point,settings);
                string raw=Path.Combine(folder,$"point_{i+1:D3}_{point.Channel}.csv");
                var samples=await hardware.CaptureStaticPointAsync(raw,TimeSpan.FromSeconds(settings.CaptureSeconds),
                    context.Progress,ct);
                var after=await hardware.ReadTwoTdAsync(ct);
                VerifyReference(after,point,settings);
                var result=Ct05Algorithm.Analyze(i+1,point,after,samples,transform,settings);
                rows.Add(result);
                context.Progress?.Report($"CT-05 [{i+1}/{plan.Count}] 真实误差 {result.ErrorDeg:+0.00000;-0.00000;0}°；已保存 {result.AcceptedSamples} 帧");
                await Ct05Report.SaveCheckpointAsync(folder,Summary("采集中",""),ct);
            }
            status="逐点采集完成/待验收";
        }
        catch(OperationCanceledException){status="用户取消/部分记录";failure="取消后需检查实体转台停车反馈";throw;}
        catch(Exception ex){status="异常中止/部分记录";failure=ex.Message;throw;}
        finally
        {
            // Cancellation must not cancel the STOP command. Stop both axes regardless of which point failed.
            try{await hardware.StopTwoTdBothAsync(CancellationToken.None);}
            catch(Exception stopError)
            {
                failure+=" 停车指令或反馈未确认："+stopError.Message;
                status="安全状态未确认/部分记录";
                context.Progress?.Report("紧急提示：双轴软停车未核验，请立即现场检查，必要时使用物理急停；不可断开连接");
            }
            try
            {
                var summary=Summary(status,failure);
                await Ct05Report.SaveCheckpointAsync(folder,summary,CancellationToken.None);
                await Ct05Report.ExportAsync(folder,summary,CancellationToken.None);
            }
            catch(Exception ex){context.Progress?.Report("报告保存失败："+ex.Message+"；原始逐点数据仍保留在 "+folder);}
        }
        if(status.StartsWith("安全状态",StringComparison.Ordinal))
            throw new IOException("转台停车状态未确认；禁止将测试记录视为完成。"+failure);
        var files=new[]{"CT-05_result.json","CT-05_points.csv","CT-05_report.html","CT-05_report.xlsx","checkpoint.json"}
            .Select(n=>Path.Combine(folder,n)).ToArray();
        return new TestExecutionResult(TestId,TestOutcome.PendingAcceptance,
            $"真实检测采集完成 {rows.Count}/{plan.Count} 点；请审核 Excel/HTML 报告和转台不确定度（不自动判 PASS）。",null,files);

        Ct05Summary Summary(string s,string error)
        {
            double? bias=null,rmse=null,max=null;
            if(rows.Count>0){var m=Ct05Algorithm.Summarize(rows);bias=m.Bias;rmse=m.Rmse;max=m.MaxAbs;}
            return new Ct05Summary(TestId,id.UidHex,id.DtsId,settings.CalibrationJson,sha,start,
                DateTimeOffset.UtcNow.ToString("O"),s,error,settings,rows.ToArray(),bias,rmse,max);
        }
    }
    private static void CheckAxis(RealAxisFeedback a,string name)
    {
        if(!a.Normal || a.Enabled != true || !double.IsFinite(a.PositionDeg)||!double.IsFinite(a.SpeedDps))
            throw new IOException($"{name}非正常/未使能/反馈无效，禁止自动扫描：{a.Detail}");
    }
    private static async Task MoveAndVerify(IStaticAngleHardware h,int axis,double target,Ct05Settings settings,CancellationToken ct)
    {
        if(target<settings.AllowedTravelMinDeg||target>settings.AllowedTravelMaxDeg)
            throw new InvalidOperationException("目标超出现场批准的绝对行程");
        var before=await h.ReadTwoTdAsync(ct);
        var actual=axis==0?before.Inner:before.Outer;
        CheckAxis(actual,axis==0?"内轴":"外轴");
        if(Math.Abs(actual.PositionDeg-target)<=settings.PositionToleranceDeg &&
           Math.Abs(actual.SpeedDps)<=0.05 && actual.InPlace==true)return;
        await h.SetTwoTdAbsoluteAsync(axis,target,settings.SpeedDps,ct);
        double angularDistance=Math.Abs(target-actual.PositionDeg);
        var watch=System.Diagnostics.Stopwatch.StartNew();
        double timeout=Math.Min(300,Math.Max(20,angularDistance/settings.SpeedDps*2.5+15));
        int consecutive=0;
        while(watch.Elapsed.TotalSeconds<timeout)
        {
            ct.ThrowIfCancellationRequested();
            await Task.Delay(200,ct);
            var state=await h.ReadTwoTdAsync(ct);
            var a=axis==0?state.Inner:state.Outer;
            CheckAxis(a,axis==0?"内轴":"外轴");
            bool reached=Math.Abs(a.PositionDeg-target)<=settings.PositionToleranceDeg
                &&Math.Abs(a.SpeedDps)<=0.05&&a.InPlace==true;
            consecutive=reached?consecutive+1:0;
            if(consecutive>=3)return;
        }
        throw new TimeoutException($"轴 {axis} 目标 {target}° 超时或未获得连续到位反馈");
    }
    private static void VerifyReference(RealTableFeedback s,Ct05PlanPoint p,Ct05Settings settings)
    {
        CheckAxis(s.Inner,"内轴");CheckAxis(s.Outer,"外轴");
        if(Math.Abs(s.Inner.PositionDeg-p.InnerTargetDeg)>settings.PositionToleranceDeg||
           Math.Abs(s.Outer.PositionDeg-p.OuterCommandDeg)>settings.PositionToleranceDeg||
           s.Inner.InPlace!=true||s.Outer.InPlace!=true||
           Math.Abs(s.Inner.SpeedDps)>0.05||Math.Abs(s.Outer.SpeedDps)>0.05)
            throw new InvalidDataException("采样前后转台不在目标位置/未静止；禁止用目标指令冒充实际参考角度");
    }
}
