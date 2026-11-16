# -*- coding: utf-8 -*-
"""三方案独立验证结果导出；只写本次实验目录，不影响原标定 latest 文件。"""
import csv
import json
import numpy as np
from pathlib import Path
from calibration_model_compare import MODEL_NAMES, serialize


def _wk_acc_pose_details(code, rows, fit):
    """Audit rows use per-pose mean frames from the original unmodified model."""
    bias=np.asarray(fit['bias'],float)
    matrix=np.asarray(fit['correction_matrix'],float)
    result=[]
    for r in rows:
        ref=np.asarray(r['reference'],float)
        raw=np.asarray(r['measured'],float)
        corrected=(raw-bias)@matrix.T
        direction=float(np.degrees(np.arccos(np.clip(
            np.dot(corrected,ref)/max(np.linalg.norm(corrected)*np.linalg.norm(ref),1e-12),-1,1))))
        result.append([code,r['step_id'],r.get('temperature_mean_c'),
            *ref.tolist(),*raw.tolist(),float(np.linalg.norm(raw)),
            float((np.linalg.norm(raw)-1.)*1000),
            *corrected.tolist(),float(np.linalg.norm(corrected)),
            float((np.linalg.norm(corrected)-1.)*1000),
            float(np.linalg.norm(corrected-ref)*1000),direction])
    return result


