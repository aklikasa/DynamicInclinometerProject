# -*- coding: utf-8 -*-
import csv, json, math, sys, tempfile, unittest
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from production_r5_cycle import decide_transition,write_cycle_manifest
from production_cycle_analysis import (transformed_features,fit_candidate,forward_matrix,
   candidate_ids,choose_model,model_parts)
from production_ramp import FIELDS,analyze_ramp_file,locate_ramp_file
from production_six_axis import analyze_six_axis_records


def training(sensor,n=12):
    rng=np.random.default_rng(22 if sensor=='acc' else 123)
    rows=[]
    for t in range(-40,86,10):
        for i in range(n):
            ref=rng.normal(size=3)
            if sensor=='acc':ref/=np.linalg.norm(ref)
            bias=np.array([.004,-.003,.002] if sensor=='acc' else [.008,-.003,.005])
            obs=ref+bias
            rows.append({'sensor':sensor,'reference':ref.tolist(),'temperature_mean_c':float(t),
                         '_direction':'warming','temperature_target_c':float(t),
                         'step_id':str(i),'mode':'static' if sensor=='acc' else 'rate',
                         ('acc_raw_mean_g' if sensor=='acc' else 'gyro_raw_mean_dps'):obs.tolist(),
                         'temperature_span_c':.01,'temperature_split':'fit',
                         'split':'fit'})
    return rows


class R5ProductionTests(unittest.TestCase):
    def test_cycle_only_chains_on_all_safety_readbacks(self):
        ok=decide_transition('warming',True,True,True,True,True)
        self.assertEqual(ok['action'],'next')
        self.assertEqual(decide_transition('cooling',True,True,True,True,True)['action'],'analyze')
        for k in range(5):
            checks=[True]*5;checks[k]=False
            x=decide_transition('warming',*checks)
            self.assertEqual(x['action'],'halt',checks)
        self.assertEqual(decide_transition('bad',True,True,True,True,True)['action'],'halt')
    def test_manifest_records_independent_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            cycle={'phase':'cooling','status':'WARMING_COMPLETED',
                   'batch_id':'PCB_A-09','runs':{'warming':'abc','cooling':'xyz'},'approved':True}
            write_cycle_manifest(tmp,cycle)
            saved=json.loads((Path(tmp)/'R5_CYCLE_PCB_A-09.json').read_text('utf8'))
            self.assertTrue(saved['two_separate_run_folders_required'])
            self.assertFalse(saved['not_production_release'] is False)
            with self.assertRaises(ValueError):write_cycle_manifest(tmp,{**cycle,'batch_id':'../../no'})
    def test_continuous_piecewise_derivatives(self):
        for model,knot in [('SEG2_0',0.),('SEG3_0',0.),('SEG2_25',25.),('SEG3_25',25.)]:
            delta=1e-6;kn=(knot-22.5)/62.5
            f0=transformed_features(kn,model);left=transformed_features(kn-delta,model)
            right=transformed_features(kn+delta,model)
            self.assertTrue(np.all(np.isfinite(f0)))
            self.assertLess(np.max(np.abs(left+right-2*f0)),2e-9)
    def test_single_curve_never_selects_phase_model(self):
        rows=training('acc',n=12)
        fit=[r for r in rows if r['temperature_mean_c']%20==0]
        v=[{**r,'split':'validate'} for r in fit]
        h=[{**r,'split':'validate','temperature_split':'validate'} for r in rows
           if r['temperature_mean_c']%20!=0]
        # Artificially all in one direction to keep the implementation simple.
        allrows=fit+v+h
        m=choose_model(allrows,'acc',{'T0':{'id':'T0'}},'single')
        self.assertFalse(m['model']['phase'])
        self.assertEqual(next(x for x in m['scores'] if x['model']=='T0-D3_HY')['status'],'not_evaluated')
        self.assertEqual(len(candidate_ids()),34)
    def test_temperature_ramp_independent_both_directions(self):
        models={s:{'model':fit_candidate(training(s),s,'T0-D2',{'T0':{'id':'T0'}})} for s in ('acc','gyro')}
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'R5_RAMP_test.csv'
            with path.open('w',encoding='utf-8-sig',newline='') as f:
                writer=csv.DictWriter(f,fieldnames=FIELDS);writer.writeheader()
                k=0
                for j in range(2):
                    for i in range(400):
                        t=-10+12*i/399 if j==0 else 2-12*i/399
                        row={'unix_s':1000+k,'chip_c':t,'pv_c':t+.1,
                            'acc_x_g':.004,'acc_y_g':-.003,'acc_z_g':1.002,
                            'gyro_x_dps':.008,'gyro_y_dps':-.003,'gyro_z_dps':.005,
                            'frame_count':k,'wk_stopped_confirmed':True,
                            'device_sn':'PCB1','batch_id':'LOT1'}
                        writer.writerow(row);k+=1
            self.assertEqual(locate_ramp_file(tmp,'LOT1'),[path])
            info=analyze_ramp_file(path,models)
            for s in ('acc','gyro'):
                self.assertEqual(info[s]['status'],'EVALUATED',info[s])
                self.assertTrue(info[s]['pass'],info[s])
                self.assertGreater(info[s]['directions']['cooling'],10)
    def test_ramp_refuses_fake_standstill(self):
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/'R5_RAMP_false.csv'
            with file.open('w',newline='',encoding='utf-8-sig') as f:
                writer=csv.DictWriter(f,fieldnames=FIELDS);writer.writeheader()
                writer.writerow({**dict.fromkeys(FIELDS,0),'wk_stopped_confirmed':False,'device_sn':'A','batch_id':'B'})
            from production_ramp import load_ramp_rows
            with self.assertRaisesRegex(ValueError,'停车'):load_ramp_rows(file)
    def test_dynamic_cross_product_two_axis_excitation(self):
        models={s:{'model':fit_candidate(training(s),s,'T0-D2',{'T0':{'id':'T0'}})} for s in ('acc','gyro')}
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/'imu_full_frames.jsonl'
            rows=[]
            with file.open('w',encoding='utf-8') as f:
                for axis in ('X','Y'):
                    step='GYRO_VAL_'+axis+'_01'
                    rows.append({'step_id':step,'sensor':'gyro','mode':'rate',
                                 'temperature_split':'validate','split':'validate'})
                    for k in range(130):
                        time=k*.1;omega=.1
                        if axis=='X':
                            g=[0.,math.sin(omega*time),math.cos(omega*time)]
                            w=[omega*180/math.pi,0.,0.]
                        else:
                            g=[-math.sin(omega*time),0.,math.cos(omega*time)]
                            w=[0.,omega*180/math.pi,0.]
                        acc=np.array(g)+np.array([.004,-.003,.002])
                        gyr=np.array(w)+np.array([.008,-.003,.005])
                        frame={'monotonic_time_ns':int((100000+(1 if axis=='X' else 2)*100+time)*1e9),
                               'acc_g_arr':[acc.tolist()]*16,
                               'gyr_dps_arr':[gyr.tolist()]*16,'temp_c':25.}
                        f.write(json.dumps({'step_id':step,'frame':frame})+'\n')
            runs={'warming':{'folder':tmp,'rows':rows}}
            result=analyze_six_axis_records(runs,models)
            self.assertEqual(result['status'],'EVALUATED',result)
            self.assertTrue(result['pass'],result)
            self.assertLess(result['residual_rmse_per_s'],.003)

if __name__=='__main__':unittest.main()
