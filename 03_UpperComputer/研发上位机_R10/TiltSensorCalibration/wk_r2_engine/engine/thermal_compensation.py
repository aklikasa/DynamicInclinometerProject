# -*- coding: utf-8 -*-
"""IMU thermal calibration fitting/validation. Pure numpy; no device or UI dependencies.

Reference frame is the fixture coordinate frame; temperature is the sensor's own
measured die temperature, not the chamber setpoint. Temperature models are
intentionally NOT production-released without an independent holdout pass.
"""
import json
from datetime import datetime, timezone
import numpy as np


def _arr(x, shape=None):
    a = np.asarray(x, dtype=float)
    if (shape is not None and a.shape != shape) or not np.all(np.isfinite(a)):
        raise ValueError('数据维度错误或出现 NaN/Inf')
    return a


def fit_affine(rows, sensor):
    """Fit raw = F @ reference + b; correction C = inv(F).

    Needs 4 non-coplanar reference directions (the production plan uses 12/19).
    """
    name = 'acc_raw_mean_g' if sensor == 'acc' else 'gyro_raw_mean_dps'
    refs = _arr([r['reference'] for r in rows])
    meas = _arr([r[name] for r in rows])
    if refs.ndim != 2 or refs.shape[1] != 3 or meas.shape != refs.shape or len(refs) < 6:
        raise ValueError('每个拟合温度点的标定工况不足')
    X = np.column_stack((refs, np.ones(len(refs))))
    if np.linalg.matrix_rank(X) != 4 or np.linalg.cond(X) > 1500:
        raise ValueError('转台参考姿态/速率覆盖不足，不能拟合完整 3×3 矩阵')
    B, *_ = np.linalg.lstsq(X, meas, rcond=None)
    F = B[:3, :].T
    if np.linalg.cond(F) > 100 or abs(np.linalg.det(F)) < 1e-7:
        raise ValueError('拟合出的传感器矩阵病态/奇异，拒绝保存可用补偿')
    return {'bias': B[3, :].tolist(), 'forward_matrix': F.tolist(),
            'correction_matrix': np.linalg.inv(F).tolist(),
            'fit_vector_rmse': float(np.sqrt(np.mean(np.sum((X @ B - meas)**2, axis=1))))}


def _fit_poly(xs, ys, degree):
    x = _arr(xs)
    y = _arr(ys)
    if len(x) < degree + 1 or np.ptp(x) < 5 or len(np.unique(np.round(x, 3))) < degree + 1:
        raise ValueError('温度拟合点不足或没有实际温度跨度')
    design = np.vander(x - 25., degree + 1, increasing=True)
    if np.linalg.cond(design) > 1.e7:
        raise ValueError('温度采样点病态，温度模型不可靠')
    c, *_ = np.linalg.lstsq(design, y.reshape(len(x), -1), rcond=None)
    return c.T.reshape(y.shape[1:] + (degree + 1,)).tolist()


def _eval_poly(coeff, t):
    c = _arr(coeff)
    t = float(t)
    return np.tensordot(c, np.power(t - 25., np.arange(c.shape[-1])), axes=([-1], [0]))


def evaluate(rows, sensor, model):
    name = 'acc_raw_mean_g' if sensor == 'acc' else 'gyro_raw_mean_dps'
    errors = []
    for row in rows:
        temp = float(row['temperature_mean_c'])
        bias = _eval_poly(model['bias_coeff'], temp)
        forward = _eval_poly(model['forward_coeff'], temp)
        if np.linalg.cond(forward) > 100 or abs(np.linalg.det(forward)) < 1e-7:
            raise ValueError('验证点插值矩阵病态，拒绝外推')
        raw = _arr(row[name], (3,))
        ref = _arr(row['reference'], (3,))
        pred = np.linalg.solve(forward, raw - bias)
        errors.append(float(np.linalg.norm(pred - ref)))
    if not errors:
        raise ValueError('无可用的独立验证样本')
    return {'count': len(errors), 'vector_rmse': float(np.sqrt(np.mean(np.square(errors)))),
            'vector_max': float(np.max(errors)), 'individual_vector_errors': errors,
            'unit': 'g' if sensor == 'acc' else 'deg/s'}


