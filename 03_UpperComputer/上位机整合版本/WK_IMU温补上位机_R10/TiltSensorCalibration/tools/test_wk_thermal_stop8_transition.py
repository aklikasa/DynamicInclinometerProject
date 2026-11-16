# -*- coding: utf-8 -*-
"""2FDT600WK 温补停车8#->1#等待，硬件无关实测状态机回归。"""
import ast
import math
import threading
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'form'/'form_thermal_compensation.py'
source = SOURCE.read_text(encoding='utf-8')
tree = ast.parse(source)
cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'FormThermalCompensation')
methods = [next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name)
           for name in ('_wk_stop_confirmed','_begin_wk_stop_wait','_tick')]
class Clock:
    now = 0.0
    def monotonic(self): return self.now
clock = Clock()
state = {'inner':8,'outer':1,'alarm_inner':0,'alarm_outer':0,'read_ok':True}
feedback = types.SimpleNamespace(update_count=10,last_update_monotonic_ns=0,
                                 inner_axis_speed=0.,outer_axis_speed=0.)

def read_state(axis, alarm, status, angle, error):
    if not state['read_ok']:
        error[0] = 9
        return False
    name = 'inner' if axis == 0 else 'outer'
    status[0] = state[name]
    alarm[0] = state['alarm_'+name]
    angle[0] = 0.0
    error[0] = 0
    return True

wk = types.SimpleNamespace(twoFDT600WK_getAxisStateInfo=read_state)
imu = types.SimpleNamespace(data_lock=threading.Lock(),data_update_count=1,
                            acc_fs=8,gyro_fs=250,data_odr=208)
ns = dict(time=clock,turntableData=feedback,turntableComm=types.SimpleNamespace(thread_lock=threading.Lock()),
          wk_comm=wk,INNER_ROTATION_AXIS=0,OUTER_ROTATION_AXIS=2,
          tiltSensorRawData=imu,tilt_sensor_calibration_queue_drop_count_get=lambda:0,
          math=math)
runner = ast.ClassDef(name='Runner',bases=[],keywords=[],decorator_list=[],body=methods)
exec(compile(ast.fix_missing_locations(ast.Module(body=[runner],type_ignores=[])),str(SOURCE),'exec'),ns)

class Label:
    def __init__(self): self.text = ''
    def setText(self, value): self.text = str(value)
    def setValue(self, value): self.value = value

class Fake(ns['Runner']):
    def __init__(self):
        self.label, self.progress, self.plc_telemetry = Label(),Label(),Label()
        self.logs, self.saves = [],[]
        self.task = dict(phase='wait_stop',phase_start=0.0,manual=True,
                         baseline_config=(8,250,208),last_imu_count=1,last_imu_change=0.0,
                         temp_i=0,step_i=1,temps=[25.],
                         steps=[{'step_id':f'S{i}'} for i in range(3)],
                         pending_dynamic_row={'step_id':'S1'},rows=[],
                         stop_feedback_count=10,stop_ready_since=None,stop_wait_last_state=None)
    def _motion_status(self): pass
    def _collect(self): pass
    def _stopped(self):
        return abs(feedback.inner_axis_speed)<0.05 and abs(feedback.outer_axis_speed)<0.05
    def _log(self,s): self.logs.append(s)
    def _next_step_after_result(self,now):
        self.task['retry_count']=0
        self.task['step_i']+=1
        self.task['phase']='position'
    def _save_partial(self,*args): self.saves.append(args)
    def _abort(self,msg): raise RuntimeError(msg)

