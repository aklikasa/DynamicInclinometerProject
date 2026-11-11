# -*- coding: utf-8 -*-
"""No actual motors are touched. Fail-closed tests for the new local Web UI."""
import os
import sys
import time
import unittest
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from native_web.device_service import DeviceService


class FakeTD:
    INNER_ROTATION_AXIS=0
    OUTER_ROTATION_AXIS=2
    def __init__(self,enabled=True,fault=False):
        self.enabled=enabled
        self.fault=fault
        self.moves=[]
        self.stops=[]
        self.enable_calls=[]
        self.angle={0:15.0,2:45.0}
        self.speed={0:0.0,2:0.0}
        self.motion_mode={0:'静止',2:'静止'}
    def twoTD600_getPositionRaw(self,a):return self.angle[a]
    def twoTD600_getSpeedRaw(self,a):return self.speed[a]
    def twoTD600_getRunMode(self,a):return self.motion_mode[a]
    def twoTD600_getAxisEnable(self,a):return self.enabled
    def twoTD600_getAxisNormal(self,a):return True
    def twoTD600_getAxisFindZero(self,a):return True
    def twoTD600_getAxisDriverFault(self,a):return self.fault
    def twoTD600_getAxisOverSpeed(self,a):return False
    def twoTD600_getAxisOverDiff(self,a):return False
    def twoTD600_getAxisOverVoltage(self,a):return False
    def twoTD600_getAxisUpLimit(self,a):return False
    def twoTD600_getAxisDownLimit(self,a):return False
    def twoTD600_getAxisMoveInPlace(self,a):return True
    def twoTD600_SetAxisPosition(self,a,pos,speed):
        self.moves.append((a,pos,speed));return True
    def twoTD600_SetAxisOpposition(self,a,delta,speed):
        self.moves.append((a,delta,speed));return True
    def twoTD600_SetAxisStop(self,a):self.stops.append(a);return True
    def twoTD600_SetAxisEnable(self,a):self.enable_calls.append(a);self.enabled=True;return True

class ClickOnlyTests(unittest.TestCase):
    def setUp(self):
        self.s=DeviceService();self.td=FakeTD()
        self.s.td_mod=self.td
        self.s._td_driver=lambda:self.td
        self.s.td_connected=True
        self.s.td_state.update(last_monotonic=time.monotonic(),inner={},outer={})
    def valid(self,**more):
        return dict(axis='inner',step_deg=1.0,speed_dps=1.0,safety_ack='PHYSICAL_ESTOP_READY',**more)
    def test_inert_on_init_and_no_autoscan_startup(self):
        src=(Path(__file__).resolve().parents[1]/'server.py').read_text(encoding='utf8')
        self.assertNotIn('SERVICE.start_td_auto_scan()',src)
        self.assertNotIn('td/auto/configure',src)
        self.assertEqual(self.td.moves,[])
    def test_motion_requires_physical_ack(self):
        with self.assertRaisesRegex(ValueError,'现场确认'):
            self.s.td_jog(dict(axis='inner',step_deg=1,speed_dps=1))
        self.assertEqual(self.td.moves,[])
    def test_zero_nonfinite_rejected_and_no_five_degree_cap(self):
        for value in [0,float('nan'),float('inf')]:
            with self.assertRaises(ValueError):self.s.td_jog(dict(axis='inner',step_deg=value,speed_dps=1,safety_ack='PHYSICAL_ESTOP_READY'))
        self.assertEqual(self.td.moves,[])
        self.td.angle[2]=0.0
        self.s.td_jog(dict(axis='inner',step_deg=12.375,speed_dps=1,safety_ack='PHYSICAL_ESTOP_READY'))
        self.assertEqual(self.td.moves,[(0,12.375,1.)])
    def test_original_r7_speed_limit(self):
        with self.assertRaisesRegex(ValueError,'速度'):
            self.s.td_jog(dict(axis='outer',step_deg=1.0,speed_dps=60.0,safety_ack='PHYSICAL_ESTOP_READY'))
        self.assertEqual(self.td.moves,[])
        self.s.td_jog(dict(axis='outer',step_deg=1.0,speed_dps=9.0,safety_ack='PHYSICAL_ESTOP_READY'))
        self.assertEqual(self.td.moves,[(2,1.0,9.0)])
    def test_disabled_axis_rejects_motion(self):
        self.td.enabled=False
        with self.assertRaisesRegex(RuntimeError,'未使能'):
            self.s.td_jog(self.valid())
        self.assertFalse(self.td.moves)
    def test_explicit_enable_after_confirmation(self):
        self.td.enabled=False
        with self.assertRaises(ValueError):self.s.td_enable_axes({})
        self.assertFalse(self.td.enable_calls)
        self.s.td_enable_axes({'safety_ack':'PHYSICAL_ESTOP_READY'})
        self.assertTrue(self.td.enabled)
        self.assertIn(0,self.td.enable_calls)

    def test_fault_refuses_motion(self):
        self.td.fault=True
        with self.assertRaisesRegex(RuntimeError,'故障'):
            self.s.td_jog(self.valid())
        self.assertFalse(self.td.moves)
    def test_stale_feedback_rejected(self):
        self.s.td_state['last_monotonic']-=9
        with self.assertRaisesRegex(RuntimeError,'反馈过期'):
            self.s.td_jog(self.valid())
        self.assertFalse(self.td.moves)
    def test_single_step_real_command_path_and_arrival_feedback(self):
        self.td.angle[2]=0.0
        m=self.s.td_jog(self.valid())
        self.assertEqual(m['state'],'moving')
        self.assertEqual(self.td.moves,[(0,1.0,1.0)])
        with self.assertRaisesRegex(RuntimeError,'运动、停车或故障'):
            self.s.td_jog(self.valid())
        self.td.angle[0]=16.0
        self.s._td_monitor_motion({})
        self.assertEqual(self.s.td_motion['state'],'complete')
    def test_software_stop_uses_both_axes(self):
        self.s.td_stop_all()
        self.assertEqual(self.td.stops,[0,2])
        self.assertEqual(self.s.td_motion['state'],'stopping')
    def test_scan_ambiguous_refuses_all_probes(self):
        self.s.td_connected=False
        self.s.serial_ports=lambda:[dict(device='COM2'),dict(device='COM3')]
        with self.assertRaisesRegex(ValueError,'多个'):
            self.s.td_scan_connect()
        self.assertEqual(self.td.moves,[])
    def test_scan_unique_uses_only_one_unreserved_port(self):
        self.s.td_connected=False
        self.s.settings.update(port='COM5',wk_inner='COM8',wk_outer='COM9',td_port='COM4')
        self.s.serial_ports=lambda:[dict(device=x) for x in ['COM5','COM7','COM8']]
        connections=[]
        self.s.td_connect=lambda:connections.append(self.s.settings['td_port'])
        self.s.td_scan_connect()
        self.assertEqual(connections,['COM7'])
    def test_ui_has_exact_button_no_identity_control(self):
        ui=(Path(__file__).resolve().parents[1]/'index.html').read_text(encoding='utf8')
        self.assertIn('id="tdScanConnect"',ui)
        self.assertNotIn('tdBindAuto',ui)
        self.assertNotIn('tdDisableAuto',ui)
        self.assertNotIn('设备识别码',ui)

if __name__=='__main__':unittest.main()
