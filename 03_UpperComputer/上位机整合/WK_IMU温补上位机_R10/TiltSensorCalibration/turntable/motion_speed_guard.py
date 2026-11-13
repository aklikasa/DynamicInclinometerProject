"""Turntable motion validation and task-scoped feedback guard.

No global +/-10 deg/s software cap is applied. The optional feedback ceiling is
used only during an explicitly acknowledged automatic GYRO high-speed trial.
This module is not a functional-safety-rated interlock.
"""
import math

MAX_AUTO_GYRO_SPEED_DPS = 60.0
_AUTO_GYRO_HIGH_SPEED_LIMIT_DPS = None


def set_auto_gyro_high_speed_limit(limit):
    """Set/clear the temporary feedback ceiling for an acknowledged GYRO task.

    None clears the task-scoped ceiling; manual turntable operation has no
    application-wide +/-10 deg/s feedback cap.
    """
    global _AUTO_GYRO_HIGH_SPEED_LIMIT_DPS
    if limit is None:
        _AUTO_GYRO_HIGH_SPEED_LIMIT_DPS = None
        return
    value = float(limit)
    if not math.isfinite(value) or not 10.0 < value <= MAX_AUTO_GYRO_SPEED_DPS:
        raise ValueError('自动GYRO反馈监控阈值必须大于10且不超过60°/s')
    _AUTO_GYRO_HIGH_SPEED_LIMIT_DPS = value


def target_speed_allowed(speed):
    """Return True for any finite, non-zero requested speed; no fixed 10 dps cap."""
    try:
        value = float(speed)
        return math.isfinite(value) and abs(value) > 0.0
    except (TypeError, ValueError, OverflowError):
        return False


def sway_peak_speed(amplitude_deg, frequency_hz):
    a, f = float(amplitude_deg), float(frequency_hz)
    if not all(map(math.isfinite, (a, f))) or a <= 0 or f <= 0:
        raise ValueError("摇摆幅度、频率必须是正的有限数值")
    return 2 * math.pi * a * f


def feedback_overspeed(inner_speed, outer_speed, max_abs_speed_dps=None):
    """Check invalid feedback or an explicitly supplied/task-scoped ceiling.

    With no active task ceiling, any finite speed is accepted; NaN/Inf remains
    a feedback fault and is never treated as a valid measurement.
    """
    try:
        if max_abs_speed_dps is not None:
            limit = float(max_abs_speed_dps)
        else:
            limit = _AUTO_GYRO_HIGH_SPEED_LIMIT_DPS
        values = [float(inner_speed), float(outer_speed)]
        if not all(math.isfinite(v) for v in values):
            return True
        if limit is None:
            return False
        if not math.isfinite(float(limit)) or float(limit) <= 0:
            return True
        return any(abs(v) > float(limit) for v in values)
    except (TypeError, ValueError, OverflowError):
        return True
