namespace Dts.Wpf.TestWindows;

/// <summary>
/// Optional per-test window capability: auto-suggest exactly UID-named calibration files.
/// Showing a candidate file does not remove each test's hardware ownership confirmation.
/// </summary>
public interface ICalibrationDirectoryAware
{
    void SuggestCalibrationDirectory(string folder);
}
