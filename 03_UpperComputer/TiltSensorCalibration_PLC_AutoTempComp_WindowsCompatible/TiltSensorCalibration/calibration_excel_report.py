# -*- coding: utf-8 -*-
"""把生产标定/独立验证 JSON 转成可直接用 Excel 打开的对比报告。

仅依赖 Python 标准库。不会修改标定数据、校正参数或 PASS/FAIL 结果。
报告中的“标定前模长误差”是旋转不变的诊断量，不等于标定前的三轴参考向量误差。
"""
from __future__ import annotations

import datetime
import math
import os
from pathlib import Path
import tempfile
from xml.sax.saxutils import escape
from zipfile import ZipFile, ZIP_DEFLATED


_NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
_REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
_PKG = 'http://schemas.openxmlformats.org/package/2006/relationships'


def _norm(v):
    return math.sqrt(sum(float(x)**2 for x in v))


def _vector(raw, bias, correction):
    x = [float(r)-float(b) for r, b in zip(raw, bias)]
    return [sum(float(row[i])*x[i] for i in range(3)) for row in correction]


def _direction_angle(a, b):
    aa, bb = _norm(a), _norm(b)
    if aa < 1e-10 or bb < 1e-10:
        return None
    cosine = sum(float(i)*float(j) for i, j in zip(a,b))/(aa*bb)
    return math.degrees(math.acos(max(-1.,min(1.,cosine))))


def _rms(values):
    return math.sqrt(sum(float(x)**2 for x in values)/len(values)) if values else None


def _column_letter(i):
    s=''
    while i:
        i,r=divmod(i-1,26)
        s=chr(65+r)+s
    return s


def _xml_text(v):
    return escape(str(v), {'"':'&quot;'})


def _cell(value, col, row, style=0):
    if value is None or (isinstance(value,float) and not math.isfinite(value)):
        return ''
    address=f'{_column_letter(col)}{row}'
    if isinstance(value, (float,int)) and not isinstance(value,bool):
        return f'<c r="{address}" s="{style}"><v>{float(value):.12g}</v></c>'
    text=_xml_text(value)
    return f'<c r="{address}" s="{style}" t="inlineStr"><is><t xml:space="preserve">{text}</t></is></c>'


