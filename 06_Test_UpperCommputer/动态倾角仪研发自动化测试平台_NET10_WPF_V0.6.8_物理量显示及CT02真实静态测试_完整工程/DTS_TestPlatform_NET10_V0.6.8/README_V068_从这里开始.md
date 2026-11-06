# V0.6.8 — 未标定物理量显示 + CT-02 单姿态真实测试

## 你问的 S1 为什么叫 CT

S1 是“常温标定后验证”的阶段名称，CT-xx 是旧版测试指南和 tests.json 沿用的测试项目编号；`CT-02` 在程序内部属于 S1。编号关联注册表、报告、历史链接，因此这一版保留 CT-xx 以避免断开兼容。后续可以单独提供 S1-02 等显示别名及旧ID映射，不应仅改按钮字样。

## 未选择标定时的六轴值（本次按要求更正）

* 不勾选常温/全温：表格和 `imu_selected.csv` 显示 `int16 × 灵敏度系数`，ACC 为 g，Gyro 为 °/s。
* 历史输入换算固定 ACC ±2g ×0.000061 g/LSB；Gyro ±2000°/s ×0.070 °/s/LSB。这是目前的**软件历史换算约定**，不表明芯片一定设置成该物理量程。
* 勾选常温：先按匹配 JSON 的拟合输入量程换算物理量，再应用各自的零偏和 3×3 校正矩阵；不会多乘或多除 8。
* 勾选全温：保留 V0.6.7.1 已有温度模型的条件与逻辑，本次不拓展其数学模型。
* `imu_raw.csv` 始终包含 6 个真实 int16 原始计数列，以备独立复算。

**以后修改历史默认显示量程：** `src/Dts.Core/CalibrationInputScalePolicy.cs` 的 `HistoricalAccFullScaleG = 2` 和 `HistoricalGyroFullScaleDps = 2000`。实际灵敏度表在 `src/Dts.Core/Core.cs` 的 `Asm330Codec` 中。改变默认显示量程不会自动改造旧 Gyro 标定矩阵；旧 JSON 仍按其自身记录的拟合输入量程处理。

## CT-02：常温零位与静态零速残差（单姿态真实子项）

新模块独立文件夹：`src/Dts.Tests/S1/CT02/`：

- `CT_02_Test.cs` — 真实采集、UID/模式校验、报告组织；
- `CT_02_Algorithm.cs` — 六轴均值、样本标准差、Roll/Pitch 零位分量、重力向量方向误差、Gyro 三轴零速残差；
- `CT_02_Result.cs` — 参数与结果数据结构；
- `CT_02_Report.cs` — 独立 JSON/CSV/HTML 报告。

专用窗口：`src/Dts.Wpf/TestWindows/CT02/CT02Window.xaml` 和 `.xaml.cs`，使用现有 `[TestWindowFor("CT-02")]` 自动发现，不需要在 MainWindow 为每个测试添加分支。

**现场操作**：在主窗口连接真实 IMU 并读取完整 UID，选中标定总目录并勾选“常温标定”；固定设备，确认转台完全静止，使用可信的机械参考定位到零位；点击 S1/CT-02，选择**校准后的平台 P 系**中零位重力的 +Z 或 -Z 方向（不可根据 PCB 原始 Az 的正负猜测），输入采样秒数（默认30秒），确认现场条件，开始采集。即使没有连接 2TD，也能读取静止六轴；但没有可信的机械零位参考时不能声称测出了“零位精度”。

采集后结果目录自动创建 `DTS编号_完整UID/时间_CT-02/`，保存 `imu_raw.csv`、`imu_selected.csv`、`manifest.json`、`calibration_snapshots/`、`CT-02_result.json`、`CT-02_metrics.csv`、`CT-02_report.html`、`test_execution.json`。只有真实采集成功且样本数不少于50、MCU tick跨至少两批、所有选定帧均为常温补偿结果，才形成统计报告。

**严格限定**：这是 CT-02 的单姿态实测子项，**尚未实现自动重复定位及独立参考仪器不确定度评定**，不会自动判定产品 PASS/FAIL。这个版本新增模块没有调用任何转台运动命令；不要误认为转台机械安全性能已经验证。

## 构建和测试状态

`python scripts/check_sources.py` 和 `python scripts/check_v068.py` 仅检查源码/XAML结构。当前打包环境没有 Windows .NET 10 SDK，未完成 Windows 的真实编译、窗口启动及设备现场测试。请在 Visual Studio 中执行“清理解决方案→重新生成解决方案”，有第一条 CSxxxx 错误时以其为准，后续 CS0006 通常是级联错误。`scripts/build_windows.cmd` 可生成详细构建日志。
