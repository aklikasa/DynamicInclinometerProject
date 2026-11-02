# -*- coding: utf-8 -*-
"""Research-only thermal calibration workbook; no automatic release gate."""
from pathlib import Path
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill


def export_thermal_xlsx(folder, rows, summary):
    root=Path(folder)
    wb=Workbook()
    overview=wb.active;overview.title='温补总览'
    overview.append(['动态倾角仪 IMU 自动温补报告（研发验证，不可直接量产放行）'])
    overview.append(['类别','状态','温补后 RMSE','单位','25℃固定矩阵 RMSE','备注'])
    for sensor in ('acc','gyro'):
        d=summary.get('sensors',{}).get(sensor,{})
        stat=d.get('temperature_holdout',{})
        overview.append([sensor.upper(),d.get('status','not_estimated'),
                          stat.get('vector_rmse'),stat.get('unit'),
                          d.get('fixed_25c_holdout',{}).get('vector_rmse'),d.get('reason','')])
    overview.append(['注意','温箱来源必须与真实设备一致；如洋 RS232 协议未提供时，本程序只允许人工控制温度。'])
    overview.append(['安全','报告不代表已通过设备联调、温度计量或量产验收。'])
    overview.append(['对照说明','25℃固定矩阵指温补拟合曲线在25℃的参数固定使用，不等于原常温C方案文件。'])
    ws=wb.create_sheet('逐工况测量')
    ws.append(['温度设定°C','拟合/温度验证','工况编号','ACC/GYRO','姿态/动态','拟合/工况验证',
               '芯片温度°C','内轴角°','外轴角°','内轴速率°/s','外轴速率°/s',
               '参考X','参考Y','参考Z','实测X','实测Y','实测Z','有效帧','总帧'])
    for r in rows:
        measure=r.get('acc_raw_mean_g') if r.get('sensor')=='acc' else r.get('gyro_raw_mean_dps')
        ws.append([r['temperature_target_c'],r['temperature_split'],r['step_id'],r['sensor'],r['mode'],
                   r['split'],r['temperature_mean_c'],r['inner_actual_mean_deg'],r['outer_actual_mean_deg'],
                   r['inner_rate_mean_dps'],r['outer_rate_mean_dps'],*r['reference'],*measure,
                   r['accepted_frames'],r['frame_count']])
    for tab in wb.worksheets:
        tab.freeze_panes='A3' if tab is overview else 'A2'
        tab.auto_filter.ref=f'A2:S{tab.max_row}' if tab is ws else None
        tab.row_dimensions[1].height=26
        for cell in tab[1]:
            cell.font=Font(name='微软雅黑',size=11,bold=True,color='FFFFFF')
            cell.fill=PatternFill('solid',fgColor='254B67')
            cell.alignment=Alignment(vertical='center')
        for col in tab.columns:
            key=col[0].column_letter
            tab.column_dimensions[key].width=20 if tab==ws else 27
    path=root/'thermal_calibration_report.xlsx'
    wb.save(path)
    return str(path)
