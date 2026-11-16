# -*- coding: utf-8 -*-
"""Pure WK feedback diagnostics with configurable research-only thresholds.

Position timestamps bound host reads, NOT device-precision sample times.
Independent regression and derivative checks are BOTH retained. The configured
limits are experiment-local and must not be interpreted as a metrology certificate.
"""
import math
import numpy as np


def inspect_feedback(samples, axis, target, max_error=0.30, max_std=0.18,
                     max_slope_difference=0.36, max_position_residual_rms=0.35):
    """Validate encoder samples using independent read timestamps.

    max_std is ONLY the raw position-difference velocity dispersion limit;
    mean error, two-half slope difference and position residual are independent
    vetoes, even when the operator increases the dispersion allowance.
    """
    limits=(max_error,max_std,max_slope_difference,max_position_residual_rms)
    if any(not math.isfinite(float(v)) or float(v)<=0 for v in limits):
        raise ValueError('转台测速质量阈值必须全部为有限正数')
    if axis not in ('inner', 'outer'):
        raise ValueError('unknown turntable axis')
    records=[]
    for s in samples:
        a=int(s.get(axis+'_position_read_start_ns') or 0)
        b=int(s.get(axis+'_position_read_end_ns') or 0)
        angle=float(s.get(axis+'_position_deg',float('nan')))
        if not (a>0 and b>=a and math.isfinite(angle)):
            continue
        records.append((0.5*(a+b)*1e-9,angle,(b-a)*1e-9))
    records.sort(key=lambda x:x[0])
    # Only independent encoder polls; never reweight duplicate values per IMU frame.
    unique=[]
    for x in records:
        if not unique or x[0]-unique[-1][0] > 0.001:
            unique.append(x)
    result={'status':'INSUFFICIENT_REFERENCE', 'sample_count':len(unique),
            'target_dps':float(target), 'certified':False,
            'reason':'有效独立位置反馈不足，无法判断匀速'}
    if len(unique)<7:
        return result
    t=np.asarray([x[0] for x in unique],dtype=float)
    dt=np.diff(t)
    if np.any(dt<=0) or np.max(dt)>1.2:
        result['reason']='位置反馈间隔过长或时间戳不递增'
        return result
    raw=np.asarray([x[1] for x in unique],dtype=float)
    increments=(np.diff(raw)+180.0)%360.0-180.0
    # Continuous rotation can move >180deg between polls; refuse ambiguous unwrap.
    if np.any(np.abs(dt*target)>=165.0) or np.any(np.abs(increments)>=175.0):
        result['reason']='角度反馈间隔可能跨越半圈，无法安全展开'
        return result
    theta=np.concatenate(([0.0],np.cumsum(increments)))
    x=t-t[0]
    coeff=np.polyfit(x,theta,1)
    mean=float(coeff[0]); residual=theta-np.polyval(coeff,x)
    # Independent poll-only raw derivative, for diagnosis (not IMU-frame replication).
    raw_diff=increments/dt
    std=float(np.std(raw_diff))
    # Check difference between two temporal slopes; cannot detect unobserved HF jitter.
    middle=len(x)//2
    left=float(np.polyfit(x[:middle+1],theta[:middle+1],1)[0])
    right=float(np.polyfit(x[middle:],theta[middle:],1)[0])
    rms=float(np.sqrt(np.mean(residual**2)))
    max_latency=max(s[2] for s in unique)
    result.update(sample_count=len(unique),duration_s=float(x[-1]),mean_dps=mean,
                  raw_diff_std_dps=std,first_half_dps=left,second_half_dps=right,
                  position_residual_rms_deg=rms,max_read_duration_s=max_latency,
                  applied_limits={'mean_error_dps':float(max_error), 'difference_std_dps':float(max_std),
                                  'half_slope_difference_dps':float(max_slope_difference),
                                  'position_residual_rms_deg':float(max_position_residual_rms)})
    if x[-1]<2.0:
        result['reason']='独立反馈覆盖时长不足2秒'
    elif abs(mean-target)>max_error:
        result['status']='SPEED_ERROR';result['reason']='独立角度回归平均转速偏离目标'
    elif std>max_std:
        result['status']='REFERENCE_JITTER';result['reason']='独立角度反馈差分速度波动超限（可能含测速噪声）'
    elif abs(left-right)>max_slope_difference:
        result['status']='ACCELERATION_DETECTED';result['reason']='前后半段角速度趋势不一致'
    elif rms>max_position_residual_rms:
        result['status']='POSITION_RESIDUAL';result['reason']='独立角度回归的位置残差超限'
    else:
        # Host polls cannot certify high-frequency mechanical speed jitter.
        result['status']='POLLING_PASS_RESEARCH_ONLY'
        result['certified']=True
        result['reason']='通过现有反馈分辨率下的工程质检；不代表独立计量认证'
    return result
