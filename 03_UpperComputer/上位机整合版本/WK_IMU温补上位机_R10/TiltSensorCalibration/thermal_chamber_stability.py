# -*- coding: utf-8 -*-
"""PLC温箱PV稳定判据（纯函数，无设备I/O）。

输入 trace 为 (monotonic_timestamp, pv_c)；调用方只应追加真实新鲜的PLC PV读数。
"""
import math


def _window_points(trace, now, window_seconds, *, min_coverage_seconds,
                   max_gap_seconds, fresh_seconds, minimum_points):
    now = float(now)
    window_seconds = float(window_seconds)
    points = []
    for stamp, value in trace:
        stamp, value = float(stamp), float(value)
        if (math.isfinite(stamp) and math.isfinite(value)
                and now - window_seconds <= stamp <= now):
            points.append((stamp, value))
    points.sort(key=lambda item: item[0])
    # PLC同一采样时间戳只保留一条，避免重复点虚增样本数。
    deduped = []
    for point in points:
        if deduped and point[0] == deduped[-1][0]:
            deduped[-1] = point
        else:
            deduped.append(point)
    if not deduped:
        return [], 0.0, False
    covered = max(0.0, deduped[-1][0] - deduped[0][0])
    gaps_ok = all(0.0 < right[0] - left[0] <= float(max_gap_seconds)
                  for left, right in zip(deduped, deduped[1:]))
    fresh = now - deduped[-1][0] <= float(fresh_seconds)
    complete = (len(deduped) >= int(minimum_points)
                and covered >= float(min_coverage_seconds)
                and gaps_ok and fresh)
    return deduped, covered, complete


def _linear_slope_c_per_min(points):
    """Least-squares slope of PV against monotonic time, in °C/min."""
    if len(points) < 2:
        return 0.0
    t = [p[0] for p in points]
    y = [p[1] for p in points]
    mt = sum(t) / len(t)
    my = sum(y) / len(y)
    denom = sum((x - mt) ** 2 for x in t)
    if denom <= 1e-12:
        return 0.0
    slope_c_per_s = sum((x - mt) * (v - my) for x, v in zip(t, y)) / denom
    return slope_c_per_s * 60.0


def chamber_stability_status(trace, now, window_seconds=300.0,
                             max_range_c=0.3,
                             max_abs_slope_c_per_min=0.05,
                             min_coverage_seconds=None,
                             max_gap_seconds=5.0,
                             fresh_seconds=2.0,
                             minimum_points=5):
    """返回 (stable, 覆盖秒数, PV极差, LS斜率°C/min)。

    默认要求最近5分钟有至少295秒有效覆盖、没有超过5秒的采样间断，
    PV极差≤0.3°C且线性回归斜率绝对值≤0.05°C/min。
    """
    window_seconds = float(window_seconds)
    if min_coverage_seconds is None:
        min_coverage_seconds = max(0.0, window_seconds - 5.0)
    points, covered, complete = _window_points(
        trace, now, window_seconds,
        min_coverage_seconds=min_coverage_seconds,
        max_gap_seconds=max_gap_seconds,
        fresh_seconds=fresh_seconds,
        minimum_points=minimum_points)
    if not points:
        return False, 0.0, 0.0, 0.0
    values = [value for _, value in points]
    span = max(values) - min(values)
    slope = _linear_slope_c_per_min(points)
    stable = (complete and span <= float(max_range_c) + 1e-9
              and abs(slope) <= float(max_abs_slope_c_per_min) + 1e-9)
    return stable, covered, span, slope


def chamber_band_status(trace, now, target_c, tolerance_c=0.1,
                        window_seconds=300.0,
                        min_coverage_seconds=None,
                        max_gap_seconds=5.0,
                        fresh_seconds=2.0,
                        minimum_points=5):
    """返回 (stable, 覆盖秒数, 窗口内最大目标偏差)。

    用于最终PV检查：最近完整窗口内每一个新鲜PV读数都必须处于
    target_c ± tolerance_c，且窗口覆盖时间、采样间隔及新鲜度合格。
    """
    window_seconds = float(window_seconds)
    if min_coverage_seconds is None:
        min_coverage_seconds = max(0.0, window_seconds - 5.0)
    points, covered, complete = _window_points(
        trace, now, window_seconds,
        min_coverage_seconds=min_coverage_seconds,
        max_gap_seconds=max_gap_seconds,
        fresh_seconds=fresh_seconds,
        minimum_points=minimum_points)
    if not points:
        return False, 0.0, float('inf')
    max_deviation = max(abs(value - float(target_c)) for _, value in points)
    stable = complete and max_deviation <= float(tolerance_c) + 1e-9
    return stable, covered, max_deviation
