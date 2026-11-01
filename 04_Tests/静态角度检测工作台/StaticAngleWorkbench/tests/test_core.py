"""不需要实机、串口和 PySide6 的核心逻辑测试。"""
from pathlib import Path
import sys
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.core.calibration import Calibration
from app.devices.imu_protocol import crc16, decode, WORDS, IMUProtocolError


class ProtocolTests(unittest.TestCase):
    def test_crc(self):
        packet = bytes([1, 3, 0x03, 0xE8, 0, 104])
        crc = crc16(packet)
        self.assertEqual(crc16(packet + crc.to_bytes(2, 'little')), 0)

    def test_decode(self):
        words = [0] * WORDS
        words[0] = 1
        words[1:17] = [1000]*16
        words[17:33] = [2000]*16
        words[33:49] = [3000]*16
        words[97] = 0
        words[98] = 123
        words[100] = 2
        words[101] = 2000
        words[102] = 104
        result = decode(words)
        self.assertTrue(result.valid)
        self.assertEqual(result.tick_ms, 123)
        self.assertAlmostEqual(result.accel_g[0], .061)
        self.assertAlmostEqual(result.accel_g[1], .122)
        self.assertAlmostEqual(result.accel_g[2], .183)
        words[1:97] = [0]*96
        self.assertFalse(decode(words).valid)

    def test_calibration(self):
        cal = Calibration.load(ROOT / 'examples' / 'accel_calibration_example.json')
        self.assertEqual(len(cal.bias), 3)
        self.assertEqual(len(cal.matrix), 3)
        result = cal.correct(cal.bias)
        self.assertTrue(all(abs(n) < 1e-12 for n in result))
        self.assertFalse(cal.approved)


if __name__ == '__main__':
    unittest.main()
