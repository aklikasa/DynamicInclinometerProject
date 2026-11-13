# -*- coding: utf-8 -*-
"""R10 + GYRO60 集成离线回归；不启动 Qt、不连接串口、不驱动转台。"""
import ast
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import production_calibration as pc
sys.path.insert(0, str(ROOT / 'turntable'))
from calibration_artifact_paths import (
    ambient_root, thermal_root, ambient_filename, thermal_filename
)
from motion_speed_guard import feedback_overspeed, set_auto_gyro_high_speed_limit


def test_profile_and_98_steps():
    disk = pc.load_profile(str(ROOT))
    assert disk['rates']['fit_dps'] == [1.0, 2.0, 5.0]
    assert disk['rates']['verify_dps'] == [1.5, 3.5]
    assert disk['rates']['maximum_command_rate_dps'] == 10.0
    fit = list(pc.GYRO_FULL60_FIT_DPS)
    verify = list(pc.GYRO_FULL60_VERIFY_DPS)
    assert fit == [1.0, 2.0, 5.0, 10.0, 15.0, 20.0, 30.0, 45.0, 60.0]
    assert verify == [3.0, 7.5, 12.0, 25.0, 35.0, 50.0, 55.0]
    assert not set(fit) & set(verify)

    try:
        pc.profile_with_gyro_rates(disk, fit, verify)
    except ValueError:
        pass
    else:
        raise AssertionError('未人工授权的高速工况必须拒绝')

    profile = pc.profile_with_gyro_rates(
        disk, fit, verify, high_speed_acknowledged=True, acceleration_dps2=10.0
    )
    assert profile['rates']['maximum_command_rate_dps'] == 60.0
    assert profile['rates']['high_speed_trial_acknowledged'] is True
    assert profile['rates']['velocity_accel_dps2'] == 10.0
    assert profile['approved_for_production'] is False
    assert disk['rates']['maximum_command_rate_dps'] == 10.0
    fit_steps = pc.gyro_fit_steps(profile)
    verify_steps = pc.gyro_verify_steps(profile)
    assert len(fit_steps) == 55 and len(verify_steps) == 43
    assert len({s['step_id'] for s in fit_steps + verify_steps}) == 98
    assert max(abs(s['target_rate_dps']) for s in fit_steps + verify_steps if s['mode'] == 'rate') == 60.0

    for bad_accel in (0.5, 31.0):
        try:
            pc.profile_with_gyro_rates(
                disk, fit, verify, high_speed_acknowledged=True, acceleration_dps2=bad_accel
            )
        except ValueError:
            pass
        else:
            raise AssertionError('非法加速度未被拒绝')

    # 固定速率覆盖X/Y/Z正反转，并保持仿射模型设计矩阵满秩。
    source = ROOT / 'form' / 'form_imu_calibration.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    top = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in (
        '_rotation_x', '_rotation_y', '_rotation_z', '_platform_rotation',
        '_platform_angular_rate', '_fit_affine_reference'
    )]
    ns = {'np': np}
    exec(compile(ast.fix_missing_locations(ast.Module(body=top, type_ignores=[])), str(source), 'exec'), ns)

    def ref_for(step):
        if step['mode'] == 'static':
            return np.zeros(3)
        return ns['_platform_angular_rate'](
            step['inner_deg'], step['outer_deg'],
            step['target_rate_dps'] if step['rotation_axis'] == 'inner' else 0.0,
            step['target_rate_dps'] if step['rotation_axis'] == 'outer' else 0.0,
            'outer_x_inner_z'
        )

    refs = np.asarray([ref_for(s) for s in fit_steps])
    assert np.linalg.matrix_rank(np.column_stack([refs, np.ones(len(refs))])) == 4

    matrix = np.array([[0.94, 0.015, -0.01], [-0.02, 1.035, 0.008], [0.012, -0.018, 0.975]])
    bias = np.array([0.12, -0.15, 0.08])
    raw = refs @ matrix.T + bias
    solved = ns['_fit_affine_reference'](refs, raw, 'deg/s', 'deg/s')
    assert np.max(np.abs(solved['forward_matrix'] - matrix)) < 1e-9
    assert np.max(np.abs(solved['bias'] - bias)) < 1e-9

    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'FormImuCalibration')
    fit_method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_fit_gyroscope_result')
    stub = ast.ClassDef(name='FitStub', bases=[], keywords=[], decorator_list=[], body=[fit_method])
    fit_ns = {
        'np': np,
        'residual_statistics': pc.residual_statistics,
        'evaluate': pc.evaluate,
        'sensor_axis_invariants': pc.sensor_axis_invariants,
        '_fit_affine_reference': ns['_fit_affine_reference'],
        '_now_iso': lambda: '2026-11-13T09:00:00+08:00',
    }
    exec(compile(ast.fix_missing_locations(ast.Module(body=[stub], type_ignores=[])), str(source), 'exec'), fit_ns)
    obj = fit_ns['FitStub']()
    obj.run_id = 'SYNTHETIC_GYRO60'
    val_steps = verify_steps

    def row(step):
        v = ref_for(step)
        return {**step, 'reference': v.tolist(), 'measured': (matrix @ v + bias).tolist(),
                'temperature_mean_c': 25.0}

    result = obj._fit_gyroscope_result({
        'gyro_fit_samples': [row(s) for s in fit_steps],
        'gyro_validation_samples': [row(s) for s in val_steps],
        'quality_profile': profile,
        'device_serial': 'DTS_TEST',
        'axis_model': 'outer_x_inner_z',
        'gravity_sign': 1,
    })
    assert result['quality_gate']['metric_pass'] is True, result['quality_gate']
    assert len(result['fit_measurements']) == 55
    assert len(result['validation_measurements']) == 43
    assert set(result['tested_rate_points_dps']) == set(fit + verify)


