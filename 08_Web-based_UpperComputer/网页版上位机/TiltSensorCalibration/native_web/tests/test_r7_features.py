# -*- coding: utf-8 -*-
"""Tests exercise R7 pure-data code only; never touch COM/PLC/WK hardware."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from native_web import r7_features as r

class R7FeaturesTest(unittest.TestCase):
    def test_r7_default_uses_real_validators(self):
        d,plan=r.validate_draft({})
        self.assertEqual(d['quality_mode'],'production_adaptive')
        self.assertEqual(len(plan['execution_order']),9)
        self.assertEqual(len(plan['gyro_fit_rates']),7)
        self.assertTrue(plan['r7_policy']['target_sp_direct'])
        self.assertFalse(plan['r7_policy']['actuator_commands_enabled'])

    def test_overlap_and_out_of_range_rejected(self):
        with self.assertRaises(ValueError):
            r.validate_draft({'validation_temperatures':'25, 27.5'})
        with self.assertRaises(ValueError):
            r.validate_draft({'fit_temperatures':'-80,20,40'})
        with self.assertRaises(ValueError):
            r.validate_draft({'gyro_fit_rates':'1, 2, 30, 60.1'})
        with self.assertRaises(ValueError):
            r.validate_draft({'gyro_verify_rates':'2.5, 3'})
        with self.assertRaises(ValueError):
            r.validate_draft({'gyro_verify_rates':'1.5, 2'})

    def test_no_unexpected_control_fields(self):
        with self.assertRaises(ValueError):
            r.validate_draft({'actuator_enabled':True})
        with self.assertRaises(ValueError):
            r.validate_draft({'dwell_seconds':0})

    def test_pose_source_is_r7(self):
        v=r.R7Workspace().poses()
        self.assertEqual(len(v['fit']),12)
        self.assertEqual(len(v['verify']),12)
        self.assertEqual(v['fit'][0]['step_id'],'ACC_FIT_01')

    def test_run_paths_reject_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(r,'IMPORTED_RUNS',Path(tmp)):
                wk=r.R7Workspace()
                for unsafe in ('..','../../windows',r'C:\secret','x/../y'):
                    with self.assertRaises((ValueError,FileNotFoundError)):
                        wk.detail(unsafe)

    def test_draft_save_does_not_change_experiment_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(r,'DRAFT',Path(tmp)/'draft.json'):
                wk=r.R7Workspace()
                result=wk.save_draft({'sn':'DTS123456'})
                self.assertEqual(wk.draft()['sn'],'DTS123456')
                self.assertFalse((Path(tmp)/'experiment_config.json').exists())
                self.assertFalse(result['preview']['r7_policy']['actuator_commands_enabled'])

    def test_incomplete_archive_not_analyzed(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            run=root/'a';run.mkdir()
            (run/'experiment_config.json').write_text(json.dumps({'temperature_setpoints_c':[25]}))
            (run/'temperature_measurements.json').write_text(json.dumps({'status':'INCOMPLETE','rows':[{'sensor':'acc'}]}))
            with patch.object(r,'IMPORTED_RUNS',root):
                wk=r.R7Workspace()
                self.assertEqual(len(wk.list_runs()),1)
                with self.assertRaises(ValueError):wk.analyze('a')
                self.assertEqual(wk.job_state()['state'],'idle')

if __name__=='__main__':unittest.main()
