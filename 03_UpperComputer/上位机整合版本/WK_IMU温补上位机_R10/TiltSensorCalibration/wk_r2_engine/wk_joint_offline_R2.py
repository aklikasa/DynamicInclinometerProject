# -*- coding: utf-8 -*-
"""WK dual axis / IMU 15-temperature offline calibration R2.

Research only; read-only inputs. Reference model, not physical turntable metrology.
The immutable output is deliberately not a firmware-loadable coefficient package.

Use: py -3 wk_joint_offline_R2.py "E:\\动态倾角仪研发\\溫補測試" [--skip-raw]
"""
from __future__ import annotations
import argparse, copy, csv, hashlib, html, json, math, os, sys, time
from pathlib import Path
from collections import defaultdict, deque, Counter
from datetime import datetime, timezone, timedelta

try:
    import numpy as np
    from scipy.optimize import minimize, minimize_scalar
except ImportError as exc:
    sys.exit('缺少numpy/scipy，请运行 pip install -r requirements.txt: '+str(exc))

sys.path.insert(0,str(Path(__file__).resolve().parent/'engine'))
from thermal_model_catalog import full_catalog
from thermal_temperature_inputs import attach_chamber_pv, fit_pv_equivalent_transform, map_chip_temperature
from thermal_model_selection import _candidate, _baseline, _group_fit, _errors_inrange_preview
from thermal_compensation import _eval_poly

VERSION='R2.0 / 2026-11-09'
WARNING='仅研究性同源联合反演，不是机械转台计量校准，不构成六轴绝对对齐/整机精度认证，不可直接烧录参数。'
QUALITY={'acc_vector_rmse_mg':2.0,'acc_norm_rmse_mg':1.0,'acc_direction_rmse_deg':0.10,'gyro_vector_rmse_dps':0.030}

def save_json(path,obj):
    path.write_text(json.dumps(obj,indent=2,ensure_ascii=False,allow_nan=False,default=lambda v:float(v) if isinstance(v,np.number) else str(v)),encoding='utf-8')

def write_csv(path,items):
    if not items:return
    keys=list(dict.fromkeys(k for d in items for k in d))
    with path.open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=keys,extrasaction='ignore');w.writeheader();w.writerows(items)

def locate(root,stem,ext,required=False):
    import re
    files=[p for p in root.iterdir() if p.is_file() and p.suffix.lower()==ext.lower()
           and re.fullmatch(re.escape(stem)+r'(?:\s*\(\d+\))?',p.stem,re.I)]
    files.sort(key=lambda p:(p.stem!=stem,p.name))
    if files:return files[0]
    if required:raise FileNotFoundError('实验目录缺少 '+stem+ext)
    return None

def partitions(rows,sensor):
    found=[r for r in rows if r.get('sensor')==sensor and (sensor!='acc' or r.get('mode')=='static')]
    tr=[r for r in found if r.get('temperature_split')=='fit' and r.get('split')=='fit']
    va=[r for r in found if r.get('temperature_split')=='fit' and r.get('split')=='validate']
    ho=[r for r in found if r.get('temperature_split')=='validate' and r.get('split')=='validate']
    if not tr or not va or not ho:raise ValueError(f'{sensor} 缺少独立分组（拟合工况/同温独立姿态/独立温度）')
    if {r['temperature_target_c'] for r in tr}&{r['temperature_target_c'] for r in ho}:
        raise ValueError('训练温度和独立验证温度重叠，拒绝泄漏')
    return tr,va,ho

def ref_acc(rows,delta=0.,elev=0.):
    # ref = Rz(-phi) R_a(-(theta+delta)) [0,0,1], a=(cos eps,0,sin eps)
    theta=np.deg2rad([float(r['outer_actual_mean_deg'])+delta for r in rows]);phi=np.deg2rad([float(r['inner_actual_mean_deg']) for r in rows])
    ce=math.cos(math.radians(elev));se=math.sin(math.radians(elev))
    x=ce*se*(1-np.cos(theta));y=ce*np.sin(theta);z=np.cos(theta)+se*se*(1-np.cos(theta))
    return np.column_stack([np.cos(phi)*x+np.sin(phi)*y,-np.sin(phi)*x+np.cos(phi)*y,z])

def ref_gyro(rows,elev=0.):
    # Outer-axis body projection after inner rotation; zero position shift does not change axis angular velocity.
    phi=np.deg2rad([float(r['inner_actual_mean_deg']) for r in rows]);v=np.array([float(r['outer_rate_mean_dps']) for r in rows]);u=np.array([float(r['inner_rate_mean_dps']) for r in rows]);ce=math.cos(math.radians(elev));se=math.sin(math.radians(elev))
    projected=np.column_stack([ce*np.cos(phi)*v,-ce*np.sin(phi)*v,u+se*v])
    # Preserve the upstream reference's independent speed/phase convention at eps=0.
    # This matters at GYRO_ZERO rows: their target reference is EXACTLY zero
    # although encoder speed noise is nonzero.
    if all('reference' in r for r in rows):
        nominal=np.column_stack([np.cos(phi)*v,-np.sin(phi)*v,u])
        baseline=np.asarray([r['reference'] for r in rows],dtype=float)
        projected=baseline+(projected-nominal)
        static=np.asarray([r.get('mode')=='static' for r in rows])
        projected[static]=0.
    return projected

def matrix_polar(F):
    U,_,Vt=np.linalg.svd(F);R=U@Vt
    if np.linalg.det(R)<0:U[:,-1]*=-1;R=U@Vt
    return R

