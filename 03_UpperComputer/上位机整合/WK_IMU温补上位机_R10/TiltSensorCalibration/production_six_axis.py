# -*- coding: utf-8 -*-
"""Independent *diagnostic* for synchronized, measured 6-axis dynamic consistency.

Use validation gyro steps only; sample timestamps are from the MCU frame thread.
Insufficient gravity trajectory excitation or missing genuine frames => NOT_EVALUATED.
No machine control, never auto-certifies absolute PCB-axis alignment.
"""
from __future__ import annotations
import json, math
from pathlib import Path
from collections import defaultdict
import numpy as np


def analyze_six_axis_records(pair,models,max_frames=250_000):
    from production_cycle_analysis import forward_matrix
    info={'status':'NOT_EVALUATED','pass':False,'frames_used':0,'residual_rmse_per_s':None,
          'gravity_motion_axes':[],'reason':'缺少足够有时间戳的多轴动态独立验证数据'}
    records=defaultdict(list);scanned=0;selected=0
    for direction,run in pair.items():
        file=Path(run['folder'])/'imu_full_frames.jsonl'
        if not file.is_file():continue
        allowed={str(r['step_id']) for r in run['rows']
                 if r.get('sensor')=='gyro' and r.get('mode')=='rate'
                 and r.get('temperature_split')=='validate' and r.get('split')=='validate'}
        try:
            with file.open('r',encoding='utf-8') as f:
                for line in f:
                    scanned+=1
                    if scanned>2_000_000:
                        info['reason']='原始日志超过200万条读取预算，需拆分批次重新评价';return info
                    try:v=json.loads(line)
                    except (ValueError,TypeError):continue
                    step=str(v.get('step_id',''))
                    if step not in allowed:continue
                    selected+=1
                    if selected>max_frames:
                        info['reason']='独立动态候选帧超过25万条安全预算；需下采样再评价';return info
                    frame=v.get('frame',{})
                    stamp=int(frame.get('monotonic_time_ns',0) or 0)
                    acc=np.asarray(frame.get('acc_g_arr',[]),dtype=float)
                    gyro=np.asarray(frame.get('gyr_dps_arr',[]),dtype=float)
                    if stamp<=0 or acc.ndim!=2 or gyro.ndim!=2 or acc.shape[1:]!=(3,) or gyro.shape[1:]!=(3,):continue
                    if not len(acc) or not len(gyro) or not (np.all(np.isfinite(acc)) and np.all(np.isfinite(gyro))):continue
                    temp=float(frame.get('temp_c',float('nan')))
                    if not math.isfinite(temp):continue
                    raw_a=np.mean(acc,axis=0);raw_g=np.mean(gyro,axis=0)
                    row={'temperature_mean_c':temp,'reference':[0.,0.,1.], '_direction':direction}
                    try:
                        Fa,ba=forward_matrix(models['acc']['model'],row)
                        Fg,bg=forward_matrix(models['gyro']['model'],row)
                        a=np.linalg.solve(Fa,raw_a-ba);g=np.linalg.solve(Fg,raw_g-bg)
                    except (np.linalg.LinAlgError,ValueError):continue
                    if not .7<np.linalg.norm(a)<1.3:continue
                    records[(direction,step)].append((stamp*1e-9,a/np.linalg.norm(a),np.deg2rad(g)))
        except (UnicodeDecodeError,OSError) as exc:
            info['reason']='无法读取动态原始记录：'+str(exc);return info
    derivatives=[];motions=[];axis_sets=set();used=0
    for key,rows in records.items():
        rows.sort(key=lambda r:r[0]);path=np.array([r[1] for r in rows])
        if len(rows)<8 or np.linalg.norm(path[-1]-path[0])<.005:continue
        axis_sets.add(str(key[1]).split('_')[2] if len(str(key[1]).split('_'))>=3 else str(key[1]))
        for i in range(2,len(rows)-2):
            t0,g0,_=rows[i-2];t1,g1,w=rows[i];t2,g2,_=rows[i+2]
            dt=t2-t0
            if not .02<dt<2.5:continue
            speed=np.linalg.norm(w)
            if not np.deg2rad(.5)<speed<np.deg2rad(55):continue
            # Unit gravity derivative, line acceleration is unobservable here.
            residual=(g2-g0)/dt+np.cross(w,g1)
            derivatives.append(float(np.linalg.norm(residual)))
            motions.append(float(np.linalg.norm((g2-g0)/dt)))
            used+=1
    info['frames_used']=used;info['gravity_motion_axes']=sorted(axis_sets)
    if used<80 or len(axis_sets)<2 or np.median(motions)<.003:
        info['reason']='验证帧<80、重力运动轴种类<2或重力变化过小（绕重力方向旋转不可辨识）'
        return info
    residual=float(np.sqrt(np.mean(np.square(derivatives))))
    info.update({'status':'EVALUATED','residual_rmse_per_s':residual,
                'pass':bool(residual<.03),
                'reason':'重力单位向量时间导数与校正角速度叉积的一致性；门槛0.03/s为研发候选，需独立动态复测'})
    return info
