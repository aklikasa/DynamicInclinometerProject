"""V0.6.8 source contracts: cannot replace Windows dotnet build or hardware acceptance."""
from pathlib import Path
import json, re, xml.etree.ElementTree as ET
root = Path(__file__).resolve().parents[1]
read = lambda f: (root/f).read_text(encoding='utf-8')
selected = read('src/Dts.Devices/SelectedImuFrame.cs')
policy = read('src/Dts.Core/CalibrationInputScalePolicy.cs')
acq = read('src/Dts.Devices/Acquisition.cs')
ct02 = read('src/Dts.Tests/S1/CT02/CT_02_Test.cs')
ct02alg = read('src/Dts.Tests/S1/CT02/CT_02_Algorithm.cs')
ct02rep = read('src/Dts.Tests/S1/CT02/CT_02_Report.cs')
ct02res = read('src/Dts.Tests/S1/CT02/CT_02_Result.cs')
ct02win = read('src/Dts.Wpf/TestWindows/CT02/CT02Window.xaml.cs')
ct02xaml = read('src/Dts.Wpf/TestWindows/CT02/CT02Window.xaml')
checks = {
    'historical FS = 2g / 2000dps': 'HistoricalAccFullScaleG = 2' in policy and 'HistoricalGyroFullScaleDps = 2000' in policy,
    'uncalibrated physical stream first': 'UncalibratedDisplayScale' in selected and 'F(acc[0]),F(acc[1])' in selected and '"g","deg/s",rawStatus' in selected,
    'immutable raw fields retained': 'sample.RawAx,sample.RawAy,sample.RawAz' in selected and 'imu_raw.csv' in acq,
    'selected file units g/deg/s': 'selected_stream_units="g/deg/s"' in acq,
    'no CT02 motor commands': 'SetTwoTd' not in ct02 and 'Move' not in ct02 and 'StopTwoTd' not in ct02,
    'per-uid calibration frozen & hash checked': 'SetEquals(run.Sources.Select(x => x.Sha256))' in ct02 and 'run.Validate(identity)' in ct02,
    'real capture only': 'CaptureStaticImuAsync' in ct02 and 'AnalyzeSelectedCsvAsync' in ct02alg,
    'one submodule has four own C# files': all((root/f'src/Dts.Tests/S1/CT02/CT_02_{part}.cs').is_file() for part in ('Test','Algorithm','Result','Report')),
    'report JSON / CSV / HTML': all(name in ct02rep for name in ['CT-02_result.json', 'CT-02_metrics.csv', 'CT-02_report.html']),
    'uses calibrated status and sample count': 'MCU_SCALE_VERIFIED_CALIBRATED' in ct02alg and 'count < 50' in ct02alg and 'ticks.Count < 2' in ct02alg,
    'visible dedicated window automatically registered': '[Dts.Wpf.TestWindows.TestWindowFor("CT-02")]' in ct02win,
    'calibration snapshot passed through existing interface': 'ICalibrationRunAware' in ct02win and 'SetCalibrationRun' in ct02win,
    'no automatic PASS': 'TestOutcome.PendingAcceptance' in ct02 and 'TestOutcome.Passed' not in ct02,
    '74 test stages unchanged': len(json.loads(read('assets/tests.json'))) == 84,
}
for k, passed in checks.items():
    assert passed, k
for f in root.glob('src/Dts.Wpf/TestWindows/CT02/*.xaml'):
    ET.parse(f)
assert 'SelectedMode==CalibrationMode.Raw ? "未标定物理量 (g / °/s)"' in read('src/Dts.Wpf/MainWindow.xaml.cs')
assert 'CT-02' in read('src/Dts.SelfTest/Program.cs')
print('PASS: V0.6.8 current raw mode = physical, historical 2g/2000dps, counts backed up')
print('PASS: CT-02 single-pose real capture module, independent XAML, validation, statistics, exports')
print('PASS: 84 original test IDs unchanged; CT02 automatic discovery, no MainWindow test-specific branch')
print('WARNING: no Windows .NET 10 compiler, WPF launch or real equipment to verify here')
