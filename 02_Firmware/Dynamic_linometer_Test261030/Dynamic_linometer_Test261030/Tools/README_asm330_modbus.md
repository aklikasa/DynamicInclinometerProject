# ASM330LHH IMU 数据上位机读取（Modbus RTU 主机）

本目录提供 PC 端 Python 程序，通过 **Modbus RTU 主机（Master/Client）** 读取 MCU 中
`ASM330_DATA` 共享结构体里的 IMU 数据，并把 int16 原始值按量程灵敏度换算成 **double**。

> ⚠️ 本程序**只是 Modbus 主站**。MCU 固件才是从机（Slave），不会主动上报数据，
> 必须由上位机轮询读取。程序内**不包含任何从机/服务端代码**，也不提供写寄存器功能。

## 1. 文件说明

| 文件 | 说明 |
| --- | --- |
| `asm330_modbus.py` | 主程序：量程/灵敏度 define、换算函数、寄存器解析、Modbus 主站客户端、CLI 演示 |
| `test_asm330_modbus.py` | 离线自测（不需要硬件）：换算/符号/映射/量程回退/CRC/串口开关状态机 |
| `README_asm330_modbus.md` | 本说明文件 |

## 2. 依赖与安装

```powershell
python -m pip install pymodbus        # 已实测 3.15.0（自动兼容 3.6~3.15 的 slave/device_id 差异）
# pyserial 3.5 已随 pymodbus 存在；本程序只用 pymodbus 的 client(主站) 一侧
```

* 已实装环境：Python 3.12.8 + pymodbus 3.15.0 + pyserial 3.5

## 3. 通信参数（与固件一致）

| 项目 | 值 | 来源 |
| --- | --- | --- |
| 协议 | Modbus **RTU**，8N1 | `app_lpuart0.c` |
| 波特率 | **1500000**（注释写 1M，实际 1.5M） | `LPUART0_BAUDRATE` / `USART1_BAUDRATE` |
| 从机地址 | **0x01**（LPUART1）；0x02（USART1/485） | `LPUART0_MB_SLAVE_ADDR` |
| 数据模型 | 保持寄存器基址 **1000**（0x03）、输入寄存器基址 **5000**（0x04） | `mbserial_slave_port.c` |
| 结构体长度 | **104 个寄存器**（208 字节，全 16 位成员无填充） | `sizeof(ASM330_DATA)/2` |
| 单片读取上限 | **1..126 个寄存器**（num>0x7E 会返回异常码 0x02） | `mbserial_slave.c` |
| 寄存器字节序 | **大端**（MSB 先发） | `PUTU16` / `MBDataToBigEndian` |
| 帧尾 CRC | **标准 Modbus CRC**（初值 FFFF、poly A001、**低字节先发**） | `crc16_lrc.c`，已实测比对 |

## 4. 快速开始（命令行演示）

```powershell
# 1) 查看本机串口
python asm330_modbus.py --list-ports

# 2) 只验证串口能不能“开 + 关”（不需要从机应答）
python asm330_modbus.py -p COM5 --open-test

# 3) 读 5 轮数据并打印换算后的 double
python asm330_modbus.py -p COM5 -n 5

# 4) 一直读并保存 CSV（Ctrl+C 停止）
python asm330_modbus.py -p COM5 --csv imu.csv

# 5) 用输入寄存器 0x04 读（基址 5000）、改量程、附带原始值
python asm330_modbus.py -p COM5 -r 5000 --acc-fs 4 --gyro-fs 500 --raw

# 6) 从机地址 0x02（USART1/485 那一路）
python asm330_modbus.py -p COM6 -s 0x02
```

输出示例：

```
[0001] tick=123456ms unread=1 odr=833Hz acc_fs=+-2g gyro_fs=+-2000dps state=0x0001[SENSOR_OK] temp=26.125C
      idx |       AccX[g]       AccY[g]       AccZ[g] |      GyrX[dps]      GyrY[dps]      GyrZ[dps]
        0 |       0.006100      -0.006100       1.001000 |       7.000000      -7.000000       0.000000
        ...
```

命令行参数：`-p 串口` `-b 波特率(默认1500000)` `-s 从机地址(默认0x01)` `-r 1000|5000`
`-n 轮数(0=无限)` `-i 间隔秒` `--timeout` `--retries` `--acc-fs` `--gyro-fs` `--force-fs`
`--raw` `--csv` `--list-ports` `--open-test` `--verbose`

## 5. 库方式使用（串口开/关由你自己的脚本显式控制）

```python
from asm330_modbus import Asm330ModbusClient, Asm330ModbusError

cli = Asm330ModbusClient(port="COM5", baudrate=1500000, slave_addr=0x01)  # 构造时不打开串口
cli.open()                       # 显式打开；失败抛 Asm330PortError（含中文原因）
try:
    while True:
        blk = cli.read_block()   # 一次读取 16 个样本并换算成 double
        print(blk.tick_ms, blk.acc_g[0], blk.gyro_dps[0], blk.temp_c)
except KeyboardInterrupt:
    pass
finally:
    cli.close()                  # 显式关闭（幂等，可重复调用）
```

