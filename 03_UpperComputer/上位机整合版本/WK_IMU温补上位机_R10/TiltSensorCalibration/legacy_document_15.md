# 本次修订说明：以能读数、能正常退出的旧版为底座

## 范围控制

这次以用户上传的 `动态倾角仪工作台_紧凑玻璃版_修复启动导入(2).zip` 为**完整底座**。所有文件除下列标定专属文件外均原样保留：

- 更新 `form/form_imu_calibration.py`：常温 ACC 12 拟合 + 12 验证，GYRO 静止/多速率拟合与独立验证，公共 P 系六轴验证，MAD 稳态数据筛选、零位/目标角位置核验、量程拦截、结果输出；与旧版 IMU 帧队列兼容。
- 新增 `production_calibration.py`、`production_quality_profile.json`、`calibration_excel_report.py`：工艺参数、纯数学与独立 Excel 报告。
- **仅对 `turntable/turntable_data_get.py` 两行做必需的状态赋值修正**：旧版外轴机械找零反馈误写到 `is_outer_axis_in_place`，现改为 `is_outer_axis_find_zero`，其他采集和通信线程完全未动。
- 新增三个纯标定模块检查脚本。

## 保持完全不变的核心文件（逐字节一致）

`main.py`，`ui/mainWindow.ui`，`form/form_tilt_sensor_cal.py`，`form/form_turntable_ctrl.py`，`form/form_tc.py`，`tilt_sensor/tilt_sensor_asm330_data_get.py`，`tilt_sensor/tilt_sensor_asm330_comm.py`，`turntable/turntable_2TD600_comm.py`，`turntable/turntable_2FDT600WK_comm.py`，`temperature_chamber/*`，两个厂商 DLL，原配置 XML 等。

本版**没有**使用新版的 DLL 子进程隔离/后台连接/退出线程重构，也**没有**修改普通 IMU 数据读取和文件记录逻辑。原版 Tkinter 等依赖行为保持不变，因此本包首先用于你的 Python 虚拟环境运行；Nuitka EXE 仍需单独处理 Tkinter 兼容（不可把其等同于本次标定修复）。

## 工艺原则

- 外 X/内 Z 为候选默认轴系，需核验机械零位、方向和限位。自动找零及运动必须现场监护。
- 旧固件若未上报准确的 ±8g/±250dps 和 ODR，自动标定会拒绝启动，**但普通实时读数不应因此停止**。上位机没有自动改 MCU 寄存器。
- GYRO 正式运行仍为 ±1/±2/±5°/s；更高候选速率仅保存在配置，绝不自动执行。
- 试生产阈值未获批准，合格候选只产生 `PILOT_PASS_NOT_RELEASED`，不是正式出厂 PASS。
- 旧版队列没有逐帧量程有效标志，本版使用采集线程安全快照核验；若需要严格每帧同源元数据，未来需在固件通信协议版本化后实现，不应悄悄改动旧读数流程。
- 独立多点验证和 Excel 报告仅在自动标定完成后生成。

## 验证边界

无需实机的源代码、数据结构、拟合、Excel 检查可执行；未在 Windows + 2TD600 + MCU 上做设备联调。用户应先验证普通读数与退出，再在监护下运行转台自动归零及标定。

## 回滚

如果只想恢复原先的标定页，覆盖旧版本 `form/form_imu_calibration.py`，并删除此次新增的三个工艺/Excel 文件即可。恢复原版转台反馈文件会重新引入外轴找零状态错误，不推荐。