def _styles_xml():
    # 0=文本，1=大标题，2=次标题，3=表头，4=普通小数，5=交替行，6=警告，7=通过。
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="{_NS}">
 <numFmts count="1"><numFmt numFmtId="165" formatCode="0.000000"/></numFmts>
 <fonts count="4"><font><sz val="10"/><name val="Microsoft YaHei"/><color rgb="FF26333D"/></font>
 <font><b/><sz val="17"/><name val="Microsoft YaHei"/><color rgb="FF26333D"/></font>
 <font><sz val="10"/><name val="Microsoft YaHei"/><color rgb="FF64717B"/></font>
 <font><b/><sz val="10"/><name val="Microsoft YaHei"/><color rgb="FFFFFFFF"/></font></fonts>
 <fills count="5"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>
 <fill><patternFill patternType="solid"><fgColor rgb="FFF3F5F5"/><bgColor indexed="64"/></patternFill></fill>
 <fill><patternFill patternType="solid"><fgColor rgb="FF34454D"/><bgColor indexed="64"/></patternFill></fill>
 <fill><patternFill patternType="solid"><fgColor rgb="FFFFF1EC"/><bgColor indexed="64"/></patternFill></fill></fills>
 <borders count="2"><border><left/><right/><top/><bottom/><diagonal/></border>
 <border><left/><right/><top/><bottom style="hair"><color rgb="FFDFE4E5"/></bottom><diagonal/></border></borders>
 <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
 <cellXfs count="8">
 <xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0"/>
 <xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0"/>
 <xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0"/>
 <xf numFmtId="0" fontId="3" fillId="3" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf>
 <xf numFmtId="165" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1"/>
 <xf numFmtId="165" fontId="0" fillId="2" borderId="1" xfId="0" applyNumberFormat="1"/>
 <xf numFmtId="0" fontId="0" fillId="4" borderId="1" xfId="0"/>
 <xf numFmtId="0" fontId="0" fillId="2" borderId="1" xfId="0"/>
 </cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>'''


def _worksheet_xml(title, subtitle, header, rows, widths=None, table=True):
    ncols=max(len(header), 10)
    lastcol=_column_letter(ncols)
    lastrow=max(4,4+len(rows))
    widths=widths or {}
    columns=''.join(f'<col min="{i}" max="{i}" width="{float(widths.get(i, 15))}" customWidth="1"/>' for i in range(1,ncols+1))
    lines=[]
    for row_idx, data in ((1,[title]),(2,[subtitle]),(4,header)):
        sty=1 if row_idx==1 else 2 if row_idx==2 else 3
        lines.append(f'<row r="{row_idx}" ht="{31 if row_idx==1 else 23 if row_idx==2 else 33}" customHeight="1">'+
                     ''.join(_cell(v,i+1,row_idx,sty) for i,v in enumerate(data))+'</row>')
    for i,row in enumerate(rows,5):
        style=4 if i%2==1 else 5
        cells=[]
        for j,value in enumerate(row,1):
            s=style if isinstance(value,float) else (0 if i%2 else 7)
            if value=='FAIL': s=6
            cells.append(_cell(value,j,i,s))
        lines.append(f'<row r="{i}" ht="21" customHeight="1">'+''.join(cells)+'</row>')
    auto=f'<autoFilter ref="A4:{lastcol}{lastrow}"/>' if table and rows else ''
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="{_NS}"><dimension ref="A1:{lastcol}{lastrow}"/>
<sheetViews><sheetView showGridLines="0" workbookViewId="0"><pane ySplit="4" topLeftCell="A5" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>
<sheetFormatPr defaultRowHeight="20"/><cols>{columns}</cols><sheetData>{''.join(lines)}</sheetData>
<mergeCells count="2"><mergeCell ref="A1:{lastcol}1"/><mergeCell ref="A2:{lastcol}2"/></mergeCells>
{auto}<pageMargins left="0.3" right="0.3" top="0.5" bottom="0.5" header="0.2" footer="0.2"/>
</worksheet>'''


def _write_with_xlsxwriter(path, sheets):
    """优先使用 Excel 兼容性成熟的 XlsxWriter；标准库 OOXML 为无依赖回退。"""
    import xlsxwriter
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    book = xlsxwriter.Workbook(str(path))
    book.set_properties({'title':'IMU 校准验证对比', 'subject':'逐姿态原始数据和拟合后比较'})
    title_f = book.add_format({'bold':True,'font_name':'微软雅黑','font_size':15,'font_color':'#24313A'})
    subtitle_f = book.add_format({'font_name':'微软雅黑','font_size':9,'font_color':'#607080'})
    head_f = book.add_format({'font_name':'微软雅黑','bold':True,'bg_color':'#34454D',
                              'font_color':'white','text_wrap':True,'valign':'vcenter','border':1,'border_color':'#E0E4E5'})
    txt_f = book.add_format({'font_name':'微软雅黑','font_size':10,'bottom':1,'bottom_color':'#E6E9EB'})
    num_f = book.add_format({'font_name':'微软雅黑','font_size':10,'num_format':'0.000000',
                             'bottom':1,'bottom_color':'#E6E9EB'})
    fail_f = book.add_format({'font_name':'微软雅黑','bold':True,'font_color':'#A62727', 'bg_color':'#FFF1EC'})
    for sheet_name, payload in sheets:
        heading, subheading, header, rows, widths = payload
        if not rows:
            raise ValueError(f'{sheet_name} 报告无数据，禁止写入空工作簿')
        ws = book.add_worksheet(sheet_name)
        count = max(10,len(header))
        ws.merge_range(0,0,0,count-1,heading,title_f)
        ws.merge_range(1,0,1,count-1,subheading,subtitle_f)
        ws.set_row(0,29)
        ws.set_row(3,36)
        ws.freeze_panes(4,0)
        for i in range(count): ws.set_column(i,i,float(widths.get(i+1,15)))
        for col,key in enumerate(header): ws.write(3,col,key,head_f)
        for row_idx,values in enumerate(rows,4):
            for col,val in enumerate(values):
                fmt=fail_f if val=='FAIL' else num_f if isinstance(val,(int,float)) and not isinstance(val,bool) else txt_f
                if val is None: ws.write_blank(row_idx,col,None,txt_f)
                elif isinstance(val,(int,float)) and not isinstance(val,bool) and not math.isfinite(val):
                    ws.write_blank(row_idx,col,None,txt_f)
                else: ws.write(row_idx,col,val,fmt)
        ws.autofilter(3,0,3+len(rows),count-1)
        ws.set_landscape()
        ws.fit_to_pages(1,0)
    book.close()
    with ZipFile(path) as z:
        if z.testzip(): raise ValueError('Excel zip CRC 校验失败')
        for i in range(1,len(sheets)+1):
            content=z.read(f'xl/worksheets/sheet{i}.xml')
            if b'<sheetData' not in content: raise ValueError('Excel 工作表不含数据')
    return str(path)


