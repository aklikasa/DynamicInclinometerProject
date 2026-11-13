# -*- coding: utf-8 -*-
"""Flexible WK thermal experiment temperatures, with honest statistical output.

This module is pure Python/Numpy: it does not send any device, PLC or motor command.
"""
import json
import math
import re
from pathlib import Path
import numpy as np
from thermal_compensation import (fit_affine, evaluate, _fit_poly, save_models,
                                  build_gyro_zero_bias_model, _arr)


def parse_temperatures(text):
    """Accept one or more unique setpoints in the range supported by the existing UI."""
    tokens = re.split(r'[,，;；\n]+', str(text).strip())
    if not tokens or any(not tok.strip() for tok in tokens):
        raise ValueError('请填写至少一个温度，例如 25 或 -20, 0, 25, 45, 70')
    try:
        values = [float(tok.strip()) for tok in tokens]
    except ValueError as exc:
        raise ValueError('温度点格式错误，请使用逗号分隔数字，例如 25 或 -20, 25, 70') from exc
    if any(not math.isfinite(v) or not -40.0 <= v <= 85.0 for v in values):
        raise ValueError('温度点必须为 -40～85°C 内的有限数字')
    if len(set(values)) != len(values):
        raise ValueError('温度点不能重复')
    if values != sorted(values):
        raise ValueError('当前自动流程按低温到高温运行，请按升序填写温度点')
    return values


def temperature_splits(temps):
    """Assign setpoints for cubic T-model calibration, without leakage.

    1-4 temperatures: all are fit setpoints (1-3: local-only; 4: provisional
    cubic without independent temperature holdout).
    5+ temperatures: preserve both endpoints and at least four temperature-fit
    setpoints; leave one or more interior setpoints for independent validation.
    Default five: -20, 0, 25, 70 fit; 45 independent temperature validation.
    """
    if not temps:
        raise ValueError('温度点不能为空')
    values = [float(t) for t in temps]
    n = len(values)
    if n <= 4:
        return {t: 'fit' for t in values}
    fit_indices = {0, n - 1} | {i for i in range(0, n, 2)}
    for i in range(1, n - 1):
        if len(fit_indices) >= 4:
            break
        fit_indices.add(i)
    result = {t: ('fit' if i in fit_indices else 'validate')
              for i, t in enumerate(values)}
    assert sum(v == 'fit' for v in result.values()) >= 4
    assert sum(v == 'validate' for v in result.values()) >= 1
    return result



def separate_temperature_plan(fit_text, validation_text):
    """Build a fixed, ordered acquisition plan from two user-controlled lists.

    PV and IMU stabilization are identical at both kinds of temperature. The
    validation setpoints NEVER participate in temperature-map or sensor fits.
    """
    fit = parse_temperatures(fit_text)
    validation = parse_temperatures(validation_text)
    if len(fit) < 3:
        raise ValueError('拟合温度至少需要3个不同温度点；三次模型建议至少5个拟合温度点')
    overlap = set(fit).intersection(validation)
    if overlap:
        raise ValueError('拟合温度与独立验证温度不能重复：' + ', '.join(f'{v:g}℃' for v in sorted(overlap)))
    if any(not fit[0] < value < fit[-1] for value in validation):
        raise ValueError('独立验证温度必须位于拟合温度的最小值和最大值之间，禁止外推验收')
    splits = {t: ('fit' if t in fit else 'validate') for t in sorted(fit+validation)}
    return {'fit_temperatures_c': fit,
            'validation_temperatures_c': validation,
            'temperature_setpoints_c': sorted(splits),
            'temperature_split': splits}


def steps_for_temperature(all_steps, role):
    """Fit points run calibration + condition verification; holdout runs tests only."""
    if role not in ('fit', 'validate'):
        raise ValueError('未知温度点用途')
    if role == 'fit':
        return list(all_steps)
    selected = [step for step in all_steps if step['split'] == 'validate']
    if not selected:
        raise ValueError('独立验证温度缺少独立测试工况')
    return selected

