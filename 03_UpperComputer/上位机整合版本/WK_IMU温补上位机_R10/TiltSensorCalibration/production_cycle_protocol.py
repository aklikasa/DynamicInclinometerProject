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

# R8 keeps the R7 pure-protocol default points for reproducibility, but
# accepts a user-selected bounded range, 5C sampling grid and repeat count.
PROTOCOL_R7 = PROTOCOL
PROTOCOL = 'R8_USER_RANGE_5C_REPEATED_CYCLES_20261110'


def validate_temperature_limits(min_c=-40.0,max_c=85.0,cycles=1):
    try:
        low=float(min_c);high=float(max_c);repeats=int(cycles)
    except (ValueError, TypeError) as exc:
        raise ValueError('最低温、最高温和循环次数须是有效数字') from exc
    if not all(math.isfinite(v) for v in (low,high)) or not (-40.0<=low<high<=85.0):
        raise ValueError('当前整机未经更宽温区验证：最低温>=-40℃、最高温<=85℃，且最低温必须小于最高温')
    if repeats<1 or repeats>99 or float(cycles)!=repeats:
        raise ValueError('完整升降温循环次数支持1～99次')
    return low,high,repeats


def cycle_passes(cycles=1):
    _,_,count=validate_temperature_limits(-40,85,cycles)
    return [{'index':idx,'cycle':idx//2+1,
             'direction':('warming' if idx%2==0 else 'cooling'),
             'key':f'cycle_{idx//2+1:02d}_'+('warming' if idx%2==0 else 'cooling')}
            for idx in range(2*count)]


def generate_temperature_plan(direction='warming', min_c=-40.0, max_c=85.0, cycles=1):
    if direction not in ('warming','cooling'):
        raise ValueError('仅支持warming升温或cooling降温')
    low,high,n=validate_temperature_limits(min_c,max_c,cycles)
    # No invented setpoints outside user limits. Endpoints explicitly included.
    k=int(math.floor((high-low)/5.0))
    points=[round(low+5.0*i,5) for i in range(k+1)]
    if not math.isclose(points[-1],high,abs_tol=1e-5):points.append(high)
    else:points[-1]=high
    fit=[t for idx,t in enumerate(points) if idx%2==0 or idx==len(points)-1]
    holdout=[t for t in points if t not in fit]
    roles={t:('fit' if t in fit else 'validate') for t in points}
    return {'protocol':PROTOCOL,'direction':direction,'min_c':low,'max_c':high,
            'cycle_count':n,'step_c':5.,'fit_temperatures_c':fit,
            'validation_temperatures_c':holdout, 'temperature_split':roles,
            'temperature_setpoints_c':(points if direction=='warming' else list(reversed(points))),
            'method':'5C steps from user min to user max; every other point FIT, intermediate independent validation; endpoint FIT',
            'pass_isolation':'each pass has its own THERM folder; repeated setpoints never share (setpoint, step_id) checkpoint key',
            'gyro_fit_rates_dps':list(FIT_RATES_DPS),'gyro_verify_rates_dps':list(VALID_RATES_DPS)}


def verify_plan(plan):
    expected=generate_temperature_plan(plan['direction'],plan.get('min_c',-40),plan.get('max_c',85),plan.get('cycle_count',1))
    if plan['temperature_setpoints_c']!=expected['temperature_setpoints_c']:
        raise ValueError('温度扫描顺序、上下限或步距不匹配')
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
