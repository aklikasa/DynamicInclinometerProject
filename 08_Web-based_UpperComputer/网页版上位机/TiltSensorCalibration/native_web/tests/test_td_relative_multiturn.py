# -*- coding: utf-8 -*-
"""R7 manual movement uses vendor D6 increment and counts real travel, not orientation.

No hardware connected. Fake rotating feedback wraps to [0, 360).
"""
from pathlib import Path
import sys, time, unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from native_web.device_service import DeviceService
from test_td_click_manual import FakeTD


class MultiturnTests(unittest.TestCase):
    def setUp(self):
        self.service = DeviceService()
        self.vendor = FakeTD()
        self.service._td_driver = lambda: self.vendor
        self.service.td_connected = True
        self.service.td_state.update(last_monotonic=time.monotonic(), inner={}, outer={})

    def send(self, axis='outer', step=720, speed=10):
        return self.service.td_jog(dict(axis=axis, step_deg=step,
                     speed_dps=speed, safety_ack='PHYSICAL_ESTOP_READY'))

    def progress(self, direction, n):
        axis = 2
        for _ in range(n):
            # Simulated 1-second feedback interval, 10 deg travel in that interval.
            # A real turntable is monitored by a separate polling thread.
            self.service.td_motion['last_update'] -= 1.0
            self.vendor.angle[axis] = (self.vendor.angle[axis] + 10*direction) % 360
            self.service._td_monitor_motion({})

    def test_relative_crosses_positive_360_and_does_not_use_absolute_command(self):
        self.vendor.angle[2] = 350
        motion = self.send(step=20, speed=10)
        self.assertEqual(self.vendor.moves, [(2,20.0,10.0)])
        self.assertEqual(motion['mode'], 'relative')
        self.assertIsNone(motion['target'])
        self.assertEqual(motion['requested_step_deg'],20.0)
        self.progress(1,1)
        self.assertEqual(self.service.td_motion['state'], 'moving')
        self.progress(1,1)
        self.assertEqual(self.service.td_motion['state'], 'complete')

    def test_two_full_turns_do_not_complete_at_first_revolution(self):
        self.vendor.angle[2] = 350
        self.send(step=720, speed=10)
        self.progress(1, 36)
        self.assertEqual(self.service.td_motion['state'], 'moving')
        self.assertAlmostEqual(self.service.td_motion['travelled_deg'], 360, places=3)
        self.progress(1, 36)
        self.assertEqual(self.service.td_motion['state'], 'complete')
        self.assertAlmostEqual(self.service.td_motion['travelled_deg'], 720, places=3)

    def test_negative_one_and_half_turns(self):
        self.vendor.angle[2] = 12
        self.send(step=-540, speed=10)
        self.assertEqual(self.vendor.moves, [(2,-540.0,10.0)])
        self.progress(-1, 36)
        self.assertEqual(self.service.td_motion['state'], 'moving')
        self.progress(-1, 18)
        self.assertEqual(self.service.td_motion['state'], 'complete')
        self.assertAlmostEqual(self.service.td_motion['travelled_deg'], -540, places=3)

    def test_impossible_feedback_gap_triggers_software_stop(self):
        self.send(step=500,speed=10)
        self.service.td_motion['last_update']-=3.
        self.vendor.angle[2]=50
        self.service._td_monitor_motion({})
        self.assertEqual(self.service.td_motion['state'], 'fault')
        self.assertEqual(self.vendor.stops, [0,2])

    def test_inner_requires_outer_zero_before_relative_motion(self):
        self.vendor.angle[2]=20
        with self.assertRaisesRegex(RuntimeError,'外轴非零位'):
            self.send(axis='inner',step=720)
        self.assertEqual(self.vendor.moves,[])
        self.vendor.angle[2]=0
        self.send(axis='inner',step=720)
        self.assertEqual(self.vendor.moves,[(0,720.0,10.0)])

    def test_nonfinite_increment_rejected_before_vendor_call(self):
        for step in [float('nan'),float('inf'),0.0]:
            with self.assertRaises(ValueError): self.send(step=step)
        self.assertEqual(self.vendor.moves,[])

    def test_real_driver_exports_relative_not_just_absolute(self):
        root=Path(__file__).resolve().parents[2]
        txt=(root/'turntable/turntable_2TD600_comm.py').read_text(encoding='utf8')
        self.assertIn('def twoTD600_SetAxisOpposition(',txt)
        self.assertIn('SetAxisOpposition',txt)
        web=(root/'native_web/device_service.py').read_text(encoding='utf8')
        self.assertIn('td.twoTD600_SetAxisOpposition(axis, float(step), speed)',web)
        self.assertNotIn('目标绝对角度超出当前软件工作区间 ±360°',web)

if __name__=='__main__': unittest.main()
