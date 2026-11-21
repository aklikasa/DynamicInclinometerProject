using System;
using System.IO;
using System.Threading;
using System.Threading.Tasks;
using System.Linq;
using Dts.Core;
using Dts.TestEngine;

namespace Dts.Tests.S1.CT01;

/// <summary>
/// Verifies that the UID-matched calibration snapshot used by the live acquisition
/// pipeline independently reproduces every corrected sample. This is a parameter
/// application diagnostic, not an accuracy acceptance test.
/// </summary>
public sealed class CT_01_Test : TestModuleBase
{
    public override string TestId => "CT-01";
    public override string Name => "参数生效与补偿前后对比";
    public override string Purpose =>
        "核验当前真实 MCU UID 对应的 ACC/Gyro 常温或全温标定文件是否被正确加载、输入量程换算是否一致、同批原始样本的补偿输出是否与冻结 JSON 独立重算一致。";
    public override string Procedure =>
        "主窗口选择常温补偿或全温补偿并加载当前设备标定文件；保持 IMU 静止采集同一批真实 FIFO 原始样本；使用本次采集冻结的 JSON 快照独立重算；比较量程换算、六轴补偿输出及主程序所选输出流；生成诊断报告。";
    public override string Priority => "P0";
    public override bool IsExecutable => true;
    public override bool RequiresStaticBench => true;
    public override string ImplementationNote =>
        "真实 IMU 静态采集；不控制转台。必须在主窗口选择并确认当前 PCB 的常温或全温标定模式。结果只证明参数身份/量程/计算链一致，不代表角度或角速度精度合格，不自动判产品 PASS。";

    public override async Task<TestExecutionResult> ExecuteAsync(TestExecutionContext context, CancellationToken ct)
    {
        if (context.Parameters is not Ct01RunSettings settings)
            throw new InvalidOperationException("CT-01 必须通过专用窗口启动；缺少冻结的标定模式参数。");

        var run = settings.CalibrationRun;
        if (run.Mode is not (CalibrationMode.Ambient or CalibrationMode.Thermal))
            throw new InvalidOperationException("CT-01 不允许使用 RAW 未标定模式；请在主窗口选择常温补偿或全温补偿。");

        var identity = context.Hardware.CurrentIdentity
            ?? throw new InvalidOperationException("未连接真实 IMU 或未读取完整 MCU UID。");
        if (identity.UidHex.Length != 24 || !identity.UidHex.All(Uri.IsHexDigit))
            throw new InvalidDataException("当前 MCU UID 不是有效的 12 字节/24位十六进制 UID。");
        run.Validate(identity);
        if (run.Sources.Count != 2)
            throw new InvalidDataException("CT-01 要求当前模式同时具备 ACC 和 Gyro 两份标定文件。");
        if (context.Duration < TimeSpan.FromSeconds(5) || context.Duration > TimeSpan.FromMinutes(30))
            throw new ArgumentOutOfRangeException(nameof(context.Duration), "CT-01 采集时长必须为 5～1800 秒。");

        context.Progress?.Report($"CT-01：UID={identity.UidHex}；模式={run.Mode}；正在采集同批原始/补偿数据……");
        var capture = await context.Hardware.CaptureStaticImuAsync(
            TestId, context.Duration, analyzeRawStatistics: false, context.Progress, ct);

        var verification = await Ct01Algorithm.AnalyzeAsync(capture, identity, run, ct);
        var files = await Ct01Report.WriteAsync(capture.Folder, verification, ct);

        string sourceStatus = verification.SensorUnverifiedSamples == 0
            ? "采集批次均报告 SENSOR_OK"
            : $"有 {verification.SensorUnverifiedSamples}/{verification.Samples} 帧来源状态未核实";
        return new TestExecutionResult(
            TestId, TestOutcome.DiagnosticOnly,
            $"参数应用链核验完成：{verification.Mode}；{verification.Samples}帧；独立重算最大差值 {verification.MaxRecomputeAbsError:G4}；{sourceStatus}。该结果不是产品精度 PASS。",
            capture, files);
    }
}

public sealed record Ct01RunSettings(CalibrationRun CalibrationRun);
