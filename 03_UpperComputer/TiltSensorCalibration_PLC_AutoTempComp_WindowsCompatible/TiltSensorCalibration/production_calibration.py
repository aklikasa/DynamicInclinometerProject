# -*- coding: utf-8 -*-
"""常温 IMU 逐台标定的独立计算/工况模块（不依赖 Qt、设备 DLL）。

数值限值来自可编辑的生产工艺试运行配置，不是 IEEE 标准统一规定的验收值。
"""
import json
import math
import os
import numpy as np

PROFILE_FILENAME = 'production_quality_profile.json'

# 注意：下列默认阈值属于工程试运行占位值，必须结合器件、产品指标、转台证书和 GR&R 正式批准。
DEFAULT_PROFILE = {
    'profile_id': 'PILOT_AMBIENT_IMU_V1',
    'approved_for_production': False,
    'scope': 'PCB 六轴 IMU 常温，公共机械平台 P，禁止作为全温产品认证',
    'references': ['IEEE 1293-2018（加速度计方法参考）',
                   'IEEE 1431-2004（非活动保留；陀螺仪方法参考）',
                   'IEEE 1554-2005（非活动保留；设备及数据参考）'],
    'quality': {
        'minimum_frames': 50,
        'static_sample_max_retries': 5,
        'rate_sample_max_retries': 3,
        'max_rejection_fraction': 0.10,
        'mad_sigma': 3.0,  # ACC帧内与跨帧
        'gyro_mad_sigma': 6.0,  # GYRO噪声分布单独配置，避免ACC改动误伤GYRO
        'static_acc_std_max_g': 0.025,
        'static_gyro_std_max_dps': 0.45,
        'rate_gyro_std_max_dps': 0.55,
        'rate_reference_std_max_dps': 0.18,
        'rate_reference_error_max_dps': 0.30,
        'static_feedback_speed_max_dps': 0.05,
        'temperature_min_c': 15.0,
        'temperature_max_c': 35.0,
        'temperature_span_max_c': 1.0,
        'feedback_age_max_ms': 250,
    },
    'acceptance': {
        'acc_vector_rmse_max_g': 0.015,
        'acc_vector_max_error_g': 0.035,
        'acc_angle_max_deg': 1.2,
        'acc_norm_max_error_g': 0.030,
        'gyro_vector_rmse_max_dps': 0.25,
        'gyro_vector_max_error_dps': 0.65,
        'gyro_zero_residual_max_dps': 0.15,
        'gyro_direction_max_deg': 4.0,
        'gyro_cross_axis_max_dps': 0.45,
        'correction_condition_max': 30.0,
        'fit_design_condition_max': 20.0,
        'temperature_run_span_max_c': 3.0,
    },
    'rates': {'fit_dps': [1.0, 2.0, 5.0], 'verify_dps': [1.5, 3.5],
              'maximum_command_rate_dps': 10.0},
    'timing': {'gyro_zero_seconds': 45.0, 'static_seconds': 5.0, 'rate_seconds': 5.0,
               'settle_seconds': 3.0},
}


def load_profile(root):
    path = os.path.join(root, PROFILE_FILENAME)
    with open(path, encoding='utf-8') as stream:
        cfg = json.load(stream)
    for key in ('quality', 'acceptance', 'rates', 'timing'):
        if key not in cfg or not isinstance(cfg[key], dict):
            raise ValueError(f'工艺配置缺少 {key} 字段')
    if cfg['rates']['maximum_command_rate_dps'] > 10.0:
        raise ValueError('生产工艺速率上限不得直接超出已有限速 10°/s；须重新验证设备能力')
    all_rates = cfg['rates']['fit_dps'] + cfg['rates']['verify_dps']
    if not all_rates or min(all_rates) <= 0 or max(all_rates) > cfg['rates']['maximum_command_rate_dps']:
        raise ValueError('标定/验证转速超出允许的正数范围')
    if set(cfg['rates']['fit_dps']) & set(cfg['rates']['verify_dps']):
        raise ValueError('拟合和独立验证必须使用不同的速度幅值')
    # 静态工况重试次数是有限非负整数；不允许配置成无限循环。
    retries = cfg['quality'].get('static_sample_max_retries', 5)
    if type(retries) is not int or not 0 <= retries <= 10:
        raise ValueError('quality.static_sample_max_retries 必须为 0–10 的整数')
    rate_retries = cfg['quality'].get('rate_sample_max_retries', 3)
    if type(rate_retries) is not int or not 0 <= rate_retries <= 10:
        raise ValueError('quality.rate_sample_max_retries 必须为 0–10 的整数')
    if float(cfg['timing']['gyro_zero_seconds']) < 20:
        raise ValueError('陀螺仪静止零偏采样不允许少于20秒')
    validate_profile(cfg)
    return cfg


