# -*- coding: utf-8 -*-
"""Static wiring/plan test, works on non-Windows without PySide6 or vendor DLL."""
import ast
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from production_calibration import load_profile,acc_fit_steps,acc_verify_steps,gyro_fit_steps,gyro_verify_steps
page=ast.parse((ROOT/'form'/'form_thermal_compensation.py').read_text(encoding='utf-8'))
cls=next(n for n in page.body if isinstance(n,ast.ClassDef) and n.name=='FormThermalCompensation')
methods={n.name:n for n in cls.body if isinstance(n,ast.FunctionDef)}
for name in ('start','_tick','_confirm_temperature','_collect','_frame_sample','_stop_axes',
             '_save_partial','_finish','_abort','shutdown','_move','_rate_command'):
    assert name in methods, f'温补自动任务函数缺失：{name}'
source=(ROOT/'main.py').read_text(encoding='utf-8')
assert 'FormThermalCompensation(ui, form_turntable_ctrl, form_imu_calibration)' in source
assert 'app.aboutToQuit.connect(form_thermal.shutdown)' in source
assert 'form_thermal_compensation import FormThermalCompensation' in source
plan=methods['_steps']
ns={'acc_fit_steps':acc_fit_steps,'acc_verify_steps':acc_verify_steps,
    'gyro_fit_steps':gyro_fit_steps,'gyro_verify_steps':gyro_verify_steps}
exec(compile(ast.fix_missing_locations(ast.Module(body=[plan],type_ignores=[])),str(ROOT/'form'/'form_thermal_compensation.py'),'exec'),ns)
profile=load_profile(str(ROOT))
steps=ns['_steps'](True,profile)
assert len(steps)==56,(len(steps),'预期ACC 24 + GYRO零速2 + GYRO动态30')
assert len([x for x in steps if x['sensor']=='acc'])==24
assert len([x for x in steps if x['sensor']=='gyro' and x['mode']=='rate'])==30
assert len(ns['_steps'](False,profile))==26
comm=(ROOT/'turntable'/'turntable_data_get.py').read_text(encoding='utf-8-sig')
section=comm.split('def thread_func_of_turntable_2FDT600WK_data_get():',1)[1]
assert 'turntableData.inner_axis_speed = delta(' in section
assert 'turntableData.outer_axis_speed = delta(' in section
print('PASS: 页面注册、停止/异常/采样功能、56工况/26工况与2FDT编码器测速静态检查')
