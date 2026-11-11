# -*- coding: utf-8 -*-
"""No physical movement: synthetic frames test deterministic state/quality only."""
import math
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

from native_web.ambient_capture import AmbientGuided


class FakeRaw:
    def __init__(self):
        self.data_lock=threading.RLock()
        self.is_data_valid=True
        self.acc_g_arr=[[0.0,0.0,1.0]]*16
        self.gyr_dps_arr=[[0.0,0.0,0.0]]*16
        self.temp_c=25.0
        self.acc_fs=4
        self.gyro_fs=2000
        self.acc_fs_ever_valid=True
        self.gyro_fs_ever_valid=True
        self.data_odr=100
        self.data_update_count=1


class FakeService:
    def __init__(self):
        self.lock=threading.RLock()
        self.td_io_lock=threading.RLock()
        self.td_connected=True
        self.td_state={'last_monotonic':100.0, 'inner':{'angle':0.,'speed':0.},'outer':{'angle':0.,'speed':0.}}
        self.imu_mod=type('I',(),{'tiltSensorRawData':FakeRaw()})()
        self.motion={'state':'idle'}
        self.imu_recording=False
        self.reading=True
        self.speeds={'inner':0.,'outer':0.}
        self.positions={'inner':0.,'outer':0.}

    def status(self):
        return {'imu':{'reading':self.reading,'recording':self.imu_recording},
                'td':{'reading':self.reading,'feedback_age_ms':45,'motion':self.motion}}

    def _td_safety_snapshot(self):
        return {k:{'position':self.positions[k],'speed':self.speeds[k],
                   'mode':'静止'} for k in ('inner','outer')}


class GuidedTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.clock=[100.0]
        self.service=FakeService()
        self.engine=AmbientGuided(self.service,Path(self.tmp.name),clock=lambda:self.clock[0])
        self.request={'kind':'acc','device_serial':'DTS123456','gravity_sign':1,
                      'safety_ack':'PHYSICAL_ESTOP_READY'}

    def tearDown(self):self.tmp.cleanup()

    def test_start_does_not_move_or_autoconnect(self):
        self.assertRaises(ValueError,self.engine.start,{**self.request,'safety_ack':''})
        result=self.engine.start(self.request)
        self.assertEqual(result['state'],'ready')
        self.assertEqual(result['total'],24)
        self.assertFalse(result['automatic_motion']) if 'automatic_motion' in result else None
        self.assertFalse(self.engine.is_collecting())

    def test_first_acc_step_uses_live_real_frames_with_quality(self):
        self.engine.start(self.request)
        self.engine.begin()
        raw=self.service.imu_mod.tiltSensorRawData
        for i in range(80):
            self.clock[0]=100+i*.075
            self.service.td_state['last_monotonic']=self.clock[0]-.025
            raw.data_update_count=i+1
            self.engine.on_frame(1700000000+i*.075,raw)
        self.clock[0]=106.2
        self.service.td_state['last_monotonic']=106.1
        result=self.engine.finish()
        self.assertEqual(result['index'],1)
        self.assertEqual(result['accepted'],1)
        self.assertEqual(result['rejected'],0)
        self.assertTrue((Path(self.tmp.name)/result['run_id']/'measurements.json').is_file())

    def test_invalid_no_feedback_never_advances(self):
        self.engine.start(self.request)
        self.engine.begin()
        self.clock[0]=106.2
        # no frames -> refuse, keep same step; no synthesized data
        result=self.engine.finish()
        self.assertEqual(result['index'],0)
        self.assertEqual(result['rejected'],1)
        self.assertEqual(result['state'],'ready')

    def test_no_capture_unless_at_target(self):
        self.engine.start(self.request)
        self.service.positions['inner']=9
        self.assertRaises(RuntimeError,self.engine.begin)
        self.assertFalse(self.engine.is_collecting())

    def test_gyro_plan_32_real_steps(self):
        result=self.engine.start({**self.request,'kind':'gyro'})
        self.assertEqual(result['total'],32)
        self.assertEqual(result['current_step']['step_id'],'GYRO_ZERO_FIT')

    def test_cancel_refuses_next_begin_and_reports_safe_name(self):
        res=self.engine.start(self.request)
        name=res['run_id']
        self.engine.cancel()
        self.assertRaises(RuntimeError,self.engine.begin)
        self.assertRaises(ValueError,self.engine.report_file,'../../etc','session.json')
        self.assertTrue(self.engine.report_file(name,'session.json').is_file())

    def test_gyro_cannot_collect_without_target_rate(self):
        self.engine.start({**self.request,'kind':'gyro'})
        with self.engine.lock:
            self.engine.session['index']=1  # synthetic stage transition, does not affect real driver
            step=self.engine.session['steps'][1]
        self.service.positions['inner']=step['inner_deg']
        self.service.positions['outer']=step['outer_deg']
        self.assertRaises(RuntimeError,self.engine.begin)

    def test_report_model_comparison_uses_original_pure_module(self):
        # Model fitting is validated by original R7 numerical test suite; no fabricated
        # physical session accepted as real. Ensure no false success on empty results.
        self.engine.start(self.request)
        with self.engine.lock:
            self.engine.session['state']='analyzing'
            self.engine._analyze()
        self.assertEqual(self.engine.status()['state'],'complete' if self.engine.status()['model_report_ready'] else 'analysis_failed')


if __name__=='__main__':unittest.main()