def _write_xlsx(path, sheets):
    try:
        import xlsxwriter  # noqa: F401
    except ImportError:
        pass  # 对未安装XlsxWriter的旧版PC继续使用无需依赖的标准库实现
    else:
        return _write_with_xlsxwriter(path, sheets)
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(suffix='.xlsx',prefix='.report_',dir=path.parent)
    os.close(fd)
    try:
        with ZipFile(tmp,'w',ZIP_DEFLATED,compresslevel=6) as z:
            overrides=''.join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(1,len(sheets)+1))
            z.writestr('[Content_Types].xml', f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>{overrides}</Types>''')
            z.writestr('_rels/.rels', f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="{_PKG}"><Relationship Id="rId1" Type="{_REL}/officeDocument" Target="xl/workbook.xml"/></Relationships>''')
            entries=''.join(f'<sheet name="{_xml_text(name)}" sheetId="{i}" r:id="rId{i}"/>' for i,(name,_) in enumerate(sheets,1))
            z.writestr('xl/workbook.xml',f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="{_NS}" xmlns:r="{_REL}"><bookViews><workbookView/></bookViews><sheets>{entries}</sheets></workbook>''')
            rels=''.join(f'<Relationship Id="rId{i}" Type="{_REL}/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1,len(sheets)+1))
            z.writestr('xl/_rels/workbook.xml.rels',f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="{_PKG}">{rels}<Relationship Id="rId{len(sheets)+1}" Type="{_REL}/styles" Target="styles.xml"/></Relationships>''')
            z.writestr('xl/styles.xml',_styles_xml())
            for i,(name,payload) in enumerate(sheets,1):
                z.writestr(f'xl/worksheets/sheet{i}.xml',_worksheet_xml(*payload))
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)
    return str(path)


def _acc_rows(entries, bias, correction, fallback='独立验证'):
    details=[]
    for item in entries:
        ref=item.get('gravity_reference_platform_g')
        if ref is None:
            raise ValueError(f"ACC缺少参考向量：{item.get('step_id')}")
        raw=item['acc_raw_mean_g']
        corrected=_vector(raw,bias,correction)
        before=_norm(raw);after=_norm(corrected)
        target=_norm(ref)
        d_error=_norm([a-b for a,b in zip(corrected,ref)])*1000
        angle=_direction_angle(corrected,ref)
        split={'fit':'拟合','validate':'独立验证'}.get(item.get('split'),fallback)
        if fallback=='六轴复核': split=fallback
        data=[split,item.get('step_id',''),item.get('outer_target_deg'),item.get('inner_target_deg'),
              *map(float,ref),*map(float,raw),before,(before-target)*1000,
              *corrected,after,(after-target)*1000,d_error,angle,
              item.get('accepted_frames',item.get('frame_count')),item.get('temperature_mean_c')]
        details.append({'split':split,'row':data,'before_error':(before-target)*1000,'after_error':(after-target)*1000,
                        'vector_error':d_error,'angle':angle})
    return details


