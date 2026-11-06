"""V0.6.7.1: regression guard for the CS0136 shadowing fix; not a compiler."""
from pathlib import Path
p=Path(__file__).resolve().parents[1]/'src/Dts.Devices/SelectedImuFrame.cs'
s=p.read_text(encoding='utf-8')
assert 'string rawStatus=sensorOk?' in s
assert '"g","deg/s",rawStatus,' in s
assert 'string status=sensorOk?' not in s
assert 'SelectedImuFrame Missing(string reason)' in s
assert 'string status=scaleVerified && sensorOk' in s
print('PASS: SelectedImuFrame status shadowing renamed to rawStatus/reason')
