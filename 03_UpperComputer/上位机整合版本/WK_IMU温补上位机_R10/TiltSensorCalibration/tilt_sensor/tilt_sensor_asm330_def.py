"""ASM330 IMU相关定义"""

#
# 通讯参数定义
#
INC_COMM_PORT_DEFAULT = "COM12"          # 默认串口号（与config.xml的IncCommPort对应）
INC_COMM_ADDR_DEFAULT = 0x01            # 默认从机地址（MCU固件LPUART1=0x01，USART1/485=0x02）
INC_BAUDRATE_DEFAULT = 1500000          # 默认波特率（与MCU固件LPUART0_BAUDRATE一致）
INC_RESPONSE_TIMEOUT_MS_DEFAULT = 1000  # 默认通讯应答超时时间，单位毫秒
INC_ARRAY_NUM_DEFAULT = 1               # 默认阵列数（单机单IMU）
INC_SEGMENT_NUM_DEFAULT = 1             # 默认段数（单机单IMU）
INC_AVERAGE_NUM_DEFAULT = 1             # 默认平均次数
INC_AVERAGE_NUM_AIA_DEFAULT = 200       # AIA平均次数
INC_AIA_ENABLE_DEFAULT = True           # 默认AIA使能
INC_SERIAL_DATA_BITS = 8                # 数据位
INC_SERIAL_STOP_BITS = 1                # 停止位
INC_SERIAL_PARITY = 'N'                 # 校验位（以上三条即8N1）
MB_POLL_INTERVAL_MS_DEFAULT = 20        # 数据轮询节拍(ms)：20ms约等于固件填满一批16样本的时间(16/833Hz=19.2ms)，
                                        # 这样每次读到的16个样本都是新采样的；0=全速(读快于固件填速会出现重复值)
MB_USE_WIN_TIMER_RESOLUTION = True      # Windows下进程内请求1ms定时器精度(双保险)

#
# Modbus定义
#
MB_FUNC_READ_HOLDING_REGISTERS = 0x03   # 读保持寄存器
MB_FUNC_READ_INPUT_REGISTERS = 0x04     # 读输入寄存器
MB_EXCEPTION_FLAG = 0x80                # 异常帧标志（功能码 |= 0x80）
MB_MAX_READ_REGISTERS = 0x7E            # 固件限制：单次读取1~126个寄存器
MB_ERROR_CODE_FREE = 0                  # 无错
MB_ERROR_CODE_TIMEOUT = -1              # 无应答/超时
MB_ERROR_CODE_FRAME = -2                # 应答帧格式错误（长度/地址/功能码/字节数不符）
MB_ERROR_CODE_CRC = -3                  # CRC校验错误
MB_ERROR_CODE_EXCEPTION = -4            # 从机异常帧（异常码见mb_exception_code）
MB_ERROR_CODE_SERIAL_NOT_OPEN = -5      # 串口未打开
MB_ERROR_CODE_COMM_FAIL = -1            # 通讯失败（兼容旧名，等同TIMEOUT，原为-1）

#
# ASM330_DATA结构体寄存器映射定义（与MCU固件保持一致）
#   Protocol/Port/mbserial_slave_port.c : MB_REG_ASM330_BASE_HR=1000 / MB_REG_ASM330_BASE_IR=5000
#   APP/app_spi.h                       : typedef struct asm330_data (ASM330_DATA)
#
MB_REG_BASE_HR = 1000                   # 保持寄存器起始地址（功能码0x03）
MB_REG_BASE_IR = 5000                   # 输入寄存器起始地址（功能码0x04）
ASM330_DATA_WORDS = 104                 # sizeof(ASM330_DATA)/2，结构体共104个16位寄存器
INC_SAMPLE_NUM = 16                     # 每个轴一次上传的样本数
INC_ARRAY_SEGMENT_NUM_MAX = 1           # 阵列段数（单机单IMU）
INC_TABLE_KEEP_ROWS = 512               # 加速度数据页表格保留的最大行数(勾选"自动滚动刷新"时)
INC_TABLE_KEEP_ROWS_PAUSED = 4096       # 取消勾选(暂停跟随)时保留的最大行数，便于任意翻看历史

