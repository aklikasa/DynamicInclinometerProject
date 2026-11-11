# -*- coding: utf-8 -*-
"""Two-direction -40..85C six-axis candidate fit, hysteresis & HTML QA.

NO hardware operations; NO MCU coefficient writes; NO metrological claim.
Cannot separate fixture/IMU gauge freedoms from this IMU alone.
Usage: python production_cycle_analysis.py <folder containing warming/cooling runs>
"""
from __future__ import annotations
import argparse, csv, datetime, html, json, math, sys
from pathlib import Path
import numpy as np
from thermal_temperature_inputs import attach_chamber_pv, fit_pv_equivalent_transform, map_chip_temperature
try:
    from wk_r2_engine.wk_joint_offline_R2 import geometry_fit, ref_acc, ref_gyro
except ImportError:
    # Importing scipy is an explicit requirement for joint turntable estimation.
    geometry_fit = ref_acc = ref_gyro = None
from production_cycle_protocol import PROTOCOL, generate_temperature_plan
from production_ramp import analyze_ramp_file, locate_ramp_file
from production_six_axis import analyze_six_axis_records

SENSOR_FIELDS={'acc':'acc_raw_mean_g','gyro':'gyro_raw_mean_dps'}
QUALITY={'acc_vector_rmse_mg':2.,'acc_norm_rmse_mg':1.,'acc_direction_rmse_deg':.10,
         'gyro_vector_rmse_dps':.03,'gyro_zero_rmse_dps':.02,'temperature_group_span_c':.5}
CENTER=22.5
SCALE=62.5

def load_run(path):
    folder=Path(path)
    config=json.loads((folder/'experiment_config.json').read_text('utf-8'))
    data=json.loads((folder/'temperature_measurements.json').read_text('utf-8'))
    direction=config.get('production_scan_direction') or config.get('resume_immutable_config',{}).get('production_scan_direction')
    if direction not in ('warming','cooling'):
        raise ValueError(f'{folder}: 非R4升降温生产扫描，不允许当作循环数据')
    if (config.get('production_protocol') or config.get('resume_immutable_config',{}).get('production_protocol'))!=PROTOCOL:
        raise ValueError(f'{folder}: 实验协议版本不匹配')
    if data.get('status')!='COMPLETED':
        raise ValueError(f'{folder}: 实验状态为{data.get("status")}，不允许混入不完整数据')
    shut=data.get('chamber_shutdown',{})
    if not bool(shut.get('confirmed')) or bool(shut.get('manual_mode')):
        raise ValueError(f'{folder}: 未取得PLC温箱定值停止真实回读，不能作为完整生产方向数据')
    if int(data.get('imu_queue_drops',0) or 0)>0:
        raise ValueError(f'{folder}: IMU逐帧队列发生溢出，不作为完整生产数据')
    plan=generate_temperature_plan(direction)
    actual=[float(t) for t in config.get('temperature_setpoints_c',[])]
    if actual!=plan['temperature_setpoints_c']:
        raise ValueError(f'{folder}: 26个设定温度或方向不完整')
    roles=config.get('temperature_split',{})
    for temp,role in plan['temperature_split'].items():
        if roles.get(str(temp))!=role:
            raise ValueError(f'{folder}: {temp}℃用途不符')
    rows=data.get('rows',[])
    if not rows:raise ValueError(f'{folder}: 无工况数据')
    if any(str(r.get('temperature_split')) not in ('fit','validate') for r in rows):
        raise ValueError(f'{folder}: 工况用途缺失')
    return {'folder':str(folder),'config':config,'data':data,'direction':direction,'rows':rows}

def locate_runs(parent,batch_id=None):
    base=Path(parent)
    if not base.is_dir():raise FileNotFoundError(str(base))
    if batch_id:
        manifest=base/('R5_CYCLE_'+str(batch_id)+'.json')
        if manifest.is_file():
            record=json.loads(manifest.read_text(encoding='utf-8'))
            if record.get('status')!='BOTH_PASSES_COMPLETED':
                raise ValueError('R5一键循环尚未完成两方向；不得合并未完成数据')
            folder_names=record.get('runs',{})
            if set(folder_names)!={'warming','cooling'}:
                raise ValueError('R5一键循环缺少独立的升温/降温文件夹')
            pair={}
            for direction in ('warming','cooling'):
                folder=Path(folder_names[direction]).resolve()
                if folder.parent != base.resolve():
                    raise ValueError('R5循环记录的实验文件夹不在选定的父目录内')
                record_run=load_run(folder)
                if record_run['direction']!=direction:
                    raise ValueError('R5循环记录的方向和原始实验配置不一致')
                cfg=record_run['config']
                if cfg.get('production_batch_id')!=batch_id or cfg.get('device_sn')!=record.get('device_sn'):
                    raise ValueError('R5循环记录的批次或芯片编号与实验配置不一致')
                pair[direction]=record_run
            return pair
    candidates=[]
    for folder in [base]+sorted(p for p in base.iterdir() if p.is_dir()):
        if not ((folder/'experiment_config.json').is_file() and (folder/'temperature_measurements.json').is_file()):continue
        try:r=load_run(folder)
        except (ValueError,KeyError,TypeError):continue
        candidates.append(r)
    by_batch={}
    for r in candidates:
        batch=r['config'].get('production_batch_id') or r['config'].get('resume_immutable_config',{}).get('production_batch_id')
        if not batch:continue
        by_batch.setdefault((r['config'].get('device_sn'),batch),[]).append(r)
    matched=[]
    for key, runs in by_batch.items():
        if len(runs)==2 and {r['direction'] for r in runs}=={'warming','cooling'}:
            matched.append((key,runs))
    if batch_id is not None:
        matched=[item for item in matched if item[0][1]==batch_id]
    if len(matched)!=1:
        raise ValueError('必须有且只有一组同PCB、同批次ID的COMPLETED升温+降温记录；'
                         f'发现{len(matched)}组。请把要比较的两个THERM_文件夹放进一个独立目录。')
    _, pair=matched[0]
    return {r['direction']:r for r in pair}

