# -*- coding: utf-8 -*-
"""无硬件静态采样质控 + 5次重试状态机回归。"""
import ast
import sys
import copy
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from production_calibration import load_profile, robust_segment
from test_production_calibration import fake_frames

PROFILE = load_profile(ROOT)

def check_acc_vs_gyro():
    frames = fake_frames(num=100)
    for i, f in enumerate(frames):
        f['gyro'] = [5*np.sin(i), 4*np.cos(i), -6*np.sin(i*.7)]
    result = robust_segment(frames, 'static', PROFILE, static_sensor='acc')
    assert result['accepted_frames'] >= 90, result
    assert max(result['gyro_std_dps']) > .45
    try:
        robust_segment(frames, 'static', PROFILE, static_sensor='both')
    except ValueError as e:
        assert 'GYRO抖动' in str(e), e
    else:
        raise AssertionError('Six-axis verification unexpectedly accepted noisy gyro')
    # 加速度计采样阶段容许无有效 GYRO 数据；只把 GYRO 当诊断信息。
    frames = fake_frames(num=100)
    for f in frames: f['gyro'] = [None, None, None]
    result = robust_segment(frames, 'static', PROFILE, static_sensor='acc')
    assert result['gyro_raw_mean_dps'] is None
    # ACC 本身确实不稳定则拒绝，不因忽略 GYRO 放宽 ACC 质控。
    frames = fake_frames(num=100)
    for i,f in enumerate(frames): f['acc'][0] += .1*np.sin(i)
    try:
        robust_segment(frames, 'static', PROFILE, static_sensor='acc')
    except ValueError as e: assert 'ACC抖动' in str(e), e
    else: raise AssertionError('Failed to reject unstable ACC')
    # Gyro static zero still checks gyro jitter
    try:
        noisy=fake_frames(num=100)
        for i, f in enumerate(noisy): f['gyro'][0] += 1.2*np.sin(i)
        robust_segment(noisy, 'static', PROFILE, static_sensor='gyro')
    except ValueError as e: assert 'GYRO抖动' in str(e), e
    else: raise AssertionError('Failed to reject unstable gyro zero')


def check_state_machine():
    path = ROOT/'form'/'form_imu_calibration.py'
    module=ast.parse(path.read_text(encoding='utf-8'))
    klass=next(x for x in module.body if isinstance(x,ast.ClassDef) and any(isinstance(m,ast.FunctionDef) and m.name=='_retry_static_sample_or_abort' for m in x.body))
    methods = [m for m in klass.body if isinstance(m,ast.FunctionDef) and m.name in ('_retry_static_sample_or_abort', '_advance_auto_step', '_complete_static_sample')]
    class Mock:
        def __init__(self):
            self._auto_task={ 'type':'accel', 'phase':'sample_static', 'index':0,
                              'steps':[{'step_id':'ACC_FIT_03','mode':'static','split':'fit','inner_deg':90.,'outer_deg':90.},
                                       {'step_id':'ACC_FIT_04','mode':'static','split':'fit','inner_deg':180.,'outer_deg':90.}],
                              'static_retry_count':0, 'static_retry_history':[],
                              'last_static_quality_error':'', 'sample_frames':fake_frames(num=100),
                              'sample_started':50, 'stable_since':None, 'phase_started':50,
                              'quality_profile':PROFILE, 'pose_measurements':[] }
            self.label_auto_task=type('L',(),{'setText':lambda s,t:None})()
            self.events=[];self.aborts=[]
        def _log_event(self,*a): self.events.append(a)
        def _request_auto_abort(self,reason): self.aborts.append(reason); self._auto_task['phase']='aborting'
        def _update_auto_progress(self): pass
        def _complete_auto_task(self): pass
    ns={'robust_segment':robust_segment,'_now_iso':lambda:'2026-10-22T10:45:54+08:00','time':__import__('time')}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.ClassDef(name='Methods',bases=[],keywords=[],body=methods,decorator_list=[])],type_ignores=[])), str(path),'exec'),ns)
    for method in methods: setattr(Mock,method.name,getattr(ns['Methods'],method.name))
    m=Mock(); step=m._auto_task['steps'][0]
    # make bad accelerometer repeatedly, five retry transitions, no index advancement or fit data
    for retry in range(1,6):
        bad=fake_frames(num=100)
        for i, f in enumerate(bad): f['acc'][0] += .1*np.sin(i)
        m._auto_task['phase']='sample_static';m._auto_task['sample_frames']=bad
        assert not m._complete_static_sample(step)
        m._retry_static_sample_or_abort(step, 100+retry)
        assert m._auto_task['static_retry_count']==retry
        assert m._auto_task['phase']=='wait_position'
        assert m._auto_task['index']==0
        assert not m._auto_task['sample_frames']
        assert len(m._auto_task['static_retry_history'])==retry
        assert not m.aborts
    # sixth attempt succeeds, exactly one row stored, next step retry reset
    m._auto_task['phase']='sample_static';m._auto_task['sample_frames']=fake_frames(num=100)
    assert m._complete_static_sample(step)
    assert len(m._auto_task['pose_measurements'])==1
    assert m._auto_task['pose_measurements'][0]['attempts']==6
    m._advance_auto_step()
    assert m._auto_task['index']==1 and m._auto_task['static_retry_count']==0
    # fresh mock must stop after sixth failed attempt
    m=Mock();step=m._auto_task['steps'][0]
    for retry in range(1,7):
        m._auto_task['last_static_quality_error']='ACC抖动超限'
        m._retry_static_sample_or_abort(step,100+retry)
    assert len(m.aborts)==1 and len(m._auto_task['static_retry_history'])==6
    assert m._auto_task['phase']=='aborting' and m._auto_task['index']==0
    assert '共 6 次采样' in m.aborts[0]
    print('PASS: ACC ignores gyro jitter, gyro zero still checks gyro, 5 retries/6 attempts, abort on sixth failure')

if __name__=='__main__':
    check_acc_vs_gyro();check_state_machine()
