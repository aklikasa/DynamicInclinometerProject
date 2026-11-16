# -*- coding: utf-8 -*-
"""Offline tests for true degree-3 fitted-temperature model and holdout logic.
No Qt/vendor DLL/PLC connection is required.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from thermal_compensation import _eval_poly, apply_temperature_model, build_thermal_model
from thermal_variable_temperature import (temperature_splits, save_variable_models,
                                          save_optional_gyro_bias)


def synthetic_rows(temps=(-20,0,25,45,70)):
    result=[]
    splits=temperature_splits(temps)
    for t in temps:
        z = (float(t)-25.0)/50.0
        # A genuine cubic dependence in both scale and bias. Magnitudes stay physical.
        F=np.array([[1.004+0.002*z+0.001*z*z+0.0004*z**3,0.0005,0.0],
                    [0.0003,0.996-0.001*z+0.0007*z*z*z,0.0],
                    [0.0,0.0004,1.003+0.001*z*z-0.0003*z**3]])
        b=np.array([0.01+0.001*z-0.0005*z*z+0.0003*z**3,
                    -0.008+0.0004*z*z,0.002-0.0002*z+0.0001*z**3])
        refs=[np.eye(3)[axis]*sgn*rate for axis in range(3)
              for rate in (1,5,15,30,60) for sgn in (-1,1)]
        validation=[np.eye(3)[axis]*sgn*rate for axis in range(3)
                    for rate in (1.5,3.5,10,20,45) for sgn in (-1,1)]
        for split, vectors in (('fit',refs),('validate',validation)):
            for idx,ref in enumerate(vectors):
                result.append({'sensor':'gyro','temperature_split':splits[t],
                               'temperature_target_c':float(t),
                               'temperature_mean_c':float(t),
                               'reference':ref.tolist(), 'gyro_raw_mean_dps':(F@ref+b).tolist(),
                               'split':split, 'mode':'rate'})
        for split in ('fit','validate'):
            result.append({'sensor':'gyro','temperature_split':splits[t],
                           'temperature_target_c':float(t),
                           'temperature_mean_c':float(t),
                           'reference':[0.,0.,0.], 'gyro_raw_mean_dps':b.tolist(),
                           'split':split, 'mode':'static'})
    return result

class CubicTests(unittest.TestCase):
    def test_degree_three_on_independent_temperature(self):
        rows=synthetic_rows()
        model=build_thermal_model(rows,'gyro',degree=3)
        self.assertEqual(model['polynomial_degree'],3)
        self.assertEqual(model['fit_temperature_setpoints_c'],[-20.,0.,25.,70.])
        self.assertEqual(model['holdout_temperature_setpoints_c'],[45.])
        self.assertEqual(len(model['bias_coeff'][0]),4)
        self.assertEqual(len(model['forward_coeff'][0][0]),4)
        self.assertLess(model['temperature_holdout']['vector_rmse'],1e-9)
        self.assertFalse(model['production_release'])
        measured=([1.0,0,0])
        y=apply_temperature_model(model,measured,25.)
        self.assertEqual(len(y),3)
    def test_full_model_and_bias_save_cubic(self):
        rows=synthetic_rows()
        with tempfile.TemporaryDirectory() as d:
            status=save_variable_models(d,rows,[-20,0,25,45,70],('gyro',))
            self.assertEqual(status['sensors']['gyro']['polynomial_degree'],3)
            path=Path(d)/'thermal_gyro_candidate.json'
            self.assertTrue(path.exists())
            x=json.loads(path.read_text(encoding='utf8'))
            self.assertEqual(x['polynomial_degree'],3)
            bp=Path(save_optional_gyro_bias(d,rows,[-20,0,25,45,70]))
            self.assertEqual(json.loads(bp.read_text(encoding='utf8'))['degree'],3)
    def test_four_temperatures_research_only_and_no_temperature_holdout(self):
        temps=(-20.,0.,25.,70.)
        rows=synthetic_rows(temps)
        with tempfile.TemporaryDirectory() as d:
            result=save_variable_models(d,rows,temps,('gyro',))
            self.assertEqual(result['sensors']['gyro']['status'],'provisional_cubic_no_temperature_holdout')
            self.assertTrue((Path(d)/'thermal_gyro_PROVISIONAL_cubic_no_temperature_holdout.json').exists())
            self.assertFalse((Path(d)/'thermal_gyro_candidate.json').exists())
    def test_three_temperatures_no_cubic_or_linear_fallback(self):
        temps=(-20.,25.,70.)
        rows=synthetic_rows(temps)
        with tempfile.TemporaryDirectory() as d:
            result=save_variable_models(d,rows,temps,('gyro',))
            self.assertEqual(result['sensors']['gyro']['status'],'local_calibration_only')
            self.assertFalse(any(Path(d).glob('thermal_gyro_PROVISIONAL*.json')))
            self.assertFalse((Path(d)/'thermal_gyro_candidate.json').exists())
    def test_split_limits(self):
        for n in range(1,11):
            temps=list(range(n))
            splits=temperature_splits(temps)
            self.assertEqual(splits[temps[0]],'fit')
            self.assertEqual(splits[temps[-1]],'fit')
            if n>=5:
                self.assertGreaterEqual(list(splits.values()).count('fit'),4)
                self.assertIn('validate',list(splits.values()))
            else:
                self.assertEqual(set(splits.values()),{'fit'})
if __name__ == '__main__':unittest.main(verbosity=2)