REG_OFF_DATA_UNREAD = 0                 # uint16    未读取的FIFO批次数(0=本次没有新数据)
REG_OFF_ACC_X = 1                       # int16[16] 加速度计X轴原始值
REG_OFF_ACC_Y = 17                      # int16[16] 加速度计Y轴原始值
REG_OFF_ACC_Z = 33                      # int16[16] 加速度计Z轴原始值
REG_OFF_GYR_X = 49                      # int16[16] 陀螺仪X轴原始值
REG_OFF_GYR_Y = 65                      # int16[16] 陀螺仪Y轴原始值
REG_OFF_GYR_Z = 81                      # int16[16] 陀螺仪Z轴原始值
REG_OFF_TEMP = 97                       # int16     温度原始值
REG_OFF_TIME_LOW = 98                   # uint16    采样时间HAL_GetTick低16位
REG_OFF_TIME_HIGH = 99                  # uint16    采样时间HAL_GetTick高16位
REG_OFF_ACC_LEVEL = 100                 # uint16    加速度量程(g)：2/4/8/16
REG_OFF_GYRO_LEVEL = 101                # uint16    陀螺仪量程(dps)：125/250/500/1000/2000/4000
REG_OFF_DATA_ODR = 102                  # uint16    输出速率(Hz)
REG_OFF_FIFO_STATE = 103                # uint16    FIFO状态位标志

#
# FIFO状态位定义（与固件app_spi.h的ASM330_STATE_*一致）
#
FIFO_STATE_SENSOR_OK = 0x0001           # 传感器正常
FIFO_STATE_SIM_MODE = 0x0002            # 模拟数据模式
FIFO_STATE_FIFO_WTM = 0x0010            # 水印中断标志
FIFO_STATE_FIFO_OVR = 0x0020            # FIFO溢出标志
FIFO_STATE_FIFO_FULL = 0x0040           # FIFO满标志
FIFO_STATE_FIFO_EMPTY = 0x0080          # FIFO空标志
FIFO_STATE_TAG_UNKNOWN = 0x0100         # 出现未知TAG

#
# 加速度计量程定义（单位g）
#
ACC_FS_2G = 2                           # ±2g
ACC_FS_4G = 4                           # ±4g
ACC_FS_8G = 8                           # ±8g
ACC_FS_16G = 16                         # ±16g

#
# 陀螺仪量程定义（单位dps）
#
GYRO_FS_125DPS = 125                    # ±125dps
GYRO_FS_250DPS = 250                    # ±250dps
GYRO_FS_500DPS = 500                    # ±500dps
GYRO_FS_1000DPS = 1000                  # ±1000dps
GYRO_FS_2000DPS = 2000                  # ±2000dps
GYRO_FS_4000DPS = 4000                  # ±4000dps

#
# 加速度计灵敏度定义LA_So（单位mg/LSB）
#
ACC_LSB_2G_MG = 0.061                   # @LA_FS = ±2g
ACC_LSB_4G_MG = 0.122                   # @LA_FS = ±4g
ACC_LSB_8G_MG = 0.244                   # @LA_FS = ±8g
ACC_LSB_16G_MG = 0.488                  # @LA_FS = ±16g

#
# 陀螺仪灵敏度定义G_So（单位mdps/LSB）
#
GYRO_LSB_125DPS_MDPS = 4.37             # @G_FS = ±125dps
GYRO_LSB_250DPS_MDPS = 8.75             # @G_FS = ±250dps
GYRO_LSB_500DPS_MDPS = 17.5             # @G_FS = ±500dps
GYRO_LSB_1000DPS_MDPS = 35.0            # @G_FS = ±1000dps
GYRO_LSB_2000DPS_MDPS = 70.0            # @G_FS = ±2000dps
GYRO_LSB_4000DPS_MDPS = 140.0           # @G_FS = ±4000dps

