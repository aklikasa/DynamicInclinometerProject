# -*- coding: utf-8 -*-
"""Thermal model comparison without changing the acquisition/safety state machine.

Model selection uses only independent CONDITION rows at FIT temperatures. A
separate TEMPERATURE holdout is consulted exactly once for final acceptance;
its data never changes the winner. All output is research-only.
"""
import json
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
from thermal_compensation import _arr, _eval_poly, _fit_poly, fit_affine
from thermal_temperature_inputs import attach_chamber_pv, fit_pv_equivalent_transform, map_chip_temperature
from thermal_joint_fit import fit_joint_polynomial, ensure_complete_fit_groups

FAMILIES = (
    ('A', '25℃固定参数', 0),
    ('B', '仅零偏温补', 1),
    ('C', '零偏+比例因子温补', 2),
    ('D', '完整3×3矩阵温补', 3),
)
FIELD = {'acc': 'acc_raw_mean_g', 'gyro': 'gyro_raw_mean_dps'}
STATUS_LABELS = {
    'INDEPENDENT_TEMPERATURE_IMPROVEMENT_CONFIRMED_RESEARCH_ONLY': '独立温度验证：误差改善（研发候选，未量产放行）',
    'BASELINE_PREFERRED_NO_TEMPERATURE_COMPENSATION': '模型选型：固定参数更合适，暂不建议温补',
    'HOLDOUT_NOT_IMPROVED_NO_APPROVAL': '独立温度未改善：候选不建议采用',
    'HOLDOUT_INVALID_NO_APPROVAL': '独立温度验证无效：候选不建议采用',
    'NOT_EVALUATED': '数据不足或模型无效：未完成选型',
}


def _metrics(errors, angles=()):
    data = _arr(errors)
    if data.ndim != 1 or not len(data):
        raise ValueError('独立验证数据为空')
    out = {'count': int(len(data)), 'vector_rmse': float(np.sqrt(np.mean(data**2))),
           'vector_max': float(np.max(data))}
    a = np.asarray(angles, dtype=float)
    if a.size:
        out['static_gravity_direction_angle_count'] = int(len(a))
        out['static_gravity_direction_angle_rmse_deg'] = float(np.sqrt(np.mean(a*a)))
        out['static_gravity_direction_angle_max_deg'] = float(np.max(a))
    return out


def _valid_matrix(F):
    if not np.all(np.isfinite(F)) or np.linalg.cond(F) > 100 or abs(np.linalg.det(F)) < 1e-7:
        raise ValueError('温度模型产生病态/奇异矩阵')


def _group_fit(rows, sensor):
    groups = {}
    for r in rows:
        if r.get('sensor') == sensor and r.get('temperature_split') == 'fit' and r.get('split') == 'fit':
            groups.setdefault(float(r['temperature_target_c']), []).append(r)
    if not groups:
        raise ValueError('没有拟合温度数据')
    return dict(sorted(groups.items()))


def _baseline(groups, sensor):
    # Use a REAL measured fit-temperature calibration, not a selected model's
    # polynomial value at 25C. If no 25C fit point, label the nearest explicitly.
    at = min(groups, key=lambda t: (abs(t-25.), t))
    model = fit_affine(groups[at], sensor)
    return at, _arr(model['forward_matrix'], (3,3)), _arr(model['bias'], (3,))


def _per_temperature(groups, sensor, family, F0):
    temps, biases, matrices = [], [], []
    for _target, group in groups.items():
        r = _arr([x['reference'] for x in group])
        y = _arr([x[FIELD[sensor]] for x in group])
        temps.append(float(np.mean([x['temperature_mean_c'] for x in group])))
        if family == 'B':
            F = F0.copy()
            b = np.mean(y-r @ F.T, axis=0)
        elif family == 'C':
            # Constrained refit: fixed off-diagonals, estimate only bias and
            # the three diagonal changes. Avoid full-fit parameter leakage.
            F = F0.copy()
            b = np.empty(3)
            residual = y-r @ F0.T
            for axis in range(3):
                X = np.column_stack((np.ones(len(r)), r[:,axis]))
                if np.linalg.matrix_rank(X) < 2:
                    raise ValueError('某轴参考激励不足，无法估计比例因子')
                v, *_ = np.linalg.lstsq(X, residual[:,axis], rcond=None)
                b[axis] = v[0]
                F[axis,axis] += v[1]
        else:
            result = fit_affine(group, sensor)
            F = _arr(result['forward_matrix'], (3,3))
            b = _arr(result['bias'], (3,))
        _valid_matrix(F)
        biases.append(b)
        matrices.append(F)
    return temps, np.stack(biases), np.stack(matrices)


