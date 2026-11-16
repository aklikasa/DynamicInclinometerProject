# -*- coding: utf-8 -*-
"""分阶段温箱热平衡状态机测试：初步PV→共同热浸→最终PV+芯片稳定。"""
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
from thermal_chamber_stability import chamber_stability_status, chamber_band_status

SOURCE=ROOT/'form'/'form_thermal_compensation.py'
tree=ast.parse(SOURCE.read_text(encoding='utf-8'))
cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='FormThermalCompensation')
tick=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='_tick')

class Clock:
    now=0.0
    def monotonic(self): return self.now
clock=Clock()
imu=types.SimpleNamespace(data_lock=Lock(),data_update_count=0,acc_fs=8,gyro_fs=250,
                          data_odr=208,temp_c=25.0)
ns={'time':clock,'math':math,'tilt_sensor_calibration_queue_drop_count_get':lambda:0,
    'tiltSensorRawData':imu,'tcState':types.SimpleNamespace(is_device_fault=False),
    'tcData':types.SimpleNamespace(is_tc_data_available=True),
    'tcComm':types.SimpleNamespace(is_connected=True),
    'require_setpoint_ack':lambda snapshot,target:None,
    'chip_stability_status':chip_stability_status,
    'chamber_stability_status':chamber_stability_status,
    'chamber_band_status':chamber_band_status}
runner=ast.ClassDef(name='Runner',bases=[],keywords=[],decorator_list=[],body=[tick])
exec(compile(ast.fix_missing_locations(ast.Module(body=[runner],type_ignores=[])),str(SOURCE),'exec'),ns)

class Reporter:
    def __init__(self): self.text=''; self.value=None
    def setText(self,value): self.text=str(value)
    def setValue(self,value): self.value=value

class Fake(ns['Runner']):
    def __init__(self):
        self.label=Reporter();self.progress=Reporter();self.plc_telemetry=Reporter()
        self.logs=[];self.pv=25.0
        self.dwell=types.SimpleNamespace(value=lambda:1800)
        self.task={'manual':False,'phase':'wait_plc','phase_start':0.0,
            'temperature_wait_started':0.0,'temps':[25.0],'temp_i':0,'step_i':0,
            'steps':[{'mode':'static','step_id':'S1'}],'return_ambient':False,
            'chip_stability_only':False,'pv_initial_seconds':300,
            'pv_initial_range_c':0.3,'pv_initial_slope_c_per_min':0.05,
            'pv_final_tolerance_c':0.1,'pv_final_seconds':300,
            'pv_initial_trace':[],'pv_initial_since':None,'pv_initial_last_update':None,
            'pv_final_trace':[],'pv_final_last_update':None,
            'thermal_elapsed_s':0.0,'thermal_last_tick':None,'thermal_pv_in_range':False,
            'chip_trace':[],'last_chip_trace_count':None,
            'baseline_config':(8,250,208),'last_imu_count':0,'last_imu_change':0.0,
            'resume_temp_index':None,'resume_step_index':0}
    def _motion_status(self): pass
    def _collect(self): pass
    def _stopped(self): return True
    def _log(self,message): self.logs.append(str(message))
    def _require_plc(self,now):
        return {'pv':self.pv,'sp':25.0,'pv_updated':now,'fixed_mode':True,
                'fixed_started':True,'running':True,'alarm':0}
    def _abort(self,message): raise AssertionError(message)

class StagedTemperatureStateMachineTests(unittest.TestCase):
    def setUp(self):
        clock.now=0.0;imu.data_update_count=0;imu.temp_c=25.0
        self.f=Fake()
    def tick_at(self,sec,pv=25.0):
        clock.now=float(sec);self.f.pv=float(pv)
        imu.data_update_count+=1
        self.f._tick()
    def test_initial_gate_needs_full_five_minute_stable_window(self):
        for sec in range(0,31): self.tick_at(sec)
        self.assertEqual(self.f.task['phase'],'wait_plc')
        for sec in range(31,301): self.tick_at(sec)
        self.assertEqual(self.f.task['phase'],'thermal_soak')
        self.assertAlmostEqual(self.f.task['thermal_elapsed_s'],0.0)
    def test_heat_soak_counts_only_while_pv_within_plus_minus_one(self):
        for sec in range(0,301): self.tick_at(sec)
        self.tick_at(301,25.0)
        before=self.f.task['thermal_elapsed_s']
        for sec in range(302,307): self.tick_at(sec,26.5)
        self.assertAlmostEqual(self.f.task['thermal_elapsed_s'],before)
        self.tick_at(307,25.0)  # first recovered tick restarts accumulation, does not backfill the gap
        self.assertAlmostEqual(self.f.task['thermal_elapsed_s'],before)
        self.tick_at(308,25.0)
        self.assertGreater(self.f.task['thermal_elapsed_s'],before)
    def test_full_formal_gate_reaches_position_only_after_soak_and_final_checks(self):
        for sec in range(0,301): self.tick_at(sec)
        self.assertEqual(self.f.task['phase'],'thermal_soak')
        for sec in range(301,2101): self.tick_at(sec)
        self.assertEqual(self.f.task['phase'],'final_stability')
        for sec in range(2101,2401):
            self.tick_at(sec,24.9 if sec%2 else 25.1)
            if self.f.task['phase']=='position': break
        self.assertEqual(self.f.task['phase'],'position')
        self.assertTrue(any('正式温度门槛全部通过' in msg for msg in self.f.logs))
    def test_final_pv_excursion_over_one_degree_restarts_soak(self):
        for sec in range(0,301): self.tick_at(sec)
        for sec in range(301,2101): self.tick_at(sec)
        self.assertEqual(self.f.task['phase'],'final_stability')
        self.tick_at(2101,27.0)
        self.assertEqual(self.f.task['phase'],'thermal_soak')
        self.assertEqual(self.f.task['thermal_elapsed_s'],0.0)

    def test_task_config_keys_match_staged_gate_runtime_consumers(self):
        source = SOURCE.read_text(encoding='utf-8')
        parsed = ast.parse(source)
        task_dict = None
        for node in ast.walk(parsed):
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Attribute) and target.attr == 'task'
                for target in node.targets
            ) and isinstance(node.value, ast.Dict):
                task_dict = node.value
                break
        self.assertIsNotNone(task_dict)
        configured = {
            key.value for key in task_dict.keys
            if isinstance(key, ast.Constant) and isinstance(key.value, str)
        }
        self.assertTrue({
            'pv_initial_range_c',
            'pv_initial_slope_c_per_min',
            'pv_final_tolerance_c',
            'pv_final_seconds',
        }.issubset(configured))
        self.assertFalse({
            'pv_initial_range', 'pv_initial_slope', 'pv_final_tolerance'
        } & configured)

if __name__=='__main__': unittest.main(verbosity=2)
