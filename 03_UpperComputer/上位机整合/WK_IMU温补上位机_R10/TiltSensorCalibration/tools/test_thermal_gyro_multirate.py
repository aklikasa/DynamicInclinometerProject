# -*- coding: utf-8 -*-
"""温补多速率、符号方向、反馈看门狗离线测试；不依赖Qt/WK DLL或设备。"""
import ast
import copy
import ctypes
import math
from pathlib import Path
import sys
import threading
import time
import types
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from production_calibration import load_profile,gyro_fit_steps,gyro_verify_steps,acc_fit_steps,acc_verify_steps
from thermal_gyro_multirate import (
    FIT_RATES_DPS,VERIFY_RATES_DPS,configure_thermal_gyro_profile,
    wk_signed_velocity,conservative_sweep_degrees,signed_wrapped_increment)


def isolated_method(name, globals_):
    """只提取温补类成员做假 DLL 验证，不加载 PySide6。"""
    module=ast.parse((ROOT/'form'/'form_thermal_compensation.py').read_text('utf-8'))
    cls=next(x for x in module.body if isinstance(x,ast.ClassDef) and x.name=='FormThermalCompensation')
    fn=copy.deepcopy(next(x for x in cls.body if isinstance(x,ast.FunctionDef) and x.name==name))
    compiled=compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<thermal-method>','exec')
    ns=dict(globals_)
    exec(compiled,ns)
    return ns[name]


class DummyFunc:
    def __init__(self):self.calls=[];self.argtypes=None;self.restype=None
    def __call__(self,*args):self.calls.append(args);return 0