def _candidate(groups, sensor, family, degree, F0, b0, base_at, transform, joint=False):
    chip_t = [float(np.mean([r['temperature_mean_c'] for r in grp])) for grp in groups.values()]
    all_training_chip=[float(r['temperature_mean_c']) for group in groups.values() for r in group]
    lo, hi = min(all_training_chip), max(all_training_chip)
    input_id = transform['id']
    if family == 'A':
        if input_id != 'T0':
            raise ValueError('固定参数基准A0不使用温度校正')
        bc = np.asarray(b0, dtype=float)[...,None].tolist()
        fc = np.asarray(F0, dtype=float)[...,None].tolist()
        d = 0
    elif joint:
        # One 3x3 F(T) and one b(T) from every complete FIT group together.
        # Temperature is each condition's measured die-temperature mean.
        fc,bc,fit_details=fit_joint_polynomial(groups,sensor,family,degree,F0,b0,transform)
        d=degree
    else:
        # At least one extra temperature beyond the polynomial's interpolation
        # minimum: cubic with four points merely passes through four observations.
        if len(groups) < degree+2:
            raise ValueError(f'{degree}次温补需要至少{degree+2}个拟合温度点以避免纯插值，当前{len(groups)}个')
        temps, bs, fs = _per_temperature(groups, sensor, family, F0)
        temps = [map_chip_temperature(transform,t) for t in temps]
        if len(np.unique(np.round(temps,3))) < degree+1:
            raise ValueError('校正后有效温度点重合')
        bc = _fit_poly(temps, bs, degree)
        if family == 'B':
            fc = np.asarray(F0, dtype=float)[...,None].tolist()
        elif family == 'C':
            fc = np.zeros((3,3,degree+1), dtype=float)
            fc[:,:,0] = F0
            for j in range(3):
                fc[j,j,:] = _arr(_fit_poly(temps, fs[:,j,j], degree))
            fc = fc.tolist()
        else:
            fc = _fit_poly(temps, fs, degree)
        d = degree
    out = {'schema_version': 3, 'sensor': sensor,
           'fit_strategy':('joint_complete_groups_per_condition_chip_T' if joint else
                           'legacy_fit_per_setpoint_then_polynomial'),
           **(fit_details if family!='A' and joint else {}),
           'family': family, 'polynomial_degree': d,
           'id': 'A0' if family == 'A' else f'{input_id}-{family}{d}',
           'model': 'raw = F(T_effective) @ reference + b(T_effective)',
           'temperature_variable': 'measured IMU chip temperature at runtime',
           'temperature_input_id': input_id,
           'temperature_input': transform,
           'temperature_center_c': 25.,
           # This range is intentionally in the RAW CHIP input domain.
           'fit_temperature_range_c': [lo,hi],
           'effective_temperature_range_c': [map_chip_temperature(transform,lo),map_chip_temperature(transform,hi)],
           'fit_temperature_setpoints_c': list(groups),
           'baseline_measured_setpoint_c': base_at,
           'bias_coeff': bc, 'forward_coeff': fc,
           'production_release': False,
           'status': 'RESEARCH_ONLY_NOT_PRODUCTION_APPROVED'}
    for chip in np.linspace(lo,hi,81):
        effective = map_chip_temperature(transform,float(chip))
        _valid_matrix(_eval_poly(fc,effective))
        bcheck=_eval_poly(bc,effective)
        if not np.all(np.isfinite(bcheck)):
            raise ValueError('温度模型产生非有限零偏')
    return out


