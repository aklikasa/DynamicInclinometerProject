# -*- coding: utf-8 -*-
"""R7 regressions: direct PLC SP, non-destructive 2C+ 12-pose groups,
joint per-condition chip-T model. No WK/PLC hardware access."""
import ast
import math
import unittest
from pathlib import Path
import numpy as np
from thermal_joint_fit import fit_joint_polynomial, ensure_complete_fit_groups
from thermal_compensation import _eval_poly
from thermal_temperature_policy import policy_for
from production_cycle_protocol import check_user_hardware_clearance

APP=Path(__file__).resolve().parents[1]
SOURCE=APP/'form/form_thermal_compensation.py'

def method(name):
    tree=ast.parse(SOURCE.read_text(encoding='utf8'))
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='FormThermalCompensation')
    fn=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name==name)
    m=ast.Module(body=[fn],type_ignores=[])
    ast.fix_missing_locations(m)
    scope={}
    exec(compile(m,str(SOURCE),'exec'),scope)
    return scope[name]


def synthetic_groups(span=2.15):
    views=np.array([[0,0,1],[0,0,-1],[1,0,0],[-1,0,0],[0,1,0],[0,-1,0],
                    [1,1,1],[-1,1,1],[1,-1,1],[1,1,-1],[-1,-1,1],[-1,1,-1]],float)
    views/=np.linalg.norm(views,axis=1)[:,None]
    groups={}
    for target in [-40,-20,0,20,40,60,80]:
        group=[]
        for i,vec in enumerate(views):
            die=target+span*i/11
            u=(die-25.)/50.
            F=np.array([[1.004+.0015*u,.002,-.001],
                        [.001,.998-.002*u,-.002],
                        [-.003,.001,1.003+.001*u]])
            b=np.array([.008-.003*u,-.005+.002*u,.011+.003*u])
            raw=F@vec+b
            group.append({'step_id':f'ACC_FIT_{i+1:02d}','sensor':'acc','mode':'static','split':'fit',
                          'temperature_target_c':float(target),'temperature_mean_c':die,
                          'reference':vec.tolist(),'acc_raw_mean_g':raw.tolist()})
        groups[float(target)]=group
    return groups


class R7Integration(unittest.TestCase):
    def test_group_over_2_c_keeps_all_12_and_audits(self):
        rows=synthetic_groups()[(-40.)]
        obj=type('Fake',(),{})()
        obj.task={'temp_i':0,'temps':[-40.],'rows':rows,
                  'temperature_quality_mode':'production_adaptive'}
        obj.logs=[];obj.saved=[]
        obj._log=lambda text:obj.logs.append(text)
        obj._save_partial=lambda *args:obj.saved.append(args)
        obj.halted=[]
        obj._halt_incomplete_temperature=lambda reason:obj.halted.append(reason)
        result=method('_audit_current_temperature_groups')(obj)
        self.assertTrue(result)
        self.assertEqual(len(obj.halted),1)
        self.assertIn('2.000',obj.halted[0])
        self.assertEqual(len(obj.task['rows']),12)
        self.assertEqual(len(obj.task['temperature_group_audit']),1)
        self.assertGreater(obj.task['temperature_group_audit'][0]['chip_span_c'],2.0)
        self.assertEqual(obj.task['temperature_group_audit'][0]['decision'],'SAFE_STOP_PRESERVE_RAW')
        self.assertGreaterEqual(len(obj.saved),1)
        method('_audit_current_temperature_groups')(obj)
        self.assertEqual(len(obj.task['temperature_group_audit']),1)

    def test_no_intermediate_setpoints_in_live_state_machine(self):
        tree=ast.parse(SOURCE.read_text(encoding='utf8'))
        code=SOURCE.read_text(encoding='utf8')
        self.assertIn('self._issue_plc_setpoint(target)',code)
        self.assertNotIn('initial_stages(',code)
        self.assertNotIn("t['phase']='verify_auto_arrival_sp'",code)
        self.assertNotIn('self.auto_arrival_step',code)
        self.assertNotIn('auto_arrival_timeout_minutes',code)
        self.assertIn('require_setpoint_ack(chamber,target)',code)
        self.assertIn('if not self._stopped()',code)

    def test_production_mode_has_existing_continuous_limits_no_invented_group_gate(self):
        prod=policy_for('production_adaptive')
        cont=policy_for('continuous')
        # R9 production defaults are deliberately editable and less strict
        # than the historical R7 continuous policy.
        self.assertNotEqual(prod['runtime'],cont['runtime'])
        self.assertGreaterEqual(prod['pv_final_tolerance_c'],2.0)
        self.assertGreaterEqual(prod['runtime']['recovery_pv_c'],2.0)
        self.assertNotIn('group_spread_alert_c',prod)
        self.assertTrue(check_user_hardware_clearance(True,True,False,'production_adaptive'))
        with self.assertRaises(ValueError):
            check_user_hardware_clearance(True,True,False,False)

    def test_complete_12_required(self):
        groups=synthetic_groups()
        self.assertEqual(ensure_complete_fit_groups(groups,'acc'),12)
        groups[-40.]=groups[-40.][:-1]
        with self.assertRaisesRegex(ValueError,'完整12姿态|姿态不完整'):
            ensure_complete_fit_groups(groups,'acc')

    def test_joint_all_12_positions_each_has_its_own_real_chip_t(self):
        groups=synthetic_groups()
        F0=np.eye(3);b0=np.zeros(3)
        forward,bias,meta=fit_joint_polynomial(
            groups,'acc','D',1,F0,b0,{'id':'T0','kind':'raw_chip'})
        self.assertEqual(meta['fit_conditions_per_setpoint'],12)
        self.assertEqual(meta['fit_group_count'],7)
        self.assertEqual(meta['fit_condition_count'],84)
        self.assertEqual(meta['temperature_independent_variable'],
                         'condition_mean_of_valid_IMU_chip_temperature_frames')
        errors=[]
        for target,group in groups.items():
            for row in group:
                Te=row['temperature_mean_c']
                F=_eval_poly(forward,Te);b=_eval_poly(bias,Te)
                corrected=np.linalg.solve(F,np.array(row['acc_raw_mean_g'])-b)
                errors.append(np.linalg.norm(corrected-row['reference']))
        self.assertLess(max(errors),1.e-7)

if __name__=='__main__':unittest.main()
