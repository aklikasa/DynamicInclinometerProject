using Dts.Core;

namespace Dts.TestEngine;

/// <summary>采集前只探测真实批次，不生成虚构数据，也不修改校准文件。</summary>
public sealed record AllanPreflightResult(int UniqueBatches,int SensorUnverifiedBatches,int OdrHz);

/// <summary>CT-12A专用的短时真实FIFO探测；需在正式计时采集之前执行。</summary>
public interface IAllanPreflightHardware
{
    Task<AllanPreflightResult> ProbeAllanAsync(CalibrationRun run,CancellationToken ct);
}
