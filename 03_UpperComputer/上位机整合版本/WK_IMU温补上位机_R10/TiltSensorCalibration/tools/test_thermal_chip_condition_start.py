# -*- coding: utf-8 -*-
"""无硬件温补快速启动判据测试：芯片真实新帧与PLC稳定条件必须同时满足。"""
import ast
import math
import sys
import types
import unittest
from pathlib import Path
from threading import Lock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from thermal_chip_stability import chip_stability_status

class TestPureStability(unittest.TestCase):
    def test_needs_full_window_and_fresh_frames(self):
        obs=[(0.0+i*0.1,25.0+0.02*(i%3)) for i in range(600)]
        ok, seconds, span=chip_stability_status(obs,59.9)
        self.assertTrue(ok)
        self.assertGreater(seconds,55)
        self.assertFalse(chip_stability_status(obs[:100],9.9)[0])
        self.assertFalse(chip_stability_status(obs,65.0)[0])

    def test_drift_or_gap_not_accepted(self):
        drift=[(i*0.1,20+i*0.001) for i in range(600)]
        self.assertFalse(chip_stability_status(drift,59.9)[0])
        gap=[(i*0.1,25) for i in range(100)]+[(15+i*0.1,25) for i in range(450)]
        self.assertFalse(chip_stability_status(gap,59.9)[0])

class Clock:
    def __init__(self):self.now=0.0
    def monotonic(self):return self.now

# AST只取 _tick 函数，确保测试是在运行真实自动状态机分支，不导入Qt或设备DLL。
source=(ROOT/'form/form_thermal_compensation.py').read_text(encoding='utf-8')
tree=ast.parse(source)
cls=next(x for x in tree.body if isinstance(x,ast.ClassDef) and x.name=='FormThermalCompensation')
tick=next(x for x in cls.body if isinstance(x,ast.FunctionDef) and x.name=='_tick')
clock=Clock()
imu=types.SimpleNamespace(data_lock=Lock(),data_update_count=1,acc_fs=8,gyro_fs=250,data_odr=208,temp_c=25.0)
chamber_state=types.SimpleNamespace(is_device_fault=False)
chamber_data=types.SimpleNamespace(is_tc_data_available=True)
chamber_comm=types.SimpleNamespace(is_connected=True)
ns={'math':math,'time':clock,'tilt_sensor_calibration_queue_drop_count_get':lambda:0,
    'tiltSensorRawData':imu,'tcState':chamber_state,'tcData':chamber_data,'tcComm':chamber_comm,
    'chip_stability_status':chip_stability_status,'require_setpoint_ack':lambda status,target:None}
klass=ast.ClassDef(name='Runner',bases=[],keywords=[],decorator_list=[],body=[tick])
exec(compile(ast.fix_missing_locations(ast.Module(body=[klass],type_ignores=[])),str(ROOT/'form/form_thermal_compensation.py'),'exec'),ns)

class Reporter:
    def __init__(self):self.text=''
    def setText(self,t):self.text=t
    def setValue(self,t):self.text=str(t)

class Fake(ns['Runner']):
    def __init__(self,fast):
        self.dwell=types.SimpleNamespace(value=lambda:1800)
        self.label=Reporter()
        self.plc_telemetry=Reporter()
        self.progress=Reporter()
        self.sent=[]
        self.task={'manual':False,'phase':'thermal_stability', 'temps':[25.0],
                   'temp_i':0,'step_i':0,'steps':[{'mode':'static'}],
                   'phase_start':0.0,'chip_trace':[],'last_chip_trace_count':None,
                   'baseline_config':(8,250,208),'last_imu_count':1,
                   'last_imu_change':0.0, 'chip_stability_only':fast,
                   'return_ambient':False}
    def _motion_status(self):pass
    def _collect(self):pass
    def _stopped(self):return True
    def _log(self,s):self.sent.append(s)
    def _require_plc(self,now):
        return {'pv':getattr(self,'pv',25.0),'sp':25.,'running':True,
                'fixed_mode':True,'fixed_started':True,'alarm':0}
    def _abort(self,msg):raise AssertionError(f'abort: {msg}')
    def _move(self,*args):pass

class TestRealStateMachine(unittest.TestCase):
    def setUp(self):
        clock.now=0.0
        imu.data_update_count=1
        imu.temp_c=25.0
        self.fake=Fake(True)

    def run_ticks(self, upto, start=0, dt=.1, temp_func=None):
        n=int((upto-start)/dt)
        for i in range(n+1):
            clock.now=round(start+i*dt,5)
            imu.data_update_count+=1
            imu.temp_c=25 if temp_func is None else temp_func(clock.now)
            self.fake._tick()
            if self.fake.task['phase']=='position':break

    def test_stability_no_1800_seconds(self):
        self.run_ticks(70)
        self.assertEqual(self.fake.task['phase'],'position')
        self.assertLess(clock.now,120)

    def test_less_than_60_seconds_not_enough(self):
        self.run_ticks(52)
        self.assertEqual(self.fake.task['phase'],'thermal_stability')

    def test_original_fixed_dwell_preserved(self):
        self.fake.task['chip_stability_only']=False
        self.run_ticks(90)
        self.assertEqual(self.fake.task['phase'],'thermal_stability')

    def test_nonstationary_chip_does_not_start(self):
        self.run_ticks(100,temp_func=lambda now: 25+0.005*now)
        self.assertEqual(self.fake.task['phase'],'thermal_stability')

    def test_pv_lost_resets_stability(self):
        self.run_ticks(40)
        self.fake.pv=26.5
        clock.now=41.0;imu.data_update_count+=1
        self.fake._tick()
        self.assertEqual(self.fake.task['phase'],'wait_plc')
        self.assertEqual(self.fake.task['chip_trace'],[])

    def test_resume_records_policy(self):
        self.assertIn("'chip_stability_only_60s':True",source)
        self.assertIn("self.chip_stability_only",source)
        self.assertIn("'thermal_stability_mode'",source)

if __name__=='__main__':unittest.main(verbosity=2)
