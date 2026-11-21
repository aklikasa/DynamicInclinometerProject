# -*- coding: utf-8 -*-
"""Run with python tools/test_thermal_compensation.py; no hardware or Qt required."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
from thermal_compensation import build_thermal_model,build_gyro_zero_bias_model,fit_affine,save_models,apply_temperature_model


def vectors():
    # Reference excitation comparable to six-axis accelerated/static positions.
    acc=[np.array(v,float) / np.linalg.norm(v) for v in (
        [0,0,1],[1,0,0],[-1,0,0],[0,1,0],[0,-1,0],[0,0,-1],
        [1,1,1],[-1,1,1],[1,-1,1],[1,1,-1],[-1,-1,1],[1,-1,-1])]
    accv=[np.array(v,float) / np.linalg.norm(v) for v in (
        [2,1,1],[1,2,-1],[-1,2,1],[1,-1,2],[2,-1,-1],[-1,-2,-1])]
    gyro=[np.zeros(3)] + [np.eye(3)[axis]*sign*rate for axis in range(3) for rate in (1,2,5) for sign in (1,-1)]
    gyrov=[np.zeros(3)] + [np.eye(3)[axis]*sign*rate for axis in range(3) for rate in (1.5,3.5) for sign in (1,-1)]
    return {'acc':(acc,accv),'gyro':(gyro,gyrov)}


def dataset():
    r=[]
    rng=np.random.default_rng(32)
    for target in [-20,0,25,45,70]:
        split_temp='validate' if target in (0,45) else 'fit'
        for sensor,(fit,check) in vectors().items():
            scale=0.001 if sensor=='acc' else 0.003
            F=np.array([[1.02,0.002,0.0004],[-.002,.995,.0008],[0.0,-0.001,1.01]])
            F=F + (target-25)*np.array([[0.000015,0,0],[0,-0.000012,0],[0,0,0.00002]])
            b=np.array([0.01,-0.008,0.006])+(target-25)*np.array([1e-4,-2e-4,3e-5])
            for kind,vecs in (('fit',fit),('validate',check)):
                for vec in vecs:
                    meas=F@vec+b+rng.normal(0,scale,3)
                    r.append({'temperature_split':split_temp,'temperature_target_c':target,
                              'temperature_mean_c':target,'reference':vec.tolist(),
                              ('acc_raw_mean_g' if sensor=='acc' else 'gyro_raw_mean_dps'):meas.tolist(),
                              'sensor':sensor,'split':kind,'mode':'static' if not np.any(vec) else 'rate'})
    return r


class Tests(unittest.TestCase):
    def test_acc_full_matrix(self):
        rows=[x for x in dataset() if x['sensor']=='acc']
        model=build_thermal_model(rows,'acc',degree=1)
        self.assertLess(model['temperature_holdout']['vector_rmse'],0.012)
        self.assertEqual(model['temperature_holdout']['count'],12)
        self.assertFalse(model['production_release'])

    def test_gyro_full_matrix(self):
        rows=[x for x in dataset() if x['sensor']=='gyro']
        model=build_thermal_model(rows,'gyro',degree=1)
        self.assertLess(model['temperature_holdout']['vector_rmse'],0.02)
        self.assertEqual(model['temperature_holdout']['count'],26)

    def test_mixed_sensor_report_export_and_correction(self):
        import tempfile, json
        with tempfile.TemporaryDirectory() as folder:
            summary=save_models(folder,dataset(),degree=1)
            self.assertEqual(summary['sensors']['acc']['status'],'candidate_created')
            self.assertEqual(summary['sensors']['gyro']['status'],'candidate_created')
            with open(Path(folder)/'thermal_acc_candidate.json',encoding='utf8') as f:
                model=json.load(f)
            recovered=apply_temperature_model(model,[0.01,-0.008,1.006],25)
            self.assertEqual(len(recovered),3)
            with self.assertRaises(ValueError):apply_temperature_model(model,[0,0,1],150)

    def test_gyro_bias_only(self):
        rows=[x for x in dataset() if x['sensor']=='gyro' and x['mode']=='static' and np.linalg.norm(x['reference'])==0]
        model=build_gyro_zero_bias_model(rows,degree=1)
        self.assertLess(model['independent_temperature_rmse_dps'],0.02)
        self.assertFalse(model['production_release'])

    def test_holdout_cannot_leak(self):
        rows=[x for x in dataset() if x['sensor']=='acc']
        for r in rows:
            if r['temperature_target_c'] in (-20,25):
                r['temperature_split']='validate'
        with self.assertRaises(ValueError):build_thermal_model(rows,'acc',degree=1)

    def test_reject_degenerate_reference(self):
        rows=[{'reference':[0,0,1],'acc_raw_mean_g':[0,0,1]} for _ in range(15)]
        with self.assertRaises(ValueError):fit_affine(rows,'acc')

    def test_no_thermal_extrapolation(self):
        rows=[x for x in dataset() if x['sensor']=='acc']
        for r in rows:
            if r['temperature_target_c']==45:r['temperature_mean_c']=75
        with self.assertRaises(ValueError):build_thermal_model(rows,'acc',degree=1)

if __name__=='__main__':unittest.main(verbosity=2)
