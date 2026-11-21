# -*- coding: utf-8 -*-
"""Pure-data verification of independent ACC/GYRO completeness from saved plan."""
from production_calibration import acc_fit_steps, acc_verify_steps, gyro_fit_steps, gyro_verify_steps
from thermal_variable_temperature import steps_for_temperature


def fully_accepted_sensors(config, checkpoint):
    """Only report a sensor when every planned step is uniquely accepted.

    For a partial legacy experiment without a complete immutable step plan,
    conservatively refuse to guess completeness from count alone.
    """
    immutable=config.get('resume_immutable_config') or {}
    profile=immutable.get('quality_profile')
    temps=config.get('temperature_setpoints_c')
    roles=config.get('temperature_split') or {}
    if not isinstance(profile,dict) or not isinstance(temps,list) or not isinstance(roles,dict):
        raise ValueError('缺少原实验工况与质量配置，不能证明某传感器数据完整')
    dynamic=bool(immutable.get('gyro_dynamic',True))
    steps=[{**x,'sensor':'acc'} for x in acc_fit_steps()+acc_verify_steps()]
    for split,name in (('fit','GYRO_ZERO_FIT'),('validate','GYRO_ZERO_VAL')):
        steps.append({'mode':'static','step_id':name,'split':split,'sensor':'gyro'})
    if dynamic:
        for x in gyro_fit_steps(profile)+gyro_verify_steps(profile):
            if x['mode']=='rate':steps.append({**x,'sensor':'gyro'})
    expected={'acc':set(),'gyro':set()}
    by_key={}
    for temp in temps:
        target=float(temp)
        role=roles.get(str(target),roles.get(str(temp)))
        if role not in ('fit','validate'):
            raise ValueError(f'缺少目标温度{target:g}℃的拟合/验证角色')
        for step in steps_for_temperature(steps,role):
            key=(target,step['step_id'])
            if key in by_key:raise ValueError('原工况表存在重复工况')
            by_key[key]=step
            expected[step['sensor']].add(key)
    accepted={'acc':set(),'gyro':set()}
    for row in checkpoint.get('rows',[]):
        key=(float(row['temperature_target_c']),row['step_id'])
        step=by_key.get(key)
        if not step:raise ValueError('已接受记录不属于实验计划')
        sensor=step['sensor']
        if (key in accepted[sensor] or row['sensor']!=sensor or
              row['split']!=step['split'] or row['mode']!=step['mode'] or
              int(row.get('accepted_frames',0))<1):
            raise ValueError('已接受记录存在重复或与原工况计划不一致')
        role=roles.get(str(key[0]),roles.get(str(int(key[0]))))
        if role!=row.get('temperature_split'):
            raise ValueError('某工况的拟合/独立验证温度角色不匹配')
        if step['mode']=='rate':
            if (row.get('rotation_axis')!=step.get('rotation_axis') or
                float(row.get('target_rate_dps',float('nan')))!=float(step['target_rate_dps'])):
                raise ValueError('动态工况转轴/转速与计划不一致')
        accepted[sensor].add(key)
    return tuple(s for s in ('acc','gyro') if expected[s] and accepted[s]==expected[s])