def save_model_comparison(run_dir, kind, result, device_sn=None):
    folder = Path(run_dir)
    folder.mkdir(parents=True, exist_ok=True)
    suffix = 'ACC' if kind == 'acc' else 'GYRO'
    prefix = f'{device_sn}_{suffix}_AMBIENT_MODEL_COMPARISON' if device_sn else f'model_comparison_{suffix.lower()}'
    json_path = folder / f'{prefix}.json'
    json_path.write_text(json.dumps(serialize(result), ensure_ascii=False, indent=2)+'\n',encoding='utf-8')
    lines=[]
    for code in MODEL_NAMES:
        model = result['models'].get(code)
        if model is None:
            lines.append([code, MODEL_NAMES[code], 'FIT_FAILED', None, None, None, None, None, None,
                          result.get('errors',{}).get(code,'')])
            continue
        v=model['independent_validation']; gate=model['quality_gate']
        lines.append([code, MODEL_NAMES[code],gate['verdict'],v['rmse_vector'],v['max_vector_error'],
                      v.get('max_direction_error_deg'),v.get('max_norm_error_g'),
                      v.get('max_cross_axis_dps'),v.get('max_zero_rate_residual_dps'),model['fit']['model_note']])
    header=['方案','方案说明','质量结论','独立验证矢量RMSE_g','最大矢量误差_g','最大方向误差_deg',
            '最大模长误差_g','GYRO最大交叉轴误差_dps','GYRO最大零速残差_dps','说明/异常']
    # Extend the original model-results sheet with fit *and* verification,
    # presenting 1g modulus error in mg independently from 3D vector error.
    wk_metrics=result.get('wk_metric_summary',{}) if kind=='acc' else {}
    if wk_metrics:
        header += ['拟合模长RMSE_mg','拟合向量RMSE_mg','验证模长RMSE_mg',
                   '验证向量RMSE_mg','标定前拟合模长RMSE_mg','标定前验证模长RMSE_mg']
        for row in lines:
            m=wk_metrics.get(row[0],{})
            tr=m.get('fit',{});va=m.get('validation',{})
            row.extend([tr.get('norm_rmse_mg'),tr.get('vector_rmse_mg'),
                        va.get('norm_rmse_mg'),va.get('vector_rmse_mg'),
                        tr.get('before_norm_rmse_mg'),va.get('before_norm_rmse_mg')])
        # Put the two norm RMSE metrics up front (D/E), where users see them
        # immediately. Keep the old vector-RMSE columns and notes to the right.
        report_order=[0,1,2,10,12,11,13,14,15,3,4,5,6,7,8,9]
        header=[header[i] for i in report_order]
        lines=[[row[i] for i in report_order] for row in lines]
    csv_path=folder/f'{prefix}.csv'
    with csv_path.open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.writer(f)
        writer.writerow(header)
        writer.writerows(lines)
    # Excel: 方案汇总 + 全部独立验证工况残差；无需用户上传已有标定文件。
    from calibration_excel_report import _write_xlsx
    detail_header=['模型','工况序号','参考X','参考Y','参考Z','校正X','校正Y','校正Z',
                   '误差X','误差Y','误差Z','矢量误差']
    detail=[]
    for code in MODEL_NAMES:
        model=result['models'].get(code)
        if model is None: continue
        for idx, point in enumerate(model['independent_validation']['vectors'],1):
            ref=point['reference']; corr=point['corrected']; err=point['error']
            detail.append([code,idx,*ref,*corr,*err,sum(float(x)**2 for x in err)**.5])
    if not detail:
        detail=[['所有候选模型拟合失败，未获得独立验证残差']]
    parameter_rows=[]
    for code in MODEL_NAMES:
        item=result['models'].get(code)
        if item is None:
            parameter_rows.append([code,'拟合失败',None,None,None,result.get('errors',{}).get(code,'')])
            continue
        fit=item['fit']
        parameter_rows.append([code,'零偏',*fit['bias'].tolist(),fit['model_note']])
        parameter_rows.append([code,'原始轴比例',*fit['axis_sensitivity'],'仅B/C矩阵包含额外方向项'])
        for label,key in [('正向P→Raw','forward_matrix'),('校正Raw→P','correction_matrix')]:
            for axis,values in zip('XYZ',fit[key]):
                parameter_rows.append([code,f'{label} {axis}',*values.tolist(),''])
        if fit['rotation_matrix'] is not None:
            for axis,values in zip('XYZ',fit['rotation_matrix']):
                parameter_rows.append([code,f'旋转R {axis}',*values.tolist(),'B方案刚体安装旋转'])
    sheets=[
        ('模型结果',('常温IMU三方案自动标定与独立测试',
                 '采用旧版A/B/C算法；拟合/验证模长RMSE与向量RMSE分别展示，单位不可混用。',header,lines,
                 {1:13,2:40,3:25,4:24,5:27,6:23,7:26,8:26,9:26,
                  10:26,11:24,12:26,13:25,14:26,15:27,16:70})),
        ('独立验证残差',('逐工况独立验证误差',
                 '校正后向量与转台参考坐标系P比较，未加入拟合过程。',detail_header,detail,{1:13,2:14})),
        ('参数矩阵',('逐方案参数与校正矩阵',
                 'A方案仅对应名义轴，B含SO(3)旋转，C为完整线性矩阵。',
                 ['方案','参数项','X/列1','Y/列2','Z/列3','说明'],parameter_rows,
                 {1:14,2:26,3:20,4:20,5:20,6:77})),
    ]
    if wk_metrics:
        metric_head=['模型','数据集','工况数','原始模长RMSE_mg','校正模长RMSE_mg',
                     '校正向量RMSE_mg','校正最大模长偏差_mg','校正最大向量误差_mg']
        metric_rows=[]
        for code in MODEL_NAMES:
            model=wk_metrics.get(code)
            if not model:
                metric_rows.append([code,'拟合失败',0,None,None,None,None,None]);continue
            for name,key in [('12个拟合姿态','fit'),('12个独立验证姿态','validation')]:
                m=model[key]
                metric_rows.append([code,name,m['count'],m['before_norm_rmse_mg'],
                                    m['norm_rmse_mg'],m['vector_rmse_mg'],
                                    m['norm_max_abs_mg'],m['vector_max_mg']])
        pose_head=['模型','工况','真实芯片温度℃','参考X_g','参考Y_g','参考Z_g',
                   '原始X_g','原始Y_g','原始Z_g','原始模长_g','原始模长偏差_mg',
                   '校正X_g','校正Y_g','校正Z_g','校正模长_g','校正模长偏差_mg',
                   '校正向量误差_mg','重力方向误差_deg']
        fit_pose=[];valid_pose=[]
        for code in MODEL_NAMES:
            mdl=result['models'].get(code)
            if not mdl:continue
            fit_pose.extend(_wk_acc_pose_details(code,result['wk_fit_rows'],mdl['fit']))
            valid_pose.extend(_wk_acc_pose_details(code,result['wk_validation_rows'],mdl['fit']))
        note_rows=[
            ['拟合姿态','12个工况仅用于A/B/C参数求解，拟合RMSE不等于独立验证RMSE。'],
            ['独立验证姿态','另外12个从未参与参数求解的姿态，用于实际泛化检查。'],
            ['模长RMSE_mg','1000 × sqrt(mean((||a_corrected|| - 1)^2))。旧转台2026-10-22报告模长验证RMSE为0.329mg，不是0.788mg。'],
            ['旧转台0.788mg的含义','它是旧报告独立验证三维向量RMSE；应与WK的独立验证三维向量RMSE对比，且需同一PCB、温度、姿态和采样口径。'],
            ['去噪方法','ACC每帧16样本约3×1.4826×MAD剔离群后均值，工况内5秒帧均值再作3×MAD筛选。仅剔离群，不消除系统姿态偏差。'],
            ['静态噪声门槛','工艺默认三轴帧均值标准差每轴≤0.025g（25mg），此为采样合格门槛，并非最终标定RMSE要求。'],
            ['三轴向量RMSE_mg','1000 × sqrt(mean(||a_corrected - g_reference||^2))；包含安装与轴系方向误差。'],
            ['原始模长RMSE_mg','1000 × sqrt(mean((||a_raw|| - 1)^2))，未进行任何标定。'],
            ['单位检查','模型结果原来的独立验证矢量RMSE列为g；新增列显式使用mg。'],
            ['原版C','完整3×3仿射拟合，拟合与独立验证的逐姿态原始/校正值可在对应表查看。'],
            ['结果边界','不同转台仅在同一PCB、装夹、温度、姿态和同口径情况下可归因比较。'],
            ['温度','单点对照使用实际芯片温度标签；不人为要求20～30℃；单次采样仍须稳定。'],
        ]
        audit_header=['数据集','工况','真实芯片温度℃','本姿态温漂℃',
                      '原始帧数','有效帧数','跨帧3σ剔除率','原始帧内ACC样本总数',
                      '两级筛选后ACC样本数','X帧均值标准差_mg','Y帧均值标准差_mg','Z帧均值标准差_mg',
                      '内轴目标°','内轴实测°','外轴目标°','外轴实测°','滤波方案','稳健σ倍率']
        audit_rows=[]
        for stage,key in [('拟合','wk_fit_rows'),('独立验证','wk_validation_rows')]:
            for r in result[key]:
                std=r.get('acc_std_g')
                std=[(float(x)*1000 if x is not None else None) for x in std] if std is not None else [None]*3
                audit_rows.append([stage,r['step_id'],r.get('temperature_mean_c'),r.get('temperature_span_c'),
                    r.get('frame_count'),r.get('accepted_frames'),r.get('reject_fraction'),
                    r.get('acc_raw_samples'),r.get('acc_accepted_samples'),*std,
                    r.get('inner_target_deg'),r.get('inner_actual_mean_deg'),
                    r.get('outer_target_deg'),r.get('outer_actual_mean_deg'),
                    r.get('filter_method'),r.get('filter_sigma')])
        sheets += [
            ('ACC采样去噪审计',('ACC各姿态采样3σ去噪与静止质量审计',
             '该表来自实测工况统计；旧Excel仅有每姿态均值时缺少逐帧审计信息，不可反推或虚构。',
             audit_header,audit_rows,{1:13,2:19,3:21,4:17,5:15,6:15,7:23,
                                      8:22,9:24,10:24,11:24,12:24,
                                      13:16,14:16,15:16,16:16,17:48,18:18})),
            ('ACC拟合与验证RMSE',('ACC拟合与独立验证 — 模长相对1g的RMSE（mg）',
             '旧版常温A/B/C算法不变；各模型12拟合、12验证；三维RMSE不同于模长RMSE。',
             metric_head,metric_rows,{1:13,2:28,3:13,4:24,5:24,6:24,7:28,8:26})),
            ('ACC拟合集逐姿态',('ACC 12拟合姿态 — 标定前后模长与向量比较',
             '各模型同一12姿态，记录每个工况实测芯片温度；模长相对1g单位mg。',
             pose_head,fit_pose,{1:12,2:20,3:20,11:22,16:22,17:22,18:22})),
            ('ACC验证集逐姿态',('ACC 12独立验证姿态 — 标定前后模长与向量比较',
             '各模型同一12独立姿态，未参与求参；模长相对1g单位mg。',
             pose_head,valid_pose,{1:12,2:20,3:20,11:22,16:22,17:22,18:22})),
            ('ACC指标解释',('旧版标定报告计算口径与拟合/验证拆分',
             '本工作簿为单点实验离线结果，不直接代表温补或整机动态倾角精度。',
             ['项目','解释'],note_rows,{1:29,2:115})),
        ]
    xlsx_path=folder/f'{prefix}.xlsx'
    _write_xlsx(xlsx_path,sheets)
    return [str(json_path),str(csv_path),str(xlsx_path)]


def save_selected_model(run_dir, kind, model_id, result, device_sn=None):
    sensor = 'ACC' if kind == 'acc' else 'GYRO'
    name=(f'{device_sn}_{sensor}_AMBIENT_MODEL_{model_id}_CANDIDATE.json' if device_sn else
          f'{"accel" if kind=="acc" else "gyro"}_model_{model_id}_candidate.json')
    path=Path(run_dir)/name
    path.write_text(json.dumps(serialize(result),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return str(path)
