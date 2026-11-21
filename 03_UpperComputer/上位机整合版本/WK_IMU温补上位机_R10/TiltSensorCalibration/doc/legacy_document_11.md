# 上位机（倾角仪）数据读取 / 记录 —— 修改指南

> 目的：别人拿到这套代码后，知道**改数据读取、改记录**该动哪个文件、哪个常量。
> 涉及的程序目录：`D:\倾角仪研发上位机软件`（下称"工程目录"）。

---

## 0. 文件分工（谁负责什么）

| 文件 | 作用 | 常见改动 |
|---|---|---|
| `tilt_sensor\tilt_sensor_asm330_def.py` | **协议与换算常量**：串口/波特率默认值、从机地址、寄存器基址与数量、每帧样本数、量程灵敏度表、寄存器字段偏移、轮询节拍、错误码 | 换寄存器映射、换样本数、换节拍、换量程 |
| `tilt_sensor\tilt_sensor_asm330_comm.py` | **Modbus RTU 主机**：打开/关闭串口、构造请求帧、校验应答（长度/CRC/异常码）、保存最近收发 hex | 改功能码、改请求帧格式、改超时 |
| `tilt_sensor\tilt_sensor_asm330_data_get.py` | **采集线程**：20ms 节拍轮询、原始值→double 换算、空帧(未更新)过滤、"数据未更新5秒"判定、CSV 自动记录触发、读 `config.xml` | 改节拍逻辑、改换算、改空帧/无数据判定 |
| `tilt_sensor\tilt_sensor_asm330_csv.py` | **CSV 记录**：列定义、每帧16行、时间轴插值、写盘线程、记录目录与暂停标志 | 改 CSV 列/格式、改记录目录规则、改丢帧保护 |
| `form\form_tilt_sensor_cal.py` | **界面**：串口下拉/打开关闭、状态灯、加速度数据表、通讯框、数据记录页（路径 + 开始/暂停记录） | 改灯的颜色/文字、改界面显示逻辑 |
| `ui\mainWindow.ui` | **界面布局**（Qt Designer 文件）：所有控件的位置与文字 | 增删控件、改位置 |
| `config.xml` | **运行参数**：串口、波特率、记录目录等；程序启动读取，界面改动会写回 | 换串口、换记录目录 |

---

## 1. 常见修改场景 → 到底改哪里

### 1.1 换串口 / 波特率 / 从机地址
- **串口、波特率**：改 `config.xml` 的 `<IncCommPort>` / `<IncBaudrate>`（也可在界面下拉框选、点"打开串口"）；
  默认值在 `def.py`：`INC_COMM_PORT_DEFAULT`、`INC_BAUDRATE_DEFAULT`
- **从机地址**：`def.py` 的 `INC_COMM_ADDR_DEFAULT`（默认 1）；若换地址，`config.xml` 里加 `<IncCommAddr>2</IncCommAddr>` 即可

### 1.2 寄存器地址 / 数量 / 功能码 变了（固件映射变了）
- `def.py`：
  - `MB_REG_BASE_HR = 1000`（保持寄存器起始地址）
  - `ASM330_DATA_WORDS = 104`（一次读多少个寄存器）
  - `MB_FUNC_READ_HOLDING_REGISTERS = 3`、`MB_MAX_READ_REGISTERS = 126`（固件限幅）
- 请求帧构造在 `comm.py` 的 `_mb_read_holding_registers()`（改成读输入寄存器 0x04 就改这里 + 基址）

### 1.3 固件结构体字段/顺序变了【最关键，必须同步】
- `def.py` 的 `REG_OFF_*`（每个字段在寄存器里的**偏移**）：
  `REG_OFF_DATA_UNREAD(0)`、`REG_OFF_ACC_X(1)`、`REG_OFF_ACC_Y(17)`、`REG_OFF_ACC_Z(33)`、
  `REG_OFF_GYR_X(49)`、`REG_OFF_GYR_Y(65)`、`REG_OFF_GYR_Z(81)`、`REG_OFF_TEMP(97)`、
  `REG_OFF_TIME_LOW(98)`、`REG_OFF_TIME_HIGH(99)`、`REG_OFF_ACC_LEVEL(100)`、
  `REG_OFF_GYRO_LEVEL(101)`、`REG_OFF_DATA_ODR(102)`、`REG_OFF_FIFO_STATE(103)`
