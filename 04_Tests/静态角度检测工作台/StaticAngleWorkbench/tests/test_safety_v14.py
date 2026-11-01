"""V1.4 安全断开回归测试：模拟驱动，不连接真实转台。"""
from __future__ import annotations
import math
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from test_turntable_enable import TurntableWorker, INNER, OUTER
from app.core.calibration import Calibration
from app.core.report import export_report


class SafeFakeDriver:
    def __init__(self, inner=True, outer=True, inner_speed=0.0, outer_speed=0.0,
                 fail_stop=(), refuse_disable=()):
        self.is_open = True
        self.calls = []
        self.fail_stop = set(fail_stop)
        self.refuse_disable = set(refuse_disable)
        self.data = {}
        for name, enabled, speed in (('inner', inner, inner_speed), ('outer', outer, outer_speed)):
            self.data[name] = dict(
                enabled=enabled, normal=True, in_place=abs(speed)<.05,
                driver_fault=False, up_limit=False, down_limit=False,
                over_speed=False, over_diff=False, position=10., speed=float(speed))
    def info(self):
        return {key: value.copy() for key, value in self.data.items()}
    def stop(self, axis):
        self.calls.append(('stop', axis))
        if axis in self.fail_stop:
            raise IOError(f'厂家DLL轴{axis}停车返回0')
        key = 'inner' if axis == INNER else 'outer'
        self.data[key]['speed'] = 0.0
        self.data[key]['in_place'] = True
    def enable(self, axis, enabled):
        self.calls.append(('enable', axis, enabled))
        if not enabled and axis not in self.refuse_disable:
            self.data['inner' if axis == INNER else 'outer']['enabled'] = False
    def close(self):
        self.calls.append(('close',))
        self.is_open = False


class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.worker = TurntableWorker('COM2')

    @patch('app.devices.turntable_worker.time.sleep')
    def test_disconnect_mixed_enabled_axis(self, _sleep):
        drv = SafeFakeDriver(inner=True, outer=False, inner_speed=.7)
        msg = self.worker._do(drv, 'disconnect', ())
        self.assertIn('已关闭', msg)
        self.assertIn(('stop', INNER), drv.calls)
        self.assertNotIn(('stop', OUTER), drv.calls)
        self.assertIn(('enable', INNER, False), drv.calls)
        self.assertEqual(drv.calls[-1], ('close',))
        self.assertFalse(drv.is_open)

    @patch('app.devices.turntable_worker.time.sleep')
    def test_both_disabled_no_bad_stop_return(self, _sleep):
        drv = SafeFakeDriver(inner=False, outer=False)
        self.worker._do(drv, 'disconnect', ())
        self.assertEqual(drv.calls, [('close',)])

    @patch('app.devices.turntable_worker.time.sleep')
    def test_moving_stop_return_zero_does_not_disconnect(self, _sleep):
        drv = SafeFakeDriver(inner=True, outer=True, inner_speed=2.0,
                             outer_speed=.5, fail_stop=(INNER,))
        with patch('app.devices.turntable_worker.time.monotonic', side_effect=[0] * 99 + [7]):
            try:
                self.worker._do(drv, 'disconnect', ())
            except (RuntimeError, StopIteration):
                pass
        self.assertNotIn(('close',), drv.calls)
        self.assertNotIn(('enable', OUTER, False), drv.calls)
        self.assertIn(('stop', INNER), drv.calls)
        self.assertIn(('stop', OUTER), drv.calls)

    @patch('app.devices.turntable_worker.time.sleep')
    def test_disable_feedback_must_be_confirmed(self, _sleep):
        drv = SafeFakeDriver(inner=True, outer=True, refuse_disable=(OUTER,))
        with patch('app.devices.turntable_worker.time.monotonic') as mock_mono:
            now = [0.0]
            def advance():
                now[0] += 0.30
                return now[0]
            mock_mono.side_effect = advance
            with self.assertRaisesRegex(RuntimeError, '外轴2'):
                self.worker._do(drv, 'disconnect', ())
        self.assertNotIn(('close',), drv.calls)
        self.assertTrue(drv.data['outer']['enabled'])

    def test_disconnect_discards_pending_motion(self):
        self.worker.submit('move', OUTER, 320, 2)
        self.worker.submit('move', INNER, 10, 1)
        self.worker.submit('disconnect')
        self.assertFalse(self.worker.submit('move', OUTER, 40, 2))
        self.assertEqual(self.worker._next()[0], 'disconnect')
        self.assertIsNone(self.worker._next())

    def test_stop_discards_pending_motion(self):
        self.worker.submit('move', OUTER, 320, 2)
        self.worker.submit('stop_all')
        self.assertEqual(self.worker._next()[0], 'stop_all')
        self.assertIsNone(self.worker._next())

    @patch('app.devices.turntable_worker.time.sleep')
    def test_idle_axis_stop_error_requires_feedback_not_fake_success(self, _sleep):
        drv = SafeFakeDriver(inner=True, outer=False, fail_stop=(INNER,))
        text = self.worker._do(drv, 'stop_all', ())
        self.assertIn('连续3次', text)
        self.assertNotIn(('close',), drv.calls)

    @patch('app.devices.turntable_worker.time.sleep')
    def test_invalid_speed_blocks_disconnect(self, _sleep):
        drv = SafeFakeDriver(inner=False, outer=False, outer_speed=math.nan)
        with self.assertRaisesRegex(RuntimeError, '无效'):
            self.worker._do(drv, 'disconnect', ())
        self.assertNotIn(('close',), drv.calls)

    def test_report_even_with_zero_rows(self):
        cal = Calibration.load(Path(__file__).resolve().parents[1] / 'examples/accel_calibration_example.json')
        with TemporaryDirectory() as temp:
            path = Path(temp) / '终止记录.xlsx'
            export_report(path, [], cal, {}, '中止', '实机停车确认失败')
            self.assertTrue(path.is_file())
            self.assertGreater(path.stat().st_size, 3000)

    def test_export_button_removed(self):
        src = (Path(__file__).resolve().parents[1] / 'app/ui/main_window.py').read_text(encoding='utf-8')
        self.assertNotIn("button('导出已有结果'", src)
        self.assertNotIn('def export_current(', src)
        self.assertIn('self._save_excel(status,reason)', src)


if __name__ == '__main__':
    unittest.main()
