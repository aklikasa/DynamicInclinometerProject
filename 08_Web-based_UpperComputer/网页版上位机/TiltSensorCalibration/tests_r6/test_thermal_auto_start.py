import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from thermal_auto_arrival import initial_stages
from thermal_production_quality import validated_runtime_policy, missing_at_temperature


class AutoArrivalTests(unittest.TestCase):
    def test_room_to_minus40_has_bounded_steps(self):
        stages=initial_stages(25,-40,5)
        self.assertEqual(stages[0],20)
        self.assertEqual(stages[-1],-35)
        self.assertEqual(len(stages),12)
        self.assertTrue(all(abs(b-a)<=5 for a,b in zip([25]+stages, stages+[-40])))

    def test_reverse(self):
        a=initial_stages(-40,85,5)
        self.assertEqual(len(a),24)
        self.assertEqual(a[0],-35)
        self.assertEqual(a[-1],80)

    def test_near_enough_skips_intermediates(self):
        self.assertEqual(initial_stages(-39,-40,5),[])

    def test_reject_out_of_envelope(self):
        with self.assertRaises(ValueError):initial_stages(110,-40,5)
        with self.assertRaises(ValueError):initial_stages(25,-40,100)

    def test_runtime_policy(self):
        p=dict(pv_pause_c=2.2,pv_hold_seconds=60,resoak_pv_c=3.0,
               resoak_hold_seconds=60,chip_span_c=.3,chip_span_hold_seconds=60,
               chip_slope_c_per_min=.1,chip_slope_hold_seconds=120,
               recovery_pv_c=.75,recovery_chip_span_c=.2,recovery_chip_slope_c_per_min=.08)
        self.assertEqual(validated_runtime_policy(p)['pv_pause_c'],2.2)
        p['recovery_pv_c']=2.3
        with self.assertRaises(ValueError):validated_runtime_policy(p)

    def test_no_step_skip(self):
        steps=[dict(step_id=k) for k in ['A1','A2','G1']]
        rows=[dict(step_id='A1',temperature_target_c=-40)]
        self.assertEqual(missing_at_temperature(-40,steps,rows),['A2','G1'])
        rows += [dict(step_id='A2',temperature_target_c=-40),dict(step_id='G1',temperature_target_c=-40)]
        self.assertEqual(missing_at_temperature(-40,steps,rows),[])

if __name__=='__main__':unittest.main()
