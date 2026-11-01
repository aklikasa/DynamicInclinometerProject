# -*- coding: utf-8 -*-
"""标定量程非阻断机制、工况安全门和出厂状态隔离测试。"""
import copy
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from production_calibration import (load_profile, verify_sensor_config,
                                    sensor_config_consistent, restrict_unverified_release)
p=load_profile(ROOT)
# 旧固件无量程/ODR可靠字段，但底层固定回退换算值合法：允许开发试运行
fallback={'acc_fs':2,'gyro_fs':2000,'acc_fs_ever_valid':False,
          'gyro_fs_ever_valid':False,'data_odr':0}
a=verify_sensor_config(p,fallback)
assert a['verified_for_release'] is False
assert (a['acc_fs_g'],a['gyro_fs_dps']) == (2,2000)
# 同样的有效量程，MCU报告标志由False转True：不是换算配置改变
confirmed=verify_sensor_config(p,dict(fallback,acc_fs_ever_valid=True,gyro_fs_ever_valid=True,data_odr=208))
assert sensor_config_consistent(a, confirmed)
assert confirmed['verified_for_release']
assert not sensor_config_consistent(a,verify_sensor_config(p,dict(fallback,acc_fs=8)))
assert not sensor_config_consistent(confirmed,verify_sensor_config(p,dict(fallback,data_odr=416)))
# 任意合法量程可以标定，不是只能8g/250dps
for acc in (2,4,8,16):
    for gyro in (125,250,500,1000,2000,4000):
        assert verify_sensor_config(p, dict(fallback, acc_fs=acc,gyro_fs=gyro))['gyro_fs_dps']==gyro
# 未知配置，即使工艺某天被批准，也不能产生正式出厂PASS
result={'quality_gate':{'metric_pass':True,'verdict':'PASS', 'approved_for_production':True},
        'combined_calibration':{'release_verdict':'PASS'},'status':'PASS'}
restrict_unverified_release(result,a)
assert result['quality_gate']['verdict']=='PILOT_PASS_NOT_RELEASED'
assert not result['quality_gate']['approved_for_production']
assert result['combined_calibration']['release_verdict']=='PILOT_PASS_NOT_RELEASED'
assert result['status']=='PILOT_PASS_NOT_RELEASED'
# 真正已经核验配置的任务不改变工艺判断
released={'quality_gate':{'metric_pass':True,'verdict':'PASS','approved_for_production':True},'status':'PASS'}
restrict_unverified_release(released,confirmed)
assert released['status']=='PASS'
for bad in (dict(fallback,acc_fs=99), dict(fallback,gyro_fs=9999)):
    try: verify_sensor_config(p,bad)
    except ValueError: pass
    else: raise AssertionError('非法换算量程被接受')
# 高速候选不可执行，始终保留10dps限速
bad_p=copy.deepcopy(p)
bad_p['rates']['maximum_command_rate_dps']=100
from production_calibration import validate_profile
try: validate_profile(bad_p)
except ValueError: pass
else: raise AssertionError('转台保守限速被绕过')
print('PASS: flexible valid FS, frozen conversion, release hold, unsafe rate blocked')
