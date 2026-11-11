# -*- coding: utf-8 -*-
"""No hardware / Qt: regression tests for this version's three requested changes."""
from pathlib import Path
import ast
import sys
import math
import threading
from types import SimpleNamespace
from xml.etree import ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'turntable'))
from motion_speed_guard import target_speed_allowed, sway_peak_speed, feedback_overspeed
assert target_speed_allowed(10)
assert target_speed_allowed(-10)
assert not target_speed_allowed(10.0001)
assert not target_speed_allowed(-11)
assert not target_speed_allowed(0)
assert not target_speed_allowed(float('nan'))
assert not target_speed_allowed(float('inf'))
assert abs(sway_peak_speed(1.0, 1.0)-math.tau)<1e-7
assert sway_peak_speed(2.0,1.0)>10
assert feedback_overspeed(0, -10.01)
assert not feedback_overspeed(10, -9.99)

root=ET.parse(ROOT/'ui/mainWindow.ui').getroot()
tabs={x.attrib['name']:x for x in root.findall('.//widget') if x.attrib.get('name') in ('tab_27','tab_30')}
for name in ('groupBox_InnerSstate','groupBox_OutState','groupBox_2','groupBox_3','groupBox_AllRationController'):
    assert tabs['tab_27'].find(f'./widget[@name="{name}"]') is not None, name
for name in ('groupBox_15','groupBox_16','groupBox_17','groupBox_18'):
    assert tabs['tab_30'].find(f'./widget[@name="{name}"]') is not None, name
# Every controller button should still appear once in UI XML.
for name in ('pushButton_InnerRun','pushButton_OutterRun','pushButton_AllRun','pushButton_AllStop','pushButton_InnerRunForSpeedMode','pushButton_OuterRunForSwayMode','pushButton_InnerReturnZero'):
    assert len(root.findall(f'.//widget[@name="{name}"]'))==1,name

# Execute only the chamber disconnect button logic against mocks, with no Qt/PLC hardware.
code=ast.parse((ROOT/'form/form_tc.py').read_text(encoding='utf8'))
cls=next(n for n in code.body if isinstance(n,ast.ClassDef) and n.name=='FormTc')
fn=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='pushButton_ConnectTC_Click')
small=ast.fix_missing_locations(ast.Module(body=[ast.ClassDef(name='MockFormTc',bases=[],keywords=[],decorator_list=[],body=[fn])],type_ignores=[]))
class El:
    def __init__(self,label=''):
        self.label=label
    def text(self):return self.label
    def setText(self,v):self.label=v
    def setEnabled(self,*a):pass
    def stop(self):pass
class ThreadAware:
    def __init__(self):
        self.is_connected=True;self.is_comm_error=False;self.thread_instance=None;self.thread_lock=threading.Lock();self.terminate_thread_requst=False
class Popups:
    failures=[]
    @staticmethod
    def showerror(*a):Popups.failures.append(a)
    @staticmethod
    def showwarning(*a):Popups.failures.append(a)
tc=ThreadAware(); data=SimpleNamespace(is_tc_data_available=True)
disconnected=[]
ns=dict(tcComm=tc,tcData=data,OFFLINE_DEBUG=False,tc_connect_state_get=lambda:True,
        tc_fixed_value_state_get=lambda:False,tc_run_state_get=lambda:False,
        tc_disconnect=lambda:disconnected.append(1),messagebox=Popups,threading=threading,
        tc_connect=lambda x:True,thread_of_tc_data_get_create_and_start=lambda:None)
exec(compile(small,str(ROOT/'form/form_tc.py'),'exec'),ns)
form=ns['MockFormTc']()
form.lineEdit_ip=El('192.168.0.10');form.pushButton_ConnectTC=El('断开')
for n in ('lineEdit_UltraHighTemperature','lineEdit_UltraLowTemperature','checkBox_fixedValueRateOnOff','lineEdit_fixedValueRate','timer_TemperatureDisplay','timer_TcStateDisplay','timer_TcFaultMonitor'):
    setattr(form,n,El())
form.all_pushbutton_setEnabled=lambda *a:None
form.all_signal_button_restore_default_state=lambda:None
form.pushButton_ConnectTC_Click()
assert disconnected and not tc.is_connected and not data.is_tc_data_available
assert form.pushButton_ConnectTC.text()=='连接'
assert not Popups.failures
# Still running: must reject software disconnection.
tc.is_connected=True
form.pushButton_ConnectTC.setText('断开')
ns['tc_fixed_value_state_get']=lambda:True
form.pushButton_ConnectTC_Click()
assert tc.is_connected
assert len(disconnected)==1
assert Popups.failures
print('PASS: 转台首屏控制、目标速度和摇摆限幅、温箱断开同步及运行中拦截')
