# -*- coding: utf-8 -*-
"""温补瞬时空帧和过期IMU数据判据离线测试；无须PySide6、串口或转台。"""
import ast, copy, math, time, types, threading, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

source=(ROOT/'form/form_thermal_compensation.py').read_text(encoding='utf-8')
tree=ast.parse(source)
cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='FormThermalCompensation')
method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='_valid_device')
method=copy.deepcopy(method)
ns=dict(math=math,time=time)
exec(compile(ast.fix_missing_locations(ast.Module(body=[method],type_ignores=[])), '<imu-empty-frame-test>', 'exec'),ns)

class TestImuTransientFrameGuard(unittest.TestCase):
    def setUp(self):
        self.turntableComm=types.SimpleNamespace(turntable_model='2FDT600WK')
        self.turntableData=types.SimpleNamespace(is_turntable_data_available=True,last_update_time_sec=time.time())
        self.turntableState=types.SimpleNamespace(
            is_inner_axis_in_enable=True,is_outer_axis_in_enable=True,
            is_inner_axis_normal=True,is_outer_axis_normal=True,
            is_inner_axis_over_diff=False,is_outer_axis_over_diff=False,
            is_inner_axis_driver_fault=False,is_outer_axis_driver_fault=False)
        self.tiltSensorComm=types.SimpleNamespace(is_serial_opened=True,is_data_available=False,
                                                  last_success_time_sec=time.time())
        self.tiltSensorRawData=types.SimpleNamespace(data_lock=threading.Lock(),is_data_valid=False,data_update_count=25)
        self.fake=types.SimpleNamespace(ambient_form=types.SimpleNamespace(_auto_task=None,recording=False))
        ns.update(turntableComm=self.turntableComm,turntableData=self.turntableData,
                  turntableState=self.turntableState,tiltSensorComm=self.tiltSensorComm,
                  tiltSensorRawData=self.tiltSensorRawData)
        exec(compile(ast.fix_missing_locations(ast.Module(body=[copy.deepcopy(method)],type_ignores=[])),
                     '<imu-empty-frame-test>', 'exec'),ns)
        self.check=ns['_valid_device']

    def test_transient_empty_frame_does_not_abort(self):
        # A just-received blank frame toggles the instantaneous validity flag.
        self.tiltSensorRawData.is_data_valid=False
        self.tiltSensorComm.is_data_available=False
        self.check(self.fake)

    def test_recent_valid_frame_is_accepted(self):
        self.tiltSensorComm.last_success_time_sec=time.time()-3.0
        self.check(self.fake)

    def test_stale_data_aborts_after_five_seconds(self):
        self.tiltSensorComm.last_success_time_sec=time.time()-5.2
        with self.assertRaisesRegex(ValueError,'超过5秒'):
            self.check(self.fake)

    def test_no_real_sample_aborts(self):
        self.tiltSensorRawData.data_update_count=0
        with self.assertRaisesRegex(ValueError,'有效'):
            self.check(self.fake)

    def test_serial_closed_aborts(self):
        self.tiltSensorComm.is_serial_opened=False
        with self.assertRaisesRegex(ValueError,'串口未连接'):
            self.check(self.fake)

    def test_turntable_fault_still_aborts(self):
        self.turntableState.is_outer_axis_driver_fault=True
        with self.assertRaisesRegex(ValueError,'驱动故障'):
            self.check(self.fake)

    def test_thermal_trace_appends_only_on_new_frame(self):
        code=source
        self.assertIn("if chip_frame_count != t.get('last_chip_trace_count'):",code)
        self.assertIn("t['last_chip_trace_count']=chip_frame_count",code)
        self.assertIn("t['last_chip_trace_count']=None",code)

if __name__=='__main__':unittest.main(verbosity=2)