def _errors(rows, sensor, model):
    errors, angle_errors = [], []
    groups = {}
    for r in rows:
        chip = float(r['temperature_mean_c'])
        low, high = model['fit_temperature_range_c']
        if not np.isfinite(chip) or not low-1e-8 <= chip <= high+1e-8:
            raise ValueError('验证芯片温度不在实际拟合温度范围内（禁止外推）')
        effective = map_chip_temperature(model.get('temperature_input'),chip)
        F = _eval_poly(model['forward_coeff'], effective)
        b = _eval_poly(model['bias_coeff'], effective)
        _valid_matrix(F)
        raw = _arr(r[FIELD[sensor]], (3,))
        ref = _arr(r['reference'], (3,))
        corrected = np.linalg.solve(F,raw-b)
        value = float(np.linalg.norm(corrected-ref))
        errors.append(value)
        k = str(float(r['temperature_target_c']))
        groups.setdefault(k, {'errors':[], 'angles':[]})['errors'].append(value)
        if sensor == 'acc' and r.get('mode') == 'static':
            a = float(np.linalg.norm(corrected))
            b_ref = float(np.linalg.norm(ref))
            if a > 1e-9 and b_ref > 1e-9:
                cosangle = float(np.clip(np.dot(corrected,ref)/(a*b_ref),-1,1))
                angle = float(np.rad2deg(np.arccos(cosangle)))
                angle_errors.append(angle)
                groups[k]['angles'].append(angle)
    summary = _metrics(errors, angle_errors)
    summary['unit'] = 'g' if sensor == 'acc' else 'deg/s'
    summary['per_setpoint'] = {k:_metrics(v['errors'],v['angles']) for k,v in groups.items()}
    return summary


def _errors_inrange_preview(rows, sensor, model):
    """In-range-only research comparison; excluded rows are counted, not hidden.

    Independent validation samples are NEVER used for fitting or choosing their
    temperature limits. The same training-derived domain applies to all 28 models.
    If >10% of a set is outside, refuse to rank rather than silently cherry-pick.
    """
    lo,hi=map(float,model['fit_temperature_range_c'])
    inside=[r for r in rows if lo-1e-8<=float(r['temperature_mean_c'])<=hi+1e-8]
    excluded=len(rows)-len(inside)
    if not inside or len(inside)<0.9*len(rows):
        raise ValueError(f'验证数据超出拟合温区比例过大：{excluded}/{len(rows)}，拒绝评分')
    summary=_errors(inside,sensor,model)
    summary['total_input_count']=len(rows)
    summary['excluded_out_of_range_count']=excluded
    summary['evaluation_policy']='IN_RANGE_RESEARCH_PREVIEW' if excluded else 'FULL_IN_RANGE'
    return summary


