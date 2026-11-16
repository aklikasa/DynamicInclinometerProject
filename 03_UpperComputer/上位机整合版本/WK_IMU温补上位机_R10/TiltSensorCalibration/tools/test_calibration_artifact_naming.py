# -*- coding: utf-8 -*-
"""DTS-based ambient/thermal calibration artifact naming regression tests."""
import ast
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT))

from calibration_artifact_paths import (
    AMBIENT_FOLDER, THERMAL_FOLDER, ambient_root, thermal_root,
    ambient_filename, thermal_filename, existing_ambient_path,
)
from thermal_model_selection import run_thermal_model_selection
from thermal_excel_report import export_thermal_xlsx
from thermal_variable_temperature import save_variable_models, save_optional_gyro_bias
from tools.test_thermal_model_selection import fake_thermal_rows
from tools.test_thermal_cubic_temperature import synthetic_rows


class CalibrationArtifactNamingTests(unittest.TestCase):
    def test_ambient_and_thermal_device_directories_are_separate(self):
        with tempfile.TemporaryDirectory() as temp:
            ambient = ambient_root(temp, 'DTS672516')
            thermal = thermal_root(temp, 'DTS672516')
            self.assertEqual(ambient.name, AMBIENT_FOLDER)
            self.assertEqual(thermal.name, THERMAL_FOLDER)
            self.assertNotEqual(ambient, thermal)
            self.assertEqual(ambient.parent, thermal.parent)
            self.assertEqual(ambient_filename('DTS672516', 'acc'), 'DTS672516_ACC_AMBIENT.json')
            self.assertEqual(ambient_filename('DTS672516', 'gyro'), 'DTS672516_GYRO_AMBIENT.json')
            self.assertEqual(thermal_filename('DTS672516', 'acc', 'selected'),
                             'DTS672516_ACC_THERMAL_SELECTED_CANDIDATE.json')
            self.assertEqual(thermal_filename('DTS672516', 'gyro', 'models'),
                             'DTS672516_GYRO_THERMAL_MODEL_CANDIDATES.json')

    def test_legacy_ambient_files_remain_readable_but_new_path_is_preferred(self):
        with tempfile.TemporaryDirectory() as temp:
            legacy = Path(temp) / 'accel_calibration.json'
            legacy.write_text('{"device_serial":"DTS672516"}', encoding='utf-8')
            self.assertEqual(existing_ambient_path(temp, 'DTS672516', 'acc'), legacy)
            current = ambient_root(temp, 'DTS672516')
            current.mkdir(parents=True)
            current_file = current / ambient_filename('DTS672516', 'acc')
            current_file.write_text('{"device_serial":"DTS672516"}', encoding='utf-8')
            self.assertEqual(existing_ambient_path(temp, 'DTS672516', 'acc'), current_file)

    def test_thermal_selected_models_and_candidates_include_dts(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'run'
            selection = run_thermal_model_selection(
                output, fake_thermal_rows(), [-20, 0, 25, 45, 70],
                device_sn='DTS672516')
            self.assertEqual(selection['device_serial'], 'DTS672516')
            self.assertTrue((output / thermal_filename('DTS672516', 'acc', 'selected')).is_file())
            self.assertTrue((output / thermal_filename('DTS672516', 'gyro', 'selected')).is_file())
            self.assertTrue((output / thermal_filename('DTS672516', 'acc', 'models')).is_file())
            self.assertTrue((output / thermal_filename('DTS672516', 'gyro', 'models')).is_file())
            self.assertTrue((output / thermal_filename('DTS672516', artifact='selection')).is_file())
            model = json.loads((output / thermal_filename('DTS672516', 'gyro', 'selected')).read_text(encoding='utf-8'))
            self.assertEqual(model['device_serial'], 'DTS672516')
            self.assertEqual(model['calibration_type'], 'gyro_thermal_selected_candidate')
            self.assertFalse(model['production_release'])
            self.assertFalse((output / 'thermal_gyro_selected_candidate.json').exists())
            self.assertNotIn('device_uid_raw', model)
            workbook = export_thermal_xlsx(output, fake_thermal_rows(), {'sensors': {}, 'model_selection': selection})
            self.assertTrue(Path(workbook).name.startswith('DTS672516_THERMAL_'))

    def test_legacy_thermal_candidate_and_bias_files_include_dts(self):
        with tempfile.TemporaryDirectory() as temp:
            save_variable_models(temp, synthetic_rows(), [-20, 0, 25, 45, 70], ('gyro',),
                                 device_sn='DTS672516')
            self.assertTrue((Path(temp) / thermal_filename('DTS672516', 'gyro', 'candidate')).is_file())
            self.assertTrue((Path(temp) / thermal_filename('DTS672516', artifact='fit_status')).is_file())
            bias = save_optional_gyro_bias(temp, synthetic_rows(), [-20, 0, 25, 45, 70],
                                           device_sn='DTS672516')
            self.assertTrue(Path(bias).name.startswith('DTS672516_GYRO_THERMAL_BIAS_ONLY'))

    def test_ambient_result_writer_saves_dts_named_files_in_device_folder(self):
        source = ROOT / 'form' / 'form_imu_calibration.py'
        tree = ast.parse(source.read_text(encoding='utf-8'))
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'FormImuCalibration')
        method = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == '_save_calibration_result')
        namespace = {'os': os, 'json': json, 'safe_device_sn': __import__('calibration_artifact_paths').safe_device_sn,
                      'ambient_root': ambient_root, 'ambient_filename': ambient_filename}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])), str(source), 'exec'), namespace)
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp) / 'run_001'
            run_dir.mkdir()
            writer = namespace['_save_calibration_result']
            obj = SimpleNamespace(
                line_output_root=SimpleNamespace(text=lambda: temp), run_dir=str(run_dir),
                _last_accel_result=None, _last_gyro_result=None, _last_alignment_result=None,
                _manifest={})
            result = {'quality_gate': {'metric_pass': True, 'verdict': 'PASS'}}
            saved = writer(obj, {'type': 'accel', 'device_serial': 'DTS672516', 'axis_model': 'outer_x_inner_z'}, result)
            expected = ambient_root(temp, 'DTS672516') / ambient_filename('DTS672516', 'acc')
            self.assertEqual(Path(saved), expected)
            self.assertTrue(expected.is_file())
            self.assertTrue((run_dir / expected.name).is_file())
            self.assertEqual(obj._manifest['result_files'], [expected.name, expected.name])

    def test_invalid_or_missing_device_serial_is_rejected_for_new_device_folders(self):
        with tempfile.TemporaryDirectory() as temp:
            for invalid in ('', '.', '..', '../PCB', 'DTS/123', 'DTS 123'):
                with self.subTest(invalid=invalid):
                    with self.assertRaises(ValueError):
                        thermal_root(temp, invalid)


if __name__ == '__main__':
    unittest.main(verbosity=2)
