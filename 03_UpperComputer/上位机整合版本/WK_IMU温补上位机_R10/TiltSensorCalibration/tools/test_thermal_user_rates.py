# -*- coding: utf-8 -*-
"""Offline configurable fitting/verification rate safety and retention tests."""
import copy
import ast
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from thermal_gyro_multirate import (
    parse_rate_list, validate_rate_lists, configure_thermal_gyro_profile,
    PILOT_FIT_RATES_DPS, PILOT_VERIFY_RATES_DPS,
)
from production_calibration import load_profile, gyro_fit_steps, gyro_verify_steps

class TestUserRates(unittest.TestCase):
    def test_user_lists_are_parsed_with_chinese_punctuation_and_sorted(self):
        self.assertEqual(parse_rate_list('30，5; 1\n15'),(1.,5.,15.,30.))
        self.assertEqual(parse_rate_list('0.5, 2.5'),(.5,2.5))

    def test_empty_duplicates_invalid_and_range_rejected(self):
        for inp in ('', '0', '-5,2', 'nan,1', 'inf', '60.1', '1,1', '1,1.0000001', '±1,5', '1e100'):
            with self.subTest(inp=inp),self.assertRaises(ValueError):
                parse_rate_list(inp)

    def test_fit_and_validation_must_be_disjoint(self):
        with self.assertRaises(ValueError):validate_rate_lists((1.,5.,15.),(1.5,5.))
        with self.assertRaises(ValueError):validate_rate_lists((1.,),(1.5,))
        self.assertEqual(validate_rate_lists((30.,1.,5.),(1.5,20.)),((1.,5.,30.),(1.5,20.)))

    def test_profile_uses_custom_rates_and_leaves_original_config_unchanged(self):
        ambient=load_profile(str(ROOT))
        original=copy.deepcopy(ambient)
        thermal=configure_thermal_gyro_profile(copy.deepcopy(ambient),fit_rates=(1,5,10,25),verify_rates=(1.5,12,22))
        self.assertEqual(ambient,original)
        self.assertEqual(thermal['rates']['fit_dps'],[1.,5.,10.,25.])
        self.assertEqual(thermal['rates']['verify_dps'],[1.5,12.,22.])
        self.assertEqual(thermal['rates']['maximum_command_rate_dps'],25.)
        self.assertEqual(thermal['quality']['rate_reference_std_max_dps'],0.18)
        fit_ids=[x for x in gyro_fit_steps(thermal) if x['mode']=='rate']
        verify_ids=[x for x in gyro_verify_steps(thermal) if x['mode']=='rate']
        self.assertEqual(len(fit_ids),4*6)
        self.assertEqual(len(verify_ids),3*6)
        self.assertEqual(max(abs(s['target_rate_dps']) for s in fit_ids),25.)

    def test_preset_is_backwards_compatible(self):
        profile=load_profile(str(ROOT))
        result=configure_thermal_gyro_profile(copy.deepcopy(profile),high_speed=False)
        self.assertEqual(tuple(result['rates']['fit_dps']),PILOT_FIT_RATES_DPS)
        self.assertEqual(tuple(result['rates']['verify_dps']),PILOT_VERIFY_RATES_DPS)

    def test_ui_wiring_safety_and_resume_source(self):
        source=(ROOT/'form/form_thermal_compensation.py').read_text('utf8')
        tree=ast.parse(source)
        cls=next(x for x in tree.body if isinstance(x,ast.ClassDef) and x.name=='FormThermalCompensation')
        methods={x.name for x in cls.body if isinstance(x,ast.FunctionDef)}
        self.assertIn('_on_gyro_rate_mode_changed',methods)
        self.assertIn('_selected_rates',methods)
        self.assertIn('thermal_gyro_fit_rates',source)
        self.assertIn('thermal_gyro_verify_rates',source)
        self.assertIn('gyro_fit_rates_dps',source)
        self.assertIn('gyro_verify_rates_dps',source)
        self.assertIn('max(rates_fit+rates_val)>30.0',source)
        self.assertIn('if high_speed and not self.check_highspeed.isChecked()',source)
        self.assertIn('validate_rate_lists(',source)
        self.assertIn('self.gyro_fit_rates,',source)

if __name__=='__main__':unittest.main()
