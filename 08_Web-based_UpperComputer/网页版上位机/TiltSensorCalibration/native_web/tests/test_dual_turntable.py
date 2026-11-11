"""No physical hardware accessed; fake DLL only."""
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from native_web import device_service as dev

class Fake2TD:
    INNER_ROTATION_AXIS=0
    OUTER_ROTATION_AXIS=2
    def __init__(self):self.opened=False;self.motion_calls=0;self.speed=0.0;self.port=None
    def twoTD600_openPort(self, port, baud):self.opened=True;self.port=port;return True
    def twoTD600_closePort(self):self.opened=False
    def twoTD600_getPositionRaw(self, axis):return 12.0 if axis==0 else -13.0
    def twoTD600_getSpeedRaw(self, axis):return self.speed
    def twoTD600_getRunMode(self, axis):return '静止' if self.speed==0 else '速率运动'
    def twoTD600_getAxisEnable(self, axis):return False
    def twoTD600_getAxisFindZero(self, axis):return True
    def twoTD600_getAxisNormal(self, axis):return True

class DualTurntableOfflineTest(unittest.TestCase):
    def new_service(self):
        with patch.object(dev,'SETTINGS_FILE',Path(tempfile.gettempdir())/'__WK_no_saved_dual_turntable_2026.json'):
            return dev.DeviceService()
    def test_two_models_separate_and_defaults(self):
        s=self.new_service()
        self.assertEqual(s.settings['td_port'],'COM4')
        self.assertNotIn(s.settings['td_port'],(s.settings['wk_inner'],s.settings['wk_outer']))
        obj=s.status()
        self.assertFalse(obj['td']['connected'])
        self.assertIsNone(obj['td']['inner'])
        self.assertFalse(obj['td']['identity_verified'])
        self.assertFalse(obj['capabilities']['imu_calibration'])
    def test_bad_td_port_rejected(self):
        s=self.new_service()
        for bad in ('/dev/tty2','COM0','COM1 && del','COM1000'):
            with self.assertRaises(ValueError):s.update_settings({'td_port':bad})
    def test_fake_td_readback_is_explicitly_not_verified(self):
        s=self.new_service();fake=Fake2TD();s._td_driver=lambda:fake
        try:
            result=s.td_connect()
            self.assertIn('确认物理设备身份',result)
            snap=s.status()['td']
            self.assertTrue(snap['connected'])
            self.assertTrue(snap['reading'])
            self.assertFalse(snap['identity_verified'])
            self.assertAlmostEqual(snap['inner']['angle'],12.0)
            with self.assertRaises(ValueError):s.update_settings({'td_port':'COM6'})
            self.assertIn('关闭',s.td_disconnect())
            self.assertFalse(fake.opened)
        finally:
            s.td_stop.set()
            if s.td_thread:s.td_thread.join(1)
    def test_moving_td_refuses_to_disconnect(self):
        s=self.new_service();fake=Fake2TD();s._td_driver=lambda:fake
        try:
            s.td_connect();fake.speed=1.4
            with self.assertRaises(RuntimeError):s.td_disconnect()
            self.assertTrue(fake.opened)
            fake.speed=0
            self.assertIn('关闭',s.td_disconnect())
        finally:
            s.td_stop.set()
            if s.td_thread:s.td_thread.join(1)
    def test_stale_data_cleared(self):
        s=self.new_service();s.td_connected=True
        s.td_state.update(inner={'angle':3.0},outer={'angle':-4.0},last_monotonic=time.monotonic()-100)
        snap=s.status()['td']
        self.assertFalse(snap['reading'])
        self.assertIsNone(snap['inner'])
    def test_td_port_conflict_with_wk_rejected(self):
        s=self.new_service();s.wk_ports_open=True
        s.settings['td_port']=s.settings['wk_inner']
        fake=Fake2TD();s._td_driver=lambda:fake
        with self.assertRaises(ValueError):s.td_connect()
        self.assertFalse(fake.opened)

if __name__=='__main__':unittest.main()
