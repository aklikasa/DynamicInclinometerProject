"""静态角度检测 Excel 报告与逐点断电恢复备份。

只依赖 PyPI 官方发布的 openpyxl（不使用 ChatGPT 内部 artifact_tool）。
Excel 写入采用同目录临时文件 + os.replace，避免半成品覆盖已有报表。
"""
from __future__ import annotations

from datetime import datetime
import json
import math
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from openpyxl import Workbook, load_workbook
from openpyxl.chart import ScatterChart, Reference, Series
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

TITLE_FILL = PatternFill('solid', fgColor='10283F')
HEADER_FILL = PatternFill('solid', fgColor='086C82')
LIGHT_FILL = PatternFill('solid', fgColor='E9F6FA')
ROW_FILL = PatternFill('solid', fgColor='F2F7FB')
HEADER_FONT = Font(name='Microsoft YaHei', bold=True, color='FFFFFF', size=10)
BODY_FONT = Font(name='Microsoft YaHei', size=10, color='23384D')

DETAIL_HEADERS = [
    '序号', '通道', '内轴目标°', '外轴目标°', '内轴反馈°', '外轴反馈°',
    '实测角度°', '参考角度°', '误差°', '模长g', '有效帧', '全部帧',
    '异常值率', '采样开始', '采样结束', '状态/说明', '原始X g',
    '原始Y g', '原始Z g', '校正X g', '校正Y g', '校正Z g',
    'STD X g', 'STD Y g', 'STD Z g',
]


def _sheet_headers(ws, row_num, headers):
    for index, value in enumerate(headers, 1):
        cell = ws.cell(row_num, index, value)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(vertical='center', horizontal='center', wrap_text=True)
    ws.row_dimensions[row_num].height = 32


def _cell_style(ws, start, end, *, rows=None):
    if rows is None:
        rows = range(1, ws.max_row + 1)
    for r in rows:
        for c in range(start, end + 1):
            cell = ws.cell(r, c)
            if cell.value is None:
                continue
            cell.font = BODY_FONT
            cell.alignment = Alignment(vertical='center', wrap_text=c in (1, 2, 16))
            if r % 2 == 0:
                cell.fill = ROW_FILL


def _finite_number(value):
    if value is None or value == '':
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _vector(row, key):
    raw = row.get(key)
    if not isinstance(raw, (list, tuple)) or len(raw) != 3:
        return [None] * 3
    return [_finite_number(v) for v in raw]


