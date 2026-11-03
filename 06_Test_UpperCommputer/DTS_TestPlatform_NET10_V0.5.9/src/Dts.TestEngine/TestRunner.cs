using System.Reflection;
using System.Text.Json;

namespace Dts.TestEngine;

/// <summary>任务互斥 + 结果审计；不会自动把诊断结果写成 PASS。</summary>
public sealed class TestRunner
{
    private int _running;
    public bool IsRunning => Volatile.Read(ref _running) != 0;

    public async Task<TestExecutionResult> RunAsync(
        ITestModule module, TestExecutionContext context, CancellationToken ct)
    {
        if (!module.IsExecutable)
            throw new NotSupportedException($"{module.TestId} 只有测试目录/占位类，不能运行。");
        if (!string.Equals(module.TestId, context.Definition.Id, StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("执行类与所选测试编号不一致");
        if (Interlocked.CompareExchange(ref _running, 1, 0) != 0)
            throw new InvalidOperationException("另一个测试正在执行，禁止并发启动");
        DateTimeOffset started = DateTimeOffset.UtcNow;
        try
        {
            ct.ThrowIfCancellationRequested();
            var result = await module.ExecuteAsync(context, ct);
            ct.ThrowIfCancellationRequested();
            if (!string.Equals(result.TestId, module.TestId, StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("执行结果测试编号错误");
            if (result.Outcome is TestOutcome.Passed or TestOutcome.Failed &&
                (result.Acceptance is null ||
                 string.IsNullOrWhiteSpace(result.Acceptance.SpecificationId) ||
                 string.IsNullOrWhiteSpace(result.Acceptance.ReferenceInstrumentId) ||
                 !File.Exists(result.Acceptance.MetricResultFile)))
                throw new InvalidDataException("产品级 PASS/FAIL 缺少验收判据、参考设备与计算结果文件；拒绝写入验收结论");
            if (result.Capture is { } a)
            {
                if (a.Samples < 1 || a.DeviceNumber.Length == 0 || a.UidHex.Length != 24 ||
                    !File.Exists(a.CsvFile) || !File.Exists(a.ManifestFile))
                    throw new InvalidDataException("原始数据或 UID 证据不完整，不生成成功记录");
                var audit = new
                {
                    test_id = module.TestId,
                    module_type = module.GetType().FullName,
                    module_assembly_version = module.GetType().Assembly.GetName().Version?.ToString(),
                    started_utc = started, completed_utc = DateTimeOffset.UtcNow,
                    uid_raw_12_bytes = a.UidHex, device_number = a.DeviceNumber,
                    outcome = result.Outcome.ToString(), result.Summary, result.Files, result.Acceptance,
                    warning = "DiagnosticOnly 不属于产品通过；只有具有明确标准与参考不确定度的完整验收模块才允许 PASS。"
                };
                await File.WriteAllTextAsync(Path.Combine(a.Folder, "test_execution.json"),
                    JsonSerializer.Serialize(audit, new JsonSerializerOptions { WriteIndented = true }), ct);
            }
            return result;
        }
        finally { Interlocked.Exchange(ref _running, 0); }
    }
}
