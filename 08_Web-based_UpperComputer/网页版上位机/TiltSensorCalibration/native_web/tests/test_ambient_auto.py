# -*- coding: utf-8 -*-
"""Offline fake-hardware checks; never loads physical manufacturer DLL."""
import math
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from native_web.ambient_auto import AmbientAuto
from native_web.ambient_capture import AmbientGuided
from native_web.device_service import DeviceService

class FakeRig:
    INNER_ROTATION_AXIS=0
    OUTER_ROTATION_AXIS=2
    def __init__(self):
        self.angle={'inner':0.,'outer':0.}
        self.speed={'inner':0.,'outer':0.}
        self.commands=[]
        self.healthy=True
    def axis(self,x):return 'inner' if x==0 else 'outer'
    def twoTD600_getAxisLock(self,axis):return False
    def twoTD600_getAxisMoveInPlace(self,axis):return True
    def twoTD600_SetAxisPosition(self,axis,angle,speed):
        self.commands.append(('position',self.axis(axis),angle,speed))
        self.angle[self.axis(axis)]=angle
        return True
    def twoTD600_SetAxisVelocity(self,axis,speed,accel):
        self.commands.append(('rate',self.axis(axis),speed,accel))
        self.speed[self.axis(axis)]=speed
        return True
    def twoTD600_SetAxisStop(self,axis):
        self.commands.append(('stop',self.axis(axis)))
        self.speed[self.axis(axis)]=0.
        return True

class FakeClock:
    def __init__(self):self.value=100.
    def now(self):return self.value
    def sleep(self,delta):self.value+=max(delta,.005)

class FakeService:
    def __init__(self,rig,clk):
        self.rig=rig;self.clk=clk
        self.td_io_lock=threading.RLock()
        self.td_motion_lock=threading.RLock()
        self.td_motion={'state':'idle'}
        self.td_connected=True
        self.count=100
    def status(self):
        self.count+=1
        return {'imu':{'reading':True,'recording':False,'success_count':self.count},
            'td':{'reading':True,'feedback_age_ms':20,'motion':{'state':'idle'}}}
    def _td_driver(self):return self.rig
    def _td_safety_snapshot(self):
        if not self.rig.healthy:raise RuntimeError('模拟驱动故障')
        return {k:{'position':self.rig.angle[k], 'speed':self.rig.speed[k], 'mode':'静止'} for k in ('inner','outer')}

class FakeGuided:
    def __init__(self):self.session=None;self.collecting=False;self.records=[];self.count=0
    def start(self,body):
        self.count+=1
        self.session={'run_id':'TEST_REAL_MOTION_PATH_'+str(self.count),'kind':body['kind'],'index':0,'state':'ready',
            'profile':{'timing':{'settle_seconds':.06},'quality':{'static_sample_max_retries':1,'rate_sample_max_retries':1},
                       'rates':{'maximum_command_rate_dps':10}},
            'steps':[{'step_id':'ACC_FIT_01','mode':'static','inner_deg':90.,'outer_deg':90.},
                     {'step_id':'GYRO_FIT_01','mode':'rate','inner_deg':0.,'outer_deg':180.,
                      'rotation_axis':'outer','target_rate_dps':2.0}]}
        return {'run_id':self.session['run_id']}
    def _store(self):pass
    def _audit(self,*args):pass
    def begin(self):self.collecting=True;self.session['state']='collecting'
    def status(self):return {'required_seconds':.1}
    def finish(self):
        self.collecting=False
        self.session['index']+=1
        self.session['state']='complete' if self.session['index']==len(self.session['steps']) else 'ready'
        return dict(index=self.session['index'],state=self.session['state'])
    def cancel(self):self.session['state']='cancelled';self.collecting=False

