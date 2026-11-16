# -*- coding: utf-8 -*-
"""纯软件：温补续做、安全数据合并及旧参数兼容；不加载转台DLL。"""
import ast
import copy
import json
import tempfile
import unittest
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from thermal_run_resume import (RESUME_SCHEMA, atomic_write_json, validate_resume,validate_appendable_raw_files)
from thermal_gyro_multirate import conservative_sweep_degrees

class ResumeTests(unittest.TestCase):
    def setUp(self):
        self.temps=[-20.,0.,25.,45.,70.]
        self.steps=[{'step_id':'ACC_FIT_01','sensor':'acc','split':'fit','mode':'static'},
                    {'step_id':'GYRO_FIT_X_01','sensor':'gyro','split':'fit','mode':'rate',
                     'rotation_axis':'outer','target_rate_dps':60.0},
                    {'step_id':'GYRO_FIT_X_02','sensor':'gyro','split':'fit','mode':'rate',
                     'rotation_axis':'outer','target_rate_dps':-60.0}]
        self.params={'device_sn':'pcb-a','temperature_setpoints_c':self.temps,
                     'gyro_fit_rates_dps':[1.,5.,15.,30.,60.],
                     'sample_seconds':5,'quality_profile':{'minimum_frames':50}}
        self.config={'resume_schema_version':RESUME_SCHEMA,'resume_immutable_config':copy.deepcopy(self.params)}
    def row(self,i):
        ti,si=divmod(i,len(self.steps))
        a=self.steps[si].copy()
        a.update({'temperature_target_c':self.temps[ti], 'accepted_frames':123,
                  'reference':[0,0,1], 'temperature_mean_c':self.temps[ti]})
        return a
    def checkpoint(self,n=0,status='RUNNING'):
        return {'status':status,'device_sn':'pcb-a','rows':[self.row(i) for i in range(n)],
                'events':[],'imu_frame_count':50*n}
    def resume(self,n=0,status='RUNNING'):
        return validate_resume(self.config,self.checkpoint(n,status),self.params,self.temps,self.steps)
    def test_empty_resume_first_step(self):
        r=self.resume();self.assertEqual((r['temp_index'],r['step_index']),(0,0))
    def test_resume_at_failed_60(self):
        r=self.resume(1)
        self.assertEqual((r['temp_index'],r['step_index']),(0,1))
        self.assertEqual(len(r['rows']),1)
    def test_resume_after_one_temperature(self):
        r=self.resume(3)
        self.assertEqual((r['temp_index'],r['step_index']),(1,0))
    def test_resume_60_negative_pending(self):
        r=self.resume(2)
        self.assertEqual((r['temp_index'],r['step_index']),(0,2))
    def test_resume_after_all_steps(self):
        r=self.resume(15)
        self.assertEqual((r['temp_index'],r['step_index']),(5,0))
    def test_mismatch_rejected(self):
        for prop,val in [('device_sn','pcb-b'),('sample_seconds',6)]:
            p=self.params.copy();p[prop]=val
            with self.subTest(prop=prop),self.assertRaisesRegex(ValueError,'配置'):
                validate_resume(self.config,self.checkpoint(2),p,self.temps,self.steps)
    def test_resume_obsolete_angle_limit_is_ignored(self):
        legacy=copy.deepcopy(self.config)
        legacy['resume_immutable_config']['gyro_sweep_limit_deg']=360
        r=validate_resume(legacy,self.checkpoint(1),self.params,self.temps,self.steps)
        self.assertEqual((r['temp_index'],r['step_index']),(0,1))

    def test_old_schema_rejected(self):
        with self.assertRaisesRegex(ValueError,'旧版'):
            validate_resume({},self.checkpoint(),self.params,self.temps,self.steps)
    def test_completed_rejected(self):
        with self.assertRaisesRegex(ValueError,'COMPLETED'):
            self.resume(15,'COMPLETED')
    def test_reordered_or_corrupted_rejected(self):
        c=self.checkpoint(2);c['rows'][1]['step_id']='GYRO_FIT_Z_07'
        with self.assertRaisesRegex(ValueError,'工况顺序'):
            validate_resume(self.config,c,self.params,self.temps,self.steps)
        c=self.checkpoint(2);c['rows'][1]['target_rate_dps']=-60.0
        with self.assertRaisesRegex(ValueError,'角速度'):
            validate_resume(self.config,c,self.params,self.temps,self.steps)
    def test_atomically_written_checkpoint_and_raw_files(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            atomic_write_json(root/'temperature_measurements.json',self.checkpoint(1))
            self.assertEqual(json.loads((root/'temperature_measurements.json').read_text())['status'],'RUNNING')
            (root/'imu_frame_means.csv').write_bytes(b'col1,col2\n1,2\n')
            (root/'imu_full_frames.jsonl').write_bytes(b'{"a":1}\n')
            validate_appendable_raw_files(root,1)
            (root/'imu_full_frames.jsonl').write_bytes(b'{"a":')
            with self.assertRaisesRegex(ValueError,'尾部不完整'):
                validate_appendable_raw_files(root,1)
    def test_60_preflight_before_heating(self):
        self.assertAlmostEqual(conservative_sweep_degrees(60,30,5),510.0)
        self.assertGreater(conservative_sweep_degrees(60,30,5),360)
        self.assertLess(conservative_sweep_degrees(60,30,5),600)
    def test_ui_source_commits_each_step_and_preserves_other_parts(self):
        s=(ROOT/'form'/'form_thermal_compensation.py').read_text(encoding='utf-8')
        ast.parse(s)
        self.assertIn('self._save_partial(\'RUNNING\',f\'逐工况存档',s)
        self.assertIn("t['pending_dynamic_row']=row",s)
        self.assertIn('validate_resume(config,checkpoint,immutable,temperatures,steps)',s)
        self.assertIn("t['step_i']=t.pop('resume_step_index',0)",s)

if __name__=='__main__':unittest.main(verbosity=2)
