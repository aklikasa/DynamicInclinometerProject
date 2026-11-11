# -*- coding: utf-8 -*-
"""Dry-run tests with fake DLL; never touches motors."""
from pathlib import Path
import sys,time,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from native_web.device_service import DeviceService
from test_td_click_manual import FakeTD

class ZeroPositionTests(unittest.TestCase):
    def setUp(self):
        self.s=DeviceService();self.td=FakeTD()
        self.s.td_mod=self.td
        self.s._td_driver=lambda:self.td
        self.s.td_connected=True
        self.s.td_state.update(last_monotonic=time.monotonic(),inner={},outer={})
    @staticmethod
    def data(**kw):
        x=dict(inner_speed_dps=1.25,outer_speed_dps=0.75,safety_ack='PHYSICAL_ESTOP_READY')
        x.update(kw)
        return x
    def test_sequential_outer_then_inner_and_fresh_arrival_feedback(self):
        result=self.s.td_return_zero(self.data())
        self.assertEqual(result['axis'],'outer')
        self.assertEqual(self.td.moves,[(2,0.0,0.75)])
        # A stale in-place flag must NOT trigger second axis before position reaches 0.
        self.s._td_monitor_motion({})
        self.assertEqual(len(self.td.moves),1)
        # Position feedback arrives but outer still moving; no second axis.
        self.td.angle[2]=0.0
        self.td.speed[2]=0.10
        self.td.motion_mode[2]='绝对位置运动'
        self.s._td_monitor_motion({})
        self.assertEqual(len(self.td.moves),1)
        self.td.speed[2]=0.0
        self.td.motion_mode[2]='静止'
        self.s._td_monitor_motion({})
        self.assertEqual(len(self.td.moves),1)  # Require 0.5 second stable feedback
        self.s.td_motion['stable_since']-=0.6
        self.s._td_monitor_motion({})
        self.assertEqual(self.td.moves,[(2,0.0,0.75),(0,0.0,1.25)])
        self.assertEqual(self.s.td_motion['axis'],'inner')
        self.td.angle[0]=0.0
        self.s._td_monitor_motion({})
        self.assertEqual(self.s.td_motion['state'],'moving')
        self.s.td_motion['stable_since']-=0.6
        self.s._td_monitor_motion({})
        self.assertEqual(self.s.td_motion['state'],'complete')
        self.assertIn('双轴位置归零完成',self.s.td_motion['message'])
    def test_stop_cancels_pending_second_axis(self):
        self.s.td_return_zero(self.data())
        self.s.td_stop_all()
        self.td.angle[2]=0.0
        self.s._td_monitor_motion({})
        self.assertEqual(self.td.moves,[(2,0.,0.75)])
        self.assertEqual(self.s.td_motion['state'],'stopped')
    def test_reject_on_fault_without_any_command(self):
        self.td.fault=True
        with self.assertRaisesRegex(RuntimeError,'故障'):
            self.s.td_return_zero(self.data())
        self.assertFalse(self.td.moves)
    def test_reject_without_ack_or_over_limit(self):
        for inp in [self.data(safety_ack=''),self.data(outer_speed_dps=60.),self.data(inner_speed_dps=0.)]:
            with self.assertRaises(ValueError):self.s.td_return_zero(inp)
        self.assertFalse(self.td.moves)
    def test_already_zero_sends_no_movement(self):
        self.td.angle={0:0.,2:0.}
        result=self.s.td_return_zero(self.data())
        self.assertEqual(result['state'],'complete')
        self.assertEqual(self.td.moves,[])
    def test_inner_only_if_outer_is_zero(self):
        self.td.angle[2]=0.0
        result=self.s.td_return_zero(self.data())
        self.assertEqual(result['axis'],'inner')
        self.assertEqual(self.td.moves,[(0,0.0,1.25)])
    def test_endpoint_and_button_wired(self):
        web=Path(__file__).resolve().parents[1]
        self.assertIn("'/api/td/return-zero':SERVICE.td_return_zero",(web/'server.py').read_text('utf8'))
        self.assertIn('id="tdReturnZero"',(web/'index.html').read_text('utf8'))
        self.assertIn("post('td/return-zero'",(web/'app.js').read_text('utf8'))

if __name__=='__main__':unittest.main()
