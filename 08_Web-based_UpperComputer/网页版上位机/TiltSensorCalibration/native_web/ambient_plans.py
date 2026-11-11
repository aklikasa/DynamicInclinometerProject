# -*- coding: utf-8 -*-
"""Original R7 ambient calibration plans; read-only. No motor writes.

Next stage is a Qt-independent, formally commissioned state machine.
This module never drives motors or claims that an automatic job can run.
"""
from __future__ import annotations
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent


def ambient_plan(kind: str) -> dict:
    # production_calibration is pure R7 numerical configuration (numpy, no Qt).
    from production_calibration import load_profile,acc_fit_steps,acc_verify_steps,gyro_fit_steps,gyro_verify_steps
    profile=load_profile(str(ROOT))
    if kind=='acc':
        steps=acc_fit_steps()+acc_verify_steps()
        title='ACC 常温 12 姿态拟合 + 12 姿态独立验证'
    elif kind=='gyro':
        steps=gyro_fit_steps(profile)+gyro_verify_steps(profile)
        title='GYRO 零偏 + 正反转多速率拟合及独立验证'
    else:
        raise ValueError('未知工况计划，只允许 acc/gyro')
    proposed=profile['rates'].get('proposed_after_turntable_approval',{})
    proposal_rates=list(proposed.get('fit_dps',[]))+list(proposed.get('verify_dps',[])) if isinstance(proposed,dict) else []
    warnings=[]
    if any(float(v)>60 for v in proposal_rates):
        warnings.append('原 R7 工艺配置中的【未启用】拟议速率包含超过 2TD-600 说明书额定 60°/s 的数值，不能直接启用。')
    warnings.append('原 R7 自动工况的安装姿态、双轴互锁、锁紧机构、线缆、速度与停车逻辑，尚待现场校核。')
    return {'title':title,'kind':kind,'profile_id':profile['profile_id'],
            'approved_for_production':bool(profile.get('approved_for_production',False)),
            'rates':profile['rates'],'timing':profile['timing'],'steps':steps,'warnings':warnings,
            'automatic_execution_available':False,
            'notice':'只读工况：当前不会让转台运动；必须通过现场联调后才能接入自动执行。'}