def _gyro_rows(entries,bias,correction,fallback='独立验证'):
    details=[]
    for item in entries:
        ref=item['reference'];raw=item['measured']
        corrected=_vector(raw,bias,correction)
        target=_norm(ref);before=_norm(raw);after=_norm(corrected)
        ve=_norm([a-b for a,b in zip(corrected,ref)])
        angle=_direction_angle(corrected,ref)
        cross=None if target<1e-10 else _norm([a-sum(x*y for x,y in zip(corrected,ref))/target**2*b for a,b in zip(corrected,ref)])
        split={'fit':'拟合','validate':'独立验证'}.get(item.get('split'),fallback)
        if fallback=='六轴复核': split=fallback
        row=[split,item.get('step_id',''),item.get('axis','静止'),item.get('target_rate_dps',0.0),
             *map(float,ref),target,*map(float,raw),before,before-target,
             *corrected,after,after-target,ve,angle,cross,
             item.get('accepted_frames',item.get('frame_count')),item.get('temperature_mean_c')]
        details.append({'split':split,'row':row,'before_error':before-target,'after_error':after-target,
                        'vector_error':ve,'angle':angle})
    return details


def _overview_rows(acc,gyro,result):
    rows=[]
    for kind,details,unit in [('ACC',acc,'mg'),('GYRO',gyro,'°/s')]:
        for split in ('拟合','独立验证','六轴复核'):
            pts=[r for r in details if r['split']==split]
            if not pts:continue
            rows.append([kind,split,len(pts),unit,
                         _rms([p['before_error'] for p in pts]),
                         _rms([p['after_error'] for p in pts]),
                         _rms([p['vector_error'] for p in pts]),
                         max(p['vector_error'] for p in pts),
                         max([p['angle'] for p in pts if p['angle'] is not None],default=None),
                         '前后模长RMSE；方向与向量误差仅对校正后计算'])
    gate=result.get('quality_gate',{})
    rows.append(['验收结论',gate.get('verdict',result.get('status','未知')),None,'',None,None,None,None,None,
                 '试运行门槛不等于行业强制阈值；正式放行须批准'])
    for key,val in gate.get('gates',gate.get('checks',{})).items():
        if isinstance(val,dict):
            rows.append(['门限',key,None,'',val.get('value',val.get('actual')),val.get('limit'),None,None,None,'通过' if val.get('pass') else '不通过'])
    return rows


