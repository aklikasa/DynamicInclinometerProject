# -*- coding: utf-8 -*-
"""No hardware: regression checks for 28 thermal model candidates and PV-only-in-lab calibration."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from thermal_model_selection import run_thermal_model_selection
from thermal_compensation import apply_temperature_model
from thermal_excel_report import export_thermal_xlsx
from thermal_variable_temperature import temperature_splits
from openpyxl import load_workbook


def fake_thermal_rows(seed=17, temps=None):
    rng=np.random.default_rng(seed)
    temps=[-20,0,25,45,70] if temps is None else temps
    split=temperature_splits(temps)
    acc_fit=[[0,0,1],[0,0,-1],[1,0,0],[-1,0,0],[0,1,0],[0,-1,0],
             [1,1,1],[1,-1,1],[-1,1,1],[1,1,-1],[1,-1,-1],[-1,-1,1]]
    acc_validate=[[2,1,1],[-2,1,1],[1,2,-1],[1,-2,1],[1,1,2],[-1,1,-2]]
    gyro_fit=[np.eye(3)[a]*rate*s for a in range(3) for rate in (1,5,15,30,60) for s in (1,-1)]
    gyro_val=[np.eye(3)[a]*rate*s for a in range(3) for rate in (1.5,3.5,10,20,45) for s in (1,-1)]
    rows=[]
    for t in temps:
        z=(t-25)/50
        for sensor in ('acc','gyro'):
            # Distinct temperature slope, diagonals, and nonzero fixed coupling.
            F=np.array([[1.006+0.009*z,0.003,0.002],
                        [-0.001,0.996-0.005*z,0.001],
                        [0.002,-0.001,1.003+0.004*z]],float)
            b=np.array([0.014,-0.010,0.006])+np.array([0.008,-0.005,0.004])*z
            vectors=(acc_fit,acc_validate) if sensor=='acc' else (gyro_fit,gyro_val)
            for cond, references in zip(('fit','validate'),vectors):
                refs=([np.asarray(x,dtype=float)/np.linalg.norm(x) for x in references]
                      if sensor=='acc' else [np.asarray(x,dtype=float) for x in references])
                if sensor=='gyro':refs=[np.zeros(3)]+refs
                for v in refs:
                    value=F@v+b+rng.normal(0,0.00004 if sensor=='acc' else 0.0002,3)
                    rows.append({'sensor':sensor,'temperature_split':split[t],
                                 'temperature_target_c':t,'temperature_mean_c':t,
                                 'split':cond,'mode':'static' if sensor=='acc' or np.linalg.norm(v)==0 else 'rate',
                                 'step_id':f'{sensor}_{t}_{cond}_{len(rows)}',
                                 'inner_actual_mean_deg':0.,'outer_actual_mean_deg':0.,
                                 'inner_rate_mean_dps':0.,'outer_rate_mean_dps':0.,
                                 'accepted_frames':60,'frame_count':60,
                                 'reference':v.tolist(),
                                 ('acc_raw_mean_g' if sensor=='acc' else 'gyro_raw_mean_dps'):value.tolist()})
    return rows


class CompareTests(unittest.TestCase):
    def test_twenty_eight_models_for_each_sensor_and_report(self):
        rows=fake_thermal_rows()
        with tempfile.TemporaryDirectory() as d:
            selection=run_thermal_model_selection(d,rows,[-20,0,25,45,70])
            for sensor in ('acc','gyro'):
                entry=selection['sensors'][sensor]
                self.assertEqual(len(entry['candidates']),28)
                self.assertIn(entry['selected_id'], ['A0']+[f'T{t}-{c}{d}' for t in range(3) for c in 'BCD' for d in (1,2,3)])
                self.assertFalse(entry['production_release'])
                self.assertTrue((Path(d)/f'thermal_{sensor}_selected_candidate.json').exists())
                self.assertTrue((Path(d)/f'thermal_{sensor}_model_candidates.json').exists())
                self.assertIn('dynamic_tilt_status',entry)
                self.assertIn('vector_rmse',next(c for c in entry['candidates'] if c['id']=='A0')['independent_temperature_verification'])
                model=json.loads((Path(d)/f'thermal_{sensor}_selected_candidate.json').read_text(encoding='utf8'))
                self.assertFalse(model['production_release'])
                self.assertEqual(len(apply_temperature_model(model, [0,0,1], 25)),3)
                with self.assertRaises(ValueError):apply_temperature_model(model,[0,0,1],200)
            report=export_thermal_xlsx(d,rows,{'sensors':{},'model_selection':selection})
            book=load_workbook(report,read_only=True)
            for name in ('温补总览','逐工况测量','模型自动比较','芯片温度校正','逐温度误差比较','静态倾角精度对比','结论与数据边界','MCU部署说明'):
                self.assertIn(name,book.sheetnames)
            self.assertEqual(book['模型自动比较'].max_row,57)
            self.assertGreater(book['静态倾角精度对比'].max_row,1)
            self.assertTrue(any('同步' in str(row[1].value) for row in book['结论与数据边界'].iter_rows(min_row=2,max_col=2)))
            book.close()

    def test_holdout_measurements_never_pick_winner(self):
        rows=fake_thermal_rows()
        with tempfile.TemporaryDirectory() as d:
            a=run_thermal_model_selection(d,rows,[-20,0,25,45,70])
            altered=copy.deepcopy(rows)
            for row in altered:
                if row['temperature_split']=='validate':
                    k='acc_raw_mean_g' if row['sensor']=='acc' else 'gyro_raw_mean_dps'
                    row[k]=[float(x+0.14) for x in row[k]]
            b=run_thermal_model_selection(d,altered,[-20,0,25,45,70])
            for sensor in ('acc','gyro'):
                self.assertEqual(a['sensors'][sensor]['selected_id'],b['sensors'][sensor]['selected_id'])
                self.assertEqual([x.get('selection_score') for x in a['sensors'][sensor]['candidates']],
                                 [x.get('selection_score') for x in b['sensors'][sensor]['candidates']])
                self.assertNotEqual(
                    next(x for x in a['sensors'][sensor]['candidates'] if x['id']=='A0')['independent_temperature_verification']['vector_rmse'],
                    next(x for x in b['sensors'][sensor]['candidates'] if x['id']=='A0')['independent_temperature_verification']['vector_rmse'])

    def test_no_holdout_and_short_temperature_plan_are_not_approved(self):
        rows=fake_thermal_rows()
        for r in rows:r['temperature_split']='fit'
        with tempfile.TemporaryDirectory() as d:
            out=run_thermal_model_selection(d,rows,[-20,0,25,45,70])
            for k in ('acc','gyro'):
                self.assertEqual(out['sensors'][k]['status'],'NOT_EVALUATED')
                self.assertFalse((Path(d)/f'thermal_{k}_selected_candidate.json').exists())

    def test_static_tilt_direction_improves_on_independent_temperature(self):
        rows=fake_thermal_rows()
        with tempfile.TemporaryDirectory() as d:
            out=run_thermal_model_selection(d,rows,[-20,0,25,45,70])
            acc={x['id']:x for x in out['sensors']['acc']['candidates']}
            winner=out['sensors']['acc']['selected_id']
            self.assertIn('static_gravity_direction_angle_rmse_deg',
                          acc[winner]['independent_temperature_verification'])
            self.assertLess(acc[winner]['independent_temperature_verification']['vector_rmse'],
                            acc['A0']['independent_temperature_verification']['vector_rmse'])


    def test_pv_calibration_uses_only_fit_conditions_and_not_holdout(self):
        rows=fake_thermal_rows()
        # Synthetic nonlinear chip-to-PV relation, not necessarily physical die temperature.
        for r in rows:
            chip=float(r['temperature_mean_c'])
            r['chamber_pv_mean_c']=chip+0.4+0.001*(chip-25)**2
        with tempfile.TemporaryDirectory() as d:
            a=run_thermal_model_selection(d,rows,[-20,0,25,45,70])
            t1=a['temperature_input_candidates']['T1']
            t2=a['temperature_input_candidates']['T2']
            self.assertIn('coefficients_c',t1)
            self.assertIn('coefficients_c',t2)
            self.assertLess(t2['pv_fit_rmse_c'],t1['pv_fit_rmse_c'])
            self.assertEqual(len(t2['fit_training_pairs']),4)
            changed=copy.deepcopy(rows)
            for r in changed:
                if r['temperature_split']=='validate' or r['split']=='validate':
                    r['chamber_pv_mean_c']+=12345.0
            b=run_thermal_model_selection(d,changed,[-20,0,25,45,70])
            self.assertEqual(t2['coefficients_c'],b['temperature_input_candidates']['T2']['coefficients_c'])
            for sensor in ('acc','gyro'):
                self.assertEqual(a['sensors'][sensor]['selected_id'],b['sensors'][sensor]['selected_id'])
                self.assertEqual(len(a['sensors'][sensor]['candidates']),28)
                self.assertEqual(sum(c['status']=='candidate_evaluated' for c in a['sensors'][sensor]['candidates']),19)
                self.assertIn('纯插值',next(c for c in a['sensors'][sensor]['candidates'] if c['id']=='T2-D3')['reason'])

    def test_pv_csv_original_folder_used_for_offline_reanalysis(self):
        import csv
        rows=fake_thermal_rows()
        for r in rows: r['frame_count']=1  # synthetic CSV contains one test frame per step
        with tempfile.TemporaryDirectory() as d:
            source=Path(d)/'original'; source.mkdir()
            output=source/'analysis';output.mkdir()
            with (source/'imu_frame_means.csv').open('w',encoding='utf-8-sig',newline='') as f:
                writer=csv.DictWriter(f,fieldnames=['target_temp_c','step','imu_temp_c','chamber_pv_c'])
                writer.writeheader()
                for r in rows:
                    writer.writerow({'target_temp_c':r['temperature_target_c'],
                       'step':r['step_id'], 'imu_temp_c':r['temperature_mean_c'],
                       'chamber_pv_c':r['temperature_target_c']+0.35})
            result=run_thermal_model_selection(output,rows,[-20,0,25,45,70],source_folder=source)
            self.assertEqual(result['pv_telemetry']['matched'],len(rows))
            self.assertIn('coefficients_c',result['temperature_input_candidates']['T1'])
            self.assertIn('coefficients_c',result['temperature_input_candidates']['T2'])
            self.assertTrue((output/'thermal_model_selection.json').is_file())

    def test_bad_pv_never_creates_fake_temperature_calibration(self):
        rows=fake_thermal_rows()
        with tempfile.TemporaryDirectory() as d:
            result=run_thermal_model_selection(d,rows,[-20,0,25,45,70])
            self.assertIn('error',result['temperature_input_candidates']['T1'])
            self.assertIn('error',result['temperature_input_candidates']['T2'])
            for sensor in ('acc','gyro'):
                entry=result['sensors'][sensor]
                self.assertEqual(len(entry['candidates']),28)
                self.assertTrue(entry['selected_id']=='A0' or entry['selected_id'].startswith('T0-'))
                self.assertEqual(sum(c['status']=='candidate_evaluated' for c in entry['candidates']),7)
                self.assertTrue(all(c['status']=='not_estimated' for c in entry['candidates'] if c['id'].startswith(('T1-','T2-'))))

    def test_runtime_equivalence_uses_no_chamber_pv(self):
        from thermal_temperature_inputs import map_chip_temperature
        rows=fake_thermal_rows()
        for r in rows:
            chip=float(r['temperature_mean_c'])
            r['chamber_pv_mean_c']=chip+1.3
        with tempfile.TemporaryDirectory() as d:
            result=run_thermal_model_selection(d,rows,[-20,0,25,45,70])
            model=json.loads((Path(d)/'thermal_acc_model_candidates.json').read_text(encoding='utf8'))['T1-B1']
            raw=[0.03,-0.02,1.02]
            value=apply_temperature_model(model,raw,25.0)
            from thermal_compensation import _eval_poly
            eff=map_chip_temperature(model['temperature_input'],25.0)
            F=_eval_poly(model['forward_coeff'],eff)
            b=_eval_poly(model['bias_coeff'],eff)
            expected=np.linalg.solve(F,np.asarray(raw)-b)
            self.assertTrue(np.allclose(value,expected,atol=1e-10))
            self.assertAlmostEqual(eff,26.3,places=6)
            with self.assertRaises(ValueError):apply_temperature_model(model,raw,200)


    def test_eight_temperatures_support_all_twenty_eight_evaluations(self):
        temps=[-20,-10,0,15,25,40,55,70]
        rows=fake_thermal_rows(temps=temps)
        for r in rows:
            chip=float(r['temperature_mean_c'])
            r['chamber_pv_mean_c']=chip+0.3+0.00015*(chip-25)**2
        with tempfile.TemporaryDirectory() as d:
            result=run_thermal_model_selection(d,rows,temps)
            for sensor in ('acc','gyro'):
                entry=result['sensors'][sensor]
                self.assertEqual(len(entry['candidates']),28)
                failed=[(r['id'],r.get('reason')) for r in entry['candidates'] if r['status']!='candidate_evaluated']
                self.assertEqual(failed,[])
                self.assertEqual(len(entry['final_holdout_setpoints_c']),3)

if __name__=='__main__':unittest.main(verbosity=2)
