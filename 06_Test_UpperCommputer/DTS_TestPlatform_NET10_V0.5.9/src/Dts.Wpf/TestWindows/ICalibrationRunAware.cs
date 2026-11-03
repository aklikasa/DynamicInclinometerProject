using Dts.Core;
namespace Dts.Wpf.TestWindows;

/// <summary>Test windows receive a central UID-matched run snapshot, never a per-test file picker.</summary>
public interface ICalibrationRunAware
{
    void SetCalibrationRun(CalibrationRun run);
}
