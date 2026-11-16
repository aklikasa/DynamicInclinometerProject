# -*- coding: utf-8 -*-
"""热平衡采样判据（纯函数）：必须是真实且连续更新的60秒芯片温度数据。

不对温箱发送任何命令；PLC到温/运行/报警、转台停车、采样新鲜度
仍由原自动温补状态机逐项检查。
"""
import math


def chip_stability_status(trace, now, window_seconds=60.0, max_range_c=0.2,
                          min_coverage_seconds=55.0, max_gap_seconds=5.0,
                          fresh_seconds=2.0, minimum_points=20):
    """返回 (stable, 覆盖秒数, 温度极差)。

    跟踪记录为 `(monotonic_time, actual_chip_temperature_c)`；只允许新有效帧
    添加到记录，避免用重复的缓存温度伪造稳定窗口。
    """
    points = []
    for stamp, temp in trace:
        stamp, temp = float(stamp), float(temp)
        if (math.isfinite(stamp) and math.isfinite(temp)
                and now - window_seconds <= stamp <= now):
            points.append((stamp, temp))
    if not points:
        return False, 0.0, 0.0
    points.sort(key=lambda item: item[0])
    covered = max(0.0, points[-1][0] - points[0][0])
    values = [temp for _, temp in points]
    span = max(values) - min(values)
    valid_gaps = all(0.0 < right[0] - left[0] <= max_gap_seconds
                     for left, right in zip(points, points[1:]))
    stable = (len(points) >= minimum_points
              and covered >= min_coverage_seconds
              and now - points[-1][0] <= fresh_seconds
              and valid_gaps
              and span <= max_range_c)
    return stable, covered, span
