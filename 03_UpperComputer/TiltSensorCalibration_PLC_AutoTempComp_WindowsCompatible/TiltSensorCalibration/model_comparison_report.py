# -*- coding: utf-8 -*-
"""三方案独立验证结果导出；只写本次实验目录，不影响原标定 latest 文件。"""
import csv
import json
from pathlib import Path
from calibration_model_compare import MODEL_NAMES, serialize


def save_model_comparison(run_dir, kind, result):
    folder = Path(run_dir)
    folder.mkdir(parents=True, exist_ok=True)
    suffix = 'acc' if kind == 'acc' else 'gyro'
    json_path = folder / f'model_comparison_{suffix}.json'
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
    header=['方案','方案说明','质量结论','独立验证矢量RMSE','最大矢量误差','最大方向误差_deg',
            '最大模长误差_g','GYRO最大交叉轴误差_dps','GYRO最大零速残差_dps','说明/异常']
    csv_path=folder/f'model_comparison_{suffix}.csv'
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
    xlsx_path=folder/f'model_comparison_{suffix}.xlsx' 
    _write_xlsx(xlsx_path, [
        ('模型结果',('常温IMU三方案自动标定与独立测试',
                 '同批采样，独立验证；A未辨识安装旋转。候选模型并非量产放行。',header,lines,{1:13,2:40,3:24,10:70})),
        ('独立验证残差',('逐工况独立验证误差',
                 '校正后向量与转台参考坐标系P比较，未加入拟合过程。',detail_header,detail,{1:13,2:14})),
        ('参数矩阵',('逐方案参数与校正矩阵',
                 'A方案仅对应名义轴，B含SO(3)旋转，C为完整线性矩阵。',
                 ['方案','参数项','X/列1','Y/列2','Z/列3','说明'],parameter_rows,
                 {1:14,2:26,3:20,4:20,5:20,6:77})),
    ])
    return [str(json_path),str(csv_path),str(xlsx_path)]


def save_selected_model(run_dir, kind, model_id, result):
    name=f'{"accel" if kind=="acc" else "gyro"}_model_{model_id}_candidate.json'
    path=Path(run_dir)/name
    path.write_text(json.dumps(serialize(result),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return str(path)
