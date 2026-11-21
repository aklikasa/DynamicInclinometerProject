# -*- coding: utf-8 -*-
import json,math,sys,tempfile,unittest
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from production_cycle_protocol import generate_temperature_plan,verify_plan,check_user_hardware_clearance
from production_cycle_analysis import (candidate_ids,fit_candidate,evaluate,model_parts,
    normalize_signed_raw,axis_channel_diagnostic,locate_runs,analyze)

class TestR4Production(unittest.TestCase):
    def test_plan_exact_bounds_holdouts_and_direction(self):
        u=generate_temperature_plan('warming');d=generate_temperature_plan('cooling')
        self.assertTrue(verify_plan(u));self.assertTrue(verify_plan(d))
        self.assertEqual(u['temperature_setpoints_c'][0],-40.)
        self.assertEqual(u['temperature_setpoints_c'][-1],85.)
        self.assertEqual(d['temperature_setpoints_c'][0],85.)
        self.assertEqual(d['temperature_setpoints_c'][-1],-40.)
        self.assertEqual(len(u['temperature_setpoints_c']),26)
        self.assertEqual(len(u['fit_temperatures_c']),14)
        self.assertEqual(len(u['validation_temperatures_c']),12)
        self.assertEqual(u['temperature_split'],d['temperature_split'])
        self.assertFalse(set(u['fit_temperatures_c'])&set(u['validation_temperatures_c']))
    def test_safety_interlocks(self):
        for args in [(0,1,0,1),(1,0,0,1),(1,1,1,1),(1,1,0,0)]:
            with self.assertRaises(ValueError):check_user_hardware_clearance(*args)
        self.assertTrue(check_user_hardware_clearance(1,1,0,1))
    def test_28_plus_two(self):
        ids=candidate_ids()
        self.assertEqual(len(ids),34)  # R5 adds 4 continuous spline candidates; R4 candidates retained
        self.assertEqual(len(set(ids)),34)
        self.assertIn('T2-D3',ids)
        self.assertIn('T0-SEG2',ids)
        self.assertIn('T0-D3_HY',ids)
    def test_27_candidates_are_not_silently_renamed(self):
        self.assertEqual(model_parts('A0'),('T0','A0'))
        self.assertEqual(model_parts('T1-D3'),('T1','D3'))
        self.assertEqual(model_parts('T0-SEG2'),('T0','SEG2'))
    def test_model_fit_and_axis_sign(self):
        rng=np.random.default_rng(5);rows=[]
        for t in range(-40,86,5):
            for k in range(14):
                ref=rng.normal(size=3);ref/=np.linalg.norm(ref)
                obs=np.array([-ref[0],ref[1],ref[2]])+np.array([.01,-.03,.02])
                rows.append({'reference':ref.tolist(),'acc_raw_mean_g':obs.tolist(),
                             'temperature_mean_c':float(t),'temperature_target_c':float(t),
                             '_direction':'warming','step_id':str(k),'temperature_span_c':.05})
        m=fit_candidate(rows,'acc','T0-D3',{'T0':{'id':'T0'}})
        score,_=evaluate(m,rows,'acc')
        self.assertLess(score['vector_rmse_mg'],.000001)
        self.assertGreater(score['det_negative_count'],0)
    def test_raw_axis_sign_normalization_preserves_corrected_six_axis_output(self):
        F=np.array([[-1.003,.004,.002],[.003,1.002,.001],[.004,.002,.997]])
        raw=np.array([.4,-.5,.8]);bias=np.array([.01,-.005,.04])
        for axis in (0,1,2):
            proposed=normalize_signed_raw(raw,F,bias,axis)
            self.assertGreater(np.linalg.det(np.array(proposed['forward'])),0)
            expected=np.linalg.solve(F,raw-bias)
            np.testing.assert_allclose(np.array(proposed['corrected']),expected,atol=1e-12)
    def test_ui_embeds_real_safety_and_report_entry(self):
        s=(ROOT/'form/form_thermal_compensation.py').read_text('utf-8')
        self.assertIn('check_user_hardware_clearance',s)
        self.assertIn('production_scan_direction',s)
        self.assertIn('production_analyze',s)
        self.assertIn('production_cycle_analysis.py',s)
        self.assertIn('QProcessEnvironment',s)
        self.assertIn('PLC直接设定目标温度',s)
        self.assertNotIn('initial_stages(',s)
        self.assertIn("self._issue_plc_setpoint(target)",s)
        self.assertIn('self._new_guard()',s)
    def test_incomplete_or_wrong_batch_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with self.assertRaisesRegex(ValueError,'必须有且只有'):
                locate_runs(root)
            folder=root/'THERM_demo';folder.mkdir()
            p=generate_temperature_plan('warming')
            (folder/'experiment_config.json').write_text(json.dumps({
                'production_scan_direction':'warming','production_protocol':p['protocol'],
                'temperature_setpoints_c':p['temperature_setpoints_c'],
                'temperature_split':{str(k):v for k,v in p['temperature_split'].items()}}))
            (folder/'temperature_measurements.json').write_text(json.dumps({'status':'PARTIAL_COMPLETED','rows':[]}))
            with self.assertRaisesRegex(ValueError,'COMPLETED'):
                from production_cycle_analysis import load_run
                load_run(folder)

if __name__=='__main__':unittest.main()
