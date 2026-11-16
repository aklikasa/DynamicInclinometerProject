# -*- coding: utf-8 -*-
"""静态回归核对：不连接设备、不启动转台、无需 PySide6。"""
from __future__ import annotations
import ast
import re
import sys
import py_compile
from pathlib import Path
from xml.etree import ElementTree as ET

BASE = Path(__file__).resolve().parents[1]
ui_file = BASE / 'ui' / 'mainWindow.ui'
root = ET.parse(ui_file).getroot()
widgets = list(root.iter('widget'))
widget_names = {w.get('name') for w in widgets}
assert len([w for w in widgets if w.get('name') == 'mainWindow']) == 1
assert root.find('./widget/property[@name="geometry"]/rect/width').text == '1144'
assert root.find('./widget/property[@name="geometry"]/rect/height').text == '723'
assert {'tab_AccData', 'tab_DataRecord', 'tabWidget_CalMain',
        'pushButton_DataRecordStart', 'pushButton_AccDataSaveDirectorySelect'} <= widget_names
assert 'pushButton_DataRecordPause' not in widget_names
assert 'pushButton_AccDataRecorded' not in widget_names
assert 'setUpBox' not in widget_names
assert 'SpinBox_ArrSetting' not in widget_names
assert 'lineEdit_segmentNum' not in widget_names
assert 'tabWidget_Manual_2' not in widget_names
assert all(name not in widget_names for name in ('tab_CalCalcu', 'tab_AccTdc', 'tab_3', 'tab_26'))

for source in (BASE / 'form').glob('*.py'):
    py_compile.compile(str(source), doraise=True)
py_compile.compile(str(BASE / 'main.py'), doraise=True)

for source in [BASE / 'form' / name for name in ('form_tilt_sensor_cal.py',
                 'form_turntable_ctrl.py', 'form_tc.py')] + [BASE / 'main.py']:
    src = source.read_text(encoding='utf-8-sig')
    ui_refs = set(re.findall(r'\bui\.([A-Za-z_]\w*)', src))
    methods = {'show', 'setFixedSize', 'setWindowFlags', 'windowFlags', 'width', 'height'}
    missing = ui_refs - widget_names - methods
    assert not missing, f'{source.name} 引用了缺失的控件: {sorted(missing)}'

# 从源代码提取槽函数，在模拟按钮/CSV 状态上执行切换单元测试，避免依赖硬件或 Qt。
class _Style:
    def unpolish(self, button): pass
    def polish(self, button): pass

class _Button:
    def __init__(self): self.label='开始记录'; self.props={'recording':False}
    def text(self): return self.label
    def setText(self, text): self.label=text
    def property(self, key): return self.props.get(key)
    def setProperty(self, key, value): self.props[key]=value
    def style(self): return _Style()
    def update(self): pass


def extract_method(filename, class_name, method):
    tree=ast.parse((BASE/'form'/filename).read_text(encoding='utf-8-sig'))
    obj=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name==class_name)
    item=next(n for n in obj.body if isinstance(n,ast.FunctionDef) and n.name==method)
    module=ast.fix_missing_locations(ast.Module(body=[item],type_ignores=[]))
    scope={}
    exec(compile(module,filename,'exec'),scope)
    return scope[method]

legacy = {
    'toggle': extract_method('form_tilt_sensor_cal.py', 'FormTiltSensorCal', 'pushButton_DataRecordToggle_Click'),
    'sync': extract_method('form_tilt_sensor_cal.py', 'FormTiltSensorCal', '_sync_record_button'),
}
state={'active':False}
legacy['toggle'].__globals__['csv_is_enabled']=lambda:state['active']
legacy['sync'].__globals__['csv_is_enabled']=lambda:state['active']
class _DataRecorder:
    def __init__(self):
        self.pushButton_DataRecordStart=_Button()
        self._sync_record_button=lambda:legacy['sync'](self)
    def pushButton_DataRecordStart_Click(self):state['active']=True
    def pushButton_DataRecordPause_Click(self):state['active']=False
rec=_DataRecorder()
for expected in (True,False,True,False):
    legacy['toggle'](rec)
    assert state['active']==expected
    assert rec.pushButton_DataRecordStart.text()==('停止记录' if expected else '开始记录')
    assert rec.pushButton_DataRecordStart.property('recording')==expected

im_sync=extract_method('form_imu_calibration.py', 'FormImuCalibration', '_sync_imu_record_button')
im_toggle=extract_method('form_imu_calibration.py', 'FormImuCalibration', '_toggle_recording')
class _ImuRecorder:
    def __init__(self):
        self.recording=False
        self.button_record_start=_Button()
        self._sync_imu_record_button=lambda:im_sync(self)
    def _start_recording(self):self.recording=True
    def _stop_recording(self):self.recording=False
rec2=_ImuRecorder()
for expected in (True,False,True,False):
    im_toggle(rec2)
    assert rec2.recording==expected
    assert rec2.button_record_start.text()==('停止记录' if expected else '开始记录')
    assert rec2.button_record_start.property('recording')==expected

print('PASS: Qt .ui XML / 窗口尺寸 / 控件引用 / 源码语法 / 两个记录按钮状态机')
print('NOTE: 这是无设备的静态与模拟检查，不能代替 Windows 上的 PySide6 界面运行和转台联调。')
