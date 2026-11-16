# -*- coding: utf-8 -*-
"""No-hardware tests: 15-temperature partial result reporting and safe gate split."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from thermal_result_readiness import build_result_readiness,write_result_readiness
from thermal_temperature_policy import policy_for
from thermal_analysis_publisher import publish_sensor_reports
from tools.test_thermal_model_selection import fake_thermal_rows


class ResultTests(unittest.TestCase):
    def test_readiness_detects_missing_temp_without_erasing_good_data(self):
        temps=[5.0,7.5,10.0]
        plan=[ [{'step_id':'A1','sensor':'acc','split':'fit'},
                 {'step_id':'G1','sensor':'gyro','split':'fit'}],
               [{'step_id':'A2','sensor':'acc','split':'validate'},
                {'step_id':'G2','sensor':'gyro','split':'validate'}],
               [{'step_id':'A3','sensor':'acc','split':'fit'},
                {'step_id':'G3','sensor':'gyro','split':'fit'}]]
        rows=[{'temperature_target_c':5.0,'step_id':'A1','sensor':'acc'},
              {'temperature_target_c':5.0,'step_id':'G1','sensor':'gyro'},
              {'temperature_target_c':7.5,'step_id':'A2','sensor':'acc'},
              {'temperature_target_c':10.0,'step_id':'A3','sensor':'acc'}]
        r=build_result_readiness(temps,plan,rows,{5.0:'fit',7.5:'validate',10.0:'fit'},
                                 auto_skipped=[{'temperature_target_c':10.0}])
        self.assertEqual((r['total_planned'],r['total_accepted'],r['total_missing']),(6,4,2))
        self.assertEqual(r['sensors']['acc']['model_status'],'FULL_DATA_READY_FOR_MODEL_EVALUATION')
        self.assertEqual(r['sensors']['gyro']['model_status'],'INSUFFICIENT_DATA_REPORT_MISSING_ONLY')
        with tempfile.TemporaryDirectory() as folder:
            paths=write_result_readiness(folder,r,'PARTIAL_COMPLETED')
            self.assertIn('GYRO',Path(paths['markdown']).read_text(encoding='utf8'))
            self.assertIn('"total_missing": 2',Path(paths['json']).read_text(encoding='utf8'))
    def test_continuous_gates_only_relaxed_without_changing_strict_or_runtime_safety(self):
        c=policy_for('continuous');s=policy_for('strict')
        self.assertEqual(c['pv_final_tolerance_c'],1.0)
        self.assertEqual(s['pv_final_tolerance_c'],0.10)
        self.assertEqual(c['chip_gate_60s_span_c'],0.25)
        self.assertEqual(s['chip_gate_60s_span_c'],0.20)
        self.assertGreater(c['dwell_seconds'],600)
        self.assertEqual(s['dwell_seconds'],1800)
        self.assertNotIn('alarm',c['runtime'])
        self.assertNotIn('emergency',c['runtime'])
    def test_partial_rows_still_generate_readable_research_model_reports(self):
        rows=fake_thermal_rows()
        # Delete one entire GYRO fit temperature while ACC remains complete.
        partial=[r for r in rows if not (r['sensor']=='gyro' and float(r['temperature_target_c'])==-20.0)]
        with tempfile.TemporaryDirectory() as folder:
            out=publish_sensor_reports(folder,partial,[-20,0,25,45,70],('gyro',),source_folder=folder)
            self.assertTrue(Path(out['combined_workbook']).is_file())
            m=Path(folder)/'GYRO_单独28方案报告'/'GYRO_28模型结构及排名_研发报告.md'
            self.assertTrue(m.is_file())
            self.assertIn('T2-D3',m.read_text(encoding='utf8'))
            self.assertIn(out['selection']['sensors']['gyro']['status'],
                          ('NOT_EVALUATED','BASELINE_PREFERRED_NO_TEMPERATURE_COMPENSATION',
                           'INDEPENDENT_TEMPERATURE_IMPROVEMENT_CONFIRMED_RESEARCH_ONLY',
                           'HOLDOUT_NOT_IMPROVED_NO_APPROVAL','HOLDOUT_INVALID_NO_APPROVAL'))
    def test_excel_exposes_readiness_from_original_experiment_dir(self):
        rows=fake_thermal_rows()
        with tempfile.TemporaryDirectory() as folder:
            # Authoritative checkpoint-derived readiness summary; no guessing
            # completeness from the number of available rows.
            r={'total_accepted':101,'total_planned':110,'total_missing':9,
               'per_temperature':[{'sensor':'acc','temperature_target_c':25.0,
                  'temperature_role':'fit','accepted':11,'planned':12,'missing':1,
                  'fully_complete':False}],
               'sensors':{'acc':{'accepted':11,'planned':12}}}
            (Path(folder)/'thermal_result_readiness.json').write_text(
                __import__('json').dumps(r),encoding='utf8')
            result=publish_sensor_reports(folder,rows,[-20,0,25,45,70],('acc',),source_folder=folder)
            from openpyxl import load_workbook
            w=load_workbook(result['combined_workbook'],read_only=True)
            self.assertIn('结果可用性与缺失温度',w.sheetnames)
            self.assertEqual(w['结果可用性与缺失温度']['F2'].value,1)
            w.close()

    def test_no_holdout_must_report_not_evaluated_not_fabricate_coefficients(self):
        rows=[r for r in fake_thermal_rows() if r['sensor']=='acc' and r['temperature_split']=='fit']
        with tempfile.TemporaryDirectory() as folder:
            out=publish_sensor_reports(folder,rows,[-20,0,25,45,70],('acc',),source_folder=folder)
            self.assertEqual(out['selection']['sensors']['acc']['status'],'NOT_EVALUATED')
            self.assertIsNone(out['selection']['sensors']['acc']['selected_id'])
            self.assertTrue((Path(folder)/'ACC_单独28方案报告'/'ACC_28模型结构及排名_研发报告.md').is_file())
            self.assertFalse((Path(folder)/'thermal_acc_selected_candidate.json').exists())
    def test_return_to_ambient_timeout_bounded_and_not_falsely_confirmed(self):
        from tools.test_thermal_auto_quality_no_click import StateMachineTests
        f,tick=StateMachineTests().fake_step('wait_return',now=8000)
        f.task['phase_start']=100
        f.task['pv_stable_since']=None
        f.chamber['pv']=35.0
        f._request_final_stop=__import__('unittest').mock.Mock()
        tick(f)
        self.assertFalse(f.aborted)
        self.assertTrue(f.task['return_ambient_unconfirmed'])
        self.assertEqual(f._request_final_stop.call_count,1)
        self.assertIn('回25℃超过60分钟未完成',f._request_final_stop.call_args.args[1])
    def test_return_timeout_abnormal_temperature_requires_fault_handling(self):
        from tools.test_thermal_auto_quality_no_click import StateMachineTests
        f,tick=StateMachineTests().fake_step('wait_return',now=8000)
        f.task['phase_start']=100
        f.task['pv_stable_since']=None
        f.chamber['pv']=75.0
        f._request_final_stop=__import__('unittest').mock.Mock()
        tick(f)
        self.assertTrue(f.aborted)
        self.assertEqual(f._request_final_stop.call_count,0)

    def test_hardware_gates_not_disabled_in_form(self):
        src=(Path(__file__).resolve().parents[1]/'form'/'form_thermal_compensation.py').read_text(encoding='utf8')
        for snippet in ('_wk_stop_confirmed(t,now)', 'require_setpoint_ack(chamber,target)',
                        "if action=='safety'",'require_live_chamber(data,now)',
                        'tilt_sensor_calibration_queue_drop_count_get()'):
            self.assertIn(snippet,src)
        self.assertIn('write_result_readiness(',src)
        self.assertIn('PARTIAL_INCOMPLETE_SENSORS_RESEARCH',src)

if __name__=='__main__':unittest.main()