def select_rows(rows,sensor,partition):
    out=[r for r in rows if r.get('sensor')==sensor and (sensor!='acc' or r.get('mode')=='static')]
    if partition=='train':return [r for r in out if r.get('temperature_split')=='fit' and r.get('split')=='fit']
    if partition=='same_temp':return [r for r in out if r.get('temperature_split')=='fit' and r.get('split')=='validate']
    if partition=='holdout':return [r for r in out if r.get('temperature_split')=='validate' and r.get('split')=='validate']
    raise ValueError(partition)

def chip_model_temperature(r,kind,transforms):
    if kind=='T0':return float(r['temperature_mean_c'])
    transform=transforms.get(kind, {})
    if not transform or transform.get('error'):
        raise ValueError(f'{kind}缺少同实验同步PV数据，未评价')
    return map_chip_temperature(transform,float(r['temperature_mean_c']))

def transformed_features(u,model):
    if model.startswith('SEG'):
        # Truncated-power spline. Every breakpoint has at least C1 continuity;
        # never introduce a step that causes an IMU correction discontinuity.
        knot_c = 25.0 if model.endswith('_25') else 0.0 if model.endswith('_0') else CENTER
        h=max(0.,u-(knot_c-CENTER)/SCALE)
        if model.startswith('SEG3'):
            return np.array([1.,u,u*u,u**3,h*h,h**3])
        return np.array([1.,u,u*u,h*h])
    degree=int(model[-1]) if model!='A0' else 0
    return np.array([u**k for k in range(degree+1)])

def design_rows(rows,sensor,model,phase=False,temperature_input='T0',transforms=None):
    fam='A' if model=='A0' else ('D' if model.startswith('SEG') else model[0]); Xaxes=[[],[],[]]
    for r in rows:
        temp=chip_model_temperature(r,temperature_input,transforms or {})
        if not math.isfinite(temp):raise ValueError('温度映射无效')
        ref=np.array(r['reference'],float)
        if ref.shape!=(3,):raise ValueError('reference must be three axes')
        b=transformed_features((temp-CENTER)/SCALE,model)
        for a in range(3):
            if fam=='A':z=list(ref)+[1.]
            elif fam=='B':z=list(ref)+list(b)
            elif fam=='C':z=[ref[j] for j in range(3) if j!=a]+list(ref[a]*b)+list(b)
            else:z=list(np.outer(b,ref).flatten())+list(b)
            if phase:
                sign=1. if r.get('_direction')=='warming' else -1.
                z+=list(sign*np.array([1.,(temp-CENTER)/SCALE]))
            Xaxes[a].append(z)
    return [np.array(x,float) for x in Xaxes]

def candidate_ids():
    # Same 28 named structures as the original upper computer, with two
    # additional R4 research models (segmented, direction-dependent bias).
    return ['A0']+[f'{t}-{fam}{deg}' for t in ('T0','T1','T2')
                  for fam in 'BCD' for deg in (1,2,3)]+[
                    'T0-SEG2','T0-SEG2_0','T0-SEG2_25',
                    'T0-SEG3_0','T0-SEG3_25','T0-D3_HY']

def model_parts(name):
    if name=='A0':return 'T0','A0'
    kind,base=name.split('-',1)
    return kind,base

def fit_candidate(rows,sensor,model,transforms=None):
    kind,base=model_parts(model)
    phase=base.endswith('_HY');base=base.replace('_HY','')
    xs=design_rows(rows,sensor,base,phase,kind,transforms)
    obs=np.array([r[SENSOR_FIELDS[sensor]] for r in rows],float)
    if len(rows)<=max(x.shape[1] for x in xs)*1.5:raise ValueError('训练样本不足')
    fits=[];rank=[];conds=[]
    for a,X in enumerate(xs):
        rank_a=int(np.linalg.matrix_rank(X));rank.append(rank_a)
        if rank_a<X.shape[1]:raise ValueError(f'设计矩阵秩亏：{model} {sensor} axis{a}')
        cond=float(np.linalg.cond(X));conds.append(cond)
        if cond>5e6:raise ValueError('设计矩阵病态')
        beta,*_=np.linalg.lstsq(X,obs[:,a],rcond=None)
        fits.append(beta.tolist())
    result={'id':model,'sensor':sensor,'coeff':fits,'phase':phase,'input_id':kind,
            'input_transform':(transforms or {}).get(kind,{'id':'T0'}),'columns':list(map(lambda x:x.shape[1],xs)),
            'cond_max':max(conds),'center_c':CENTER,'scale_c':SCALE,
            'temperature_domain_c':[min(float(r['temperature_mean_c']) for r in rows),max(float(r['temperature_mean_c']) for r in rows)],
            'raw_units':'g' if sensor=='acc' else 'deg/s','releasable':False}
    # Dense interpolation-domain check; a high-order polynomial can produce an
    # unphysical/singular matrix BETWEEN observed temperature setpoints.
    lo,hi=result['temperature_domain_c'];probe={**rows[0],'reference':[0.,0.,1.]}
    for tt in np.linspace(lo,hi,101):
        probe['temperature_mean_c']=float(tt)
        for direct in (('warming','cooling') if phase else ('warming',)):
            probe['_direction']=direct
            F,_=forward_matrix(result,probe)
            cond=np.linalg.cond(F)
            if not np.isfinite(cond) or cond>60 or abs(np.linalg.det(F))<1e-7:
                raise ValueError('拟合中途温度的3×3矩阵病态（候选禁止选用）')
    return result

def forward(model,r):
    kind,base=model_parts(model['id']);base=base.replace('_HY','')
    X=design_rows([r],model['sensor'],base,model['phase'],kind,{kind:model['input_transform']})
    return np.array([float((X[a]@np.array(model['coeff'][a]))[0]) for a in range(3)])

def forward_matrix(model,r):
    # Evaluate full local Jacobian of raw vs reference, including model structure
    copy=dict(r); copy['reference']=[0.,0.,0.]
    y0=forward(model,copy);F=np.zeros((3,3))
    for k in range(3):
        copy['reference']=[float(k==a) for a in range(3)]
        F[:,k]=forward(model,copy)-y0
    return F,y0