class MultiRateTests(unittest.TestCase):
    def test_fit_verify_rates_and_original_ambient_unchanged(self):
        ambient=load_profile(str(ROOT))
        ambient_copy=copy.deepcopy(ambient)
        warm=configure_thermal_gyro_profile(copy.deepcopy(ambient))
        self.assertEqual(ambient,ambient_copy)
        self.assertEqual(ambient['rates']['fit_dps'],[1.,2.,5.])
        self.assertEqual(warm['rates']['fit_dps'],list(FIT_RATES_DPS))
        self.assertEqual(warm['rates']['verify_dps'],list(VERIFY_RATES_DPS))
        f=[x for x in gyro_fit_steps(warm) if x['mode']=='rate']
        v=[x for x in gyro_verify_steps(warm) if x['mode']=='rate']
        self.assertEqual(len(f),30)
        self.assertEqual(len(v),30)
        self.assertEqual(len(acc_fit_steps()+acc_verify_steps())+len(f)+len(v)+2,86)
        for x in f+v:self.assertTrue(-60<=x['target_rate_dps']<=60)
        self.assertEqual({abs(x['target_rate_dps']) for x in f},set(FIT_RATES_DPS))
        self.assertEqual({abs(x['target_rate_dps']) for x in v},set(VERIFY_RATES_DPS))

    def test_sign_acceleration_and_limits(self):
        self.assertEqual(wk_signed_velocity(+60,30,'inner'),(0,30,60))
        self.assertEqual(wk_signed_velocity(-60,30,'inner'),(1,30,60))
        self.assertEqual(wk_signed_velocity(-45,30,'outer'),(1,30,45))
        for bad in (float('nan'),float('inf'),0.0):
            with self.assertRaises(ValueError):wk_signed_velocity(bad,30,'inner')
        with self.assertRaises(ValueError):wk_signed_velocity(60,50.0,'inner')
        with self.assertRaises(ValueError):wk_signed_velocity(60,80,'outer')
        with self.assertRaises(ValueError):wk_signed_velocity(110,30,'outer')
        self.assertAlmostEqual(signed_wrapped_increment(2,359),3)
        self.assertAlmostEqual(signed_wrapped_increment(359,2),-3)

    def test_high_speed_distance_budget(self):
        dist=conservative_sweep_degrees(60,30,5)
        self.assertEqual(dist,510.0)
        self.assertGreater(dist,360.)
        self.assertLess(dist,540.)

    def test_feedback_watchdog_allows_multirevolution_motion(self):
        table=types.SimpleNamespace(is_turntable_data_available=True, update_count=1,
            last_update_monotonic_ns=time.monotonic_ns(), inner_axis_position=5.0,
            outer_axis_position=0.0, inner_axis_speed=60.0, outer_axis_speed=0.0)
        ns=dict(turntableData=table,time=time,math=math)
        tick=isolated_method('_check_rate_feedback',ns)
        dummy=types.SimpleNamespace(_wk_rate_guard={'axis':'inner',
            'last_feedback_count':1,'started':time.monotonic()})
        # 连续10圈不会因累计角度被停车；每次均有新鲜的编码器数据。
        for i in range(200):
            table.inner_axis_position=(5.0+18*(i+1))%360
            table.update_count+=1
            table.last_update_monotonic_ns=time.monotonic_ns()
            tick(dummy)
        self.assertEqual(dummy._wk_rate_guard['last_feedback_count'],201)
        table.is_turntable_data_available=False
        with self.assertRaisesRegex(ValueError,'反馈陈旧'):
            tick(dummy)

    def test_feedback_watchdog_rejects_bad_speed_and_stale_counter(self):
        table=types.SimpleNamespace(is_turntable_data_available=True,update_count=2,
            last_update_monotonic_ns=time.monotonic_ns(),inner_axis_speed=float('nan'),outer_axis_speed=0.0)
        tick=isolated_method('_check_rate_feedback',dict(turntableData=table,time=time,math=math))
        dummy=types.SimpleNamespace(_wk_rate_guard={'axis':'inner','last_feedback_count':1,'started':time.monotonic()})
        with self.assertRaisesRegex(ValueError,'非有限值'):
            tick(dummy)
        table.inner_axis_speed=10.0
        dummy._wk_rate_guard['last_feedback_count']=2
        dummy._wk_rate_guard['started']=time.monotonic()-1.0
        with self.assertRaisesRegex(ValueError,'反馈未更新'):
            tick(dummy)

    def test_360_limit_removed_from_ui_precheck_and_runtime(self):
        source=(ROOT/'form'/'form_thermal_compensation.py').read_text(encoding='utf-8')
        self.assertNotIn('gyro_sweep_limit',source)
        self.assertNotIn('_check_rate_sweep',source)
        self.assertIn('self._check_rate_feedback()',source)
        self.assertIn('if high_speed and not self.check_highspeed.isChecked()',source)
        self.assertIn("max_wait=8.0 if abs(ref)>=30 else 12.0",source)
        class MessageBox:
            shown=[]
            @classmethod
            def information(cls,*args):cls.shown.append(args)
            @classmethod
            def warning(cls,*args):raise AssertionError('预检查不应该报错：'+str(args))
        preview=isolated_method('_preview_preflight',dict(QMessageBox=MessageBox,
            FIT_RATES_DPS=FIT_RATES_DPS,VERIFY_RATES_DPS=VERIFY_RATES_DPS,
            wk_signed_velocity=wk_signed_velocity,conservative_sweep_degrees=conservative_sweep_degrees))
        fake=types.SimpleNamespace(page=None,dynamic=types.SimpleNamespace(isChecked=lambda:True),
            gyro_accel=types.SimpleNamespace(value=lambda:30),
            sample_seconds=types.SimpleNamespace(value=lambda:5),
            _selected_rates=lambda:(FIT_RATES_DPS,VERIFY_RATES_DPS))
        preview(fake)
        self.assertIn('60°/s',MessageBox.shown[-1][-1])
        self.assertIn('无固定累计角度拦截',MessageBox.shown[-1][-1])

    def test_full_multirate_thermal_fit_uses_five_speeds(self):
        import numpy as np
        from thermal_compensation import build_thermal_model
        profile=configure_thermal_gyro_profile(copy.deepcopy(load_profile(str(ROOT))))
        rows=[]
        for temp in (-20,0,25,45,70):
            group='validate' if temp in (0,45) else 'fit'
            F=np.diag([1.005+(temp-25)*0.00002,0.995-(temp-25)*0.00001,1.015])
            bias=np.array([0.04,-0.03,0.02])+(temp-25)*np.array([0.001,-0.001,0.0005])
            for name, steps in (('fit',gyro_fit_steps(profile)),('validate',gyro_verify_steps(profile))):
                for step in steps:
                    ref=np.zeros(3,dtype=float)
                    if step['mode']=='rate':
                        d={'X':0,'Y':1,'Z':2}[step['step_id'].split('_')[2]]
                        ref[d]=step['target_rate_dps']
                    obs=F@ref+bias
                    rows.append(dict(sensor='gyro',split=name,temperature_split=group,
                        temperature_target_c=temp,temperature_mean_c=temp,
                        reference=ref.tolist(),gyro_raw_mean_dps=obs.tolist()))
        model=build_thermal_model(rows,'gyro',degree=1)
        self.assertEqual(model['temperature_holdout']['count'],2*31)
        self.assertEqual(model['condition_holdout']['count'],3*31)
        self.assertLess(model['temperature_holdout']['vector_rmse'],1e-8)
        self.assertFalse(model['production_release'])

    def test_real_command_signature_no_hardware(self):
        fake_func=DummyFunc()
        dummy_dll=types.SimpleNamespace(SetAxisVelocity=fake_func)
        def get_state(axis,alarm,state,actual,error):
            alarm[0]=0;state[0]=1;actual[0]=90.0;error[0]=0;return True
        wk=types.SimpleNamespace(turntableDll=dummy_dll,axisPorts={0:8,2:9},twoFDT600WK_getAxisStateInfo=get_state)
        table=types.SimpleNamespace(update_count=8)
        comm=types.SimpleNamespace(thread_lock=threading.Lock())
        ns=dict(math=math,ctypes=ctypes,time=time,turntableComm=comm,turntableData=table,
                INNER_ROTATION_AXIS=0,OUTER_ROTATION_AXIS=2,wk_comm=wk,wk_signed_velocity=wk_signed_velocity)
        func=isolated_method('_rate_command',ns)
        dummy=types.SimpleNamespace(task={'phase':'settle'},turntable_form=types.SimpleNamespace(_speed_limit_tripped=False),
                gyro_accel=types.SimpleNamespace(value=lambda:30),_wk_rate_guard=None,_stopped=lambda:True,
                _log=lambda msg:None)
        func(dummy,'inner',+60)
        func(dummy,'inner',-60)
        func(dummy,'outer',-45)
        self.assertEqual(fake_func.calls[0],(8,0,0,30,60.0))
        self.assertEqual(fake_func.calls[1],(8,0,1,30,60.0))
        self.assertEqual(fake_func.calls[2],(9,2,1,30,45.0))
        self.assertEqual(fake_func.argtypes[-2:], [ctypes.c_uint16,ctypes.c_float])
        with self.assertRaises(ValueError):func(dummy,'inner',float('nan'))
        self.assertEqual(len(fake_func.calls),3)

if __name__=='__main__':unittest.main(verbosity=2)
