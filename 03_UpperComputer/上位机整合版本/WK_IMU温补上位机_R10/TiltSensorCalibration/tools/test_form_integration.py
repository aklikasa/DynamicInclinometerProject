# -*- coding: utf-8 -*-
"""提取真实 Qt 页面中的求参方法做合成数据贯通测试（无Qt及硬件依赖）。"""
import ast
import json
import sys
import tempfile
import datetime
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'form'))
import production_calibration as pc

source=ROOT/'form'/'form_imu_calibration.py'
tree=ast.parse(source.read_text(encoding='utf-8'))
cls=next(x for x in tree.body if isinstance(x,ast.ClassDef) and x.name=='FormImuCalibration')
subset=ast.ClassDef(name='Fitted',bases=[],keywords=[],decorator_list=[],
                    body=[x for x in cls.body if isinstance(x,ast.FunctionDef) and x.name in
                          ('_fit_accelerometer_result','_fit_gyroscope_result','_fit_alignment_result')])
math_names={'_rotation_x','_rotation_y','_rotation_z','_platform_rotation','_platform_gravity_vector',
            '_platform_angular_rate','_fit_affine_reference','_now_iso'}
math_funcs=[x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name in math_names]
ns={'np':np,'json':json,'os':__import__('os'),'datetime':datetime,
    'residual_statistics':pc.residual_statistics,'evaluate':pc.evaluate,
    'sensor_axis_invariants':pc.sensor_axis_invariants}
exec(compile(ast.fix_missing_locations(ast.Module(body=math_funcs+[subset],type_ignores=[])),str(source),'exec'),ns)

rng=np.random.default_rng(887)
profile=pc.load_profile(ROOT)
A=np.array([[0.92,-0.39,0.012],[0.38,0.93,-0.005],[0.008,0.011,1.004]])
ab=np.array([0.006,-0.005,0.013])
G=np.array([[0.98,-0.12,0.007],[0.14,0.98,0.003],[0.005,0.004,1.01]])
gb=np.array([0.02,-0.03,0.05])


def apose(step):
    ref=ns['_platform_gravity_vector'](step['inner_deg'],step['outer_deg'],'outer_x_inner_z',1)
    return {**step,'inner_actual_mean_deg':step['inner_deg'],
            'outer_actual_mean_deg':step['outer_deg'],
            'acc_raw_mean_g':(A@ref+ab+rng.normal(0,0.0005,3)).tolist(),
            'temperature_mean_c':25.0}


def grate(step):
    if step['mode']=='static': ref=np.zeros(3)
    else:
        speed=step['target_rate_dps']
        ref=ns['_platform_angular_rate'](step['inner_deg'],step['outer_deg'],
            speed if step['rotation_axis']=='inner' else 0,
            speed if step['rotation_axis']=='outer' else 0,'outer_x_inner_z')
    return {**step,'reference':ref.tolist(),
            'measured':(G@ref+gb+rng.normal(0,0.01,3)).tolist(),'temperature_mean_c':25.0}

obj=ns['Fitted']()
obj.run_id='SYNTHETIC_TEST'
taskbase={'axis_model':'outer_x_inner_z','gravity_sign':1,
          'quality_profile':profile,'device_serial':'PCB-TEST-001'}
atrial={**taskbase,'pose_measurements':[apose(s) for s in pc.acc_fit_steps()+pc.acc_verify_steps()]}
ares=obj._fit_accelerometer_result(atrial)
assert ares['quality_gate']['metric_pass'], ares['quality_gate']
assert ares['quality_gate']['verdict']=='PILOT_PASS_NOT_RELEASED'
gtrial={**taskbase,'gyro_fit_samples':[grate(s) for s in pc.gyro_fit_steps(profile)],
        'gyro_validation_samples':[grate(s) for s in pc.gyro_verify_steps(profile)]}
gres=obj._fit_gyroscope_result(gtrial)
assert gres['quality_gate']['metric_pass'],gres['quality_gate']
with tempfile.TemporaryDirectory() as tmp:
    from types import SimpleNamespace
    obj.line_output_root=SimpleNamespace(text=lambda:tmp)
    for name,data in [('accel_calibration.json',ares),('gyro_calibration.json',gres)]:
        Path(tmp,name).write_text(json.dumps(data),encoding='utf-8')
    sixtrial={**taskbase,'pose_measurements':[apose(s) for s in pc.acc_verify_steps()],
              'gyro_validation_samples':[grate(s) for s in pc.gyro_verify_steps(profile)]}
    final=obj._fit_alignment_result(sixtrial)
    assert final['quality_gate']['metric_pass']
    assert final['status']=='PILOT_PASS_NOT_RELEASED'
    assert 'relative_rotation_gyro_to_accel' not in final
    gtrial_bad={**gtrial,'device_serial':'OTHERPCB'}
    badgres=obj._fit_gyroscope_result(gtrial_bad)
    Path(tmp,'gyro_calibration.json').write_text(json.dumps(badgres),encoding='utf-8')
    try: obj._fit_alignment_result(sixtrial)
    except ValueError as exc: assert '编号' in str(exc)
    else: raise AssertionError('跨PCB参数混用未被拦截')
print('PASS: Qt source methods ACC/GYRO/6-axis end-to-end synthetic validation and PCB isolation')
