# -*- coding: utf-8 -*-
"""验证已批准的界面位置控制恢复、双轴串口自动检测、速度反馈保护与温箱退出修复版本。
运行：python tools/test_stable_base_regression.py
"""
from pathlib import Path
import hashlib
import ast
import time
import numpy as np
from types import SimpleNamespace
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from production_calibration import load_profile, verify_sensor_config, sensor_config_consistent, frame_average_sanitized

EXPECTED_HASHES = {'main.py': '92828f46578f439872d250b53f554d6a478eed23fade695fc4f51c868d414417', 'ui/mainWindow.ui': '244213d959745f95d5c1eb3f9a042206b9c1efddc2803011508d4de907fc0a65', 'form/form_tilt_sensor_cal.py': 'f498d173e7ca0172a8c822c4cef330b6919268627f63f3f0b0a947299b257757', 'form/form_turntable_ctrl.py': 'b436a1a6d84e5fe8b756e0b01ce1e29876b8715cfa6e08beeffb1a7e0c9e2e2d', 'form/form_tc.py': 'f9f179f25d5ae85fc3f3a6b9699ed0fd426c5f60c00cca28616675f662de4faa', 'tilt_sensor/tilt_sensor_asm330_data_get.py': 'e90fe26295789c2c0cbb4b62bac43692f2a2ff391ea1059f8a22bcc7ce2c439e', 'tilt_sensor/tilt_sensor_asm330_comm.py': '8445476bf34b6581400192d9d648966fa89c65900c05739c0ffa83d82edbab2c', 'turntable/turntable_2TD600_comm.py': 'ae51b945ca665682296b46fa588c2b3dbb4da8b90bfcf104c0b64f3f107ae3a4', 'turntable/turntable_2FDT600WK_comm.py': 'bf69bad4e3b0c94b44deda7029573dc6fce8a05bb34df213288437db26620764', 'temperature_chamber/temperature_chamber_data_get.py': '1e73111d4a1ffd9a1ef1fdceb77bafd1d53e7722c5837ff112c0c3e972f4afff', 'tilt_sensor/tilt_sensor_asm330_def.py': '24feb250dd2da5840c1463b2d4b1ccb59bb7c7e1e355f6f3d2d0413e47e5aaa9', 'tilt_sensor/tilt_sensor_asm330_csv.py': '6b35140188ba2ebbbd3c50ef331e0fcefdcf764ba22553103656f25a69f82842'}
for rel,expected in EXPECTED_HASHES.items():
    actual=hashlib.sha256((ROOT/rel).read_bytes()).hexdigest()
    assert actual==expected, f'稳定旧版核心文件被改动：{rel}'

src=ROOT/'form'/'form_imu_calibration.py'
tree=ast.parse(src.read_text(encoding='utf-8'))
cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='FormImuCalibration')
method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='_capture_auto_task_frame')
small=ast.ClassDef(name='TestForm',bases=[],keywords=[],decorator_list=[],body=[method])
profile=load_profile(ROOT)
now=time.perf_counter_ns()
turntableData=SimpleNamespace(last_update_monotonic_ns=now,inner_axis_position=0.,outer_axis_position=0.,inner_axis_speed=0.,outer_axis_speed=0.)
ns={'np':np,'frame_average_sanitized':frame_average_sanitized,'verify_sensor_config':verify_sensor_config,'sensor_config_consistent':sensor_config_consistent,'turntableData':turntableData,'_now_iso':lambda:'2026-01-01T00:00:00','time':time}
exec(compile(ast.fix_missing_locations(ast.Module(body=[small],type_ignores=[])),str(src),'exec'),ns)
class FrameForm(ns['TestForm']):
    def __init__(self):
        self._auto_task={'type':'accel', 'phase':'sample_static','sample_started':time.monotonic()-1,
                         'quality_profile':profile,'sensor_configuration':verify_sensor_config(profile,{'acc_fs':8,'gyro_fs':250,'acc_fs_ever_valid':True,'gyro_fs_ever_valid':True,'data_odr':208}),
                         'sample_frames':[]}
        self.errors=[]
    def _sensor_reading_snapshot(self):
        return {'acc_fs':8,'gyro_fs':250,'acc_fs_ever_valid':True,'gyro_fs_ever_valid':True,'data_odr':208}
    def _request_auto_abort(self,reason):
        self.errors.append(reason)
    def _log_event(self,*args):
        self.errors.append(str(args))
form=FrameForm()
# The baseline queue intentionally does NOT have *_ever_valid fields; should still work.
frame={'acc_fs':8,'gyro_fs':250,'data_odr':208,'acc_g_arr':[(0.01,0.02,1.0)]*16,
       'gyr_dps_arr':[(0.1,-0.03,0.01)]*16,'temp_c':25.,'monotonic_time_ns':now,'frame_update_count':42}
form._capture_auto_task_frame(frame)
assert not form.errors,form.errors
assert len(form._auto_task['sample_frames'])==1,'标定页未接受旧版格式的有效IMU帧'
assert 'FormThermalCompensation' in (ROOT/'main.py').read_text(encoding='utf-8')
print('PASS: 核心模块批准哈希匹配（含温箱新鲜度改动），IMU数据帧兼容')
