# -*- coding: utf-8 -*-
"""常温IMU内参三模型比较；纯数值模块，不连接转台、不依赖Qt。

A: ACC轴对齐椭球(仅利用|g|=1)，GYRO参考速度的三轴独立线性校准。
   A保留传感器名义轴方向，不能估计PCB安装转角。
B: measured = diag(s) @ R.T @ reference_P + bias, R属于SO(3)。
C: measured = A @ reference_P + bias，原工作台完整12参数算法。
三个模型全部共享拟合、验证工况；仅独立验证集参与对比排名。
"""
import math
import numpy as np

from production_calibration import residual_statistics, evaluate, sensor_axis_invariants

MODEL_NAMES = {
    'A': 'A：零偏+三轴比例（ACC轴对齐椭球）',
    'B': 'B：零偏+三轴比例+安装旋转（9参数）',
    'C': 'C：完整3×3仿射校正（12参数，原方案）',
}


def _validate_points(refs, measured):
    x = np.asarray(refs, dtype=float)
    y = np.asarray(measured, dtype=float)
    if x.ndim != 2 or y.shape != x.shape or x.shape[1] != 3 or len(x) < 9:
        raise ValueError('拟合数据至少9组三维向量，且参考与测量必须一一对应')
    if not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError('拟合数据含无穷值或NaN')
    design = np.column_stack((x, np.ones(len(x))))
    if np.linalg.matrix_rank(design) < 4:
        raise ValueError('参考矢量秩不足，无法可靠估计三轴零偏与耦合')
    return x, y, float(np.linalg.cond(design))


def _full_fit(refs, raw):
    from numpy.linalg import lstsq
    design = np.column_stack((refs, np.ones(len(refs))))
    beta, _, _, _ = lstsq(design, raw, rcond=None)
    forward = beta[:3].T
    bias = beta[3]
    return forward, bias


def _rotation_from_vector(rotvec):
    angle = np.linalg.norm(rotvec)
    if angle < 1e-12:
        return np.eye(3)
    axis = rotvec / angle
    skew = np.array([[0., -axis[2], axis[1]], [axis[2], 0., -axis[0]], [-axis[1], axis[0], 0.]])
    return np.eye(3) + math.sin(angle) * skew + (1-math.cos(angle)) * (skew @ skew)


def _rotation_vector_from_matrix(matrix):
    # Avoid discontinuities in the 180 degree case by extracting the quaternion.
    r = np.asarray(matrix, float)
    angle = float(np.arccos(np.clip((np.trace(r)-1)/2, -1, 1)))
    if angle < 1e-9:
        return np.zeros(3)
    if abs(math.pi-angle) < 1e-5:
        vals, vecs = np.linalg.eigh((r + np.eye(3)) / 2)
        axis = vecs[:, np.argmax(vals)]
        return axis * angle
    return angle * np.array([r[2,1]-r[1,2],r[0,2]-r[2,0],r[1,0]-r[0,1]]) / (2*math.sin(angle))


def _lm_fit(fun, params, max_iter=130):
    """Small deterministic damped Gauss–Newton optimizer (no scipy requirement)."""
    p = np.asarray(params, float).copy()
    lam = 1e-3
    r = np.asarray(fun(p), float)
    if not np.isfinite(r).all():
        raise ValueError('迭代拟合初始残差无效')
    cost = float(r @ r)
    for _ in range(max_iter):
        jac = np.empty((len(r), len(p)))
        for j in range(len(p)):
            delta = 1e-5 * max(1., abs(p[j]))
            probe = p.copy(); probe[j] += delta
            low = p.copy(); low[j] -= delta
            jac[:, j] = (fun(probe) - fun(low)) / (2 * delta)
        normal = jac.T @ jac
        grad = jac.T @ r
        if np.max(np.abs(grad)) < 1e-11:
            break
        diag = np.maximum(np.diag(normal), 1e-8)
        try:
            step = np.linalg.solve(normal + lam * np.diag(diag), -grad)
        except np.linalg.LinAlgError:
            raise ValueError('非线性拟合正规方程不可解')
        proposal = p + step
        trial = np.asarray(fun(proposal), float)
        next_cost = float(trial @ trial) if np.isfinite(trial).all() else float('inf')
        if next_cost < cost:
            p, r, cost = proposal, trial, next_cost
            lam = max(lam / 3., 1e-10)
            if np.linalg.norm(step) < 1e-9 * (1 + np.linalg.norm(p)):
                break
        else:
            lam = min(lam * 5, 1e12)
            if lam > 1e11:
                break
    return p


