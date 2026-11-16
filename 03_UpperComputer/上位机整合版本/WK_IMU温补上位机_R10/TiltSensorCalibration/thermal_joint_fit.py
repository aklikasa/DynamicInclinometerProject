# -*- coding: utf-8 -*-
"""R7 production thermal fit: ONE matrix F(T) and bias b(T) from ALL complete
fit-condition groups, each row using its OWN measured chip-temperature mean.

12 ACC positions at a setpoint remain a complete, indivisible experimental
design. Do not fit 12 independent calibrations and do not reject an accepted
group because its position-to-position die temperature changes by 2 C.
No arbitrary group-temperature-span thresholds; only algebraic rank and the
existing model matrix-health checks are enforced.
"""
import numpy as np
from thermal_temperature_inputs import map_chip_temperature

MEASURED={'acc':'acc_raw_mean_g','gyro':'gyro_raw_mean_dps'}


def ensure_complete_fit_groups(groups, sensor):
    if sensor not in MEASURED or not groups:
        raise ValueError('联合拟合没有完整的传感器拟合姿态')
    ids={}
    for target, rows in groups.items():
        stepids=[str(row['step_id']) for row in rows]
        if not stepids or len(stepids)!=len(set(stepids)):
            raise ValueError(f'{target:g}℃拟合工况ID缺失或重复，拒绝联合拟合')
        ids[target]=set(stepids)
    expected=set(next(iter(ids.values())))
    if sensor=='acc' and len(expected)!=12:
        raise ValueError(f'ACC每个拟合温度应有完整12姿态，当前{len(expected)}项；不会把姿态拆开独立拟合')
    for target, current in ids.items():
        if current != expected:
            raise ValueError(f'{target:g}℃拟合姿态不完整：缺少{sorted(expected-current)}；额外{sorted(current-expected)}')
    return len(expected)


def fit_joint_polynomial(groups, sensor, family, degree, F0, b0, transform):
    """Fit measured raw=F(Te)@ref+b(Te); coeffs in (Te-25)^k basis.

    family B: b only, F0 fixed.
    family C: b + diagonal F, F0 off-diagonals fixed.
    family D: all 9 F elements + 3 b, jointly fitted.
    Each training row contributes its own chip T; NO group-mean T is substituted.
    """
    count=ensure_complete_fit_groups(groups,sensor)
    if family not in ('B','C','D') or degree not in (1,2,3):
        raise ValueError('联合拟合族或温度多项式阶数不支持')
    if len(groups)<degree+2:
        raise ValueError(f'{degree}次联合温补至少需要{degree+2}个完整拟合温度组')
    rows=[row for group in groups.values() for row in group]
    refs=np.array([r['reference'] for r in rows],dtype=float)
    raw=np.array([r[MEASURED[sensor]] for r in rows],dtype=float)
    actual_t=np.array([float(r['temperature_mean_c']) for r in rows],dtype=float)
    eff=np.array([float(map_chip_temperature(transform,float(t))) for t in actual_t])
    if refs.shape!=raw.shape or refs.shape!=(len(rows),3) or not np.isfinite(raw).all() or not np.isfinite(eff).all():
        raise ValueError('拟合记录缺少有效的三轴或芯片均温')
    # Center and scale polynomial for stable least squares. Convert back below
    # to the original production model's (Te-25)^k convention.
    u=(eff-25.0)/50.0
    V=np.column_stack([u**k for k in range(degree+1)])
    F=np.zeros((3,3,degree+1),dtype=float)
    B=np.zeros((3,degree+1),dtype=float)
    F[:,:,0]=np.asarray(F0,dtype=float)
    for j in range(3):
        if family=='B':
            X=V
            y=raw[:,j]-refs@F0[j,:]
        elif family=='C':
            X=np.column_stack([*(refs[:,j]*V[:,k] for k in range(degree+1)),
                              *(V[:,k] for k in range(degree+1))])
            y=raw[:,j]-sum(F0[j,other]*refs[:,other] for other in range(3) if other!=j)
        else:
            X=np.column_stack([base*V[:,k] for k in range(degree+1)
                              for base in (refs[:,0],refs[:,1],refs[:,2],np.ones(len(rows)))])
            y=raw[:,j]
        rank=np.linalg.matrix_rank(X)
        if rank!=X.shape[1]:
            raise ValueError(f'温度与姿态数据不可辨识：轴{j}联合矩阵秩{rank}/{X.shape[1]}，请补采重叠/交错姿态')
        co,*_=np.linalg.lstsq(X,y,rcond=None)
        if family=='B':
            B[j,:]=[co[k]/50.0**k for k in range(degree+1)]
        elif family=='C':
            F[j,j,:]=[co[k]/50.0**k for k in range(degree+1)]
            B[j,:]=[co[degree+1+k]/50.0**k for k in range(degree+1)]
        else:
            for k in range(degree+1):
                F[j,:,k]=co[4*k:4*k+3]/50.0**k
                B[j,k]=co[4*k+3]/50.0**k
    if not np.isfinite(F).all() or not np.isfinite(B).all():
        raise ValueError('联合温补多项式系数不是有限数')
    return (F.tolist(),B.tolist(),{
        'fit_method':'R7_COMPLETE_GROUP_JOINT_PER_CONDITION_CHIP_T',
        'fit_conditions_per_setpoint':count,
        'fit_group_count':len(groups),
        'fit_condition_count':len(rows),
        'temperature_independent_variable':'condition_mean_of_valid_IMU_chip_temperature_frames',
        'fit_group_temperature_span_is_not_a_rejection_gate':True,
        'description':'同一温度完整12姿态共同参与一套F(T)/b(T)求解；各姿态实测芯片均温作为各自自变量'})
