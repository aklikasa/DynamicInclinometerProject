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
            'not_production_release':True,'independent_run_folder_per_pass_required':True,'two_separate_run_folders_required':True}
    atomic_write_json(root/('R5_CYCLE_'+batch+'.json'),record)


def decide_repeated_transition(index, passes, success, stop_sent, complete, standstill_confirmed, plc_stop_confirmed):
    """Advance only after verified actual stop and complete acquisition.

    This is a pure decision: never commands hardware or skips a pass.
    """
    if not passes or index<0 or index>=len(passes):
        return {'action':'halt','status':'INVALID_PASS','reason':'循环索引不存在'}
    checks={'数据完成':success,'WK停车请求':stop_sent,
            '本次所有温度和工况完整':complete,
            'WK实际停车已确认':standstill_confirmed,
            'PLC停止回读已确认':plc_stop_confirmed}
    missing=[name for name,ok in checks.items() if not ok]
    if missing:return {'action':'halt','status':'STOPPED_INCOMPLETE','reason':'禁止自动接续：'+','.join(missing)}
    if index+1==len(passes):
        return {'action':'analyze','status':'ALL_CYCLES_COMPLETED','reason':'全部完整升降温周期采集完毕'}
    return {'action':'next','status':'PASS_COMPLETED','reason':'本趟安全停机确认，允许重新进行完整启动检查'}