def _point_fit(rows, sensor, setpoint):
    # Every temperature contains separate fit and independent-condition rows.
    sensor_rows = [r for r in rows if r.get('sensor') == sensor
                   and float(r.get('temperature_target_c')) == float(setpoint)]
    fit_rows = [r for r in sensor_rows if r['split'] == 'fit']
    validation_rows = [r for r in sensor_rows if r['split'] == 'validate']
    params = fit_affine(fit_rows, sensor)
    if not validation_rows:
        raise ValueError('缺少独立工况验证数据')
    field = 'acc_raw_mean_g' if sensor == 'acc' else 'gyro_raw_mean_dps'
    F = np.asarray(params['forward_matrix'], float)
    b = np.asarray(params['bias'], float)
    errors = [float(np.linalg.norm(np.linalg.solve(F, _arr(r[field], (3,)) - b)
                                   - _arr(r['reference'], (3,)))) for r in validation_rows]
    return {'setpoint_c': float(setpoint),
            'mean_sensor_temperature_c': float(np.mean([r['temperature_mean_c'] for r in fit_rows])),
            **params,
            'independent_condition_validation': {
                'count': len(errors), 'vector_rmse': float(np.sqrt(np.mean(np.square(errors)))),
                'vector_max': max(errors), 'unit': 'g' if sensor == 'acc' else 'deg/s'}}


def save_variable_models(folder, rows, temperature_points, sensors=('acc','gyro'), device_sn=None):
    """Use cubic temperature model (degree=3); never quietly revert to linear.

    1-3 setpoints: store per-temperature 3D affine matrices only.
    4 setpoints: a PROVISIONAL cubic model can be saved without a temperature
      holdout; independent CONDITION holdout remains available at each temp.
    >=5 setpoints: at least four fit temperatures + one held-out temperature;
      evaluate cubic compensation and fixed-25 baseline on independent data.
    """
    from calibration_artifact_paths import safe_device_sn, thermal_filename
    if device_sn:
        device_sn=safe_device_sn(device_sn)
    root = Path(folder)
    root.mkdir(parents=True, exist_ok=True)
    temps = [float(t) for t in temperature_points]
    if len(temps) >= 5:
        return save_models(root, rows, sensors, degree=3, device_sn=device_sn)

    manifest = {'status': 'RESEARCH_ONLY_NOT_PRODUCTION_APPROVED',
                'calibration_type':'thermal_fit_status', 'device_serial':device_sn,
                'temperature_polynomial_degree': 3,
                'temperature_setpoints_c': temps, 'records': len(rows), 'sensors': {}}
    for sensor in sensors:
        try:
            point_params = [_point_fit(rows, sensor, t) for t in temps]
            local = {'schema_version': 1, 'sensor': sensor,
                     'device_serial':device_sn, 'calibration_type':f'{sensor}_thermal_local_calibration',
                     'type': 'per_temperature_affine_calibration',
                     'temperature_setpoints_c': temps,
                     'temperature_variable': 'IMU internal measured temperature °C',
                     'per_temperature_parameters': point_params,
                     'has_independent_temperature_validation': False,
                     'production_release': False,
                     'warning': '仅为所测温度下的标定，不能证明温补模型跨温度有效。'}
            local_name=(thermal_filename(device_sn,sensor,'local') if device_sn else f'local_{sensor}_temperature_calibration.json')
            with (root / local_name).open('w',encoding='utf-8') as f:
                json.dump(local,f,ensure_ascii=False,indent=2)
            info = {'status':'local_calibration_only',
                    'reason': f'仅有 {len(temps)} 个温度点，少于三次温度模型所需的4个拟合温度点。',
                    'condition_validation': [p['independent_condition_validation'] for p in point_params]}
            if len(temps) == 4:
                actual_t = [p['mean_sensor_temperature_c'] for p in point_params]
                try:
                    provisional = {
                        'schema_version': 1, 'sensor': sensor,
                        'device_serial':device_sn, 'calibration_type':f'{sensor}_thermal_provisional_candidate',
                        'type': 'provisional_cubic_temperature_model_without_independent_temperature_validation',
                        'temperature_variable': 'IMU internal measured temperature °C',
                        'temperature_center_c': 25.0, 'polynomial_degree': 3,
                        'fit_temperature_range_c': [min(actual_t), max(actual_t)],
                        'bias_coeff': _fit_poly(actual_t,[p['bias'] for p in point_params],3),
                        'forward_coeff': _fit_poly(actual_t,[p['forward_matrix'] for p in point_params],3),
                        'fit_temperature_parameters': point_params,
                        'condition_holdout_per_temperature': [p['independent_condition_validation'] for p in point_params],
                        'has_independent_temperature_validation': False,
                        'production_release': False,
                        'warning': '四点三次曲线恰好插值四个温度参数；缺少未参与拟合的温度验证，严禁当作全温区已验证模型。'}
                    for temperature in np.linspace(min(actual_t), max(actual_t), 41):
                        from thermal_compensation import _eval_poly
                        F = _eval_poly(provisional['forward_coeff'], temperature)
                        if np.linalg.cond(F) > 100 or abs(np.linalg.det(F)) < 1e-7:
                            raise ValueError('拟合区间内三维矩阵病态')
                    provisional_name=(thermal_filename(device_sn,sensor,'provisional') if device_sn else f'thermal_{sensor}_PROVISIONAL_cubic_no_temperature_holdout.json')
                    with (root/provisional_name).open('w',encoding='utf-8') as f:
                        json.dump(provisional,f,ensure_ascii=False,indent=2)
                    info.update({'status': 'provisional_cubic_no_temperature_holdout',
                                 'polynomial_degree': 3,
                                 'reason': '四温度点三次拟合已生成，仅供研发；尚无独立温度验证。'})
                except (ValueError, np.linalg.LinAlgError) as exc:
                    info['reason'] = '已保留单温度标定参数；三次拟合不可靠：' + str(exc)
            manifest['sensors'][sensor] = info
        except (ValueError, np.linalg.LinAlgError) as exc:
            manifest['sensors'][sensor] = {'status':'not_estimated', 'reason':str(exc)}
    status_name=(thermal_filename(device_sn,artifact='fit_status') if device_sn else 'thermal_fit_status.json')
    with (root/status_name).open('w',encoding='utf-8') as f:
        json.dump(manifest,f,ensure_ascii=False,indent=2)
    return manifest


