# -*- coding: utf-8 -*-
"""No-hardware regression tests for continuous thermal policy and stop-readback.

These tests compile only the relevant UI class methods via ast because
PySide6, Snap7 and the WK DLL are intentionally unavailable in the CI runner.
"""
import ast
import json
import threading
import types
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

from thermal_temperature_policy import policy_for
from thermal_runtime_guard import ThermalRuntimeGuard
from thermal_excel_report import export_thermal_xlsx

SOURCE = Path(__file__).resolve().parents[1] / 'form' / 'form_thermal_compensation.py'


def compile_method(name, globals_):
    module=ast.parse(SOURCE.read_text(encoding='utf-8'))
    cls=next(n for n in module.body if isinstance(n,ast.ClassDef) and n.name=='FormThermalCompensation')
    fn=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name==name)
    mod=ast.Module(body=[fn],type_ignores=[])
    ast.fix_missing_locations(mod)
    scope=dict(globals_)
    exec(compile(mod,str(SOURCE),'exec'),scope)
    return scope[name]


class TemperaturePoliciesTests(unittest.TestCase):
    def test_default_research_not_quick_mode(self):
        continuous=policy_for('continuous');strict=policy_for('strict')
        self.assertEqual(continuous['gate'],'plc_staged_continuous_v3')
        self.assertGreater(continuous['pv_final_tolerance_c'],strict['pv_final_tolerance_c'])
        self.assertLess(continuous['dwell_seconds'],strict['dwell_seconds'])
        self.assertEqual(strict['dwell_seconds'],1800)
        self.assertEqual(strict['pv_final_tolerance_c'],0.10)
        self.assertEqual(continuous['pv_final_tolerance_c'],1.00)
        self.assertGreater(continuous['runtime']['pv_pause_c'],1.0)

    def test_pv_drift_does_not_auto_pause_research_after_30s(self):
        guard=ThermalRuntimeGuard(5,**policy_for('continuous')['runtime'])
        for i in range(100):
            status,reason=guard.observe(float(i),5.8,float(i),5.05,i)
            self.assertEqual(status,'ok',reason)
        # A persistent larger departure still triggers a hold.
        for i in range(100,260):
            status,reason=guard.observe(float(i),6.5,float(i),5.05,i)
            if status!='ok': break
        self.assertEqual(status,'hold')
        self.assertIn('1.25',reason)

    def test_legacy_guard_retains_original_thresholds(self):
        strict=ThermalRuntimeGuard(5,**policy_for('strict')['runtime'])
        for i in range(31):
            state,_=strict.observe(float(i),5.6,float(i),5.0,i)
        self.assertEqual(state,'hold')

    def test_continuous_does_not_erase_accepted_group(self):
        fn=compile_method('_audit_current_temperature_groups',{'policy_for':policy_for})
        steps=[{'sensor':'acc','split':'fit','step_id':f'ACC_FIT_{j:02d}'} for j in (1,2)]
        rows=[dict(temperature_target_c=5.0,temperature_mean_c=4.8,step_id='ACC_FIT_01',sensor='acc',split='fit'),
              dict(temperature_target_c=5.0,temperature_mean_c=6.19,step_id='ACC_FIT_02',sensor='acc',split='fit')]
        class F:
            def __init__(self):
                self.task={'temp_i':0,'temps':[5.0],'steps':steps,'rows':rows.copy(),
                           'temperature_quality_mode':'continuous','temperature_group_warnings':[]}
                self.saved=[];self.logs=[]
            def _log(self,m):self.logs.append(m)
            def _save_partial(self,*args):self.saved.append(args)
        f=F();out=fn(f)
        self.assertFalse(out)
        self.assertEqual(len(f.task['rows']),2)
        self.assertEqual(len(f.task['temperature_group_audit']),1)
        self.assertAlmostEqual(f.task['temperature_group_audit'][0]['chip_span_c'],1.39)
        self.assertEqual(f.task['temperature_group_audit'][0]['decision'],'KEEP_ACCEPTED_CONDITIONS_JOINT_FIT_PER_CONDITION_T')
        self.assertTrue(all(x.get('group_temperature_audit')=='INFO_ONLY_NOT_AN_INVALIDATION' for x in f.task['rows']))
        fn(f)
        self.assertEqual(len(f.task['temperature_group_audit']),1)

    def test_report_exposes_group_temperature_risk(self):
        with TemporaryDirectory() as folder:
            out=export_thermal_xlsx(folder,[],{
                'temperature_quality_warnings':[
                    {'temperature_target_c':5.0,'sensor':'acc','split':'fit','chip_span_c':1.39,
                     'chip_min_c':4.8,'chip_max_c':6.19,'count':2,'severity':'WARNING',
                     'decision':'KEEP_ACCEPTED_CONDITIONS_JOINT_FIT_PER_CONDITION_T','note':'测试警告'}]})
            from openpyxl import load_workbook
            wb=load_workbook(out,read_only=True)
            self.assertIn('温度质量审计',wb.sheetnames)
            audit=list(wb['温度质量审计'].values)
            self.assertAlmostEqual(float(audit[1][3]),1.39)