### 串口开关相关 API

| 成员 | 说明 |
| --- | --- |
| `open() -> bool` | 显式打开串口：校验端口存在性 → `connect()` → 清收发缓冲；失败抛 `Asm330PortError` |
| `close() -> None` | 显式关闭串口，**幂等**；重复调用不报错；释放底层 pyserial 句柄 |
| `reopen() -> bool` | 关闭后重新打开（换端口/波特率、断线恢复） |
| `is_open`（属性） | 真实探测：同时检查 pymodbus `connected` 与底层 `socket.is_open` |
| `describe()` | 打印当前配置：端口/波特率/帧格式/从机地址/功能码/基址/数量/超时/重试 |
| `open_count` / `close_count` | 开关次数，便于自检与排障 |
| `with Asm330ModbusClient(...) as cli:` | 语法糖：进入自动 `open()`，离开自动 `close()` |
| `open_asm330_client("COM5")` | 便捷函数：创建并立即打开 |

### 读取 API

| 成员 | 说明 |
| --- | --- |
| `read_raw_words(start_addr=None, count=None) -> List[int]` | 读原始寄存器（16 位无符号），含重试与异常码翻译 |
| `read_block(...) -> ImuBlock` | 读一轮并换算：`acc_g`(×16 double) / `gyro_dps`(×16 double) / `temp_c` / `tick_ms` / 量程 / ODR / FIFO 标志 |
| `ImuBlock.sample_rows()` | 逐样本产出 dict，便于写 CSV/pandas |
| `ImuBlock.meta_text()` | 一行元信息字符串 |

固件可能自己关闭连接（pymodbus 连续失败后），此时：`auto_reconnect=False`（默认）会抛错让你自己决定；
置 `auto_reconnect=True` 则自动 `reopen()` 后继续重试。

## 6. 寄存器映射表（Python 解析依据）

| 偏移 | 地址（保持/输入） | 成员 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| 0 | 1000 / 5000 | DataUnRead | u16 | 0 = 本次没有新数据 |
| 1–16 | 1001–1016 | AccX[0..15] | i16 | 加速度计 X 轴原始值 |
| 17–32 | 1017–1032 | AccY[0..15] | i16 | 加速度计 Y 轴原始值 |
| 33–48 | 1033–1048 | AccZ[0..15] | i16 | 加速度计 Z 轴原始值 |
| 49–64 | 1049–1064 | GyrX[0..15] | i16 | 陀螺仪 X 轴原始值 |
| 65–80 | 1065–1080 | GyrY[0..15] | i16 | 陀螺仪 Y 轴原始值 |
| 81–96 | 1081–1096 | GyrZ[0..15] | i16 | 陀螺仪 Z 轴原始值 |
| 97 | 1097 | Temp | i16 | 温度原始值 |
| 98 / 99 | 1098 / 1099 | Time[0] / Time[1] | u16 | HAL_GetTick **低 16 位在前** |
| 100 | 1100 | AccLevel | u16 | 加速度量程(g)：2/4/8/16 |
| 101 | 1101 | GyroLevel | u16 | 陀螺仪量程(dps)：125…4000 |
| 102 | 1102 | DataODR | u16 | 输出速率(Hz) |
| 103 | 1103 | FIFO_State | u16 | 位标志（见下） |

`FIFO_State` 位：`0x0001` SENSOR_OK、`0x0002` SIM_MODE、`0x0010` FIFO_WTM、
`0x0020` FIFO_OVR、`0x0040` FIFO_FULL、`0x0080` FIFO_EMPTY、`0x0100` TAG_UNKNOWN

## 7. 量程与灵敏度（换算公式）

加速度计 `LA_So`（mg/LSB）：

| 量程 | 灵敏度 | Python define |
| --- | --- | --- |
| ±2 g | 0.061 | `ACC_SENS_2G_MG_PER_LSB` |
| ±4 g | 0.122 | `ACC_SENS_4G_MG_PER_LSB` |
| ±8 g | 0.244 | `ACC_SENS_8G_MG_PER_LSB` |
| ±16 g | 0.488 | `ACC_SENS_16G_MG_PER_LSB` |

陀螺仪 `G_So`（mdps/LSB）：

| 量程 | 灵敏度 | Python define |
| --- | --- | --- |
| ±125 dps | 4.37 | `GYRO_SENS_125DPS_MDPS_PER_LSB` |
| ±250 dps | 8.75 | `GYRO_SENS_250DPS_MDPS_PER_LSB` |
| ±500 dps | 17.5 | `GYRO_SENS_500DPS_MDPS_PER_LSB` |
| ±1000 dps | 35.0 | `GYRO_SENS_1000DPS_MDPS_PER_LSB` |
| ±2000 dps | 70.0 | `GYRO_SENS_2000DPS_MDPS_PER_LSB` |
| ±4000 dps | 140.0 | `GYRO_SENS_4000DPS_MDPS_PER_LSB` |

