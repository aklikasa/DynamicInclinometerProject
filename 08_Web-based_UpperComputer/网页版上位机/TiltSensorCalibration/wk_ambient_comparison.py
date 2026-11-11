# -*- coding: utf-8 -*-
"""Same ambient IMU A/B/C fits and reports on 2FDT600WK, with honest norm RMS.

Pure reporting module. It never sends PLC/turntable commands and never writes
original room-temperature calibration parameter or *_latest files.
"""
import csv
import datetime
import json
from pathlib import Path
import numpy as np
from calibration_model_compare import compare_models, MODEL_NAMES, serialize
from model_comparison_report import save_model_comparison


def ambient_comparison_rows(all_rows, kind):
    sensor = 'acc' if kind == 'acc' else 'gyro'
    rows = []
    for r in all_rows:
        if r.get('sensor') != sensor:
            continue
        measured = r.get('acc_raw_mean_g' if sensor == 'acc' else 'gyro_raw_mean_dps')
        audit_keys=('frame_count','accepted_frames','acc_raw_samples','acc_accepted_samples',
                    'reject_fraction','acc_std_g','temperature_span_c',
                    'inner_actual_mean_deg','outer_actual_mean_deg',
                    'inner_target_deg','outer_target_deg','filter_method','filter_sigma')
        rows.append({'step_id': r['step_id'], 'split': r['split'],
                     'reference': r['reference'], 'measured': measured,
                     'temperature_mean_c': r.get('temperature_mean_c'),
                     **{key:r.get(key) for key in audit_keys}})
    return ([r for r in rows if r['split'] == 'fit'],
            [r for r in rows if r['split'] == 'validate'])


def metrics_for_model(rows, fit):
    refs = np.asarray([r['reference'] for r in rows], float)
    raw = np.asarray([r['measured'] for r in rows], float)
    if not len(raw) or not np.isfinite(refs).all() or not np.isfinite(raw).all():
        raise ValueError('无可用三轴数据或数据包含NaN/Inf')
    bias = np.asarray(fit['bias'],float)
    corr = np.asarray(fit['correction_matrix'],float)
    calibrated = (raw-bias)@corr.T
    diff = calibrated-refs
    result = {'count': len(rows),
              'before_norm_rmse_mg':float(1000*np.sqrt(np.mean((np.linalg.norm(raw,axis=1)-1)**2))),
              'before_vector_rmse_mg':float(1000*np.sqrt(np.mean(np.sum((raw-refs)**2,axis=1)))),
              'vector_rmse_mg': float(1000*np.sqrt(np.mean(np.sum(diff**2,axis=1)))),
              'norm_rmse_mg':float(1000*np.sqrt(np.mean((np.linalg.norm(calibrated,axis=1)-1)**2))),
              'norm_max_abs_mg':float(1000*np.max(np.abs(np.linalg.norm(calibrated,axis=1)-1))),
              'vector_max_mg':float(1000*np.max(np.linalg.norm(diff,axis=1)))}
    return result