class ShutdownTests(unittest.TestCase):
    def test_no_stop_request_before_wk_park_confirmed(self):
        stop=Mock(return_value=True)
        comm=types.SimpleNamespace(thread_lock=threading.RLock(),is_connected=True)
        fn=compile_method('_begin_chamber_shutdown',
                          {'tcComm':comm,'tc_fixed_value_stop':stop,
                           'time':types.SimpleNamespace(monotonic=lambda:100.2)})
        class F:
            def __init__(self,parked):
                self.task={'manual':False,'final_stop_confirmed':parked,
                           'finish_success_reason':'done'}
            def _save_partial(self,*args):pass
            def _log(self,*args):pass
            def _finish(self,*args):pass
        with self.assertRaises(RuntimeError):fn(F(False),100)
        stop.assert_not_called()
        f=F(True);fn(f,100)
        stop.assert_called_once_with()
        self.assertEqual(f.task['phase'],'verify_chamber_stop')
        self.assertTrue(f.task['plc_stop_requested'])
        self.assertFalse(f.task['plc_stop_confirmed'])

    def test_fresh_plc_readback_required_for_final_confirmation(self):
        fn=compile_method('_tick',{'time':types.SimpleNamespace(monotonic=lambda:108.0)})
        class F:
            def __init__(self,started_updated=101,run_updated=102):
                self.task={'phase':'verify_chamber_stop', 'phase_start':100,
                           'plc_stop_command_time':100,'finish_success_reason':'done',
                           'plc_stop_requested':True}
                self.received=[]
                self.label=types.SimpleNamespace(setText=lambda text:None)
                self.snap={'started_updated':started_updated,'run_updated':run_updated,
                           'fixed_started':False,'running':False}
            def _require_plc(self,*args):return self.snap
            def _finish(self,*args):self.received.append(args)
            def _log(self,*args):pass
        fresh=F();fn(fresh)
        self.assertTrue(fresh.task['plc_stop_confirmed'])
        self.assertEqual(len(fresh.received),1)
        stale=F(started_updated=99);fn(stale)
        self.assertFalse(stale.task.get('plc_stop_confirmed',False))
        self.assertEqual(len(stale.received),0)

    def test_stale_plc_feedback_cannot_claim_auto_stop(self):
        fn=compile_method('_tick',{'time':types.SimpleNamespace(monotonic=lambda:202.0)})
        class F:
            def __init__(self):
                self.task={'phase':'verify_chamber_stop','phase_start':100,
                           'plc_stop_command_time':100,'finish_success_reason':'done'}
                self.end=[]
                self.label=types.SimpleNamespace(setText=lambda text:None)
            def _require_plc(self,*args):raise ValueError('PLC unreachable')
            def _finish(self,*args):self.end.append(args)
            def _log(self,*args):pass
        f=F();fn(f)
        self.assertFalse(f.task.get('plc_stop_confirmed',False))
        self.assertEqual(len(f.end),1)
        self.assertIn('必须现场检查',f.end[0][1])


if __name__=='__main__':unittest.main()
