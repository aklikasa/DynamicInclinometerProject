# -*- coding: utf-8 -*-
"""R6 no-skip production regression tests (supersedes obsolete R5 auto-skip tests)."""
import ast
import unittest
from pathlib import Path
SOURCE=Path(__file__).resolve().parents[1]/'form'/'form_thermal_compensation.py'


def method(name):
    tree=ast.parse(SOURCE.read_text(encoding='utf-8'))
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='FormThermalCompensation')
    fn=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name==name)
    ns={};exec(compile(ast.fix_missing_locations(ast.Module([fn],type_ignores=[])),str(SOURCE),'exec'),ns)
    return ns[name]


class NoAutoSkipTests(unittest.TestCase):
    def fixture(self,accepted):
        class F:
            def __init__(self):
                self.task={'temp_i':0,'step_i':1,'temps':[-40,-35],
                           'steps_by_temperature':[[{'step_id':'A1'},{'step_id':'G1'}],[{'step_id':'V1'}]],
                           'rows':[{'temperature_target_c':-40,'step_id':k} for k in accepted],
                           'replay_mode':False,'replay_queue':[],'guard':None}
                self.logs=[];self.aborted=[];self.saved=[]
            def _log(self,msg):self.logs.append(msg)
            def _abort(self,msg):self.aborted.append(msg)
            def _save_partial(self,*args):self.saved.append(args)
            _halt_incomplete_temperature=method('_halt_incomplete_temperature')
            _advance_temperature=method('_advance_temperature')
            _skip_current_temperature_for_quality=method('_skip_current_temperature_for_quality')
        return F()

    def test_old_autoskip_entry_is_fail_closed(self):
        f=self.fixture(['A1'])
        f._skip_current_temperature_for_quality(0,'五次暂停')
        self.assertEqual(f.task['temp_i'],0)
        self.assertEqual(len(f.aborted),1)
        self.assertIn('禁止自动跳温',f.aborted[0])

    def test_unfinished_steps_block_next_temperature(self):
        f=self.fixture(['A1'])
        f._advance_temperature(0)
        self.assertEqual(f.task['temp_i'],0)
        self.assertTrue(f.aborted)
        self.assertIn('G1',f.aborted[0])

    def test_all_steps_accepted_allows_next_temperature(self):
        f=self.fixture(['A1','G1'])
        f._advance_temperature(0)
        self.assertEqual(f.task['temp_i'],1)
        self.assertEqual(f.task['phase'],'next_temperature')
        self.assertFalse(f.aborted)

    def test_automatic_skip_call_site_removed(self):
        src=SOURCE.read_text(encoding='utf-8')
        self.assertNotIn('self._skip_current_temperature_for_quality(now,',src)
        self.assertIn('self._halt_incomplete_temperature(',src)
        self.assertIn("'temperature_advance_requires_full_completion':True",src)
        self.assertIn("if not self._stop_axes():",src)


class StateMachineTests(unittest.TestCase):
    """Compatibility fixture for return-to-ambient safety regressions.

    Old skip-related tests were replaced above; external readiness tests still
    import this helper to exercise the unchanged 25C shutdown condition.
    """
    def fake_step(self,phase,now=8000,started=0,hold_count=5):
        import threading, types
        from unittest.mock import Mock
        class F:
            def __init__(self):
                self.task=dict(manual=False,phase=phase,phase_start=100.,
                               temperature_wait_started=started,temps=[5.0,7.5],
                               temp_i=0,step_i=0,steps=[dict(step_id='ACC_FIT_01')],
                               baseline_config=('acc','gyro',100),
                               last_imu_count=1,last_imu_change=now-1,
                               chip_stability_only=False,pv_stable_since=None,
                               return_ambient=True,rows=[],ui_max_progress=0)
                self._feedback_jsonl=None
                self.label=Mock();self.plc_telemetry=Mock();self.progress=Mock()
                self.confirm_temp=Mock();self.aborted=[];self.saved=[]
                self.chamber=dict(pv=25.,sp=25.,pv_updated=now-0.1,running=True,alarm=0)
            def _motion_status(self):pass
            def _collect(self):pass
            def _require_plc(self,*a):return self.chamber
            def _log(self,*a):pass
            def _abort(self,msg):self.aborted.append(msg)
            def _stopped(self):return True
            def _save_partial(self,*a):self.saved.append(a)
        f=F()
        imu=types.SimpleNamespace(data_lock=threading.RLock(),data_update_count=1,
                                  acc_fs='acc',gyro_fs='gyro',data_odr=100)
        env={'time':types.SimpleNamespace(monotonic=lambda:now),
             'tilt_sensor_calibration_queue_drop_count_get':lambda:0,
             'tiltSensorRawData':imu,'require_setpoint_ack':lambda *_:None}
        return f,method('_tick_with_dummy_name') if False else method_env('_tick',env)


def method_env(name,env):
    tree=ast.parse(SOURCE.read_text(encoding='utf-8'))
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='FormThermalCompensation')
    fn=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name==name)
    ns=dict(env);exec(compile(ast.fix_missing_locations(ast.Module([fn],type_ignores=[])),str(SOURCE),'exec'),ns)
    return ns[name]

if __name__=='__main__':unittest.main()
