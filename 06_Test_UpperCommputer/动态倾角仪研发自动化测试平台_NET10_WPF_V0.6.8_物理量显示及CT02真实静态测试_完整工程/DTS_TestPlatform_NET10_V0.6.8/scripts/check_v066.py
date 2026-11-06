from pathlib import Path
import xml.etree.ElementTree as ET
root=Path(__file__).resolve().parents[1]
read=lambda n:(root/n).read_text(encoding="utf8")
selected=read("src/Dts.Devices/SelectedImuFrame.cs")
main=read("src/Dts.Wpf/MainWindow.xaml.cs")
xaml=read("src/Dts.Wpf/MainWindow.xaml")
selftest=read("src/Dts.SelfTest/Program.cs")
acq=read("src/Dts.Devices/Acquisition.cs")
assert "AllowUnverifiedScaleTrial" not in selected+main+xaml+acq
assert "!sensorOk" not in selected
assert "run.Files?.Acc?.FsHint" in selected
assert "run.Files?.Gyro?.FsHint" in selected
assert "MCU_FS_UNKNOWN_NO_JSON_HINT" in selected
assert 'CALIBRATED_JSON_FS_UNVERIFIED' in selected
assert 'CALIBRATED_JSON_FS_MCU_MISMATCH' in selected
assert 'HasComputedCalibration' in selected and 'frame.HasComputedCalibration' in acq
assert 'unknownFrame.IsDevelopmentTrial' in selftest and 'unknownFrame.Ax=="0.989424"' in selftest
assert "未提供必要的量程参数" in selftest
assert "unknownWithoutSensor" in selftest and "mismatchFrame" in selftest
assert "VerifyImuForPrecisionTestAsync" in read("src/Dts.Devices/LiveTestHardware.cs")
assert "本机UID" in xaml and "标定" in xaml
ET.parse(root/"src/Dts.Wpf/MainWindow.xaml")
print("PASS: automatic ambient compensation no optional gate; provenance remains; XAML parses")
print("NOTE: static code checks only; .NET 10 build and physical device validation required")
