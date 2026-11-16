# -*- coding: utf-8 -*-
"""Offline tests for user-selectable 1..N temperature acquisition and reporting."""
import sys
import tempfile
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import numpy as np
from thermal_variable_temperature import (parse_temperatures, temperature_splits,
                                          save_variable_models, save_optional_gyro_bias)
from thermal_excel_report import export_thermal_xlsx


def fake_rows(temps):
    rng=np.random.default_rng(134)
    acc = [[0,0,1],[1,0,0],[-1,0,0],[0,1,0],[0,-1,0],[0,0,-1],
           [1,1,1],[-1,1,1],[1,-1,1],[1,1,-1],[-1,-1,1],[1,-1,-1]]
    gyro = [[0,0,0]] + [[(rate*sgn if j==axis else 0) for j in range(3)]
                   for axis in range(3) for rate in (1,5,15,30,60) for sgn in (-1,1)]
    rows=[]
    split=temperature_splits(temps)
    for t in temps:
        for sensor,refv in [('acc',acc),('gyro',gyro)]:
            F=np.diag([1.01 + t*1e-5,.995-t*2e-5,1.002])
            b=np.array([.011,-.009,.008])+(t-25)*np.array([.00003,-.00002,.00001])
            for mode in ('fit','validate'):
                for index,v in enumerate(refv):
                    vec=np.asarray(v,dtype=float)
                    if sensor=='acc': vec=vec/np.linalg.norm(vec)
                    raw=F@vec+b+rng.normal(0,0.00003 if sensor=='acc' else 0.0001,3)
                    row={'sensor':sensor,'split':mode,'mode':'static' if sensor=='gyro' and index==0 else 'rate',
                         'temperature_split':split[t],'temperature_target_c':t,'temperature_mean_c':t,
                         'reference':vec.tolist(),
                         ('acc_raw_mean_g' if sensor=='acc' else 'gyro_raw_mean_dps'):raw.tolist()}
                    rows.append(row)
    return rows

class TestFlexibleTemperature(unittest.TestCase):
    def test_parsing(self):
        for text,out in [('25',[25]),('-20, 0,25,45,70',[-20,0,25,45,70]),
                         ('0，25；60',[0,25,60]),('25\n70',[25,70])]:
            self.assertEqual(parse_temperatures(text),out)
        for s in ('', '25,','25,25','40,20','nan','inf','100','abc'):
            with self.subTest(s=s), self.assertRaises(ValueError):parse_temperatures(s)
    def test_split_for_cubic_five(self):
        self.assertEqual(list(temperature_splits([-20,0,25,45,70]).values()),
                         ['fit','fit','fit','validate','fit'])
    def test_split_always_includes_endpoints(self):
        for n in range(1,13):
            temps=list(range(0,n*10,10))
            split=temperature_splits(temps)
            self.assertEqual(split[temps[0]],'fit')
            self.assertEqual(split[temps[-1]],'fit')
            if n>=5:
                self.assertIn('validate',list(split.values()))
                self.assertGreaterEqual(list(split.values()).count('fit'),4)
            else:
                self.assertNotIn('validate',list(split.values()))
    def test_model_outputs_all_counts(self):
        for temps in ([25],[25,70],[-20,25,70],[-20,0,25,70],[-20,0,25,45,70],[-20,0,25,45,60,70]):
            with self.subTest(n=len(temps)),tempfile.TemporaryDirectory() as temp:
                rows=fake_rows(temps)
                report=save_variable_models(temp,rows,temps)
                self.assertTrue((Path(temp)/'thermal_fit_status.json').exists())
                self.assertNotEqual(report['sensors']['acc']['status'],'not_estimated')
                self.assertNotEqual(report['sensors']['gyro']['status'],'not_estimated')
                save_optional_gyro_bias(temp,rows,temps)
                if len(temps)==1:
                    self.assertTrue((Path(temp)/'local_acc_temperature_calibration.json').exists())
                    self.assertFalse((Path(temp)/'thermal_acc_candidate.json').exists())
                    self.assertFalse((Path(temp)/'thermal_acc_PROVISIONAL_no_temperature_holdout.json').exists())
                elif len(temps)<=3:
                    self.assertTrue((Path(temp)/'local_acc_temperature_calibration.json').exists())
                    self.assertFalse((Path(temp)/'thermal_acc_PROVISIONAL_no_temperature_holdout.json').exists())
                    self.assertFalse((Path(temp)/'thermal_acc_candidate.json').exists())
                elif len(temps)==4:
                    self.assertEqual(report['sensors']['acc']['status'],'provisional_cubic_no_temperature_holdout')
                    self.assertTrue((Path(temp)/'thermal_acc_PROVISIONAL_cubic_no_temperature_holdout.json').exists())
                    self.assertFalse((Path(temp)/'thermal_acc_candidate.json').exists())
                else:
                    self.assertEqual(report['sensors']['acc']['status'],'candidate_created')
                    self.assertEqual(report['sensors']['acc']['polynomial_degree'],3)
                    self.assertTrue((Path(temp)/'thermal_acc_candidate.json').exists())
                self.assertTrue(Path(export_thermal_xlsx(temp,[],report)).exists())
    def test_two_close_temperatures_still_keep_local_calibrations(self):
        temps=[25,26]
        with tempfile.TemporaryDirectory() as tmp:
            m=save_variable_models(tmp,fake_rows(temps),temps)
            self.assertTrue((Path(tmp)/'local_acc_temperature_calibration.json').exists())
            # If insufficient actual T span for a trend, there must be no purported thermal fit.
            self.assertFalse((Path(tmp)/'thermal_acc_candidate.json').exists())

if __name__=='__main__': unittest.main(verbosity=2)
