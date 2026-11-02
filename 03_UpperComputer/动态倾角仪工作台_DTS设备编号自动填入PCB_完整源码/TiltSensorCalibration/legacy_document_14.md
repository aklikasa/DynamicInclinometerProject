# ACC 静态质量判断与重试修复（2026-10-22）

## 触发问题
日志 `ACC_FIT_03: 静态GYRO抖动 0.47767 °/s 超限` 发生在 **ACC 标定** 中。旧逻辑对任何静态采样同时检查 ACC 和 GYRO 抖动，并且采样质量第一次不通过即中止任务。

## 修改范围
只修改 `production_calibration.py`、`form/form_imu_calibration.py`、`production_quality_profile.json`；新增 `tools/test_acc_static_retries.py`。其他主程序、UI、转台 DLL/通信、IMU 采集模块、退出路径均保持上一版不变。

1. ACC 静态拟合和验证：按 ACC 三轴质量、转台反馈速度、温度、MAD 离群、有效帧数等判定。GYRO 的均值和抖动可以作为诊断指标，但不作为拒绝 ACC 采样的理由；即使 GYRO 帧不完整也不会丢弃完整的 ACC 帧。
2. GYRO 静止零偏工况：按 GYRO 三轴抖动及转台停止等判定。六轴静态验证仍要求 ACC、GYRO 都有效。
3. 单姿态首次不合格：将失败原因写入事件日志，清空本次缓存，保持同一姿态，重新确认双轴到位且低速连续 0.5 秒，再静置用户设定的等待时间，随后重新采样完整采样时长。**最多再重试 5 次，一共 6 次采样机会**；第六次仍未通过才结束标定。
4. 只将成功的那次采样统计结果写进参数拟合或独立验证结果；失败尝试留在事件日志和 `static_retry_history` 中，供追溯。全部重试耗尽仍写入 manifest 但不生成可用参数。
5. 转台反馈失效、限位、通信丢失、角度跑偏等安全/控制异常依旧立即中止，不自动无限重试；动态速率工况暂维持原有停车和异常机制，不在这次修改内。

## 配置
`production_quality_profile.json` 中 `quality.static_sample_max_retries = 5`；单位为“额外重试次数”，不是总尝试次数。

## 本地回归
项目根目录运行：

```powershell
python tools/test_acc_static_retries.py
python tools/test_production_calibration.py
python tools/test_angle_equivalence.py
```

以上为不依赖真实硬件的测试，不等同于 Windows 实机通过。首次自动运动仍需有人监护。
