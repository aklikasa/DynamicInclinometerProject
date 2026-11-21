# -*- coding: utf-8 -*-
"""No-hardware regression of WK ambient comparison and original A/B/C reports."""
import json
import math
import sys
from pathlib import Path
import zipfile
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from production_calibration import acc_fit_steps,acc_verify_steps,gyro_fit_steps,gyro_verify_steps,load_profile
from wk_ambient_comparison import ambient_comparison_rows, metrics_for_model, export_ambient_comparison


def _gravity(beta,alpha):
    b,a=np.deg2rad([beta,alpha]); cb,sb=np.cos(b),np.sin(b);ca,sa=np.cos(a),np.sin(a)
    rz=np.array([[cb,-sb,0],[sb,cb,0],[0,0,1]])
    rx=np.array([[1,0,0],[0,ca,-sa],[0,sa,ca]])
    return (rx@rz).T @ np.array([0.,0.,1.])


def _rows():
    forward=np.array([[1.004,.002,-.001],[.001,.995,.002],[.001,-.002,1.003]])
    bias=np.array([.001,-.0005,.0008])
    out=[]
    for step in acc_fit_steps()+acc_verify_steps():
        ref=_gravity(step['inner_deg'],step['outer_deg'])
        measured=ref@forward.T+bias
        out.append({'sensor':'acc','step_id':step['step_id'],'split':step['split'],
           'reference':ref.tolist(),'acc_raw_mean_g':measured.tolist(),
           'temperature_mean_c':25.1})
    return out


def test_original_ambient_acc_pose_plan_exact():
    fit,val=acc_fit_steps(),acc_verify_steps()
    assert len(fit)==12 and len(val)==12
    assert set(x['step_id'] for x in fit).isdisjoint(x['step_id'] for x in val)
    assert fit[0]['inner_deg']==0 and fit[0]['outer_deg']==0


def test_original_ambient_gyro_plan_unchanged():
    profile=load_profile(str(ROOT))
    fit=gyro_fit_steps(profile); val=gyro_verify_steps(profile)
    assert len(fit)==19 and len(val)==13
    assert profile['rates']['fit_dps']==[1.,2.,5.]
    assert profile['rates']['verify_dps']==[1.5,3.5]
    assert fit[0]['step_id']=='GYRO_ZERO_FIT'


def test_norm_error_is_not_vector_error():
    # A rotated unit vector has zero norm error but nonzero vector error.
    rows=[{'reference':[0,0,1], 'measured':[math.sin(.01),0,math.cos(.01)]}]
    fit={'bias':[0,0,0], 'correction_matrix':np.eye(3)}
    m=metrics_for_model(rows,fit)
    assert m['norm_rmse_mg']<1e-10
    assert 9<m['vector_rmse_mg']<11


def test_same_ambient_abc_excel_report_and_norm_rmse(tmp_path):
    rows=_rows();fit,val=ambient_comparison_rows(rows,'acc')
    assert len(fit)==len(val)==12
    output,paths=export_ambient_comparison(tmp_path,rows,load_profile(str(ROOT)),
          axis_model='outer_x_inner_z',gravity_sign=1,device_serial='WK_TEST',include_gyro=False)
    assert output['production_release'] is False
    assert output['parameter_overwrite'] is False
    assert output['models']['acc']['status']=='EVALUATED'
    bycode={x['model']:x for x in output['models']['acc']['models']}
    assert set(bycode)=={'A','B','C'}
    assert bycode['C']['independent_pose_validation']['norm_rmse_mg']<1e-7
    assert bycode['C']['independent_pose_validation']['vector_rmse_mg']<1e-7
    assert len(paths)==7
    assert (tmp_path/'validation_comparison_ACC.xlsx').exists()
    for f in paths:assert Path(f).exists() and Path(f).stat().st_size>100
    with zipfile.ZipFile(tmp_path/'model_comparison_acc.xlsx') as z:
        assert 'xl/workbook.xml' in z.namelist()
        contents=z.read('xl/workbook.xml').decode()
        for title in ['模型结果','独立验证残差','参数矩阵']:
            assert title in contents
    with zipfile.ZipFile(tmp_path/'validation_comparison_ACC.xlsx') as z:
        assert 'ACC逐姿态' in z.read('xl/workbook.xml').decode()
    assert not any('latest' in p.lower() for p in paths)
    assert not any('production' in p.lower() for p in paths)
    assert '模长RMSE' in (tmp_path/'wk_ambient_comparison_summary.md').read_text(encoding='utf-8')


def test_incomplete_acc_yields_no_fake_model(tmp_path):
    output,paths=export_ambient_comparison(tmp_path,_rows()[:-1],load_profile(str(ROOT)),
          axis_model='outer_x_inner_z',gravity_sign=1,device_serial='WK_TEST',include_gyro=False)
    assert output['models']['acc']['status']=='INCOMPLETE'
    assert output['models']['acc']['validation_count']==11
    assert not (tmp_path/'model_comparison_acc.xlsx').exists()


def test_thermal_form_has_isolated_no_plc_wk_ambient_execution():
    source=(ROOT/'form'/'form_thermal_compensation.py').read_text(encoding='utf-8')
    assert 'button_WKAmbientComparison' in source
    assert 'self.start(ambient_diagnostic=True)' in source
    assert "'ambient_wk_compare':bool(ambient_diagnostic)" in source
    assert "if t.get('ambient_wk_compare'):" in source
    assert 'def _finish_wk_ambient_comparison' in source
    assert "'UNCHANGED_NO_PLC_COMMANDS'" in source
    assert '_platform_gravity_vector' in source
    assert 'twoTD600_SetAxisPosition' not in source
    assert 'twoTD600_SetAxisVelocity' not in source
    assert 'twoFDT600WK_SetAxisVelocity' in source
