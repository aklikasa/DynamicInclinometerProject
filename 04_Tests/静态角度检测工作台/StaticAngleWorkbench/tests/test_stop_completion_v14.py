"""不依赖真Qt和真转台的自动检测收尾状态测试。"""
from __future__ import annotations
import sys
import time
import types
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_turntable_enable import TurntableWorker   # 创建无 Qt 环境的轻量 QThread stub
qt = sys.modules['PySide6.QtCore']

class FakeBoundSignal:
    def __init__(self): self.slots=[]
    def connect(self, cb): self.slots.append(cb)
    def emit(self,*a):
        for callback in list(self.slots): callback(*a)
class FakeSignal:
    def __init__(self,*a): self.name=None
    def __set_name__(self,owner,name): self.name=name
    def __get__(self,obj,owner):
        if obj is None:return self
        return obj.__dict__.setdefault('_signal_'+self.name,FakeBoundSignal())
class FakeQObject:
    def __init__(self,parent=None):pass
class FakeTimer:
    def __init__(self,parent=None):self.timeout=FakeBoundSignal();self.running=False
    def setInterval(self,n):pass
    def start(self):self.running=True
    def stop(self):self.running=False
qt.Signal=FakeSignal
qt.QObject=FakeQObject
qt.QTimer=FakeTimer
from app.core.auto_scan import AutoScan

class Worker:
    def __init__(self):self.commands=[]
    def submit(self,*args):self.commands.append(args);return True

class StopCompletionTests(unittest.TestCase):
    def new_scan(self):
        obj=AutoScan()
        worker=Worker()
        obj.start(worker,None)
        events=[]
        obj.finished.connect(lambda status,reason:events.append((status,reason)))
        return obj,worker,events

    def test_abort_waits_for_verified_stop_before_reporting(self):
        scan,worker,events=self.new_scan()
        scan.abort('操作员停止')
        self.assertTrue(scan.active)
        self.assertEqual(scan.phase,'stopping')
        self.assertEqual(events,[])
        self.assertEqual(worker.commands[-1][0],'stop_all')
        scan.command_result('stop_all',True,'确认停稳')
        self.assertFalse(scan.active)
        self.assertEqual(events,[('中止','操作员停止')])

    def test_dll_stop_failure_never_marks_complete(self):
        scan,worker,events=self.new_scan()
        scan.abort('操作员停止')
        scan.command_result('stop_all',False,'轴2停车返回0')
        self.assertFalse(scan.active)
        self.assertEqual(events[0][0],'危险-停车未确认')
        self.assertIn('轴2',events[0][1])

    def test_normal_scan_completion_waits_for_stop(self):
        scan,worker,events=self.new_scan()
        scan.point_index=74
        scan.phase='next'
        scan.fb={name:dict(enabled=True,normal=True,driver_fault=False,up_limit=False,
                           down_limit=False,over_speed=False,over_diff=False,
                           position=0.,speed=0.,in_place=True) for name in ('inner','outer')}
        scan.last_fb_monotonic=time.monotonic()
        scan.tick()
        self.assertEqual(scan.phase,'stopping')
        self.assertTrue(scan.active)
        self.assertEqual(events,[])
        scan.command_result('stop_all',True,'反馈已确认')
        self.assertEqual(events,[('完成','')])

if __name__=='__main__':unittest.main()