def export_ambient_comparison(run_dir, rows, profile, *, axis_model, gravity_sign,
                              device_serial, include_gyro):
    root = Path(run_dir)
    report_paths=[]
    summaries={}
    for kind in ('acc','gyro') if include_gyro else ('acc',):
        fit_rows, val_rows=ambient_comparison_rows(rows,kind)
        expected_fit=12 if kind=='acc' else 1+6*len(profile['rates']['fit_dps'])
        expected_val=12 if kind=='acc' else 1+6*len(profile['rates']['verify_dps'])
        if (len(fit_rows),len(val_rows)) != (expected_fit,expected_val):
            summaries[kind]={'status':'INCOMPLETE', 'fit_count':len(fit_rows),
                'validation_count':len(val_rows),'expected_fit':expected_fit,
                'expected_validation':expected_val}
            continue
        comparison=compare_models(kind,fit_rows,val_rows,profile)
        comparison.update({'calibration_type':'wk_room_temperature_ambient_comparison',
                           'created_at':datetime.datetime.now().astimezone().isoformat(),
                           'device_serial':device_serial,
                           'turntable_model':'2FDT600WK',
                           'axis_model':axis_model,'gravity_sign':gravity_sign,
                           'original_ambient_profile':profile,
                           'fit_step_ids':[r['step_id'] for r in fit_rows],
                           'validation_step_ids':[r['step_id'] for r in val_rows],
                           'production_release':False,
                           'parameter_overwrite':False})
        # The same ordinary ambient C-model validation workbook as the old
        # IMU page, in addition to the original three-model comparison workbook.
        # It includes BEFORE/AFTER norm error and per-pose/per-rate vectors.
        if 'C' in comparison['models']:
            from calibration_excel_report import create_validation_workbook
            cmodel=comparison['models']['C']
            original=[r for r in rows if r.get('sensor')==kind]
            measured_tags=[float(x.get('temperature_target_c')) for x in original
                           if x.get('temperature_target_c') is not None]
            base={'device_serial':device_serial,'run_id':root.name,
                  'wk_single_temperature_c':float(np.median(measured_tags)) if measured_tags else None,
                  'quality_gate':cmodel['quality_gate'],
                  'sensor_configuration':{'chip':'ASM330LHHX','source':'this run: live IMU frames'},
                  'production_release':False}
            if kind=='acc':
                positions=[{**r, 'gravity_reference_platform_g':r['reference']}
                           for r in original]
                result={**base,'position_measurements':positions,
                        'raw_accel_bias_g':cmodel['fit']['bias'].tolist(),
                        'raw_to_platform_matrix':cmodel['fit']['correction_matrix'].tolist()}
                report_paths.append(create_validation_workbook('accel',result,root))
            else:
                measurements=[{**r,'measured':r['gyro_raw_mean_dps'],
                               'axis':r.get('rotation_axis','静止')}
                              for r in original]
                result={**base,
                        'fit_measurements':[r for r in measurements if r['split']=='fit'],
                        'validation_measurements':[r for r in measurements if r['split']=='validate'],
                        'raw_gyro_bias_dps':cmodel['fit']['bias'].tolist(),
                        'raw_to_platform_matrix':cmodel['fit']['correction_matrix'].tolist()}
                report_paths.append(create_validation_workbook('gyro',result,root))
        details=[]
        for code in MODEL_NAMES:
            model=comparison['models'].get(code)
            if not model:
                details.append({'model':code,'status':'FIT_FAILED',
                    'reason':comparison['errors'].get(code,'')})
                continue
            item={'model':code,'status':model['quality_gate']['verdict'],
                  'fit_vector_rmse':float(model['fit']['fit_vector_rmse']),
                  'validation_vector_rmse':float(model['independent_validation']['rmse_vector'])}
            if kind=='acc':
                item.update({'training':metrics_for_model(fit_rows,model['fit']),
                             'independent_pose_validation':metrics_for_model(val_rows,model['fit'])})
            details.append(item)
        if kind=='acc':
            # Attach the exact original 12 fit and 12 independent verification
            # vectors to the A/B/C workbook: same source, no second fitting.
            comparison['wk_fit_rows']=fit_rows
            comparison['wk_validation_rows']=val_rows
            comparison['wk_metric_summary']={
                item['model']:{'fit':item['training'],
                               'validation':item['independent_pose_validation']}
                for item in details if 'training' in item}
        report_paths.extend(save_model_comparison(root,kind,comparison))
        summaries[kind]={'status':'EVALUATED','fit_count':len(fit_rows),
            'validation_count':len(val_rows), 'candidate_model':comparison['candidate_model'],
            'models':details}
    output={
        'purpose':'same ambient IMU protocol on current 2FDT600WK, not thermal compensation',
        'run_dir':str(root), 'production_release':False, 'parameter_overwrite':False,
        'turntable_model':'2FDT600WK', 'axis_model':axis_model,
        'gravity_sign':gravity_sign,'device_serial':device_serial,
        'models':summaries,
        'norm_definition':'1000 * RMS(norm(corrected_mean_acceleration_g)-1g); unit mg',
        'vector_definition':'1000 * RMS(norm(corrected_mean_acceleration_g-reference_vector_g)); unit mg',
        'comparison_warning':'核对旧报告的RMSE类型：用户2026-10-22旧报告0.788mg为独立验证三维向量RMSE，模长RMSE为0.329mg。仅相同PCB、量程、温度、姿态和数据口径可以直接比较；差异不等于已证明转台故障。'}
    path=root/'wk_ambient_norm_vector_metric_summary.json'
    path.write_text(json.dumps(serialize(output),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    report_paths.append(str(path))
    csv_path=root/'wk_ambient_norm_vector_metric_summary.csv'
    with csv_path.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f)
        w.writerow(['传感器','方案','拟合三维向量RMSE_mg','拟合模长RMSE_mg',
                    '独立验证三维向量RMSE_mg','独立验证模长RMSE_mg',
                    '独立验证最大模长绝对误差_mg','结论'])
        for kind,summary in summaries.items():
            for model in summary.get('models',[]):
                tr=model.get('training',{})
                val=model.get('independent_pose_validation',{})
                w.writerow([kind.upper(),model['model'],tr.get('vector_rmse_mg'),
                    tr.get('norm_rmse_mg'),val.get('vector_rmse_mg'),
                    val.get('norm_rmse_mg'),val.get('norm_max_abs_mg'),model['status']])
    report_paths.append(str(csv_path))
    lines=['# 2FDT600WK 单点温度IMU同工艺对照报告',
           '', '采用原常温12拟合+12独立姿态工艺和A/B/C算法。',
           '允许任意有效实测芯片温度，记录实际温度标签；不执行跨温度补偿，不修改标定文件。',
           '三维向量RMSE = RMS(||校正向量 - 转台参考重力向量||)；'
           '模长RMSE = RMS(||校正向量|| - 1g)；单位mg，均基于每工况平均值。',
           '旧转台0.78mg只有在同口径、同PCB、同装夹基准条件下才可直接比较。', '']
    for kind,summary in summaries.items():
        lines += [f'## {kind.upper()}：{summary["status"]}',
                  f'拟合 {summary["fit_count"]} 项；独立验证 {summary["validation_count"]} 项。']
        for model in summary.get('models',[]):
            if kind=='acc' and 'training' in model:
                a=model['training'];v=model['independent_pose_validation']
                lines.append(f'- {model["model"]}: 拟合模长 {a["norm_rmse_mg"]:.4f} mg、'
                             f'拟合三维 {a["vector_rmse_mg"]:.4f} mg；'
                             f'独立验证模长 {v["norm_rmse_mg"]:.4f} mg、'
                             f'独立验证三维 {v["vector_rmse_mg"]:.4f} mg。')
            elif 'validation_vector_rmse' in model:
                lines.append(f'- {model["model"]}: GYRO独立验证矢量RMSE {model["validation_vector_rmse"]:.6f} dps。')
        lines += ['',f'候选模型：{summary.get("candidate_model") or "无（尚不能放行）"}', '']
    md=root/'wk_ambient_comparison_summary.md'
    md.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    report_paths.append(str(md))
    return output,report_paths