- 同步要看的两个地方：
  - `comm.py` 的 `tilt_sensor_data_get()` —— 按 `REG_OFF_*` 把寄存器拆成各轴数组
  - `csv.py` 的 `CSV_HEADER` 与 `csv_write_frame()` —— 记录的列

### 1.4 每帧样本数变了（现在是 16）
- `def.py`：`INC_SAMPLE_NUM = 16`
- 影响：`comm.py` 解析长度、`data_get.py` 平均值/表格、`csv.py` 每帧写 `INC_SAMPLE_NUM` 行 —— 都是引用该常量，改一处即可

### 1.5 轮询节拍 / 掉帧
- `def.py`：`MB_POLL_INTERVAL_MS_DEFAULT`（**当前 20ms**）
  经验：固件每凑满 16 个样本约需 19.2ms（833Hz），节拍 **必须 ≥20ms**，否则会读到"样本没凑满"的空帧导致丢数据；
  也可在 `config.xml` 用 `<IncPollIntervalMs>25</IncPollIntervalMs>` 覆盖

### 1.6 量程 / 换算系数
- `def.py`：`ACC_LSB_MG_TABLE`、`GYRO_LSB_MDPS_TABLE`（按寄存器里的 AccLevel/GyroLevel 取值）
- 固件若没填量程字段（恒为 0），程序用 `ACC_FS_DEFAULT=2` / `GYRO_FS_DEFAULT=2000` 兜底

### 1.7 记录目录 / 是否记录
- **界面**："数据记录"页 → 路径框（可直接输入）+「选择文件夹」+「开始记录」+「暂停记录」
  - 记录中：路径框**只读**、选择/开始按钮禁用（必须先"暂停记录"才能改路径）
  - 默认行为：**开机（收到第一帧数据）就自动开始记录**；点过"暂停记录"后不再自动记录，直到点"开始记录"
- **配置文件**：`config.xml` 的 `<IncDataSaveDir>D:\倾角仪数据</IncDataSaveDir>`
- **规则**：目录**不存在就不记录**（不会自动建目录），状态显示"未记录(记录目录不存在: …)"
- 相关函数：`csv.py` 的
  `CSV_DIR_DEFAULT` / `csv_dir_set()` / `csv_dir_path_get()` / `csv_dir_is_valid()` / `csv_dir_get()` /
  `csv_open()` / `csv_close()` / `csv_pause_set()` / `csv_pause_get()` / `csv_state_text_get()`

### 1.8 CSV 内容 / 格式
- `csv.py`：
  - `CSV_HEADER`：列名（timestamp、frame_index、sample_index、acc_x_g…gyr_z_dps、temp_c、量程、mcu_tick_ms、frame_interval_ms…）
  - `csv_write_frame()`：每帧写 `INC_SAMPLE_NUM` 行，时间轴按实测帧间隔均匀铺开（上限 `CSV_FRAME_INTERVAL_MAX_MS`）
  - `CSV_IDLE_CLOSE_SEC`：无数据自动收尾文件（默认 10s）；`CSV_FLUSH_INTERVAL_SEC`：写盘节流

### 1.9 "数据未更新(全0帧)"与状态灯
- `data_get.py`：
  - `tilt_sensor_raw_data_process()` 里判断**空帧**（6轴96个原始值全为0 → `is_data_valid=False`，不显示/不记录，只当作"设备还没把新数据填进寄存器"）
  - `DATA_NO_UPDATE_SEC = 5.0`：通讯正常但连续 5 秒没有新数据才提示"无数据"
  - 读取失败时才把 `is_data_available=False`（＝真正的通讯故障）
