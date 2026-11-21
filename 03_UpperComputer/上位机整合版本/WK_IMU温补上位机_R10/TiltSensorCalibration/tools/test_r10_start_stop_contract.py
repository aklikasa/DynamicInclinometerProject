# -*- coding: utf-8 -*-
"""Safety/completion/constructor regressions. Hardware and Qt not required."""
import ast
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

SOURCE=Path(__file__).resolve().parents[1]/'form'/'form_thermal_compensation.py'
module=ast.parse(SOURCE.read_text(encoding='utf8'))
cls=next(n for n in module.body if isinstance(n,ast.ClassDef) and n.name=='FormThermalCompensation')

def method(name,extra):
    fn=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name==name)
    block=ast.Module(body=[fn],type_ignores=[])
    ast.fix_missing_locations(block)
    scope=dict(extra)
    exec(compile(block,str(SOURCE),'exec'),scope)
    return scope[name]

class TestStartStopContract(unittest.TestCase):
    def test_constructor_order_no_read_before_write(self):
        fn=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='_make_ui')
        first_read={};first_write={}
        for node in ast.walk(fn):
            if not (isinstance(node,ast.Attribute) and isinstance(node.value,ast.Name)
                    and node.value.id=='self'): continue
            d=first_write if isinstance(node.ctx,ast.Store) else first_read
            d[node.attr]=min(node.lineno,d.get(node.attr,node.lineno))
        premature={name:(read,first_write[name]) for name,read in first_read.items()
                   if name in first_write and read<first_write[name]}
        self.assertEqual(premature,{})
        for attr in ('wk_mean_error','wk_slope_delta','wk_position_residual'):
            self.assertIn(attr,first_write)
        self.assertLess(first_write['wk_position_residual'],
                        max(node.lineno for node in ast.walk(fn)
                            if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute)
                            and node.func.attr=='setRange' and node.lineno>first_write['wk_position_residual']))

    def test_plc_stop_write_failure_must_not_finish_successfully(self):
        calls=[]
        comm=SimpleNamespace(thread_lock=threading.RLock(),is_connected=True)
        fn=method('_begin_chamber_shutdown',{
            'time':time,'tcComm':comm,'tc_fixed_value_stop':lambda:False})
        class Fake:
            def __init__(self):
                self.task={'manual':False,'final_stop_confirmed':True,
                           'finish_success_reason':'all data captured'}
            def _save_partial(self,*args):calls.append(('saved',args))
            def _log(self,*args):pass
            def _finish(self,success,reason):calls.append(('finish',success,reason))
        f=Fake();fn(f,time.monotonic())
        self.assertEqual(f.task['plc_stop_command_ok'],False)
        self.assertEqual([c[1] for c in calls if c[0]=='finish'],[False])

    def test_plc_stop_feedback_timeout_must_not_finish_successfully(self):
        fn=method('_tick',{'time':time})
        calls=[]
        class Fake:
            def __init__(self):
                self.task={'phase':'verify_chamber_stop','phase_start':time.monotonic()-95,
                           'plc_stop_command_time':time.monotonic()-95,
                           'finish_success_reason':'all data captured'}
                self.label=SimpleNamespace(setText=lambda *args:None)
            def _require_plc(self,now):raise ValueError('PLC stop feedback stale')
            def _log(self,*args):pass
            def _finish(self,success,reason):calls.append((success,reason))
        fn(Fake())
        self.assertEqual(len(calls),1)
        self.assertFalse(calls[0][0])
        self.assertIn('INCOMPLETE',calls[0][1])

    def test_complete_rows_not_enough_without_confirmed_plc_stop(self):
        captured=[]
        fn=method('_finish',{
            'missing_planned_conditions':lambda *args:[],
            'build_result_readiness':lambda *args,**kwargs:{'total_missing':0},
            'write_result_readiness':lambda *args,**kwargs:None,
            'tilt_sensor_calibration_queue_set':lambda *args:None,
            'turntable_feedback_queue_set':lambda *args:None,
            'QMessageBox':SimpleNamespace(warning=lambda *args:None,
                                          critical=lambda *args:None),
            'Path':Path,
        })
        class Fake:
            def __init__(self):
                self.task={'run_dir':'.','rows':[], 'temps':[5],
                           'steps_by_temperature':[[]],
                           'temperature_split_by_setpoint':{},'manual':False,
                           'final_stop_confirmed':True,'plc_stop_confirmed':False,
                           'plc_stop_requested':True, 'unresolved':[], 'dynamic':False}
                self._r5_cycle=None
                self.start_button=Mock();self.stop_button=Mock()
                self.rearm_thermal_button=Mock();self.confirm_temp=Mock()
                self.label=Mock();self.label.text.return_value="";self.page=Mock()
            def _log(self,*args):pass
            def _save_partial(self,status,*args):captured.append(status)
            def _lock_ui(self,*args):pass
        obj=Fake();fn(obj,True,'all conditions done')
        self.assertEqual(captured,['INCOMPLETE'])
        self.assertIsNone(obj.task)

    def test_group_spread_abort_does_not_advance(self):
        fn=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='_tick')
        group_checks=[node for node in ast.walk(fn) if isinstance(node,ast.If)
                      and isinstance(node.test,ast.Call)
                      and isinstance(node.test.func,ast.Attribute)
                      and node.test.func.attr=='_audit_current_temperature_groups']
        self.assertEqual(len(group_checks),1)
        self.assertTrue(any(isinstance(node,ast.Return) for node in group_checks[0].body))

    def test_quality_modes_all_have_editable_complete_runtime_policies(self):
        from thermal_temperature_policy import policy_for
        from thermal_production_quality import validated_runtime_policy
        for name in ('strict','continuous','production_adaptive'):
            policy=policy_for(name)
            self.assertEqual(validated_runtime_policy(policy['runtime']),policy['runtime'])

    def test_recovery_window_uses_frozen_operator_seconds(self):
        fn=method('_start_temperature_hold',{})
        class Fake:
            def __init__(self):
                self.task={'temp_i':0,'phase':'position',
                           'thermal_holds_per_temp':{},'frames':[],
                           'temperature_quality_mode':'production_adaptive',
                           'hold_count':0,'thermal_recovery_qualified_seconds':45.0}
            def _stop_axes(self):return True
            def _begin_wk_stop_wait(self,t,now):t['phase']='wait_stop'
            def _log(self,*args):pass
        obj=Fake();fn(obj,123.0,'test quality hold')
        self.assertEqual(obj.task['thermal_recovery_seconds'],45.0)
        self.assertEqual(obj.task['phase'],'wait_stop_thermal')

    def test_temperature_quality_wait_not_capped_by_hidden_six_hours(self):
        source=SOURCE.read_text(encoding='utf8')
        self.assertNotIn('now-wait_start>21600',source)
        self.assertIn('thermal_max_wait_minutes',source)

if __name__=='__main__':unittest.main()
