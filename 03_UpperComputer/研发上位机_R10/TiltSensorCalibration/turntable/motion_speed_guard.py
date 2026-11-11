"""Workstation software motion limit (NOT a functional-safety rated interlock)."""
import math

MAX_ABS_SPEED_DPS = 10.0

def target_speed_allowed(speed):
    try:
        value = float(speed)
        return math.isfinite(value) and 0 < abs(value) <= MAX_ABS_SPEED_DPS
    except (TypeError, ValueError, OverflowError):
        return False

def sway_peak_speed(amplitude_deg, frequency_hz):
    a, f = float(amplitude_deg), float(frequency_hz)
    if not all(map(math.isfinite, (a, f))) or a <= 0 or f <= 0:
        raise ValueError("摇摆幅度、频率必须是正的有限数值")
    return 2 * math.pi * a * f

def feedback_overspeed(inner_speed, outer_speed):
    return any(not math.isfinite(float(v)) or abs(float(v)) > MAX_ABS_SPEED_DPS
               for v in (inner_speed, outer_speed))
