# V0.5.3 · 原始采集、标定文件匹配及量程异常处理

## 这一版修复什么

- 主窗口可分别选择 **报告保存目录** 与 **标定文件目录**；两个目录保存在 `%LOCALAPPDATA%\DTS_TestPlatform`，不是同一个变量。
- MCU UID 已读取后，标定文件夹按精确文件名匹配 `DTSxxxxxx_accel_calibration.json` / `DTSxxxxxx_gyro_calibration.json`，不自动选择“最近的文件”或其他设备的标定。
- 如果 JSON 包含 `uid_raw_12_bytes` 等完整 12 字节原始 UID，会比对 MCU 返回的完整 UID；不同则拒绝应用。旧 JSON 如果只有文件名 DTS 短号，必须由操作员勾选实物归属核验。短号不是完整 UID。
- 同时识别同一 UID 下的 `alignment.json`、`imu_calibration_pilot_candidate.json`、`thermal_acc_candidate.json`、`thermal_gyro_candidate.json` 文件名并列为待核实候选，**本版不会自动叠加这些候选参数**，避免重复坐标对齐或重复温补。
- 支持 Python 原上位机常见 ACC `raw_accel_bias_g` + `raw_to_platform_matrix`、Gyro `raw_gyro_bias_dps` + `raw_to_platform_matrix`。先把原始 int16 依量程换成 g/°/s，再作 `corrected = M * (uncorrected - bias)`。标定矩阵只在上位机使用，不会修改 MCU。
- **MCU FS=0** 仍可记录真实原始 16 位计数：不再以 `ACC=0g, Gyro=0°/s` 阻止采集。默认转换列留空，并将来源标记为 `UNKNOWN`；**严禁默认为 ±2g/±2000°/s 并把结果当真实单位**。
- 可选择“按标定文件中记录的量程试算”，但须同时确认该设备的标定文件归属；对应 CSV 行标记 `CAL_FILE_UNVERIFIED`，这不是通过 MCU 验证的量程，不得用作产品精度验收。
- 点击“开始采集”后同一按钮变成“停止采集”。勾选“定时自动停止”则到时间自动结束；取消勾选则一直写盘，到手动停止。手动停止后保存 `STOPPED_BY_OPERATOR` 状态，不虚报 `PASS`。
- 采集、温度、量程来源、原始 UID、DTS 编号、ACC/Gyro JSON 文件路径和 SHA-256 都保存在 CSV/`manifest.json` 中。**未产生样本或通信错误时标记 FAILED**。
- 2TD 与 2FDT 标题“连接”以及选轴归零按钮统一限制宽度，不再由于 DockPanel 自动填充铺满整行。

## 原始与换算 CSV 字段

`imu_raw.csv` 兼容旧版本前 20 列，再在后面增加：

```
acc_scale_source,gyro_scale_source,cal_ax_g,cal_ay_g,cal_az_g,cal_gx_dps,cal_gy_dps,cal_gz_dps
```

`raw_ax`～`raw_gz` 永远是真实 MCU 16 位计数；`ax_g`～`gz_dps` 仅当 MCU 报告受支持的量程或操作员显式启用候选量程换算时有数字。`cal_*` 还要求对应 ACC/Gyro 标定 JSON 已匹配/授权，不能代表固件已写入参数。

数据状态：

- `MCU_VERIFIED`：量程来自此批次的 MCU 寄存器，支持 g/°/s 换算。
- `CAL_FILE_UNVERIFIED`：量程来自旧 JSON 的配置记录、且得到本次操作员许可。**仅研发试算**，不等于实际芯片硬件量程已经被核实。
- `UNKNOWN`：无法确认量程，**只能存原始计数**，相应物理量列留空。

温度和采样时间：本次仍使用 MCU 寄存器时间戳 + 主机每批到达时间，无法单凭 CSV 声称逐个样本均已严格同步；不能用来直接证明高精度动态时间相位。

## 现场使用步骤

1. 运行 WPF，选择报告保存目录及标定文件目录。
2. 扫描/选择 IMU 端口，连接并读取真实 UID（此前已现场验证该步可行）。
3. 查看自动匹配的两份 JSON，特别核对实物 PCB 身份、`sensor_configuration` 的 FS/ODR 来源。若只按六位 DTS 文件名匹配，请按真实工单核对后再勾选“已核实...属于当前 PCB”。
4. FS 寄存器仍为 0 的情况下：推荐先使用**原始计数模式**采一小段，以查明实际 MCU 驱动的量程和 FIFO 有效性；如果只需研发曲线，可勾选候选量程试算，但报告必须保留 `CAL_FILE_UNVERIFIED` 标签。
5. 选择定时与否，点击“开始采集”；完成后按钮自动恢复，数据保存到 `保存根目录\DTS编号_完整UID\时间_RAW_ACQUISITION\`。
6. 如需提前停止，再点击“停止采集”。**停止按钮只是停止数据采集，不会向转台发送运动/停车指令。**
7. CT-05 的校准文件路径会预填选定文件夹的 ACC JSON，但它仍要求真实 2TD 状态、机械安全和 MCU 量程有效，不能拿候选量程做正式静态角度验收。

## 真实硬件依然需要核实

- MCU 固件为什么把量程字段回传成零（也可能 ODR=0）；核实寄存器、加速度/陀螺仪真实 FS 配置和数据原始单位。
- 现场已有旧 JSON 可能标识 `device_serial=0002` 而文件名中是 `DTS672516`：本版不自动推断二者必然是同一 PCB。请结合生产工单或原始 UID 做身份绑定。
- 嵌入式/设备协议未提供对外量程读取的其他可靠通道时，暂时只能保留原始数据或明确标注候选换算。
- 当前运行环境无 Windows 和 .NET 10 SDK，代码做的是源码级静态验证；请在 Visual Studio 用 `dotnet build`/`Dts.SelfTest` 和真实硬件逐步联调。
