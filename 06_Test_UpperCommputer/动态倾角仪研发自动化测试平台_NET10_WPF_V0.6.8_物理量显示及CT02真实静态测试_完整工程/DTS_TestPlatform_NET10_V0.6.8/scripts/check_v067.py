from pathlib import Path
import re, json
root=Path(__file__).resolve().parents[1]
load=lambda f:(root/f).read_text(encoding='utf-8')
policy=load('src/Dts.Core/CalibrationInputScalePolicy.cs')
core=load('src/Dts.Core/Core.cs')
selected=load('src/Dts.Devices/SelectedImuFrame.cs')
hw=load('src/Dts.Devices/LiveTestHardware.cs')
ct05=load('src/Dts.Tests/S1/CT_05_Test.cs')
main=load('src/Dts.Wpf/MainWindow.xaml.cs')
selftest=load('src/Dts.SelfTest/Program.cs')
assert re.search(r'HistoricalGyroFullScaleDps\s*=\s*2000',policy)
assert re.search(r'HistoricalAccFullScaleG\s*=\s*2',policy)
assert '{2000,70}' in core and '{250,8.75}' in core and '{2,0.061}' in core
assert 'accFileFsG ?? accMcuFsG' in policy
assert 'gyroFileFsDps ?? gyroMcuFsDps' in policy
assert 'run.Files?.Gyro?.FsHint' in selected and 'CalibrationInputScalePolicy.Resolve' in selected
assert 'sample.RawGx*scale.GyroDpsPerLsb' in selected
assert 'selected.PhysicalAcc is not { Length: 3 }' in hw
assert 'selected.PhysicalGyro is not { Length: 3 }' in hw
assert 'var selected=SelectedImuFrame.FromSample(b,sample,i,run)' in hw
assert 'requireSensorOk:run.Mode!=CalibrationMode.Ambient' in hw
assert 'if(b.FifoUnread==0 || b.Samples.Count==0)' in hw
assert 'ReadBatchAsync(ct,requireSensorOk:false)' in hw
assert 'scaleSource=scale.AccFromJson && scale.GyroFromJson ? "UID_JSON"' in hw
assert 'gyro_fs_used_for_fitting_dps=matched.Gyro?.FsHint' in ct05
assert 'input_conversion=' in ct05
assert '"；计算输入："+scale.Display' in main
assert 'historicalScale.GyroDpsPerLsb-.070' in selftest
assert 'TestOutcome.PendingAcceptance' in ct05
assert 'CheckAxis(initial.Inner' in ct05 and 'CheckAxis(initial.Outer' in ct05
assert 'MoveAndVerify' in ct05 and 'StopTwoTdBothAsync(CancellationToken.None)' in ct05
print('PASS V067: Historical Gyro 2000dps -> 0.070dps/LSB preserved; JSON overrides MCU including 250')
print('PASS V067: CT05 samples use same physical scale; raw counts and provenance written; motor checks intact')
print('NOTE: this is a source inspection; compile and bench verification require Windows .NET 10 and real hardware')
