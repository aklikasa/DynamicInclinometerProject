# -*- coding: utf-8 -*-
"""Low-speed-focused editable gyro temperature-plan regression tests."""
import copy
import sys
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from thermal_gyro_multirate import (
    LOW_SPEED_FIT_RATES_DPS,LOW_SPEED_VERIFY_RATES_DPS,
    validate_rate_lists,parse_rate_list,configure_thermal_gyro_profile)
from production_calibration import load_profile,gyro_fit_steps,gyro_verify_steps,acc_fit_steps,acc_verify_steps

class TestLowSpeedPlan(unittest.TestCase):
    def test_fit_and_verify_presets_do_not_overlap(self):
        f,v=validate_rate_lists(LOW_SPEED_FIT_RATES_DPS,LOW_SPEED_VERIFY_RATES_DPS)
        self.assertEqual(f,(1.,2.,3.,5.,10.,20.,30.))
        self.assertEqual(v,(1.5,2.5,4.,7.5,15.,25.))
        self.assertGreaterEqual(len([r for r in f if r<=5]),4)
        self.assertEqual(max(f),30.)
    def test_editable_rates_and_limit(self):
        f,v=validate_rate_lists(parse_rate_list('0.5,1,2,5,10,30'),parse_rate_list('0.75,1.5,3,7.5,25'))
        self.assertEqual(f[0],.5)
        with self.assertRaises(ValueError):validate_rate_lists(f,(1.,3.))
        with self.assertRaises(ValueError):parse_rate_list('61')
    def test_steps_and_counts_are_from_profile(self):
        p=configure_thermal_gyro_profile(copy.deepcopy(load_profile(str(ROOT))),
                fit_rates=LOW_SPEED_FIT_RATES_DPS,verify_rates=LOW_SPEED_VERIFY_RATES_DPS)
        self.assertEqual(len(gyro_fit_steps(p)),43)
        self.assertEqual(len(gyro_verify_steps(p)),37)
        self.assertEqual(len(acc_fit_steps())+len(acc_verify_steps())+43+37,104)
        self.assertEqual(len(acc_verify_steps())+37,49)
        self.assertEqual(5*104+4*49,716)
    def test_ui_starts_editable_with_low_speed_lists(self):
        s=(ROOT/'form/form_thermal_compensation.py').read_text('utf-8')
        self.assertIn("findData('custom')",s)
        self.assertIn("QLineEdit('1, 2, 3, 5, 10, 20, 30')",s)
        self.assertIn("QLineEdit('1.5, 2.5, 4, 7.5, 15, 25')",s)
        self.assertIn("if mode == 'low_speed':",s)
        self.assertIn("return validate_rate_lists(",s)
    def test_high_std_is_editable_but_requires_extra_confirmation(self):
        s=(ROOT/'form/form_thermal_compensation.py').read_text('utf-8')
        self.assertIn('new_quality_spin(0.240,0.100,0.600,0.010)',s)
        self.assertIn('float(self.wk_std_high.value()) > 0.350',s)
        self.assertIn('QMessageBox.Yes | QMessageBox.No',s)
        self.assertIn('未确认高于0.350',s)
    def test_report_has_rate_coverage_sheet(self):
        source=(ROOT/'thermal_excel_report.py').read_text('utf8')
        self.assertIn("wb.create_sheet('GYRO速率覆盖及缺失概览')",source)
        self.assertIn('仅表示已接受采样数',source)
if __name__=='__main__':unittest.main()
