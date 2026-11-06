# V0.6.7：保持历史标定量程一致（DTS872028）

## 当前数据计算规则（重要）

DTS872028 旧 ACC/Gyro 常温 JSON 的 `sensor_configuration` 分别记录了
`acc_fs_g=2` 与 `gyro_fs_dps=2000`。这些是**生成当前零偏和矩阵时使用的输入换算设置**。

* ACC: `raw_acc_int16 × 0.000061 g/LSB`。
* Gyro: `raw_gyro_int16 × 0.070 °/s/LSB`。
* 之后分别执行 `M × (physical - bias)`，不得再额外除以 8。
* 无论 MCU 状态报告 0、250 还是其他有效量程，**常温补偿优先使用完整 UID 匹配的 JSON 原始拟合量程**。
* `imu_raw.csv` 继续保留未经改变的原始计数，`imu_selected.csv` 使用同一实时换算过程。

**这不是对芯片物理量程的更改！** 固件可能配置成 ±250°/s，但旧 JSON 是以
±2000°/s 的上位机换算拟合得到的，沿用旧矩阵时必须保持旧系数。

## 后续在哪里修改？

1. **当前这台设备真正决定换算的文件：**
   `DTS872028_gyro_calibration.json` 的 `sensor_configuration.gyro_fs_dps=2000`。
   不能孤立地把旧 JSON 这个值改成 250，否则零偏/矩阵会失去输入单位一致性。
2. **查表关系：** `src/Dts.Core/Core.cs`，`Asm330Codec.GyrMdps`：
   `2000 => 70 mdps/LSB = 0.070 °/s/LSB`；`250 => 8.75 mdps/LSB = 0.00875 °/s/LSB`。
   ST 原厂系数不需要改写。
3. **选择优先级和历史配置说明：** `src/Dts.Core/CalibrationInputScalePolicy.cs`。
   正式更换量程时，请生成对应新量程重新拟合的 JSON，然后由这套规则自动取新 JSON 的量程。
4. **实际数据流：** `src/Dts.Devices/SelectedImuFrame.cs`。
   CT-05 的实测采样也使用同一个入口，且只有 CT-05 的算法才对 ACC 物理单位再次应用校正矩阵一次。

## 对 CT-05 的改变

原 CT-05 仅因 MCU 没有上报 SENSOR_OK 或有效 FS 就无法开始。现在**常温模式**
在真实 FIFO 有数据、匹配的 ACC/Gyro JSON 可计算、现场已完成机械安全确认时，
允许以历史 JSON 输入系数运行*研发测量*，并把原始计数、输入量程来源写入逐点 CSV。
结果依然是 `PendingAcceptance`，**不宣称正式出厂 PASS**。
**转台双轴使能、故障、限位、行程、到位、停车反馈和操作者确认全部保持原有保护。**
全温模式的 MCU 量程要求未更改。

## 检查说明

执行 `python scripts/check_sources.py`、`python scripts/check_v067.py`，
然后在 Windows 实机使用 `scripts/build_windows.cmd` 编译并现场验证。
当前环境无 Windows/.NET 10 SDK 和实体转台，不能宣称编译或联调完成。
