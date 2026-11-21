# -*- coding: utf-8 -*-
"""Thermal quality monitoring while calibrating (never a substitute for PLC safety).

A chamber which has passed the rigorous pre-calibration gate may undergo small
control oscillations and die-temperature changes while the turntable moves.
Online *soft holds* therefore require persistence, and are different from the
unchanged pre-calibration gate and per-segment temperature quality limits.

Every recovery MUST begin a new observation epoch only AFTER WK stop has been
confirmed; temperature history from before the hold cannot authorize restart.
"""
from collections import deque
import math
import numpy as np


class ThermalRuntimeGuard:
    # Conservative research defaults, NOT sensor or chamber safety ratings.
    # Thermal sampling QUALITY limits are frozen from operator inputs in the
    # task. Defaults here exist only for legacy callers and isolated tests.
    def __init__(self, target, pv_pause_c=0.50, chip_span_c=0.40,
                 chip_slope_c_per_min=0.10, pv_hold_seconds=30.0,
                 chip_span_hold_seconds=30.0, chip_slope_hold_seconds=60.0,
                 recovery_pv_c=0.30, recovery_chip_span_c=0.20,
                 resoak_pv_c=1.0, resoak_hold_seconds=30.0,
                 recovery_chip_slope_c_per_min=0.05):
        self.target = float(target)
        self.pv_pause_c = float(pv_pause_c)
        self.chip_span_c = float(chip_span_c)
        self.chip_slope_c_per_min = float(chip_slope_c_per_min)
        self.pv_hold_seconds = float(pv_hold_seconds)
        self.chip_span_hold_seconds = float(chip_span_hold_seconds)
        self.chip_slope_hold_seconds = float(chip_slope_hold_seconds)
        self.recovery_pv_c = float(recovery_pv_c)
        self.recovery_chip_span_c = float(recovery_chip_span_c)
        self.resoak_pv_c = float(resoak_pv_c)
        self.resoak_hold_seconds = float(resoak_hold_seconds)
        self.recovery_chip_slope_c_per_min = float(recovery_chip_slope_c_per_min)
        self.pv = deque()
        self.chip = deque()
        self.last_pv_stamp = None
        self.last_chip_count = None
        self.high_pv_since = None
        self.large_pv_since = None
        self.chip_span_since = None
        self.chip_slope_since = None
        self.recovery_since = None

    def begin_recovery(self, now):
        """Start a fresh POST-STOP epoch; do not use old stable samples."""
        if not math.isfinite(float(now)):
            raise ValueError('恢复观察起点无效')
        self.recovery_since = float(now)
        self.pv.clear()
        self.chip.clear()
        self.last_pv_stamp = None
        self.last_chip_count = None
        self.high_pv_since = None
        self.large_pv_since = None
        self.chip_span_since = None
        self.chip_slope_since = None

    @staticmethod
    def _span(points, now, window):
        return [(t, v) for t, v in points if now - window <= t <= now]

    @staticmethod
    def _slope(points):
        ts = np.asarray([x[0] for x in points], dtype=float)
        values = np.asarray([x[1] for x in points], dtype=float)
        return float(np.polyfit((ts - ts[0]) / 60.0, values, 1)[0])

    @staticmethod
    def _held(since, now, duration):
        return since is not None and now - since >= duration

    def observe(self, now, pv, pv_stamp, chip, chip_count):
        now, pv, chip = float(now), float(pv), float(chip)
        if not all(math.isfinite(v) for v in (now, pv, chip)):
            return 'safety', '温度反馈出现非有限值'
        if pv_stamp is None or not math.isfinite(float(pv_stamp)):
            return 'hold', '温箱PV反馈无有效时间戳'
        pv_stamp = float(pv_stamp)
        if now - pv_stamp > 2.0 or now < pv_stamp - 0.5:
            return 'hold', '温箱PV未在2秒内刷新'
        if self.last_pv_stamp is None or pv_stamp > self.last_pv_stamp:
            self.pv.append((pv_stamp, pv))
            self.last_pv_stamp = pv_stamp
        if chip_count != self.last_chip_count:
            self.chip.append((now, chip))
            self.last_chip_count = chip_count
        while self.pv and now - self.pv[0][0] > 600.0:
            self.pv.popleft()
        while self.chip and now - self.chip[0][0] > 600.0:
            self.chip.popleft()

        error = abs(pv - self.target)
        # Severe chamber drift is not a soft-calibration quality decision.
        if error > self.resoak_pv_c + 1e-9:
            if self.large_pv_since is None:
                self.large_pv_since = now
            if self._held(self.large_pv_since, now, self.resoak_hold_seconds):
                return 'resoak', (f'温箱PV持续{self.resoak_hold_seconds:g}秒偏离目标'
                                  f'超过{self.resoak_pv_c:.2f}℃，需要重新热浸')
        else:
            self.large_pv_since = None

        if error > self.pv_pause_c + 1e-9:
            if self.high_pv_since is None:
                self.high_pv_since = now
            if self._held(self.high_pv_since, now, self.pv_hold_seconds):
                return 'hold', f'温箱PV偏离目标超过{self.pv_pause_c:.2f}℃持续{self.pv_hold_seconds:g}秒'
        else:
            self.high_pv_since = None

        # Do not convert a single transient/quantization crossing into a motor
        # stop. Require both a genuine 60 s observation and a persistent fault.
        recent = self._span(self.chip, now, 60.0)
        span_bad = (len(recent) >= 20 and recent[-1][0] - recent[0][0] >= 55.0
                    and max(v for _, v in recent) - min(v for _, v in recent)
                    > self.chip_span_c + 1e-9)
        if span_bad:
            if self.chip_span_since is None:
                self.chip_span_since = now
            if self._held(self.chip_span_since, now, self.chip_span_hold_seconds):
                return 'hold', (f'芯片60秒极差持续{self.chip_span_hold_seconds:g}秒'
                                f'超过{self.chip_span_c:.2f}℃')
        else:
            self.chip_span_since = None

        recent = self._span(self.chip, now, 300.0)
        slope_bad = (len(recent) >= 30 and recent[-1][0] - recent[0][0] >= 285.0
                     and abs(self._slope(recent)) > self.chip_slope_c_per_min + 1e-9)
        if slope_bad:
            if self.chip_slope_since is None:
                self.chip_slope_since = now
            if self._held(self.chip_slope_since, now, self.chip_slope_hold_seconds):
                slope = self._slope(recent)
                return 'hold', (f'芯片5分钟斜率{slope:+.4f}℃/min'
                                f'持续{self.chip_slope_hold_seconds:g}秒超出'
                                f'±{self.chip_slope_c_per_min:.3f}℃/min')
        else:
            self.chip_slope_since = None
        return 'ok', ''

    def recovery_ready(self, now, pv, chip, seconds=120.0):
        """Require fresh, continuous PV+chip data collected AFTER stopping.

        The recovery gate remains stricter than the running soft-hold trigger.
        A recovery cannot succeed before `begin_recovery()` is called.
        """
        now, pv, chip, seconds = map(float, (now, pv, chip, seconds))
        if self.recovery_since is None or now - self.recovery_since < seconds:
            return False
        if not all(math.isfinite(x) for x in (now, pv, chip)):
            return False
        pv_values = [(t, v) for t, v in self._span(self.pv, now, seconds)
                     if t >= self.recovery_since]
        chip_values = [(t, v) for t, v in self._span(self.chip, now, 60.)
                       if t >= self.recovery_since]
        if len(pv_values) < 30 or len(chip_values) < 20:
            return False
        if (pv_values[-1][0] - pv_values[0][0] < seconds - 5.0
                or chip_values[-1][0] - chip_values[0][0] < 55.0):
            return False
        if now - pv_values[-1][0] > 2.0 or now - chip_values[-1][0] > 2.0:
            return False
        if any(b[0] - a[0] > 5.0 for a, b in zip(pv_values, pv_values[1:])):
            return False
        if any(b[0] - a[0] > 5.0 for a, b in zip(chip_values, chip_values[1:])):
            return False
        if any(abs(v - self.target) > self.recovery_pv_c + 1e-9
               for _, v in pv_values):
            return False
        if max(v for _, v in chip_values) - min(v for _, v in chip_values) > self.recovery_chip_span_c + 1e-9:
            return False
        if abs(pv - self.target) > self.recovery_pv_c + 1e-9:
            return False
        if abs(chip - chip_values[-1][1]) > self.recovery_chip_span_c + 1e-9:
            return False
        long = [(t, v) for t, v in self._span(self.chip, now, 300.)
                if t >= self.recovery_since]
        if len(long) >= 30 and long[-1][0] - long[0][0] >= 285.0:
            # A long post-stop trace is available. Do not restart while the die
            # still has a large persistent drift, irrespective of running limits.
            if abs(self._slope(long)) > self.recovery_chip_slope_c_per_min + 1e-9:
                return False
        return True