class AutoTests(unittest.TestCase):
    def setUp(self):
        self.clock=FakeClock();self.rig=FakeRig();self.service=FakeService(self.rig,self.clock)
        self.guided=FakeGuided()
        self.auto=AmbientAuto(self.service,self.guided,sleep=self.clock.sleep,clock=self.clock.now)
        self.request={'kind':'acc','device_serial':'DTS123456','gravity_sign':1,
                      'safety_ack':'PHYSICAL_ESTOP_READY','motion_ack':'SUPERVISED_AUTO_MOVEMENT'}
    def test_commissioning_absent_denies_any_motor_commands(self):
        with patch.object(self.auto,'_is_commissioned',return_value=False):
            with self.assertRaisesRegex(RuntimeError,'现场'):
                self.auto.start(self.request)
        self.assertEqual(self.rig.commands,[])
    def test_no_ack_denies_auto(self):
        with patch.object(self.auto,'_is_commissioned',return_value=True):
            with self.assertRaises(ValueError):self.auto.start({**self.request,'motion_ack':''})
        self.assertEqual(self.rig.commands,[])
    def test_supervised_auto_position_rate_capture_and_stop(self):
        with patch.object(self.auto,'_is_commissioned',return_value=True):
            self.auto.start(self.request)
            self.auto.worker.join(timeout=3)
        self.assertFalse(self.auto.worker.is_alive())
        self.assertEqual(self.auto.status()['state'],'completed',self.auto.status())
        self.assertEqual(self.guided.session['index'],2)
        actions=self.rig.commands
        self.assertIn(('position','inner',90.,3.),actions)
        self.assertIn(('position','outer',90.,3.),actions)
        self.assertIn(('rate','outer',2.,1.),actions)
        self.assertTrue(('stop','inner') in actions and ('stop','outer') in actions)
        # Before every inner movement, outer was parked to 0 degrees.
        inner_index=actions.index(('position','inner',90.,3.))
        self.assertEqual(self.rig.angle['inner'],0.)
        self.assertTrue(inner_index<actions.index(('position','outer',90.,3.)))
    def test_fault_before_position_does_not_move(self):
        self.rig.healthy=False
        with patch.object(self.auto,'_is_commissioned',return_value=True):
            self.auto.start(self.request)
            self.auto.worker.join(timeout=3)
        self.assertNotEqual(self.auto.status()['state'],'completed')
        self.assertNotIn('position',[a[0] for a in self.rig.commands])
    def test_one_click_both_runs_in_sequence_and_keeps_two_reports(self):
        with patch.object(self.auto,'_is_commissioned',return_value=True):
            self.auto.start({**self.request,'kind':'both'})
            self.auto.worker.join(timeout=3)
        self.assertFalse(self.auto.worker.is_alive())
        status=self.auto.status()
        self.assertEqual(status['state'],'completed',status)
        self.assertEqual(status['kind'],'both')
        self.assertEqual(status['completed_run_ids'],['TEST_REAL_MOTION_PATH_1','TEST_REAL_MOTION_PATH_2'])
        self.assertEqual(self.guided.count,2)
        self.assertEqual(self.guided.session['kind'],'gyro')
        self.assertEqual(len([a for a in self.rig.commands if a[0]=='rate']),2)

    def test_abort_during_motion_stops_both_and_never_advances(self):
        def sleep_then_abort(seconds):
            self.clock.sleep(seconds)
            if self.auto.phase=='position' and not self.auto.abort_event.is_set():
                self.auto.request_abort()
        self.auto._sleep=sleep_then_abort
        with patch.object(self.auto,'_is_commissioned',return_value=True):
            self.auto.start(self.request)
            self.auto.worker.join(timeout=3)
        self.assertFalse(self.auto.worker.is_alive())
        self.assertEqual(self.auto.status()['state'],'aborted',self.auto.status())
        self.assertEqual(self.guided.session['index'],0)
        self.assertIn(('stop','inner'),self.rig.commands)
        self.assertIn(('stop','outer'),self.rig.commands)

    def test_motion_feedback_fault_triggers_stop_attempt(self):
        def sleep_then_fault(seconds):
            self.clock.sleep(seconds)
            if self.auto.phase=='position':self.rig.healthy=False
        self.auto._sleep=sleep_then_fault
        with patch.object(self.auto,'_is_commissioned',return_value=True):
            self.auto.start(self.request)
            self.auto.worker.join(timeout=3)
        self.assertFalse(self.auto.worker.is_alive())
        self.assertEqual(self.auto.status()['state'],'fault')
        self.assertEqual(self.guided.session['index'],0)
        self.assertIn(('stop','inner'),self.rig.commands)
        self.assertIn(('stop','outer'),self.rig.commands)

    def test_circular_angle_difference(self):
        self.assertAlmostEqual(self.auto._angle_error(359.,-1.),0.)
    def test_missing_real_encoder_polls_refuses_rate_validation(self):
        with self.assertRaises(ValueError):
            AmbientGuided._rate_diagnostic([], 'inner',2.)
    def test_independent_encoder_angular_velocity_validation(self):
        polls=[{'t':100+i*.12,'inner_deg':5+i*.24,'outer_deg':0.} for i in range(25)]
        r=AmbientGuided._rate_diagnostic(polls,'inner',2.)
        self.assertEqual(r['independent_samples'],24)
        self.assertAlmostEqual(r['mean_dps'],2.,places=5)
        self.assertLess(r['raw_diff_std_dps'],.001)
    def test_service_manual_jog_refused_when_auto_active(self):
        service=DeviceService()
        service.ambient_auto=type('Auto',(),{'is_active':lambda self: True})()
        with self.assertRaisesRegex(RuntimeError,'自动'):
            service.td_jog({'axis':'inner','step_deg':.1,'speed_dps':.5})

if __name__=='__main__':unittest.main()
