# -*- coding: utf-8 -*-
"""UI/static + fake-DLL checks: no physical serial port or axis is opened."""
from pathlib import Path
import sys, time, unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from native_web.device_service import DeviceService
from test_td_click_manual import FakeTD

class ConnectionPanelTests(unittest.TestCase):
    def setUp(self):
        self.s=DeviceService();self.fake=FakeTD()
        self.fake.closed=0
        self.fake.twoTD600_closePort=lambda: setattr(self.fake,'closed',self.fake.closed+1)
        self.s.td_mod=self.fake;self.s._td_driver=lambda:self.fake
        self.s.td_connected=True
        self.s.td_state.update(last_monotonic=time.monotonic(),inner={'angle':0},outer={'angle':0})
    def test_disconnect_is_not_software_stop(self):
        self.assertIn('已关闭', self.s.td_manual_disconnect())
        self.assertEqual(self.fake.closed,1)
        self.assertEqual(self.fake.stops,[])
        self.assertFalse(self.s.td_connected)
    def test_pending_motion_keeps_connection(self):
        self.s.td_motion['state']='moving'
        with self.assertRaisesRegex(RuntimeError,'不能直接断开'):
            self.s.td_manual_disconnect()
        self.assertTrue(self.s.td_connected)
        self.assertEqual(self.fake.closed,0)
    def test_would_not_disconnect_if_feedback_speed_nonzero(self):
        self.fake.speed[0]=0.3
        with self.assertRaisesRegex(RuntimeError,'拒绝断开'):
            self.s.td_manual_disconnect()
        self.assertTrue(self.s.td_connected)
        self.assertEqual(self.fake.closed,0)
    def test_status_age_is_real_feedback_freshness(self):
        d=self.s.status()['td']
        self.assertTrue(d['reading']);self.assertGreaterEqual(d['feedback_age_ms'],0)
        self.s.td_state['last_monotonic']=time.monotonic()-10
        d=self.s.status()['td']
        self.assertFalse(d['reading']);self.assertIsNone(d['feedback_age_ms'])
    def test_web_fields_and_distinct_actions(self):
        web=Path(__file__).resolve().parents[1]
        html=(web/'index.html').read_text('utf8')
        js=(web/'app.js').read_text('utf8')
        self.assertIn('id="tdDisconnect"',html)
        self.assertIn('断开转台通讯',html)
        self.assertIn('id="tdStopAll"',html)
        self.assertIn('id="tdTelemAge"',html)
        self.assertNotIn('td-connect-tip',html)
        self.assertIn("post('td/disconnect')",js)
        self.assertIn("post('td/stop-all')",js)
        self.assertIn('tdDisconnect',js)
if __name__=='__main__':unittest.main()
