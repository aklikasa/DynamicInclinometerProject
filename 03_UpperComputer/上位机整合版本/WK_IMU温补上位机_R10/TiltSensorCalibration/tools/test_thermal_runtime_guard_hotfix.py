# -*- coding: utf-8 -*-
"""2026-11: regression suite for live PV/chip-drift hold and safe restart.

These tests are *offline only*: no motor, PLC, or chamber commands.
"""
import ast
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from thermal_runtime_guard import ThermalRuntimeGuard


def feed(guard,start,end,pv=20.,chip=19.,step=1):
    state=('ok','')
    for i in range(start,end+1,step):
        temp=chip(i) if callable(chip) else chip
        value=pv(i) if callable(pv) else pv
        state=guard.observe(float(i),float(value),float(i),float(temp),i)
    return state


class RuntimeGuardRegression(unittest.TestCase):
    def test_original_false_stops_no_longer_force_pause(self):
        # User's PV/chip drift traces: +-0.3 C PV excursion, 0.2 C
        # chip 60s variation and 0.05 C/min slope should not stop the motor.
        g=ThermalRuntimeGuard(20)
        for i in range(500):
            pv=20.3 if (i%100)<60 else 19.75
            chip=19+0.055*i/60.0
            state,_=g.observe(float(i),pv,float(i),chip,i)
            self.assertEqual(state,'ok',f't={i}: unexpected stop')

    def test_long_pv_excursion_requires_full_duration(self):
        g=ThermalRuntimeGuard(20)
        feed(g,0,90)
        feed(g,91,119,pv=20.55)
        state,_=g.observe(120.,20.55,120.,19,120)
        self.assertEqual(state,'ok')
        state,_=g.observe(121.,20.55,121.,19,121)
        self.assertEqual(state,'hold')

    def test_short_temp_spikes_do_not_stop_moving_table(self):
        g=ThermalRuntimeGuard(20)
        for i in range(320):
            pv=20.28 if i%48<24 else 19.78
            chip=19.0+(0.12 if i%40<20 else -0.12)
            s,_=g.observe(i,pv,i,chip,i)
            self.assertEqual(s,'ok')

    def test_span_requires_sustained_exceedance(self):
        g=ThermalRuntimeGuard(20)
        feed(g,0,90)
        results=[]
        for i in range(91,145):
            s,_=g.observe(i,20.,i,19.45,i)
            results.append(s)
        self.assertIn('hold',results)

    def test_slope_requires_sustained_exceedance(self):
        g=ThermalRuntimeGuard(20)
        results=[]
        for i in range(370):
            state,_=g.observe(i,20.,i,19.0+0.12*i/60,i)
            results.append(state)
        self.assertIn('hold',results)

    def test_old_history_cannot_instantly_rearm(self):
        g=ThermalRuntimeGuard(20)
        feed(g,0,140)
        self.assertFalse(g.recovery_ready(140,20.,19.))
        g.begin_recovery(200.)
        for i in range(201,204):
            g.observe(i,20.,i,19.,i)
        self.assertFalse(g.recovery_ready(204,20.,19.))
        for i in range(204,321):
            g.observe(i,20.,i,19.,i)
        self.assertTrue(g.recovery_ready(320.,20.,19.))

    def test_pv_outside_recovery_band_cannot_authorize_rearm(self):
        g=ThermalRuntimeGuard(20)
        g.begin_recovery(0.)
        for i in range(121):
            pv=20.38 if i==70 else 20.0
            g.observe(i,pv,i,19.,i)
        self.assertFalse(g.recovery_ready(120,20,19))
        for i in range(121,193):g.observe(i,20.,i,19.,i)
        self.assertTrue(g.recovery_ready(192,20,19))

    def test_dropouts_cannot_fake_stable_window(self):
        g=ThermalRuntimeGuard(20)
        g.begin_recovery(0.)
        for i in list(range(0,45))+list(range(68,131)):
            g.observe(i,20.,i,19.,i)
        self.assertFalse(g.recovery_ready(130,20.,19.))

    def test_temperature_quality_unsafe_auto_skip_is_disabled(self):
        # Updated design contract: quality drift no longer creates a human-click
        # latch.  WK stop confirmation and recovery quality checks remain.
        source=(ROOT/'form/form_thermal_compensation.py').read_text('utf8')
        module=ast.parse(source)
        cls=next(n for n in module.body if isinstance(n,ast.ClassDef)
                 and n.name=='FormThermalCompensation')
        names={n.name for n in cls.body if isinstance(n,ast.FunctionDef)}
        self.assertIn('_thermal_recovery_seconds',names)
        self.assertIn('_skip_current_temperature_for_quality',names)
        self.assertNotIn("t['phase']='thermal_operator_hold'",source)
        self.assertIn('hold_count>=hold_limit',source)
        self.assertIn('self._halt_incomplete_temperature(',source)
        self.assertIn('self._abort(f',source)
        self.assertNotIn('self._skip_current_temperature_for_quality(now,',source)
        self.assertIn('ready, detail = self._wk_stop_confirmed(t, now)',source)
        self.assertIn('if not self._stopped():',source)
        self.assertIn("t['guard'].begin_recovery(now)",source)
        self.assertIn("if action=='resoak' or (action=='hold' and t['phase'] not in ('position','wait_position'))",source)

    def test_actual_segment_data_quality_is_unchanged(self):
        source=(ROOT/'form/form_thermal_compensation.py').read_text('utf8')
        self.assertIn("profile['quality']['temperature_span_max_c']=0.5",source)
        self.assertIn("temperature_group_audit",source)
        self.assertIn("KEEP_ACCEPTED_CONDITIONS_JOINT_FIT_PER_CONDITION_T",source)
        self.assertNotIn("if max(temps)-min(temps)<=0.6",source)
        self.assertIn('chip_stability_status(t[\'chip_trace\'],now)',source.replace(', now',',now'))


if __name__=='__main__':unittest.main(verbosity=2)