def raw_matrix(rows,delta,elev):
    refs=ref_acc(rows,delta,elev);obs=np.asarray([r['acc_raw_mean_g'] for r in rows],float)
    u=(np.asarray([r['temperature_mean_c'] for r in rows])-25.)/25.
    X=np.column_stack((refs,np.ones(len(rows)),u,u*u))
    B,*_=np.linalg.lstsq(X,obs,rcond=None)
    F=B[:3,:].T
    if abs(np.linalg.det(F))<1e-7 or np.linalg.cond(F)>100:raise ValueError('转台参数试探导致矩阵病态')
    pred=np.linalg.solve(F,(obs-X[:,3:]@B[3:,:]).T).T
    return float(np.mean(np.sum((pred-refs)**2,axis=1))),B

def geometry_fit(rows,mid):
    if mid=='M0':return (0.,0.),{'method':'fixed nominal'}
    def objective(z):
        delta,elev=(float(z[0]),float(z[1]))
        try:return raw_matrix(rows,delta,elev)[0]
        except (ValueError,np.linalg.LinAlgError):return 1.0
    if mid in ('M1','M2'):
        axis=0 if mid=='M1' else 1
        bound=(-.8,.8) if axis==0 else (-.25,.25)
        def f(x):
            z=[0.,0.];z[axis]=x;return objective(z)
        sol=minimize_scalar(f,bounds=bound,method='bounded',options={'xatol':1e-9})
        result=[0.,0.];result[axis]=float(sol.x)
        return tuple(result),{'method':'bounded_scalar','success':bool(sol.success)}
    if mid=='M3':
        starts=[[0,0],[.18,.02],[-.18,-.02],[.18,-.02],[-.18,.02],[.35,.1],[-.35,-.1]]
        def f(z):
            if abs(z[0])>.8 or abs(z[1])>.25:return 1.+sum(z*z)
            return objective(z)
        opts=[minimize(f,np.array(s,float),method='Nelder-Mead',options={'maxiter':1800,'xatol':1e-9,'fatol':1e-14}) for s in starts]
        winners=[x for x in opts if abs(x.x[0])<=.8 and abs(x.x[1])<=.25]
        if not winners:raise ValueError('几何多起点搜索全失败')
        best=min(winners,key=lambda x:x.fun)
        return tuple(float(v) for v in best.x),{'method':'7-start Nelder-Mead','success':bool(best.success),'start_count':len(opts),'best_objective_g2':float(best.fun)}
    raise ValueError('未知几何模型')

def substitute_reference(rows,geometry,sensor):
    # Never mutate the acquired data. Geometry is applied to both sensors in the *same* stage frame.
    copyrows=[dict(r) for r in rows]
    refs=ref_acc(copyrows,*geometry) if sensor=='acc' else ref_gyro(copyrows,geometry[1])
    for r,ref in zip(copyrows,refs):r['reference']=ref.tolist()
    return copyrows

def pv_transforms(rows,root,raw_date=None):
    # PV only from synchronized raw file, never setpoint imputation.
    path=locate(root,'imu_frame_means','.csv')
    base={'T0':{'id':'T0','name':'原始芯片温度','kind':'raw_chip','degree':0,'formula':'Te = T_chip'}}
    details={'raw_csv_found':bool(path),'pv_status':'PV_NOT_PROVIDED','pv_time_match':None}
    if not path:
        for d in (1,2):base[f'T{d}']={'id':f'T{d}','error':'同次实验imu_frame_means.csv缺失，不得冒充已评价'}
        return base,details
    # Optional run-date fingerprint check. When raw JSONL is present, compare wall-time to CSV.
    if raw_date is not None:
        try:
            with path.open(encoding='utf-8-sig',newline='') as f:
                first=next(csv.DictReader(f));date=datetime.fromisoformat(first['utc'].replace('Z','+00:00'))
            dif=abs((date.astimezone(timezone.utc)-raw_date.astimezone(timezone.utc)).total_seconds())/3600.
            details['pv_time_gap_hours']=dif;details['pv_time_match']=dif<36
            if dif>36:
                details['pv_status']='PV_WRONG_EXPERIMENT_TIMESTAMP'
                for d in (1,2):base[f'T{d}']={'id':f'T{d}','error':'PV与IMU逐帧日志时间相差>36小时，拒绝跨实验关联'}
                return base,details
        except (KeyError,ValueError,StopIteration) as e:
            details['pv_date_check_note']=str(e)
    enriched,pv_info=attach_chamber_pv(rows,root)
    matched=pv_info.get('matched',0);details.update({'pv_status':pv_info.get('status'),'matched_rows':matched,'total_rows':len(rows),'pv_info':pv_info})
    # Require good overall match to avoid another experiment's accidental same-step identifiers.
    if matched/max(1,len(rows))<.9:
        details['pv_status']='PV_LOW_MATCH_OR_WRONG_RUN'
        for d in (1,2):base[f'T{d}']={'id':f'T{d}','error':'PV工况匹配率不足90%，可能不是同一次实验'}
        return base,details
    for d in (1,2):
        try:base[f'T{d}']=fit_pv_equivalent_transform(enriched,d)
        except Exception as exc:base[f'T{d}']={'id':f'T{d}','error':str(exc)}
    details['pv_status']='PV_ACCEPTED'
    return base,details

