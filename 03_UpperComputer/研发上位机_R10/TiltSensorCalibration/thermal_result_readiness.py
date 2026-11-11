# -*- coding: utf-8 -*-
"""Auditable result-readiness summary, including partial/aborted experiments.

The report distinguishes data collection, mathematical model fit and verified
thermal-compensation performance. It does NOT infer coefficients or approve
missing conditions. No Qt/device dependencies, safe to re-run offline.
"""
from pathlib import Path
import json


def build_result_readiness(temperatures, steps_by_temperature, rows, temperature_splits,
                           auto_skipped=()):
    temperatures=[float(x) for x in temperatures]
    plan={str(float(t)): temperature_splits.get(t,
         temperature_splits.get(str(t),temperature_splits.get(str(float(t)))))
         for t in temperatures}
    accepted={(float(r['temperature_target_c']),str(r['step_id']),str(r['sensor']))
              for r in rows if all(k in r for k in ('temperature_target_c','step_id','sensor'))}
    out={'schema_version':1,'production_release':False,
         'total_planned':0,'total_accepted':0,'total_missing':0,
         'auto_skipped_temperatures':list(auto_skipped or []),
         'sensors':{},'per_temperature':[],
         'interpretation':('采集完整不等于温补精度合格；需要28候选实际拟合、未参与拟合的独立温度验证、'
                           '硬件参考准确性、MCU量程及最终动态倾角融合测试。')}
    sensors=('acc','gyro')
    for sensor in sensors:
        out['sensors'][sensor]={
            'planned':0,'accepted':0,'missing':0,
            'fit_temperature_setpoints_with_data':[],
            'fit_temperature_setpoints_complete':[],
            'independent_temperature_setpoints_with_data':[],
            'independent_temperature_setpoints_complete':[],
            'fit_rows_accepted':0,'condition_validation_rows_accepted':0,
            'independent_temperature_rows_accepted':0,
            'model_status':'NOT_RUN', 'model_selection_status':None,
            'note':'完整性按工况计划和已接受记录逐项核对；仅供研发，不表示计量验收。'}
    for ti,t in enumerate(temperatures):
        steps=steps_by_temperature[ti] if ti<len(steps_by_temperature) else []
        role=plan.get(str(t))
        for sensor in sensors:
            subset=[s for s in steps if s.get('sensor')==sensor]
            if not subset:continue
            keys={(t,str(s['step_id']),sensor) for s in subset}
            valid=keys & accepted
            n=len(keys);a=len(valid)
            stat=out['sensors'][sensor]
            stat['planned']+=n;stat['accepted']+=a;stat['missing']+=n-a
            if role=='fit':
                if a:stat['fit_temperature_setpoints_with_data'].append(t)
                if a==n:stat['fit_temperature_setpoints_complete'].append(t)
            elif role=='validate':
                if a:stat['independent_temperature_setpoints_with_data'].append(t)
                if a==n:stat['independent_temperature_setpoints_complete'].append(t)
            if role=='validate':
                stat['independent_temperature_rows_accepted']+=a
            else:
                stat['fit_rows_accepted']+=sum(1 for s in subset
                    if s.get('split')=='fit' and (t,str(s['step_id']),sensor) in valid)
                stat['condition_validation_rows_accepted']+=sum(1 for s in subset
                    if s.get('split')=='validate' and (t,str(s['step_id']),sensor) in valid)
            out['per_temperature'].append({
                'temperature_target_c':t,'temperature_role':role,'sensor':sensor,
                'planned':n,'accepted':a,'missing':n-a,
                'fully_complete':a==n})
    for sensor,s in out['sensors'].items():
        if not s['planned']:
            s['model_status']='NOT_SCHEDULED'
        elif not s['missing']:
            s['model_status']='FULL_DATA_READY_FOR_MODEL_EVALUATION'
        elif (len(s['fit_temperature_setpoints_with_data'])>=3 and
              s['fit_rows_accepted']>=4 and
              s['condition_validation_rows_accepted']>0 and
              s['independent_temperature_rows_accepted']>0):
            s['model_status']='PARTIAL_DATA_ATTEMPT_MODEL_PREVIEW'
        else:
            s['model_status']='INSUFFICIENT_DATA_REPORT_MISSING_ONLY'
        out['total_planned']+=s['planned']
        out['total_accepted']+=s['accepted']
        out['total_missing']+=s['missing']
    return out



def missing_planned_conditions(temperatures,steps_by_temperature,rows):
    """Reconcile the full acquisition plan against accepted rows.

    A quality timeout, process abort or interrupted checkpoint may leave no
    deferred list even though planned conditions were never sampled. Report
    these explicitly, without changing the acceptance count.
    """
    keys={(float(r['temperature_target_c']),str(r['step_id']),str(r['sensor']))
          for r in rows if all(k in r for k in ('temperature_target_c','step_id','sensor'))}
    missing=[]
    for ti,target in enumerate(temperatures):
        if ti>=len(steps_by_temperature):continue
        for si,step in enumerate(steps_by_temperature[ti]):
            if (float(target),str(step['step_id']),str(step['sensor'])) in keys:
                continue
            missing.append({'temp_index':ti,'step_index':si,
                'temperature_target_c':float(target),'step_id':step['step_id'],
                'sensor':step['sensor'],
                'rotation_axis':step.get('rotation_axis'),
                'target_rate_dps':step.get('target_rate_dps'),
                'reason':'检查点核对发现计划工况缺失；参见运行日志及设备/温控状态'})
    return missing

def write_result_readiness(folder, readiness, experiment_status='UNKNOWN'):
    root=Path(folder);root.mkdir(parents=True,exist_ok=True)
    report={**readiness,'experiment_status':experiment_status}
    json_path=root/'thermal_result_readiness.json'
    json_path.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    lines=['# 温补实验结果可用性检查（非量产验收）','',
           f'- 实验采集状态：**{experiment_status}**',
           f'- 工况计划：{readiness["total_planned"]}',
           f'- 已接受唯一工况：{readiness["total_accepted"]}',
           f'- 缺失工况：**{readiness["total_missing"]}**','',
           '| 传感器 | 已接受/计划 | 拟合温度有数据 | 独立温度有数据 | 模型分析状态 |',
           '|---|---:|---:|---:|---|']
    for sensor,s in readiness['sensors'].items():
        lines.append(f'| {sensor.upper()} | {s["accepted"]}/{s["planned"]} | '
                     f'{len(s["fit_temperature_setpoints_with_data"])} | '
                     f'{len(s["independent_temperature_setpoints_with_data"])} | '
                     f'{s["model_status"]} |')
    lines += ['','## 逐温度工况检查','',
              '| 温度 | 用途 | 传感器 | 已接受/计划 | 缺失 |',
              '|---:|---|---|---:|---:|']
    for v in readiness['per_temperature']:
        lines.append(f'| {v["temperature_target_c"]:g}℃ | {v["temperature_role"]} | '
                     f'{v["sensor"].upper()} | {v["accepted"]}/{v["planned"]} | {v["missing"]} |')
    lines += ['','**重要：** 此表只判定是否具备分析数据，**不保证28个候选都可拟合，'
              '也不保证任何模型温补有效。** 模型选型、独立温度误差、缺失工况及质量风险'
              '均应在后续独立报告中核实。连续模式下跨姿态芯片温差过大、温度与运动工况'
              '耦合时应特别谨慎。']
    md_path=root/'thermal_result_readiness.md'
    md_path.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return {'json':str(json_path),'markdown':str(md_path)}
