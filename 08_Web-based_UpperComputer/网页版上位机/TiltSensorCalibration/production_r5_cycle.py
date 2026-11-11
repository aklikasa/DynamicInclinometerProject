# -*- coding: utf-8 -*-
"""R5 dual-pass controller decisions; never issue hardware commands here.

Each scan retains R4 (setpoint,step) checkpoint keys in its own folder.
Combining rows inside a single run would silently overwrite repeated setpoints.
"""
from __future__ import annotations
import datetime
from pathlib import Path
from thermal_run_resume import atomic_write_json


def decide_transition(phase,success,stop_sent,complete,standstill_confirmed,plc_stop_confirmed):
    if phase not in ('warming','cooling'):
        return {'action':'halt','status':'FAILED','reason':'非法温度循环阶段'}
    if not (success and stop_sent and complete and standstill_confirmed and plc_stop_confirmed):
        missing=[key for key,ok in [('数据完成',success),('WK停车指令',stop_sent),
                 ('全部工况已接收',complete),('WK实际停车',standstill_confirmed),
                 ('PLC新鲜停机回读',plc_stop_confirmed)] if not ok]
        return {'action':'halt','status':'STOPPED_INCOMPLETE','reason':'不允许自动接续：'+','.join(missing)}
    if phase=='warming':
        return {'action':'next','status':'WARMING_COMPLETED','reason':'确认两轴停车和PLC停止，允许降温段重新执行启动安全检查'}
    return {'action':'analyze','status':'BOTH_PASSES_COMPLETED','reason':'两方向完成，自动合并研究报告'}


def write_cycle_manifest(root,cycle):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    batch=cycle.get('batch_id','')
    if not batch or any(not(c.isalnum() or c in '_-.') for c in batch):
        raise ValueError('批次ID只能包含文字数字下划线、短横线或点')
    record={**cycle,'manifest_updated_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'not_production_release':True,'two_separate_run_folders_required':True}
    atomic_write_json(root/('R5_CYCLE_'+batch+'.json'),record)