def candidates_for(rows,sensor,transforms,geometry,train_only=False):
    # Same original 28 structural candidates, no custom invention of T1/T2.
    replaced=substitute_reference(rows,geometry,sensor)
    groups=_group_fit(replaced,sensor);baseat,F0,b0=_baseline(groups,sensor)
    condition=[r for r in replaced if r.get('sensor')==sensor and r.get('temperature_split')=='fit' and r.get('split')=='validate']
    if not condition:raise ValueError('同温姿态验证集为空')
    scores=[];models={}
    for entry in full_catalog():
        mid=entry['id'];f=entry['family'];deg=entry['degree'];tempid=entry['input_id']
        item={'id':mid,'family':f,'degree':deg,'temp_input':tempid,'status':'not_evaluated'}
        try:
            if transforms[tempid].get('error'):raise ValueError(transforms[tempid]['error'])
            m=_candidate(groups,sensor,f,deg,F0,b0,baseat,transforms[tempid]);sel=_errors_inrange_preview(condition,sensor,m)
            complexity={'A':0,'B':1,'C':2,'D':3}[f];penalty={'T0':0,'T1':1,'T2':2}[tempid]
            score=float(sel['vector_rmse']*(1+0.02*deg+0.025*complexity+0.02*penalty))
            item.update(status='evaluated',same_temp_vector_rmse=float(sel['vector_rmse']),same_temp_vector_max=float(sel['vector_max']),score=score,
                        eligible_count=sel['count'],excluded_out_of_range=int(sel.get('excluded_out_of_range_count',0)))
            models[mid]=m
        except (KeyError,ValueError,TypeError,np.linalg.LinAlgError) as exc:item['reason']=str(exc)
        scores.append(item)
    avail=[s for s in scores if s['status']=='evaluated']
    if not avail:raise ValueError(f'{sensor}: 28个候选全部不可用')
    best=min(avail,key=lambda r:(r['score'],r['degree'],r['id']))
    return scores,models,best

def predict_model(model,rows,sensor):
    result=[];extrap=[];a,b=map(float,model['fit_temperature_range_c']);name='acc_raw_mean_g' if sensor=='acc' else 'gyro_raw_mean_dps'
    for idx,r in enumerate(rows):
        t=float(r['temperature_mean_c'])
        if not (a-1e-8<=t<=b+1e-8):extrap.append(idx);result.append(None);continue
        try:
            te=map_chip_temperature(model.get('temperature_input'),t)
            F=_eval_poly(model['forward_coeff'],te);bias=_eval_poly(model['bias_coeff'],te)
            if np.linalg.cond(F)>100 or abs(np.linalg.det(F))<1e-7:raise ValueError('matrix singular')
            result.append(np.linalg.solve(F,np.array(r[name],float)-bias))
        except (ValueError,TypeError,np.linalg.LinAlgError):extrap.append(idx);result.append(None)
    return result,extrap

def summarize_model(model,rows,sensor,geometry,label):
    refs=ref_acc(rows,*geometry) if sensor=='acc' else ref_gyro(rows,geometry[1]);pred,missing=predict_model(model,rows,sensor)
    valid=[i for i in range(len(rows)) if pred[i] is not None];allitems=[]
    for idx in range(len(rows)):
        row=rows[idx];p=pred[idx];r=refs[idx]
        item={'partition':label,'sensor':sensor,'step_id':row.get('step_id'), 'temperature_setpoint_c':row.get('temperature_target_c'),
              'chip_c':row.get('temperature_mean_c'),'mode':row.get('mode'), 'outer_deg':row.get('outer_actual_mean_deg'),
              'inner_deg':row.get('inner_actual_mean_deg'), 'target_rate_dps':row.get('target_rate_dps'),
              'status':'OK' if p is not None else 'OUTSIDE_MODEL_TEMPERATURE_DOMAIN'}
        if p is not None:
            d=p-r;item.update(vector_error=float(np.linalg.norm(d)), ref_x=float(r[0]),ref_y=float(r[1]),ref_z=float(r[2]),
                            corrected_x=float(p[0]),corrected_y=float(p[1]),corrected_z=float(p[2]))
            if sensor=='acc':
                item['vector_error_mg']=1000*item['vector_error'];item['norm_error_mg']=1000*(np.linalg.norm(p)-1.)
                item['direction_error_deg']=float(np.degrees(np.arccos(np.clip(np.dot(p,r)/(np.linalg.norm(p)*np.linalg.norm(r)),-1,1))))
        allitems.append(item)
    if len(valid)<.9*len(rows):
        return {'count_total':len(rows),'count_valid':len(valid),'excluded':len(missing),'status':'INVALID_MORE_THAN_10_PERCENT_OUTSIDE_DOMAIN'},allitems
    errors=np.array([pred[i]-refs[i] for i in valid]);norms=np.linalg.norm(errors,axis=1)
    mets={'count_total':len(rows),'count_valid':len(valid),'excluded':len(missing),'vector_rmse':float(np.sqrt(np.mean(norms**2))),
          'vector_max':float(np.max(norms)),'status':'EVALUATED_IN_RANGE_ONLY' if missing else 'EVALUATED_FULL'}
    if sensor=='acc':
        mets['vector_rmse_mg']=1000*mets['vector_rmse'];mets['vector_max_mg']=1000*mets['vector_max'];mets['norm_rmse_mg']=float(np.sqrt(np.mean([(np.linalg.norm(pred[i])-1)**2 for i in valid]))*1000.)
        mets['direction_rmse_deg']=float(np.sqrt(np.mean([allitems[i]['direction_error_deg']**2 for i in valid])))
        mets['direction_max_deg']=float(max(allitems[i]['direction_error_deg'] for i in valid))
    else:
        static=[i for i in valid if rows[i].get('mode')=='static'];rate=[i for i in valid if rows[i].get('mode')=='rate']
        for key,indices in [('static',static),('rate',rate)]:
            if indices:mets[key+'_vector_rmse_dps']=float(np.sqrt(np.mean([np.linalg.norm(pred[i]-refs[i])**2 for i in indices])))
    return mets,allitems

