# -*- coding: utf-8 -*-
"""Exercise the automatic PLC temperature progression without hardware or PySide6."""
import ast
import sys
import time
from pathlib import Path
from threading import Lock
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from chamber_auto_guard import require_setpoint_ack, ChamberSafetyError

source=ROOT/'form/form_thermal_compensation.py'
tree=ast.parse(source.read_text(encoding='utf-8'))
cls=next(x for x in tree.body if isinstance(x,ast.ClassDef) and x.name=='FormThermalCompensation')
method=next(x for x in cls.body if isinstance(x,ast.FunctionDef) and x.name=='_tick')
min_cls=ast.ClassDef(name='StateMachine',bases=[],keywords=[],decorator_list=[],body=[method])
sim=SimpleNamespace(data_lock=Lock(),data_update_count=1,acc_fs=8,gyro_fs=250,data_odr=208)
ns={'time':time,'tilt_sensor_calibration_queue_drop_count_get':lambda:0,
    'tiltSensorRawData':sim,'require_setpoint_ack':require_setpoint_ack,
    'ChamberSafetyError':ChamberSafetyError,
    'tcState':SimpleNamespace(is_device_fault=False),
    'tcData':SimpleNamespace(is_tc_data_available=True),
    'tcComm':SimpleNamespace(is_connected=True)}
exec(compile(ast.fix_missing_locations(ast.Module(body=[min_cls],type_ignores=[])),str(source),'exec'),ns)

class Recorder:
    def __init__(self):self.latest='';self.n=0
    def setText(self,text):self.latest=text;self.n+=1
    def setValue(self,num):self.latest=str(num);self.n+=1
    def setEnabled(self,value):self.latest=str(value);self.n+=1

class Fake(ns['StateMachine']):
    def __init__(self):
        self.plc_sp=25.;self.plc_pv=25.;self.sent=[];self.events=[]
        self.label=Recorder();self.progress=Recorder();self.plc_telemetry=Recorder();self.confirm_temp=Recorder()
        self.dwell=SimpleNamespace(value=lambda:1800)
        self.task={'manual':False,'temps':[-20,0,25,45,70],'temp_i':0,
                   'return_ambient':True,'phase':'next_temperature',
                   'phase_start':time.monotonic()-1,'last_imu_count':1,
                   'last_imu_change':time.monotonic(),'baseline_config':(8,250,208),
                   'steps':[{'mode':'static'}],'step_i':0,'chip_trace':[],
                   'pv_stable_since':None}
        self.finished=None;self.aborted=None
    def _motion_status(self):pass
    def _collect(self):pass
    def _stopped(self):return True
    def _log(self,msg):self.events.append(msg)
    def _abort(self,msg):self.aborted=msg;raise RuntimeError(msg)
    def _finish(self,success,reason):self.finished=(success,reason)
    def _issue_plc_setpoint(self,target):self.sent.append(target);self.plc_sp=target
    def _require_plc(self,now):
        return {'pv':self.plc_pv,'sp':self.plc_sp,'fixed_mode':True,
                'fixed_started':True,'running':True,'alarm':0}

f=Fake()
f._tick();assert f.sent==[-20] and f.task['phase']=='verify_plc_sp'
f._tick();assert f.task['phase']=='wait_plc'
f.plc_pv=-20.
f._tick();assert f.task['phase']=='wait_plc'
f.task['pv_stable_since']=time.monotonic()-31
f._tick();assert f.task['phase']=='thermal_stability'
# Simulate completion: automatically return to 25, ACK readback and check PV.
f.task['temp_i']=len(f.task['temps']);f.task['phase']='next_temperature';f.plc_pv=70
f._tick();assert f.sent==[-20,25.] and f.task['phase']=='verify_return'
f._tick();assert f.task['phase']=='wait_return'
f.plc_pv=25
f._tick();assert f.finished is None
f.task['pv_stable_since']=time.monotonic()-31
f._tick();assert f.finished and f.finished[0]
# Fail-closed on SP discrepancy after verification.
f2=Fake();f2.task['phase']='thermal_stability';f2.plc_sp=40
try:f2._tick()
except RuntimeError as ex:assert '设定值回读不一致' in str(ex)
else:raise AssertionError('SP 被外部篡改必须中止温补')
print('PASS: PLC自动设温→SP确认→PV稳定→结束回25℃；SP被外部篡改触发中止')
