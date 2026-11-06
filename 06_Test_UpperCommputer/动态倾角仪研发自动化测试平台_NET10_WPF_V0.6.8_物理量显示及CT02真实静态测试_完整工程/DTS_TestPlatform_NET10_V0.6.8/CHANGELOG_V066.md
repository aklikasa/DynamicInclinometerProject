# V0.6.6 — 常温标定实时数值自动换算

- 在主界面勾选“常温标定”后，按当前 UID 自动匹配的 ACC/Gyro JSON 中的 `sensor_configuration.acc_fs_g` 与 `gyro_fs_dps` 将真实 int16 原始计数换算为 g、°/s，然后计算 `M * (physical - bias)`。
- **不再要求 MCU 报告 SENSOR_OK 或有效量程，也不需要额外勾选“研发试算”。** 未回报状态仅作为实时表格状态文本与数据归档标签；不阻断数学计算。
- 若 JSON 缺少某轴量程，则该轴回退到 MCU 报告的有效量程；如果两处都没有足够参数，显示 `--` 和缺失原因，绝不凭空构造物理量换算系数。
- 若 JSON 量程与 MCU 实际回报不一致，按 JSON 建模时采用的量程换算并标记 `CALIBRATED_JSON_FS_MCU_MISMATCH`，不会悄悄替换标定模型的输入定义。
- 实时 DataGrid 与 `imu_selected.csv` 使用完全相同的数值和状态；`imu_raw.csv` 保存真实 int16 原始数据。采集 manifest 记录换算策略、未核实样本数。
- 保留完整 UID 匹配、simulation_only 拒绝、无效系数检查和真实设备数据通道校验。CT-05 转台的运动安全保护及正式精度验收前置检查**本次没有修改**。

## 验证范围

提供新的代码静态回归检查和 C# 自检用例：模拟 MCU FS=0、SENSOR_OK=0 且匹配 JSON 有量程提示时，检查六轴产生数值，缺少参数才显示 `--`。尚未在 Windows/.NET 10 和现场实体设备上构建及验收。
