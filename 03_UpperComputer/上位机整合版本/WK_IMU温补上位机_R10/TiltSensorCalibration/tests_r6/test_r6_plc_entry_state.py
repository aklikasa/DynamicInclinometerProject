# -*- coding: utf-8 -*-
"""Offline deterministic test exercising the real _tick implementation via AST.
Hardware APIs are stubbed. No PLC/WK communication occurs.
"""
import ast
import sys
import time
import unittest
from pathlib import Path
from threading import Lock
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from chamber_auto_guard import require_setpoint_ack, ChamberSafetyError
p=ROOT/'form/form_thermal_compensation.py'
tree=ast.parse(p.read_text('utf8'))
cls=next(a for a in tree.body if isinstance(a,ast.ClassDef) and a.name=='FormThermalCompensation')
tick=next(a for a in cls.body if isinstance(a,ast.FunctionDef) and a.name=='_tick')
model=ast.ClassDef(name='CoreTick',bases=[],keywords=[],decorator_list=[],body=[tick])
imu=SimpleNamespace(data_lock=Lock(),data_update_count=1,acc_fs=8,gyro_fs=250,data_odr=208)
ns=dict(time=time, tilt_sensor_calibration_queue_drop_count_get=lambda:0,
        tiltSensorRawData=imu, require_setpoint_ack=require_setpoint_ack,
        ChamberSafetyError=ChamberSafetyError)
exec(compile(ast.fix_missing_locations(ast.Module(body=[model],type_ignores=[])),str(p),'exec'),ns)
class Label:
    def __init__(self):self.text=''
    def setText(self,v):self.text=str(v)
    def setValue(self,v):pass
    def setEnabled(self,v):pass

class Fake(ns['CoreTick']):
    def __init__(self):
        now=time.monotonic()
        self.pv=25.0;self.sp=25.0;self.sent=[];self.saved=[];self.aborted=None;self.motor_commands=0
        self.label=Label();self.progress=Label();self.plc_telemetry=Label();self.confirm_temp=Label()
        self.task=dict(manual=False,temps=[-40.0],temp_i=0,steps=[dict(step_id='ACC_FIT_01')],
            steps_by_temperature=[[dict(step_id='ACC_FIT_01')]],temperature_quality_mode='strict',
            step_i=0, phase='next_temperature',phase_start=now-1,return_ambient=False,
            last_imu_count=1,last_imu_change=now,baseline_config=(8,250,208),
            chip_stability_only=False,temperature_wait_started=None,rows=[],ui_max_progress=0,
            startup_arrival_checked=False, auto_arrival_enabled=True,
            auto_arrival_step_c=5.0,auto_arrival_band_c=1.0,auto_arrival_timeout_minutes=60,
            auto_arrival_stages=[],auto_arrival_stage_i=0)
    def _step_key(self, ti,si): return (self.task['temps'][ti],self.task['steps_by_temperature'][ti][si]['step_id'])
    def _accepted_step_keys(self):return set()
    def _motion_status(self):pass
    def _collect(self):pass
    def _stopped(self):return True
    def _log(self,txt):pass
    def _save_partial(self,status,msg):self.saved.append((status,msg))
    def _issue_plc_setpoint(self,sp):self.sp=float(sp);self.sent.append(self.sp)
    def _require_plc(self,now):
        return dict(pv=self.pv,sp=self.sp,pv_updated=time.monotonic(),
                    fixed_mode=True,fixed_started=True,running=True,alarm=0)
    def _abort(self,msg):self.aborted=msg;raise RuntimeError(msg)

class StateTests(unittest.TestCase):
    def test_first_temp_auto_prestages_and_no_motor_movement(self):
        f=Fake();f._tick()
        self.assertEqual(f.sent,[20.0]);self.assertEqual(f.task['phase'],'verify_auto_arrival_sp')
        for _ in range(12):
            f._tick();self.assertEqual(f.task['phase'],'wait_auto_arrival_pv')
            f.pv=f.sp;f.task['auto_arrival_reached_since']=time.monotonic()-6
            f._tick()
        self.assertEqual(f.task['phase'],'verify_plc_sp')
        self.assertEqual(f.sp,-40.)
        self.assertEqual(len(f.sent),13) # 12 intermediate SP + final SP
        f._tick();self.assertEqual(f.task['phase'],'wait_plc')
        self.assertEqual(f.motor_commands,0)
    def test_no_run_if_current_sp_not_acknowledged(self):
        f=Fake();f._tick()
        f.sp=8.0
        f.task['phase_start']=time.monotonic()-91
        with self.assertRaises(RuntimeError):f._tick()
        self.assertIn('自动温补中止',f.aborted)
        self.assertEqual(f.motor_commands,0)

if __name__=='__main__':unittest.main()
