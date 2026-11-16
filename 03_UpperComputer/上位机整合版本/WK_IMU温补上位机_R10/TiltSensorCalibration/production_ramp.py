# -*- coding: utf-8 -*-
"""Independent stationary thermal-ramp capture QA; no chamber commands.

Reference is a stationary fixed-body baseline, not external angle metrology.
Ramp samples must be time ordered, include real chip and chamber PV readings,
contain a fresh MCU frame and independent verified WK standstill.  Nothing in
this module opens a PLC or drives a servo.
"""
from __future__ import annotations
import csv
import math
from pathlib import Path
import numpy as np

FIELDS=('unix_s','chip_c','pv_c','acc_x_g','acc_y_g','acc_z_g',
        'gyro_x_dps','gyro_y_dps','gyro_z_dps','frame_count',
        'wk_stopped_confirmed','device_sn','batch_id')


def locate_ramp_file(parent,batch):
    root=Path(parent)
    if not batch:return None
    # Capture filenames carry batch explicitly: no cross-PCB lookup by wildcard.
    candidates=sorted(p for p in root.glob('R5_RAMP_*.csv') if p.is_file())
    valid=[]
    for file in candidates:
        try:
            with file.open('r',encoding='utf-8-sig',newline='') as f:
                first=next(csv.DictReader(f),None)
            if first and first.get('batch_id')==batch:
                valid.append(file)
        except (UnicodeDecodeError,ValueError,OSError):pass
    return valid or None


def load_ramp_rows(paths):
    paths=[paths] if isinstance(paths,(Path,str)) else list(paths)
    samples=[];seen=set();sn=None;batch=None
    for path in paths:
        with Path(path).open('r',encoding='utf-8-sig',newline='') as f:
            reader=csv.DictReader(f)
            if not reader.fieldnames or not set(FIELDS).issubset(reader.fieldnames):
                raise ValueError(f'{path}: 斜坡日志字段不足，缺少实测温度/PV或静止确认')
            for row in reader:
                if str(row['wk_stopped_confirmed']).lower() not in ('true','1','yes'):
                    raise ValueError('斜坡过程中未始终获得WK真实停车确认；本次不能用于静态温漂评价')
                if not row['device_sn'] or not row['batch_id']:
                    raise ValueError('斜坡记录缺少设备编号或批次ID')
                if sn is None:sn=row['device_sn'];batch=row['batch_id']
                if (row['device_sn'],row['batch_id'])!=(sn,batch):
                    raise ValueError('不允许合并不同设备或批次的斜坡数据')
                vals={k:float(row[k]) for k in FIELDS[:9]}
                if not all(math.isfinite(x) for x in vals.values()):
                    raise ValueError('斜坡记录包含非有限温度或IMU读数')
                if not -55<=vals['chip_c']<=110 or not -55<=vals['pv_c']<=110:
                    raise ValueError('温度超出可置信范围')
                key=(str(path),row['frame_count'])
                if key in seen:raise ValueError('同一斜坡文件IMU帧编号重复：禁止复用旧帧')
                seen.add(key)
                vals['file']=str(path);vals['frame_count']=int(row['frame_count'])
                samples.append(vals)
    if len(samples)<100:raise ValueError('温度斜坡记录不足100个新鲜帧')
    samples.sort(key=lambda v:v['unix_s'])
    dt=np.diff([r['unix_s'] for r in samples])
    if np.any(dt<=0) or np.any(dt>30):
        raise ValueError('温度斜坡记录时间不单调或中断超过30秒，不可作为连续斜坡')
    return samples


