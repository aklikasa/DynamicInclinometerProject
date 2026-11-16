# -*- coding: utf-8 -*-
"""统一管理按DTS设备编号区分的常温/全温补标定文件路径。

只使用MCU UID映射得到的DTS短编号；不读取、不保存原始96-bit UID。
"""
from pathlib import Path
import re

AMBIENT_FOLDER = 'AMBIENT_常温'
THERMAL_FOLDER = 'THERMAL_全温补'


def safe_device_sn(device_sn):
    value = str(device_sn or '').strip()
    if value in ('.', '..') or not re.fullmatch(r'[A-Za-z0-9._-]{1,64}', value):
        raise ValueError('DTS设备编号缺失或格式非法：仅允许1–64位字母、数字、点、下划线和短横线')
    return value


def device_root(base_root, device_sn):
    return Path(base_root).expanduser().resolve() / safe_device_sn(device_sn)


def ambient_root(base_root, device_sn):
    return device_root(base_root, device_sn) / AMBIENT_FOLDER


def thermal_root(base_root, device_sn):
    return device_root(base_root, device_sn) / THERMAL_FOLDER


def ambient_filename(device_sn, artifact):
    sn = safe_device_sn(device_sn)
    names = {
        'acc': f'{sn}_ACC_AMBIENT.json',
        'gyro': f'{sn}_GYRO_AMBIENT.json',
        'alignment': f'{sn}_ALIGNMENT_AMBIENT.json',
        'final': f'{sn}_IMU_CALIBRATION_FINAL_AMBIENT.json',
        'pilot': f'{sn}_IMU_CALIBRATION_PILOT_CANDIDATE_AMBIENT.json',
    }
    try:
        return names[str(artifact).lower()]
    except KeyError as exc:
        raise ValueError(f'未知常温标定文件类型：{artifact}') from exc


def thermal_filename(device_sn, sensor=None, artifact='selected'):
    sn = safe_device_sn(device_sn)
    kind = str(artifact).lower()
    if kind == 'selection':
        return f'{sn}_THERMAL_MODEL_SELECTION.json'
    if kind == 'fit_status':
        return f'{sn}_THERMAL_FIT_STATUS.json'
    if kind == 'gyro_bias':
        return f'{sn}_GYRO_THERMAL_BIAS_ONLY_CANDIDATE.json'
    if kind == 'zero_observations':
        return f'{sn}_GYRO_THERMAL_ZERO_RATE_OBSERVATIONS.json'
    if kind == 'report_manifest':
        return f'{sn}_THERMAL_REPORT_GENERATION_MANIFEST.json'
    if sensor not in ('acc', 'gyro'):
        raise ValueError(f'未知温补传感器类型：{sensor}')
    label = sensor.upper()
    suffixes = {
        'selected': f'{sn}_{label}_THERMAL_SELECTED_CANDIDATE.json',
        'models': f'{sn}_{label}_THERMAL_MODEL_CANDIDATES.json',
        'candidate': f'{sn}_{label}_THERMAL_CANDIDATE.json',
        'local': f'{sn}_{label}_THERMAL_LOCAL_CALIBRATION.json',
        'provisional': f'{sn}_{label}_THERMAL_PROVISIONAL_CUBIC_NO_TEMPERATURE_HOLDOUT.json',
    }
    try:
        return suffixes[kind]
    except KeyError as exc:
        raise ValueError(f'未知温补文件类型：{artifact}') from exc


def existing_ambient_path(base_root, device_sn, artifact):
    """优先读取新目录/新文件名；兼容读取R10旧版根目录固定文件名。"""
    sn = safe_device_sn(device_sn)
    new_path = ambient_root(base_root, sn) / ambient_filename(sn, artifact)
    if new_path.is_file():
        return new_path
    legacy_names = {
        'acc': 'accel_calibration.json',
        'gyro': 'gyro_calibration.json',
        'alignment': 'alignment.json',
        'final': 'imu_calibration_final.json',
        'pilot': 'imu_calibration_pilot_candidate.json',
    }
    legacy = Path(base_root).expanduser().resolve() / legacy_names[str(artifact).lower()]
    return legacy if legacy.is_file() else new_path
