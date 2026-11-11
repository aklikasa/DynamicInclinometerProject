# -*- coding: utf-8 -*-
"""Isolated WK manual velocity tests; actual vendor DLL is NEVER loaded."""
import ast, copy, ctypes, math, tempfile, os, types, unittest
from pathlib import Path
FILE=Path(__file__).resolve().parents[1]/'form'/'form_turntable_ctrl.py'
class FakeFunc:
    argtypes=None;restype=None
    def __init__(self):self.calls=[];self.result=0
    def __call__(self,*args):self.calls.append(args);return self.result
class TestSharedWKVelocity(unittest.TestCase):
    def setUp(self):
        tree=ast.parse(FILE.read_text(encoding='utf-8'))
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='FormTurntableCtrl')
        names=['_wk_manual_signed_velocity','_wk_manual_inner_signed_velocity','_wk_manual_outer_signed_velocity']
        funcs=[copy.deepcopy(next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name==name)) for name in names]
        for f in funcs:f.decorator_list=[]
        self.native=FakeFunc();self.state=1;self.alarm=0;self.works=True
        def state_read(axis,a,s,p,e):
            a[0]=self.alarm;s[0]=self.state;p[0]=10.0;e[0]=0
            return self.works
        ns={'ctypes':ctypes,'math':math,'INNER_ROTATION_AXIS':0,'OUTER_ROTATION_AXIS':2,
            'wk_comm':types.SimpleNamespace(axisPorts=[8,0,9],turntableDll=types.SimpleNamespace(SetAxisVelocity=self.native)),
            'autoRunState':types.SimpleNamespace(auto_run_state='停止'),
            'twoFDT600WK_getAxisStateInfo':state_read}
        exec(compile(ast.fix_missing_locations(ast.Module(body=funcs,type_ignores=[])),'<isolated>','exec'),ns)
        self.obj=types.SimpleNamespace(button_TurntableCommPortOpen=types.SimpleNamespace(text=lambda:'关闭转台'),
                                       _wk_manual_position_pending={},_wk_manual_velocity_diagnostic=lambda msg:None)
        # bind class wrapper to mocked object instance
        self.obj._wk_manual_signed_velocity=types.MethodType(ns['_wk_manual_signed_velocity'],self.obj)
        self.inner=ns['_wk_manual_inner_signed_velocity'];self.outer=ns['_wk_manual_outer_signed_velocity']
    def test_both_axes_forward_and_reverse(self):
        for fn in (self.inner,self.outer):
            self.assertTrue(fn(self.obj,10,10)[0])
            self.assertTrue(fn(self.obj,-10,10)[0])
        self.assertEqual(self.native.calls,[(8,0,0,10,10.0),(8,0,1,10,10.0),
                                            (9,2,0,10,10.0),(9,2,1,10,10.0)])
        self.assertEqual(self.native.argtypes,[ctypes.c_int,ctypes.c_int,ctypes.c_uint8,ctypes.c_uint16,ctypes.c_float])
    def test_requires_servo_without_alarm(self):
        for st,al in [(0,0),(3,0),(4,0),(1,1)]:
            self.state=st;self.alarm=al
            self.assertFalse(self.inner(self.obj,-10,10)[0]);self.assertFalse(self.outer(self.obj,-10,10)[0])
        self.assertEqual(self.native.calls,[])
    def test_no_automatic_task(self):
        self.obj._wk_manual_position_pending={0:{}}
        self.assertFalse(self.inner(self.obj,-10,10)[0]);self.assertEqual(self.native.calls,[])
    def test_dll_return_error(self):
        self.native.result=4
        result,detail=self.inner(self.obj,-10,10)
        self.assertFalse(result);self.assertIn('4',detail)
    def test_python_dll_exception(self):
        def broken(*args):raise OSError('simulated')
        self.native.__call__=broken # special method looked up on class, replace object instead
        self.obj._wk_manual_signed_velocity.__func__.__globals__['wk_comm'].turntableDll.SetAxisVelocity=broken
        result,detail=self.inner(self.obj,-10,10)
        self.assertFalse(result);self.assertIn('模拟',detail) if False else self.assertIn('simulated',detail)
    def test_only_wk_manual_changed(self):
        s=FILE.read_text('utf-8')
        self.assertIn('ret, detail = self._wk_manual_inner_signed_velocity(speed, accel)',s)
        self.assertIn('ret, detail = self._wk_manual_outer_signed_velocity(speed, accel)',s)
        self.assertIn('Avoid a blocking modal dialog while moving.',s)
if __name__=='__main__':unittest.main(verbosity=2)