def acc_fit_steps():
    # (内轴 beta, 外轴 alpha)；六个正反方向保证 D 的秩为4。
    cardinal = [(0, 0), (0, 180), (90, 90), (270, 90), (0, 90), (180, 90)]
    extra = [(45, 45), (135, 45), (225, 135), (315, 135), (45, 225), (225, 315)]
    return [{'mode': 'static', 'step_id': f'ACC_FIT_{i:02d}', 'split': 'fit',
             'inner_deg': float(beta), 'outer_deg': float(alpha)}
            for i, (beta, alpha) in enumerate(cardinal + extra, 1)]


def acc_verify_steps():
    # 角度组合与拟合集不重合；避免 0/180 外轴纯重复方向。
    poses = [(25, 35), (75, 65), (125, 115), (175, 145),
             (235, 215), (285, 245), (40, 295), (140, 325),
             (220, 55), (310, 125), (70, 235), (250, 305)]
    return [{'mode': 'static', 'step_id': f'ACC_VAL_{i:02d}', 'split': 'validate',
             'inner_deg': float(beta), 'outer_deg': float(alpha)}
            for i, (beta, alpha) in enumerate(poses, 1)]


def gyro_rate_steps(rates, split, prefix):
    # 旋转方向为 P 系 +Z(内轴), +X(外轴,beta=0), +Y(外轴,beta=270 正速度)。
    dirs = [('Z', 'inner', 180, 0), ('X', 'outer', 0, 180), ('Y', 'outer', 270, 180)]
    steps = []
    for dname, axis, beta, alpha in dirs:
        for magnitude in rates:
            for direction in (1, -1):
                steps.append({'mode': 'rate', 'step_id': f'{prefix}_{dname}_{len(steps)+1:02d}',
                              'split': split, 'inner_deg': float(beta), 'outer_deg': float(alpha),
                              'rotation_axis': axis, 'target_rate_dps': float(magnitude * direction)})
    return steps


def gyro_fit_steps(profile):
    return ([{'mode': 'static', 'step_id': 'GYRO_ZERO_FIT', 'split': 'fit',
              'inner_deg': 0.0, 'outer_deg': 0.0,
              'sample_seconds': float(profile['timing']['gyro_zero_seconds'])}]
            + gyro_rate_steps(profile['rates']['fit_dps'], 'fit', 'GYRO_FIT'))


def gyro_verify_steps(profile):
    return ([{'mode': 'static', 'step_id': 'GYRO_ZERO_VAL', 'split': 'validate',
              'inner_deg': 0.0, 'outer_deg': 0.0,
              'sample_seconds': max(10.0, float(profile['timing']['static_seconds']))}]
            + gyro_rate_steps(profile['rates']['verify_dps'], 'validate', 'GYRO_VAL'))


def _static_circular_mean_degrees(angles):
    """静态位置的角度均值。处理采样反馈由 359.9° 跨到 0.1° 的情况。"""
    values = np.asarray(angles, dtype=float)
    if values.ndim != 1 or len(values) == 0 or not np.all(np.isfinite(values)):
        raise ValueError('转台姿态角反馈无效')
    base = values[0]
    differences = (values - base + 180.0) % 360.0 - 180.0
    return float((base + np.mean(differences)) % 360.0)


