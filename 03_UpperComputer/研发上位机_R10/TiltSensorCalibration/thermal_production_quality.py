# -*- coding: utf-8 -*-
"""Immutable, validated calibration quality gates and required condition checks.

These controls do not replace independent PLC alarms or mechanical e-stop.
"""
import math

RUNTIME_FIELDS = ('pv_pause_c','pv_hold_seconds','resoak_pv_c','resoak_hold_seconds',
                  'chip_span_c','chip_span_hold_seconds','chip_slope_c_per_min',
                  'chip_slope_hold_seconds','recovery_pv_c','recovery_chip_span_c',
                  'recovery_chip_slope_c_per_min')


def validated_runtime_policy(params):
    if set(params) != set(RUNTIME_FIELDS):
        raise ValueError('运行期温控策略缺少或包含未知参数')
    p = {k: float(params[k]) for k in RUNTIME_FIELDS}
    if not all(math.isfinite(v) for v in p.values()):
        raise ValueError('温控阈值不能包含无效数值')
    if p['pv_pause_c'] <= 0 or p['resoak_pv_c'] <= p['pv_pause_c']:
        raise ValueError('重新热浸PV偏差必须大于运行暂停PV偏差；请在界面调整')
    if not 0 < p['recovery_pv_c'] < p['pv_pause_c']:
        raise ValueError('恢复PV偏差必须小于运行暂停PV偏差；请在界面调整')
    if not 0 < p['recovery_chip_span_c'] <= p['chip_span_c']:
        raise ValueError('恢复芯片温差必须小于或等于运行芯片温差上限')
    if not 0 < p['recovery_chip_slope_c_per_min'] <= p['chip_slope_c_per_min']:
        raise ValueError('恢复芯片斜率必须小于或等于运行芯片斜率上限')
    for k in ('pv_hold_seconds','resoak_hold_seconds','chip_span_hold_seconds',
              'chip_slope_hold_seconds'):
        if p[k] < 1:
            raise ValueError(k+'的持续时间必须大于或等于1秒')
    return p


def missing_at_temperature(temperature, steps, accepted_rows):
    """All planned IDs must have a matching *accepted* row at this temperature."""
    target = float(temperature)
    accepted = {str(row['step_id']) for row in accepted_rows
                if math.isclose(float(row.get('temperature_target_c',float('nan'))),
                                target,rel_tol=0,abs_tol=1e-5)
                and row.get('step_id') is not None}
    planned = [str(step['step_id']) for step in steps]
    if len(set(planned)) != len(planned):
        raise ValueError('温度点计划存在重复step_id，不允许自动通过完整性检查')
    return [k for k in planned if k not in accepted]