def save_optional_gyro_bias(folder, rows, temps, device_sn=None):
    """Cubic static-bias temperature candidate only with >=5 setpoints + holdout."""
    from calibration_artifact_paths import safe_device_sn, thermal_filename
    if device_sn:
        device_sn=safe_device_sn(device_sn)
    root = Path(folder)
    if len(temps) >= 5:
        obj = build_gyro_zero_bias_model(rows, degree=3)
        name = thermal_filename(device_sn,artifact='gyro_bias') if device_sn else 'thermal_gyro_bias_only_candidate.json'
        if device_sn:
            obj['device_serial']=device_sn
            obj['calibration_type']='gyro_thermal_bias_only_candidate'
    else:
        zero = [r for r in rows if r.get('sensor')=='gyro' and r.get('mode')=='static']
        obj = {'schema_version':1,'sensor':'gyro','type':'static_bias_measurements_only',
               'temperature_setpoints_c':list(temps),
               'measurements':[{'target_temperature_c':r['temperature_target_c'],
                                'chip_temperature_c':r['temperature_mean_c'],
                                'gyro_mean_dps':r['gyro_raw_mean_dps'],
                                'split':r['split']} for r in zero],
               'independent_temperature_validation':False,
               'production_release':False,
               'reason':'少于5点，没有足够的拟合温度与独立温度验证点；仅保留静态观测。'}
        name = thermal_filename(device_sn,artifact='zero_observations') if device_sn else 'gyro_zero_rate_observations.json'
        if device_sn:
            obj['device_serial']=device_sn
            obj['calibration_type']='gyro_thermal_zero_rate_observations'
    with (root/name).open('w',encoding='utf-8') as f:
        json.dump(obj,f,indent=2,ensure_ascii=False)
    return str(root/name)
