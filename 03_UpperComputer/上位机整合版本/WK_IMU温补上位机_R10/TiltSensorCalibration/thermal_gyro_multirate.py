# -*- coding: utf-8 -*-
"""2FDT600WK 温补专用 Gyro 多速率工况与控制参数（纯函数）。

不修改常温标定配置/算法，不发送硬件命令。
所有高转速动态工况需先核实温箱内线缆、行程、设备实际速率与硬件急停。
"""
import math
import re

FIT_RATES_DPS = (1.0, 5.0, 15.0, 30.0, 60.0)
VERIFY_RATES_DPS = (1.5, 3.5, 10.0, 20.0, 45.0)
PILOT_FIT_RATES_DPS = (1.0, 5.0, 15.0, 30.0)
PILOT_VERIFY_RATES_DPS = (1.5, 3.5, 10.0, 20.0, 25.0)
# Prefer more calibration/holdout points in the typical slow-tilt operating band.
# This is a preset, not an immutable speed plan. All rates run ± on all axes.
LOW_SPEED_FIT_RATES_DPS = (1.0, 2.0, 3.0, 5.0, 10.0, 20.0, 30.0)
LOW_SPEED_VERIFY_RATES_DPS = (1.5, 2.5, 4.0, 7.5, 15.0, 25.0)
MAX_WK_INNER_DPS = 200.0
MAX_WK_OUTER_DPS = 100.0


# GUI custom速率的允许范围是本次研发试验包络，不是WK厂家全部额定速率。
# 大于60°/s的研究必须单独进行安全评审，不能通过自由输入绕过。
MAX_THERMAL_EXPERIMENT_DPS = 60.0
MAX_RATE_POINTS_PER_LIST = 20


def parse_rate_list(text, label='GYRO角速度'):
    """Parse positive magnitude speeds; every configured speed runs both directions.

    The caller must not pass signed speed commands or map ± prefixes to motor
    direction. Motor direction remains controlled by the existing step planner.
    """
    tokens = [part for part in re.split(r'[,，;；\s]+', str(text).strip()) if part]
    if not tokens:
        raise ValueError(f'{label}不能为空；请输入正数，例如 1, 5, 15, 30')
    if len(tokens) > MAX_RATE_POINTS_PER_LIST:
        raise ValueError(f'{label}最多允许{MAX_RATE_POINTS_PER_LIST}个速率，避免长时间无人值守旋转')
    try:
        rates = tuple(float(token) for token in tokens)
    except ValueError as exc:
        raise ValueError(f'{label}格式错误：只能填写用逗号分隔的正数幅值（自动执行±正反转）') from exc
    if any(not math.isfinite(rate) or rate < 0.1 or rate > MAX_THERMAL_EXPERIMENT_DPS for rate in rates):
        raise ValueError(f'{label}每项必须在0.1～{MAX_THERMAL_EXPERIMENT_DPS:g}°/s内；超出需单独审核连续旋转安全')
    if len({round(rate, 6) for rate in rates}) != len(rates):
        raise ValueError(f'{label}存在重复速率')
    return tuple(sorted(rates))


def validate_rate_lists(fit_rates, verify_rates):
    """Validate selected fit/holdout magnitudes; no overlap or hidden replacements."""
    fit = parse_rate_list(','.join(str(x) for x in fit_rates), '拟合速率')
    verify = parse_rate_list(','.join(str(x) for x in verify_rates), '独立验证速率')
    if len(fit) < 2:
        raise ValueError('GYRO多速率拟合至少需要2个不同的正向速率幅值')
    if {round(x, 6) for x in fit} & {round(x, 6) for x in verify}:
        raise ValueError('GYRO拟合速率与独立验证速率不能重复，以免测试数据泄漏')
    return fit, verify


def configure_thermal_gyro_profile(profile, high_speed=True, *, fit_rates=None, verify_rates=None):
    """Modify only a thermal-run profile copy. Ambient settings remain untouched.

    The optional validated rate lists are persisted by the thermal UI and used
    by gyro_fit_steps / gyro_verify_steps; presets remain backwards compatible.
    """
    if (fit_rates is None) != (verify_rates is None):
        raise ValueError('自定义拟合速率与验证速率必须同时提供')
    if fit_rates is not None:
        fit, verify = validate_rate_lists(fit_rates, verify_rates)
    else:
        fit, verify = validate_rate_lists(
            FIT_RATES_DPS if high_speed else PILOT_FIT_RATES_DPS,
            VERIFY_RATES_DPS if high_speed else PILOT_VERIFY_RATES_DPS)
    rates = profile['rates']
    rates['fit_dps'] = list(fit)
    rates['verify_dps'] = list(verify)
    rates['maximum_command_rate_dps'] = max(fit + verify)
    return profile


def wk_signed_velocity(rate_dps, acceleration_dps2, axis):
    """按厂家速率指令格式：0顺时针、1逆时针，速度字段仅填正幅值。"""
    rate = float(rate_dps)
    if not math.isfinite(rate) or rate == 0:
        raise ValueError('目标角速度必须为非零有限值')
    if axis not in ('inner', 'outer'):
        raise ValueError('未知WK轴名')
    maximum = MAX_WK_INNER_DPS if axis == 'inner' else MAX_WK_OUTER_DPS
    if abs(rate) > maximum:
        raise ValueError(f'{axis}目标速率{rate:g}°/s超过转台额定范围±{maximum:g}°/s')
    if type(acceleration_dps2) is not int:
        raise ValueError('WK加速度必须为整数')
    accel_max = 100 if axis == 'inner' else 50
    if not 1 <= acceleration_dps2 <= accel_max:
        raise ValueError(f'{axis}加速度须为1至{accel_max}°/s²')
    return (0 if rate > 0 else 1), acceleration_dps2, abs(rate)


def conservative_sweep_degrees(rate_dps, acceleration_dps2, sampling_seconds, stabilization_seconds=1.0, margin_seconds=0.5):
    """单段行程预算：加速+采样+稳定+缓冲+减速（保守估算，不是硬件保护）。"""
    speed = abs(float(rate_dps))
    accel = float(acceleration_dps2)
    duration = float(sampling_seconds)
    if not all(math.isfinite(x) for x in (speed, accel, duration)) or speed <= 0 or accel <= 0 or duration <= 0:
        raise ValueError('行程估算输入无效')
    return speed*speed/accel + speed*(duration + stabilization_seconds + margin_seconds)


def signed_wrapped_increment(new_deg, old_deg):
    """连续编码器反馈角度差分；调用方须保证采样间隔足够短而不会漏一圈。"""
    if not (math.isfinite(float(new_deg)) and math.isfinite(float(old_deg))):
        raise ValueError('转台角度反馈无效')
    return (float(new_deg) - float(old_deg) + 180.0) % 360.0 - 180.0
