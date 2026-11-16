# -*- coding: utf-8 -*-
"""2026-11-07 regressions: operator limits, wrap-safe reference, 28-model reports."""
import ast
import copy
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from production_calibration import _dynamic_unwrapped_mean_degrees, robust_segment, load_profile
from thermal_reference_diagnostics import inspect_feedback
from thermal_model_catalog import full_catalog
from thermal_model_selection import _errors_inrange_preview
from thermal_analysis_publisher import publish_sensor_reports
from thermal_model_completion import fully_accepted_sensors
from thermal_gyro_multirate import configure_thermal_gyro_profile
from thermal_variable_temperature import steps_for_temperature
from production_calibration import acc_fit_steps, acc_verify_steps, gyro_fit_steps, gyro_verify_steps


def encoder(rate=30, n=20, dt=.43, jitter=.035):
    items=[]
    for i in range(n):
        t=200+i*dt
        pos=(rate*dt*i+jitter*(-1)**i)%360
        items.append({'outer_position_deg':pos,
                      'outer_position_read_start_ns':int((t-0.0005)*1e9),
                      'outer_position_read_end_ns':int((t+0.0005)*1e9)})
    return items

class ConfigurableQATests(unittest.TestCase):
    def test_30dps_can_increase_only_polling_dispersion_not_mean_and_direction(self):
        s=encoder(jitter=.05)
        original=inspect_feedback(s,'outer',30,max_std=.18)
        increased=inspect_feedback(s,'outer',30,max_std=.24)
        self.assertFalse(original['certified'], original)
        self.assertTrue(increased['certified'], increased)
        self.assertTrue(increased['raw_diff_std_dps']>.18)
        self.assertTrue(increased['raw_diff_std_dps']<.24)
        self.assertFalse(inspect_feedback(s,'outer',-30,max_std=.24)['certified'])
        self.assertFalse(inspect_feedback(encoder(rate=31.5,jitter=.03),'outer',30,max_std=.24)['certified'])

    def test_diagnostic_trend_and_residual_still_apply_after_high_std_limit(self):
        s=encoder(jitter=.05)
        baseline=inspect_feedback(s,'outer',30,max_std=.24)
        self.assertTrue(baseline['certified'])
        self.assertFalse(inspect_feedback(s,'outer',30,max_std=.24,
                          max_slope_difference=.0001)['certified'])
        self.assertFalse(inspect_feedback(s,'outer',30,max_std=.24,
                          max_position_residual_rms=.00001)['certified'])

    def test_dynamic_degree_wrap_math(self):
        self.assertAlmostEqual(_dynamic_unwrapped_mean_degrees([359.9,0,0.1]),0,places=6)
        self.assertAlmostEqual(_dynamic_unwrapped_mean_degrees([350,355,0,5,10]),0,places=6)
        self.assertAlmostEqual(_dynamic_unwrapped_mean_degrees([350,10,30,50]),20,places=6)
        with self.assertRaises(ValueError):_dynamic_unwrapped_mean_degrees([10,200])

    def test_rate_robust_segment_consumes_high_speed_limit(self):
        import random
        p=load_profile(str(ROOT));p['quality']['temperature_min_c']=-45;p['quality']['temperature_max_c']=90
        p['quality']['rate_reference_high_speed_start_dps']=25
        p['quality']['rate_reference_high_speed_std_max_dps']=.24
        rng=np.random.default_rng(19)
        frames=[]
        for n in range(150):
            frames.append({'acc':[0,0,1], 'gyro':(np.array([30,0,0])+rng.normal(0,.018,3)).tolist(),
                 'inner_rate_dps':0,'outer_rate_dps':30,'temp_c':25.0,
                 'inner_deg':359.9 if n%2 else .1,'outer_deg':(170+n*.02)%360})
        diag={'certified':True,'raw_diff_std_dps':.210,'mean_dps':30.02,
              'status':'POLLING_PASS_RESEARCH_ONLY'}
        result=robust_segment(frames,'rate',p,target_rate=30,axis='outer',reference_diagnostic=diag)
        self.assertGreater(result['accepted_frames'],120)
        with self.assertRaises(ValueError):
            robust_segment(frames,'rate',p,target_rate=20,axis='outer',reference_diagnostic=diag)

    def test_ui_settings_source_locked_and_immutable(self):
        code=(ROOT/'form/form_thermal_compensation.py').read_text(encoding='utf8')
        self.assertIn('thermal_wk_std_high',code)
        self.assertIn('thermal_wk_std_low',code)
        self.assertIn('self._wk_rate_quality_arguments(step[\'target_rate_dps\'])',code)
        self.assertIn("profile['quality']['rate_reference_high_speed_std_max_dps']",code)
        self.assertIn('self.wk_std_high,self.wk_mean_error,',code)
        self.assertIn("'quality_profile':profile",code)

class ReportTests(unittest.TestCase):
    def test_28_catalog_has_correct_math_and_coeff_counts(self):
        entries=full_catalog()
        self.assertEqual(len(entries),28)
        self.assertEqual(len(set(x['id'] for x in entries)),28)
        ids={x['id']:x for x in entries}
        self.assertEqual(ids['A0']['parameter_count'],12)
        self.assertEqual(ids['T0-B3']['parameter_count'],21)
        self.assertEqual(ids['T1-C2']['parameter_count'],24)
        self.assertEqual(ids['T2-D3']['parameter_count'],48)
        self.assertEqual(ids['T2-D3']['input_coeff_count'],3)

    def test_inrange_preview_excludes_explicitly_and_refuses_mass_exclusion(self):
        rows=[{'temperature_mean_c':i/10,'reference':[0,0,1],
               'acc_raw_mean_g':[0,0,1],'temperature_target_c':i/10,'mode':'static'}
              for i in range(10)]
        model={'fit_temperature_range_c':[0,.8],'temperature_input':{'id':'T0','kind':'raw_chip'},
               'forward_coeff':[[[1],[0],[0]],[[0],[1],[0]],[[0],[0],[1]]],
               'bias_coeff':[[0],[0],[0]]}
        out=_errors_inrange_preview(rows,'acc',model)
        self.assertEqual(out['excluded_out_of_range_count'],1)
        self.assertEqual(out['count'],9)
        bad=copy.deepcopy(model);bad['fit_temperature_range_c']=[0,.7]
        with self.assertRaises(ValueError):_errors_inrange_preview(rows,'acc',bad)

    def test_partial_real_data_acc_complete_gyro_missing_if_mounted(self):
        data=Path('/mnt/data/thermal_diagnosis/temperature_measurements.json')
        if not data.is_file():self.skipTest('Prior run JSON absent')
        checkpoint=json.loads(data.read_text(encoding='utf8'))
        p=load_profile(str(ROOT))
        configure_thermal_gyro_profile(p,fit_rates=(1,5,15,30),verify_rates=(1.5,3.5,10,20,25))
        temps=[20,22.5,25,27.5,30,32.5,35,37.5,40]
        config={'temperature_setpoints_c':temps,
                'temperature_split':{str(float(x)):('fit' if x%5==0 else 'validate') for x in temps},
                'resume_immutable_config':{'quality_profile':p,'gyro_dynamic':True}}
        self.assertEqual(fully_accepted_sensors(config,checkpoint),('acc',))

if __name__=='__main__':unittest.main()