def test_warn_only_is_isolated_and_other_checks_remain():
    disk = pc.load_profile(str(ROOT))
    profile = pc.profile_with_gyro_rates(
        disk, pc.GYRO_FULL60_FIT_DPS, pc.GYRO_FULL60_VERIFY_DPS,
        high_speed_acknowledged=True, acceleration_dps2=10.0
    )
    rng = np.random.default_rng(5)
    frames = []
    for i in range(220):
        frames.append({
            'acc': [0.03, 0.0, 1.0],
            'gyro': [4 + rng.normal(0, 0.4), -6 + rng.normal(0, 0.4), 116 + rng.normal(0, 0.76)],
            'inner_rate_dps': 15 + rng.normal(0, 0.001),
            'outer_rate_dps': 0.0,
            'inner_deg': 200 + i * 0.1,
            'outer_deg': 0.0,
            'temp_c': 27.0,
            'gyro_raw_samples': 16, 'gyro_accepted_samples': 16,
            'acc_raw_samples': 16, 'acc_accepted_samples': 16,
        })
    try:
        pc.robust_segment(frames, 'rate', profile, target_rate=15.0, axis='inner')
    except ValueError as exc:
        assert '动态GYRO抖动' in str(exc)
    else:
        raise AssertionError('默认严格模式应拒绝动态GYRO标准差超限')

    profile['quality']['rate_gyro_std_policy'] = 'warn_only'
    pc.validate_profile(profile)
    stats = pc.robust_segment(frames, 'rate', profile, target_rate=15.0, axis='inner')
    assert stats['accepted_frames'] >= 200
    assert len(stats['quality_warnings']) == 1
    assert stats['gyro_std_dps'][2] > 0.55

    wrong_speed = [dict(f, inner_rate_dps=10.0) for f in frames]
    try:
        pc.robust_segment(wrong_speed, 'rate', profile, target_rate=15.0, axis='inner')
    except ValueError as exc:
        assert '偏离目标' in str(exc)
    else:
        raise AssertionError('warn-only不得跳过转台参考速度误差')

    hot = [dict(f, temp_c=60.0) for f in frames]
    try:
        pc.robust_segment(hot, 'rate', profile, target_rate=15.0, axis='inner')
    except ValueError as exc:
        assert '温度' in str(exc)
    else:
        raise AssertionError('warn-only不得跳过温度质量门槛')

    invalid = dict(profile)
    invalid['approved_for_production'] = True
    try:
        pc.validate_profile(invalid)
    except ValueError:
        pass
    else:
        raise AssertionError('warn-only/高速试验配置不得被标记为生产放行')


