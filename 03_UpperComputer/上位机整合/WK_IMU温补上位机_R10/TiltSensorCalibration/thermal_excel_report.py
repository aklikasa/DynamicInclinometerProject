# -*- coding: utf-8 -*-
"""Research-only thermal calibration workbook; no automatic release gate."""
from pathlib import Path
import json
import numpy as np
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.chart import BarChart, Reference
from thermal_model_catalog import full_catalog, INPUTS


def export_thermal_xlsx(folder, rows, summary):
    root=Path(folder)
    selection_meta=summary.get('model_selection') or {}
    device_sn=selection_meta.get('device_serial')
    from calibration_artifact_paths import thermal_filename, safe_device_sn
    if device_sn:
        device_sn=safe_device_sn(device_sn)
    wb=Workbook()
    overview=wb.active;overview.title='温补总览'
    overview.append(['动态倾角仪 IMU 自动温补报告（研发验证，不可直接量产放行）'])
    overview.append(['类别','状态','温补后 RMSE','单位','25℃固定矩阵 RMSE','备注'])
    readiness=summary.get('result_readiness')
    if readiness:
        overview.append(['数据完整性','已接受 '+str(readiness['total_accepted'])+'/'+str(readiness['total_planned'])
                         +'，缺失 '+str(readiness['total_missing']),
                         '有缺失时模型计算仅可作为研发预览，不能视为验证合格'])
        check=wb.create_sheet('结果可用性与缺失温度')
        check.append(['传感器','温度℃','温度角色','已接受工况','计划工况','缺失工况','完整性状态'])
        for item in readiness.get('per_temperature',[]):
            check.append([str(item.get('sensor','')).upper(),item.get('temperature_target_c'),
                          item.get('temperature_role'),item.get('accepted'),
                          item.get('planned'),item.get('missing'),
                          '完整' if item.get('fully_complete') else '缺失；不得视为验收合格'])
        check.append(['重要','本表来自实验完整计划与已接受检查点；模型拟合成功不等于数据完整/独立验证合格。'])
    issues=list(summary.get('temperature_quality_warnings',[]))
    if issues:
        overview.append(['温度质量风险','历史实验记录'+str(len(issues))+'组跨工况温差警告',
                         '该部分数据虽然保留，温度/姿态耦合尚需验证，不代表生产验收合格'])
    for sensor in ('acc','gyro'):
        d=summary.get('sensors',{}).get(sensor,{})
        if d:
            stat=d.get('temperature_holdout',{})
            overview.append([sensor.upper(),d.get('status','not_estimated'),
                             stat.get('vector_rmse'),stat.get('unit'),
                             d.get('fixed_25c_holdout',{}).get('vector_rmse'),d.get('reason','')])
        else:
            selected=summary.get('model_selection',{}).get('sensors',{}).get(sensor,{})
            candidates={c['id']:c for c in selected.get('candidates',[])}
            preferred=candidates.get(selected.get('selected_id'),{})
            a0=candidates.get('A0',{})
            eval_=preferred.get('independent_temperature_verification',{})
            baseline=a0.get('independent_temperature_verification',{})
            overview.append([sensor.upper(),selected.get('status_text',selected.get('status','未分析/数据不完整')),
                             eval_.get('vector_rmse'),'g' if sensor=='acc' else 'deg/s',
                             baseline.get('vector_rmse'),
                             '模型在拟合温度独立工况上选型；独立温度只做终验。参见《28模型逐项说明》。'])
    overview.append(['旧版三次模型','旧版完整矩阵三次拟合仅为可选诊断；不再阻止ACC/GYRO独立28模型报告。详细看《28套模型优选排名》和《28套模型逐项说明》。'])
    overview.append(['注意','温箱PLC IP通信保持原工程方式；设备联调和高转速连续行程必须单独实机验证。'])
    overview.append(['安全','报告不代表已通过设备联调、温度计量或量产验收。'])
    overview.append(['对照说明','25℃固定矩阵指温补拟合曲线在25℃的参数固定使用，不等于原常温C方案文件。'])
    if summary.get('model_selection'):
        method=summary['model_selection'].get('fit_strategy','legacy_two_stage')
        overview.append(['温度自变量与联合拟合口径',
                         'R7每个工况实测芯片均温T_i，全部拟合温度的12姿态组联合求F(T)/b(T)'
                         if method=='joint_complete_groups_per_condition_chip_T'
                         else '旧模式：每组求矩阵，再以组均温拟合多项式',
                         '温箱设定温度只用于分组和拟合/独立验证划分，不直接作为温补多项式自变量'])
        overview.append(['28套联合优选','A0固定参数+T0/T1/T2温度输入 × B/C/D参数结构 × 一二三次温补；无有效PV时T1/T2标记为不可用。'])
        overview.append(['温度输入定义','T0原始芯片温度；T1 PV等效线性校正；T2 PV等效二次校正，最终MCU只使用芯片温度。'])
        overview.append(['优选模型比较','详细结果见《28套模型优选排名》《28套模型逐项说明》《28模型实际拟合系数》《28候选分温度误差》《静态倾角精度对比》。'])
        for sensor, data in summary['model_selection'].get('sensors',{}).items():
            overview.append([sensor.upper()+' 自动模型优选',
                             data.get('selected_id') or '未选出',data.get('status_text',data.get('status')),
                             '最终独立温度验证只用于验收，未参与模型排名'])
    if summary.get('model_selection'):
        schedule=wb.create_sheet('温度工况计划')
        schedule.append(['温箱目标温度℃','温度角色','ACC标定工况数','ACC独立测试数',
                         'GYRO标定工况数','GYRO独立测试数','数据用途'])
        by_temp={}
        for record in rows:
            key=float(record['temperature_target_c'])
            info=by_temp.setdefault(key,{'role':record.get('temperature_split'),
                                          'acc_fit':0,'acc_validate':0,'gyro_fit':0,'gyro_validate':0})
            if info['role']!=record.get('temperature_split'):
                raise ValueError(f'温度 {key:g}℃ 同时被标记为拟合和独立验证，拒绝生成报告')
            field=f'{record["sensor"]}_{record["split"]}'
            if field in info:
                info[field]+=1
        for setpoint,info in sorted(by_temp.items()):
            role=info['role']
            schedule.append([setpoint,'模型拟合' if role=='fit' else '独立温度验证',
                             info['acc_fit'],info['acc_validate'],
                             info['gyro_fit'],info['gyro_validate'],
                             '拟合参数+模型选型' if role=='fit' else '只用于最终温度验收，不参与拟合或排名'])
        schedule.append(['备注','这张表为已完成并保存的工况统计，不能代表未完成工况的计划数量。'])
        schedule.append(['安全','验证温度与拟合温度采用相同的PLC、PV和芯片温度稳定检查。'])
    audit=wb.create_sheet('温度质量审计')
    audit.append(['设定温度℃','传感器','拟合/验证','芯片温差℃','芯片最低℃','芯片最高℃','工况数',
                  '风险级别','处置','说明'])
    issues=list(summary.get('temperature_quality_warnings',[]))
    # R7 records ALL complete group spans, including 2C+ differences, as facts.
    # These are NOT quality gates; accepted poses remain part of a joint fit.
    if not issues:
        groups={}
        for r in rows:
            if r.get('group_temperature_audit')=='INFO_ONLY_NOT_AN_INVALIDATION':
                key=(float(r['temperature_target_c']),r['sensor'],r['split'])
                groups.setdefault(key,[]).append(r)
        for (setpoint,sensor,split),group in sorted(groups.items()):
            die_t=[float(r['temperature_mean_c']) for r in group]
            if len(die_t)<2:continue
            issues.append({'temperature_target_c':setpoint,'sensor':sensor,'split':split,
                           'chip_span_c':max(die_t)-min(die_t),
                           'chip_min_c':min(die_t),'chip_max_c':max(die_t),
                           'count':len(group),'severity':'INFO（不是拒收阈值）',
                           'decision':'KEEP_COMPLETE_GROUP',
                           'note':'12姿态组完整性仍必须通过；各工况独立实测芯片均温作为联合拟合输入'})
    for issue in issues:
        audit.append([issue.get('temperature_target_c'),issue.get('sensor'),issue.get('split'),
                      issue.get('chip_span_c'),issue.get('chip_min_c'),issue.get('chip_max_c'),
                      issue.get('count'),issue.get('severity'),issue.get('decision'),issue.get('note')])
    if not issues:
        audit.append(['无可用组间温度记录','不等于已完成生产热循环验收'])
    audit.append(['必须了解','本实验所用温补模型报告仅供研发；芯片温度与姿态/速率相关会影响模型可辨识性。'])
    coverage=wb.create_sheet('GYRO速率覆盖及缺失概览')
    coverage.append(['温度用途','速率用途','速率幅值(°/s)','正向已接受数','反向已接受数','合计','说明'])
    observed={}
    for r in rows:
        if r.get('sensor')!='gyro' or r.get('mode')!='rate' or r.get('target_rate_dps') is None:
            continue
        split=r.get('temperature_split')
        mode=r.get('split')
        speed=float(r['target_rate_dps'])
        k=(split,mode,round(abs(speed),6))
        d=observed.setdefault(k,[0,0])
        d[0 if speed>0 else 1]+=1
    for (split,mode,rate),counts in sorted(observed.items(),key=lambda t:(t[0][0]=='validate',t[0][1]=='validate',t[0][2])):
        label='拟合温度' if split=='fit' else '独立验证温度'
        use='模型拟合' if mode=='fit' else '独立工况验证'
        coverage.append([label,use,rate,counts[0],counts[1],sum(counts),
                         '低速≤5°/s；本表仅表示已接受采样数，不代表全部计划都成功' if rate<=5 else ''])
    coverage.append(['说明','速率配置来自每次实验的拟合/验证列表，非写死的点位；每个幅值按三轴、正反方向执行。'])
    coverage.append(['提示','低速数据可增加低速性能的验证覆盖，但实际精度仍需看独立工况RMSE。'])
    coverage.append(['缺失','本表不能替代检查点和不完整报告；未接受的工况不计入。'])
    ws=wb.create_sheet('逐工况测量')
    ws.append(['温度设定°C','拟合/温度验证','工况编号','ACC/GYRO','姿态/动态','拟合/工况验证',
               '芯片温度°C','内轴角°','外轴角°','内轴速率°/s','外轴速率°/s',
               '参考X','参考Y','参考Z','实测X','实测Y','实测Z','有效帧','总帧',
               '目标速率°/s','转动轴','实测减目标°/s','温补后向量误差°/s','25°C固定矩阵误差°/s','评价数据口径'])
    gyro_model=None
    model_path=root/(thermal_filename(device_sn,'gyro','candidate') if device_sn else 'thermal_gyro_candidate.json')
    if model_path.exists():
        with model_path.open('r',encoding='utf-8') as f:
            gyro_model=json.load(f)
    for r in rows:
        measure=r.get('acc_raw_mean_g') if r.get('sensor')=='acc' else r.get('gyro_raw_mean_dps')
        target=r.get('target_rate_dps')
        axis=r.get('rotation_axis')
        measured_rate=(r.get('inner_rate_mean_dps') if axis=='inner' else
                       r.get('outer_rate_mean_dps') if axis=='outer' else None)
        deviation=(float(measured_rate)-float(target)) if target is not None and measured_rate is not None else None
        thermal_error=None
        fixed_error=None
        scope=''
        if r.get('sensor')=='gyro' and r.get('mode')=='rate':
            ts, cs=r.get('temperature_split'),r.get('split')
            scope=('拟合温度/拟合速率(训练数据)' if ts=='fit' and cs=='fit' else
                   '拟合温度/独立速率验证' if ts=='fit' and cs=='validate' else
                   '独立温度/独立速率验证' if ts=='validate' and cs=='validate' else
                   '独立温度/拟合速率(仅诊断)')
            if gyro_model is not None:
                # 报告诊断值；主评价依然以热补模型 JSON 的独立验证结果为准。
                from thermal_compensation import _eval_poly
                temp=float(r['temperature_mean_c'])
                F=np.asarray(_eval_poly(gyro_model['forward_coeff'],temp),float)
                b=np.asarray(_eval_poly(gyro_model['bias_coeff'],temp),float)
                F25=np.asarray(_eval_poly(gyro_model['forward_coeff'],25.0),float)
                b25=np.asarray(_eval_poly(gyro_model['bias_coeff'],25.0),float)
                raw=np.asarray(measure,float)
                ref=np.asarray(r['reference'],float)
                thermal_error=float(np.linalg.norm(np.linalg.solve(F,raw-b)-ref))
                fixed_error=float(np.linalg.norm(np.linalg.solve(F25,raw-b25)-ref))
        ws.append([r['temperature_target_c'],r['temperature_split'],r['step_id'],r['sensor'],r['mode'],
                   r['split'],r['temperature_mean_c'],r['inner_actual_mean_deg'],r['outer_actual_mean_deg'],
                   r['inner_rate_mean_dps'],r['outer_rate_mean_dps'],*r['reference'],*measure,
                   r['accepted_frames'],r['frame_count'],target,axis,deviation,
                   thermal_error,fixed_error,scope])
    # The comparison sheets are appended only for the upgraded workstation;
    # legacy report clients that pass a plain summary retain the old layout.
    selection=summary.get('model_selection')
    if selection:
        best=wb.create_sheet('模型自动比较')
        best.append(['传感器','候选编号','补偿模型','温度阶数','选型工况RMSE','选型工况最大误差',
                     '复杂度评分','独立温度RMSE','独立温度最大误差','误差单位','是否被选中','状态/不可用原因',
                     '温度输入编号','温度输入描述'])
        for sensor in ('acc','gyro'):
            detail=selection.get('sensors',{}).get(sensor,{})
            if not detail.get('candidates'):
                best.append([sensor.upper(),'', '未完成比较',None,None,None,None,None,None,
                             'g' if sensor=='acc' else 'deg/s','否',detail.get('reason',detail.get('status','无数据')),'',''])
                continue
            for item in detail['candidates']:
                train=item.get('selection_condition_validation',{})
                test=item.get('independent_temperature_verification',{})
                best.append([sensor.upper(),item['id'],item['name'],item['degree'],
                             train.get('vector_rmse'),train.get('vector_max'),
                             item.get('selection_score'),test.get('vector_rmse'),
                             test.get('vector_max'), 'g' if sensor=='acc' else 'deg/s',
                             (('独立温度验证改善' if detail.get('status')=='INDEPENDENT_TEMPERATURE_IMPROVEMENT_CONFIRMED_RESEARCH_ONLY'
                               else '固定参数排名第一' if detail.get('status')=='BASELINE_PREFERRED_NO_TEMPERATURE_COMPENSATION'
                               else '排名第一但最终未通过') if item['id']==detail.get('selected_id') else ''),
                             item.get('reason',item.get('status')),
                             item.get('temperature_input_id'),item.get('temperature_input_name')])
        # Full 28-model explanation, readable without decoding model IDs.
        catalog=wb.create_sheet('28套模型逐项说明')
        catalog.append(['传感器','候选编号','温度输入类型','温度输入公式','结构类别','多项式阶数',
                        '完整测量校正公式','F矩阵及零偏实际结构','哪些参数会随温度改变',
                        '每参数温度多项式范式','估计参数个数','额外温度映射系数个数',
                        '选型工况RMSE','独立温度RMSE','独立温度最大误差','选型评分','模型状态/原因','使用说明'])
        catalog_rows=full_catalog()
        for sensor in ('acc','gyro'):
            detail=selection.get('sensors',{}).get(sensor,{})
            candidates={c['id']:c for c in detail.get('candidates',[])}
            for entry in catalog_rows:
                item=candidates.get(entry['id'],{})
                select=item.get('selection_condition_validation',{})
                verify=item.get('independent_temperature_verification',{})
                catalog.append([sensor.upper(),entry['id'],entry['input_name'],entry['temperature_formula'],
                     entry['family'],entry['degree'],entry['calibration_formula'],entry['structure'],
                     entry['change'],entry['parameter_polynomial'],entry['parameter_count'],
                     entry['input_coeff_count'],select.get('vector_rmse'),verify.get('vector_rmse'),
                     verify.get('vector_max'),item.get('selection_score'),
                     item.get('reason',item.get('status','该传感器未完成评估')),entry['note']])
        coefficients=wb.create_sheet('28模型实际拟合系数')
        coefficients.append(['传感器','模型编号','参数种类','轴/矩阵行(0起)','矩阵列(0起)',
                             '多项式系数阶k','拟合系数值','解释'])
        for sensor in ('acc','gyro'):
            path=root/(thermal_filename(device_sn,sensor,'models') if device_sn else f'thermal_{sensor}_model_candidates.json')
            if not path.is_file():
                coefficients.append([sensor.upper(),'无可用模型',None,None,None,None,None,
                                     '缺失工况或无效模型；不允许伪造参数'])
                continue
            models=json.loads(path.read_text(encoding='utf-8'))
            for mid, model in sorted(models.items()):
                for i, vector in enumerate(model.get('bias_coeff',[])):
                    for k,value in enumerate(vector):
                        coefficients.append([sensor.upper(),mid,'零偏 b',i,None,k,float(value),
                            f'b[{i}](Te) 第{k}阶；以(Te−25)^k展开'])
                for i,matrix_row in enumerate(model.get('forward_coeff',[])):
                    for j,vector in enumerate(matrix_row):
                        for k,value in enumerate(vector):
                            coefficients.append([sensor.upper(),mid,'正向矩阵 F',i,j,k,float(value),
                                f'F[{i},{j}](Te) 第{k}阶；以(Te−25)^k展开'])
                transform=model.get('temperature_input',{})
                for k,value in enumerate(transform.get('coefficients_c',[])):
                    coefficients.append([sensor.upper(),mid,'芯片→等效温度映射',None,None,k,float(value),
                        'Te=25+Σc[k]·((Tchip−25)/50)^k'])
        qa=wb.create_sheet('实验质检阈值说明')
        qa.append(['项目','数值/来源','解读'])
        config_path=(root/'experiment_config.json')
        if not config_path.is_file() and root.name=='PARTIAL_ONLY_COMPLETE_SENSORS_RESEARCH':
            config_path=root.parent/'experiment_config.json'
        if config_path.is_file():
            config=json.loads(config_path.read_text(encoding='utf-8'))
            quality=config.get('resume_immutable_config',{}).get('quality_profile',{}).get('quality',{})
            for key in ('rate_reference_std_max_dps','rate_reference_high_speed_std_max_dps',
                        'rate_reference_high_speed_start_dps','rate_reference_error_max_dps',
                        'rate_reference_half_slope_difference_max_dps',
                        'rate_reference_position_residual_rms_max_deg','rate_gyro_std_max_dps',
                        'temperature_span_max_c'):
                qa.append([key,quality.get(key,'原始实验未记录'), '配置在实验启动时冻结；更改只影响新实验'])
        else:
            qa.append(['配置文件','无','仅模型结果；具体质检阈值见原始实验配置'])
        qa.append(['参考速度','来自独立编码器轮询','不能由待标定IMU替代转台速度质量参考'])
        qa.append(['结果级别','RESEARCH_ONLY','实际测量误差与量产批准为不同概念'])
        qa.append(['数据边界','拒绝模型温度外推','少量越界验证数据仅可明确排除并作为研发预览评分'])
        explain=wb.create_sheet('模型计算与参数解读')
        explain.append(['步骤/条目','实现公式或说明'])
        for row in [
            ('符号','Tchip：运行时IMU芯片温度(°C)；Te：经T0/T1/T2定义的有效温度'),
            ('T0',INPUTS['T0'][1]),('T1',INPUTS['T1'][1]),('T2',INPUTS['T2'][1]),
            ('参数拟合','F_ij(Te)或b_i(Te)=Σ[k=0…d] p_k·(Te−25)^k；未变化的参数为常数'),
            ('正向测量模型','raw=F(Te)×reference+b(Te)'),
            ('运行时补偿','reference=inv(F(Te))×(raw−b(Te))；矩阵求逆/线性解需校验条件数'),
            ('A0','只在25℃参考实测拟合，常数12个参数；完全无温度补偿'),
            ('B','3个零偏随温度，F矩阵9个参数恒定'),
            ('C','3个零偏+3个比例因子随温度；6个非对角耦合系数保持常数'),
            ('D','3个零偏+3×3矩阵全部随温度变化'),
            ('选型','只用拟合温度下独立工况；得分=RMSE×(1+0.02阶数+0.025复杂度+0.02温度映射复杂度)'),
            ('独立验收','独立温度未用于拟合和选型；被选中的模型还需比较独立温度误差'),
            ('参数个数','A=12；B=9+3(d+1)；C=6+6(d+1)；D=12(d+1)；不含输入温度映射系数'),
            ('有效温区','严格限于实测拟合芯片温度最小～最大值；超出时禁止外推'),
            ('计量声明','本报告为研发候选；未核实MCU温度换算、量程与轴定义前不得烧录量产'),
        ]:explain.append(list(row))
        # Explicit selection ranking is not the holdout ranking (prevents test leakage).
        ranking=wb.create_sheet('28套模型优选排名')
        ranking.append(['传感器','选型名次','模型编号','模型系列','温度输入','阶数',
                        '选型工况RMSE','模型复杂度调整评分（越小越优）','独立温度RMSE（只验收）',
                        '独立温度最大误差','参与选型工况数','越界排除数','评价状态'])
        pertemp=wb.create_sheet('28候选分温度误差')
        pertemp.append(['传感器','模型编号','口径','温度设定°C','工况数','RMSE','最大误差','单位','超出拟合温区被排除数'])
        for sensor in ('acc','gyro'):
            detail=selection.get('sensors',{}).get(sensor,{})
            available=[c for c in detail.get('candidates',[]) if c.get('status')=='candidate_evaluated']
            available=sorted(available,key=lambda c:(c['selection_score'],c['degree'],c['id']))
            for rank,c in enumerate(available,1):
                select=c.get('selection_condition_validation',{})
                verify=c.get('independent_temperature_verification',{})
                ranking.append([sensor.upper(),rank,c['id'],c['family'],c['temperature_input_id'],
                                c['degree'],select.get('vector_rmse'),c['selection_score'],
                                verify.get('vector_rmse'),verify.get('vector_max'),
                                select.get('count'),select.get('excluded_out_of_range_count',0),
                                ('选型第一，独立验证状态：'+detail.get('status_text','')) if rank==1
                                else '拟合温度下独立工况选型分数'])
            for c in detail.get('candidates',[]):
                for label,scope in (('拟合温度独立工况（选型）','selection_condition_validation'),
                                    ('独立温度独立工况（终验）','independent_temperature_verification')):
                    m=c.get(scope,{})
                    for target,record in sorted(m.get('per_setpoint',{}).items(),key=lambda item:float(item[0])):
                        pertemp.append([sensor.upper(),c['id'],label,float(target),record.get('count'),
                                        record.get('vector_rmse'),record.get('vector_max'),
                                        'g' if sensor=='acc' else 'deg/s',
                                        m.get('excluded_out_of_range_count',0)])
        # Selection visual is based on selection score only; held-out results
        # are intentionally NOT mixed into the chart ranking.
        for sensor,row0 in (('acc',2),('gyro',2+sum(1 for x in selection.get('sensors',{}).get('acc',{}).get('candidates',[])
                                              if x.get('status')=='candidate_evaluated'))):
            count=sum(1 for x in selection.get('sensors',{}).get(sensor,{}).get('candidates',[])
                      if x.get('status')=='candidate_evaluated')
            if count>=3:
                top=min(10,count)
                chart=BarChart()
                chart.type='bar'
                chart.title=sensor.upper()+' 前10候选：选型评分（非独立温度误差）'
                chart.y_axis.title='模型编号'
                chart.x_axis.title='RMSE×复杂度惩罚'
                chart.add_data(Reference(ranking,min_col=8,min_row=row0,max_row=row0+top-1),titles_from_data=False)
                chart.set_categories(Reference(ranking,min_col=3,min_row=row0,max_row=row0+top-1))
                chart.width=19;chart.height=9
                ranking.add_chart(chart,'O2' if sensor=='acc' else 'O22')
        # Temperature input choices: PV is reference data during lab fitting ONLY.
        # None of these formulas needs PV at runtime.
        transforms=selection.get('temperature_input_candidates',{})
        tw=wb.create_sheet('芯片温度校正')
        tw.append(['温度输入编号','说明','拟合状态','校正阶数','芯片温度中心°C','归一化尺度°C',
                   '系数c0','系数c1','系数c2','PV拟合RMSE°C','有效芯片温区°C','说明/异常'])
        for key in ('T0','T1','T2'):
            value=transforms.get(key,{})
            coeff=value.get('coefficients_c',[])
            tw.append([key,value.get('name'),('不可用' if value.get('error') else '可用'),
                       value.get('degree'),value.get('temperature_center_c'),
                       value.get('temperature_scale_c'),
                       *(coeff+[None]*3)[:3],value.get('pv_fit_rmse_c'),
                       str(value.get('chip_temperature_fit_range_c','')),
                       value.get('error',value.get('warning',value.get('formula')))])
        tw.append([])
        tw.append(['数据来源','原始实验 imu_frame_means.csv 中每帧同步记录的 chamber_pv_c / imu_temp_c'])
        tw.append(['PV适用范围','仅拟合温度、仅标定工况用于计算校正系数；独立温度PV不参与校正训练'])
        tw.append(['重要提示','PV等效温度不是芯片结温绝对真值；线性校正与直接用原始芯片温度的同阶多项式表达能力等价。'])
        raw_status=selection.get('pv_telemetry',{})
        tw.append(['PV原始记录状态',raw_status.get('status'), '匹配工况数',raw_status.get('matched'),
                   '无效帧数',raw_status.get('invalid_raw_frames')])
        tw.append([])
        tw.append(['训练温度点°C','芯片实测°C','温箱实测PV°C','T1预测°C','T2预测°C','差值PV-芯片°C'])
        from thermal_temperature_inputs import map_chip_temperature
        pairs=transforms.get('T1',{}).get('fit_training_pairs',[]) or transforms.get('T2',{}).get('fit_training_pairs',[])
        for record in pairs:
            chip=float(record['chip_temperature_c'])
            pv=float(record['pv_temperature_c'])
            predicted=[]
            for tid in ('T1','T2'):
                transform=transforms.get(tid,{})
                try:
                    predicted.append(None if transform.get('error') else map_chip_temperature(transform,chip))
                except (ValueError,KeyError,TypeError):
                    predicted.append(None)
            tw.append([record['setpoint_c'],chip,pv,*predicted,pv-chip])
        compare=wb.create_sheet('逐温度误差比较')
        compare.append(['传感器','数据口径','温度设定°C','固定参数RMSE','优选温补RMSE','RMSE改善率',
                        '固定参数最大误差','优选温补最大误差','最大误差改善率','单位','模型编号','验证状态'])
        tilt=wb.create_sheet('静态倾角精度对比')
        tilt.append(['数据口径','温度设定°C','固定参数重力方向角RMSE(°)',
                     '优选温补重力方向角RMSE(°)','角RMSE改善率',
                     '固定参数最大角误差(°)','优选温补最大角误差(°)',
                     '评价说明'])
        for sensor in ('acc','gyro'):
            detail=selection.get('sensors',{}).get(sensor,{})
            candidates={x['id']:x for x in detail.get('candidates',[])}
            baseline=candidates.get('A0',{})
            chosen=candidates.get(detail.get('selected_id'),{})
            for scope,field in (('拟合温度/独立工况（用于选型）','selection_condition_validation'),
                                ('独立温度/独立工况（最终验收）','independent_temperature_verification')):
                bm=baseline.get(field,{})
                cm=chosen.get(field,{})
                bp=bm.get('per_setpoint',{})
                cp=cm.get('per_setpoint',{})
                for t in sorted(set(bp)|set(cp),key=float):
                    old,new=bp.get(t,{}),cp.get(t,{})
                    v0,v1=old.get('vector_rmse'),new.get('vector_rmse')
                    x0,x1=old.get('vector_max'),new.get('vector_max')
                    change=100*(v0-v1)/v0 if v0 is not None and v1 is not None and v0>0 else None
                    max_change=100*(x0-x1)/x0 if x0 is not None and x1 is not None and x0>0 else None
                    compare.append([sensor.upper(),scope,float(t),v0,v1,change,x0,x1,max_change,
                                    'g' if sensor=='acc' else 'deg/s',
                                    detail.get('selected_id'),detail.get('status_text',detail.get('status'))])
                    if sensor=='acc':
                        av0,av1=(old.get('static_gravity_direction_angle_rmse_deg'),
                                 new.get('static_gravity_direction_angle_rmse_deg'))
                        mx0,mx1=(old.get('static_gravity_direction_angle_max_deg'),
                                 new.get('static_gravity_direction_angle_max_deg'))
                        ac=100*(av0-av1)/av0 if av0 is not None and av1 is not None and av0>0 else None
                        tilt.append([scope,float(t),av0,av1,ac,mx0,mx1,
                                     '静态ACC重力矢量方向夹角；不是整机融合算法动态倾角'])
        desc=wb.create_sheet('结论与数据边界')
        desc.append(['项目','结论/限制'])
        desc.append(['排名口径','只用拟合温度下的独立工况验证；独立温度数据不参与模型选型'])
        desc.append(['模型','A0固定参数；T0原始芯片温度；T1/T2通过拟合温度下PV建立等效温度关系；B仅零偏；C零偏及比例因子；D完整矩阵'])
        desc.append(['候选模型','ACC/GYRO各28套（A0 + T0/T1/T2 × B/C/D × 1/2/3次）；数据不足时列为不可用，不强行推荐'])
        desc.append(['过拟合保护','一二三次温补分别要求至少3/4/5个拟合温度点，三次不能用4个点纯插值并宣称最优'])
        desc.append(['部署温度输入','真正运行只需要芯片温度，选T1/T2时先做PV等效校正；永远不需要温箱PV'])
        desc.append(['温度校正参考','温箱PV不一定等于真实芯片温度；非线性转换须检查单调性和可部署范围'])
        desc.append(['参考基准','A0不等于从外部常温标定JSON读取的参数；以报表具体基准测量温度为准'])
        desc.append(['温度范围','严格限制在参与拟合温度点的芯片实测温度区间，拒绝外推'])
        desc.append(['最终状态','推荐候选不等于温度独立验证通过，更不等于量产放行'])
        desc.append(['静态倾角','静态加速度计重力方向夹角误差可以从现有姿态数据计算；用于评估ACC静态方向精度'])
        desc.append(['动态倾角','现有逐工况统计不足以给出融合算法的动态倾角误差；需同步时序ACC/GYRO/参考姿态和明确的产品解算算法'])
        desc.append(['硬件验证','本软件结果不代替温箱、转台、硬件急停及全温区实机联调'])
        for sensor, data in selection.get('sensors',{}).items():
            desc.append([sensor.upper()+'选型',
                         str(data.get('selected_id'))+' / '+str(data.get('status_text',data.get('status')))])
            if data.get('baseline_definition'):
                desc.append([sensor.upper()+'基准',data['baseline_definition']])
        deployment=wb.create_sheet('MCU部署说明')
        deployment.append(['项目','内容'])
        deployment.append(['重要','研发候选！本工具不自动向MCU写入参数，不是生产批准。'])
        deployment.append(['温度输入','运行时唯一温度输入为IMU芯片温度（°C），不读取温箱PV。'])
        deployment.append(['校正温度公式','若选T1/T2：T_effective = 25 + Σ c[k] * ((T_chip - 25)/50)^k'])
        deployment.append(['标定参数公式','p(T_effective) = Σ p_coeff[k] * (T_effective - 25)^k'])
        deployment.append(['校正测量公式','reference = inverse(F(T_effective)) @ (raw - b(T_effective))'])
        deployment.append(['芯片温度范围','必须限制在fit_temperature_range_c，超出拒绝外推。'])
        deployment.append(['参数文件',('；'.join(thermal_filename(device_sn,s,'selected') for s in ('acc','gyro')) if device_sn else 'thermal_acc_selected_candidate.json；thermal_gyro_selected_candidate.json')])
        for sensor in ('acc','gyro'):
            info=selection.get('sensors',{}).get(sensor,{})
            deployment.append([sensor.upper()+'选中模型',info.get('selected_id') or '无；数据不足'])
            deployment.append([sensor.upper()+'验收状态',info.get('status_text',info.get('status'))])
            deployment.append([sensor.upper()+'温度输入',info.get('selected_temperature_input_id') or ''])
        deployment.append(['额外前提','写入MCU前需量程、轴定义、矩阵可逆性、系数精度和代码计算一致性验证。'])
        for tab in (best,compare,tilt,desc,tw,deployment,catalog,coefficients,qa,explain,ranking,pertemp):
            tab.auto_filter.ref=f'A1:{tab.cell(1,tab.max_column).column_letter}{tab.max_row}'
        # Remove a candidate from highlighting if it has not actually passed
        # the final independent temperature check; keep selection visible.
        for row in best.iter_rows(min_row=2):
            if row[10].value:
                for cell in row:
                    cell.fill=PatternFill('solid',fgColor='E3EDF4')
    for tab in wb.worksheets:
        tab.freeze_panes='A3' if tab is overview else 'A2'
        tab.auto_filter.ref=(f'A1:{get_column_letter(tab.max_column)}{tab.max_row}'
                              if tab is not overview and tab.max_row>1 else None)
        tab.row_dimensions[1].height=26
        for cell in tab[1]:
            cell.font=Font(name='微软雅黑',size=11,bold=True,color='FFFFFF')
            cell.fill=PatternFill('solid',fgColor='254B67')
            cell.alignment=Alignment(vertical='center')
        for col in tab.columns:
            key=col[0].column_letter
            tab.column_dimensions[key].width=(20 if tab==ws else (24 if tab.title=='模型自动比较' else 28))
        for row in tab.iter_rows(min_row=2):
            for cell in row:
                if isinstance(cell.value,float):
                    cell.number_format='0.000000'
                cell.alignment=Alignment(vertical='center',wrap_text=(tab.title=='结论与数据边界'))
        if tab.title=='结论与数据边界':
            tab.column_dimensions['A'].width=22
            tab.column_dimensions['B'].width=100
        if tab.title=='模型自动比较':
            tab.column_dimensions['C'].width=29
            tab.column_dimensions['L'].width=48
            tab.column_dimensions['M'].width=16
            tab.column_dimensions['N'].width=24
        if tab.title in ('芯片温度校正','MCU部署说明','温度工况计划'):
            tab.column_dimensions['A'].width=25
            tab.column_dimensions['B'].width=40
            if tab.title=='芯片温度校正':
                tab.column_dimensions['L'].width=72
        if tab.title=='静态倾角精度对比':
            tab.column_dimensions['H'].width=68
        if tab.title=='28套模型逐项说明':
            for key in ('D','G','H','I','J','R'):tab.column_dimensions[key].width=64
            tab.column_dimensions['Q'].width=48
            for row in tab.iter_rows(min_row=2):
                for cell in row:cell.alignment=Alignment(vertical='top',wrap_text=True)
                tab.row_dimensions[row[0].row].height=55
        if tab.title=='模型计算与参数解读':
            tab.column_dimensions['A'].width=30
            tab.column_dimensions['B'].width=106
        if tab.title=='实验质检阈值说明':
            tab.column_dimensions['A'].width=58
            tab.column_dimensions['B'].width=26
            tab.column_dimensions['C'].width=90
        if tab.title=='28模型实际拟合系数':
            tab.column_dimensions['H'].width=55
        if tab.title=='28套模型优选排名':
            tab.column_dimensions['M'].width=65
        if tab.title=='28候选分温度误差':
            tab.column_dimensions['C'].width=44

    path=root/(f'{device_sn}_THERMAL_CALIBRATION_REPORT.xlsx' if device_sn else 'thermal_calibration_report.xlsx')
    wb.save(path)
    return str(path)
