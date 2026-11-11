# -*- coding: utf-8 -*-
"""Explicit, immutable experiment-local policies, never overrides PLC alarm protection.

Both modes require fresh PLC PV/SP/status, 60 s stable chip windows, encoder
reference quality and physical WK stop confirmation.  Continuous mode reduces
quality-only interruptions, NOT the PLC's own hardware safety protections.
"""

POLICIES = {
    'continuous': {
        'gate': 'plc_staged_continuous_v3',
        'dwell_seconds': 900,
        'pv_initial_window_seconds': 120,
        'pv_initial_band_c': 1.5,
        'pv_initial_range_c': 0.80,
        'pv_initial_slope_c_per_min': 0.20,
        'soak_band_c': 1.5,
        'pv_final_tolerance_c': 1.00,
        'pv_final_stable_seconds': 120,
        'runtime': {'pv_pause_c': 1.25, 'pv_hold_seconds': 120,
                    'resoak_pv_c': 2.0, 'resoak_hold_seconds': 120,
                    'chip_span_c': 0.65, 'chip_span_hold_seconds': 90,
                    'chip_slope_c_per_min': 0.25, 'chip_slope_hold_seconds': 120,
                    'recovery_pv_c': 0.75, 'recovery_chip_span_c': 0.25,
                    'recovery_chip_slope_c_per_min': 0.15},
        'chip_gate_60s_span_c': 0.25,
        'chip_5min_slope_gate_c_per_min': 0.20,
        'description': '研发连续温补：每个工况实测芯片温度；跨姿态温差只记录，12姿态仍整组拟合'
    },
    'strict': {
        'gate': 'plc_staged_v1',
        'dwell_seconds': 1800,
        'pv_initial_window_seconds': 300,
        'pv_initial_band_c': 1.0,
        'pv_initial_range_c': 0.30,
        'pv_initial_slope_c_per_min': 0.055,
        'soak_band_c': 1.0,
        'pv_final_tolerance_c': 0.10,
        'pv_final_stable_seconds': 300,
        # Exactly the same effective defaults formerly supplied implicitly by
        # ThermalRuntimeGuard(...). Freeze them explicitly so switching the
        # strict mode cannot crash the UI on missing runtime keys.
        'runtime': {'pv_pause_c':0.50,'pv_hold_seconds':30.0,
                    'resoak_pv_c':1.0,'resoak_hold_seconds':30.0,
                    'chip_span_c':0.40,'chip_span_hold_seconds':30.0,
                    'chip_slope_c_per_min':0.10,'chip_slope_hold_seconds':60.0,
                    'recovery_pv_c':0.30,'recovery_chip_span_c':0.20,
                    'recovery_chip_slope_c_per_min':0.05},
        'chip_gate_60s_span_c': 0.20,
        'chip_5min_slope_gate_c_per_min': None,
        'description': '严格恒温门槛：仅用于高精度稳态实验，跨姿态温差也不删除已通过单工况质检的记录'
    },
}


# Production-adaptive quality defaults are initial suggestions, all editable
# before a new run. PLC alarms and WK mechanical guards remain independent.
from copy import deepcopy
POLICIES['production_adaptive'] = deepcopy(POLICIES['continuous'])
POLICIES['production_adaptive'].update({
    'pv_initial_window_seconds':120,
    'pv_initial_band_c':2.0,'pv_initial_range_c':2.0,
    'pv_initial_slope_c_per_min':1.0,'soak_band_c':2.5,
    'pv_final_tolerance_c':2.0,'pv_final_stable_seconds':120,
    'chip_gate_60s_span_c':2.0,
    'chip_5min_slope_gate_c_per_min':2.0,
    'runtime':{
        'pv_pause_c':3.0,'pv_hold_seconds':120,
        'resoak_pv_c':4.0,'resoak_hold_seconds':120,
        'chip_span_c':3.0,'chip_span_hold_seconds':90,
        'chip_slope_c_per_min':2.5,'chip_slope_hold_seconds':120,
        'recovery_pv_c':2.0,'recovery_chip_span_c':2.0,
        'recovery_chip_slope_c_per_min':2.0},
})
POLICIES['production_adaptive']['description']=(
    'R9生产自适应：按2℃现场波动初始化所有PV/芯片质量参数，'
    '全部可手动设置；PLC报警和WK停车保护独立。')


def policy_for(name):
    if name not in POLICIES:
        raise ValueError('未知温度采集模式: '+str(name))
    from copy import deepcopy
    return deepcopy(POLICIES[name])
