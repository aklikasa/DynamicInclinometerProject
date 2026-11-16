# -*- coding: utf-8 -*-
"""无硬件：验证外X内Z六姿态和安全匀速重试状态机。"""
import ast,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from production_calibration import acc_fit_steps, frame_average_sanitized, load_profile
from test_production_calibration import math_from_source

def test():
    ns=math_from_source()
    steps=acc_fit_steps()[:6]
    ideal=np.array([[0,0,1],[0,0,-1],[1,0,0],[-1,0,0],[0,1,0],[0,-1,0.]])
    observed=np.array([ns['_platform_gravity_vector'](x['inner_deg'],x['outer_deg'],'outer_x_inner_z') for x in steps])
    assert np.allclose(observed,ideal,atol=1e-12),(observed,ideal)
    p=load_profile(ROOT)
    assert p['quality']['mad_sigma']==3
    arr=np.ones((16,3)); arr[0,0]=100
    mean, raw, good=frame_average_sanitized(arr,3,return_stats=True)
    assert raw==16 and good==15 and np.allclose(mean,[1,1,1])
    source=ROOT/'form'/'form_imu_calibration.py'
    tree=ast.parse(source.read_text(encoding='utf-8'))
    klass=next(x for x in tree.body if isinstance(x,ast.ClassDef) and x.name=='FormImuCalibration')
    method=next(x for x in klass.body if isinstance(x,ast.FunctionDef) and x.name=='_retry_rate_sample_or_abort')
    module=ast.fix_missing_locations(ast.Module(body=[method],type_ignores=[]))
    scope={'INNER_ROTATION_AXIS':1,'OUTER_ROTATION_AXIS':2,'_now_iso':lambda:'2026-10-22T12:00:00'}
    exec(compile(module,str(source),'exec'),scope)
    fn=scope['_retry_rate_sample_or_abort']
    class Mock:
        def __init__(self):
            self.stopped=[];self.aborted=[];self.history=[]
            self.label_auto_task=type('Label',(),{'setText':lambda s,t:None})()
            self._auto_task={'rate_retry_count':0,'rate_retry_history':[],'last_rate_quality_error':'转台实测速度波动过大',
                             'quality_profile':p,'phase':'sample_rate','sample_frames':[1,2],
                             'index':10,'steps':[None]*20}
        def _send_stop_axis(self,axis): self.stopped.append(axis);return True
        def _request_auto_abort(self,text): self.aborted.append(text)
        def _log_event(self,*args):self.history.append(args)
    m=Mock();step={'step_id':'GYRO_FIT_X_09','rotation_axis':'outer'}
    for i in range(3):
        fn(m,step,100+i)
        assert m.stopped==[2]*(i+1) and not m.aborted
        assert m._auto_task['phase']=='wait_stop_retry'
        assert m._auto_task['index']==10  # 必须在相同工况重试
        m._auto_task['phase']='sample_rate'
    fn(m,step,103)
    assert len(m.aborted)==1 and '速度波动' in m.aborted[0]
    assert m.stopped==[2,2,2] # 失败末次由全局中止逻辑停止两轴
    print('PASS: XZ六姿态, 稳健3MAD, GYRO动态失败先停车/重试3次/最后中止')
if __name__=='__main__':test()