def robust_segment(frames, mode, profile, target_rate=None, axis=None, static_sensor='both'):
    """每工况统计：先对帧均值做MAD筛除，再检验噪声/温漂/反馈稳定。

    帧内 16 样本的异常量值在采集阶段也会用 MAD 剔除，此处控制跨帧失稳。
    """
    cfg = profile['quality']
    if mode == 'static' and static_sensor not in ('acc', 'gyro', 'both'):
        raise ValueError(f'未知静态传感器质量检查类型：{static_sensor}')
    if len(frames) < int(cfg['minimum_frames']):
        raise ValueError(f'有效帧不足 {len(frames)}/{cfg["minimum_frames"]}')
    accel = np.asarray([x['acc'] for x in frames], float)
    gyro = np.asarray([x['gyro'] for x in frames], float)
    rate = np.asarray([[x['inner_rate_dps'], x['outer_rate_dps']] for x in frames], float)
    temp = np.asarray([x.get('temp_c', float('nan')) for x in frames], float)
    # ACC 标定不依赖 GYRO 噪声门槛；GYRO 零偏使用 GYRO；六轴复核保留双传感器检查。
    mat = (gyro if static_sensor == 'gyro' else accel) if mode == 'static' else gyro
    if not (np.all(np.isfinite(mat)) and np.all(np.isfinite(rate)) and np.all(np.isfinite(temp))):
        raise ValueError('当前标定所需采样存在非有限值，或者缺少可用的温度数据')
    if mode == 'static' and static_sensor == 'both' and not np.all(np.isfinite(gyro)):
        raise ValueError('六轴静态核验缺少有效 GYRO 数据')
    med = np.median(mat, axis=0)
    mad = np.median(abs(mat - med), axis=0)
    scale = np.maximum(mad * 1.4826, 1e-4 if mode == 'static' else 0.01)
    score = np.max(abs(mat - med) / scale, axis=1)
    # ACC采用3×稳健σ；GYRO仍维持原工艺6×稳健σ，独立于ACC筛选参数。
    sigma = float(cfg.get('gyro_mad_sigma', cfg['mad_sigma'])) if (
        mode == 'rate' or static_sensor == 'gyro') else float(cfg['mad_sigma'])
    mask = score <= sigma
    rejection = float(1.0 - np.mean(mask))
    if rejection > cfg['max_rejection_fraction']:
        raise ValueError(f'离群帧比例 {rejection:.1%} 超限 {cfg["max_rejection_fraction"]:.1%}')
    if sum(mask) < cfg['minimum_frames']:
        raise ValueError('剔除离群点后有效帧不足')
    a = accel[mask]; g = gyro[mask]; w = rate[mask]; t = temp[mask]
    tspan = float(np.ptp(t))
    if float(np.min(t)) < cfg['temperature_min_c'] or float(np.max(t)) > cfg['temperature_max_c']:
        raise ValueError(f'温度超出配置常温范围：{np.min(t):.2f}–{np.max(t):.2f} ℃')
    if tspan > cfg['temperature_span_max_c']:
        raise ValueError(f'采样温度漂移 {tspan:.2f} ℃ 超限')
    acc_std = np.std(a, axis=0) if np.all(np.isfinite(a)) else None
    gyr_std = np.std(g, axis=0) if np.all(np.isfinite(g)) else None
    if mode == 'static':
        if static_sensor in ('acc', 'both'):
            if acc_std is None or np.max(acc_std) > cfg['static_acc_std_max_g']:
                raise ValueError(f'静态ACC抖动 {float(np.max(acc_std)) if acc_std is not None else float("nan"):.5f} g 超限')
        if static_sensor in ('gyro', 'both'):
            if gyr_std is None or np.max(gyr_std) > cfg['static_gyro_std_max_dps']:
                raise ValueError(f'静态GYRO抖动 {float(np.max(gyr_std)) if gyr_std is not None else float("nan"):.5f} °/s 超限')
        if np.max(abs(w)) > cfg['static_feedback_speed_max_dps']:
            raise ValueError('静止采样期间转台反馈角速度不为零')
    else:
        if np.max(gyr_std) > cfg['rate_gyro_std_max_dps']:
            raise ValueError(f'动态GYRO抖动 {np.max(gyr_std):.4f} °/s 超限')
        rates = w[:, 0 if axis == 'inner' else 1]
        if float(np.std(rates)) > cfg['rate_reference_std_max_dps']:
            raise ValueError('转台实测速度波动过大')
        if target_rate is not None and abs(float(np.mean(rates))-target_rate) > cfg['rate_reference_error_max_dps']:
            raise ValueError('转台稳定段实际平均转速偏离目标')
    raw_acc_samples = sum(int(f.get('acc_raw_samples', 0)) for f in frames)
    accepted_acc_samples = sum(int(frames[i].get('acc_accepted_samples', 0)) for i in np.flatnonzero(mask))
    raw_gyro_samples = sum(int(f.get('gyro_raw_samples', 0)) for f in frames)
    accepted_gyro_samples = sum(int(frames[i].get('gyro_accepted_samples', 0)) for i in np.flatnonzero(mask))
    return {
        'frame_count': int(len(frames)), 'accepted_frames': int(np.sum(mask)),
        'acc_raw_samples': raw_acc_samples, 'acc_accepted_samples': accepted_acc_samples,
        'gyro_raw_samples': raw_gyro_samples, 'gyro_accepted_samples': accepted_gyro_samples,
        'filter_method': 'per_frame_MAD_1.4826_then_segment_MAD_1.4826',
        'filter_sigma': sigma,
        'reject_fraction': rejection,
        'acc_raw_mean_g': np.mean(a, axis=0).tolist() if acc_std is not None else None,
        'gyro_raw_mean_dps': np.mean(g, axis=0).tolist() if gyr_std is not None else None,
        'acc_std_g': acc_std.tolist() if acc_std is not None else None,
        'gyro_std_dps': gyr_std.tolist() if gyr_std is not None else None,
        # 静态姿态必须按周期角度求均值，避免 359.9°/0.1° 算术平均成 180°。
        # 动态速率段保留原有位置统计，不改变角速度拟合/稳态计算逻辑。
        'inner_actual_mean_deg': (
            _static_circular_mean_degrees([frames[i]['inner_deg'] for i in np.flatnonzero(mask)])
            if mode == 'static' else float(np.mean([frames[i]['inner_deg'] for i in np.flatnonzero(mask)]))
        ),
        'outer_actual_mean_deg': (
            _static_circular_mean_degrees([frames[i]['outer_deg'] for i in np.flatnonzero(mask)])
            if mode == 'static' else float(np.mean([frames[i]['outer_deg'] for i in np.flatnonzero(mask)]))
        ),
        'inner_rate_mean_dps': float(np.mean(w[:, 0])),
        'outer_rate_mean_dps': float(np.mean(w[:, 1])),
        'temperature_mean_c': float(np.mean(t)), 'temperature_span_c': tspan,
        'temperature_min_c': float(np.min(t)), 'temperature_max_c': float(np.max(t)),
    }