- `form\form_tilt_sensor_cal.py` 的 `timer_IncStateDisplay_Tick()` —— 状态灯规则：
  | 灯 | 文字 | 触发条件 |
  |---|---|---|
  | 灰 | 未连接 | 串口没打开 |
  | 黄 | CRC校验错误 | 应答 CRC 错 |
  | 红 | 从机无回复 / 其它错误文字 | 超时等通讯错误 |
  | 绿 | 无数据 | 通讯正常但连续 ≥5s 没有新数据 |
  | 绿 | 通讯正常 | 正常收到数据 |
  | 绿 | 等待数据 | 串口刚打开、还没收到第一帧 |
  断开瞬间会**清空加速度数据表并隐藏旧统计**，避免把旧数据当当前数据显示

---

## 2. 改完怎么自测（不用开界面）

```bat
cd /d D:\倾角仪研发上位机软件

:: ① 串口列表 + 读一帧并打印换算后的 double 数据（需串口空闲）
python tilt_sensor\tilt_sensor_asm330_comm.py
:: ② 采集线程自测：读 5 帧（含换算、CSV 自动记录触发）
python tilt_sensor\tilt_sensor_asm330_data_get.py
:: ③ CSV 模块自测：写 2 帧共 32 行并打印首尾行
python tilt_sensor\tilt_sensor_asm330_csv.py
:: ④ 直接启动界面
python main.py
```

设备侧（工程 `E:\u545cubemxproject\Dynamic_linometer_Test`）另有**不依赖上位机**的链路自检：

```bat
cd /d E:\u545cubemxproject\Dynamic_linometer_Test
python Tools\asm330_link_check.py -p COM5 -n 20 --raw
```

---

## 3. config.xml 的键（程序会读写）

| 键 | 含义 | 当前值 |
|---|---|---|
| `IncCommPort` | 测斜仪串口 | COM5 |
| `IncBaudrate` | 波特率 | 1500000 |
| `IncDataSaveDir` | **数据记录目录**（不存在就不记录） | D:\倾角仪数据 |
| `IncArrayNum` / `IncSegmentNum` | 阵列数 / 段数 | 1 / 1 |
| `IncAverageNum` / `IncAverageNumAIA` / `IncAIAEnable` | 平均次数 / AIA平均次数 / AIA使能 | 1 / 200 / True |
| `IncPollIntervalMs`（可选） | 轮询节拍(ms)，覆盖 def.py 默认值 | 未配置=用默认 20 |

---

## 4. 本次（2026-10-16）改动清单（便于交接/复盘）

| 文件 | 改动内容 |
|---|---|
| `tilt_sensor\tilt_sensor_asm330_def.py` | 轮询节拍默认值 `MB_POLL_INTERVAL_MS_DEFAULT` 5ms → **20ms**（消除"读快于填"造成的重复样本）|
| `tilt_sensor\tilt_sensor_asm330_comm.py` | 应答校验/收发 hex 记录（原有）；新增 CSV 时间戳所需字段（原有）|
| `tilt_sensor\tilt_sensor_asm330_data_get.py` | 空帧过滤（`is_data_valid`）、`DATA_NO_UPDATE_SEC=5s`、失败分支补 `is_data_available=False`、读 `IncDataSaveDir` |
| `tilt_sensor\tilt_sensor_asm330_csv.py` | 记录目录可配置且**不自动创建**、**目录不存在不记录**、暂停标志、「记录中」状态文字带目录；`mcu_sample_ms` 步进改为"帧间隔/16"；帧间隔上限钳位 `CSV_FRAME_INTERVAL_MAX_MS` |
| `form\form_tilt_sensor_cal.py` | 状态灯五态（灰/黄/红/绿正常/绿无数据/绿等待数据）、未连接时清空旧数据、通讯框新增"数据状态"行、数据记录页（路径+选择文件夹+开始/暂停记录、记录中禁止改路径）|
| `ui\mainWindow.ui` | 删除"加速度计校准补偿/安装误差校准补偿/X-Mark校准补偿/使用校准文件"4个复选框；新增"开始记录/暂停记录"按钮 |
| `config.xml` | `IncCommPort` → COM5；新增 `IncDataSaveDir`；运行期界面改动会写回 |
| `main.py`、`temperature_chamber\temperature_chamber_comm.py`、`temperature_chamber\plc_comm.py` | 加**本机 WMI 保护**（本机 `platform.system()` 走 WMI 会卡死，导致 snap7 导入卡死、界面起不来）；WMI 恢复正常后可删 |

