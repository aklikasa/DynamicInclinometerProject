# -*- coding: utf-8 -*-
"""PLC温箱PV初步稳定与最终目标带判据测试；无硬件依赖。"""
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from thermal_chamber_stability import chamber_stability_status, chamber_band_status


class ChamberStabilityTests(unittest.TestCase):
    def make_trace(self, fn, duration=300, dt=1.0):
        n = int(duration / dt)
        return [(i * dt, float(fn(i * dt))) for i in range(n + 1)]

    def test_initial_gate_accepts_small_stable_oscillation(self):
        trace = self.make_trace(lambda t: 25.0 + (0.1 if int(t) % 2 else -0.1))
        ok, covered, span, slope = chamber_stability_status(trace, 300.0)
        self.assertTrue(ok)
        self.assertGreaterEqual(covered, 295.0)
        self.assertLessEqual(span, 0.3 + 1e-9)
        self.assertLessEqual(abs(slope), 0.05)

    def test_initial_gate_rejects_continuing_drift(self):
        # 0.06°C/min，虽然处在±1°C内，但斜率超过0.05°C/min。
        trace = self.make_trace(lambda t: 24.8 + t * 0.001)
        ok, _, span, slope = chamber_stability_status(trace, 300.0)
        self.assertFalse(ok)
        self.assertLessEqual(span, 0.3 + 1e-9)
        self.assertGreater(abs(slope), 0.05)

    def test_initial_gate_rejects_large_peak_to_peak(self):
        trace = self.make_trace(lambda t: 25.0 + (0.2 if int(t) % 2 else -0.2))
        ok, _, span, _ = chamber_stability_status(trace, 300.0)
        self.assertFalse(ok)
        self.assertGreater(span, 0.3)

    def test_initial_gate_rejects_short_coverage(self):
        trace = self.make_trace(lambda t: 25.0, duration=120)
        self.assertFalse(chamber_stability_status(trace, 120.0)[0])

    def test_initial_gate_rejects_large_sampling_gap(self):
        trace = [(0.0,25.0),(1.0,25.0),(2.0,25.0),(30.0,25.0),
                 (60.0,25.0),(90.0,25.0),(120.0,25.0),(150.0,25.0),
                 (180.0,25.0),(210.0,25.0),(240.0,25.0),(270.0,25.0),(300.0,25.0)]
        self.assertFalse(chamber_stability_status(trace,300.0)[0])

    def test_final_gate_accepts_target_plus_minus_point_one(self):
        trace = self.make_trace(lambda t: 24.9 if int(t) % 2 else 25.1)
        ok, covered, max_dev = chamber_band_status(trace,300.0,25.0,0.1)
        self.assertTrue(ok)
        self.assertGreaterEqual(covered,295.0)
        self.assertLessEqual(max_dev,0.1 + 1e-9)

    def test_final_gate_rejects_outlier(self):
        trace = self.make_trace(lambda t: 25.11 if int(t)==150 else 25.0)
        self.assertFalse(chamber_band_status(trace,300.0,25.0,0.1)[0])

    def test_final_gate_rejects_stale_data(self):
        trace = self.make_trace(lambda t:25.0)
        self.assertFalse(chamber_band_status(trace,320.0,25.0,0.1)[0])

    def test_slope_is_reported_in_celsius_per_minute(self):
        trace = self.make_trace(lambda t: 20.0 + t/60.0*0.04)
        ok, _, _, slope = chamber_stability_status(trace,300.0)
        self.assertTrue(ok)
        self.assertAlmostEqual(slope,0.04,places=6)


if __name__ == '__main__':
    unittest.main(verbosity=2)