# 量程->灵敏度查表（换算函数使用，以后换量程只需改上面的define）
ACC_LSB_MG_TABLE = {
    ACC_FS_2G: ACC_LSB_2G_MG,
    ACC_FS_4G: ACC_LSB_4G_MG,
    ACC_FS_8G: ACC_LSB_8G_MG,
    ACC_FS_16G: ACC_LSB_16G_MG,
}
GYRO_LSB_MDPS_TABLE = {
    GYRO_FS_125DPS: GYRO_LSB_125DPS_MDPS,
    GYRO_FS_250DPS: GYRO_LSB_250DPS_MDPS,
    GYRO_FS_500DPS: GYRO_LSB_500DPS_MDPS,
    GYRO_FS_1000DPS: GYRO_LSB_1000DPS_MDPS,
    GYRO_FS_2000DPS: GYRO_LSB_2000DPS_MDPS,
    GYRO_FS_4000DPS: GYRO_LSB_4000DPS_MDPS,
}

#
# 默认量程定义（结构体未给出量程或量程非法时使用）
#
ACC_FS_DEFAULT = ACC_FS_2G              # 默认±2G
GYRO_FS_DEFAULT = GYRO_FS_250DPS        # 默认±250dps

#
# 温度定义（ASM330：256LSB/℃，25℃对应0LSB）
#
TEMP_LSB_PER_DEGC = 256.0               # 温度灵敏度
TEMP_OFFSET_DEGC = 25.0                 # 25℃偏移

#
# 原始值换算函数（统一输出double，符号保持不变）
#   换算公式：物理量 = int16(原始值) * 灵敏度
#     加速度：g   = 原始值 * ACC_LSB_*_MG   / 1000.0   （mg -> g）
#     角速度：dps = 原始值 * GYRO_LSB_*_MDPS / 1000.0  （mdps -> dps）
#     温度：  ℃  = 原始值 / 256.0 + 25.0
#   原始值为16位无符号寄存器值时，先做符号扩展（0x8000~0xFFFF视为负数），
#   再乘正灵敏度，因此负值换算后仍为负值（符号不会变化）。
#

def to_int16(uint16_value):
    """
    将16位无符号寄存器值还原为有符号int16（符号扩展）

    Args:
        uint16_value (int): 16位无符号值（或已经是负数的原始值）

    Returns:
        int: 有符号int16值。例：0x0000->0，0x7FFF->32767，0xFFFF->-1，0x8000->-32768

    Raises:

    Note:

    """
    value = int(uint16_value) & 0xFFFF
    if value >= 0x8000:
        return value - 0x10000
    return value


def acc_fs_is_valid(acc_fs):
    """
    判断加速度量程是否合法

    Args:
        acc_fs (int): 加速度量程(g)

    Returns:
        bool: 是支持的量程(2/4/8/16)，返回True；否则返回False

    Raises:

    Note:

    """
    return acc_fs in ACC_LSB_MG_TABLE


def gyro_fs_is_valid(gyro_fs):
    """
    判断陀螺仪量程是否合法

    Args:
        gyro_fs (int): 陀螺仪量程(dps)

    Returns:
        bool: 是支持的量程(125/250/500/1000/2000/4000)，返回True；否则返回False

    Raises:

    Note:

    """
    return gyro_fs in GYRO_LSB_MDPS_TABLE


def acc_lsb_mg_get(acc_fs=ACC_FS_DEFAULT):
    """
    获取加速度计灵敏度

    Args:
        acc_fs (int): 加速度量程(g)，默认±2G

    Returns:
        float: 灵敏度(mg/LSB)；量程非法时返回默认量程(±2G)的灵敏度

    Raises:

    Note:

    """
    if not acc_fs_is_valid(acc_fs):
        acc_fs = ACC_FS_DEFAULT
    return ACC_LSB_MG_TABLE[acc_fs]


def gyro_lsb_mdps_get(gyro_fs=GYRO_FS_DEFAULT):
    """
    获取陀螺仪灵敏度

    Args:
        gyro_fs (int): 陀螺仪量程(dps)，默认±2000dps

    Returns:
        float: 灵敏度(mdps/LSB)；量程非法时返回默认量程(±2000dps)的灵敏度

    Raises:

    Note:

    """
    if not gyro_fs_is_valid(gyro_fs):
        gyro_fs = GYRO_FS_DEFAULT
    return GYRO_LSB_MDPS_TABLE[gyro_fs]