def gyro_alignment(acc_model,gyro_model,geometry,accrows,gyrorows):
    # Both models target P; different signed sensor channel conventions are allowed.
    # A reflected 3x3 forward map (det<0) is NOT a proper 3D physical rotation.
    def F(model,t):return _eval_poly(model['forward_coeff'],map_chip_temperature(model.get('temperature_input'),t))
    time=25.
    try:
        Fa,Fg=F(acc_model,time),F(gyro_model,time)
        deta,detg=float(np.linalg.det(Fa)),float(np.linalg.det(Fg))
        if deta*detg<0:
            relative_angle=None
            angle_status='INVALID_AS_PHYSICAL_ANGLE_DIFFERENT_DETERMINANT_SIGNS'
        else:
            Ra,Rg=matrix_polar(Fa),matrix_polar(Fg)
            relative_angle=float(np.degrees(np.arccos(np.clip((np.trace(Rg@Ra.T)-1)*.5,-1,1))))
            angle_status='POLAR_DIAGNOSTIC_NOT_PHYSICAL_ALIGNMENT'
        gram_a=Fa@Fa.T;gram_g=Fg@Fg.T
        invariant={'acc_input_channel_gram':gram_a.tolist(),'gyro_input_channel_gram':gram_g.tolist()}
    except Exception as exc:
        relative_angle=None;deta=None;detg=None;angle_status='NOT_EVALUABLE: '+str(exc);invariant={}
    return {'coordinate_definition':'both corrected outputs in modelled moving platen frame P (NOT necessarily PCB/product frame)',
            'acc_gyro_forward_determinants_at_25c':{'acc':deta,'gyro':detg},
            'determinant_signs_differ':bool(deta is not None and detg is not None and deta*detg<0),
            'relative_polar_rotation_status':angle_status,
            'polar_rotation_relative_angle_deg_RESEARCH_ONLY':relative_angle,
            'intrinsic_channel_gram_checks':invariant,
            'gyro_reference_uses_same_outer_elevation_as_acc':True,
            'geometry_parameters_used_for_both_sensors':list(geometry),
            'true_acc_gyro_physical_axes_misalignment_deg':'NOT_IDENTIFIABLE_WITHOUT_INDEPENDENT_REFERENCE_AND_DYNAMIC_TEST',
            'dynamic_kinematic_test':'NOT_EXECUTED_ON_SUMMARY_MEANS',
            'warning':'行列式符号不同表示当前数据通道/模型可含反射（轴交换或符号约定）；不能把它当作两个芯片相差180°，也不能通过极分解认定真实物理对齐。必须核验原始六轴坐标定义与动态叉乘一致性。'}

def raw_start_date(p):
    if not p:return None
    try:
        with p.open(encoding='utf-8-sig') as f:
            for s in f:
                if s.strip():
                    obj=json.loads(s);t=obj.get('frame',{}).get('wall_time_ns')
                    if t:return datetime.fromtimestamp(int(t)/1e9,timezone.utc)
    except Exception:return None
    return None

def frame_sanitize(samples,sigma):
    # Identical to upstream production_calibration.frame_average_sanitized (algorithmic snapshot).
    a=np.asarray(samples,float)
    if a.ndim!=2 or a.shape[1]!=3 or len(a)<8 or not np.all(np.isfinite(a)):
        return None,len(a) if a.ndim==2 else 0,0
    med=np.median(a,axis=0);mad=np.median(np.abs(a-med),axis=0)
    floor=1e-4 if np.max(np.abs(a))<2 else .01
    good=np.max(np.abs(a-med)/np.maximum(mad*1.4826,floor),axis=1)<=sigma
    if np.mean(good)<.8:return None,len(a),int(good.sum())
    return a[good].mean(axis=0),len(a),int(good.sum())