class StopState8Tests(unittest.TestCase):
    def setUp(self):
        clock.now=0.0
        state.update(inner=8,outer=1,alarm_inner=0,alarm_outer=0,read_ok=True)
        feedback.update_count=10
        feedback.inner_axis_speed=feedback.outer_axis_speed=0.0
        feedback.last_update_monotonic_ns=0
        imu.data_update_count=1
        self.f=Fake()

    def advance(self,now,count=None):
        clock.now=now
        feedback.last_update_monotonic_ns=round(now*1e9)
        feedback.update_count+=1 if count is None else count
        imu.data_update_count+=1

    def test_state8_never_releases_completed_row(self):
        for sec in (0.1,0.4,1.0,2.0):
            self.advance(sec)
            self.f._tick()
            self.assertEqual(self.f.task['phase'],'wait_stop')
            self.assertEqual(self.f.task['step_i'],1)
            self.assertEqual(self.f.task['rows'],[])
        self.assertIn('8#',self.f.label.text)
        self.assertFalse(self.f.saves)

    def test_true_1_servo_confirmed_for_half_second(self):
        self.advance(1.0)
        self.f._tick()
        state['inner']=1
        self.advance(1.1)
        self.f._tick()
        self.assertEqual(self.f.task['phase'],'wait_stop')
        self.advance(1.4)
        self.f._tick()
        self.assertEqual(self.f.task['phase'],'wait_stop')
        self.advance(1.65)
        self.f._tick()
        self.assertEqual(self.f.task['phase'],'position')
        self.assertEqual(self.f.task['step_i'],2)
        self.assertEqual([x['step_id'] for x in self.f.task['rows']],['S1'])
        self.assertEqual(len(self.f.saves),1)

    def test_state8_timeout_protects_uncommitted_data(self):
        self.advance(30.2)
        with self.assertRaisesRegex(RuntimeError,'超过30秒'):
            self.f._tick()
        self.assertEqual(self.f.task['rows'],[])
        self.assertEqual(self.f.task['step_i'],1)

    def test_alarm_or_disabled_aborts_without_release(self):
        for update in ({'alarm_inner':2},{'inner':0}):
            with self.subTest(update=update):
                self.setUp()
                state.update(update)
                self.advance(0.5)
                with self.assertRaises(RuntimeError):
                    self.f._tick()
                self.assertFalse(self.f.saves)

    def test_no_fresh_encoder_feedback_never_confirms(self):
        state['inner']=1
        clock.now=1.0
        feedback.last_update_monotonic_ns=int(1e9)
        self.f._tick()
        self.assertEqual(self.f.task['phase'],'wait_stop')
        self.assertFalse(self.f.saves)

    def test_one_axis_moving_never_confirms(self):
        state['inner']=state['outer']=1
        feedback.inner_axis_speed=0.1
        self.advance(.5)
        ready,detail=self.f._wk_stop_confirmed(self.f.task,clock.now)
        self.assertFalse(ready)
        self.assertIsNone(self.f.task['stop_ready_since'])

    def test_short_reentry_into_state8_resets_half_second_confirmation(self):
        state['inner']=state['outer']=1
        self.advance(1)
        self.f._tick()
        state['inner']=8
        self.advance(1.2)
        self.f._tick()
        state['inner']=1
        self.advance(1.3)
        self.f._tick()
        self.advance(1.6)
        self.f._tick()
        self.assertEqual(self.f.task['phase'],'wait_stop')
        self.advance(1.85)
        self.f._tick()
        self.assertEqual(self.f.task['phase'],'position')

    def test_retry_wait_requires_servo_before_reposition(self):
        self.f._begin_wk_stop_wait(self.f.task,0.0,retry=True)
        self.assertEqual(self.f.task['phase'],'wait_stop_retry')
        self.advance(.5)
        self.f._tick()
        self.assertEqual(self.f.task['phase'],'wait_stop_retry')
        state['inner']=1
        self.advance(1.0)
        self.f._tick()
        self.advance(1.6)
        self.f._tick()
        self.assertEqual(self.f.task['phase'],'position')
        self.assertEqual(self.f.task['rows'],[])
        self.assertEqual(self.f.task['step_i'],1)

    def test_wait_state_log_does_not_flood_each_poll(self):
        for sec in (.1,.2,.3,.4):
            self.advance(sec)
            self.f._tick()
        self.assertEqual(len(self.f.logs),1)

    def test_source_uses_guard_in_both_stop_paths(self):
        self.assertIn('self._begin_wk_stop_wait(t,now,retry=True)',source)
        self.assertIn('self._begin_wk_stop_wait(t,now)',source)
        self.assertIn('self._wk_stop_confirmed(t, now)',source)
        self.assertNotIn("if self._stopped():\n                    if t['phase']=='wait_stop'",source)

if __name__=='__main__': unittest.main(verbosity=2)
