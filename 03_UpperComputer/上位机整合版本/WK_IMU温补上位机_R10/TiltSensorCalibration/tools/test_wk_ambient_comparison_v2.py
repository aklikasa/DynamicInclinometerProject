# -*- coding: utf-8 -*-
"""WK单点温度实验A/B/C标定前后与拟合验证报告，不依赖实机。"""
import json
import sys
import zipfile
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from production_calibration import acc_fit_steps,acc_verify_steps,load_profile
from wk_ambient_comparison import export_ambient_comparison


def _rows(tag_c=-17.125):
    forward=np.array([[1.006,0.003,-0.002],[0.001,0.999,0.002],[0.0005,-0.0007,1.004]])
    bias=np.array([0.004,-0.003,0.006])
    rows=[]
    for st in acc_fit_steps()+acc_verify_steps():
        beta,alpha=np.deg2rad([st['inner_deg'],st['outer_deg']]);cb,sb=np.cos(beta),np.sin(beta)
        ca,sa=np.cos(alpha),np.sin(alpha)
        rz=np.array([[cb,-sb,0],[sb,cb,0],[0,0,1]])
        rx=np.array([[1,0,0],[0,ca,-sa],[0,sa,ca]])
        ref=(rx@rz).T@np.array([0.,0.,1.]);raw=ref@forward.T+bias
        rows.append({'step_id':st['step_id'],'split':st['split'],'sensor':'acc',
                     'reference':ref.tolist(),'acc_raw_mean_g':raw.tolist(),
                     'temperature_mean_c':tag_c+0.008*(len(rows)%3),
                     'temperature_target_c':tag_c,
                     'frame_count':155,'accepted_frames':150,'reject_fraction':5/155,
                     'acc_raw_samples':2480,'acc_accepted_samples':2380,
                     'acc_std_g':[0.0002,0.0003,0.0004], 'temperature_span_c':0.03,
                     'inner_actual_mean_deg':st['inner_deg']+0.001,
                     'outer_actual_mean_deg':st['outer_deg']-0.002,
                     'filter_method':'per_frame_MAD_1.4826_then_segment_MAD_1.4826',
                     'filter_sigma':3.0,
                     'inner_target_deg':st['inner_deg'],
                     'outer_target_deg':st['outer_deg'],'accepted_frames':150})
    return rows


def test_new_report_keeps_old_sheets_adds_fit_and_norm(tmp_path):
    out,paths=export_ambient_comparison(tmp_path,_rows(),load_profile(str(ROOT)),
        axis_model='outer_x_inner_z',gravity_sign=1,device_serial='NEW',include_gyro=False)
    assert out['models']['acc']['status']=='EVALUATED'
    with zipfile.ZipFile(tmp_path/'model_comparison_acc.xlsx') as z:
        xml=z.read('xl/workbook.xml').decode()
        for name in ('模型结果','独立验证残差','参数矩阵','ACC拟合与验证RMSE',
                     'ACC拟合集逐姿态','ACC验证集逐姿态','ACC采样去噪审计','ACC指标解释'):
            assert name in xml
        joined='\n'.join(z.read(n).decode() for n in z.namelist()
                         if n.startswith('xl/') and n.endswith('.xml'))
        for header in ('拟合模长RMSE_mg','验证模长RMSE_mg','原始模长偏差_mg',
                       '校正向量误差_mg','有效帧数','跨帧3σ剔除率','12个独立验证姿态'):
            assert header in joined
    with zipfile.ZipFile(tmp_path/'validation_comparison_ACC.xlsx') as z:
        xml=z.read('xl/workbook.xml').decode()
        assert all(n in xml for n in ('结果概览','ACC逐姿态','指标解释'))
        joined='\n'.join(z.read(n).decode() for n in z.namelist()
                         if n.startswith('xl/') and n.endswith('.xml'))
        assert '-17.125' in joined
    metrics=json.loads((tmp_path/'model_comparison_acc.json').read_text(encoding='utf-8'))['wk_metric_summary']
    assert metrics['C']['fit']['norm_rmse_mg']<1e-6
    assert metrics['C']['validation']['vector_rmse_mg']<1e-6
    assert metrics['C']['fit']['count']==12
    assert metrics['C']['validation']['count']==12


def test_non_ambient_temperature_no_longer_forced_but_drift_gates_remain():
    source=(ROOT/'form/form_thermal_compensation.py').read_text(encoding='utf-8')
    start=source.split('    def _start_wk_ambient_comparison(self):')[1].split('    def start(self,',1)[0]
    assert '20.0 <= chip_temp <= 30.0' not in start
    assert 'abs(pv-25.0)>2.0' not in start
    assert 'math.isfinite(chip_temp)' in start
    assert 'math.isfinite(pv)' in start
    assert "'temperature_setpoints_c':[comparison_tag_c]" in source
    assert "(float(t['temps'][0]),step['step_id']) not in accepted" in source
    assert "profile['quality']['temperature_min_c']=-45.0" in source
    assert "profile['quality']['temperature_max_c']=90.0" in source
    assert "profile['quality']['temperature_span_max_c']=0.5" in source
    assert 'def _reanalyze_wk_ambient_run(self):' in source
    assert 'button_WKAmbientComparison' in source


def test_any_temperature_label_and_old_sheet_layout(tmp_path):
    rows=_rows(42.635)
    out,paths=export_ambient_comparison(tmp_path,rows,load_profile(str(ROOT)),
        axis_model='outer_x_inner_z',gravity_sign=1,device_serial='HOT',include_gyro=False)
    assert out['models']['acc']['status']=='EVALUATED'
    with zipfile.ZipFile(tmp_path/'validation_comparison_ACC.xlsx') as z:
        data=''.join(z.read(n).decode() for n in z.namelist() if n.endswith('.xml'))
        assert '42.635' in data
        assert '单点温度' in data