def _compare_sensor(rows, sensor, transforms, joint=False):
    groups = _group_fit(rows,sensor)
    if joint:
        ensure_complete_fit_groups(groups,sensor)
    at,F0,b0 = _baseline(groups,sensor)
    condition = [r for r in rows if r.get('sensor')==sensor and r.get('temperature_split')=='fit' and r.get('split')=='validate']
    holdout = [r for r in rows if r.get('sensor')==sensor and r.get('temperature_split')=='validate' and r.get('split')=='validate']
    holdout_set = {float(r['temperature_target_c']) for r in holdout}
    if not condition or not holdout:
        raise ValueError('缺少独立工况验证或独立温度验证')
    if holdout_set.intersection(groups):
        raise ValueError('拟合/验证温度重叠，存在数据泄漏')
    if len(groups) < 3:
        raise ValueError('有效拟合温度点少于3个，无法可靠比较温度模型')
    results, models = [], {}
    candidates = [('A','25℃固定参数',0,'T0')]
    candidates += [(fam,label,d,t) for t in ('T0','T1','T2')
                   for fam,label,_ in FAMILIES[1:] for d in (1,2,3)]
    for family,label,degree,input_id in candidates:
        candidate_id='A0' if family=='A' else f'{input_id}-{family}{degree}'
        record={'id':candidate_id, 'family':family,'name':label,
                'degree':degree,'temperature_input_id':input_id,
                'temperature_input_name':transforms[input_id].get('name',input_id),
                'status':'not_estimated'}
        try:
            if 'error' in transforms[input_id]:
                raise ValueError(transforms[input_id]['error'])
            m=_candidate(groups,sensor,family,degree,F0,b0,at,transforms[input_id],joint=joint)
            select_metrics=_errors_inrange_preview(condition,sensor,m)
            complexity={'A':0,'B':1,'C':2,'D':3}[family]
            input_penalty={'T0':0,'T1':1,'T2':2}[input_id]
            # Complexity regularization is a heuristic tie-break, not an
            # accuracy specification; keep raw RMSE/max visible separately.
            record['selection_score']=float(select_metrics['vector_rmse'] *
                (1.0+0.02*degree+0.025*complexity+0.02*input_penalty))
            record['selection_condition_validation']=select_metrics
            record['status']='candidate_evaluated'
            models[candidate_id]=m
        except (ValueError,TypeError,KeyError,np.linalg.LinAlgError) as e:
            record['reason']=str(e)
        results.append(record)
    available=[r for r in results if r['status']=='candidate_evaluated']
    if not available:
        raise ValueError('全部候选模型均不可计算')
    winner=min(available,key=lambda r:(r['selection_score'], r['degree'],
        {'A':0,'B':1,'C':2,'D':3}[r['family']], {'T0':0,'T1':1,'T2':2}[r['temperature_input_id']]))
    baseline=next(r for r in results if r['id']=='A0')
    # Holdout is evaluated AFTER the winner is frozen; it never changes ranking.
    for r in available:
        try:
            r['independent_temperature_verification']=_errors_inrange_preview(holdout,sensor,models[r['id']])
        except (ValueError,np.linalg.LinAlgError) as e:
            r['independent_temperature_verification']={'status':'invalid', 'reason':str(e)}
    win_hold=winner.get('independent_temperature_verification',{})
    base_hold=baseline.get('independent_temperature_verification',{})
    if 'vector_rmse' not in win_hold or 'vector_rmse' not in base_hold:
        status='HOLDOUT_INVALID_NO_APPROVAL'
    elif winner['family']=='A':
        status='BASELINE_PREFERRED_NO_TEMPERATURE_COMPENSATION'
    elif win_hold['vector_rmse'] <= base_hold['vector_rmse']*(1+1e-9) and win_hold['vector_max'] <= base_hold['vector_max']*(1+1e-9):
        status='INDEPENDENT_TEMPERATURE_IMPROVEMENT_CONFIRMED_RESEARCH_ONLY'
    else:
        status='HOLDOUT_NOT_IMPROVED_NO_APPROVAL'
    exclusions=max((r.get('selection_condition_validation',{}).get('excluded_out_of_range_count',0)
                    for r in available),default=0)
    if exclusions:
        status_text=STATUS_LABELS[status]+f'；选型评分排除{exclusions}条拟合边界外数据（研发预览，不作正式放行）'
    else:
        status_text=STATUS_LABELS[status]
    return {'sensor':sensor,'status':status, 'status_text':status_text, 'selected_id':winner['id'],
            'selection_boundary_exclusions':exclusions,
            'fit_strategy':('joint_complete_groups_per_condition_chip_T' if joint else 'legacy_two_stage'),
            'selected_temperature_input_id':winner['temperature_input_id'],
            'selection_basis':'fit-temperature independent CONDITION rows; held-out TEMPERATURE was NOT used for ranking',
            'selection_score_penalty':'RMSE * (1 + 0.02*degree + 0.025*family_complexity + 0.02*input_complexity)',
            'baseline_definition':f'仅使用拟合温度 {at:g}°C 的实测拟合工况标定参数固定全温区；不是单独常温标定文件',
            'fit_temperature_setpoints_c':list(groups),'final_holdout_setpoints_c':sorted(holdout_set),
            'candidates':results,'selected_model':models[winner['id']],
            'all_candidate_models':models, 'production_release':False,
            'dynamic_tilt_status':'UNAVAILABLE_REQUIRES_TIME_SYNCED_ACC_GYRO_AND_REFERENCE'}