def frame_average_sanitized(values, mad_sigma=3., return_stats=False):
    """16点帧内稳健3σ剔除（σ≈1.4826·MAD）；后取保留样本算术均值。

    return_stats=True 返回 (均值, 原始样本数, 有效样本数)，方便5秒工况追溯。
    """
    arr = np.asarray(values, float)
    if arr.ndim != 2 or arr.shape[1] != 3 or len(arr) < 8 or not np.all(np.isfinite(arr)):
        return (None, len(arr) if arr.ndim == 2 else 0, 0) if return_stats else None
    center = np.median(arr, axis=0)
    mad = np.median(abs(arr-center), axis=0)
    floor = 1e-4 if float(np.max(abs(arr))) < 2 else 0.01
    scaled = np.maximum(1.4826*mad, floor)
    mask = np.max(abs(arr-center)/scaled, axis=1) <= mad_sigma
    count = int(np.sum(mask))
    if np.mean(mask) < 0.80:
        return (None, len(arr), count) if return_stats else None
    mean = np.mean(arr[mask], axis=0)
    return (mean, len(arr), count) if return_stats else mean


def sensor_axis_invariants(forward):
    """测量行敏感度与两两夹角；对右乘安装旋转不变，不把对角线误当纯比例因子。"""
    matrix = np.asarray(forward,float)
    gram = matrix @ matrix.T
    gains = np.sqrt(np.maximum(np.diag(gram), 0.0))
    if np.min(gains) <= 0:
        raise ValueError('敏感度矩阵不合法')
    angles = {}
    for i,j,name in ((0,1,'xy'),(0,2,'xz'),(1,2,'yz')):
        cosine = np.clip(gram[i,j]/(gains[i]*gains[j]), -1,1)
        angles[name] = float(np.rad2deg(np.arccos(cosine)))
    return {'axis_sensitivity':gains.tolist(),
            'pairwise_axis_angles_deg':angles,
            'pairwise_nonorthogonality_deg':{key:value-90.0 for key,value in angles.items()},
            'meaning':'灵敏度按原始测量通道定义；安装旋转不变量；非任意校正矩阵对角元素'}