def evaluate(model,rows,sensor,skip_outside=False):
    metrics=[];missing=[];lo,hi=model['temperature_domain_c']
    for r in rows:
        t=float(r['temperature_mean_c'])
        if not (lo<=t<=hi):
            missing.append(r);continue
        try:
            F,b=forward_matrix(model,r)
            if abs(np.linalg.det(F))<1e-7 or np.linalg.cond(F)>60:raise ValueError('校正矩阵病态')
            corrected=np.linalg.solve(F,np.array(r[SENSOR_FIELDS[sensor]],float)-b)
            ref=np.array(r['reference'],float);vec=corrected-ref
            met={'direction':r['_direction'],'step_id':r.get('step_id'),
                 'setpoint_c':float(r['temperature_target_c']),'chip_c':t,
                 'vector':float(np.linalg.norm(vec)),'corrected':corrected,'ref':ref,
                 'mode':r.get('mode'),
                 'det_forward':float(np.linalg.det(F)),'temp_span':float(r.get('temperature_span_c',math.nan))}
            if sensor=='acc':
                met['norm_mg']=float(1000*(np.linalg.norm(corrected)-1.))
                met['angle_deg']=float(np.rad2deg(np.arccos(np.clip(np.dot(corrected,ref)/(max(1e-15,np.linalg.norm(corrected)*np.linalg.norm(ref))),-1.,1.))))
            metrics.append(met)
        except (ValueError,TypeError,np.linalg.LinAlgError):missing.append(r)
    if not metrics or len(missing)>.1*(len(metrics)+len(missing)):
        raise ValueError('评估缺失超过10%或无有效工况，不可评级')
    rmse=math.sqrt(sum(m['vector']**2 for m in metrics)/len(metrics))
    result={'count':len(metrics),'missing':len(missing),'vector_rmse':rmse,
            'vector_max':max(m['vector'] for m in metrics),
            'det_negative_count':sum(m['det_forward']<0 for m in metrics)}
    if sensor=='gyro':
        zero=[m['vector'] for m in metrics if m['mode']=='static']
        result['zero_vector_rmse_dps']=float(np.sqrt(np.mean(np.square(zero)))) if zero else None
    if sensor=='acc':
        result['vector_rmse_mg']=1000*rmse
        result['norm_rmse_mg']=math.sqrt(sum(m['norm_mg']**2 for m in metrics)/len(metrics))
        result['angle_rmse_deg']=math.sqrt(sum(m['angle_deg']**2 for m in metrics)/len(metrics))
    return result,metrics

def choose_model(data,sensor,transforms,model_policy="single"):
    train=select_rows(data,sensor,'train');val=select_rows(data,sensor,'same_temp');holdout=select_rows(data,sensor,'holdout')
    if not (train and val and holdout):raise ValueError('缺少模型拟合／独立姿态／独立温度分组')
    scores=[];models={}
    for mid in candidate_ids():
        item={'model':mid,'status':'not_evaluated'}
        if model_policy=='single' and mid.endswith('_HY'):
            item['reason']='最终只输出一条芯片温度函数：方向相关候选仅诊断，不参加统一选模'
            scores.append(item)
            continue
        try:
            mdl=fit_candidate(train,sensor,mid,transforms)
            va,_=evaluate(mdl,val,sensor)
            n=sum(mdl['columns']);penalty=1+0.005*n/12.
            item.update(status='evaluated',val_rmse=va['vector_rmse'],complexity_penalty=penalty,
                        selection_score=va['vector_rmse']*penalty)
            models[mid]=mdl
        except (ValueError,np.linalg.LinAlgError) as exc:item['reason']=str(exc)
        scores.append(item)
    eligible=[s for s in scores if s['status']=='evaluated']
    if not eligible:raise ValueError(f'{sensor}：无可用拟合模型')
    winner=min(eligible,key=lambda s:(s['selection_score'],s['model']))
    mdl=models[winner['model']]
    # One-curve model is always judged separately in each temperature direction.
    # Combined RMSE alone is not a sufficient quality gate.
    # Reject exporting extrapolated claim; show exact coverage explicitly
    train_metrics,_=evaluate(mdl,train,sensor)
    val_metrics,_=evaluate(mdl,val,sensor)
    test_metrics,detail=evaluate(mdl,holdout,sensor)
    return {'winner':winner,'scores':scores,'model':mdl,'train':train_metrics,
            'same_temp_validation':val_metrics,'holdout':test_metrics,'details':detail,
            'holdout_used_for_selection':False,'model_release':False}

def hysteresis_table(data,sensor):
    src=[r for r in data if r.get('sensor')==sensor and (sensor!='acc' or r.get('mode')=='static')]
    by_key={}
    for r in src:
        key=(float(r['temperature_target_c']),r.get('step_id'))
        by_key.setdefault(key,{})[r['_direction']]=r
    pairs=[]
    for (setpoint,step_id),rs in sorted(by_key.items()):
        if set(rs)!= {'warming','cooling'}:continue
        w,c=rs['warming'],rs['cooling']
        x,y=np.array(w[SENSOR_FIELDS[sensor]],float),np.array(c[SENSOR_FIELDS[sensor]],float)
        pairs.append({'setpoint_c':setpoint,'step_id':step_id,
                      'chip_delta_c':float(w['temperature_mean_c'])-float(c['temperature_mean_c']),
                      'raw_vector_diff':float(np.linalg.norm(x-y)),'unit':'g' if sensor=='acc' else 'deg/s',
                      'note':'原始两方向差（包含芯片温度差和传感器温漂，非纯迟滞）'})
    return pairs