def _make_workbook(rows, calibration, settings, status, reason):
    wb = Workbook()
    summary = wb.active
    summary.title = '检测汇总'
    detail = wb.create_sheet('逐点结果')
    config = wb.create_sheet('校准与参数')

    summary.merge_cells('A1:F2')
    title = summary['A1']
    title.value = '静态绝对倾角精度检测报告'
    title.font = Font(name='Microsoft YaHei', bold=True, color='FFFFFF', size=18)
    title.fill = TITLE_FILL
    title.alignment = Alignment(horizontal='left', vertical='center', indent=1)
    for row in summary['A1:F2']:
        for cell in row:
            cell.fill = TITLE_FILL
    summary.row_dimensions[1].height = 28
    summary.row_dimensions[2].height = 21

    meta = [
        ('报告生成时间', datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
        ('测试状态', status), ('中断原因', reason),
        ('设备序列号', str(calibration.device_serial)),
        ('标定批次', str(calibration.run_id)),
        ('校准放行状态', '已批准' if calibration.approved else '仅试运行（未正式放行）'),
        ('已记录采点数', len(rows)),
    ]
    for idx, (key, value) in enumerate(meta, start=4):
        summary.cell(idx, 1, key)
        summary.cell(idx, 2, value)
        summary.cell(idx, 1).font = Font(name='Microsoft YaHei', color='43647A', bold=True)
        summary.cell(idx, 2).font = BODY_FONT
        summary.row_dimensions[idx].height = 23

    _sheet_headers(summary, 12, ['通道', '有效点数', '最大绝对误差 (°)', 'RMSE (°)', '平均误差 (°)', '最大剔除率'])
    for idx, channel in enumerate(('Y', 'X'), start=13):
        valid = [r for r in rows if r.get('channel') == channel and r.get('ok') and
                 _finite_number(r.get('error_deg')) is not None]
        errors = [float(r['error_deg']) for r in valid]
        data = [channel, len(errors), max((abs(v) for v in errors), default=None),
                math.sqrt(sum(v*v for v in errors) / len(errors)) if errors else None,
                sum(errors) / len(errors) if errors else None,
                max((_finite_number(r.get('rejected_fraction')) or 0 for r in valid), default=None)]
        for col, value in enumerate(data, 1):
            cell = summary.cell(idx, col, value)
            cell.font = BODY_FONT
            cell.fill = LIGHT_FILL if idx == 13 else ROW_FILL
            cell.alignment = Alignment(horizontal='center', vertical='center')
            if col in (3, 4, 5):
                cell.number_format = '0.000000'
            if col == 6:
                cell.number_format = '0.00%'
        summary.row_dimensions[idx].height = 27
    summary.merge_cells('A16:F16')
    summary['A16'] = '注：报告仅反映本次静态采样；角度正方向、机械零位及量程须经实机核实。'
    summary['A16'].font = Font(name='Microsoft YaHei', italic=True, color='5F788F', size=10)
    summary['A16'].alignment = Alignment(wrap_text=True, vertical='center')
    summary.row_dimensions[16].height = 36
    for col, width in {'A': 26, 'B': 31, 'C': 23, 'D': 23, 'E': 23, 'F': 22}.items():
        summary.column_dimensions[col].width = width
    summary.freeze_panes = 'A12'
    summary.sheet_view.showGridLines = False
    summary.print_options.horizontalCentered = True
    summary.sheet_properties.pageSetUpPr.fitToPage = True
    summary.page_setup.fitToWidth = 1

    detail.append(DETAIL_HEADERS)
    _sheet_headers(detail, 1, DETAIL_HEADERS)
    for num, row in enumerate(rows, start=1):
        raw = _vector(row, 'raw')
        corrected = _vector(row, 'corrected')
        std = _vector(row, 'std_g')
        values = [
            num, row.get('channel'), _finite_number(row.get('inner_deg')),
            _finite_number(row.get('outer_signed_deg')),
            _finite_number(row.get('inner_actual')),
            _finite_number(row.get('outer_actual')),
            _finite_number(row.get('measured_deg')),
            _finite_number(row.get('reference_deg')),
            _finite_number(row.get('error_deg')),
            _finite_number(row.get('norm_g')),
            row.get('accepted_frames'), row.get('frames'),
            _finite_number(row.get('rejected_fraction')),
            row.get('started_at'), row.get('ended_at'),
            row.get('message', '完成' if row.get('ok') else '失败'),
            *raw, *corrected, *std,
        ]
        detail.append(values)
    _cell_style(detail, 1, 25, rows=range(2, detail.max_row + 1))
    for row in detail.iter_rows(min_row=2):
        for col in (3,4,5,6,7,8,9):
            row[col-1].number_format = '0.000000'
        for col in (10,17,18,19,20,21,22,23,24,25):
            row[col-1].number_format = '0.000000'
        row[12].number_format = '0.00%'
    for idx in range(1, 26):
        col = get_column_letter(idx)
        detail.column_dimensions[col].width = (32 if idx == 16 else 21 if idx in (14,15) else 16)
    detail.column_dimensions['B'].width = 11
    detail.column_dimensions['A'].width = 9
    detail.freeze_panes = 'C2'
    detail.auto_filter.ref = detail.dimensions
    detail.sheet_view.showGridLines = False
    detail.sheet_properties.pageSetUpPr.fitToPage = True
    detail.page_setup.fitToWidth = 1

    settings_rows = [
        ['项目','值'],
        ['校准文件', str(calibration.path)],
        ['校准SN', str(calibration.device_serial)],
        ['校准批次', str(calibration.run_id)],
        ['原数据模型', 'raw = forward_matrix @ reference_P + bias'],
        ['校正公式', 'platform = M @ (raw - bias)'],
        ['测试类型', '相对机械零位的重力静态绝对倾角（需实机确认零位与符号）'],
        ['X通道', '内轴90°，atan2(Px,Pz)'],
        ['Y通道', '内轴0°，atan2(Py,Pz)'],
        ['异常值方法', '帧内3×1.4826×MAD三轴联合剔除，窗口帧均值二次剔除'],
        ['报告说明', '本报告不代表全温或出厂产品认证'],
        ['检测状态', status],
        ['中断原因', reason],
    ]
    settings_rows += [[str(k),str(v)] for k,v in settings.items()]
    settings_rows += [[f'bias[{i}]',value] for i,value in enumerate(calibration.bias)]
    settings_rows += [[f'M[{i},{j}]',calibration.matrix[i][j]] for i in range(3) for j in range(3)]
    for row in settings_rows:
        config.append(row)
    _sheet_headers(config, 1, ['项目', '值'])
    _cell_style(config, 1, 2, rows=range(2, config.max_row + 1))
    config.column_dimensions['A'].width = 37
    config.column_dimensions['B'].width = 83
    config.freeze_panes = 'B2'
    config.auto_filter.ref = config.dimensions
    config.sheet_view.showGridLines = False

    # 可视化误差，直接引用逐点结果里的实际数据，不是伪造曲线。
    valid_ranges = []
    for channel in ('Y','X'):
        idxs = [i for i,r in enumerate(rows,start=2) if r.get('channel') == channel and r.get('ok')]
        if idxs and idxs == list(range(min(idxs), max(idxs) + 1)):
            valid_ranges.append((channel, min(idxs), max(idxs)))
    if valid_ranges:
        chart = ScatterChart()
        chart.title = 'X / Y 静态角度误差'
        chart.x_axis.title = '外轴目标角度 (°)'
        chart.y_axis.title = '角度误差 (°)'
        chart.style = 13
        chart.width = 20
        chart.height = 10
        chart.scatterStyle = 'lineMarker'
        for channel, start, end in valid_ranges:
            xs = Reference(detail, min_col=4, min_row=start, max_row=end)
            ys = Reference(detail, min_col=9, min_row=start, max_row=end)
            serie = Series(ys, xs, title=f'{channel} 通道')
            chart.series.append(serie)
        summary.add_chart(chart, 'A19')
    wb.calculation.fullCalcOnLoad = True
    return wb


def export_report(path, rows, calibration, settings, status, reason=''):
    """创建 Excel 并原子替换目标文件。目标被 Excel 占用时原文件不会被破坏。"""
    out = Path(path).expanduser().resolve()
    if out.suffix.lower() != '.xlsx':
        raise ValueError('报告文件必须以 .xlsx 结尾')
    out.parent.mkdir(parents=True, exist_ok=True)
    wb = _make_workbook(rows, calibration, settings, status, reason)
    temp_path = out.parent / f'.{out.stem}.{uuid4().hex}.xlsx'
    try:
        wb.save(temp_path)
        # 文件不是只检查保存成功，还要能被通用 Excel 读取器解析。
        with open(temp_path, 'rb') as fh:
            if fh.read(2) != b'PK':
                raise IOError('Excel 输出文件不是有效的 ZIP/XLSX 格式')
        os.replace(temp_path, out)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    return out


def checkpoint_path(report_path):
    path = Path(report_path).expanduser().resolve()
    return path.with_name(path.stem + '.checkpoint.json')


def save_checkpoint(report_path, rows, calibration, settings, status='采集中', reason=''):
    """每采点写一次，可在 Excel 导出失败或程序意外关闭后恢复。"""
    dest = checkpoint_path(report_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        'format_version': 1,
        'created_at': datetime.now().isoformat(timespec='seconds'),
        'report_path': str(Path(report_path).expanduser().resolve()),
        'status': str(status), 'reason': str(reason),
        'calibration': {
            'path': str(calibration.path),
            'device_serial': str(calibration.device_serial),
            'run_id': str(calibration.run_id),
            'approved': bool(calibration.approved),
            'bias': list(calibration.bias),
            'matrix': [list(v) for v in calibration.matrix],
        },
        'settings': dict(settings),
        'rows': list(rows),
    }
    temp_path = dest.with_name('.' + dest.name + '.' + uuid4().hex + '.tmp')
    try:
        with temp_path.open('w', encoding='utf-8', newline='\n') as file:
            json.dump(payload, file, ensure_ascii=False, indent=2, allow_nan=False)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp_path, dest)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    return dest


def export_from_checkpoint(checkpoint_file, output_path=None):
    """独立于 IMU/转台导出已有结果，机械设备无需连接。"""
    source = Path(checkpoint_file)
    record = json.loads(source.read_text(encoding='utf-8-sig'))
    if record.get('format_version') != 1:
        raise ValueError('无法识别的检测备份版本')
    rows = record.get('rows')
    if not isinstance(rows, list) or not rows:
        raise ValueError('备份没有已完成的采点记录')
    c = record['calibration']
    if len(c['bias']) != 3 or len(c['matrix']) != 3 or any(len(m) != 3 for m in c['matrix']):
        raise ValueError('备份校准信息结构错误')
    cal = SimpleNamespace(
        path=c['path'], device_serial=c['device_serial'], run_id=c['run_id'],
        approved=c['approved'], bias=c['bias'], matrix=c['matrix'],
    )
    return export_report(output_path or record['report_path'], rows, cal,
                         record.get('settings') or {}, record.get('status', '恢复导出'),
                         record.get('reason', ''))