默认量程（当前固件）：`DEFAULT_ACC_FS_G = ACC_FS_2G`（±2G）、`DEFAULT_GYRO_FS_DPS = GYRO_FS_2000DPS`
（±2000dps）。**换量程只需改第 3、4 节的量程/灵敏度 define**，换算函数与查表自动生效。

换算公式（全部输出 **double**，**符号保持不变**）：

```
acc_g    = to_int16(raw) * ACC_SENS_MG_PER_LSB   / 1000.0     # mg  -> g
gyro_dps = to_int16(raw) * GYRO_SENS_MDPS_PER_LSB / 1000.0    # mdps-> dps
temp_c   = to_int16(raw) / 256.0 + 25.0                       # 256 LSB/℃, 25℃ 偏移
to_int16(x) = x - 0x10000  (x >= 0x8000)  否则 x                # 符号扩展，负值仍为负
```

对应的公开函数：`accel_raw_to_mg / accel_raw_to_g / gyro_raw_to_mdps / gyro_raw_to_dps /
temp_raw_to_celsius / to_int16`，以及 `acc_sens_mg_per_lsb(fs_g)` / `gyro_sens_mdps_per_lsb(fs_dps)`。

举例：`raw = 100 @ ±2g → 0.0061 g`；`raw = -100 @ ±2g → -0.0061 g`；
`raw = 0x8000 @ ±2g → -1.998848 g`；`raw = 0x8000 @ ±2000dps → -2293.76 dps`。

## 8. 固件侧注意事项（重要）

1. **量程字段目前为 0**：`app_spi.c` 的 `App_Asm330FifoRefresh()` 函数体被整段注释，
   `AccLevel / GyroLevel / DataODR / FIFO_State` 从未被写入，读回来是 0。
   本程序已按需求内置回退：读到 0/非法值时使用默认 ±2G / ±2000dps，并在输出里标记
   `acc_fs=+-2g(默认)`。若希望上位机读到真实量程，需要恢复该函数里的量程赋值代码。
2. **只读不写**：`mbserial_slave_port.c` 把 1000/5000 区段直接 `memcpy` 映射到 `Asm330MBData`，
   上位机一旦用 0x06/0x10 写寄存器就会破坏 IMU 数据结构，因此本程序**不提供写接口**。
3. **单次读取 ≤126 个寄存器**：本结构体 104 个可一次读完；若结构体以后变长需分段读。
4. **轮询取数**：数据是在“应答帧 DMA 发送完成”时才搬进共享结构体（`App_Asm330DirectTxDone`），
   所以主站需连续轮询；`DataUnRead=0` 表示这一轮没有新数据。
5. **1.5 Mbps 适配器**：CH340 / CP2102 / FT232 均可；若你的 USB-TTL 不支持，请下调固件
   `LPUART0_BAUDRATE` 并用 `-b` 同步，否则会一直超时。
6. **DTR/RTS 可能复位 MCU**：部分板子用 DTR/RTS 接 NRST/BOOT，打开串口瞬间会复位单片机，
   属正常现象；若影响使用需在硬件上断开该引脚。

## 9. 常见问题

| 现象 | 原因与处理 |
| --- | --- |
| `Asm330PortError: 串口 COMx 不存在` | 端口号变了或被拔出；用 `--list-ports` 确认，或用 `-p auto` |
| `Asm330PortError: 被其他程序占用/权限不足` | 关掉串口助手/其他实例；pymodbus 以独占方式打开串口 |
| `读取失败：... 已重试 N 次` | 从机没上电/没跑固件/波特率不符/收发线序反；用 `--verbose` 看每轮失败原因 |
| 从机异常码 `0x02` | 起始地址或数量非法（固件限制 1..126）；确认 `-r` 用 1000/5000 |
| 数据全为 0 且 `unread=0` | 这一轮没有新数据（从机尚未攒够 16 个样本），继续轮询即可 |
| `acc_fs=+-2g(默认)` | 量程字段为 0（见第 8 节第 1 条），此时用的是默认量程 |

## 10. 自测与验证结果（已实测）

```powershell
python test_asm330_modbus.py          # 离线自测，无需硬件
```

覆盖 27 项用例：换算正确性与符号保持（含 `0x8000/0x7FFF` 边界与全部 6 种陀螺仪量程）、
结构体偏移映射、量程取自寄存器 / 回退默认 / `--force-fs`、CRC 标准向量
（`CRC-16/MODBUS("123456789") = 0x4B37`、`01 03 00 00 00 0A → C5 CD`）、
主站 `open()/close()/reopen()` 状态机与幂等性、连接失败与端口不存在的中文报错、
异常帧翻译、超时重试、`is_open` 探测等。**实测结果：27/27 全部 PASS。**

真机串口开关（COM5，CP210x）：`open → is_open=True → close → is_open=False`，
`open_count=1 / close_count=1`，退出码 0。

真机请求帧字节级校验（在 COM5 上抓取上位机实际发出的字节）：
`01 03 03 E8 00 68 C4 54` —— 从机地址 0x01、功能码 0x03、起始地址 1000(0x03E8)、
数量 104(0x0068)、CRC=C454（低字节先发），与固件从机期望的帧格式完全一致。