def residual_statistics(refs, measurements, bias, correction, kind):
    ref = np.asarray(refs, float); obs = np.asarray(measurements, float)
    if ref.shape != obs.shape or len(ref) == 0 or ref.shape[1] != 3:
        raise ValueError('独立验证集缺失或者形状错误')
    corrected = (obs - np.asarray(bias, float)) @ np.asarray(correction, float).T
    err = corrected - ref
    norm = np.linalg.norm(err, axis=1)
    report = {
        'count': len(ref), 'rmse_vector': float(np.sqrt(np.mean(norm**2))),
        'max_vector_error': float(np.max(norm)),
        'rmse_axis': np.sqrt(np.mean(err**2, axis=0)).tolist(),
        'max_error_axis': np.max(abs(err), axis=0).tolist(),
        'vectors': [{'reference': a.tolist(), 'corrected': b.tolist(), 'error': c.tolist()}
                    for a,b,c in zip(ref,corrected,err)],
    }
    if kind == 'acc':
        unit = np.linalg.norm(corrected, axis=1)
        dot = np.sum(corrected*ref, axis=1)
        dirs = np.rad2deg(np.arccos(np.clip(dot/np.maximum(unit*np.linalg.norm(ref,axis=1),1e-10),-1.,1.)))
        report.update({'max_direction_error_deg':float(np.max(dirs)),
                       'max_norm_error_g':float(np.max(abs(unit-1.0))),
                       'direction_errors_deg':dirs.tolist()})
    elif kind == 'gyro':
        ref_norm = np.linalg.norm(ref, axis=1)
        moving = ref_norm > 0.2
        angle = np.zeros(len(ref))
        if np.any(moving):
            c = corrected[moving]; r = ref[moving]
            dot = np.sum(c*r,axis=1)
            angle[moving]=np.rad2deg(np.arccos(np.clip(dot/np.maximum(np.linalg.norm(c,axis=1)*np.linalg.norm(r,axis=1),1e-10),-1.,1.)))
        report['max_direction_error_deg'] = float(np.max(angle[moving])) if np.any(moving) else None
        report['max_zero_rate_residual_dps'] = float(np.max(np.linalg.norm(corrected[~moving],axis=1))) if np.any(~moving) else None
        if np.any(moving):
            unit = ref[moving]/ref_norm[moving,None]
            transverse = corrected[moving] - np.sum(corrected[moving]*unit,axis=1)[:,None]*unit
            report['max_cross_axis_dps'] = float(np.max(np.linalg.norm(transverse,axis=1)))
    return report


