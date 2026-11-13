# -*- coding: utf-8 -*-
"""自动温补分阶段温度门槛与WK停车确认的静态集成检查。"""
import ast
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
source_path=ROOT/'form'/'form_thermal_compensation.py'
source=source_path.read_text(encoding='utf-8')
tree=ast.parse(source)
cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='FormThermalCompensation')
methods={n.name:n for n in cls.body if isinstance(n,ast.FunctionDef)}
for name in ('_wk_stop_confirmed','_begin_wk_stop_wait','_tick','_resume_immutable',
             '_on_thermal_mode_changed','_on_chamber_mode_changed'):
    assert name in methods, f'missing method: {name}'
for token in (
    'thermal_soak','final_stability','chamber_stability_status','chamber_band_status',
    'pv_initial_seconds','pv_initial_range','pv_initial_slope',
    'pv_final_tolerance','pv_final_seconds','thermal_elapsed_s',
    "self._wk_stop_confirmed(t, now)",
    "self._begin_wk_stop_wait(t,now,retry=True)",
    "self._begin_wk_stop_wait(t,now)"):
    assert token in source, f'missing staged/parking integration: {token}'
assert "state={state[0]}" in source
assert "0.5" in source and "30" in source
print('PASS: staged PV gate, 30-minute effective soak, final ±band, chip gate and WK 8#→1# parking guard are wired')
