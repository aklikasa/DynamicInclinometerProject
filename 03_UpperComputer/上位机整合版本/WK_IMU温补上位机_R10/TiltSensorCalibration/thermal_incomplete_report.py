# -*- coding: utf-8 -*-
"""Safely reports partial acquisition; NEVER exports a falsely approved thermal model."""
from pathlib import Path
import json
from openpyxl import Workbook


def export_incomplete_xlsx(folder, rows, missing, temperatures, reason=''):
    path=Path(folder)/'thermal_incomplete_data_report.xlsx'
    book=Workbook()
    sheet=book.active
    sheet.title='实验完成状态'
    sheet.append(['状态','PARTIAL_COMPLETED（数据不完整；禁止作为正式温补参数）'])
    sheet.append(['说明',reason])
    sheet.append(['合格工况数量',len(rows)])
    sheet.append(['未补齐工况数量',len(missing)])
    sheet.append(['独立验证','数据不完整，不提供正式最优模型推荐'])
    sheet.append(['原始数据','保留全部有效工况、拒绝日志和IMU原始CSV，允许后续补测'])
    fail=book.create_sheet('待补测清单')
    fail.append(['温箱目标°C','工况编号','传感器','旋转轴','目标角速度°/s','失败原因'])
    for item in missing:
        fail.append([item.get('temperature_target_c'),item.get('step_id'),item.get('sensor'),
                     item.get('rotation_axis'),item.get('target_rate_dps'),item.get('reason')])
    ok=book.create_sheet('合格数据清单')
    ok.append(['目标温度°C','工况编号','传感器','标定/验证','采样温度°C','有效帧数'])
    for item in rows:
        ok.append([item.get('temperature_target_c'),item.get('step_id'),item.get('sensor'),
                   item.get('split'),item.get('temperature_mean_c'),item.get('accepted_frames')])
    book.save(path)
    (Path(folder)/'thermal_incomplete_manifest.json').write_text(json.dumps({
        'status':'PARTIAL_COMPLETED','reason':reason,'temperatures':temperatures,
        'missing':missing,'accepted_steps':len(rows),
        'model_release_permitted':False},ensure_ascii=False,indent=2),encoding='utf8')
    return path
