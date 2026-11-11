# -*- coding: utf-8 -*-
"""WK温补姿态指令发送专项回归；仅使用假DLL，不连接真实硬件。"""
import ast
import ctypes
import math
import threading
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'form' / 'form_thermal_compensation.py'


def load_methods(fake):
    tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef)
               and n.name == 'FormThermalCompensation')
    wanted = ('_wk_thermal_position_plan', '_move', '_check_position_command_started')
    methods = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in wanted]
    runner = ast.ClassDef(name='Runner', bases=[], keywords=[], decorator_list=[], body=methods)
    ns = dict(math=math, ctypes=ctypes, time=fake.clock,
              turntableComm=fake.comm, turntableData=fake.data,
              INNER_ROTATION_AXIS=0, OUTER_ROTATION_AXIS=2,
              wk_comm=fake.wk, _angle_error=lambda a, b: (float(a)-float(b)+180) % 360-180)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[runner], type_ignores=[])),
                 str(SOURCE), 'exec'), ns)
    return ns['Runner']


class FakeClock:
    def __init__(self):
        self.now = 10.0
        self.sleeps = []
    def monotonic(self):
        return self.now
    def sleep(self, seconds):
        self.sleeps.append(float(seconds))
        self.now += float(seconds)


class FakeDLLFunction:
    def __init__(self, states, result_by_axis=None, auto_start=True):
        self.calls = []
        self.argtypes = None
        self.restype = None
        self.states = states
        self.result_by_axis = result_by_axis or {}
        self.auto_start = auto_start
    def __call__(self, port, axis, direction, acceleration, speed, target):
        self.calls.append((port, axis, direction, acceleration, speed, target))
        result = self.result_by_axis.get(axis, 0)
        if result == 0 and self.auto_start:
            self.states[axis]['state'] = 3
        return result


class Fixture:
    def __init__(self, positions=None, result_by_axis=None, auto_start=True):
        self.clock = FakeClock()
        self.states = {
            0: {'alarm': 0, 'state': 1, 'angle': 0.0},
            2: {'alarm': 0, 'state': 1, 'angle': 0.0},
        }
        if positions:
            for axis, angle in positions.items():
                self.states[axis]['angle'] = float(angle)
        self.dll_func = FakeDLLFunction(self.states, result_by_axis, auto_start)
        self.wk = types.SimpleNamespace(
            axisPorts={0: 8, 2: 9},
            turntableDll=types.SimpleNamespace(SetAxisPosition=self.dll_func),
            twoFDT600WK_getAxisStateInfo=self.read_state,
        )
        self.comm = types.SimpleNamespace(thread_lock=threading.Lock())
        self.data = types.SimpleNamespace(inner_axis_speed=0.0, outer_axis_speed=0.0)
        self.Runner = load_methods(self)
        self.obj = self.Runner()
        self.obj.turntable_form = types.SimpleNamespace(_speed_limit_tripped=False)
        self.obj.move_speed = types.SimpleNamespace(value=lambda: 2.0)
        self.obj.task = {}
        self.obj.logs = []
        self.obj._stopped = lambda: True
        self.obj._log = self.obj.logs.append
    def read_state(self, axis, alarm, state, angle, error):
        spec = self.states[axis]
        alarm[0] = spec['alarm']
        state[0] = spec['state']
        angle[0] = spec['angle']
        error[0] = 0
        return True


class ThermalPositionDispatchTests(unittest.TestCase):
    def test_skip_zero_travel_inner_and_send_outer_180_counterclockwise(self):
        f = Fixture({0: 0.0, 2: 359.995})
        f.obj._move(0.0, 180.0)
        self.assertEqual(len(f.dll_func.calls), 1)
        self.assertEqual(f.dll_func.calls[0], (9, 2, 1, 10, 2.0, 180.0))
        self.assertIn(2, f.obj.task['position_watch'])
        self.assertNotIn(0, f.obj.task['position_watch'])
        self.assertTrue(any('跳过无效位置指令' in x and '内轴' in x for x in f.obj.logs))
        self.assertEqual(f.clock.sleeps, [])

    def test_two_moving_axes_are_dispatched_with_100ms_gap(self):
        f = Fixture({0: 0.0, 2: 0.0})
        f.obj._move(90.0, 180.0)
        self.assertEqual([c[1] for c in f.dll_func.calls], [0, 2])
        self.assertEqual(f.clock.sleeps, [0.1])
        self.assertEqual(f.obj.task['position_watch'][0]['target'], 90.0)
        self.assertEqual(f.obj.task['position_watch'][2]['target'], 180.0)

    def test_start_watch_accepts_position_mode_3(self):
        f = Fixture({0: 0.0, 2: 359.995})
        f.obj._move(0.0, 180.0)
        f.obj._check_position_command_started(f.clock.monotonic())
        self.assertTrue(f.obj.task['position_watch'][2]['started'])
        self.assertTrue(any('定位启动已确认' in x for x in f.obj.logs))

    def test_start_watch_fails_early_if_dll_returns_zero_but_axis_stays_idle(self):
        f = Fixture({0: 0.0, 2: 359.995}, auto_start=False)
        f.obj._move(0.0, 180.0)
        f.clock.now += 2.1
        with self.assertRaisesRegex(RuntimeError, '2秒后仍为1#伺服待命'):
            f.obj._check_position_command_started(f.clock.monotonic())

    def test_dll_nonzero_is_reported_without_retrying_motion(self):
        f = Fixture({0: 0.0, 2: 359.995}, result_by_axis={2: 7})
        with self.assertRaisesRegex(RuntimeError, 'DLL=7'):
            f.obj._move(0.0, 180.0)
        self.assertEqual(len(f.dll_func.calls), 1)

    def test_both_axes_already_at_targets_send_no_position_command(self):
        f = Fixture({0: 0.0, 2: 180.0})
        f.obj._move(0.0, 180.0)
        self.assertEqual(f.dll_func.calls, [])
        self.assertEqual(f.obj.task['position_watch'], {})

    def test_runtime_tick_calls_start_watch_before_waiting_for_arrival(self):
        tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef)
                   and n.name == 'FormThermalCompensation')
        tick = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_tick')
        source = ast.get_source_segment(SOURCE.read_text(encoding='utf-8'), tick)
        self.assertIn("elif t['phase']=='wait_position':", source)
        self.assertIn('self._check_position_command_started(now)', source)
        self.assertIn("if now-t['phase_start']>240", source)


if __name__ == '__main__':
    unittest.main(verbosity=2)
