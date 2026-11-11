# -*- coding: utf-8 -*-
"""2FDT600WK 温补逐工况存档/安全断点续做（不依赖 Qt，不发送设备命令）。

只恢复已完成、成功质控且确认停车的统计工况；重做正在执行/失败的工况。
恢复前须由主程序重新确认设备、温度和安全条件。旧版快照没有本模块的
运行参数指纹，不能自动续做，以免错误合并不同配置/PCB 的数据。
"""
import json
import os
from pathlib import Path

RESUME_SCHEMA = 2


def atomic_write_json(path, value):
    path = Path(path)
    tmp = path.with_name(path.name + '.new')
    with tmp.open('w', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def validate_resume(config, checkpoint, expected_config, temperatures, steps):
    """确保参数完全一致、统计记录为按顺序完成的工况前缀。"""
    if config.get('resume_schema_version') != RESUME_SCHEMA:
        raise ValueError('该实验由旧版程序生成，缺少续做所需的安全配置校验；请勿自动合并。')
    # 旧版本曾在配置中保存单段累计角度上限。新版已取消该约束；续做时仅忽略
    # 这一废止参数，设备编号、工况/温度/模型/采样参数仍必须逐项严格匹配。
    actual = config.get('resume_immutable_config', {})
    if not isinstance(actual, dict):
        raise ValueError('恢复失败：原实验配置格式无效。')
    obsolete = {'gyro_sweep_limit_deg'}
    actual_effective = {k:v for k,v in actual.items() if k not in obsolete}
    expected_effective = {k:v for k,v in expected_config.items() if k not in obsolete}
    # Older dual-temperature software did not write the rate-mode name. It can
    # still be resumed in exactly matching legacy FULL-speed mode, never in
    # reduced-rate mode (where the step IDs/axis assignment may differ).
    if ('gyro_rate_mode' in expected_effective and 'gyro_rate_mode' not in actual_effective
            and expected_effective['gyro_rate_mode']=='full'
            and actual_effective.get('gyro_fit_rates_dps')==[1.0,5.0,15.0,30.0,60.0]
            and actual_effective.get('gyro_verify_rates_dps')==[1.5,3.5,10.0,20.0,45.0]):
        actual_effective['gyro_rate_mode']='full'
    if 'imu_sensor_config' in expected_effective and 'imu_sensor_config' not in actual_effective:
        raise ValueError('旧实验没有记录IMU实际量程/ODR，无法保证与当前±250dps配置一致；'
                         '为防止混用不同量程的数据，请新建实验，勿自动续写旧目录。')
    if actual_effective != expected_effective:
        changes = [name for name in sorted(set(actual_effective) | set(expected_effective))
                   if actual_effective.get(name) != expected_effective.get(name)]
        raise ValueError('恢复失败：实验配置与原实验不一致：' + '、'.join(changes))
    if checkpoint.get('status') == 'COMPLETED':
        raise ValueError('实验已标记为 COMPLETED，不允许覆盖已完成结果。')
    if checkpoint.get('status') not in ('RUNNING', 'INCOMPLETE', 'PARTIAL_COMPLETED'):
        raise ValueError('保存状态不允许续做。')
    if checkpoint.get('device_sn') != expected_config.get('device_sn'):
        raise ValueError('PCB 编号与存档不一致。')
    rows = checkpoint.get('rows')
    if not isinstance(rows, list):
        raise ValueError('保存数据缺少 rows 列表。')
    if not steps:
        raise ValueError('没有有效的实验工况表。')
    # New schedules use one step list per temperature; legacy experiments use
    # one common step list. Compare the exact committed prefix either way.
    per_temp = (steps if isinstance(steps[0], list)
                else [steps for _ in temperatures])
    if len(per_temp) != len(temperatures) or any(not part for part in per_temp):
        raise ValueError('温度工况计划缺少测试步骤。')
    expected_rows = [(t, part_step) for t, part in zip(temperatures,per_temp)
                     for part_step in part]
    if len(rows) > len(expected_rows):
        raise ValueError('记录数量超过实验预设工况数量。')
    # New long-run mode allows holes (deferred failed steps) and later back-fill.
    # Every accepted row must still belong to exactly one planned step. A
    # duplicate, unknown step or leaked fit row at a validation temperature is
    # unsafe regardless of ordering; reject the entire resume.
    progress=checkpoint.get('task_progress')
    if progress is not None:
        if not isinstance(progress,dict):raise ValueError('恢复游标格式错误')
        expected_by_key={(float(temp),st['step_id']):(temp,st)
                         for temp,st in expected_rows}
        seen=set()
        for i,row in enumerate(rows):
            if not isinstance(row,dict):raise ValueError('工况记录必须为字典')
            key=(float(row.get('temperature_target_c',float('nan'))),row.get('step_id'))
            if key in seen:raise ValueError('同一工况重复提交，拒绝恢复')
            seen.add(key)
            if key not in expected_by_key:raise ValueError('恢复数据包含未知工况')
            temp,st=expected_by_key[key]
            if (row.get('sensor')!=st.get('sensor') or row.get('split')!=st.get('split')
                    or row.get('mode')!=st.get('mode') or int(row.get('accepted_frames',0))<=0):
                raise ValueError('恢复工况的传感器/数据用途或有效帧错误')
            role=expected_config.get('temperature_fit_split',{}).get(str(float(temp)))
            if role and row.get('temperature_split')!=role:
                raise ValueError('恢复工况的温度用途错误')
            if st['mode']=='rate' and (row.get('rotation_axis')!=st.get('rotation_axis')
                  or float(row.get('target_rate_dps',float('nan')))!=float(st['target_rate_dps'])):
                raise ValueError('恢复工况的转轴/转速错误')
        temp_i=int(progress.get('temp_index',0));step_i=int(progress.get('step_index',0))
        if temp_i<0 or temp_i>len(per_temp):raise ValueError('温度恢复索引越界')
        if temp_i<len(per_temp) and not 0<=step_i<=len(per_temp[temp_i]):
            raise ValueError('步骤恢复索引越界')
        deferred=progress.get('deferred_by_temp',{})
        if not isinstance(deferred,dict):raise ValueError('待补测状态无效')
        for name,indices in deferred.items():
            ix=int(name)
            if not 0<=ix<len(per_temp) or not isinstance(indices,list):raise ValueError('待补测索引非法')
            for index in indices:
                if type(index)!=int or not 0<=index<len(per_temp[ix]):raise ValueError('待补测步骤索引非法')
        if checkpoint['status']=='PARTIAL_COMPLETED':
            unresolved=progress.get('unresolved',[])
            if not unresolved:raise ValueError('部分完成实验没有待补测清单')
            deferred={}
            for m in unresolved:
                i=int(m['temp_index']);j=int(m['step_index'])
                if not (0<=i<len(per_temp) and 0<=j<len(per_temp[i])):
                    raise ValueError('待补测工况超出原实验计划')
                if (float(temperatures[i]),per_temp[i][j]['step_id']) not in seen:
                    deferred.setdefault(str(i),[]).append(j)
            if not deferred:raise ValueError('待补测工况已全部存在，拒绝重复拟合')
            temp_i=min(int(k) for k in deferred)
            queue_for_temp=sorted(set(deferred[str(temp_i)]))
            step_i=queue_for_temp.pop(0)
            progress={'temp_index':temp_i,'step_index':step_i,'replay_mode':True,
                      'replay_queue':queue_for_temp, 'deferred_by_temp':deferred,
                      'unresolved':[], 'thermal_hold_count':0}
        return {'rows':rows,
                'events':checkpoint.get('events',[]) if isinstance(checkpoint.get('events'),list) else [],
                'frame_count':int(checkpoint.get('imu_frame_count',0)),
                'temp_index':temp_i,'step_index':step_i,'task_progress':progress}
    for i, row in enumerate(rows):
        expected_temp, expected = expected_rows[i]
        if not isinstance(row, dict):
            raise ValueError(f'第 {i+1} 条记录不是工况统计字典。')
        if (float(row.get('temperature_target_c', float('nan'))) != float(expected_temp)
                or row.get('step_id') != expected.get('step_id')
                or row.get('sensor') != expected.get('sensor')
                or row.get('split') != expected.get('split')
                or row.get('mode') != expected.get('mode')):
            raise ValueError(f'第 {i+1} 条记录不符合原工况顺序：拒绝跳过或混合工况。')
        if expected.get('mode') == 'rate':
            if (row.get('rotation_axis') != expected.get('rotation_axis') or
                    float(row.get('target_rate_dps', float('nan'))) != float(expected['target_rate_dps'])):
                raise ValueError(f'第 {i+1} 条动态记录的旋转轴或角速度不一致。')
        # Validate the committed temperature role as well as the step prefix.
        # This prevents a corrupted/mislabeled holdout row from leaking into
        # the training set on a resumed or offline-reanalyzed run.
        roles = expected_config.get('temperature_fit_split', {})
        if roles:
            role = roles.get(expected_temp, roles.get(str(float(expected_temp))))
            if role not in ('fit', 'validate') or row.get('temperature_split') != role:
                raise ValueError(f'第 {i+1} 条记录的温度拟合/验证用途与配置不一致。')
        if int(row.get('accepted_frames', 0)) <= 0:
            raise ValueError(f'第 {i+1} 条记录缺乏有效帧。')
    # Locate the first uncommitted step; at a temperature boundary the next
    # task must restart the full thermal equilibrium gate, not skip ahead.
    remaining=len(rows)
    temp_index=len(temperatures)
    step_index=0
    for j,part in enumerate(per_temp):
        if remaining<len(part):
            temp_index=j
            step_index=remaining
            break
        remaining-=len(part)
    return {'rows': rows,
            'events': checkpoint.get('events', []) if isinstance(checkpoint.get('events'), list) else [],
            'frame_count': int(checkpoint.get('imu_frame_count', 0)),
            'temp_index': temp_index,
            'step_index': step_index}


def validate_appendable_raw_files(folder, committed_rows):
    """防止误把旧/被破坏的原始记录当作同一次实验续写。"""
    folder = Path(folder)
    for name in ('imu_frame_means.csv', 'imu_full_frames.jsonl'):
        file = folder / name
        if not file.is_file():
            raise ValueError(f'续做缺少原始记录文件：{name}')
        if file.stat().st_size == 0 and committed_rows:
            raise ValueError(f'已有已完成工况但原始记录文件为空：{name}')
        if file.stat().st_size:
            with file.open('rb') as f:
                f.seek(-1, os.SEEK_END)
                if f.read(1) != b'\n':
                    raise ValueError(f'{name} 尾部不完整，请先备份并检查原始数据。')
