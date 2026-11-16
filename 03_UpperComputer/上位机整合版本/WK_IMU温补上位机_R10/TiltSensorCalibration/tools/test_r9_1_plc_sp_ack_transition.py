# -*- coding: utf-8 -*-
"""Hardware-free regression of R9.1 missing SP acknowledgement state.

Run with: python -m unittest tools.test_r9_1_plc_sp_ack_transition -v
"""
import ast
import time
import unittest
from pathlib import Path
from threading import Lock
from types import SimpleNamespace
from chamber_auto_guard import ChamberSafetyError, require_setpoint_ack

ROOT=Path(__file__).resolve().parents[1]
source=ROOT/'form/form_thermal_compensation.py'
tree=ast.parse(source.read_text(encoding='utf-8'))
cls=next(x for x in tree.body if isinstance(x,ast.ClassDef) and x.name=='FormThermalCompensation')
fn=next(x for x in cls.body if isinstance(x,ast.FunctionDef) and x.name=='_tick')
mod=ast.Module(body=[ast.ClassDef(name='Tick',bases=[],keywords=[],decorator_list=[],body=[fn])],type_ignores=[])
ast.fix_missing_locations(mod)
imu=SimpleNamespace(data_lock=Lock(),data_update_count=1,acc_fs=8,gyro_fs=250,data_odr=208)
ns={'time':time,'tiltSensorRawData':imu,'tilt_sensor_calibration_queue_drop_count_get':lambda:0,
    'require_setpoint_ack':require_setpoint_ack,'ChamberSafetyError':ChamberSafetyError}
exec(compile(mod,str(source),'exec'),ns)

class UI:
    def __init__(self): self.text=''
    def setText(self,value):self.text=str(value)
    def setValue(self,value):self.text=str(value)
    def setEnabled(self,value):self.text=str(value)

class Fixture(ns['Tick']):
    def __init__(self):
        now=time.monotonic()
        self.plc_sp=-20.0;self.plc_pv=-19.5;self.running=True;self.started=True;self.mode=True
        self.updates=now+0.01;self.log=[];self.aborted=None;self.moves=0
        self.label=UI();self.plc_telemetry=UI();self.progress=UI();self.confirm_temp=UI()
        self.task={'manual':False,'phase':'verify_plc_sp','phase_start':now-2,
                   'plc_setpoint_command_time':now-1,'temps':[-20.0], 'temp_i':0,
                   'steps':[{'step_id':'ACC_01'}],'step_i':0,
                   'last_imu_count':1,'last_imu_change':now,'baseline_config':(8,250,208),
                   'chip_stability_only':False,'pv_initial_trace':[], 'return_ambient':False,
                   'temperature_quality_mode':'production_adaptive','rows':[], 'ui_max_progress':0}
    def _motion_status(self):pass
    def _collect(self):pass
    def _stopped(self):return True
    def _log(self,m):self.log.append(m)
    def _abort(self,msg):self.aborted=msg;raise RuntimeError(msg)
    def _require_plc(self,now):
        return {'pv':self.plc_pv,'sp':self.plc_sp,'pv_updated':time.monotonic(),
                'sp_updated':self.updates,'mode_updated':self.updates,
                'started_updated':self.updates,'run_updated':self.updates,
                'fixed_mode':self.mode,'fixed_started':self.started,
                'running':self.running,'alarm':0}

class TestPLCStartAck(unittest.TestCase):
    def test_valid_ack_moves_to_temperature_observation(self):
        f=Fixture();f._tick()
        self.assertEqual(f.task['phase'],'wait_plc')
        self.assertIn('PLC设温确认成功', ''.join(f.log))
        self.assertIsNotNone(f.task['temperature_wait_started'])
        self.assertEqual(f.moves,0)
    def test_matching_temperature_without_sp_ack_must_not_start(self):
        f=Fixture();f.plc_sp=20.0;f._tick()
        self.assertEqual(f.task['phase'],'verify_plc_sp')
        self.assertIn('回读不一致',f.label.text)
        self.assertEqual(f.moves,0)
    def test_running_false_must_not_start(self):
        f=Fixture();f.started=False;f.running=False;f._tick()
        self.assertEqual(f.task['phase'],'verify_plc_sp')
        self.assertIn('运行状态',f.label.text)
    def test_cached_plc_feedback_must_not_start(self):
        f=Fixture();f.updates=f.task['plc_setpoint_command_time']-0.01;f._tick()
        self.assertEqual(f.task['phase'],'verify_plc_sp')
        self.assertIn('新鲜反馈',f.label.text)
    def test_ack_timeout_aborts_instead_of_waiting_forever(self):
        f=Fixture();f.plc_sp=20.0;f.task['phase_start']=time.monotonic()-91
        with self.assertRaisesRegex(RuntimeError,'90秒'):
            f._tick()
        self.assertIn('回读',f.aborted)

if __name__=='__main__':unittest.main()
