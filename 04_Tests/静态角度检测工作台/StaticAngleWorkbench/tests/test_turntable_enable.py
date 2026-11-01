"""模拟DLL返回值测试：不触碰真实转台、不依赖Qt。"""
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
try:
    from PySide6 import QtCore
except ImportError:
    qt = types.ModuleType('PySide6.QtCore')
    class QThread:
        def __init__(self, parent=None): pass
    class Signal:
        def __init__(self, *args): pass
        def emit(self, *args): pass
    qt.QThread = QThread
    qt.Signal = Signal
    sys.modules.setdefault('PySide6',types.ModuleType('PySide6'))
    sys.modules['PySide6.QtCore'] = qt
from app.devices.turntable_worker import TurntableWorker, INNER, OUTER

class FakeDriver:
    def __init__(self, fault=False, refuse=False):
        self.calls=[]
        self.refuse=refuse
        self.data={}
        for key in ('inner','outer'):
            self.data[key] = dict(enabled=False,normal=False,driver_fault=fault,
                                  up_limit=False,down_limit=False,over_speed=False,over_diff=False,
                                  position=0.,speed=0.,in_place=True)
    def info(self):
        return {k:dict(v) for k,v in self.data.items()}
    def enable(self,axis,on):
        self.calls.append((axis,on))
        if not self.refuse:
            key='inner' if axis==INNER else 'outer'
            self.data[key]['enabled']=on
            self.data[key]['normal']=on

class EnableTests(unittest.TestCase):
    def setUp(self):
        self.worker=TurntableWorker('COM99')

    @patch('app.devices.turntable_worker.time.sleep')
    def test_normal_false_before_enable_not_deadlocked(self,_):
        driver=FakeDriver()
        result=self.worker._do(driver,'enable_both',())
        self.assertEqual(driver.calls,[(INNER,True),(OUTER,True)])
        self.assertTrue(driver.data['inner']['enabled'])
        self.assertTrue(driver.data['outer']['normal'])
        self.assertIn('使能成功',result)

    @patch('app.devices.turntable_worker.time.sleep')
    def test_fault_prevents_power_on(self,_):
        driver=FakeDriver(fault=True)
        with self.assertRaisesRegex(RuntimeError,'故障/限位'):
            self.worker._do(driver,'enable',(INNER,))
        self.assertEqual(driver.calls,[])

    @patch('app.devices.turntable_worker.time.sleep')
    def test_return_success_but_enable_feedback_false(self,_):
        driver=FakeDriver(refuse=True)
        with self.assertRaisesRegex(RuntimeError,'GetAxisEnable仍为0'):
            self.worker._do(driver,'enable',(INNER,))
        self.assertEqual(driver.calls,[(INNER,True)])

    @patch('app.devices.turntable_worker.time.sleep')
    def test_status_diagnostics(self,_):
        driver=FakeDriver()
        summary=self.worker._do(driver,'diagnose',())
        self.assertIn('enabled=0',summary)
        self.assertIn('normal=0',summary)

if __name__=='__main__': unittest.main()