def create_validation_workbook(task_type,result,run_dir):
    """生成每一次自动任务的 Excel 审核文件；拟合与验证分组、原始和校正值同时保存。"""
    kind=str(task_type)
    acc=[];gyro=[]
    if kind=='accel':
        acc=_acc_rows(result['position_measurements'],result['raw_accel_bias_g'],result['raw_to_platform_matrix'])
    elif kind=='gyro':
        gyro=_gyro_rows(result['fit_measurements']+result['validation_measurements'],
                        result['raw_gyro_bias_dps'],result['raw_to_platform_matrix'])
    elif kind=='align':
        source=result['combined_calibration'];data=result['validation_measurements']
        a=source['accelerometer'];g=source['gyroscope']
        acc=_acc_rows(data['acc'],a['raw_bias_g'],a['raw_to_platform_matrix'],'六轴复核')
        gyro=_gyro_rows(data['gyro'],g['raw_bias_dps'],g['raw_to_platform_matrix'],'六轴复核')
    else:
        raise ValueError('不支持的自动任务类型：'+kind)
    no=0
    overview=[_overview_rows(acc,gyro,result),]
    sensor=result.get('sensor_configuration',{})
    meta=(f"PCB：{result.get('device_serial','')}  |  任务：{result.get('run_id','')}  |  "
          f"芯片：{sensor.get('chip','未记录')} ACC±{sensor.get('acc_fs_g','?')}g/" 
          f"GYRO±{sensor.get('gyro_fs_dps','?')}°/s ODR {sensor.get('odr_hz','?')}Hz  |  "
          f"结果：{result.get('quality_gate',{}).get('verdict',result.get('status',''))}  |  "
          f"生成：{datetime.datetime.now().isoformat(timespec='seconds')}")
    sheets=[('结果概览',('六轴 IMU 常温标定与验证 — 结果概览',meta,
                        ['对象','数据集','样本数','单位','标定前模长RMSE','标定后模长RMSE','标定后向量RMSE','标定后最大向量误差','最大方向误差(°)','说明'],
                        _overview_rows(acc,gyro,result),{1:18,2:24,3:12,4:13,5:23,6:23,7:23,8:28,9:20,10:54})),]
    if acc:
        sheets.append(('ACC逐姿态',('ACC：标定前后对比（模长基准 1 g）',meta,
                         ['分组','工况','外轴目标°','内轴目标°','参考X g','参考Y g','参考Z g',
                          '原始X g','原始Y g','原始Z g','原始模长g','原始偏差mg',
                          '校正X g','校正Y g','校正Z g','校正模长g','校正偏差mg','向量误差mg','方向误差°','有效帧','温度°C'],
                         [x['row'] for x in acc],{1:15,2:22,3:16,4:16,12:17,17:19,18:18,19:17,20:14,21:14})))
    if gyro:
        sheets.append(('GYRO逐速率',('GYRO：原始与校正后角速度对比',meta,
                         ['分组','工况','运动轴','指令速率°/s','参考X°/s','参考Y°/s','参考Z°/s','参考模长°/s',
                          '原始X°/s','原始Y°/s','原始Z°/s','原始模长°/s','原始模长偏差°/s',
                          '校正X°/s','校正Y°/s','校正Z°/s','校正模长°/s','校正模长偏差°/s',
                          '校正向量误差°/s','方向误差°','交叉轴残差°/s','有效帧','温度°C'],
                         [x['row'] for x in gyro],{1:15,2:26,3:13,4:18,13:25,18:25,19:25,20:18,21:23,22:13,23:15})))
    notes=[
        ['指标说明','ACC 原始与校正模长误差 = (|a| - |f_ref|)×1000 mg；参考模长为 1 g。'],
        ['指标说明','ACC 校正后向量误差 = |K(a_raw-b)-f_ref|×1000 mg；可识别方向与比例误差。'],
        ['重要提醒','未对齐机械 P 前，不能直接把加速度计原始 XYZ 与平台参考 XYZ 逐轴相减。'],
        ['指标说明','GYRO 原始与校正模长偏差 = |ω_raw或ω_cal| - |ω_ref|，单位°/s。'],
        ['重要提醒','陀螺仪原始模长偏差受原始零偏及坐标耦合影响，仅作为诊断，不等于原始三轴向量误差。'],
        ['指标说明','GYRO 校正向量误差 = |K(ω_raw-b)-ω_ref|，单位°/s。零速工况不定义方向误差。'],
        ['数据来源','每行均为质量筛选后稳定时间段的平均值；参考量来自转台实际反馈与所选运动学模型。'],
        ['离群算法','先在每帧16点内按逐轴稳健MAD剔除异常，帧均值再次MAD筛除；ACC默认3σ、GYRO维持6σ，见工艺配置快照。'],
        ['结果有效性','即使质量门槛不通过，也必须展示对应批次报告；FAIL或试运行状态严禁作为正式出厂参数。'],
        ['数据分组','拟合（fit）不等同于独立验证（validate）；六轴复核为重新采集的数据。'],
        ['工况范围','报告只能证明实际列出的离散姿态和速率工况，不能自动外推到 20°/s、100°/s 或全温区。'],
        ['工艺声明','本报告使用工艺 '+str(result.get('quality_gate',{}).get('profile_id','未知'))+'；试运行候选通过不等于正式出厂放行。'],
    ]
    sheets.append(('指标解释',('报告口径、量纲及使用限制',meta,['项目','说明'],notes,{1:22,2:112})))
    suffix={'accel':'ACC','gyro':'GYRO','align':'IMU6'}[kind]
    path=Path(run_dir)/f'validation_comparison_{suffix}.xlsx'
    return _write_xlsx(path,sheets)
