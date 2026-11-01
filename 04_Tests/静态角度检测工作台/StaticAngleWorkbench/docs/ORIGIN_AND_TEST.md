# 旧工程接口映射和验证范围

上传的原项目位于 `TiltSensorCalibration/`，以下为按原始源码逐项核对的对应关系。

| 旧工程源文件/位置 | 原功能 | 新位置 |
|---|---|---|
| `tilt_sensor/tilt_sensor_asm330_comm.py` | `mb_serial_open` / `_mb_read_holding_registers` / `tilt_sensor_data_get` | `app/devices/imu_protocol.py`、`imu_worker.py` |
| `tilt_sensor/tilt_sensor_asm330_def.py` | 104个寄存器结构定义、16样本、FS换算、温度换算 | `imu_protocol.py` |
| `tilt_sensor/tilt_sensor_asm330_data_get.py` | 实时轮询，6轴96样本全0时视为未更新、有效量程缺失时回退 | `imu_worker.py` + `imu_protocol.py` |
| `turntable/turntable_2TD600_comm.py` | `CDLL`、`OpenPort`、`GetPosition`、`GetSpeed`、`GetAxisEnable`、`SetAxisEnable`、`SetAxisDisable`、`SetAxisPosition`、`SetAxisStop` | `turntable_driver.py` |
| `form/form_turntable_ctrl.py` | 转台连接、使能、受控停车和安全断开 | `turntable_worker.py` + `main_window.py` |
| `config.xml` | IMU COM5/1500000、转台 COM4/115200 | UI 的默认端口和波特率 |
| `2TD600.dll` | 厂商原始64位DLL | `vendor/2TD600.dll` |

## 这里特意与旧工程不同的地方

- 旧界面 **打开转台 = 打开端口 + 自动使能两轴**；本版分离成连接与逐轴手动使能，联调更可控。
- 不会在连接后自动回零，不会发送任何自动运动/高速指令。
- DLL 延迟到点击“连接转台”后在 Windows 加载，非 Windows 系统不会在导入 GUI 模块时立即崩溃。
- 读设备与 GUI 分线程；长时间打印日志有抑制以避免刷屏。
- 使能、解除使能和定位均有明确反馈与操作记录。设备关闭前先停车并读取速度确认。

## 协议核查

- CRC16 Modbus (poly 0xA001, init 0xFFFF)：`01 03 00 00 00 0A` 对应 CRC 0xCDC5（线上 `C5 CD`）。
- 功能码 03；寄存器起始 `0x03E8=1000`；数量 `0x0068=104`；应答 208 字节数据。
- 数据寄存器：未读数0，ACC XYZ各16字从1/17/33，GYRO XYZ各16字从49/65/81，温度97、Tick低98高99、ACC FS100、GYRO FS101、ODR102、FIFO103。
- 加速度灵敏度(mg/LSB)：±2 0.061、±4 0.122、±8 0.244、±16 0.488。
- 陀螺仪灵敏度(mdps/LSB)：±125 4.37、±250 8.75、±500 17.5、±1000 35、±2000 70、±4000 140。

## 当前验证情况

纯Python的 IMU CRC、完整回复解码、CRC错误、从机异常、符号扩展、物理量换算、校准文件读取均可单元测试。

**无法在本环境做的验证：** Windows PySide6 实际渲染（环境未提供GUI依赖且无法联网安装）、真实 IMU 串口连接、`2TD600.dll` 的 Windows 运行、转台使能及运动。因此本版是可运行源码和联调操作入口，不得将代码静态检查等同于已通过实机验证。