def run_thermal_model_selection(folder,rows,temperature_points,sensors=('acc','gyro'),source_folder=None):
    """Evaluate 28 candidates/sensor; PV mapping uses ONLY FIT condition rows.

    source_folder: the original acquisition directory (different from output
    directory for offline reanalysis). Without PV CSV only T0 models are allowed.
    Every result is research-only; neither calibration files nor MCU are updated.
    """
    root=Path(folder)
    root.mkdir(parents=True,exist_ok=True)
    source=Path(source_folder) if source_folder is not None else root
    # The acquisition config, not mutable UI values, selects the fit semantics.
    # R6 historical experiments keep the old two-stage model for reproducibility.
    config_path=source/'experiment_config.json'
    acquisition_mode='legacy_unspecified'
    if config_path.is_file():
        try:
            acquisition_mode=str(json.loads(config_path.read_text(encoding='utf-8-sig'))
                                 .get('temperature_quality_mode','legacy_unspecified'))
        except (ValueError,TypeError) as ex:
            raise ValueError('采集配置损坏，禁止猜测温度拟合方式：'+str(ex))
    joint=acquisition_mode=='production_adaptive'
    enriched,pv_info=attach_chamber_pv(rows,source)
    transforms={'T0':{'id':'T0','name':'原始芯片温度','kind':'raw_chip','degree':0,
                      'formula':'T_effective = T_chip'}}
    for d in (1,2):
        try:
            transforms[f'T{d}']=fit_pv_equivalent_transform(enriched,d)
        except (ValueError,TypeError,np.linalg.LinAlgError) as exc:
            transforms[f'T{d}']={'id':f'T{d}','name':('PV等效线性校正' if d==1 else 'PV等效二次校正'),
                                   'kind':'unavailable','degree':d,'error':str(exc)}
    result={'schema_version':3,'status':'RESEARCH_ONLY_NOT_PRODUCTION_APPROVED',
            'created_at_utc':datetime.now(timezone.utc).isoformat(),
            'selection_policy':'fit-temp condition validation only; independent-temp final test',
            'temperature_setpoints_c':list(temperature_points),
            'temperature_input_candidates':transforms,
            'fit_strategy':('joint_complete_groups_per_condition_chip_T' if joint else
                             'legacy_two_stage'),
            'group_temperature_span_rejection_enabled':False,
            'pv_telemetry':pv_info,'sensors':{}}
    for sensor in sensors:
        try:
            selection=_compare_sensor(enriched,sensor,transforms,joint=joint)
            models=selection.pop('all_candidate_models')
            chosen=selection.pop('selected_model')
            with (root/f'thermal_{sensor}_model_candidates.json').open('w',encoding='utf-8') as f:
                json.dump(models,f,ensure_ascii=False,indent=2,allow_nan=False)
            with (root/f'thermal_{sensor}_selected_candidate.json').open('w',encoding='utf-8') as f:
                json.dump({**chosen,'selection_status':selection['status'],
                           'selection_basis':selection['selection_basis'],
                           'production_release':False},f,ensure_ascii=False,indent=2,allow_nan=False)
            result['sensors'][sensor]=selection
        except (ValueError,TypeError,KeyError,np.linalg.LinAlgError) as e:
            result['sensors'][sensor]={'status':'NOT_EVALUATED','status_text':STATUS_LABELS['NOT_EVALUATED'],
                                      'reason':str(e),'selected_id':None, 'candidates':[],
                                      'production_release':False}
    with (root/'thermal_model_selection.json').open('w',encoding='utf-8') as f:
        json.dump(result,f,ensure_ascii=False,indent=2,allow_nan=False)
    return result