def normalize_signed_raw(raw, forward, bias, axis):
    """Pure signed-input normalization that mathematically preserves calibrated output.

    This is NOT automatic recovery of the *physical* PCB axes.  Fitted 3x3 models
    are invariant under consistent raw-channel signs; absent external frame
    definition, the data cannot identify which real channel was wired inverted.
    """
    if axis not in (0,1,2):raise ValueError('只有X/Y/Z三个原始通道')
    raw=np.asarray(raw,float);F=np.asarray(forward,float);b=np.asarray(bias,float)
    if raw.shape!=(3,) or F.shape!=(3,3) or b.shape!=(3,):raise ValueError('数组形状不对')
    S=np.eye(3);S[axis,axis]=-1.
    normalized=np.linalg.solve(S@F,S@raw-S@b)
    original=np.linalg.solve(F,raw-b)
    if not np.allclose(normalized,original,atol=1e-12,rtol=1e-12):
        raise AssertionError('代数输入规范化破坏校正输出')
    return {'raw':(S@raw).tolist(),'forward':(S@F).tolist(),'bias':(S@b).tolist(),
            'corrected':normalized.tolist(),'input_sign_matrix':S.tolist(),
            'note':'代数输入通道规范化不改变校正输出；物理X/Y/Z是否反接仍须外部验证'}

def corrected_hysteresis_pairs(data,sensor,mdl):
    by={}
    for r in data:
        if r.get('sensor')!=sensor or (sensor=='acc' and r.get('mode')!='static'):
            continue
        k=(float(r['temperature_target_c']),r.get('step_id'))
        by.setdefault(k,{})[r['_direction']]=r
    errors=[]
    for (t,step),pair in by.items():
        if set(pair)!={'warming','cooling'}:continue
        values=[]
        for direction in ('warming','cooling'):
            row=pair[direction]
            try:
                F,b=forward_matrix(mdl,row)
                x=np.linalg.solve(F,np.array(row[SENSOR_FIELDS[sensor]],float)-b)
                values.append(x)
            except (ValueError,np.linalg.LinAlgError):break
        if len(values)==2:
            errors.append({'setpoint':t,'step_id':step,
                           'corrected_vector_delta':float(np.linalg.norm(values[0]-values[1])),
                           'chip_temperature_difference_c':float(pair['warming']['temperature_mean_c'])-float(pair['cooling']['temperature_mean_c'])})
    if not errors:return {'paired':0,'rms':None,'max':None}
    vals=np.array([item['corrected_vector_delta'] for item in errors])
    return {'paired':len(errors),'rms':float(np.sqrt(np.mean(vals*vals))),
            'max':float(np.max(vals)),'unit':'g' if sensor=='acc' else 'deg/s',
            'warning':'两方向校正结果差包含热历史与未建模误差；不能只看原始差判定热迟滞'}

def axis_channel_diagnostic(acc,gyro):
    items={}
    for name,res in [('acc',acc),('gyro',gyro)]:
        m=res['model'];lo,hi=m['temperature_domain_c'];probe={'temperature_mean_c':(lo+hi)/2,
            'reference':[0.,0.,1.], '_direction':'warming'}
        F,_=forward_matrix(m,probe)
        items[name]={'determinant':float(np.linalg.det(F)), 'condition':float(np.linalg.cond(F)),
                     'reflected_raw_mapping':bool(np.linalg.det(F)<0)}
    disagree=(items['acc']['determinant']*items['gyro']['determinant']<0)
    return {'channels':items,'relative_handedness_conflict':disagree,
            'sign_correction_candidates':'若ACC行列式为负，可在原始X/Y/Z任选一轴做代数符号翻转使行列式转正；数据自身不能判定实际该翻哪根轴。',
            'invariant':'对输入和前向矩阵同时变换S: m_new=S m, F_new=S F，则F_new^-1(m_new-S b)=F^-1(m-b)，输出读数不变。',
            'absolute_six_axis_aligned':False,'release_blocker':'需实机确认PCB右手坐标、静态/动态独立参考及乘积旋转运动学残差。'}

def audit_rows(pair):
    out={'unaccepted':0,'over_span':0,'nonuniform_warning':0,'conditions':0,
         'actual_chip_min_c':1e9,'actual_chip_max_c':-1e9,'by_direction':{}}
    for direct,r in pair.items():
        items=r['rows'];count=0
        for row in items:
            out['conditions']+=1;count+=1
            if int(row.get('accepted_frames',0))<=0:out['unaccepted']+=1
            if float(row.get('temperature_span_c',0))>.5:out['over_span']+=1
            if row.get('group_temperature_nonuniform_warning'):out['nonuniform_warning']+=1
            t=float(row.get('temperature_mean_c',math.nan))
            if math.isfinite(t):
                out['actual_chip_min_c']=min(out['actual_chip_min_c'],t)
                out['actual_chip_max_c']=max(out['actual_chip_max_c'],t)
        out['by_direction'][direct]=count
    out['covers_declared_-40_to_85_c']=(out['actual_chip_min_c']<=-40. and out['actual_chip_max_c']>=85.)
    return out

