# -*- coding: utf-8 -*-
"""PV is a laboratory reference only. The deployed model uses IMU chip temperature.

The immutable per-frame CSV already stores synchronized chamber_pv_c and imu_temp_c.
For legacy experiments, attach PV by (setpoint, step_id); never replace missing PV
with the commanded chamber setpoint. A PV-equivalent transform is NOT a die-temperature
calibration and must never be interpreted as an absolute chip junction temperature.
"""
import csv
from collections import defaultdict
from pathlib import Path
import numpy as np


def attach_chamber_pv(rows, source_folder):
    """Return enriched copies, diagnostic counts; never mutate acquisition rows."""
    enriched = [dict(r) for r in rows]
    file = Path(source_folder) / 'imu_frame_means.csv'
    if not file.is_file():
        return enriched, {'status': 'PV_RAW_CSV_MISSING', 'path': str(file), 'matched': 0}
    samples = defaultdict(list)
    invalid = 0
    with file.open('r', encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or not {'target_temp_c','step','chamber_pv_c','imu_temp_c'}.issubset(set(reader.fieldnames)):
            return enriched, {'status':'PV_COLUMNS_MISSING', 'path':str(file), 'matched':0}
        for r in reader:
            try:
                target = float(r['target_temp_c'])
                pv = float(r['chamber_pv_c'])
                chip = float(r['imu_temp_c'])
                if not np.all(np.isfinite((target,pv,chip))) or abs(pv - target)>15.0:
                    invalid+=1
                    continue
                samples[(target, r['step'])].append((chip,pv))
            except (KeyError, ValueError, TypeError):
                invalid+=1
    matched=0
    for r in enriched:
        key=(float(r['temperature_target_c']),r['step_id'])
        group=samples.get(key)
        # The CSV can contain rejected attempts of a step. Only the final
        # successful attempt (frame_count) corresponds to the committed row.
        if group:
            expected_frames=int(r.get('frame_count') or 0)
            if expected_frames>0:
                if len(group)<expected_frames:
                    continue
                group=group[-expected_frames:]
            vals=np.asarray(group, dtype=float)
            # Avoid associating unrelated/replayed files by checking chip means.
            if abs(float(np.median(vals[:,0])) - float(r['temperature_mean_c'])) > 2.0:
                continue
            r['chamber_pv_mean_c']=float(np.median(vals[:,1]))
            r['chamber_pv_range_c']=float(np.ptp(vals[:,1]))
            r['chamber_pv_sample_count']=len(group)
            matched+=1
    return enriched, {'status':'PV_MATCHED' if matched else 'NO_MATCHING_PV',
                     'path':str(file), 'matched':matched,'rows':len(rows),
                     'invalid_raw_frames':invalid}


def fit_pv_equivalent_transform(rows, degree):
    """Fit chamber PV vs IMU chip at FIT temperatures using FIT conditions ONLY.

    Every temperature has equal weight so the number of rate steps cannot dominate.
    Held-out temperatures and held-out conditions must not enter this fit.
    """
    if degree not in (1,2):
        raise ValueError('只支持线性/二次PV等效温度校正')
    groups=defaultdict(list)
    for r in rows:
        if r.get('temperature_split')!='fit' or r.get('split')!='fit':
            continue
        if 'chamber_pv_mean_c' not in r:
            continue
        x=float(r['temperature_mean_c'])
        y=float(r['chamber_pv_mean_c'])
        if not np.all(np.isfinite((x,y))):
            continue
        groups[float(r['temperature_target_c'])].append((x,y))
    min_points = 3 if degree==1 else 4
    if len(groups)<min_points:
        raise ValueError(f'PV校正需要至少{min_points}个带实测PV的拟合温度点，当前{len(groups)}个')
    pairs=np.asarray([np.median(group,axis=0) for _,group in sorted(groups.items())],float)
    chip,pv=pairs[:,0],pairs[:,1]
    if np.ptp(chip)<10 or len(set(np.round(chip,3)))!=len(chip):
        raise ValueError('芯片温度跨度不足或温度点重复')
    u=(chip-25.)/50.
    X=np.polynomial.polynomial.polyvander(u,degree)
    if np.linalg.cond(X)>1e5:
        raise ValueError('PV校正多项式矩阵病态')
    coeff,*_=np.linalg.lstsq(X,pv-25.,rcond=None)
    # Range includes raw chip readings of all FIT-condition steps, not just
    # setpoint medians; normal intra-setpoint drift must not be misclassified.
    all_training_chip=[float(r['temperature_mean_c']) for r in rows
       if r.get('temperature_split')=='fit' and r.get('split')=='fit'
       and 'chamber_pv_mean_c' in r]
    raw_min=min(all_training_chip)
    raw_max=max(all_training_chip)
    grid=np.linspace(raw_min,raw_max,101)
    g=(grid-25.)/50.
    out=25.+np.polynomial.polynomial.polyval(g,coeff)
    # Need a physically sensible, monotonic PV equivalence, not a mathematical trick.
    derivative=np.polynomial.polynomial.polyval(g, np.polynomial.polynomial.polyder(coeff))/50.
    if (np.min(derivative)<0.15 or np.max(derivative)>3.0 or
        np.max(np.abs(out-grid))>15.0 or not np.all(np.isfinite(out))):
        raise ValueError('PV校正不单调或偏差过大，拒绝将其用作模型自变量')
    pred=25.+X@coeff
    return {'id':f'T{degree}', 'name':'PV等效线性校正' if degree==1 else 'PV等效二次校正',
            'kind':'pv_equivalent_chip_transform','degree':degree,
            'temperature_center_c':25.0,'temperature_scale_c':50.0,
            'coefficients_c':coeff.tolist(),
            'formula':'T_equiv = 25 + sum(c[k] * ((T_chip - 25)/50)^k)',
            'chip_temperature_fit_range_c':[float(raw_min),float(raw_max)],
            'pv_fit_rmse_c':float(np.sqrt(np.mean((pred-pv)**2))),
            'fit_training_pairs':[{'setpoint_c':float(t),'chip_temperature_c':float(x),'pv_temperature_c':float(y)}
                                  for (t,_),(x,y) in zip(sorted(groups.items()),pairs)],
            'production_release':False,
            'warning':'PV等效温度，不代表IMU芯片结温绝对真值；仅限训练温度内使用。'}


def map_chip_temperature(transform, chip_c):
    chip=float(chip_c)
    if not np.isfinite(chip):
        raise ValueError('芯片温度无效')
    if transform is None or transform.get('id')=='T0':
        return chip
    lo,hi=transform['chip_temperature_fit_range_c']
    if chip<lo-1e-8 or chip>hi+1e-8:
        raise ValueError('芯片温度超出PV校正拟合范围')
    u=(chip-transform['temperature_center_c'])/transform['temperature_scale_c']
    result=25.+np.polynomial.polynomial.polyval(u,transform['coefficients_c'])
    if not np.isfinite(result):
        raise ValueError('校正温度非有限值')
    return float(result)
