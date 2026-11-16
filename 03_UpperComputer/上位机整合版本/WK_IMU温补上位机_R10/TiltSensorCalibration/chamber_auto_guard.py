# -*- coding: utf-8 -*-
"""Fail-closed checks for the *existing, field-proven* Snap7 temperature controller.

No PLC I/O is performed here. Snapshot health is intentionally tested
independently of PySide6 or proprietary DLLs.
"""
import math


class ChamberSafetyError(ValueError):
    pass


def require_live_chamber(snapshot, now, *, maximum_age=15.0):
    """Reject stale temperatures/status, faults and a disconnected PLC.

    `snapshot` holds monotonic timestamps stamped after successful PLC reads.
    Do not infer freshness from successful TCP connection alone.
    """
    if not snapshot['connected'] or not snapshot['data_available'] or snapshot['pv_failed']:
        raise ChamberSafetyError('温箱PLC断线或PV读取失败')
    for field, timestamp in (
        ('PV',snapshot['pv_updated']), ('SP',snapshot['sp_updated']),
        ('报警',snapshot['alarm_updated']), ('故障',snapshot['fault_updated']),
        ('运行',snapshot['run_updated']), ('定值启动',snapshot['started_updated']),
        ('运行模式',snapshot['mode_updated'])):
        if not math.isfinite(float(timestamp)) or timestamp<=0 or now-timestamp>maximum_age or timestamp>now+1:
            raise ChamberSafetyError(f'温箱{field}反馈过期/无效（禁止使用缓存值）')
    pv, sp = snapshot['pv'], snapshot['sp']
    if not math.isfinite(float(pv)) or not -45<=pv<=110:
        raise ChamberSafetyError('温箱PV异常或超出核对范围')
    if not math.isfinite(float(sp)) or not -45<=sp<=110:
        raise ChamberSafetyError('温箱SP异常或超出核对范围')
    if bool(snapshot['fault']) or snapshot['alarm'] != 0:
        raise ChamberSafetyError(f'温箱故障/报警：{snapshot["alarm"]}')
    return True


def require_setpoint_ack(snapshot, target, *, tolerance=0.2):
    """Readback acknowledgement is mandatory before waiting for chamber PV."""
    if abs(float(snapshot['sp'])-float(target))>tolerance:
        raise ChamberSafetyError(f'温箱设定值回读不一致：目标{target:.2f}，回读{snapshot["sp"]:.2f}℃')
    if not snapshot['fixed_mode']:
        raise ChamberSafetyError('PLC尚未进入定值模式')
    if not snapshot['fixed_started'] or not snapshot['running']:
        raise ChamberSafetyError('温箱未确认进入运行状态')
    return True