def classify_ramp(samples):
    """Classify using measured chip temperature slope over about 2 minutes.

    Direction is never inferred from the temperature setpoint or filename.
    """
    times=np.array([r['unix_s'] for r in samples]);temps=np.array([r['chip_c'] for r in samples]);n=len(temps)
    span=max(10,int(120/max(np.median(np.diff(times)),.01)))
    tags=np.zeros(n,dtype=int);slope=np.full(n,np.nan)
    for i in range(n):
        l=max(0,i-span//2);h=min(n,i+span//2+1)
        if h-l<15 or times[h-1]-times[l]<45:continue
        value=(temps[h-1]-temps[l])/(times[h-1]-times[l])*60.
        slope[i]=value
        if 0.10<=value<=2.0:tags[i]=1
        if -2.0<=value<=-0.10:tags[i]=-1
    return tags,slope


def analyze_ramp_file(paths,models):
    from production_cycle_analysis import forward_matrix
    samples=load_ramp_rows(paths)
    tags,slopes=classify_ramp(samples)
    indices={d:np.where(tags==sign)[0] for d,sign in [('warming',1),('cooling',-1)]}
    coverage={d:float(np.ptp(np.array([samples[i]['chip_c'] for i in idx]))) if len(idx)>0 else 0.
              for d,idx in indices.items()}
    base={'source_count':len(samples),'directions':coverage,
          'chip_temperature_min_c':min(r['chip_c'] for r in samples),
          'chip_temperature_max_c':max(r['chip_c'] for r in samples),
          'slope_c_per_min_min':float(np.nanmin(slopes)) if np.any(np.isfinite(slopes)) else None,
          'slope_c_per_min_max':float(np.nanmax(slopes)) if np.any(np.isfinite(slopes)) else None,
          'warning':'静止斜坡验证：ACC方向采用起始重力基准，不能验证产品绝对水平；不参与模型拟合'}
    out={}
    for sensor in ('acc','gyro'):
        result={**base,'status':'NOT_EVALUATED','pass':False,'raw_rmse':None,
                'corrected_rmse':None,'unit':'mg' if sensor=='acc' else '°/s'}
        out[sensor]=result
        if any(len(indices[d])<100 or coverage[d]<10. for d in indices):
            result['reason']='升温或降温未覆盖≥10℃的有效实测芯片斜坡，或有效帧不足100条'
            continue
        model=models[sensor]['model'];lo,hi=model['temperature_domain_c']
        valid=np.flatnonzero(tags!=0)
        if np.any([not (lo<=samples[i]['chip_c']<=hi) for i in valid]):
            result['reason']='斜坡实际芯片温度超出温补训练温区；禁止外推验证'
            continue
        raw_array=[];corrected=[]
        try:
            for i in valid:
                r=samples[int(i)];raw=np.array([r[f'{sensor if sensor=="acc" else "gyro"}_{a}_{"g" if sensor=="acc" else "dps"}'] for a in 'xyz'])
                F,b=forward_matrix(model,{'temperature_mean_c':r['chip_c'],
                             'reference':[0,0,1],'_direction':'warming' if tags[i]==1 else 'cooling'})
                if abs(np.linalg.det(F))<1e-7 or np.linalg.cond(F)>60:raise ValueError('矩阵病态')
                raw_array.append(raw);corrected.append(np.linalg.solve(F,raw-b))
        except (ValueError,np.linalg.LinAlgError) as exc:
            result['reason']='校正失败：'+str(exc);continue
        raw=np.array(raw_array);corr=np.array(corrected)
        if sensor=='acc':
            # vector stability is relative to a fixed mounting orientation.
            baseline=np.mean(corr[:min(30,len(corr))],axis=0)
            baseline=baseline/max(np.linalg.norm(baseline),1e-12)
            vec_err=np.linalg.norm(corr-baseline,axis=1)
            result['raw_rmse']=float(1e3*np.sqrt(np.mean((np.linalg.norm(raw,axis=1)-1)**2)))
            result['corrected_rmse']=float(1e3*np.sqrt(np.mean(vec_err**2)))
            result['corrected_norm_rmse_mg']=float(1e3*np.sqrt(np.mean((np.linalg.norm(corr,axis=1)-1)**2)))
            result['pass']=result['corrected_rmse']<=2. and result['corrected_norm_rmse_mg']<=1.
        else:
            result['raw_rmse']=float(np.sqrt(np.mean(np.sum(raw**2,axis=1))))
            result['corrected_rmse']=float(np.sqrt(np.mean(np.sum(corr**2,axis=1))))
            result['pass']=result['corrected_rmse']<=.02
        result['status']='EVALUATED';result['reason']='静止斜坡两方向已覆盖；PASS仍不能替代角度与动态计量'
        result['evaluated_count']=len(valid)
        result['by_direction']={}
        for d,idx in indices.items():
            sub=[int(np.where(valid==i)[0][0]) for i in idx]
            result['by_direction'][d]={'count':len(sub),'corrected_rmse':float(
               np.sqrt(np.mean(np.sum(corr[sub]**2,axis=1))) if sensor=='gyro' else
               1e3*np.sqrt(np.mean(np.linalg.norm(corr[sub]-baseline,axis=1)**2)))}
    return out