def _fit_acc_ellipsoid(raw):
    """Fit (y-b).T diag(s^-2) (y-b) = 1, positive s. No cross-axis mixing."""
    y = np.asarray(raw, float)
    if len(y) < 10:
        raise ValueError('ACC简化椭球拟合至少需要10个不同的姿态')
    # Initial bias from extrema; ellipsoid (axis-aligned) refined by norm-only LS.
    bias0 = (np.max(y, axis=0) + np.min(y, axis=0)) / 2
    gains0 = np.maximum((np.max(y, axis=0) - np.min(y, axis=0))/2, .05)
    initial = np.r_[bias0, np.log(gains0)]
    def residual(p):
        bias, gain = p[:3], np.exp(np.clip(p[3:], -8., 8.))
        return np.linalg.norm((y-bias)/gain, axis=1) - 1.
    p = _lm_fit(residual, initial, max_iter=180)
    gains = np.exp(np.clip(p[3:],-8,8))
    normalized = (y-p[:3])/gains
    lengths = np.maximum(np.linalg.norm(normalized, axis=1), 1e-12)
    # 雅可比列：对零偏和log(比例因子)的偏导，保证6个参数可被观测。
    jac = np.column_stack((-normalized / (lengths[:, None]*gains),
                           -normalized**2 / lengths[:, None]))
    singular = np.linalg.svd(jac, compute_uv=False)
    if (np.max(np.abs(residual(p))) > .3 or np.min(gains) < .1 or np.max(gains) > 10
            or singular[-1] < 1e-8 or singular[0]/singular[-1] > 1e5):
        raise ValueError('轴对齐椭球拟合病态或不可唯一辨识；检查姿态覆盖与轴间耦合')
    return np.diag(gains), p[:3]


def _fit_diag_gyro(refs, raw):
    gains = np.empty(3)
    bias = np.empty(3)
    for j in range(3):
        beta, _, _, _ = np.linalg.lstsq(np.column_stack((refs[:, j], np.ones(len(refs)))), raw[:, j], rcond=None)
        gains[j], bias[j] = beta
    if np.min(gains) < .1 or np.max(gains) > 10:
        raise ValueError('GYRO A方案求出的比例因子非正或超出允许范围')
    return np.diag(gains), bias


def _fit_diagonal_rotation(refs, raw):
    init_forward, init_bias = _full_fit(refs, raw)
    if np.linalg.det(init_forward) <= 0:
        raise ValueError('B方案要求正向右手坐标变换；检测到负行列式，请核查轴符号定义')
    gains = np.linalg.norm(init_forward, axis=1)
    normalized = init_forward / gains[:,None]
    u, _, vh = np.linalg.svd(normalized)
    orient = u @ vh
    if np.linalg.det(orient) < 0:
        raise ValueError('B方案初始方向不是右手旋转')
    initial = np.r_[init_bias, np.log(np.maximum(gains,1e-3)), _rotation_vector_from_matrix(orient.T)]
    def residual(p):
        d = np.exp(np.clip(p[3:6], -8, 8))
        rot = _rotation_from_vector(p[6:9])
        # forward = D @ R.T; row data (N,3) -> (N,3)
        return (refs @ rot @ np.diag(d) + p[:3] - raw).ravel()
    p = _lm_fit(residual, initial)
    gains = np.exp(np.clip(p[3:6], -8,8))
    if np.min(gains) < .1 or np.max(gains) > 10:
        raise ValueError('B方案比例因子超出合理范围')
    rotation = _rotation_from_vector(p[6:9])
    return np.diag(gains) @ rotation.T, p[:3], rotation


