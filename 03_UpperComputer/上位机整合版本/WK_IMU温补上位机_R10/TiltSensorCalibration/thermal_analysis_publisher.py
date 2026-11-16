# -*- coding: utf-8 -*-
"""Research-only per-sensor and combined 28-model reporting.

Legacy cubic training is OPTIONAL. It must not prevent a complete ACC dataset
from getting an independent 28-candidate report when GYRO is incomplete.
"""
from pathlib import Path
import json
from thermal_model_selection import run_thermal_model_selection
from thermal_excel_report import export_thermal_xlsx
from thermal_model_catalog import full_catalog


def publish_sensor_reports(folder, rows, temperatures, sensors=('acc','gyro'), source_folder=None, quality_warnings=None):
    """Create combined and independent reports, never approve MCU release."""
    root=Path(folder);root.mkdir(parents=True,exist_ok=True)
    quality_warnings=list(quality_warnings or [])
    source=Path(source_folder) if source_folder is not None else root
    selection=run_thermal_model_selection(root,rows,temperatures,tuple(sensors),source_folder=source)
    device_sn=selection.get('device_serial')
    # The original run's readiness audit is authoritative for planned vs
    # accepted steps. Never infer experiment completeness from row count alone.
    readiness_file=source/'thermal_result_readiness.json'
    try:
        readiness=json.loads(readiness_file.read_text(encoding='utf-8')) if readiness_file.is_file() else None
    except (OSError,ValueError):
        readiness=None
    summary={'sensors':{},'model_selection':selection,
             'result_readiness':readiness,
             'temperature_quality_warnings':quality_warnings,
             'report_scope':'RESEARCH_ONLY_COMPLETENESS_CHECKED_AT_CALL_SITE'}
    workbook=export_thermal_xlsx(root,rows,summary)
    outcomes={'combined_workbook':workbook,'independent':{},'selection':selection}
    for sensor in sensors:
        destination=root/('ACC_单独28方案报告' if sensor=='acc' else 'GYRO_单独28方案报告')
        destination.mkdir(exist_ok=True)
        report=run_thermal_model_selection(destination,rows,temperatures,(sensor,),source_folder=source)
        path=export_thermal_xlsx(destination,rows,{'sensors':{},'model_selection':report,
                         'temperature_quality_warnings':[w for w in quality_warnings if w['sensor']==sensor],
                         'result_readiness':readiness})
        label='ACC' if sensor=='acc' else 'GYRO'
        # A readable companion with all formulas and validation metrics; coefficients
        # live in Excel and per-model JSON, not rounded by the prose summary.
        detail=report['sensors'].get(sensor,{})
        candidates={x['id']:x for x in detail.get('candidates',[])}
        lines=[f'# {label} 28套温补模型独立分析报告（研发预览）','',
               '> 所有结果仅供研发验证；不代表MCU生产放行。','',
               f"- 实际选中模型：{detail.get('selected_id') or '无'}",
               f"- 选型状态：{detail.get('status_text',detail.get('status'))}",
               f"- 选型依据：{detail.get('selection_basis','见Excel原始评分列')}",
               f"- 数据状态：{'部分采集（不可发布）' if readiness and readiness.get('total_missing') else '请核对完整性检查'}",
               f"- 本传感器工况：{readiness['sensors'][sensor]['accepted']}/{readiness['sensors'][sensor]['planned']}" if readiness and sensor in readiness['sensors'] else '- 本传感器完整性：请查看原始实验清单',
               '- 数学定义：raw=F(Te)×reference+b(Te)；reference=F(Te)⁻¹×(raw−b(Te))。',
               '- 温度参数：p(Te)=Σp_k·(Te−25)^k；模型不允许外推。','',
               '## 28套模型逐项定义与评价','',
               '| 编号 | 温度表达式 | 参数结构 | 阶次 | 选型RMSE | 独立温度RMSE | 状态 |',
               '|---|---|---|---:|---:|---:|---|']
        for c in full_catalog():
            item=candidates.get(c['id'],{})
            train=item.get('selection_condition_validation',{})
            hold=item.get('independent_temperature_verification',{})
            def fmt(x):return f'{x:.7g}' if isinstance(x,(int,float)) else '未评估'
            reason=str(item.get('reason',item.get('status','数据不完整'))).replace('|','/')
            lines.append(f"| {c['id']} | {c['temperature_formula']} | {c['structure']} | {c['degree']} | "
                         f"{fmt(train.get('vector_rmse'))} | {fmt(hold.get('vector_rmse'))} | {reason} |")
        lines+=['','## 跨工况芯片温度一致性（重要研发风险）','',
                '温度跨度>0.6℃的同组记录在连续研发模式中不再自动删除，保留真实实测温度，'
                '但温度与姿态/转速耦合可能影响矩阵拟合。禁止仅凭该报告量产放行。','']
        for warning in quality_warnings:
            if warning['sensor']==sensor:
                lines.append(f"- {warning['temperature_target_c']:g}℃ {warning['sensor']}/{warning['split']}："
                             f"芯片跨度{warning['chip_span_c']:.3f}℃，"
                             f"风险等级{warning['severity']}，保留逐工况原始数据供研发复核。")
        lines+=['','## 验证口径与数据安全',
                '- 模型排行只根据拟合温度下的独立工况；独立温度不参与选型。',
                '- 如果少量验证点处于拟合芯片温度边界外，研发评分会显示排除数量，禁止使用这些点做外推。',
                '- 详细矩阵/零偏/温度校正系数见Excel“28模型实际拟合系数”及模型候选JSON。',
                '- 硬件转速质检通过不等于独立计量认证，需校核MCU量程、轴系和实际算法实现。']
        md=destination/(f'{device_sn}_{label}_28模型结构及排名_研发报告.md' if device_sn else f'{label}_28模型结构及排名_研发报告.md')
        md.write_text('\n'.join(lines)+'\n',encoding='utf-8')
        outcomes['independent'][sensor]={'workbook':path,'markdown':str(md),'selection':detail}
    manifest_name=(f'{device_sn}_THERMAL_REPORT_GENERATION_MANIFEST.json' if device_sn else 'report_generation_manifest.json')
    (root/manifest_name).write_text(json.dumps({
        'status':'RESEARCH_ONLY','device_serial':device_sn,'sensors':list(sensors),'combined_workbook':str(workbook),
        'independent_report_paths':{k:{key:val for key,val in v.items() if key!='selection'}
                                    for k,v in outcomes['independent'].items()},
        'production_release':False,'temperature_quality_warning_count':len(quality_warnings)},indent=2,ensure_ascii=False),encoding='utf-8')
    return outcomes