def replay_frames(root,rows,out):
    raw=locate(root,'imu_full_frames','.jsonl');fb=locate(root,'wk_independent_position_feedback','.jsonl')
    report={'status':'NO_RAW_FILES','files':{},'replay':{},'feedback':{}}
    expected={(float(r['temperature_target_c']),str(r['step_id'])):r for r in rows}
    if raw:
        report['status']='REPLAY_ATTEMPTED'
        groups=defaultdict(lambda:deque(maxlen=550));record_total=Counter();bad=0;n=0
        for s in raw.open(encoding='utf-8-sig',errors='replace'):
            if not s.strip():continue
            n+=1
            try:o=json.loads(s);key=(float(o['target_temp_c']),str(o['step_id']));f=o['frame']
            except (ValueError,KeyError,TypeError):bad+=1;continue
            if key not in expected:continue
            rec=expected[key];sigma=3. if rec['sensor']=='acc' and rec['mode']=='static' else 6.
            a,ar,aa=frame_sanitize(f.get('acc_g_arr',[]),3.)
            g,gr,ga=frame_sanitize(f.get('gyr_dps_arr',[]),6.)
            if a is None or g is None:continue
            groups[key].append({'acc':a,'gyro':g,'temp':float(f['temp_c']),'acc_n':aa,'gyro_n':ga,
                                'acc_raw':ar,'gyro_raw':gr,'frame_update_count':f.get('frame_update_count'),
                                'wall_time_ns':f.get('wall_time_ns')})
            record_total[key]+=1
        report['files']['imu_full_frames']={'bytes':raw.stat().st_size,'records':n,'bad_json':bad,'matched_condition_ids':len(groups)}
        results=[];matched=0
        for key,r in expected.items():
            records=list(groups.get(key,[]));target=int(r.get('frame_count') or 0)
            if target and len(records)>=target:records=records[-target:]
            if len(records)<min(target,50):continue
            sensor=r['sensor'];mode=r['mode'];sigma=3. if sensor=='acc' and mode=='static' else 6.
            mat=np.asarray([x['acc' if sensor=='acc' and mode=='static' else 'gyro'] for x in records])
            mid=np.median(mat,axis=0);mad=np.median(np.abs(mat-mid),axis=0)
            mask=np.max(np.abs(mat-mid)/np.maximum(mad*1.4826,1e-4 if mode=='static' else .01),axis=1)<=sigma
            if not mask.any():continue
            acc=np.mean([x['acc'] for i,x in enumerate(records) if mask[i]],axis=0)
            gyr=np.mean([x['gyro'] for i,x in enumerate(records) if mask[i]],axis=0)
            dr=float(np.linalg.norm(acc-np.array(r['acc_raw_mean_g']))*1000)
            dg=float(np.linalg.norm(gyr-np.array(r['gyro_raw_mean_dps'])))
            results.append({'setpoint_c':key[0],'step_id':key[1],'accepted_frames_report':r['accepted_frames'],
                            'frames_replayed':len(records),'replayed_kept':int(mask.sum()),'acc_mean_delta_mg':dr,
                            'gyro_mean_delta_dps':dg,'matches_1e6g_1e5dps':dr<.001 and dg<1e-5,
                            'note':'跨帧筛选已按源码重算；如存在重试，需要以最终提交段精确定位。'})
            matched+=1
        write_csv(out/'逐帧3sigma重放对账.csv',results)
        ratio=matched/len(expected)
        report['replay']={'total_expected_conditions':len(expected),'conditions_replayed':matched,'coverage':ratio,
                          'exact_mean_agreement_count':sum(x['matches_1e6g_1e5dps'] for x in results),
                          'mean_acc_diff_mg':float(np.mean([x['acc_mean_delta_mg'] for x in results])) if results else None,
                          'status':'FULL_2STAGE_MEANS_REPLAY_AUDITED' if ratio>.95 else 'PARTIAL_OR_WRONG_EXPERIMENT_RAW',
                          'limitation':'逐帧记录不含独立反馈与最终重试事务ID；结果有差异时不能自动覆盖已提交工况均值。'}
        if ratio<.90:report['status']='RAW_NOT_MATCHED_TO_SUMMARY'
    if fb:
        gr=defaultdict(lambda:{'n':0,'amin':[1e9,1e9],'amax':[-1e9,-1e9],'anchor':[None,None],'max_speed':[0,0]});bad=0;n=0
        for s in fb.open(encoding='utf-8-sig',errors='replace'):
            if not s.strip():continue
            n+=1
            try:
                o=json.loads(s);key=(float(o['temp_c']),str(o['step_id']))
                if o.get('phase')!='sample' or key not in expected:continue
                f=o['feedback'];v=gr[key];v['n']+=1
                for j,k in enumerate(('outer','inner')):
                    angle=float(f[k+'_position_deg']);speed=abs(float(f[k+'_speed_dps']))
                    if v['anchor'][j] is None:v['anchor'][j]=angle
                    delta=(angle-v['anchor'][j]+180)%360-180
                    v['amin'][j]=min(v['amin'][j],delta);v['amax'][j]=max(v['amax'][j],delta);v['max_speed'][j]=max(v['max_speed'][j],speed)
            except (ValueError,KeyError,TypeError):bad+=1
        res=[{'setpoint_c':k[0],'step_id':k[1],'feedback_sample_count':v['n'],
              'outer_span_deg':v['amax'][0]-v['amin'][0],'inner_span_deg':v['amax'][1]-v['amin'][1],
              'outer_max_speed_dps':v['max_speed'][0],'inner_max_speed_dps':v['max_speed'][1]} for k,v in gr.items() if v['n']]
        write_csv(out/'采样期转台位置反馈审计.csv',res)
        report['feedback']={'file_records':n,'bad_json':bad,'matched_conditions':len(res),'status':'ENCODER_STABILITY_ONLY_NOT_ABSOLUTE_ACCURACY'}
    return report

def dynamic_six_axis_check(root, acc_model, gyro_model, pv_info, out):
    """Slow-rate consistency check from time-synchronised *same-experiment* frame CSV.

    Checks dg/dt = -omega x g in common modelled platen frame; returns diagnostic
    residual only. It cannot separate translational acceleration or certify true axes.
    """
    p=locate(root,'imu_frame_means','.csv')
    if not p or pv_info.get('pv_status')!='PV_ACCEPTED':
        return {'status':'NOT_AVAILABLE','reason':'缺少与本次实验相匹配的逐帧CSV；无法做时序六轴运动学检验'}
    total=0;chosen=[];groups=defaultdict(list);bad=0
    with p.open(encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f)
        columns=set(reader.fieldnames or [])
        mandatory={'utc','target_temp_c','step','acc_x_g','acc_y_g','acc_z_g','gyro_x_dps','gyro_y_dps','gyro_z_dps','imu_temp_c','inner_rate_dps','outer_rate_dps'}
        if not mandatory.issubset(columns):
            return {'status':'NOT_AVAILABLE','reason':'时序CSV缺少运动学复核所需列: '+str(sorted(mandatory-columns))}
        for r in reader:
            total+=1
            try:
                if not r['step'].startswith(('GYRO_FIT','GYRO_VAL')):continue
                temp=float(r['imu_temp_c']);outer=float(r['outer_rate_dps']);inner=float(r['inner_rate_dps'])
                if abs(inner)+abs(outer)<2 or max(abs(inner),abs(outer))>20:continue
                t=datetime.fromisoformat(r['utc'].replace('Z','+00:00')).timestamp()
                a=np.array([float(r['acc_'+k+'_g']) for k in 'xyz'],float)
                gyro=np.array([float(r['gyro_'+k+'_dps']) for k in 'xyz'],float)
                ao=0.;wo=0.
                for model,x in ((acc_model,a),(gyro_model,gyro)):
                    low,high=model['fit_temperature_range_c']
                    if not low<=temp<=high:raise ValueError('temperature outside fit range')
                ate=map_chip_temperature(acc_model.get('temperature_input'),temp)
                gte=map_chip_temperature(gyro_model.get('temperature_input'),temp)
                acc=np.linalg.solve(_eval_poly(acc_model['forward_coeff'],ate),a-_eval_poly(acc_model['bias_coeff'],ate))
                rate=np.linalg.solve(_eval_poly(gyro_model['forward_coeff'],gte),gyro-_eval_poly(gyro_model['bias_coeff'],gte))*math.pi/180.
                key=(r['target_temp_c'],r['step'])
                groups[key].append((t,acc,rate));chosen.append(key)
            except (ValueError,KeyError,TypeError,np.linalg.LinAlgError):bad+=1
    # A 0.2-0.4 s secant slope suppresses frame quantization noise better than a 20 ms derivative.
    entries=[];e=[];signal=[]
    for key,arr in groups.items():
        if len(arr)<20:continue
        arr=sorted(arr,key=lambda x:x[0]);n=len(arr)
        step=8
        for i in range(step,n-step,3):
            t0,a0,_=arr[i-step];t1,a1,_=arr[i+step];dt=t1-t0
            if dt<.15 or dt>.9:continue
            tt,g,w=arr[i]
            if not .6<np.linalg.norm(g)<1.4:continue
            derivative=(a1-a0)/dt
            reference=-np.cross(w,g)
            magnitude=float(np.linalg.norm(reference))
            if magnitude<.02:continue
            residual=float(np.linalg.norm(derivative-reference))
            e.append(residual);signal.append(magnitude)
            if len(entries)<40000:
                entries.append({'setpoint_c':key[0],'step_id':key[1], 'unix_time_s':tt,
                                'kinematic_residual_g_per_s':residual,
                                'expected_derivative_g_per_s':magnitude,
                                'ratio_residual_to_expected':residual/magnitude})
    write_csv(out/'六轴时序运动学一致性_研究检查.csv',entries)
    if len(e)<100:return {'status':'INSUFFICIENT_EXCITATION','sample_count':len(e),'source_rows':total,'bad_csv':bad}
    return {'status':'RESEARCH_DIAGNOSTIC_ONLY_NOT_ALIGNMENT_CERTIFICATION', 'point_count':len(e),
            'source_rows':total,'bad_csv':bad,'rmse_residual_g_per_s':float(np.sqrt(np.mean(np.square(e)))),
            'reference_rate_rms_g_per_s':float(np.sqrt(np.mean(np.square(signal)))),
            'normalized_rmse':float(np.sqrt(np.mean(np.square(e)))/np.sqrt(np.mean(np.square(signal)))),
            'limitations':'仅在低速且重力占优时适用；采样时间戳/加速度的动态项、时延、滤波相位和转台反馈独立计量仍需验证；无法当作真实六轴对齐角。'}


