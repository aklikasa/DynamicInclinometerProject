"""No-hardware regression check for Qt dialogs and turntable homing action.

Usage: python tools/test_qt_homing_patch.py
No PySide6 installation needed: dialog API is mocked for the test.
"""
from pathlib import Path
from contextlib import contextmanager
import ast
import sys
import types
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
ctrl_file = ROOT / 'form' / 'form_turntable_ctrl.py'
source = ctrl_file.read_text(encoding='utf-8-sig')
assert 'from qt_dialogs import filedialog, messagebox' in source
assert 'from tkinter import' not in source

# Check Qt dialog mapping without requiring Qt to be installed.
qt = types.ModuleType('PySide6')
qtw = types.ModuleType('PySide6.QtWidgets')
class FakeApp:
    @staticmethod
    def instance():
        return types.SimpleNamespace(activeWindow=lambda: None)
class FakeMessageBox:
    @staticmethod
    def information(parent, title, msg): return ('info', title, msg)
    @staticmethod
    def warning(parent, title, msg): return ('warn', title, msg)
    @staticmethod
    def critical(parent, title, msg): return ('error', title, msg)
class FakeFileDialog:
    @staticmethod
    def getExistingDirectory(parent, title, initial): return '/tmp/imu'
qtw.QApplication = FakeApp
qtw.QMessageBox = FakeMessageBox
qtw.QFileDialog = FakeFileDialog
sys.modules['PySide6'] = qt
sys.modules['PySide6.QtWidgets'] = qtw
sys.path.insert(0, str(ROOT))
import qt_dialogs
assert qt_dialogs.messagebox.showinfo('', 'test')[0] == 'info'
assert qt_dialogs.messagebox.showerror('', 'test')[0] == 'error'
assert qt_dialogs.messagebox.showwarning('', 'test')[0] == 'warn'
assert qt_dialogs.filedialog.askdirectory() == '/tmp/imu'

# Only execute new manual homing functions, not imports or vendor DLL.
mod = ast.parse(source)
klass = next(x for x in mod.body if isinstance(x, ast.ClassDef) and x.name == 'FormTurntableCtrl')
method_names = ('_send_home_commands','pushButton_InnerReturnZero_Click','pushButton_OuterReturnZero_Click','pushButton_AllAxisReturnZero_Click')
methods = [node for node in klass.body if isinstance(node, ast.FunctionDef) and node.name in method_names]
assert len(methods) == len(method_names)
wrapper = ast.Module(body=[ast.ClassDef(name='TestCtrl',bases=[],keywords=[],body=methods,decorator_list=[])],type_ignores=[])
ast.fix_missing_locations(wrapper)
lock = threading.Lock()
comm = types.SimpleNamespace(thread_lock=lock)
msgs=[]
commands=[]
class FakeBox:
    @staticmethod
    def showwarning(*args):
        assert not lock.locked(), 'warning while lock held'
        msgs.append(('warning',args))
    @staticmethod
    def showerror(*args):
        assert not lock.locked(), 'error dialog while lock held'
        msgs.append(('error',args))

def comm_fn(axis, speed, accel):
    commands.append((axis,speed,accel))
    return True
ns={'turntableComm':comm,'messagebox':FakeBox,'twoTD600_SetAxisFindZero':comm_fn,
    'twoFDT600WK_SetAxisFindZero':lambda axis,code: True,
    'INNER_ROTATION_AXIS':1,'OUTER_ROTATION_AXIS':2,'time':time}
exec(compile(wrapper,'<test-homing>', 'exec'),ns)
obj=ns['TestCtrl']()
obj.turntable_model='2TD600'
notices=[]
obj._notify_homing_started=notices.append
obj.pushButton_AllAxisReturnZero_Click()
assert commands == [(1,10,10),(2,10,10)],commands
assert not lock.locked()
assert len(notices)==1 and not msgs

# Invalid result and native Python exception should not leave lock held.
ns['twoTD600_SetAxisFindZero'] = lambda axis,speed,accel: False
obj.pushButton_InnerReturnZero_Click()
assert msgs[-1][0]=='error' and not lock.locked()
def broken(*args): raise RuntimeError('mock DLL wrapper failure')
ns['twoTD600_SetAxisFindZero'] = broken
obj.pushButton_OuterReturnZero_Click()
assert msgs[-1][0]=='error' and not lock.locked()

obj.turntable_model='not connected'
obj.pushButton_AllAxisReturnZero_Click()
assert msgs[-1][0]=='warning' and not lock.locked()

# Auto preflight stages have UI progress text and the user-confirmed 360°/0° periodic check.
imu=(ROOT/'form'/'form_imu_calibration.py').read_text(encoding='utf-8')
assert '自动标定准备阶段：' in imu
assert '_wrapped_angle_error_deg(inner, targets[0])' in imu
assert '_wrapped_angle_error_deg(outer, targets[1])' in imu

print('PASS: Qt dialogs, single/dual homing, failure exception/lock release, auto phase status')