def evaluate_fixed_25(rows, sensor, model):
    """Comparison baseline: FIX the fitted thermal matrix at T=25°C.

    This baseline is not the workstation's separate ambient JSON; report this
    distinction explicitly and never call it a production parameter.
    """
    name = 'acc_raw_mean_g' if sensor == 'acc' else 'gyro_raw_mean_dps'
    F = _eval_poly(model['forward_coeff'], 25.0)
    b = _eval_poly(model['bias_coeff'], 25.0)
    if np.linalg.cond(F) > 100:
        raise ValueError('25℃基准矩阵病态')
    errors = [float(np.linalg.norm(np.linalg.solve(F, _arr(r[name], (3,)) - b) - _arr(r['reference'], (3,)))) for r in rows]
    if not errors:
        raise ValueError('无温度对比样本')
    return {'count': len(errors), 'vector_rmse': float(np.sqrt(np.mean(np.square(errors)))),
            'vector_max': float(max(errors)),
            'unit': 'g' if sensor == 'acc' else 'deg/s',
            'reference': 'thermal fit matrix held fixed at 25C (NOT external ambient JSON)'}


def build_thermal_model(rows, sensor, degree=3):
    """Strict split: temperature fit points != independent holdout temperatures.

    At each fit temperature, fit intrinsic parameters from fit-condition rows only.
    Verify model with independent CONDITIONS at fit temperatures AND independent
    TEMPERATURES. Never feed holdout rows into any parameter fitting.
    """
    if sensor not in ('acc', 'gyro') or degree not in (1, 2, 3):
        raise ValueError('不支持的传感器类型或多项式阶数')
    fit_groups = {}
    for row in rows:
        if row['sensor'] == sensor and row['split'] == 'fit' and row['temperature_split'] == 'fit':
            fit_groups.setdefault(float(row['temperature_target_c']), []).append(row)
    if len(fit_groups) < degree + 1:
        raise ValueError('拟合温度点太少')
    temps, biases, forwards, per_point = [], [], [], []
    for set_t, group in sorted(fit_groups.items()):
        result = fit_affine(group, sensor)
        temps.append(float(np.mean([x['temperature_mean_c'] for x in group])))
        biases.append(result['bias'])
        forwards.append(result['forward_matrix'])
        per_point.append({'target_temperature_c': set_t,
                          'mean_sensor_temperature_c': temps[-1], **result})
    model = {'schema_version': 1, 'sensor': sensor,
             'model': 'raw = F(T_chip) @ reference + b(T_chip)',
             'temperature_variable': 'IMU internal temperature (°C)',
             'temperature_center_c': 25., 'polynomial_degree': degree,
             'fit_temperature_range_c': [min(temps), max(temps)],
             'fit_temperature_setpoints_c': sorted(fit_groups),
             'bias_coeff': _fit_poly(temps, biases, degree),
             'forward_coeff': _fit_poly(temps, forwards, degree),
             'fit_temperature_parameters': per_point}
    # 高阶曲线不仅检查拟合点，还检查拟合区间内部是否出现不可逆矩阵。
    for candidate_t in np.linspace(min(temps), max(temps), 41):
        local_F = _eval_poly(model['forward_coeff'], candidate_t)
        if np.linalg.cond(local_F) > 100 or abs(np.linalg.det(local_F)) < 1e-7:
            raise ValueError('温度多项式在拟合区间内出现奇异/病态矩阵，拒绝生成候选模型')
    condition_holdout = [r for r in rows if r['sensor'] == sensor and r['temperature_split'] == 'fit' and r['split'] == 'validate']
    temp_holdout = [r for r in rows if r['sensor'] == sensor and r['temperature_split'] == 'validate' and r['split'] == 'validate']
    if not condition_holdout or not temp_holdout:
        raise ValueError('缺少独立验证姿态或独立验证温度点')
    temp_holdout_set = {float(r['temperature_target_c']) for r in temp_holdout}
    if temp_holdout_set & set(fit_groups):
        raise ValueError('温度拟合与独立验证集合重叠，禁止数据泄漏')
    if any(not (min(temps) <= float(r['temperature_mean_c']) <= max(temps)) for r in temp_holdout):
        raise ValueError('独立验证温度落在拟合实测温度范围之外，禁止外推评价')
    model['condition_holdout'] = evaluate(condition_holdout, sensor, model)
    model['temperature_holdout'] = evaluate(temp_holdout, sensor, model)
    model['fixed_25c_holdout'] = evaluate_fixed_25(temp_holdout, sensor, model)
    model['holdout_temperature_setpoints_c'] = sorted(temp_holdout_set)
    model['production_release'] = False
    model['status'] = 'RESEARCH_ONLY_NOT_PRODUCTION_APPROVED'
    model['created_at_utc'] = datetime.now(timezone.utc).isoformat()
    return model


