# -*- coding: utf-8 -*-
"""确认核心模块逐字节一致；温箱线程和连接页为PLC自动温补补强过期PV及IP记录，更新批准哈希。
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

EXPECTED_HASHES = {'main.py': 'f3bd0e9d0ba9f6d7ebc35ae462b43e6e8b73830f4e217fd5c148bbec68c695e7', 'ui/mainWindow.ui': 'ea4026767689ab8f07aee0513d99252d0f6cebafd8e5b4ce23356d2482d89d69', 'form/form_tilt_sensor_cal.py': 'b1811f6882c8c3125b3503fa2bcfc0029ebdade7ac5f240069d30faa9c61d58e', 'form/form_turntable_ctrl.py': 'c5c34dcefb0aafbeaf3556d90a705c9a37f42b77c3d87926d596dc1b76863d7e', 'form/form_tc.py': 'cf59c6167939660ba643f44f5cfee44bdd00d6974bb74dac363c254890062fc7', 'tilt_sensor/tilt_sensor_asm330_data_get.py': 'deb00246b910c5cebc607a229efefaf5e4889a2a32a827cf5087ceee5dbcb81f', 'tilt_sensor/tilt_sensor_asm330_comm.py': '31b6bf1db42d5b27d40b1b50e3d8509799a50935139ee54541a1c54f97ab8ca2', 'turntable/turntable_2TD600_comm.py': 'ae51b945ca665682296b46fa588c2b3dbb4da8b90bfcf104c0b64f3f107ae3a4', 'turntable/turntable_2FDT600WK_comm.py': 'edb3a7e8f93f330e409cf726edf389d7eb5b5dbec9dd3850608ce0aab4136877', 'temperature_chamber/temperature_chamber_data_get.py': '1e73111d4a1ffd9a1ef1fdceb77bafd1d53e7722c5837ff112c0c3e972f4afff', 'tilt_sensor/tilt_sensor_asm330_def.py': 'a71715b4c56732612ab5a380a01cc60d7ebadeecd5c28ef29737177b4801df88', 'tilt_sensor/tilt_sensor_asm330_csv.py': '6b35140188ba2ebbbd3c50ef331e0fcefdcf764ba22553103656f25a69f82842'}
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