def file_hash(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for part in iter(lambda:f.read(1<<20),b''):h.update(part)
    return h.hexdigest()

def html_output(out,record):
    esc=lambda x:html.escape(str(x))
    table=lambda rows,cols:'<table><thead><tr>'+''.join('<th>'+esc(k)+'</th>' for k in cols)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+esc(r.get(k,''))+'</td>' for k in cols)+'</tr>' for r in rows)+'</tbody></table>'
    geometry=[{'模型':x['id'],'δ零位等效°':round(x.get('zero_deg',0),6),'ε轴倾等效°':round(x.get('axis_elevation_deg',0),6),
               '同温选型分数':round(x.get('selection_score',1e9),8),'入选': '是' if x.get('selected') else ''} for x in record['geometry_ranking']]
    metrics=[]
    for sensor in ('acc','gyro'):
        for stage,metric in record['metrics'][sensor].items():
            metrics.append({'传感器':sensor,'数据集':stage,'数目':metric.get('count_valid'),
                            '向量RMSE':f"{metric.get('vector_rmse_mg',metric.get('vector_rmse',float('nan'))):.6f}",
                            '模长RMSE mg':round(metric.get('norm_rmse_mg',0),5),'角度RMSE°':round(metric.get('direction_rmse_deg',0),5),
                            '状态':metric.get('status')})
    rank=[]
    for sensor in ('acc','gyro'):
        for x in record['candidate_ranking'][sensor]:
            rank.append({'传感器':sensor,'模型':x['id'],'状态':x['status'],'同温选型RMSE':round(x.get('same_temp_vector_rmse',-1),7),
                         '选型分数':round(x.get('score',-1),7),'备注':x.get('reason','')})
    h='''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>WK R2 联合温补研究报告</title>
    <style>body{font-family:system-ui,'Microsoft YaHei',sans-serif;color:#1e293b;line-height:1.6;max-width:1150px;margin:30px auto;padding:0 22px;background:#f6f8fa}h1,h2{color:#203d59}section{background:#fff;border:1px solid #d9e1e8;border-radius:10px;padding:16px 24px;margin:18px 0}table{border-collapse:collapse;width:100%;font-size:12px;margin:12px 0 22px}th,td{border-bottom:1px solid #d8e3ea;padding:7px;text-align:left;word-break:break-word}th{background:#e8eff6}.notice{padding:16px;background:#fff5e5;border-left:4px solid #c68c34}</style></head><body>'''
    h+='<h1>WK 双轴转台／六轴IMU 联合温补与几何反演 · R2</h1><p>运行时间 '+esc(record['run_time'])+' | 设备 '+esc(record['device_sn'])+'</p>'
    h+='<div class="notice"><b>重要限制：</b>'+esc(WARNING)+' 28套是候选结构总数，不代表输入缺少同实验PV时能够全部估计。独立温度验证不可拿来反复调参。</div>'
    h+='<section><h2>一、完成内容与选型规则</h2><p>先只在拟合温度和拟合工况上估计几何参数；几何和28温补候选都只使用同温独立工况选型；选定并冻结模型后才读取独立温度验证误差。实际测得的IMU芯片温度用于温补。ACC与GYRO被统一映射到模型假定的同一末端负载坐标系P，不自动认定为PCB坐标系。</p>'
    h+='<p>入选几何 '+esc(record['selected_geometry'])+'，ACC '+esc(record['selected_models']['acc']['id'])+'，GYRO '+esc(record['selected_models']['gyro']['id'])+'</p></section>'
    h+='<section><h2>二、几何模型研究拟合</h2>'+table(geometry,['模型','δ零位等效°','ε轴倾等效°','同温选型分数','入选'])
    h+='<p>M0理想；M1外轴角度参考常数偏移；M2外轴轴线仰角；M3二者联合。δ无法区分机械零位与特定方向的初始重力基准偏移；ε也不能直接视为厂家转台真实倾角。</p></section>'
    h+='<section><h2>三、温补精度与最终未见温度检验</h2>'+table(metrics,['传感器','数据集','数目','向量RMSE','模长RMSE mg','角度RMSE°','状态'])+'<p>ACC向量单位mg；GYRO向量单位°/s。少量超出训练芯片温度范围的验证行按规则排除并如实报告；超过10%则失效，禁止静默外推。</p></section>'
    h+='<section><h2>四、原版28温补结构逐项排名</h2><p>包含A0及T0/T1/T2×B/C/D×1/2/3。T1/T2需要与本次实验匹配的真实温箱PV日志。不可评候选显示未评原因。</p>'+table(rank,['传感器','模型','状态','同温选型RMSE','选型分数','备注'])+'</section>'
    h+='<section><h2>五、六轴对齐：只能确认共同参考定义，不等于物理安装角已验证</h2><p>25℃前向矩阵行列式：ACC='+esc(round(record['alignment']['acc_gyro_forward_determinants_at_25c']['acc'],6) if record['alignment']['acc_gyro_forward_determinants_at_25c']['acc'] is not None else '不可算')+'，GYRO='+esc(round(record['alignment']['acc_gyro_forward_determinants_at_25c']['gyro'],6) if record['alignment']['acc_gyro_forward_determinants_at_25c']['gyro'] is not None else '不可算')+'。符号不同时必须核查原始通道坐标左右手与符号，不能解释成物理旋转180°。</p><p>统一坐标输出：ACC、GYRO分别按同一几何参考的校正矩阵输出到P。ACC的外轴参考偏移δ影响重力姿态；GYRO角速度参考不随常数δ改变，但必须使用相同轴线仰角ε。若只调整ACC参考，不调整GYRO参考，两者可能引入额外旋转误差。</p><p>正确同步姿态运动学：d(g)/dt=−ω×g；共同刚性旋转R对两边同时变换仍成立，分别采用不同R则一般不成立。</p><p><b>独立动态检验：</b>'+esc(record['alignment']['dynamic_kinematic_test'])+'；无法仅从每工况均值证明真实六轴同轴。</p></section>'
    h+='<section><h2>六、原始帧与独立位置反馈</h2><pre style="white-space:pre-wrap">'+esc(json.dumps(record['raw_replay'],ensure_ascii=False,indent=2))+'</pre></section>'
    h+='<section><h2>七、文件说明</h2><p>总览.json；28候选排名.csv；ACC逐工况.csv；GYRO逐工况.csv；最终研究模型参数.json；逐帧3sigma重放对账.csv；采样期转台位置反馈审计.csv。研究系数默认不可直接用于MCU。</p></section></body></html>'
    (out/'离线研究报告.html').write_text(h,encoding='utf-8')