def to_jsonable(value):
    if isinstance(value,np.ndarray):return value.tolist()
    if isinstance(value,np.generic):return value.item()
    if isinstance(value,dict):return {str(k):to_jsonable(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [to_jsonable(v) for v in value]
    if isinstance(value,float) and not math.isfinite(value):return None
    return value

def report_html(result):
    e=lambda x:html.escape(str(x))
    def minirow(items):return '<tr>'+''.join('<td>'+e(x)+'</td>' for x in items)+'</tr>'
    sels=result['models'];rows=[]
    for s in ('acc','gyro'):
        r=sels[s]
        rows.append(minirow((s.upper(),r['winner']['model'],f"{r['same_temp_validation']['vector_rmse']* (1000 if s=='acc' else 1):.5f}",
                         f"{r['holdout']['vector_rmse']*(1000 if s=='acc' else 1):.5f}",r['holdout']['count'],r['holdout']['missing'])))
    hysteresis=[]
    for s,pairs in result['hysteresis'].items():
        if pairs:
            raw=np.array([p['raw_vector_diff'] for p in pairs]);delta=np.array([abs(p['chip_delta_c']) for p in pairs]);
            hysteresis.append(minirow((s.upper(),len(pairs),f'{np.sqrt(np.mean(raw**2)) * (1000 if s=="acc" else 1):.4f}',f'{max(delta):.4f}',
                          '未剔除温度差影响，不能独立归因热迟滞')))
    def chart_sensor(sensor):
        details=result['models'][sensor].get('details',[])
        groups={}
        for r in details:
            key=(r['direction'],float(r['setpoint_c']))
            groups.setdefault(key,[]).append(float(r['vector'])*(1000 if sensor=='acc' else 1))
        if not groups:return '<p>暂无可绘制的独立温度数据</p>'
        w,h=780,256
        values={d:sorted((t,math.sqrt(sum(x*x for x in vals)/len(vals)))
                    for (dd,t),vals in groups.items() if dd==d)
                for d in ('warming','cooling')}
        high=max([v for rows in values.values() for _,v in rows] or [1.])
        high=max(high*1.15,1e-7)
        tx=lambda t:50+(float(t)+40.)/125.*(w-75)
        ty=lambda v:h-34-float(v)/high*(h-64)
        lines=[f'<svg role="img" aria-label="{sensor.upper()}独立验证温度分方向RMSE" width="100%" viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg">',
               f'<line x1="50" y1="{h-34}" x2="{w-25}" y2="{h-34}" stroke="#9aa8b8"/>',
               '<line x1="50" y1="25" x2="50" y2="222" stroke="#9aa8b8"/>']
        for temp in (-40,-20,0,20,40,60,85):
            x=tx(temp)
            lines.append(f'<text x="{x:.1f}" y="{h-12}" text-anchor="middle" font-size="11" fill="#526578">{temp}℃</text>')
        for direct,color,label in [('warming','#356ca2','升温'),('cooling','#d3893a','降温')]:
            valueset=values[direct]
            points=' '.join(f'{tx(t):.2f},{ty(v):.2f}' for t,v in valueset)
            if points:lines.append(f'<polyline fill="none" stroke="{color}" stroke-width="2.5" points="{points}"/>')
            for t,v in valueset:
                lines.append(f'<circle cx="{tx(t):.2f}" cy="{ty(v):.2f}" r="3" fill="{color}"/>')
            lines.append(f'<text x="{w-150}" y="{37 if direct=="warming" else 57}" fill="{color}" font-size="13">{label}</text>')
        lines.append(f'<text x="5" y="20" font-size="11" fill="#526578">RMSE, {"mg" if sensor=="acc" else "°/s"} (峰值{high:.4g})</text></svg>')
        return ''.join(lines)
    acc_chart=chart_sensor('acc');gyro_chart=chart_sensor('gyro')
    audit=result['quality'];axes=result['axis_diagnostic'];bad=bool(result['release_blockers'])
    htmltext=f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>WK R5 -40～85℃ 统一温补与六轴测试报告</title>
<style>body{{font-family:Arial,'Microsoft YaHei',sans-serif;color:#203042;background:#f5f7fa;max-width:1080px;margin:28px auto;padding:18px;line-height:1.65}}
section{{background:white;border:1px solid #dbe2ed;padding:20px;margin:17px 0;border-radius:8px}}
table{{border-collapse:collapse;width:100%;font-size:14px}}td,th{{border-bottom:1px solid #dfe4ea;padding:9px;text-align:left}}
th{{background:#eaf0f7}}small{{color:#657388}}</style></head><body>
<h1>WK 六轴 IMU R5｜双向统一温补、斜坡及六轴动态测试</h1>
<p>生成时间 {e(result['generated_at'])}　设备 {e(result['device_sn'])}　批次 {e(result['batch_id'])}</p>
<section><h2>报告结论</h2><p><strong>{'当前不可按生产合格放行' if bad else '离线质量门槛初评通过；仍不可当作计量放行'}</strong></p>
<p>本报告使用两次独立扫描（升温、降温）的同块IMU，拟合/同温验证/独立温度严格分组；相同温度不同方向不覆盖。</p>
<p>本次未进行转台独立机械测角认证、六轴产品坐标认证或MCU参数烧录。温度迟滞如超限，应采用验证过的方向状态模型或退回重测，不得不加判断地平均两条曲线。</p>
<h3>阻断项</h3><ul>{''.join('<li>'+e(x)+'</li>' for x in result['release_blockers']) or '<li>无软件质量阻断项；仍需外部计量验证及签署</li>'}</ul></section>
<section><h2>拟合结果（T0芯片实温；候选A0/B/C/D 1～3阶和分段SEG2/方向差模型D3_HY）</h2>
<table><thead><tr><th>传感器</th><th>选中研究候选</th><th>同温验证RMSE</th><th>独立温度RMSE</th><th>独立有效数</th><th>未覆盖</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table><small>ACC单位mg，GYRO单位°/s；同温姿态验证用于选模，独立温度不用于拟合或选模。物理正确性未证实。</small></section>
<section><h2>独立验证趋势（真实结果，未参与模型选型）</h2>
<p>每个验证温度下先按工况求向量误差，再求均方根；升温和降温分开显示。</p>
<h3>ACC | 向量RMSE / mg</h3>{acc_chart}
<h3>GYRO | 向量RMSE / °/s</h3>{gyro_chart}</section>
<section><h2>单曲线 / 分段候选与双向独立验收</h2>
<p>最终策略：{e(result['curve_policy'])}。默认single只允许一套温度自变量函数；方向模型不会替代不合格的统一曲线。</p>
<table><tr><th>传感器</th><th>扫描方向</th><th>独立温度向量RMSE</th><th>单位</th><th>研发门槛</th><th>结果</th></tr>
{''.join(minirow((s,d,round(g['holdout_rmse'],6),'mg' if s=='acc' else '°/s',g['threshold'],'PASS' if g['pass'] else 'FAIL')) for s,ds in result['direction_quality'].items() for d,g in ds.items())}</table>
<p>分段SEG2/SEG3在0℃或25℃处保证至少函数值和一阶导数连续；在未用于选模的独立温度点检验，禁止靠增大次数直接宣称改进。</p></section>
<section><h2>温度斜坡法（独立测试，不参与拟合）</h2>
<p>记录来源：{e(result['ramp_source'] or '无')}。温箱运行需另行配置经设备验证的安全斜坡程序，本软件的斜坡记录器不向PLC发送未知速率控制指令。</p>
<table><tr><th>传感器</th><th>状态</th><th>方向覆盖</th><th>原始误差</th><th>补偿后误差</th><th>备注</th></tr>
{''.join(minirow((s,v['status'],v.get('directions',{}),v.get('raw_rmse'),v.get('corrected_rmse'),v.get('reason',''))) for s,v in result['ramp_validation'].items())}</table>
<p>ACC使用固定姿态的模长和方向稳定性，GYRO使用停车时零速漂移；正反向和芯片实际温度连续轨迹须独立留存。缺数据=未评价。</p></section>
<section><h2>ACC/GYRO同步动态对齐检验</h2>
<p>状态：{e(result['six_axis_dynamic'].get('status'))}；结果：{e(result['six_axis_dynamic'].get('reason',''))}。</p>
<p>总配对帧：{e(result['six_axis_dynamic'].get('frames_used'))}；动力学残差RMS：{e(result['six_axis_dynamic'].get('residual_rmse_per_s'))} 1/s；运动幅值验证：{e(result['six_axis_dynamic'].get('gravity_motion_axes'))}。</p>
<p>验证dg/dt+ω×g=0，需充分的倾角与不同转轴；静态校准RMSE小不等于六轴对齐。即使通过本项，也不能替代PCB绝对轴向计量。</p></section>
<section><h2>两方向原始差异（不能直接当作迟滞）</h2><table><tr><th>通道</th><th>匹配工况对数</th><th>原始差RMS mg/°/s</th><th>最大芯片温差℃</th><th>备注</th></tr>{''.join(hysteresis)}</table></section>
<section><h2>校正后两方向残差对比</h2>
<p>ACC校正后的升温/降温同姿态差RMS：{e(result['hysteresis_corrected']['acc']['rms'])} g；GYRO：{e(result['hysteresis_corrected']['gyro']['rms'])} °/s。</p>
<p>阈值：ACC 2mg、GYRO 0.03°/s；超限时禁止只平均两条标定曲线。</p></section>
<section><h2>质量与温区</h2><p>总工况：{audit['conditions']}；单工况温差超0.5℃：{audit['over_span']}；跨工况温度不均匀告警：{audit['nonuniform_warning']}；缺有效帧：{audit['unaccepted']}。</p>
<p>芯片真实温度覆盖：{audit['actual_chip_min_c']:.3f}℃～{audit['actual_chip_max_c']:.3f}℃；目标产品温区为−40～85℃，温箱设定温度不等于芯片实温。</p></section>
<section><h2>六轴坐标关系</h2><p>ACC前向矩阵行列式：{axes['channels']['acc']['determinant']:.6g}；GYRO：{axes['channels']['gyro']['determinant']:.6g}；符号差异：{axes['relative_handedness_conflict']}。</p>
<p>{e(axes['sign_correction_candidates'])}</p><p>{e(axes['invariant'])}</p>
<p><strong>六轴真实物理对齐：未验收。</strong>不能从静态ACC和独立GYRO小RMSE推出PCB坐标正确。需要同一刚体多轴动态实验，检验dg/dt+ω×g≈0。</p></section>
<section><h2>转台几何与零位（模型对比）</h2>
<p>本次选中：{e(result['geometry']['selected']['name'])}；等效参数δ/ε={e(result['geometry']['selected']['params_deg'])}°。</p>
<table><tr><th>假设</th><th>δ/ε°</th><th>同温姿态RMSE mg</th><th>状态</th></tr>
{''.join(minirow([r['name'],r.get('params_deg','—'),round(r.get('val_vector_rmse_mg',float('nan')),5),r['status']]) for r in result['geometry']['scores'])}</table>
<p>四模型仅训练拟合几何并使用同温独立姿态选型；独立温度不用于几何选型。没有独立基准时无法将δ分解成“机械零位”和“底座初始重力方向”；不自动改厂家转台零位。</p></section>
<section><h2>28种原结构＋分段/热滞后研究模型</h2>
<p>原28候选=A0＋T0/T1/T2×B/C/D×1/2/3；只有同次实验PV匹配充分才评价T1/T2，未匹配不会使用设定温度冒充PV。另比较连续分段二次/三次（0℃、25℃等分界）及T0-D3_HY，后者方向状态依赖，不允许直接无状态烧录。</p>
<p>每工况温度T=芯片实测平均温度，T0直接使用，T1/T2由训练数据拟合PV等效映射；u=(Te−22.5)/62.5；raw=F(Te,方向)·reference+b(Te,方向)。SEG2为连续分段二次；D3_HY在零偏中增加方向常数与线性项。</p><p>实际应用通过 F⁻¹(raw−b) 校正。模型参数见 JSON，<strong>没有放行批准不得当作固件参数。</strong></p></section></body></html>'''
    return htmltext

def attach_pv_transforms(pair,data):
    enriched=[];audit={}
    for direction,run in pair.items():
        part=[r for r in data if r['_direction']==direction]
        enrich,info=attach_chamber_pv(part,run['folder'])
        enriched.extend(enrich)
        audit[direction]=info
    transforms={'T0':{'id':'T0','kind':'raw_chip'}}
    fit_rows=[r for r in enriched if r['temperature_split']=='fit' and r['split']=='fit']
    matched=sum('chamber_pv_mean_c' in r for r in fit_rows)
    if matched<.9*len(fit_rows):
        for kind in ('T1','T2'):
            transforms[kind]={'error':'同实验独立PV工况匹配不足90%，不可替代设定温度'}
    else:
        for degree in (1,2):
            kind='T'+str(degree)
            try:transforms[kind]=fit_pv_equivalent_transform(enriched,degree)
            except ValueError as exc:transforms[kind]={'error':str(exc)}
    return enriched,transforms,audit

def choose_geometry(data):
    # Estimate effective geometry on ACC FIT pose samples only, select by
    # same-temperature independent poses. Independent temperatures are untouched.
    if geometry_fit is None:
        raise RuntimeError('缺少scipy或R2几何计算引擎；不能把M0冒充已联合反演')
    train=select_rows(data,'acc','train');val=select_rows(data,'acc','same_temp')
    scores=[];valid=[]
    for name in ('M0','M1','M2','M3'):
        rec={'name':name,'status':'not_evaluated'}
        try:
            params,diagnostic=geometry_fit(train,name)
            gtr=ref_acc(train,*params);gv=ref_acc(val,*params)
            copytr=[{**r,'reference':v.tolist()} for r,v in zip(train,gtr)]
            copyva=[{**r,'reference':v.tolist()} for r,v in zip(val,gv)]
            m=fit_candidate(copytr,'acc','T0-D2',{'T0':{'id':'T0'}})
            metrics,_=evaluate(m,copyva,'acc')
            complexity={'M0':0,'M1':1,'M2':1,'M3':2}[name]
            rec.update(status='evaluated',params_deg=list(params),val_vector_rmse_mg=metrics['vector_rmse_mg'],
                       selection_score=metrics['vector_rmse_mg']*(1+0.03*complexity),diagnostic=diagnostic)
            valid.append(rec)
        except (ValueError,TypeError,np.linalg.LinAlgError) as exc:rec['reason']=str(exc)
        scores.append(rec)
    if not valid:raise ValueError('四种几何假设都不可评价')
    winner=min(valid,key=lambda x:(x['selection_score'],x['name']))
    return {'selected':winner,'scores':scores,
            'warning':'几何参数只能称为等效参考，不能独立认证为转台机械计量误差'}

def apply_geometry(data,params):
    out=[]
    for sensor in ('acc','gyro'):
        rows=[r for r in data if r.get('sensor')==sensor]
        refs=ref_acc(rows,*params) if sensor=='acc' else ref_gyro(rows,params[1])
        out.extend([{**r,'reference':v.tolist()} for r,v in zip(rows,refs)])
    return out

def analyze(base,output=None,model_policy='single',batch_id=None):
    pair=locate_runs(base,batch_id=batch_id)
    w,c=pair['warming'],pair['cooling'];wc,wf=w['config'],c['config']
    if wc['device_sn']!=wf['device_sn']:raise ValueError('两方向PCB号不同')
    sw=wc.get('imu_sensor_config');sc=wf.get('imu_sensor_config')
    if sw!=sc:raise ValueError('两方向IMU量程/ODR配置不同，禁止拼接')
    data=[]
    for direction,run in pair.items():
        data.extend([{**r,'_direction':direction} for r in run['rows']])
    audit=audit_rows(pair)
    geometry=choose_geometry(data)
    data=apply_geometry(data,geometry['selected']['params_deg'])
    data,transforms,pv_audit=attach_pv_transforms(pair,data)
    models={s:choose_model(data,s,transforms,model_policy) for s in ('acc','gyro')}
    directions={s:{d:{k:evaluate(models[s]['model'],select_rows([r for r in data if r['_direction']==d],s,k),s)[0] for k in ('train','same_temp','holdout')}
                    for d in ('warming','cooling')} for s in ('acc','gyro')}
    hysteresis={s:hysteresis_table(data,s) for s in ('acc','gyro')}
    hysteresis_corrected={s:corrected_hysteresis_pairs(data,s,models[s]['model']) for s in ('acc','gyro')}
    axes=axis_channel_diagnostic(models['acc'],models['gyro'])
    # Independent, never used for fitting or candidate selection.
    ramp_path=locate_ramp_file(base, w['config'].get('production_batch_id',''))
    ramp={s:{'status':'NOT_EVALUATED','reason':'未提供独立、转台静止的连续温度斜坡记录'} for s in ('acc','gyro')}
    if ramp_path is not None:
        try:
            ramp=analyze_ramp_file(ramp_path,models)
        except (ValueError,OSError,KeyError) as exc:
            ramp={s:{'status':'NOT_EVALUATED','reason':str(exc)} for s in ('acc','gyro')}
    six_axis=analyze_six_axis_records(pair,models)
    # Production evaluation is multi-objective: report worst independent direction,
    # not only the aggregate holdout averaged over both directions.
    direction_quality={}
    for sensor in ('acc','gyro'):
        key='vector_rmse_mg' if sensor=='acc' else 'vector_rmse'
        threshold=QUALITY['acc_vector_rmse_mg'] if sensor=='acc' else QUALITY['gyro_vector_rmse_dps']
        direction_quality[sensor]={direct:{'holdout_rmse':float(directions[sensor][direct]['holdout'][key]),
                                     'threshold':threshold,
                                     'pass':float(directions[sensor][direct]['holdout'][key])<=threshold}
                                   for direct in ('warming','cooling')}

    block=[]
    if not audit['covers_declared_-40_to_85_c']:block.append('芯片真实温区未完整覆盖−40～85℃，禁止按全温区放行')
    if audit['over_span']:block.append(f'单工况芯片温差超过0.5℃：{audit["over_span"]}条')
    if audit['nonuniform_warning']:block.append(f'存在跨姿态温度不一致告警：{audit["nonuniform_warning"]}条')
    if axes['relative_handedness_conflict']:block.append('ACC/GYRO原始轴系行列式符号不同，需独立轴符号/PCB坐标复核')
    if not all(x['pass'] for x in direction_quality['acc'].values()):block.append('ACC统一温补曲线未同时满足升温、降温独立温度门槛')
    if not all(x['pass'] for x in direction_quality['gyro'].values()):block.append('GYRO统一温补曲线未同时满足升温、降温独立温度门槛')
    if models['acc']['holdout']['vector_rmse_mg']>QUALITY['acc_vector_rmse_mg']:block.append('ACC独立温度向量RMSE超研发门槛')
    if models['acc']['holdout']['norm_rmse_mg']>QUALITY['acc_norm_rmse_mg']:block.append('ACC独立温度模长RMSE超研发门槛')
    if models['acc']['holdout']['angle_rmse_deg']>QUALITY['acc_direction_rmse_deg']:block.append('ACC独立温度方向角RMSE超研发门槛')
    if models['gyro']['holdout']['vector_rmse']>QUALITY['gyro_vector_rmse_dps']:block.append('GYRO独立温度向量RMSE超研发门槛')
    gyro_zero=models['gyro']['holdout'].get('zero_vector_rmse_dps')
    if gyro_zero is None: block.append('独立温度缺少GYRO静态零速验证')
    elif gyro_zero>QUALITY['gyro_zero_rmse_dps']:block.append('GYRO独立温度静态零速RMSE超研发门槛')
    if any(models[s]['model']['phase'] for s in ('acc','gyro')):block.append('最佳模型依赖升降温方向，需定义运行时状态判定/热历史，不允许直接烧录')
    if hysteresis_corrected['acc']['rms'] is not None and hysteresis_corrected['acc']['rms']>.002:
        block.append('同姿态升降温校正ACC差异RMS>2mg；不能强行合并单曲线')
    if hysteresis_corrected['gyro']['rms'] is not None and hysteresis_corrected['gyro']['rms']>.03:
        block.append('同工况升降温校正GYRO差异RMS>0.03°/s；不能强行合并单曲线')
    for sensor in ('acc','gyro'):
        if ramp[sensor]['status']!='EVALUATED':
            block.append(sensor.upper()+'没有足够独立温度斜坡数据，不能评定热动态补偿')
        elif not ramp[sensor]['pass']:
            block.append(sensor.upper()+'温度斜坡验证超限')
    if six_axis['status']!='EVALUATED' or not six_axis.get('pass'):
        block.append('ACC/GYRO同步动态运动学测试未达到验证条件或未通过')
    block.append('缺少独立转台测角与PCB绝对坐标实机验收；软件报告仅供研究')
    result={'generated_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'device_sn':wc['device_sn'],'batch_id':wc['production_batch_id'],
            'run_folders':{d:pair[d]['folder'] for d in ('warming','cooling')},
            'quality':audit,'axis_diagnostic':axes,'release_blockers':block,
            'temperature_model':'T0 measured actual chip condition mean',
            'models':models,'directions':directions,'hysteresis':hysteresis,
            'hysteresis_corrected':hysteresis_corrected,
            'curve_policy':model_policy,
            'direction_quality':direction_quality,
            'ramp_validation':ramp,
            'ramp_source':str(ramp_path) if ramp_path else None,
            'six_axis_dynamic':six_axis,
            'geometry':geometry,'pv_transforms':transforms,'pv_audit':pv_audit,
            'status':'RESEARCH_ONLY_NO_PRODUCTION_RELEASE'}
    dest=Path(output) if output else Path(base)/('WK_R5双向温补研究结果_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S'))
    dest.mkdir(parents=True,exist_ok=False)
    (dest/'双向温补质量分析报告.html').write_text(report_html(result),encoding='utf-8')
    (dest/'全量研究结果_不得直接烧录.json').write_text(json.dumps(to_jsonable(result),ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    (dest/'统一温补研究参数_未经生产批准.json').write_text(json.dumps(to_jsonable({
        'scope':'Research coefficients, never automatically loaded to MCU',
        'temperature_input':'measured chip temperature, per condition',
        'curve_policy':model_policy,
        'acc':models['acc']['model'],'gyro':models['gyro']['model'],
        'formula':'corrected=solve(F(chip_temperature),raw-b(chip_temperature))',
        'coordinate_frame':'assumed WK tool frame, physical PCB frame unverified',
    }),ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    (dest/'原始六轴符号校验说明.json').write_text(json.dumps(to_jsonable(axes),ensure_ascii=False,indent=2),encoding='utf-8')
    with (dest/'模型评分.csv').open('w',encoding='utf-8-sig',newline='') as f:
        wr=csv.DictWriter(f,fieldnames=['sensor','model','status','val_rmse','selection_score','reason']);wr.writeheader()
        for s in ('acc','gyro'):
            for row in models[s]['scores']:wr.writerow({key:(s if key=='sensor' else row.get(key,'')) for key in wr.fieldnames})
    with (dest/'升降温原始差异.csv').open('w',encoding='utf-8-sig',newline='') as f:
        cols=['sensor','setpoint_c','step_id','chip_delta_c','raw_vector_diff','unit','note'];wr=csv.DictWriter(f,fieldnames=cols);wr.writeheader()
        for s in ('acc','gyro'):
            for p in hysteresis[s]:wr.writerow({'sensor':s,**p})
    with (dest/'升降温独立验证.csv').open('w',encoding='utf-8-sig',newline='') as f:
        cols=['sensor','direction','independent_count','independent_missing','vector_rmse','threshold','pass'];wr=csv.DictWriter(f,fieldnames=cols);wr.writeheader()
        for sensor in ('acc','gyro'):
            for direction in ('warming','cooling'):
                metric=directions[sensor][direction]['holdout']
                gate=direction_quality[sensor][direction]
                wr.writerow({'sensor':sensor,'direction':direction,'independent_count':metric['count'],
                    'independent_missing':metric['missing'],'vector_rmse':gate['holdout_rmse'],
                    'threshold':gate['threshold'],'pass':gate['pass']})
    return dest,result

def main():
    parser=argparse.ArgumentParser(description='WK R5 -40..85℃ 双向温补合并与六轴坐标风险报告（无硬件动作）')
    parser.add_argument('folder',help='包含本批次升温/降温两个THERM_目录的父文件夹')
    parser.add_argument('--output',default=None)
    parser.add_argument('--batch-id',default=None,help='只分析指定生产批次；其他批次不参与')
    parser.add_argument('--model-policy',choices=['single','research_directional'],default='single',
                        help='single: only one temperature function; research_directional: allow nondeployable directional diagnosis')
    args=parser.parse_args()
    dest,result=analyze(args.folder,args.output,args.model_policy,args.batch_id)
    print('双向温补报告已生成:',dest/'双向温补质量分析报告.html')
    print('研究结果：',result['models']['acc']['winner']['model'],result['models']['gyro']['winner']['model'])
    print('放行状态: 研究用途，禁止自动生产放行')

if __name__=='__main__':main()
