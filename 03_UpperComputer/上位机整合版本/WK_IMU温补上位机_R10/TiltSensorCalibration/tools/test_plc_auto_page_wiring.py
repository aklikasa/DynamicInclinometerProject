# -*- coding: utf-8 -*-
"""Static checks of new automatic path independent of Qt/DLL."""
import ast
from pathlib import Path
root=Path(__file__).resolve().parents[1]
page=(root/'form/form_thermal_compensation.py').read_text(encoding='utf-8')
tree=ast.parse(page)
cls=next(c for c in tree.body if isinstance(c,ast.ClassDef) and c.name=='FormThermalCompensation')
methods={n.name:n for n in cls.body if isinstance(n,ast.FunctionDef)}
for name in ('_plc_snapshot','_require_plc','_issue_plc_setpoint','_on_chamber_mode_changed','_tick'):
    assert name in methods
assert page.index("'plc')")<page.index("'manual')"), '自动控温必须是第一项默认选项'
assert "t['phase']='verify_plc_sp'" in page
assert "require_setpoint_ack(chamber,target)" in page
assert 'self._issue_plc_setpoint(target)' in page
assert 'OFFLINE_DEBUG' in page
assert 'self.check_plc.isChecked()' in page
assert 't[\'pv_stable_since\']' in page
assert "t['phase']='verify_return'" in page
assert 'tc_fixed_value_stop()' in page
poll=(root/'temperature_chamber/temperature_chamber_data_get.py').read_text(encoding='utf-8')
for name in ('pv_update_monotonic','sp_update_monotonic','alarm_update_monotonic','fault_update_monotonic','run_update_monotonic'):
    assert name in poll
assert 'tcData.is_tc_data_available = not is_pv_get_failed' in poll
print('PASS: 自动PLC温补页面默认模式/回读门槛/PV稳定/读数新鲜度静态检查')
