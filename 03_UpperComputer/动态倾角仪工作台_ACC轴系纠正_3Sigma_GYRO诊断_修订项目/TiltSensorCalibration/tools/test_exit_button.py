"""无 Qt、无硬件状态机注入测试，只测试退出按钮的 Python 分支与依赖隔离。"""
from pathlib import Path
import ast
import threading
from types import SimpleNamespace

root=Path(__file__).resolve().parents[1]
src=root/'form/form_turntable_ctrl.py'
mod=ast.parse(src.read_text(encoding='utf-8'))
cls=next(n for n in mod.body if isinstance(n,ast.ClassDef) and n.name=='FormTurntableCtrl')
meth=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='pushButton_closeWindows_Click')
code=ast.fix_missing_locations(ast.Module(body=[ast.ClassDef(name='TestForm',bases=[],keywords=[],decorator_list=[],body=[meth])],type_ignores=[]))

calls=[]
class QtMsg:
    @staticmethod
    def warning(*args): calls.append(('warn',args[1])); return None
class QtCore:
    @staticmethod
    def quit(): calls.append(('quit',None))

class Button:
    def __init__(self,text):self.label=text
    def text(self):return self.label

fake=SimpleNamespace(thread_instance=None,terminate_thread_requst=False)
tc=SimpleNamespace(thread_instance=None,terminate_thread_requst=False,is_connected=False,thread_lock=threading.Lock())
ns={'turntableComm':fake,'tcComm':tc,'QMessageBox':QtMsg,'QCoreApplication':QtCore,'threading':threading,'sys':__import__('sys'),'Et':__import__('xml.etree.ElementTree',fromlist=['x']),'tc_fixed_value_stop':lambda:None,'TimeoutError':TimeoutError}
exec(compile(code,str(src),'exec'),ns)
class Form(ns['TestForm']):
    def __init__(self,connected=False):
        self.button_TurntableCommPortOpen=Button('关闭转台' if connected else '打开转台')
        self.pushButton_closeWindows=object()
    def record_user_habits(self):calls.append(('config',None))

# Case1: no hardware => save settings & exit; no vendor DLL calls permitted by method.
Form().pushButton_closeWindows_Click()
assert calls==[('config',None),('quit',None)],calls
# Case2: turntable connected => must not disable motor or exit.
calls.clear(); Form(True).pushButton_closeWindows_Click()
assert calls==[('warn','请先安全断开转台')],calls
# Case3: orphaned thread => remain in UI until operator stops it safely.
calls.clear();fake.thread_instance=object();Form().pushButton_closeWindows_Click()
assert calls==[('warn','请先安全断开转台')],calls
fake.thread_instance=None
# Case4: stalled temperature thread => finite wait and warning, don't block forever.
class Stuck:
    def join(self,timeout):
        calls.append(('join',timeout))
    def is_alive(self):return True

tc.thread_instance=Stuck();calls.clear();Form().pushButton_closeWindows_Click()
assert ('join',2.0) in calls and ('warn','温箱未完成断开') in calls and not any(t=='quit' for t,_ in calls), calls
print('PASS: 未连接无驱动调用安全退出、转台连接禁止强制断电、温箱等待限时')
