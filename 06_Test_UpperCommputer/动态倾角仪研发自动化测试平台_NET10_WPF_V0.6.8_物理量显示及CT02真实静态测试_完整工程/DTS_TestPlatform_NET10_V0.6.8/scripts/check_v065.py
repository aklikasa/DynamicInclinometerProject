from pathlib import Path
import xml.etree.ElementTree as ET
root=Path(__file__).resolve().parents[1]
get=lambda p:(root/p).read_text(encoding='utf8')
ct05_xaml=get('src/Dts.Wpf/TestWindows/CT05/CT05Window.xaml')
main_xaml=get('src/Dts.Wpf/MainWindow.xaml')
ct05_algo=get('src/Dts.Tests/S1/CT05/CT_05_Algorithm.cs')
ct05_test=get('src/Dts.Tests/S1/CT_05_Test.cs')
selected=get('src/Dts.Devices/SelectedImuFrame.cs')
acq=get('src/Dts.Devices/Acquisition.cs')
assert 'x:Name="MaxTravel" Text="90"' in ct05_xaml
assert 'CircularDistanceDeg(359.9999,0)' in get('src/Dts.SelfTest/Program.cs')
assert ct05_test.count('Ct05Algorithm.CircularDistanceDeg(')>=6
assert 'VerifyImuForPrecisionTestAsync' in ct05_test
assert 'VerifyImuForPrecisionTestAsync' in get('src/Dts.Devices/LiveTestHardware.cs')
assert 'x:Name="TdZeroSpeed" Text="10"' in main_xaml
assert '"2TD",speed)' in get('src/Dts.Wpf/MainWindow.xaml.cs')
assert 'CALIBRATED_JSON_FS_UNVERIFIED' in selected
assert 'unverified_calibrated_samples=trialSamples' in acq
assert 'unknownFrame.IsDevelopmentTrial' in get('src/Dts.SelfTest/Program.cs')
assert 'imu_selected.csv' in acq and 'imu_raw.csv' in acq
ET.parse(root/'src/Dts.Wpf/MainWindow.xaml')
ET.parse(root/'src/Dts.Wpf/TestWindows/CT05/CT05Window.xaml')
print('PASS: CT05 default 90°; circular 0/360 comparisons; IMU preflight; configurable 10°/s homing')
print('PASS: automatic JSON FS conversion; selected/main CSV provenance and status; XAML parse')
print('NOTE: not a .NET compiler or physical bench test')
