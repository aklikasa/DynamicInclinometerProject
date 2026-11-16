# -*- coding: utf-8 -*-
"""模拟UI方法提取：不用PySide6验证A/B候选结果格式可喂给原版Excel。"""
import ast
import datetime
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from calibration_model_compare import MODEL_NAMES,score_model
from production_calibration import acc_fit_steps,acc_verify_steps,gyro_fit_steps,gyro_verify_steps,load_profile,sensor_axis_invariants
from calibration_excel_report import create_validation_workbook
from test_model_compare import acc_rows,gyro_rows

FILE=Path(__file__).resolve().parent.parent/'form/form_imu_calibration.py'
TREE=ast.parse(FILE.read_text(encoding='utf-8'))
FORM=next(node for node in TREE.body if isinstance(node,ast.ClassDef) and node.name=='FormImuCalibration')
selected=next(node for node in FORM.body if isinstance(node,ast.FunctionDef) and node.name=='_run_selected_model')
namespace={'MODEL_NAMES':MODEL_NAMES,'score_model':score_model,'sensor_axis_invariants':sensor_axis_invariants,
           '_now_iso':lambda: datetime.datetime.now().isoformat()}
exec(compile(ast.Module(body=[selected],type_ignores=[]),str(FILE),'exec'),namespace)


class SelectedModelExcelCompatibility(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile=load_profile(str(Path(__file__).resolve().parent.parent))

    def test_acc_and_gyro_AB_candidate_workbook(self):
        for kind in ('acc','gyro'):
            f=np.diag([1.01,.995,1.02]);b=np.array([.015,-.012,.01])
            if kind=='acc':
                fit=acc_rows(acc_fit_steps(),f,b);validate=acc_rows(acc_verify_steps(),f,b)
                poses=[]
                for step, item in zip(acc_fit_steps()+acc_verify_steps(),fit+validate):
                    poses.append(dict(step_id=item['step_id'],split=item['split'],
                        gravity_reference_platform_g=item['reference'],acc_raw_mean_g=item['measured'],
                        inner_target_deg=step['inner_deg'],outer_target_deg=step['outer_deg'],
                        temperature_mean_c=25,accepted_frames=55))
                task_type='accel'
            else:
                fit=gyro_rows(gyro_fit_steps(self.profile),f,b)
                validate=gyro_rows(gyro_verify_steps(self.profile),f,b)
                poses=[];task_type='gyro'
            task={'type':task_type,'pose_measurements':poses,
                  'axis_model':'outer_x_inner_z','device_serial':'TEST-01',
                  'gravity_sign':1,'quality_profile':self.profile}
            fake=SimpleNamespace(run_id='TEST_001')
            fake._model_rows=lambda task:(fit,validate)
            for model in ('A','B'):
                result=namespace['_run_selected_model'](fake,task,model)
                result['sensor_configuration']={'chip':'ASM330LHHX'}
                with self.subTest(kind=kind,model=model),tempfile.TemporaryDirectory() as out:
                    path=create_validation_workbook(task_type,result,out)
                    self.assertTrue(Path(path).is_file())
                    self.assertEqual(result['model_id'],model)

if __name__=='__main__': unittest.main(verbosity=2)