def run(args):
    root=Path(args.folder).expanduser()
    if not root.is_dir():raise NotADirectoryError(root)
    measure=locate(root,'temperature_measurements','.json',True);conf=locate(root,'experiment_config','.json',True)
    summary=json.loads(measure.read_text(encoding='utf-8-sig'));cfg=json.loads(conf.read_text(encoding='utf-8-sig'))
    rows=summary['rows'];a_tr,a_va,a_ho=partitions(rows,'acc');g_tr,g_va,g_ho=partitions(rows,'gyro')
    dev=str(summary.get('device_sn',cfg.get('device_sn','unknown')))
    if cfg.get('device_sn') and cfg['device_sn']!=dev:raise ValueError('设备编号与试验配置不一致')
    if cfg.get('axis_model','outer_x_inner_z')!='outer_x_inner_z':raise ValueError('R2只支持已经确认的outer_x_inner_z结构；其它轴系不能静默套用')
    print(f'输入目录: {root}\n设备: {dev}; 总工况={len(rows)}; ACC训练/同温/跨温={len(a_tr)}/{len(a_va)}/{len(a_ho)}; GYRO={len(g_tr)}/{len(g_va)}/{len(g_ho)}',flush=True)
    stamp=datetime.now().strftime('%Y%m%d_%H%M%S')
    out_base=Path(args.output).expanduser() if args.output else root/'WK_R2离线研究结果'
    out=out_base/stamp;out.mkdir(parents=True,exist_ok=False)
    dates=raw_start_date(locate(root,'imu_full_frames','.jsonl'))
    transforms,pvinfo=pv_transforms(rows,root,dates)
    print('PV:',pvinfo['pv_status'],flush=True)
    ranking=[];chosen=None;chosen_models=None;chosen_ranking=None
    for mid in ('M0','M1','M2','M3'):
        params,geostatus=geometry_fit(a_tr,mid)
        # Fit all 28 models for ACC, choose the geometric + thermal pair on *same-temperature* holdout only.
        scores,models,best=candidates_for(rows,'acc',transforms,params)
        family_penalty={'M0':0,'M1':0.008,'M2':0.008,'M3':0.016}[mid]
        # score in g; extra geometry complexity tie break 0.8%/parameter.
        geo_score=best['score']*(1+family_penalty)
        item={'id':mid,'zero_deg':params[0],'axis_elevation_deg':params[1], 'best_acc_thermal_model':best['id'],
              'same_temp_vector_rmse_g':best['same_temp_vector_rmse'],'selection_score':geo_score,'optimization':geostatus}
        ranking.append(item)
        if chosen is None or geo_score<chosen['selection_score']:
            chosen=item;chosen_models=models;chosen_ranking=scores
        print(f'{mid}: δ={params[0]:+.6f}°, ε={params[1]:+.6f}°, ACC同温向量RMSE={best["same_temp_vector_rmse"]*1000:.4f}mg, 模型={best["id"]}',flush=True)
    chosen['selected']=True;geometry=(chosen['zero_deg'],chosen['axis_elevation_deg']);geo=chosen['id']
    accbest=next(x for x in chosen_ranking if x['id']==chosen['best_acc_thermal_model'])
    accmodel=chosen_models[accbest['id']]
    gyroscores,gyromodels,gyrobest=candidates_for(rows,'gyro',transforms,geometry)
    gyromodel=gyromodels[gyrobest['id']]
    print('锁定几何='+geo+'，ACC='+accbest['id']+'，GYRO='+gyrobest['id']+'；开始最终独立温度验证',flush=True)
    metrics={};perpose={}
    for sensor,model,sets in (('acc',accmodel,(a_tr,a_va,a_ho)),('gyro',gyromodel,(g_tr,g_va,g_ho))):
        metrics[sensor]={};items=[]
        for label,data in zip(('训练拟合','同温独立','跨温独立'),sets):
            met,detail=summarize_model(model,data,sensor,geometry,label)
            metrics[sensor][label]=met;items.extend(detail)
        perpose[sensor]=items
        write_csv(out/('ACC逐工况.csv' if sensor=='acc' else 'GYRO逐工况.csv'),items)
    # Original nominal reference baseline, independently re-ranked on same-temp to compare fairly.
    base={}
    for sensor,hold in (('acc',a_ho),('gyro',g_ho)):
        nom_sc,nom_models,nom_best=candidates_for(rows,sensor,transforms,(0.,0.))
        nom_met,_=summarize_model(nom_models[nom_best['id']],hold,sensor,(0.,0.),'跨温独立')
        base[sensor]={'model_id':nom_best['id'],'cross_temp_metrics':nom_met}
    if args.skip_raw:raw={'status':'SKIPPED_BY_USER'}
    else:
        print('开始流式重放逐帧3σ和独立反馈（文件很大时请以本机计算速度为准）',flush=True)
        raw=replay_frames(root,rows,out)
    align=gyro_alignment(accmodel,gyromodel,geometry,a_ho,g_ho)
    if not args.skip_raw:
        print('正在检查逐帧ACC/GYRO运动学一致性（数据允许时）',flush=True)
        alignment_time=dynamic_six_axis_check(root,accmodel,gyromodel,pvinfo,out)
    else:alignment_time={'status':'SKIPPED_BY_USER'}
    align['time_series_kinematics']=alignment_time
    align['dynamic_kinematic_test']=alignment_time['status']
    record={'version':VERSION,'status':'RESEARCH_ONLY_NO_PHYSICAL_TURNTABLE_CERTIFICATION','warning':WARNING,
            'run_time':datetime.now().isoformat(),'device_sn':dev,'source_input_directory':str(root),
            'original_source_files':{'temperature_measurements':measure.name,'experiment_config':conf.name},
            'input_sha256':{measure.name:file_hash(measure),conf.name:file_hash(conf)},
            'counts':{'acc':[len(a_tr),len(a_va),len(a_ho)],'gyro':[len(g_tr),len(g_va),len(g_ho)],'total':len(rows)},
            'train_setpoints':sorted({r['temperature_target_c'] for r in a_tr}),
            'unseen_setpoints':sorted({r['temperature_target_c'] for r in a_ho}),
            'selection_policy':'All geometry+temperature model selection on same-temp independent CONDITIONS; independent TEMPERATURES evaluated only after both winners frozen.',
            'pv_inputs':pvinfo,'pv_mapping_candidates':transforms,
            'geometry_ranking':ranking,'selected_geometry':geo,
            'selected_geometry_equivalent_parameters_deg':{'outer_zero_delta':geometry[0],'outer_axis_elevation_epsilon':geometry[1]},
            'candidate_ranking':{'acc':chosen_ranking,'gyro':gyroscores},
            'selected_models':{'acc':{'id':accbest['id'],'temperature_input':accmodel.get('temperature_input_id')},
                               'gyro':{'id':gyrobest['id'],'temperature_input':gyromodel.get('temperature_input_id')}},
            'nominal_baseline_model_reselected':base,'metrics':metrics,'alignment':align,'raw_replay':raw,
            'claimed_global_optimum':False,'mechanical_turntable_error_certified':False,'six_axis_alignment_independently_certified':False,
            'production_release':False}
    # Numeric coefficients and common frame definition; no firmware install format.
    save_json(out/'最终研究模型参数_不可直接烧录.json',{'warning':WARNING,'geometry_model':geo,'geometry_deg':geometry,
                    'coordinate_frame':'modelled moving platen P, not PCB or product casing',
                    'acc':accmodel,'gyro':gyromodel})
    rankrows=[]
    for sensor,scores in record['candidate_ranking'].items():
        for v in scores:rankrows.append({'sensor':sensor,'geometric_model':geo,**v})
    write_csv(out/'28候选温补模型排名.csv',rankrows)
    write_csv(out/'转台几何候选模型对比.csv',ranking)
    save_json(out/'完整研究总览.json',record);html_output(out,record)
    print(f'完成（仅研究，不可烧录）：{out}\n报告：{out/"离线研究报告.html"}',flush=True)
    return out,record

def main():
    parser=argparse.ArgumentParser(description='WK外轴参考+ACC/GYRO 28结构候选联合温补，研究用途')
    parser.add_argument('folder',help='实验目录，如 E:\\动态倾角仪研发\\溫補測試')
    parser.add_argument('--output',help='指定报告根目录（默认实验文件夹内的新目录）')
    parser.add_argument('--skip-raw',action='store_true',help='跳过大型逐帧文件，仅运行统计数据重拟合')
    opts=parser.parse_args()
    try:run(opts)
    except Exception as exc:
        import traceback
        traceback.print_exc();sys.exit('分析失败（未修改任何输入文件）：'+str(exc))
if __name__=='__main__':main()
