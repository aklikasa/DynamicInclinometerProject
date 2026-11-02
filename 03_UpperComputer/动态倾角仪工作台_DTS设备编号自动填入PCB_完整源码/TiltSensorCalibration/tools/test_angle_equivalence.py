# -*- coding: utf-8 -*-
"""无硬件/无Qt周期角度回归测试。运行：python tools/test_angle_equivalence.py"""
import ast
import sys
from pathlib import Path
from types import SimpleNamespace
import numpy as np
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from production_calibration import _static_circular_mean_degrees

source = ROOT / 'form' / 'form_imu_calibration.py'
tree = ast.parse(source.read_text(encoding='utf-8'))
funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in (
    '_wrapped_angle_error_deg', '_feedback_at_target')]
assert len(funcs) == 2
ns = {'np': np,
      'turntableData': SimpleNamespace(inner_axis_position=0., outer_axis_position=360.),
      'POSITION_TOLERANCE_DEG': 0.2}
exec(compile(ast.fix_missing_locations(ast.Module(body=funcs, type_ignores=[])),str(source),'exec'),ns)
check = ns['_feedback_at_target']
angle = ns['_wrapped_angle_error_deg']
assert check(0,0), '360 should match 0'
for actual in (0, 360, -360, 720, 359.9, 0.1):
    assert abs(angle(actual, 0)) <= 0.2, actual
for actual in (-60, 300, 660):
    assert abs(angle(actual, 300)) <= 1e-10, actual
assert abs(angle(180,-180)) < 1e-10
assert not abs(angle(359,0)) <= 0.2
assert not abs(angle(1,0)) <= 0.2
ns['turntableData'].inner_axis_position = 359.95
ns['turntableData'].outer_axis_position = 0.04
assert check(0,0)
ns['turntableData'].outer_axis_position = 0.3
assert not check(0,0)
ns['turntableData'].outer_axis_position = float('nan')
assert not check(0,0)
assert abs(angle(360,0)) == 0
assert min(abs(_static_circular_mean_degrees([359.9,0.1])-0),abs(_static_circular_mean_degrees([359.9,0.1])-360)) < 1e-8
assert abs(_static_circular_mean_degrees([300,300.1,299.9])-300) < 1e-8
assert abs(_static_circular_mean_degrees([360,0,360])-0) < 1e-8
try:
    _static_circular_mean_degrees([0, float('nan')])
except ValueError:
    pass
else:
    raise AssertionError('Invalid angles must be rejected')
print('PASS: 360°/0° periodic comparison, tolerance, invalid feedback and static circular mean')
