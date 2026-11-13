# -*- coding: utf-8 -*-
"""No hardware: tests independent feedback, drift hold, sparse resume and partial reports."""
import ast
import copy
import json
import tempfile
import unittest
from pathlib import Path
import sys

import numpy as np
from openpyxl import load_workbook
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from thermal_reference_diagnostics import inspect_feedback
from thermal_runtime_guard import ThermalRuntimeGuard
from thermal_gyro_multirate import configure_thermal_gyro_profile,PILOT_FIT_RATES_DPS,PILOT_VERIFY_RATES_DPS
from production_calibration import load_profile
from thermal_incomplete_report import export_incomplete_xlsx
from thermal_run_resume import validate_resume,RESUME_SCHEMA


def samples(speed, dt=0.35, n=20, error_ms=0, disturbance=0):
    out=[]
    for i in range(n):
        t=500.+i*dt
        pos=(speed*t+disturbance*((-1)**i))%360
        shifted=t+error_ms*.001*((-1)**i)
        a=int((shifted-0.0005)*1e9)
        b=int((shifted+0.0005)*1e9)
        out.append({'inner_position_deg':pos,'inner_position_read_start_ns':a,
                    'inner_position_read_end_ns':b})
    return out

class FeedbackTests(unittest.TestCase):
    def test_true_constant_rate_has_independent_evidence(self):
        s=samples(30,n=19)
        result=inspect_feedback(s,'inner',30)
        self.assertTrue(result['certified'],result)
        self.assertAlmostEqual(result['mean_dps'],30,places=5)
        self.assertEqual(result['sample_count'],19)

    def test_time_jitter_fails_closed_not_mistaken_as_true_mechanics(self):
        jittered=samples(60,dt=.43,n=13,error_ms=2.5)
        result=inspect_feedback(jittered,'inner',60)
        self.assertFalse(result['certified'])
        self.assertEqual(result['status'],'REFERENCE_JITTER')

    def test_real_motion_variability_is_not_smoothed_into_a_pass(self):
        result=inspect_feedback(samples(30,n=19,disturbance=.25),'inner',30)
        self.assertFalse(result['certified'])

    def test_stale_or_ambiguous_samples_fail_closed(self):
        tiny=samples(60,n=5)
        self.assertEqual(inspect_feedback(tiny,'inner',60)['status'],'INSUFFICIENT_REFERENCE')
        huge=samples(60,dt=4,n=10)
        self.assertFalse(inspect_feedback(huge,'inner',60)['certified'])

    def test_pilot_rate_profile_does_not_touch_ambient(self):
        original=load_profile(str(ROOT))
        copy_profile=copy.deepcopy(original)
        pilot=configure_thermal_gyro_profile(copy.deepcopy(original),high_speed=False)
        self.assertEqual(original,copy_profile)
        self.assertEqual(tuple(pilot['rates']['fit_dps']),PILOT_FIT_RATES_DPS)
        self.assertEqual(tuple(pilot['rates']['verify_dps']),PILOT_VERIFY_RATES_DPS)
        self.assertEqual(max(pilot['rates']['fit_dps']),30)
        self.assertNotIn(45,pilot['rates']['verify_dps'])
        self.assertEqual(pilot['quality']['rate_reference_std_max_dps'],0.18)

class ThermalGuardTests(unittest.TestCase):
    def test_sustained_pv_drift_triggers_hold_not_hard_abort(self):
        guard=ThermalRuntimeGuard(10)
        for sec in range(71):
            pv=10 if sec<40 else 10.55
            state,msg=guard.observe(float(sec),pv,float(sec),9.0,sec)
        self.assertEqual(state,'hold')
        self.assertIn('PV',msg)

    def test_severe_excursion_requires_full_soak(self):
        guard=ThermalRuntimeGuard(10)
        for sec in range(90):
            state,_=guard.observe(float(sec),11.2,float(sec),9.0,sec)
        self.assertEqual(state,'resoak')

    def test_pv_recovery_requires_120_seconds_and_chip60(self):
        guard=ThermalRuntimeGuard(10)
        guard.begin_recovery(0.0)
        for sec in range(121):
            guard.observe(float(sec),10.0,float(sec),9.0,sec)
        self.assertTrue(guard.recovery_ready(120.,10.,9.))
        self.assertFalse(guard.recovery_ready(160.,10.,9.))

    def test_long_slope_detects_thermal_drift(self):
        guard=ThermalRuntimeGuard(10)
        state=None
        for sec in range(370):
            state,_=guard.observe(float(sec),10,float(sec),9+0.12*sec/60,sec)
        self.assertEqual(state,'hold')

