# -*- coding: utf-8 -*-
"""Regression tests for separate fit/independent-temperature inputs (no hardware)."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'tools'))
from thermal_variable_temperature import separate_temperature_plan, steps_for_temperature, save_variable_models
from thermal_run_resume import RESUME_SCHEMA, validate_resume
from thermal_model_selection import run_thermal_model_selection
from thermal_excel_report import export_thermal_xlsx
from test_thermal_model_selection import fake_thermal_rows
from openpyxl import load_workbook


class SplitTemperatureTests(unittest.TestCase):
    def test_user_inputs_merge_order_and_roles(self):
        p=separate_temperature_plan('10, 15, 20, 25, 30','12.5, 22.5')
        self.assertEqual(p['temperature_setpoints_c'],[10,12.5,15,20,22.5,25,30])
        self.assertEqual(p['fit_temperatures_c'],[10,15,20,25,30])
        self.assertEqual(p['validation_temperatures_c'],[12.5,22.5])
        self.assertEqual([p['temperature_split'][t] for t in p['temperature_setpoints_c']],
                         ['fit','validate','fit','fit','validate','fit','fit'])

    def test_reject_duplicate_overlap_extrapolation_and_inadequate_fit(self):
        for fit,test in [('10, 15, 20','15'),('10, 15, 20','9'),
                         ('10, 15, 20','21'),('10, 15, 20',''),
                         ('10, 15, 20','12,12'),('10,20','15'),
                         ('10, 15, 20','nan')]:
            with self.subTest(fit=fit,test=test),self.assertRaises(ValueError):
                separate_temperature_plan(fit,test)

    def test_verification_temperature_only_tests_and_no_fit(self):
        all_steps=[{'step_id':x, 'split':role} for x,role in
                   [('A0','fit'),('A1','validate'),('G0','fit'),('G1','validate')]]
        self.assertEqual(len(steps_for_temperature(all_steps,'fit')),4)
        only=steps_for_temperature(all_steps,'validate')
        self.assertEqual([x['step_id'] for x in only],['A1','G1'])
        self.assertTrue(all(x['split']=='validate' for x in only))
        self.assertEqual(len(all_steps),4)

    def test_per_temperature_resume_exact_prefix(self):
        p=separate_temperature_plan('10, 15, 20', '12.5, 17.5')
        temps=p['temperature_setpoints_c']
        all_steps=[{'step_id':sid,'split':role,'sensor':'acc','mode':'static'}
                   for sid,role in [('FIT','fit'),('VERIFY','validate')]]
        schedule=[steps_for_temperature(all_steps,p['temperature_split'][t]) for t in temps]
        params={'device_sn':'unit-01','temperature_setpoints_c':temps,
                'temperature_fit_split':{str(float(t)):role for t,role in p['temperature_split'].items()}}
        config=json.loads(json.dumps({'resume_schema_version':RESUME_SCHEMA,'resume_immutable_config':copy.deepcopy(params)}))
        flattened=[(t,step) for t,part in zip(temps,schedule) for step in part]
        for count in range(len(flattened)+1):
            rows=[{**step,'temperature_target_c':t,'temperature_split':p['temperature_split'][t],
                   'accepted_frames':70} for t,step in flattened[:count]]
            ck={'status':'RUNNING','device_sn':'unit-01','rows':rows}
            result=validate_resume(config,ck,params,temps,schedule)
            before=sum(len(part) for part in schedule[:result['temp_index']])
            self.assertEqual(before+result['step_index'],count)
        corrupted=copy.deepcopy(ck)
        corrupted['rows'][2]['temperature_split']='fit'
        with self.assertRaisesRegex(ValueError,'用途'):
            validate_resume(config,corrupted,params,temps,schedule)
        changed=copy.deepcopy(params)
        changed['temperature_fit_split']['12.5']='fit'
        with self.assertRaisesRegex(ValueError,'配置'):
            validate_resume(config,ck,changed,temps,schedule)

    def test_holdout_only_rows_keep_28_candidates_and_excel(self):
        temps=[10,12.5,15,20,22.5,25,30]
        plan=separate_temperature_plan('10,15,20,25,30','12.5,22.5')
        rows=fake_thermal_rows(temps=temps)
        for r in rows:
            r['temperature_split']=plan['temperature_split'][r['temperature_target_c']]
        rows=[r for r in rows if r['temperature_split']=='fit' or r['split']=='validate']
        self.assertFalse(any(r['temperature_split']=='validate' and r['split']=='fit' for r in rows))
        with tempfile.TemporaryDirectory() as d:
            baseline=save_variable_models(d,rows,temps)
            selected=run_thermal_model_selection(d,rows,temps)
            self.assertEqual(set(selected['sensors']),{'acc','gyro'})
            for sensor in ('acc','gyro'):
                result=selected['sensors'][sensor]
                self.assertEqual(len(result['candidates']),28)
                self.assertIn(result['selected_id'], [r['id'] for r in result['candidates']])
                self.assertEqual(sorted(result['final_holdout_setpoints_c']),[12.5,22.5])
                self.assertEqual(sorted(result['fit_temperature_setpoints_c']),[10,15,20,25,30])
            baseline['model_selection']=selected
            excel=export_thermal_xlsx(d,rows,baseline)
            wb=load_workbook(excel,read_only=True)
            self.assertIn('温度工况计划',wb.sheetnames)
            table=list(wb['温度工况计划'].iter_rows(values_only=True))
            self.assertTrue(any(row[0]==12.5 and row[1]=='独立温度验证' and row[2]==0 and row[4]==0 for row in table))
            self.assertTrue(any(row[0]==22.5 and row[1]=='独立温度验证' and row[2]==0 and row[4]==0 for row in table))
            wb.close()

    def test_gui_source_wires_both_inputs_and_variable_steps(self):
        text=(ROOT/'form'/'form_thermal_compensation.py').read_text(encoding='utf8')
        for required in ('self.fit_temperatures', 'self.validation_temperatures',
                         "steps_for_temperature(all_steps,splits[target])",
                         "'steps_by_temperature':steps", "'temperature_split':self.task['temperature_split_by_setpoint']"):
            self.assertIn(required,text)


if __name__ == '__main__':
    unittest.main(verbosity=2)
