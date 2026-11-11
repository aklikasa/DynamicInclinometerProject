# -*- coding: utf-8 -*-
"""R4 product -40..85 C thermal protocol; pure functions; no hardware writes.

Two physically separate directional passes are intentional: current state store
identifies a sample by (temperature,step_id), and may not safely overwrite a
revisit of that same setpoint in one run.  A third party compares the two runs.
"""
from __future__ import annotations
import math

PRODUCT_MIN_C = -40.0
PRODUCT_MAX_C = 85.0
PROTOCOL = 'R4_PRODUCT_-40_85_5C_BIDIRECTIONAL_20261109'
FIT_RATES_DPS = (1.,2.,5.,10.,20.,30.)
VALID_RATES_DPS = (1.5,3.5,7.5,15.,25.)

def generate_temperature_plan(direction='warming'):
    if direction not in ('warming','cooling'):
        raise ValueError('仅支持warming升温或cooling降温')
    all_points=[float(x) for x in range(-40, 86, 5)]
    assert len(all_points)==26 and all_points[-1]==85.0
    fit=[float(x) for x in range(-40,81,10)]+[85.0]
    holdout=[v for v in all_points if v not in set(fit)]
    roles={t:('fit' if t in set(fit) else 'validate') for t in all_points}
    return {'protocol':PROTOCOL,'direction':direction,'min_c':PRODUCT_MIN_C,'max_c':PRODUCT_MAX_C,
            'fit_temperatures_c':fit,'validation_temperatures_c':holdout,
            'temperature_split':roles,
            'temperature_setpoints_c':all_points if direction=='warming' else list(reversed(all_points)),
            'method':'each 5C: every 10C fit; intermediate 5C independent holdout; 85C endpoint fit',
            'pass_isolation':'warming and cooling MUST use different experiment folders; do not mix rows under one temp key',
            'gyro_fit_rates_dps':list(FIT_RATES_DPS),'gyro_verify_rates_dps':list(VALID_RATES_DPS)}

def verify_plan(plan):
    if len(plan['temperature_setpoints_c'])!=26:raise ValueError('生产扫描必须完整覆盖26个温度点')
    expected=generate_temperature_plan(plan['direction'])
    if plan['temperature_setpoints_c']!=expected['temperature_setpoints_c']:
        raise ValueError('禁止改变温度扫描顺序')
    if plan['temperature_split']!=expected['temperature_split']:
        raise ValueError('禁止更改拟合/验证用途')
    return True

def check_user_hardware_clearance(approved:bool,plc:bool, fast:bool, strict:bool):
    if not approved:raise ValueError('未确认-40～85℃整机、线缆、转台及温箱安全，不启动生产实验')
    if not plc:raise ValueError('生产扫描必须使用可回读的PLC温箱，不接受人工温箱')
    if fast:raise ValueError('生产实验禁止绕过正式热平衡')
    # R7 accepts the explicit sealed production_adaptive policy. Historical
    # Boolean True remains the legacy strict mode; Boolean False is rejected.
    if strict not in (True, 1, 'production_adaptive'):
        raise ValueError('生产实验须选择严格恒温或R7生产完整姿态组质量模式')
    return True
