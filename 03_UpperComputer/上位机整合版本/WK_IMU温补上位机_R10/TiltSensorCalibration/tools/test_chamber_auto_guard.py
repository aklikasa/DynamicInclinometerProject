# -*- coding: utf-8 -*-
"""Tests for the automatic Snap7/PLC chamber safety gates; no hardware writes."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from chamber_auto_guard import require_live_chamber, require_setpoint_ack, ChamberSafetyError


def snapshot(now=100.0):
    return {'connected':True,'data_available':True,'pv_failed':False,
            'pv':25.0,'sp':25.0,'pv_updated':99.0,'sp_updated':99.0,
            'alarm':0,'fault':False,'alarm_updated':99.0,'fault_updated':99.0,
            'running':True,'fixed_started':True,'fixed_mode':True,
            'run_updated':99.0,'started_updated':99.0,'mode_updated':99.0}


def must_fail(data, now=100.0, ack=False):
    try:
        if ack:require_setpoint_ack(data,25.0)
        else:require_live_chamber(data,now)
    except ChamberSafetyError:
        return
    raise AssertionError('不应允许异常PLC状态继续执行')


def run():
    good=snapshot()
    assert require_live_chamber(good,100)
    assert require_setpoint_ack(good,25)
    count=2
    for key,val in [
        ('connected',False),('data_available',False),('pv_failed',True),
        ('pv',float('nan')),('pv',130.),('sp',float('nan')),
        ('alarm',3),('fault',True)]:
        bad=snapshot();bad[key]=val;must_fail(bad);count+=1
    for key in ('pv_updated','sp_updated','alarm_updated','fault_updated',
                'run_updated','started_updated','mode_updated'):
        bad=snapshot();bad[key]=50.0;must_fail(bad);count+=1
        bad=snapshot();bad[key]=0.0;must_fail(bad);count+=1
    for key,val in [('sp',23.0),('running',False),('fixed_started',False),('fixed_mode',False)]:
        bad=snapshot();bad[key]=val;must_fail(bad,ack=True);count+=1
    print(f'PASS: PLC自动温补健康状态、回读、失联/过期/报警/未运行共{count}种检查')


if __name__=='__main__':run()
