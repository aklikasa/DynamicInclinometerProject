namespace Dts.Devices;

/// <summary>
/// A request to energize a real 2TD motor, not an automatic movement command.
/// The caller MUST hold the device-operation gate and obtain explicit onsite
/// operator confirmation before calling this method. No fault/moving axis is
/// energized. A failed/partial request leaves the COM port open for diagnosis;
/// callers must not claim the table is operational.
/// </summary>
public static class TdEnableWorkflow
{
    public sealed record Outcome(bool Verified, bool CommandSent,
        string Reason, TableSnapshot? Feedback);

    public static async Task<Outcome> RequestAsync(
        IRealTurntable table, CancellationToken ct = default,
        Func<TimeSpan, CancellationToken, Task>? delay = null)
    {
        if (!table.Connected)
            return new Outcome(false, false, "串口尚未连接", null);

        delay ??= (duration, token) => Task.Delay(duration, token);
        TableSnapshot? before = null;
        string? readError = null;
        for (int n = 0; n < 4; n++)
        {
            ct.ThrowIfCancellationRequested();
            try
            {
                before = await Task.Run(table.Read, ct);
                if (TdConnectionPolicy.CanRequestEnable(before)) break;
            }
            catch (Exception ex) { readError = ex.Message; }
            if (n < 3) await delay(TimeSpan.FromMilliseconds(250), ct);
        }
        if (before is null || !TdConnectionPolicy.CanRequestEnable(before))
            return new Outcome(false, false,
                TdConnectionPolicy.ExplainEnableBlock(before) +
                (readError is null ? "" : "；读取错误：" + readError), before);

        // If both axes are already enabled and healthy, this is a read-only retry.
        if (TdConnectionPolicy.CanOperate(before!))
            return new Outcome(true, false, "已核实双轴正常且使能", before);

        bool commanded = false;
        try
        {
            // Match the Python workstation's proven command order and delays.
            // On a partial failure do NOT silently disable an axis or close COM.
            if (!before!.Inner.Enabled)
            {
                commanded = true; // A thrown native call may still have reached hardware.
                await Task.Run(() => table.EnableAxis(0), ct);
            }
            await delay(TimeSpan.FromMilliseconds(100), ct);
            if (!before.Outer.Enabled)
            {
                commanded = true;
                await Task.Run(() => table.EnableAxis(2), ct);
            }
            await delay(TimeSpan.FromMilliseconds(500), ct);

            TableSnapshot? last = before;
            int stableChecks = 0;
            for (int n = 0; n < 6; n++)
            {
                ct.ThrowIfCancellationRequested();
                try
                {
                    last = await Task.Run(table.Read, ct);
                    // Faults after an enable request must be investigated onsite.
                    if (last.Inner.Fault != false || last.Outer.Fault != false)
                        return new Outcome(false, commanded,
                            "使能后反馈有故障/限位或无法核实故障位", last);
                    stableChecks = TdConnectionPolicy.CanOperate(last)
                        ? stableChecks + 1 : 0;
                    if (stableChecks >= 2)
                        return new Outcome(true, commanded,
                            "连续两次反馈确认双轴正常且已使能", last);
                }
                catch (Exception ex) { readError = ex.Message; stableChecks = 0; }
                if (n < 5) await delay(TimeSpan.FromMilliseconds(200), ct);
            }
            return new Outcome(false, commanded,
                "发送使能后仍未连续确认双轴正常且已使能" +
                (readError is null ? "" : "；读取错误：" + readError), last);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            // Device may have one live axis. Retain connection in diagnosis mode.
            return new Outcome(false, commanded,
                "使能命令/反馈异常：" + ex.Message, before);
        }
    }
}
