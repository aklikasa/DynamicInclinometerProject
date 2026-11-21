"""Offline regression tests for 2FDT600WK zero-status interpretation."""
from pathlib import Path
import ctypes
import sys
import types

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "turntable"))

# The classifier itself is pure Python; mock the vendor DLL load for this offline test.
class FakeDll:
    pass

_original_cdll = ctypes.CDLL
ctypes.CDLL = lambda *_args, **_kwargs: FakeDll()
try:
    import turntable_2FDT600WK_comm as comm
finally:
    ctypes.CDLL = _original_cdll

# State code 2 is homing-in-progress, never "already at zero".
assert comm.twoFDT600WK_classify_zero_status(2, 125.0) == (False, "回零中")

# Only idle/servo states at the absolute zero angle may show "已到零位".
assert comm.twoFDT600WK_classify_zero_status(1, 0.0) == (True, "已到零位")
assert comm.twoFDT600WK_classify_zero_status(0, 359.9999) == (True, "已到零位")
assert comm.twoFDT600WK_classify_zero_status(1, 0.02) == (False, "未到零位")
assert comm.twoFDT600WK_classify_zero_status(1, 180.0) == (False, "未到零位")

# Moving states must not be marked as zero even if the angle crosses 0°.
for state in (3, 4, 5, 6, 7, 8, 9):
    assert comm.twoFDT600WK_classify_zero_status(state, 0.0) == (False, "运动中")

assert comm.twoFDT600WK_classify_zero_status(99, 0.0) == (False, "状态未知")
assert comm.twoFDT600WK_classify_zero_status(1, float("nan")) == (False, "状态未知")
assert comm.twoFDT600WK_classify_zero_status(1, 360.0) == (False, "状态未知")

# The read API returns success for any successfully read state, and always refreshes
# the boolean/status output (including false after leaving state 2).
comm.twoFDT600WK_getAxisStateInfo = lambda axis, alarm, state, angle, err: (
    alarm.__setitem__(0, 0),
    state.__setitem__(0, 2),
    angle.__setitem__(0, 125.0),
    err.__setitem__(0, 0),
    True
)[-1]
at_zero = [True]
status = ["已到零位"]
err = [0]
assert comm.twoFDT600WK_getAxisZeroStatus(0, at_zero, status, err) is True
assert at_zero[0] is False and status[0] == "回零中"

comm.twoFDT600WK_getAxisStateInfo = lambda axis, alarm, state, angle, err: (
    alarm.__setitem__(0, 0),
    state.__setitem__(0, 1),
    angle.__setitem__(0, 45.0),
    err.__setitem__(0, 0),
    True
)[-1]
assert comm.twoFDT600WK_getAxisZeroStatus(0, at_zero, status, err) is True
assert at_zero[0] is False and status[0] == "未到零位"

comm.twoFDT600WK_getAxisStateInfo = lambda *args: False
assert comm.twoFDT600WK_getAxisZeroStatus(0, at_zero, status, err) is False
assert at_zero[0] is False and status[0] == "状态未知"

# Static guard: data polling must explicitly clear/update the 2FDT flags on read failure.
data_source = (ROOT / "turntable" / "turntable_data_get.py").read_text(encoding="utf-8-sig")
assert "twoFDT600WK_getAxisZeroStatus(" in data_source
assert 'turntableState.is_inner_axis_find_zero = None' in data_source
assert 'turntableState.is_outer_axis_find_zero = None' in data_source
assert 'turntableState.inner_axis_zero_status_text = "状态未知"' in data_source
assert 'turntableState.outer_axis_zero_status_text = "状态未知"' in data_source
assert 'turntableState.is_inner_axis_find_zero = None' in data_source
assert 'turntableState.is_outer_axis_find_zero = None' in data_source

imu_source = (ROOT / "form" / "form_imu_calibration.py").read_text(encoding="utf-8-sig")
assert '"inner_zero_status", "outer_zero_status"' in imu_source
assert 'item["inner_zero_status"], item["outer_zero_status"]' in imu_source

# R10 UI uses the state-summary text (not a dedicated "回零中" button label).
# Verify that state 2 is presented as homing and unknown codes remain explicit.
ui_source = (ROOT / "form" / "form_turntable_ctrl.py").read_text(encoding="utf-8-sig")
ui_tree = __import__('ast').parse(ui_source)
ui_cls = next(n for n in ui_tree.body if isinstance(n, __import__('ast').ClassDef)
              and n.name == 'FormTurntableCtrl')
summary_node = next(n for n in ui_cls.body if isinstance(n, __import__('ast').FunctionDef)
                    and n.name == '_2fdt_state_summary')
summary_module = __import__('ast').Module(body=[summary_node], type_ignores=[])
__import__('ast').fix_missing_locations(summary_module)
summary_ns = {'INNER_ROTATION_AXIS': 0, 'OUTER_ROTATION_AXIS': 2}
exec(compile(summary_module, str(ROOT / "form" / "form_turntable_ctrl.py"), 'exec'), summary_ns)
summary = summary_ns['_2fdt_state_summary']({
    0: {'name': '内轴', 'ok': True, 'state': 2, 'alarm': 0, 'angle': 125.0},
    2: {'name': '外轴', 'ok': True, 'state': 99, 'alarm': 0, 'angle': 0.0},
})
assert '内轴：状态 2（回零）' in summary
assert '外轴：状态 99（未知）' in summary

print("PASS: 2FDT600WK homing-in-progress, absolute-zero, moving, unknown and stale-state regressions")