def fit_model(kind, model, refs, raw):
    """Fit one model, returning forward, bias and raw-to-P correction arrays."""
    if kind not in ('acc', 'gyro') or model not in MODEL_NAMES:
        raise ValueError('未知模型或传感器')
    refs, raw, design_condition = _validate_points(refs, raw)
    if model == 'C' and len(refs) < 12:
        raise ValueError('原C方案完整12参数拟合至少需要12组参考向量')
    if model == 'A':
        forward, bias = _fit_acc_ellipsoid(raw) if kind == 'acc' else _fit_diag_gyro(refs, raw)
        rotation = None
    elif model == 'B':
        forward, bias, rotation = _fit_diagonal_rotation(refs, raw)
    else:
        forward, bias = _full_fit(refs, raw)
        rotation = None
    matrix_condition = float(np.linalg.cond(forward))
    if (not np.isfinite(forward).all() or not np.isfinite(bias).all()
            or abs(float(np.linalg.det(forward))) < 1e-10
            or not np.isfinite(matrix_condition) or matrix_condition > 1e5):
        raise ValueError('标定矩阵奇异、病态或者包含无效数字')
    correction = np.linalg.inv(forward)
    corrected = (raw-bias) @ correction.T
    residual = corrected - refs
    return {
        'model_id':model, 'model_name':MODEL_NAMES[model],
        'bias':bias, 'forward_matrix':forward, 'correction_matrix':correction,
        'rotation_matrix':rotation,
        'condition_number':matrix_condition, 'design_condition':design_condition,
        'fit_vector_rmse':float(np.sqrt(np.mean(np.sum(residual**2,axis=1)))),
        'fit_vector_max':float(np.max(np.linalg.norm(residual,axis=1))),
        'axis_sensitivity':np.linalg.norm(forward,axis=1).tolist(),
        'model_note': ('A方案ACC仅校正零偏与椭球模长，未求传感器安装方向；方向误差按名义轴系评估。'
                       if model == 'A' and kind == 'acc' else
                       'A方案GYRO根据各轴参考角速度线性回归，未校正安装方向。' if model == 'A' else
                       'B方案只有三轴正比例因子+刚体SO(3)旋转，不拟合额外交叉轴形变。' if model == 'B' else
                       '原工作台完整12参数仿射标定。'),
    }


def score_model(kind, model, fit_rows, validation_rows, profile):
    """fit_rows and validation_rows are [dict(reference, measured, ...)] with different steps."""
    if not fit_rows or not validation_rows:
        raise ValueError('独立拟合和验证工况不能为空')
    ids_fit = {x['step_id'] for x in fit_rows}
    ids_validation = {x['step_id'] for x in validation_rows}
    if ids_fit & ids_validation:
        raise ValueError('拟合与验证工况编号发生重叠，不允许泄漏')
    refs = [x['reference'] for x in fit_rows]
    measured = [x['measured'] for x in fit_rows]
    fit = fit_model(kind, model, refs, measured)
    check = residual_statistics([x['reference'] for x in validation_rows],
                                [x['measured'] for x in validation_rows],
                                fit['bias'], fit['correction_matrix'], kind)
    temperatures = [x.get('temperature_mean_c') for x in fit_rows+validation_rows]
    temperatures = [float(t) for t in temperatures if t is not None and np.isfinite(t)]
    span = max(temperatures)-min(temperatures) if temperatures else None
    decision = evaluate(profile, kind, check, fit['condition_number'], fit['design_condition'], span)
    return {'model_id':model, 'model_name':MODEL_NAMES[model], 'fit':fit, 'independent_validation':check,
            'quality_gate':decision, 'validation_count':len(validation_rows)}


def compare_models(kind, fit_rows, validation_rows, profile):
    """Return independent model results and a cautious *candidate*, not a production release."""
    models, errors = {}, {}
    for code in MODEL_NAMES:
        try:
            models[code] = score_model(kind, code, fit_rows, validation_rows, profile)
        except (ValueError, np.linalg.LinAlgError, FloatingPointError) as exc:
            errors[code] = str(exc)
    # Display best independent vector-RMSE with gate satisfied, but do not auto-release any model.
    valid = [(code, val) for code,val in models.items()
             if val['quality_gate']['metric_pass'] is True]
    valid.sort(key=lambda pair:(pair[1]['independent_validation']['rmse_vector'], 'ABC'.index(pair[0])))
    candidate = valid[0][0] if valid else None
    return {'kind':kind, 'models':models, 'errors':errors,
            'candidate_model':candidate,
            'selection_rule':'先满足独立验证质量门限，再按验证矢量RMSE排序；只是候选，需跨板/复装及不确定度验证。',
            'note':'A/B/C对同一拟合数据和不同工况的独立验证数据进行比较；A方案不估安装旋转；未进行新的全温/全量程认证。'}


def serialize(obj):
    """Turn internal numpy arrays into JSON-compatible values."""
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, (np.floating, np.integer, np.bool_)):
        return obj.item()
    if isinstance(obj, dict):
        return {str(k):serialize(v) for k,v in obj.items()}
    if isinstance(obj, (tuple,list)):
        return [serialize(x) for x in obj]
    return obj
