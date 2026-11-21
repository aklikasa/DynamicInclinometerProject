# -*- coding: utf-8 -*-
"""三方案标定：不需要 Qt、串口或转台的数值及导出回归测试。"""
import json
import math
import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np
from calibration_model_compare import fit_model, compare_models, MODEL_NAMES, _rotation_from_vector
from model_comparison_report import save_model_comparison
from production_calibration import acc_fit_steps,acc_verify_steps,gyro_fit_steps,gyro_verify_steps,load_profile


def platform_ref(step):
    alpha=math.radians(step['outer_deg']); beta=math.radians(step['inner_deg'])
    ca,sa=math.cos(alpha),math.sin(alpha)
    cb,sb=math.cos(beta),math.sin(beta)
    outer=np.array([[1,0,0],[0,ca,-sa],[0,sa,ca]])
    inner=np.array([[cb,-sb,0],[sb,cb,0],[0,0,1]])
    return (outer@inner).T@np.array([0.,0.,1.])


def acc_rows(steps, forward, bias):
    return [dict(step_id=step['step_id'],split=step['split'],reference=r.tolist(),
                 measured=(forward@r+bias).tolist(),temperature_mean_c=25.)
            for step in steps for r in [platform_ref(step)]]


def gyro_rows(steps, forward, bias):
    out=[]
    for step in steps:
        ref=np.zeros(3)
        if step['mode']=='rate':
            axis={'Z':2,'X':0,'Y':1}[step['step_id'].split('_')[2]]
            ref[axis]=step['target_rate_dps']
        out.append(dict(step_id=step['step_id'],split=step['split'],reference=ref.tolist(),
                        measured=(forward@ref+bias).tolist(), temperature_mean_c=25.,
                        target_rate_dps=step.get('target_rate_dps')))
    return out


class CompareModelsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile=load_profile(str(Path(__file__).resolve().parent.parent))

    def test_acc_axis_aligned_ellipsoid_bias_scales(self):
        forward=np.diag([1.013,.984,1.022]); bias=np.array([.023,-.014,.009])
        rows=acc_rows(acc_fit_steps(),forward,bias)
        fit=fit_model('acc','A',[r['reference'] for r in rows],[r['measured'] for r in rows])
        np.testing.assert_allclose(fit['bias'],bias,atol=1e-6)
        np.testing.assert_allclose(fit['forward_matrix'],forward,atol=1e-6)
        self.assertLess(fit['fit_vector_rmse'],1e-6)

    def test_acc_ellipsoid_finds_bias_even_if_mounted_rotated(self):
        # 椭球校正不自动把加速度轴转入P系，不能用零模长误差冒充方向准确。
        R=_rotation_from_vector([.035,-.042,.019])
        D=np.diag([1.013,.984,1.022]); forward=D@R.T
        bias=np.array([.023,-.014,.009]); fit_steps=acc_fit_steps(); val_steps=acc_verify_steps()
        rows=acc_rows(fit_steps,forward,bias)
        val=acc_rows(val_steps,forward,bias)
        compare=compare_models('acc',rows,val,self.profile)
        np.testing.assert_allclose(compare['models']['A']['fit']['bias'],bias,atol=1e-5)
        np.testing.assert_allclose(compare['models']['A']['fit']['axis_sensitivity'],np.diag(D),atol=1e-5)
        self.assertGreater(compare['models']['A']['independent_validation']['max_direction_error_deg'],1)
        self.assertLess(compare['models']['B']['independent_validation']['rmse_vector'],1e-5)
        self.assertLess(compare['models']['C']['independent_validation']['rmse_vector'],1e-5)

    def test_gyro_three_models_fit_and_validate(self):
        profile=self.profile
        D=np.diag([1.011,.993,1.007]); b=np.array([.015,-.022,.012])
        R=_rotation_from_vector([.023,-.017,.018]); F=D@R.T
        rows=gyro_rows(gyro_fit_steps(profile),F,b)
        val=gyro_rows(gyro_verify_steps(profile),F,b)
        report=compare_models('gyro',rows,val,profile)
        self.assertEqual(len(report['models']),3,str(report['errors']))
        self.assertLess(report['models']['B']['independent_validation']['rmse_vector'],1e-5)
        self.assertLess(report['models']['C']['independent_validation']['rmse_vector'],1e-5)
        self.assertGreater(report['models']['A']['independent_validation']['rmse_vector'],1e-3)
        self.assertEqual(len(report['models']['C']['independent_validation']['vectors']),13)

    def test_json_csv_xlsx_export(self):
        D=np.diag([1.01,.99,1.02]); b=np.array([.01,.02,.015])
        report=compare_models('acc',acc_rows(acc_fit_steps(),D,b),
                              acc_rows(acc_verify_steps(),D,b),self.profile)
        with tempfile.TemporaryDirectory() as tmp:
            files=save_model_comparison(tmp,'acc',report)
            self.assertEqual(len(files),3)
            for path in files: self.assertTrue(Path(path).is_file(),path)
            data=json.loads(Path(files[0]).read_text(encoding='utf-8'))
            self.assertIn('models',data)
            import zipfile
            with zipfile.ZipFile(files[2]) as z:
                self.assertIsNone(z.testzip())
                self.assertIn('xl/worksheets/sheet2.xml',z.namelist())

    def test_validation_leakage_rejected(self):
        D=np.eye(3); b=np.zeros(3)
        fit=acc_rows(acc_fit_steps(),D,b)
        with self.assertRaisesRegex(ValueError,'重叠'):
            from calibration_model_compare import score_model
            score_model('acc','C',fit,fit,self.profile)

    def test_gyro_singular_design_rejected(self):
        x=np.zeros((20,3)); y=np.zeros((20,3))
        with self.assertRaisesRegex(ValueError,'秩不足'):
            fit_model('gyro','C',x,y)


if __name__=='__main__':
    unittest.main(verbosity=2)