def evaluate(profile, kind, report, condition_number, design_cond=1.0, temperature_span=None):
    limits = profile['acceptance']
    gates = {
        'matrix_condition': {'value': condition_number, 'limit': limits['correction_condition_max']},
        'design_condition': {'value': design_cond, 'limit': limits['fit_design_condition_max']},
    }
    if kind == 'acc':
        gates.update({
            'rmse_vector_g': {'value': report['rmse_vector'], 'limit': limits['acc_vector_rmse_max_g']},
            'max_vector_g': {'value': report['max_vector_error'], 'limit': limits['acc_vector_max_error_g']},
            'max_direction_deg': {'value': report['max_direction_error_deg'], 'limit': limits['acc_angle_max_deg']},
            'max_norm_g': {'value': report['max_norm_error_g'], 'limit': limits['acc_norm_max_error_g']},
        })
    else:
        gates.update({
            'rmse_vector_dps': {'value': report['rmse_vector'], 'limit': limits['gyro_vector_rmse_max_dps']},
            'max_vector_dps': {'value': report['max_vector_error'], 'limit': limits['gyro_vector_max_error_dps']},
            'max_direction_deg': {'value': report['max_direction_error_deg'], 'limit': limits['gyro_direction_max_deg']},
            'max_cross_axis_dps': {'value': report['max_cross_axis_dps'], 'limit': limits['gyro_cross_axis_max_dps']},
        })
        if report.get('max_zero_rate_residual_dps') is not None:
            gates['max_zero_rate_dps'] = {'value': report['max_zero_rate_residual_dps'], 'limit': limits['gyro_zero_residual_max_dps']}
        else:
            gates['zero_rate_observed'] = {'value': None, 'limit': 'required', 'pass': False}
    if temperature_span is not None:
        gates['temperature_run_span_c'] = {'value':temperature_span,'limit':limits['temperature_run_span_max_c']}
    for item in gates.values():
        if 'pass' not in item:
            item['pass'] = bool(item['value'] is not None and np.isfinite(item['value']) and item['value'] <= item['limit'])
    metric_pass = all(x['pass'] for x in gates.values())
    approved = bool(profile['approved_for_production'])
    return {'gates':gates,'metric_pass':metric_pass, 'profile_id':profile['profile_id'],
            'approved_for_production': approved,
            'verdict': ('PASS' if approved else 'PILOT_PASS_NOT_RELEASED') if metric_pass else 'FAIL',
            'notice': '试运行阈值未批准，不得签发出厂合格结论' if not approved else '按已批准工艺规格判定'}


# 工艺安全闸门：与数值工况模块保持单一来源，防止不同目录同名模块冲突。
def validate_profile(profile):
    """纯配置校验：禁止把待核准的高速候选速率用于运动计划。"""
    from math import isfinite
    sensor = profile.get('sensor_config')
    if not isinstance(sensor, dict):
        raise ValueError('生产工艺缺少 sensor_config，禁止按默认量程继续标定')
    if sensor.get('chip') != 'ASM330LHHX':
        raise ValueError('当前生产配置仅针对 ASM330LHHX')
    # 候选量程仅用于产品配置规划。实际内参标定沿用正在运行的量程，
    # 不强制要求切换固件或在启动时得到MCU量程确认字段。
    acc = sensor.get('candidate_acc_fs_g', sensor.get('expected_acc_fs_g'))
    gyr = sensor.get('candidate_gyro_fs_dps', sensor.get('expected_gyro_fs_dps'))
    if acc is not None and acc not in (2, 4, 8, 16):
        raise ValueError('ACC候选量程配置非法')
    if gyr is not None and gyr not in (125, 250, 500, 1000, 2000, 4000):
        raise ValueError('GYRO候选量程配置非法')
    r = profile['rates']
    fits = list(r.get('fit_dps', ()))
    vals = list(r.get('verify_dps', ()))
    if not fits or not vals or len(set(fits)) != len(fits) or len(set(vals)) != len(vals):
        raise ValueError('速率配置不能为空且不能存在重复幅值')
    if set(fits) & set(vals):
        raise ValueError('拟合速率与独立验证速率不能重复')
    limit = float(r['maximum_command_rate_dps'])
    if not isfinite(limit) or not 0 < limit <= 10.0:
        raise ValueError('当前未认证的转台软件限速不可超过 10°/s')
    if not all(isinstance(x, (int, float)) and isfinite(x) and 0 < x <= limit for x in fits + vals):
        raise ValueError('正在执行的转速超出保守限速；请勿把高速候选工况移入活动速率表')
    proposed = r.get('proposed_after_turntable_approval', {})
    if proposed.get('enabled'):
        raise ValueError('高速候选方案只能在转台独立计量与安全认证后由工程人员另行发布，不接受直接 enabled=true')
    if float(profile['timing']['gyro_zero_seconds']) < 30:
        raise ValueError('静止零偏时长过短，当前试运行至少 30 秒')
    return True