def apply_temperature_model(model, measured, temperature_c):
    '''Apply candidate full-affine thermal correction only within fitted range.'''
    T = float(temperature_c)
    low, high = model['fit_temperature_range_c']
    if not low <= T <= high:
        raise ValueError('超出模型的实测拟合温度范围；禁止外推')
    if model.get('temperature_input'):
        from thermal_temperature_inputs import map_chip_temperature
        effective_T = map_chip_temperature(model['temperature_input'], T)
    else:
        effective_T = T
    F = _eval_poly(model['forward_coeff'], effective_T)
    b = _eval_poly(model['bias_coeff'], effective_T)
    if np.linalg.cond(F) > 100:
        raise ValueError('温度补偿矩阵病态')
    return np.linalg.solve(F, _arr(measured, (3,))-b).tolist()


def save_models(folder, rows, sensor_types=('acc', 'gyro'), degree=3):
    from pathlib import Path
    root = Path(folder)
    root.mkdir(parents=True, exist_ok=True)
    manifest = {'status': 'RESEARCH_ONLY_NOT_PRODUCTION_APPROVED', 'sensors': {},
                'temperature_polynomial_degree': degree, 'records': len(rows)}
    for sensor in sensor_types:
        try:
            model = build_thermal_model(rows, sensor, degree)
            with (root / f'thermal_{sensor}_candidate.json').open('w', encoding='utf-8') as f:
                json.dump(model, f, indent=2, ensure_ascii=False)
            manifest['sensors'][sensor] = {'status': 'candidate_created',
                                           'polynomial_degree': degree,
                                           'temperature_holdout': model['temperature_holdout'],
                                           'fixed_25c_holdout':model['fixed_25c_holdout']}
        except (ValueError, np.linalg.LinAlgError) as exc:
            manifest['sensors'][sensor] = {'status': 'not_estimated', 'reason': str(exc)}
    with (root / 'thermal_fit_status.json').open('w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    return manifest


def build_gyro_zero_bias_model(rows, degree=3):
    """Independent static gyro-bias thermal model; never claims scale compensation."""
    zero = [r for r in rows if r['sensor'] == 'gyro' and r.get('mode') == 'static']
    fit = [r for r in zero if r['temperature_split'] == 'fit' and r['split'] == 'fit']
    validate = [r for r in zero if r['temperature_split'] == 'validate' and r['split'] == 'validate']
    if len(fit) < degree + 1 or not validate:
        raise ValueError('GYRO 静止零偏温补缺少拟合或独立验证温度点')
    temps = [float(r['temperature_mean_c']) for r in fit]
    coeff = _fit_poly(temps, [r['gyro_raw_mean_dps'] for r in fit], degree)
    errors = [float(np.linalg.norm(_arr(r['gyro_raw_mean_dps'], (3,)) - _eval_poly(coeff, float(r['temperature_mean_c'])))) for r in validate]
    if any(not min(temps) <= r['temperature_mean_c'] <= max(temps) for r in validate):
        raise ValueError('验证温度不在拟合温度范围内')
    return {'schema_version': 1, 'sensor': 'gyro', 'type': 'zero_bias_temperature_only',
            'temperature_variable': 'IMU internal temperature (°C)',
            'temperature_center_c': 25., 'degree': degree, 'bias_coeff_dps': coeff,
            'fit_temperature_range_c': [min(temps), max(temps)],
            'independent_temperature_rmse_dps': float(np.sqrt(np.mean(np.square(errors)))),
            'independent_temperature_max_dps': float(max(errors)),
            'validation_count': len(errors), 'production_release': False,
            'status': 'RESEARCH_ONLY_NOT_PRODUCTION_APPROVED'}