def test_ui_and_turntable_guard_integration():
    source = ROOT / 'form' / 'form_imu_calibration.py'
    src = source.read_text(encoding='utf-8')
    tree = ast.parse(src)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'FormImuCalibration')
    methods = {n.name: ast.get_source_segment(src, n) for n in cls.body if isinstance(n, ast.FunctionDef)}
    assert 'self.edit_gyro_fit_rates.setReadOnly(True)' in src
    assert 'self.edit_gyro_verify_rates.setReadOnly(True)' in src
    assert 'GYRO_FULL60_FIT_DPS' in methods['_load_ui_gyro_profile']
    assert 'GYRO_FULL60_VERIFY_DPS' in methods['_load_ui_gyro_profile']
    assert 'self.check_gyro_high_speed.isChecked()' in methods['_load_ui_gyro_profile']
    for name in ('_start_gyro_auto', '_start_gyro_compare', '_start_alignment_auto', '_generate_gyro_plan'):
        assert 'self._load_ui_gyro_profile(' in methods[name], name
    assert 'profile_override=profile' in methods['_start_gyro_auto']
    assert 'profile_override=profile' in methods['_start_gyro_compare']
    assert 'profile_override=profile' in methods['_start_alignment_auto']
    assert 'copy.deepcopy(profile_override)' in methods['_start_auto_task']
    assert 'expected_steps' in methods['_start_auto_task']
    assert 'self.check_gyro_high_speed.setChecked(False)' in methods['_finalize_auto_task']
    assert 'set_auto_gyro_high_speed_limit(None)' in methods['_finalize_auto_task']
    assert 'set_auto_gyro_high_speed_limit(None)' in methods['_request_auto_abort']
    assert 'set_auto_gyro_high_speed_limit(None)' in methods['_start_auto_task']
    tick_src = methods['_auto_task_tick']
    assert 'monitor_limit = min(task_cap, max(abs(speed) * 1.10, abs(speed) + 0.5))' in tick_src
    assert 'set_auto_gyro_high_speed_limit(' in tick_src
    assert 'set_auto_gyro_high_speed_limit(None)' in tick_src
    assert 'experimental_dynamic_std_warn_only' in methods['_save_calibration_result']
    assert 'ambient_root' in methods['_save_calibration_result']

    # Manual operation has no global +/-10°/s feedback cap.
    assert feedback_overspeed(10.01, 0.0) is False
    assert feedback_overspeed(120.0, -95.0) is False
    set_auto_gyro_high_speed_limit(60.0)
    assert feedback_overspeed(59.9, 0.0) is False
    assert feedback_overspeed(60.01, 0.0) is True
    set_auto_gyro_high_speed_limit(None)
    assert feedback_overspeed(10.01, 0.0) is False
    for invalid_limit in (10.0, 60.01, float('nan')):
        try:
            set_auto_gyro_high_speed_limit(invalid_limit)
        except ValueError:
            pass
        else:
            raise AssertionError('临时自动高速授权不得低于/超过允许边界或使用NaN')

    # 转台控制页不再设置全局±10°/s命令/反馈上限；保留任务临时阈值和反馈有效性检查。
    tt_source = ROOT / 'form' / 'form_turntable_ctrl.py'
    tt_src = tt_source.read_text(encoding='utf-8')
    assert 'if not feedback_overspeed(inn, out):' in tt_src
    assert 'MAX_ABS_SPEED_DPS' not in tt_src
    assert 'target_speed_allowed(speed)' in tt_src  # 仅校验有限非零输入，不含固定速率上限
    imu_src = source.read_text(encoding='utf-8')
    assert 'if not math.isfinite(speed) or speed <= 0:' in imu_src  # 自动位置运动不再受10°/s限幅
    assert 'if abs(speed) > GYRO_HIGH_SPEED_ACK_THRESHOLD_DPS:' not in imu_src  # 手动速率入口无10°/s限幅


def test_dts_ambient_thermal_file_naming_remains_intact():
    assert ambient_root('/tmp/out', 'DTS672516').name == 'AMBIENT_常温'
    assert thermal_root('/tmp/out', 'DTS672516').name == 'THERMAL_全温补'
    assert ambient_filename('DTS672516', 'gyro') == 'DTS672516_GYRO_AMBIENT.json'
    assert thermal_filename('DTS672516', 'gyro', 'selected') == 'DTS672516_GYRO_THERMAL_SELECTED_CANDIDATE.json'
    assert thermal_filename('DTS672516', artifact='selection') == 'DTS672516_THERMAL_MODEL_SELECTION.json'


if __name__ == '__main__':
    test_profile_and_98_steps()
    test_warn_only_is_isolated_and_other_checks_remain()
    test_ui_and_turntable_guard_integration()
    test_dts_ambient_thermal_file_naming_remains_intact()
    print('PASS: R10 + GYRO60 98工况、试验质控隔离、取消全局±10°/s限速并保留自动GYRO任务反馈阈值、DTS文件命名（纯离线）')
