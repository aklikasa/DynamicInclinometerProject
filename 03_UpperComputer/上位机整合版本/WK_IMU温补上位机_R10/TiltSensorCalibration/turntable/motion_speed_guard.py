"""Turntable command-input validation and feedback-value validity helpers.

No global +/-10 deg/s software cap or application-side feedback speed ceiling
is applied. Hardware overspeed, drive-fault, limit and emergency-stop states
remain the responsibility of the turntable controller/status interface.
This module is not a functional-safety-rated interlock.
"""
import math

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


def feedback_invalid(inner_speed, outer_speed):
    """仅判断转台速度反馈是否为有限数值；不限制反馈速度幅值。"""
    try:
        values = [float(inner_speed), float(outer_speed)]
        return not all(math.isfinite(v) for v in values)
    except (TypeError, ValueError, OverflowError):
        return True
