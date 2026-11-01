"""Axis0/Axis2 contract regression tests. No live hardware calls."""
from __future__ import annotations
import unittest
from unittest.mock import patch
from test_turntable_enable import FakeDriver, TurntableWorker, INNER, OUTER
from app.devices.turntable_driver import TurntableDriver
from app.core.scan_plan import make_scan_plan
from app.core.measurement import wrap_deg

class NewAxisFeedbackTests(unittest.TestCase):
    @patch('app.devices.turntable_worker.time.sleep')
    def test_only_outer_disabled_and_normal_true(self, _sleep):
        driver = FakeDriver()
        driver.data['inner']['enabled'] = True
        driver.data['inner']['normal'] = True
        driver.data['outer']['enabled'] = False
        driver.data['outer']['normal'] = True
        worker = TurntableWorker('COM2')
        text = worker._do(driver, 'enable', (OUTER,))
        self.assertEqual(driver.calls, [(OUTER, True)])
        self.assertIn('轴2', text)
        self.assertTrue(driver.data['outer']['enabled'])

    @patch('app.devices.turntable_worker.time.sleep')
    def test_outer_failure_not_masked_by_normal_true(self, _sleep):
        driver = FakeDriver(refuse=True)
        driver.data['inner']['enabled'] = True
        driver.data['inner']['normal'] = True
        driver.data['outer']['normal'] = True
        worker = TurntableWorker('COM2')
        with self.assertRaisesRegex(RuntimeError, 'GetAxisEnable仍为0'):
            worker._do(driver, 'enable', (OUTER,))
        self.assertEqual(driver.calls, [(OUTER, True)])

    def test_feedback_codes_must_be_binary(self):
        class FakeLib:
            def GetAxisEnable(self, axis): return -1
            def GetAxisNormal(self, axis): return 1
        driver = TurntableDriver.__new__(TurntableDriver)
        driver.lib = FakeLib()
        with self.assertRaisesRegex(IOError, '不是有效的 0/1'):
            driver._binary_feedback('GetAxisEnable', OUTER)
        self.assertTrue(driver._binary_feedback('GetAxisNormal', INNER))

    def test_outer_command_targets_stay_in_0_360(self):
        plan = make_scan_plan()
        self.assertEqual(len(plan), 74)
        self.assertEqual({p.inner_deg for p in plan}, {0, 90})
        self.assertTrue(all(0 <= p.outer_command_deg < 360 for p in plan))
        self.assertEqual(next(p.outer_command_deg for p in plan if p.outer_signed_deg == -10),350)
        self.assertEqual(next(p.outer_command_deg for p in plan if p.outer_signed_deg == -180),180)
        self.assertEqual(wrap_deg(360),0)

if __name__ == '__main__':
    unittest.main()
