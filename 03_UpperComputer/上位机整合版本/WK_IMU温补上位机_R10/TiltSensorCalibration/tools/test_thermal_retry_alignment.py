# -*- coding: utf-8 -*-
"""温补/常温失败重试次数一致性回归（无需PLC、转台、Qt或串口）。

只验证质量不合格路径；危险的硬件/通信异常仍走原立即中止逻辑。
"""
import ast
import copy
import sys
import types
import unittest
import numpy as np
from pathlib import Path
from threading import Lock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from production_calibration import load_profile

SOURCE = ROOT / 'form/form_thermal_compensation.py'
parsed = ast.parse(SOURCE.read_text(encoding='utf-8'))
cls = next(n for n in parsed.body if isinstance(n, ast.ClassDef)
           and n.name == 'FormThermalCompensation')
tick = copy.deepcopy(next(n for n in cls.body if isinstance(n, ast.FunctionDef)
                          and n.name == '_tick'))


class Clock:
    value = 100.0
    def monotonic(self):
        return self.value


clock = Clock()
imu = types.SimpleNamespace(data_lock=Lock(), data_update_count=1,
                            acc_fs=8, gyro_fs=250, data_odr=208)

def bad_segment(*args, **kwargs):
    raise ValueError('模拟：采样质量不合格')

ns = dict(time=clock, tiltSensorRawData=imu,
          tilt_sensor_calibration_queue_drop_count_get=lambda: 0,
          robust_segment=bad_segment, np=np,
          _platform_gravity_vector=lambda *args: np.array([0.0, 0.0, 1.0]),
          _platform_angular_rate=lambda *args: np.array([5.0, 0.0, 0.0]))
runner = ast.ClassDef(name='Runner', bases=[], keywords=[], decorator_list=[],
                      body=[tick])
exec(compile(ast.fix_missing_locations(ast.Module(body=[runner], type_ignores=[])),
             str(SOURCE), 'exec'), ns)


class Reporter:
    def setText(self, value):
        self.text = value
    def setValue(self, value):
        self.value = value


class Fake(ns['Runner']):
    def __init__(self, mode='static', static_retries=5, rate_retries=3):
        self.log = []
        self.aborted = []
        self.stop_count = 0
        self.label = Reporter()
        self.progress = Reporter()
        self.sample_seconds = types.SimpleNamespace(value=lambda: 5)
        self.task = {
            'manual': True, 'phase': 'sample', 'sample_start': 0,
            'rows': [], 'axis_model': 'outer_x_inner_z',
            'phase_start': 0, 'frames': [object()], 'retry_count': 0,
            'profile': {'quality': {'static_sample_max_retries': static_retries,
                                    'rate_sample_max_retries': rate_retries,
                                    'temperature_span_max_c': 0.5}},
            'steps': [{'mode': mode, 'sensor': 'gyro' if mode == 'rate' else 'acc',
                       'step_id': 'RETRY_TEST', 'split': 'fit', 'rotation_axis': 'inner',
                       'target_rate_dps': 5.0}],
            'temps': [25.0], 'temp_i': 0, 'step_i': 0,
            'temperature_split_by_setpoint': {25.0: 'fit'},
            'baseline_config': (8, 250, 208),
            'last_imu_count': 1, 'last_imu_change': 100.0,
        }
    def _motion_status(self): pass
    def _collect(self): pass
    def _check_rate_feedback(self): pass
    def _log(self, value): self.log.append(value)
    def _stop_axes(self):
        self.stop_count += 1
        return True
    def _begin_wk_stop_wait(self, task, now, retry=False):
        task['phase'] = 'wait_stop_retry' if retry else 'wait_stop'
    def _next_step_after_result(self, now):
        self.task['retry_count']=0
        self.task['step_i']+=1
        self.task['phase']='position'
    def _defer_current_step(self, now, reason):
        self.deferred_reason=str(reason)
        self.task['retry_count']=0
        self.task['phase']='wait_stop_defer' if self.task['steps'][self.task['step_i']]['mode']=='rate' else 'position'
        if self.task['phase']=='wait_stop_defer':self._stop_axes()
        else:self.task['step_i']+=1
    def _save_partial(self, *args): pass
    def _abort(self, value):
        self.aborted.append(value)
        self.task = None


def attempt(f):
    """模拟等待实际停车/重新定位后开始的新采样段。"""
    if f.task is not None:
        f.task['phase'] = 'sample'
        f.task['sample_start'] = 0
        f.task['frames'] = [object()]
    f._tick()


