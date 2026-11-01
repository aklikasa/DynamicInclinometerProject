import json
import tempfile
import unittest
from pathlib import Path
from app.core.calibration import Calibration

class CalibrationTests(unittest.TestCase):
    def test_real_json(self):
        cal = Calibration.load(Path(__file__).resolve().parents[1] / 'examples' / 'accel_calibration_example.json')
        self.assertEqual(len(cal.bias), 3)
        self.assertEqual(len(cal.matrix), 3)
        self.assertEqual(cal.device_serial,'0002')
        self.assertFalse(cal.approved)
        self.assertEqual(cal.correct(cal.bias), (0.,0.,0.))

    def test_reject_invalid(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'data.json'
            path.write_text(json.dumps({'raw_accel_bias_g':[0,0,0], 'raw_to_platform_matrix':[[0,0,0]]*3}),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'不可逆'):
                Calibration.load(path)

if __name__ == '__main__': unittest.main()