def accel_raw_to_mg(raw, acc_fs=ACC_FS_DEFAULT):
    """
    加速度原始值换算为毫g（double）

    Args:
        raw (int): 加速度原始值（int16，或Modbus读到的16位无符号值）
        acc_fs (int): 加速度量程(g)，默认±2G

    Returns:
        float: 加速度值(mg)。例：raw=100 @±2g -> 6.1；raw=-100 @±2g -> -6.1

    Raises:

    Note:

    """
    return to_int16(raw) * acc_lsb_mg_get(acc_fs)


def accel_raw_to_g(raw, acc_fs=ACC_FS_DEFAULT):
    """
    加速度原始值换算为g（double，符号保持不变）

    Args:
        raw (int): 加速度原始值（int16，或Modbus读到的16位无符号值）
        acc_fs (int): 加速度量程(g)，默认±2G

    Returns:
        float: 加速度值(g)。例：raw=100 -> 0.0061；raw=-100 -> -0.0061；
               raw=0x8000(-32768) @±2g -> -1.998848

    Raises:

    Note:

    """
    return accel_raw_to_mg(raw, acc_fs) / 1000.0


def gyro_raw_to_mdps(raw, gyro_fs=GYRO_FS_DEFAULT):
    """
    陀螺仪原始值换算为毫度每秒（double）

    Args:
        raw (int): 陀螺仪原始值（int16，或Modbus读到的16位无符号值）
        gyro_fs (int): 陀螺仪量程(dps)，默认±2000dps

    Returns:
        float: 角速度值(mdps)。例：raw=100 @±2000dps -> 7000.0

    Raises:

    Note:

    """
    return to_int16(raw) * gyro_lsb_mdps_get(gyro_fs)


def gyro_raw_to_dps(raw, gyro_fs=GYRO_FS_DEFAULT):
    """
    陀螺仪原始值换算为度每秒（double，符号保持不变）

    Args:
        raw (int): 陀螺仪原始值（int16，或Modbus读到的16位无符号值）
        gyro_fs (int): 陀螺仪量程(dps)，默认±2000dps

    Returns:
        float: 角速度值(dps)。例：raw=100 -> 7.0；raw=-100 -> -7.0；
               raw=0x8000(-32768) @±2000dps -> -2293.76

    Raises:

    Note:

    """
    return gyro_raw_to_mdps(raw, gyro_fs) / 1000.0


def temp_raw_to_celsius(raw):
    """
    温度原始值换算为摄氏度（double）

    Args:
        raw (int): 温度原始值（int16）

    Returns:
        float: 温度值(℃)。例：raw=0 -> 25.0；raw=-256 -> 24.0；raw=6400 -> 50.0

    Raises:

    Note:

    """
    return to_int16(raw) / TEMP_LSB_PER_DEGC + TEMP_OFFSET_DEGC


def fifo_state_text_arr_get(fifo_state):
    """
    将FIFO状态位翻译为文字列表，便于界面显示

    Args:
        fifo_state (int): FIFO状态位

    Returns:
        list: 状态文字列表，如["SENSOR_OK", "FIFO_WTM"]

    Raises:

    Note:

    """
    state_text_arr = []
    if fifo_state & FIFO_STATE_SENSOR_OK:
        state_text_arr.append("SENSOR_OK")
    if fifo_state & FIFO_STATE_SIM_MODE:
        state_text_arr.append("SIM_MODE")
    if fifo_state & FIFO_STATE_FIFO_WTM:
        state_text_arr.append("FIFO_WTM")
    if fifo_state & FIFO_STATE_FIFO_OVR:
        state_text_arr.append("FIFO_OVR")
    if fifo_state & FIFO_STATE_FIFO_FULL:
        state_text_arr.append("FIFO_FULL")
    if fifo_state & FIFO_STATE_FIFO_EMPTY:
        state_text_arr.append("FIFO_EMPTY")
    if fifo_state & FIFO_STATE_TAG_UNKNOWN:
        state_text_arr.append("TAG_UNKNOWN")
    return state_text_arr