class PartialResumeTests(unittest.TestCase):
    def test_sparse_rows_and_replayed_step_resume_without_duplication(self):
        temps=[10.,12.5]
        per=[[{'step_id':'F1','mode':'static','sensor':'acc','split':'fit'},
              {'step_id':'F2','mode':'static','sensor':'acc','split':'validate'}],
             [{'step_id':'V1','mode':'static','sensor':'acc','split':'validate'}]]
        immutable={'device_sn':'PCB01','temperature_fit_split':{'10.0':'fit','12.5':'validate'}}
        config={'resume_schema_version':RESUME_SCHEMA,'resume_immutable_config':immutable}
        rows=[{'step_id':'F2','temperature_target_c':10,'sensor':'acc','mode':'static',
               'split':'validate','temperature_split':'fit','accepted_frames':90}]
        progress={'temp_index':0,'step_index':1,'replay_mode':True,'replay_queue':[],
                  'deferred_by_temp':{'0':[0]},'unresolved':[]}
        checkpoint={'status':'RUNNING','device_sn':'PCB01','rows':rows,
                    'task_progress':progress}
        loaded=validate_resume(config,checkpoint,immutable,temps,per)
        self.assertEqual(loaded['step_index'],1)
        checkpoint['status']='PARTIAL_COMPLETED'
        checkpoint['task_progress']['unresolved']=[{'temp_index':0,'step_index':0}]
        recovered=validate_resume(config,checkpoint,immutable,temps,per)
        self.assertEqual((recovered['temp_index'],recovered['step_index']),(0,0))
        bad=copy.deepcopy(checkpoint)
        bad['rows']=rows*2
        with self.assertRaisesRegex(ValueError,'重复'):
            validate_resume(config,bad,immutable,temps,per)

    def test_partial_report_is_explicitly_not_released(self):
        with tempfile.TemporaryDirectory() as d:
            path=export_incomplete_xlsx(d,[],[{'temperature_target_c':10,'step_id':'GYRO_FIT_Z_09',
                            'sensor':'gyro','reason':'60 dps speed uncertified'}],[10.,15.],'研发不完整')
            book=load_workbook(path,read_only=True)
            self.assertIn('待补测清单',book.sheetnames)
            book.close()
            manifest=json.loads((Path(d)/'thermal_incomplete_manifest.json').read_text('utf8'))
            self.assertFalse(manifest['model_release_permitted'])

class GroupQualityTests(unittest.TestCase):
    def test_complete_group_spread_is_recorded_not_invalidated(self):
        # R7: group spans (even >2C) are informational. Per-step QA unchanged.
        source=(ROOT/'form'/'form_thermal_compensation.py').read_text('utf8')
        tree=ast.parse(source)
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='FormThermalCompensation')
        method=copy.deepcopy(next(n for n in cls.body if isinstance(n,ast.FunctionDef)
                                  and n.name=='_audit_current_temperature_groups'))
        runner=ast.ClassDef(name='Runner',bases=[],keywords=[],decorator_list=[],body=[method])
        ns={}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[runner],type_ignores=[])),str(ROOT),'exec'),ns)
        class Fake(ns['Runner']):
            def __init__(self):
                self.log=[]
                self.task={'temps':[10.],'temp_i':0,'steps':[
                    {'sensor':'acc','split':'fit','step_id':'F1'},
                    {'sensor':'acc','split':'fit','step_id':'F2'}],
                    'rows':[{'temperature_target_c':10.,'sensor':'acc','split':'fit','step_id':'F1',
                              'temperature_mean_c':8.0},
                            {'temperature_target_c':10.,'sensor':'acc','split':'fit','step_id':'F2',
                              'temperature_mean_c':10.5}],
                    'group_rechecks':{},'deferred_by_temp':{},'unresolved':[]}
            def _log(self,x):self.log.append(x)
            def _save_partial(self,*args):pass
        f=Fake();self.assertFalse(f._audit_current_temperature_groups())
        self.assertEqual(len(f.task['rows']),2)
        self.assertEqual(len(f.task['temperature_group_audit']),1)
        self.assertAlmostEqual(f.task['temperature_group_audit'][0]['chip_span_c'],2.5)
        self.assertFalse(f.task['unresolved'])
        self.assertFalse(f.task['deferred_by_temp'])
        self.assertFalse(f._audit_current_temperature_groups())
        self.assertEqual(len(f.task['temperature_group_audit']),1)

if __name__=='__main__':unittest.main(verbosity=2)