class ThermalRetryAlignmentTests(unittest.TestCase):
    def test_ambient_quality_config_is_the_same_source(self):
        profile = load_profile(str(ROOT))
        self.assertEqual(profile['quality']['static_sample_max_retries'], 5)
        self.assertEqual(profile['quality']['rate_sample_max_retries'], 3)
        self.assertEqual(profile['quality']['temperature_span_max_c'], 1.0)
        src = SOURCE.read_text(encoding='utf-8')
        self.assertIn("profile['quality']['temperature_span_max_c']=0.5", src)

    def test_static_allows_five_retries_then_defers_on_sixth_failure(self):
        f = Fake(mode='static')
        for n in range(1, 6):
            attempt(f)
            self.assertEqual(f.task['retry_count'], n)
            self.assertEqual(f.task['phase'], 'wait_position')
            self.assertEqual(f.task['step_i'], 0)
            self.assertEqual(f.stop_count, 0)
            self.assertFalse(f.aborted)
        attempt(f)
        self.assertEqual(f.task['step_i'],1)
        self.assertFalse(f.aborted)
        self.assertIn('共6次',f.deferred_reason)

    def test_rate_allows_three_retries_with_stop_confirmation_path(self):
        f = Fake(mode='rate')
        for n in range(1, 4):
            attempt(f)
            self.assertEqual(f.task['retry_count'], n)
            self.assertEqual(f.task['phase'], 'wait_stop_retry')
            self.assertEqual(f.task['step_i'], 0)
            self.assertEqual(f.stop_count, n)
            self.assertFalse(f.aborted)
        attempt(f)
        self.assertEqual(f.task['phase'],'wait_stop_defer')
        self.assertFalse(f.aborted)
        self.assertEqual(f.stop_count, 4)
        self.assertIn('共4次', f.deferred_reason)

    def test_success_after_retries_accepts_only_good_static_data(self):
        f = Fake(mode='static')
        attempt(f)
        attempt(f)
        self.assertEqual(f.task['retry_count'], 2)
        self.assertEqual(f.task['rows'], [])
        def good_segment(*args, **kwargs):
            return dict(frame_count=56, accepted_frames=55, temperature_mean_c=25.0,
                        inner_actual_mean_deg=0.0, outer_actual_mean_deg=0.0,
                        acc_raw_mean_g=[0.0, 0.0, 1.0])
        old = ns['robust_segment']
        try:
            ns['robust_segment'] = good_segment
            attempt(f)
        finally:
            ns['robust_segment'] = old
        self.assertFalse(f.aborted)
        self.assertEqual(f.task['retry_count'], 0)
        self.assertEqual(f.task['step_i'], 1)
        self.assertEqual(len(f.task['rows']), 1)
        self.assertEqual(f.task['rows'][0]['step_id'], 'RETRY_TEST')

    def test_good_dynamic_still_requires_stop_confirmation_before_commit(self):
        f = Fake(mode='rate')
        attempt(f)
        self.assertEqual(f.task['retry_count'], 1)
        def good_segment(*args, **kwargs):
            return dict(frame_count=57, accepted_frames=55, temperature_mean_c=25.0,
                        inner_actual_mean_deg=0.0, outer_actual_mean_deg=0.0,
                        inner_rate_mean_dps=5.0, outer_rate_mean_dps=0.0,
                        gyro_raw_mean_dps=[5.0, 0.0, 0.0])
        old = ns['robust_segment']
        try:
            ns['robust_segment'] = good_segment
            attempt(f)
        finally:
            ns['robust_segment'] = old
        self.assertFalse(f.aborted)
        self.assertEqual(f.stop_count, 2)
        self.assertEqual(f.task['phase'], 'wait_stop')
        self.assertEqual(f.task['rows'], [])
        self.assertEqual(f.task['step_i'], 0)
        self.assertIn('pending_dynamic_row', f.task)

    def test_configured_counts_are_read_not_hardcoded(self):
        f = Fake(mode='static', static_retries=1)
        attempt(f)
        self.assertEqual(f.task['retry_count'], 1)
        attempt(f)
        self.assertIn('共2次', f.deferred_reason)
        f = Fake(mode='rate', rate_retries=0)
        attempt(f)
        self.assertIn('共1次', f.deferred_reason)
        self.assertEqual(f.stop_count,1) # 质量失败依然必须停车确认


if __name__ == '__main__':
    unittest.main(verbosity=2)
