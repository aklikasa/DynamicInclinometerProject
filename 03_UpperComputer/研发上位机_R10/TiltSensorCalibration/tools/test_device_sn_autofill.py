# -*- coding: utf-8 -*-
"""DTS PCB auto-fill regression, run without PySide6 or real hardware."""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'form'))
from device_sn_autofill import DeviceSnAutoFill


class FakeLineEdit:
    def __init__(self, text=''):
        self.value = text
        self.change_count = 0

    def text(self):
        return self.value

    def setText(self, value):
        self.change_count += 1
        self.value = value

    def clear(self):
        self.change_count += 1
        self.value = ''


# New firmware: update two independent pages from one DTS number, no copy/paste.
imu, thermal = FakeLineEdit(), FakeLineEdit()
controller = DeviceSnAutoFill()
imu_busy = False
thermal_busy = False
controller.register(imu, lambda: imu_busy)
controller.register(thermal, lambda: thermal_busy)
controller.register(imu)
assert len(controller._bindings) == 2
controller.update('DTS672516')
assert (imu.text(), thermal.text()) == ('DTS672516', 'DTS672516')
controller.update('DTS672516')
assert (imu.change_count, thermal.change_count) == (1, 1)
# Modbus failure does not show errors or leave previous board identity in the fields.
controller.update('')
assert (imu.text(), thermal.text()) == ('', '')
# Old firmware may continue with existing manual PCB-identification workflow.
imu.setText('PCB-LEGACY-0001')
thermal.setText('PCB-LEGACY-0001')
controller.update(None)
assert (imu.text(), thermal.text()) == ('PCB-LEGACY-0001', 'PCB-LEGACY-0001')
# A valid UID from a different device takes precedence over old typed values.
controller.update('DTS123456')
assert (imu.text(), thermal.text()) == ('DTS123456', 'DTS123456')
# Out-of-band value is never propagated.
controller.update('anything-else')
assert (imu.text(), thermal.text()) == ('', '')
# During a record/calibration run do not change an immutable run's device identifier.
controller.update('DTS111111')
imu_busy = True
thermal_busy = True
controller.update('DTS222222')
assert (imu.text(), thermal.text()) == ('DTS111111', 'DTS111111')
imu_busy = False
controller.update('DTS222222')
assert imu.text() == 'DTS222222' and thermal.text() == 'DTS111111'
thermal_busy = False
controller.update('DTS222222')
assert thermal.text() == 'DTS222222'
controller.update('')
assert (imu.text(), thermal.text()) == ('', '')

# Wiring checks on the actual project tree; ensure existing UI field value is used
# in calibration run data and thermal experiment metadata.
main = (ROOT / 'main.py').read_text(encoding='utf-8')
tilt = (ROOT / 'form/form_tilt_sensor_cal.py').read_text(encoding='utf-8')
imu_source = (ROOT / 'form/form_imu_calibration.py').read_text(encoding='utf-8')
thermal_source = (ROOT / 'form/form_thermal_compensation.py').read_text(encoding='utf-8')
for filename in ('main.py', 'form/form_tilt_sensor_cal.py',
                 'form/form_imu_calibration.py', 'form/form_thermal_compensation.py'):
    ast.parse((ROOT / filename).read_text(encoding='utf-8'))
assert 'form_tilt_sensor_cal.register_device_sn_field(' in main
assert 'form_imu_calibration.line_device_sn' in main
assert 'form_thermal.sn' in main
assert 'self._device_sn_auto_fill.update(device_sn)' in tilt
assert 'device_sn = self.line_device_sn.text().strip()' in imu_source
assert "'device_sn':self.sn.text().strip()" in thermal_source
assert 'form_imu_calibration._auto_task is not None' in main
assert 'form_thermal.task is not None' in main
print('[PASS] PCB编号自动填充、旧固件手动兜底、断开清空、防止任务中途改写、标定保存接线')
