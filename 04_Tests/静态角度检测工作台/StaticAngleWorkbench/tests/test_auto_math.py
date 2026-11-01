import math
import unittest
from app.core.measurement import median_filter3,process_point,angle_error
from app.core.scan_plan import make_scan_plan
from app.core.calibration import Calibration
from pathlib import Path

class AutomaticMathTests(unittest.TestCase):
    def test_plan(self):
        p=make_scan_plan(); self.assertEqual(len(p),74)
        self.assertEqual([p[0].outer_command_deg,p[36].outer_command_deg],[180,180])
        self.assertEqual([p[37].channel,p[37].inner_deg],['X',90])
    def test_circular(self):
        self.assertAlmostEqual(angle_error(-179,179),2)
        self.assertAlmostEqual(angle_error(179,-179),-2)
    def test_outlier(self):
        vals=[(0.1,0.2,1.)]*15+[(500.,500.,500.)]
        keep,drop=median_filter3(vals)
        self.assertEqual((len(keep),drop),(15,1))
    def test_point(self):
        cal=Calibration.load(Path(__file__).resolve().parents[1]/'examples'/'accel_calibration_example.json')
        # Simulate a raw reading for reference platform [0,0,1]
        import json
        obj=json.loads(cal.path.read_text(encoding='utf-8-sig'))
        F=obj['forward_platform_to_raw_matrix'];b=cal.bias
        raw=tuple(F[i][2]+b[i] for i in range(3))
        frames=[tuple(raw for _ in range(16)) for _ in range(60)]
        result=process_point(frames,cal,'Y',0)
        self.assertLess(abs(result['error_deg']),.01)
        self.assertEqual(result['accepted_frames'],60)
    def test_not_enough_frames(self):
        cal=Calibration.load(Path(__file__).resolve().parents[1]/'examples'/'accel_calibration_example.json')
        with self.assertRaises(ValueError): process_point([((0.,0.,1.),)*16]*10,cal,'Y',0)
if __name__=='__main__':unittest.main()