ACC_VALID_FULL_SCALES = (2, 4, 8, 16)
GYRO_VALID_FULL_SCALES = (125, 250, 500, 1000, 2000, 4000)


def sensor_config_consistent(frozen, current):
    """仅比较影响数字→物理量换算的有效配置，不因确认标志升级而中断采样。

    读数一开始可能只有旧固件回退量程，任务中途得到MCU明确上报且数值一致，
    不代表量程发生变化；已经得到的ODR值若两边均有效则须保持相同。
    """
    for key in ('chip', 'acc_fs_g', 'gyro_fs_dps'):
        if frozen.get(key) != current.get(key):
            return False
    old_odr = int(frozen.get('odr_hz') or 0)
    new_odr = int(current.get('odr_hz') or 0)
    if old_odr > 0 and new_odr > 0 and old_odr != new_odr:
        return False
    return True


def restrict_unverified_release(result, sensor):
    """量程/ODR尚未确认时允许试验求参，但任何结果不得签发生产PASS。"""
    if sensor.get('verified_for_release') is True:
        return result
    notice = ('量程或ODR未得到MCU有效报告；使用本次任务的固定换算设置进行试运行标定。'
              '需确认实际寄存器配置后复核，禁止作为正式出厂PASS。')
    gates = [result.get('quality_gate', {})]
    validation = result.get('validation', {})
    for k in ('acc_gates', 'gyro_gates'):
        if isinstance(validation.get(k), dict):
            gates.append(validation[k])
    for gate in gates:
        gate['approved_for_production'] = False
        gate['configuration_verified_for_release'] = False
        gate['notice'] = notice
        if gate.get('metric_pass') is True:
            gate['verdict'] = 'PILOT_PASS_NOT_RELEASED'
    if result.get('quality_gate', {}).get('metric_pass') is True:
        result['status'] = 'PILOT_PASS_NOT_RELEASED'
    result['configuration_warning'] = notice
    combined = result.get('combined_calibration')
    if isinstance(combined, dict):
        combined['release_verdict'] = result.get('quality_gate', {}).get('verdict', 'FAIL')
        combined['warning'] = notice
    return result


def verify_sensor_config(profile, reading):
    """检查本次采集的*有效换算值*；未知固件量程仅作风险记录，不阻止试运行。

    原始数据在底层驱动中已经被换算为g/°/s，该过程可能用了旧固件的默认量程。
    不修改底层换算代码；这里固定本次有效数值，并附加是否由MCU确认的状态。
    若不确定真实量程，拟合数值仅可用于试验，不能正式放行。
    """
    c = profile['sensor_config']
    acc = int(reading.get('acc_fs', 0) or 0)
    gyro = int(reading.get('gyro_fs', 0) or 0)
    if acc not in ACC_VALID_FULL_SCALES or gyro not in GYRO_VALID_FULL_SCALES:
        raise ValueError('当前IMU数据换算量程非法，不能确定g/°/s单位；请检查原始数据。')
    odr = int(reading.get('data_odr', 0) or 0)
    if odr < 0:
        raise ValueError('MCU报告了非法的负ODR。')
    acc_ok = bool(reading.get('acc_fs_ever_valid'))
    gyro_ok = bool(reading.get('gyro_fs_ever_valid'))
    odr_ok = odr > 0
    verified = acc_ok and gyro_ok and odr_ok
    return {
        'chip': c['chip'], 'acc_fs_g': acc, 'gyro_fs_dps': gyro, 'odr_hz': odr,
        'acc_full_scale_mcu_verified': acc_ok,
        'gyro_full_scale_mcu_verified': gyro_ok,
        'odr_mcu_verified': odr_ok,
        'verified_for_release': verified,
        'source': ('MCU_REPORTED' if acc_ok and gyro_ok else 'EFFECTIVE_FALLBACK_UNVERIFIED'),
        'note': ('MCU确认有效' if verified else
                 'MCU量程或ODR缺少可信报告；显示数值可能是底层默认回退，仅供开发标定；运行时必须保持数值一致'),
    }
