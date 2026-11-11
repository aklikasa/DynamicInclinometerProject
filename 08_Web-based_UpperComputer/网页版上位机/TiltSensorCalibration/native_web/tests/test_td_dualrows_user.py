# -*- coding: utf-8 -*-
from pathlib import Path
import sys,time,unittest
root=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(root))
from native_web.device_service import DeviceService
from native_web.ambient_plans import ambient_plan

class FakeVendor:
    INNER_ROTATION_AXIS=0
    OUTER_ROTATION_AXIS=2
    def __init__(self):self.moves=[]
    def twoTD600_getAxisEnable(self,a):return True
    def twoTD600_getAxisNormal(self,a):return True
    def twoTD600_getAxisFindZero(self,a):return True
    def twoTD600_getAxisDriverFault(self,a):return False
    def twoTD600_getAxisOverSpeed(self,a):return False
    def twoTD600_getAxisOverDiff(self,a):return False
    def twoTD600_getAxisOverVoltage(self,a):return False
    def twoTD600_getAxisUpLimit(self,a):return False
    def twoTD600_getAxisDownLimit(self,a):return False
    def twoTD600_getPositionRaw(self,a):return {0:14.0,2:25.0}[a]
    def twoTD600_getSpeedRaw(self,a):return 0.0
    def twoTD600_getRunMode(self,a):return '静止'
    def twoTD600_SetAxisPosition(self,a,pos,speed):self.moves.append((a,pos,speed));return True
    def twoTD600_SetAxisOpposition(self,a,delta,speed):self.moves.append((a,delta,speed));return True

class DualRowsTests(unittest.TestCase):
    def setUp(self):
        self.s=DeviceService();self.fake=FakeVendor();self.s._td_driver=lambda:self.fake
        self.s.td_connected=True
        self.s.td_state.update(last_monotonic=time.monotonic(),inner={},outer={})
    def test_floating_point_input_and_separate_axis_commands(self):
        p={'axis':'outer','step_deg':-2.75,'speed_dps':1.37,'safety_ack':'PHYSICAL_ESTOP_READY'}
        self.s.td_jog(p)
        self.assertEqual(self.fake.moves,[(2,-2.75,1.37)])
    def test_decimal_step_supported(self):
        self.fake.twoTD600_getPositionRaw=lambda a: {0:14.,2:0.}[a]
        self.s.td_jog({'axis':'inner','step_deg':0.75,'speed_dps':0.15,'safety_ack':'PHYSICAL_ESTOP_READY'})
        self.assertEqual(self.fake.moves,[(0,0.75,0.15)])
    def test_r7_speed_guard_preserved(self):
        with self.assertRaisesRegex(ValueError,'60'):
            self.s.td_jog({'axis':'inner','step_deg':1.,'speed_dps':60.,'safety_ack':'PHYSICAL_ESTOP_READY'})
        self.assertEqual(self.fake.moves,[])
    def test_r7_original_plans_readonly(self):
        acc=ambient_plan('acc');gyro=ambient_plan('gyro')
        self.assertEqual(len(acc['steps']),24)
        self.assertEqual(len(gyro['steps']),32)
        self.assertFalse(acc['automatic_execution_available'])
        self.assertTrue(any('60' in x for x in gyro['warnings']))
    def test_real_two_row_ui_and_no_old_dropdowns(self):
        h=(root/'native_web/index.html').read_text(encoding='utf-8')
        js=(root/'native_web/app.js').read_text(encoding='utf-8')
        for key in ['tdInnerStep','tdOuterStep','tdInnerJogSpeed','tdOuterJogSpeed']:
            self.assertIn(f'id="{key}" type="number"',h)
        for key in ['tdInnerMinus','tdInnerPlus','tdOuterMinus','tdOuterPlus']:
            self.assertIn(key,h);self.assertIn(key,js)
        self.assertNotIn('id="tdJogAxis"',h)
        self.assertNotIn('id="tdJogSpeed"',h)
        self.assertNotIn('id="tdJogStep"',h)

if __name__=='__main__':unittest.main()
