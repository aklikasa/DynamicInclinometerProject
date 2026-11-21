# -*- coding: utf-8 -*-
"""无Qt/硬件的生产算法回归及故障注入测试。命令：python tools/test_production_calibration.py"""
import ast
import copy
import json
from pathlib import Path
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'form'))
import production_calibration as pc


def math_from_source():
    path = ROOT/'form'/'form_imu_calibration.py'
    tree = ast.parse(path.read_text(encoding='utf-8'))
    names = {'_rotation_x','_rotation_y','_rotation_z','_platform_rotation',
             '_platform_gravity_vector','_platform_angular_rate','_fit_affine_reference'}
    funcs = [x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name in names]
    namespace = {'np':np}
    exec(compile(ast.Module(body=funcs,type_ignores=[]),str(path),'exec'),namespace)
    return namespace


def fake_frames(acc=(0,0,1),gyro=(4,-7,-3),num=120,mode='static',target=0.0,axis='inner',seed=2026):
    rng = np.random.default_rng(seed)
    return [{
        'acc': (np.asarray(acc)+rng.normal(0,0.0008,3)).tolist(),
        'gyro': (np.asarray(gyro)+rng.normal(0,0.025,3)).tolist(),
        'inner_deg':0.0,'outer_deg':0.0,
        'inner_rate_dps':float(target if axis=='inner' else 0.0),
        'outer_rate_dps':float(target if axis=='outer' else 0.0),
        'temp_c':25.0 + rng.normal(0,0.02),'feedback_delta_ms':10.0}
        for i in range(num)]


def test():
    p = copy.deepcopy(pc.load_profile(ROOT))
    ns = math_from_source()
    av = pc.acc_fit_steps(); ah = pc.acc_verify_steps()
    gf=pc.gyro_fit_steps(p); gh=pc.gyro_verify_steps(p)
    assert len(av)==12 and len(ah)==12 and len(gf)==19 and len(gh)==13
    a_angles={(d['inner_deg'],d['outer_deg']) for d in av}
    b_angles={(d['inner_deg'],d['outer_deg']) for d in ah}
    assert not (a_angles&b_angles)
    angular=lambda row: ns['_platform_gravity_vector'](row['inner_deg'],row['outer_deg'],'outer_x_inner_z')
    aref=np.asarray([angular(v) for v in av]); vref=np.asarray([angular(v) for v in ah])
    assert np.linalg.matrix_rank(np.column_stack((aref,np.ones(len(aref)))))==4
    assert np.linalg.matrix_rank(np.column_stack((vref,np.ones(len(vref)))))==4
    forward_a=np.asarray([[0.92,-0.39,0.012],[0.38,0.93,-0.005],[0.008,0.011,1.004]])
    bias_a=np.array([0.006,-0.005,0.013]); rng=np.random.default_rng(2026)
    raw=aref@forward_a.T+bias_a+rng.normal(0,0.0005,aref.shape)
    validation=vref@forward_a.T+bias_a+rng.normal(0,0.0005,vref.shape)
    fit_a=ns['_fit_affine_reference'](aref,raw,'g','g')
    stats_a=pc.residual_statistics(vref,validation,fit_a['bias'],fit_a['correction_matrix'],'acc')
    decision_a=pc.evaluate(p,'acc',stats_a,fit_a['condition_number'], 3.0,1.0)
    assert decision_a['verdict']=='PILOT_PASS_NOT_RELEASED',decision_a
    assert np.max(abs(fit_a['bias']-bias_a))<0.002
    assert stats_a['rmse_vector']<0.005
    rate_reference=lambda step: ns['_platform_angular_rate'](step['inner_deg'],step['outer_deg'],
                         step['target_rate_dps'] if step['rotation_axis']=='inner' else 0.,
                         step['target_rate_dps'] if step['rotation_axis']=='outer' else 0.,'outer_x_inner_z')
    gref=np.asarray([[0.,0.,0.]]+[rate_reference(x) for x in gf[1:]])
    gvref=np.asarray([[0.,0.,0.]]+[rate_reference(x) for x in gh[1:]])
    assert np.linalg.matrix_rank(np.column_stack((gref,np.ones(len(gref)))))==4
    gforward=np.array([[0.98,-0.12,0.007],[0.14,0.98,0.003],[0.005,0.004,1.01]])
    gbias=np.array([0.02,-0.03,0.05])
    gr=gref@gforward.T+gbias+rng.normal(0,0.015,gref.shape)
    gval=gvref@gforward.T+gbias+rng.normal(0,0.015,gvref.shape)
    fit_g=ns['_fit_affine_reference'](gref,gr,'deg/s','deg/s')
    stats_g=pc.residual_statistics(gvref,gval,fit_g['bias'],fit_g['correction_matrix'],'gyro')
    decision_g=pc.evaluate(p,'gyro',stats_g,fit_g['condition_number'],5.,1.)
    assert decision_g['metric_pass'],decision_g
    frames=fake_frames()
    frames[0]['acc']=[1.,1.,1.]
    out=pc.robust_segment(frames,'static',p)
    assert out['accepted_frames'] < 120 and out['accepted_frames'] >= 110
    bad=fake_frames(); bad[10]['temp_c']=52.0
    try: pc.robust_segment(bad,'static',p)
    except ValueError: pass
    else: raise AssertionError('高温样本未被拒绝')
    rate_frames=fake_frames(gyro=[0.1,0.2,5.0],mode='rate',target=5.,axis='inner')
    assert pc.robust_segment(rate_frames,'rate',p,5.,'inner')['accepted_frames']>=108
    rate_frames[-1]['inner_rate_dps']=1.0
    try: pc.robust_segment(rate_frames,'rate',p,5.,'inner')
    except ValueError: pass
    else: raise AssertionError('速度波动数据未拒绝')
    assert pc.frame_average_sanitized(np.tile([0,0,1.0],(16,1)),6.0) is not None
    assert pc.frame_average_sanitized(np.full((16,3),float('nan')),6.0) is None
    approved=copy.deepcopy(p);approved['approved_for_production']=True
    assert pc.evaluate(approved,'acc',stats_a,fit_a['condition_number'],3.,1.)['verdict']=='PASS'
    print("PASS: 12+12 ACC / 19+13 GYRO plans, rank 4, holdout,")
    print('      robust reject, rate checks, temperature checks, draft/release gate')


if __name__=='__main__':
    test()
