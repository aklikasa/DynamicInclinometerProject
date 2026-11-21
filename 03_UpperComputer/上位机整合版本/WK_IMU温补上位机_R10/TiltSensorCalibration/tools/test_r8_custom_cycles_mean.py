# -*- coding: utf-8 -*-
"""R8 offline regression for selectable ranges, repeated independent passes and
non-destructive mean-temperature recording. No hardware or UI required.
"""
import ast
import json
import tempfile
import unittest
from pathlib import Path
import numpy as np
from production_cycle_protocol import generate_temperature_plan,verify_plan,cycle_passes,validate_temperature_limits,PROTOCOL
from production_r5_cycle import decide_repeated_transition,write_cycle_manifest
from production_cycle_analysis import load_run,locate_runs,hysteresis_table
from production_calibration import robust_segment,load_profile

ROOT=Path(__file__).resolve().parents[1]


class R8CustomCycles(unittest.TestCase):
    def test_negative20_to_60_with_2_cycles(self):
        w=generate_temperature_plan('warming',-20,60,2)
        c=generate_temperature_plan('cooling',-20,60,2)
        self.assertEqual(len(w['temperature_setpoints_c']),17)
        self.assertEqual(w['temperature_setpoints_c'][0],-20)
        self.assertEqual(w['temperature_setpoints_c'][-1],60)
        self.assertEqual(c['temperature_setpoints_c'],list(reversed(w['temperature_setpoints_c'])))
        self.assertEqual(len(w['fit_temperatures_c']),9)
        self.assertEqual(len(w['validation_temperatures_c']),8)
        self.assertTrue(verify_plan(w));self.assertTrue(verify_plan(c))
        self.assertEqual([x['key'] for x in cycle_passes(2)],
                         ['cycle_01_warming','cycle_01_cooling','cycle_02_warming','cycle_02_cooling'])

    def test_non_grid_endpoint_included_and_limits(self):
        p=generate_temperature_plan('warming',-23,63,3)
        self.assertEqual(p['temperature_setpoints_c'][0],-23)
        self.assertEqual(p['temperature_setpoints_c'][-1],63)
        self.assertTrue(verify_plan(p))
        for args in [(-41,60,1),(-20,86,1),(60,-20,1),(-20,60,0),(-20,60,100)]:
            with self.assertRaises(ValueError):validate_temperature_limits(*args)

    def test_no_automatic_step_after_uncertain_stop(self):
        passes=cycle_passes(3)
        good=decide_repeated_transition(2,passes,True,True,True,True,True)
        self.assertEqual(good['action'],'next')
        for idx in range(len(passes)):
            bad=decide_repeated_transition(idx,passes,True,True,True,True,False)
            self.assertEqual(bad['action'],'halt')
        self.assertEqual(decide_repeated_transition(5,passes,True,True,True,True,True)['action'],'analyze')

    def test_each_pass_has_own_folder_and_manifest_can_aggregate(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);passes=cycle_passes(2);runs={}
            for entry in passes:
                d=root/('THERM_'+entry['key']);d.mkdir()
                plan=generate_temperature_plan(entry['direction'],-20,60,2)
                cfg={'production_protocol':PROTOCOL,
                     'production_scan_direction':entry['direction'],
                     'production_min_c':-20.,'production_max_c':60.,
                     'production_cycle_count':2,'production_pass_index':entry['index'],
                     'temperature_setpoints_c':plan['temperature_setpoints_c'],
                     'temperature_split':{str(t):v for t,v in plan['temperature_split'].items()},
                     'production_batch_id':'UNIT','device_sn':'PCB001',
                     'temperature_quality_mode':'production_adaptive',
                     'imu_sensor_config':{'gyro_fs_dps':250}}
                rows=[{'step_id':'ACC_FIT_01','temperature_target_c':-20.,'sensor':'acc',
                       'mode':'static','split':'fit','temperature_split':'fit',
                       'temperature_mean_c':-20.5+entry['cycle']*.2,
                       'accepted_frames':120,'acc_raw_mean_g':[0,0,1]}]
                (d/'experiment_config.json').write_text(json.dumps(cfg),encoding='utf-8')
                (d/'temperature_measurements.json').write_text(json.dumps({
                    'status':'COMPLETED','rows':rows,'chamber_shutdown':{'confirmed':True,'manual_mode':False},
                    'imu_queue_drops':0}),encoding='utf-8')
                runs[entry['key']]=str(d)
            manifest={'batch_id':'UNIT','device_sn':'PCB001','status':'ALL_CYCLES_COMPLETED',
                      'passes':passes,'repeat_count':2,'min_c':-20.,'max_c':60.,'runs_by_pass':runs}
            write_cycle_manifest(root,manifest)
            matched=locate_runs(root,'UNIT')
            self.assertEqual(len(matched['_all_passes']),4)
            self.assertEqual(len(matched['warming']['rows']),2)
            self.assertEqual(len(matched['cooling']['rows']),2)
            self.assertEqual([r['_cycle_index'] for r in matched['warming']['rows']],[1,2])
            bad=root/'R5_CYCLE_UNIT.json'
            manifest['status']='PASS_COMPLETED'
            write_cycle_manifest(root,manifest)
            with self.assertRaisesRegex(ValueError,'并未完整结束'):
                locate_runs(root,'UNIT')

    def test_per_condition_mean_even_when_sample_span_exceeds_two(self):
        # Stable motion/noise and true physical T spread are independent QA axes.
        profile=load_profile(str(ROOT))
        q=profile['quality'];q['temperature_min_c']=-45.;q['temperature_max_c']=90.
        q['temperature_span_max_c']=.5
        q['temperature_span_only_log']=True
        frames=[]
        for i in range(100):
            frames.append({'acc':[.001,-.002,1.001], 'gyro':[.0,.0,.0],
                           'temp_c':-40+3*i/99., 'inner_rate_dps':0.,'outer_rate_dps':0.,
                           'inner_deg':0.,'outer_deg':0.})
        kwargs={'mode':'static','profile':profile,'static_sensor':'acc'}
        result=robust_segment(frames,**kwargs)
        self.assertAlmostEqual(result['temperature_mean_c'],-38.5,places=8)
        self.assertAlmostEqual(result['temperature_span_c'],3.0,places=8)
        q['temperature_span_only_log']=False
        with self.assertRaisesRegex(ValueError,'温度漂移'):
            robust_segment(frames,**kwargs)

    def test_controlled_two_degree_group_stop_keeps_all_measurements(self):
        path=ROOT/'form/form_thermal_compensation.py'
        tree=ast.parse(path.read_text(encoding='utf-8'))
        cls=next(x for x in tree.body if isinstance(x,ast.ClassDef) and x.name=='FormThermalCompensation')
        fn=next(x for x in cls.body if isinstance(x,ast.FunctionDef) and x.name=='_audit_current_temperature_groups')
        mod=ast.Module(body=[fn],type_ignores=[]);ast.fix_missing_locations(mod)
        env={};exec(compile(mod,str(path),'exec'),env)
        from unittest.mock import Mock
        class Fake:
            def __init__(self):
                self.task={'temp_i':0,'temps':[-40.], 'rows':[
                    {'sensor':'acc','split':'fit','temperature_target_c':-40.,
                     'temperature_mean_c':-40.+2.01*i/11., 'step_id':f'ACC_FIT_{i+1:02d}'}
                    for i in range(12)],'temperature_quality_mode':'production_adaptive'}
                self._log=Mock();self._save_partial=Mock();self._halt_incomplete_temperature=Mock()
        a=Fake()
        self.assertTrue(env['_audit_current_temperature_groups'](a))
        self.assertEqual(len(a.task['rows']),12)
        self.assertEqual(a.task['temperature_group_audit'][0]['decision'],'SAFE_STOP_PRESERVE_RAW')
        self.assertEqual(a._halt_incomplete_temperature.call_count,1)
        b=Fake()
        for i,x in enumerate(b.task['rows']):x['temperature_mean_c']=-40.+1.99*i/11.
        self.assertFalse(env['_audit_current_temperature_groups'](b))
        b._halt_incomplete_temperature.assert_not_called()


if __name__=='__main__':unittest.main()
