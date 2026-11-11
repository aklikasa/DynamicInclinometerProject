# -*- coding: utf-8 -*-
"""PLC initial staged-setpoint planner; not a physical temperature ramp controller.

The workstation already owns a tested fixed-SP write/readback path.  This
module ONLY plans intermediate targets for that existing path.  Each stage
must be acknowledged, and its live PV observed, before the next SP is sent.
"""
import math


def initial_stages(current_pv_c, final_target_c, max_step_c=5.0):
    """Return intermediate SP values (final target excluded).

    Return [] for a target that needs at most one SP step.  Temperatures are
    intentionally limited to the application's research operating envelope;
    hard PLC protections and device approval remain independent.
    """
    now, target, step = map(float, (current_pv_c, final_target_c, max_step_c))
    if not all(math.isfinite(v) for v in (now,target,step)):
        raise ValueError('自动设温的PV/目标/每级温差必须是有限数值')
    if not (-45 <= now <= 90 and -40 <= target <= 85):
        raise ValueError('自动设温当前PV或目标超出已定义研究范围')
    if not 1.0 <= step <= 8.0:
        raise ValueError('每级SP改变量必须在1～8℃之间')
    delta = target - now
    if abs(delta) <= step + 1e-9:
        return []
    direction = 1.0 if delta > 0 else -1.0
    n = int(math.ceil(abs(delta) / step)) - 1
    if n > 150:
        raise ValueError('自动温度阶段过多')
    stages = [round(now + direction * step * (i + 1), 2) for i in range(n)]
    # All segments, including the final target, are <= step; protect against
    # floating-point rounding to a 0.01 C device setpoint.
    all_points = [now] + stages + [target]
    if any(abs(b-a) > step+0.015 for a,b in zip(all_points,all_points[1:])):
        raise ValueError('自动到温分段超出每级SP变化上限')
    return stages
