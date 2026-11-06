# -*- coding: utf-8 -*-
"""
asm330_modbus.py —— ASM330LHH IMU 数据上位机程序（Modbus RTU 主机 / Master）

功能
    1. 以 Modbus RTU **主机（主站）**身份读取 MCU 侧 ASM330_DATA 结构体：
       保持寄存器基址 1000（功能码 0x03）和输入寄存器基址 5000（功能码 0x04）
       映射到同一块共享内存 Asm330MBData。
    2. 把结构体里的 int16 原始值按量程灵敏度（加速度 mg/LSB、角速度 mdps/LSB）
       换算成 double 输出，**符号保持不变**；量程取自结构体中的 AccLevel/GyroLevel，
       未给出（为 0 或非法）时回退默认量程 ±2G / ±2000dps。

寄存器映射来源（与固件一一对应，固件改动后需同步修改本文件）
    Protocol/Port/mbserial_slave_port.c : MB_REG_ASM330_BASE_HR = 1000, MB_REG_ASM330_BASE_IR = 5000
    APP/app_spi.h                       : typedef struct asm330_data (ASM330_DATA)
    APP/app_lpuart0.h                   : LPUART0_BAUDRATE = 1500000, LPUART0_MB_SLAVE_ADDR = 0x01
    APP/app_usart.h                     : USART1_BAUDRATE = 1500000, USART1_MB_SLAVE_ADDR = 0x02

注意事项
    * 本程序只实现 Modbus **主站**，不含任何从机/服务端代码；MCU 固件才是从机。
    * 从机固件把 1000/5000 区段直接映射到 Asm330MBData 结构体内存（memcpy 直接写入），
      因此本程序只提供读接口，不提供写寄存器接口（写会破坏 IMU 数据结构）。
    * 单次读取寄存器数量固件限制为 1..126（mbserial_slave.c 中 num>0x7E 返回异常码 0x02），
      本结构体共 104 个寄存器，可一次读完。
    * 上位机是主站，必须主动轮询；MCU 不会主动上报。固件在“应答帧 DMA 发送完成”时才把
      最新 16 组样本搬进共享结构体（App_Asm330DirectTxDone），故需连续轮询取数。

用法（库方式，串口开/关由调用者显式控制）
    from asm330_modbus import Asm330ModbusClient
    cli = Asm330ModbusClient(port="COM5", baudrate=1500000, slave_addr=0x01)
    cli.open()
    try:
        blk = cli.read_block()
        print(blk.acc_g[0], blk.gyro_dps[0], blk.temp_c)
    finally:
        cli.close()

用法（命令行演示）
    python asm330_modbus.py --list-ports
    python asm330_modbus.py -p COM5 --open-test
    python asm330_modbus.py -p COM5 -n 5 --csv out.csv

依赖：pymodbus（已实测 3.15.0）、pyserial
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

__all__ = [
    "Asm330ModbusClient", "Asm330ModbusError", "Asm330PortError", "ImuBlock",
    "parse_asm330_block", "open_asm330_client",
    "to_int16", "accel_raw_to_mg", "accel_raw_to_g",
    "gyro_raw_to_mdps", "gyro_raw_to_dps", "temp_raw_to_celsius",
    "acc_sens_mg_per_lsb", "gyro_sens_mdps_per_lsb", "decode_fifo_state",
    "crc16_modbus",
]

# ---------------------------------------------------------------------------
# 可选依赖：pymodbus（仅使用“主站 / client”一侧）与 pyserial（端口探测）
# ---------------------------------------------------------------------------
try:
    import serial                                   # pyserial
    import serial.tools.list_ports                  # 串口枚举
    _PYSERIAL_OK = True
except ImportError:                                 # pragma: no cover
    serial = None                                   # type: ignore
    _PYSERIAL_OK = False

try:
    import pymodbus
    from pymodbus.client import ModbusSerialClient
    from pymodbus.exceptions import (ConnectionException, ModbusException,
                                     ModbusIOException)
    try:
        from pymodbus.constants import ExcCodes     # pymodbus >= 3.9
    except ImportError:                             # pragma: no cover
        ExcCodes = None                             # type: ignore
    _PYMODBUS_OK = True
except ImportError:                                 # pragma: no cover
    pymodbus = None                                 # type: ignore
    ModbusSerialClient = None                       # type: ignore
    ConnectionException = ModbusException = ModbusIOException = Exception  # type: ignore
    ExcCodes = None                                 # type: ignore
    _PYMODBUS_OK = False

# ===========================================================================
# 一、串口 / 协议参数 define（与固件 app_lpuart0.h、app_usart.h 保持一致）
# ===========================================================================

DEFAULT_BAUDRATE   = 1500000        # 与 LPUART0_BAUDRATE / USART1_BAUDRATE 一致(1.5Mbps)
DEFAULT_SLAVE_ADDR = 0x01           # LPUART1 那一路从机地址；USART1(485) 那一路为 0x02
DEFAULT_TIMEOUT    = 1.0            # 单次请求超时(s)。1.5Mbps 下 104 寄存器应答约 215B≈1.4ms
DEFAULT_RETRIES    = 3              # 超时重试次数
DEFAULT_PARITY     = "N"            # 8N1
DEFAULT_BYTESIZE   = 8
DEFAULT_STOPBITS   = 1

MB_FUNC_READ_HOLDING_REGISTERS = 0x03   # 读保持寄存器（基址 1000）
MB_FUNC_READ_INPUT_REGISTERS   = 0x04   # 读输入寄存器（基址 5000）

# 常见 USB-TTL 芯片 VID（--port auto 自动选择时使用）
USB_SERIAL_VIDS = (0x1A86,   # WCH CH340/CH341
                   0x10C4,   # Silicon Labs CP210x
                   0x0403,   # FTDI
                   0x2341,   # Arduino
                   0x0483)   # STMicroelectronics


# ===========================================================================
# 二、寄存器映射 define（与 APP/app_spi.h 的 ASM330_DATA 结构体严格对应）
# ===========================================================================

MB_REG_ASM330_BASE_HR = 1000        # 保持寄存器起始地址（mbserial_slave_port.c）
MB_REG_ASM330_BASE_IR = 5000        # 输入寄存器起始地址（同上）
ASM330_DATA_WORDS     = 104         # sizeof(ASM330_DATA)/2，结构体共 104 个 16 位寄存器
SAMPLES_PER_BLOCK     = 16          # 每个轴的上传样本数
MB_MAX_READ_REGISTERS = 0x7E        # 固件限制：单次读取 1..126 个寄存器

# ---- 结构体成员在寄存器数组中的偏移（单位：16 位寄存器） ----
REG_OFF_DATA_UNREAD = 0             # uint16    未读取的 FIFO 批次数(0=本次没有新数据)
REG_OFF_ACC_X       = 1             # int16[16] 加速度计 X 轴原始值
REG_OFF_ACC_Y       = 17            # int16[16] 加速度计 Y 轴原始值
REG_OFF_ACC_Z       = 33            # int16[16] 加速度计 Z 轴原始值
REG_OFF_GYR_X       = 49            # int16[16] 陀螺仪 X 轴原始值
REG_OFF_GYR_Y       = 65            # int16[16] 陀螺仪 Y 轴原始值
REG_OFF_GYR_Z       = 81            # int16[16] 陀螺仪 Z 轴原始值
REG_OFF_TEMP        = 97            # int16     温度原始值(每次只上传一个)
REG_OFF_TIME_LOW    = 98            # uint16    采样时间 HAL_GetTick 低 16 位
REG_OFF_TIME_HIGH   = 99            # uint16    采样时间 HAL_GetTick 高 16 位
REG_OFF_ACC_LEVEL   = 100           # uint16    加速度量程(g)：2/4/8/16
REG_OFF_GYRO_LEVEL  = 101           # uint16    陀螺仪量程(dps)：125/250/500/1000/2000/4000
REG_OFF_DATA_ODR    = 102           # uint16    输出速率(Hz)
REG_OFF_FIFO_STATE  = 103           # uint16    FIFO 状态位标志

# ---- FIFO_State 位定义（与 app_spi.h 的 ASM330_STATE_* 一致） ----
FIFO_STATE_SENSOR_OK   = 0x0001     # 传感器正常
FIFO_STATE_SIM_MODE    = 0x0002     # 模拟数据模式
FIFO_STATE_FIFO_WTM    = 0x0010     # 水印中断标志
FIFO_STATE_FIFO_OVR    = 0x0020     # FIFO 溢出标志
FIFO_STATE_FIFO_FULL   = 0x0040     # FIFO 满标志
FIFO_STATE_FIFO_EMPTY  = 0x0080     # FIFO 空标志
FIFO_STATE_TAG_UNKNOWN = 0x0100     # 出现未知 TAG

# ---- Modbus 异常码说明（把从机异常帧翻译成人话） ----
MODBUS_EXCEPTION_TEXT: Dict[int, str] = {
    0x01: "非法功能码(0x01)：从机不支持该功能码",
    0x02: "非法数据地址/数量(0x02)：起始地址或寄存器数量非法，固件限制单次读取 1..126 个",
    0x03: "非法数据值(0x03)",
    0x04: "从机设备故障(0x04)",
    0x05: "确认(0x05)：从机已接受请求，正在处理",
    0x06: "从机设备忙(0x06)",
    0x07: "否认(0x07)",
    0x08: "存储奇偶校验错误(0x08)",
    0x0A: "网关路径不可用(0x0A)",
    0x0B: "网关目标设备无响应(0x0B)：通常为超时或从机地址不匹配",
}

# ===========================================================================
# 三、量程 define（与 Device/asm330.h 中 ASM330_FS_* 的物理量程对应，便于以后替换）
# ===========================================================================

# ---- 加速度计量程(单位 g) ----
ACC_FS_2G  = 2
ACC_FS_4G  = 4
ACC_FS_8G  = 8
ACC_FS_16G = 16

# ---- 陀螺仪量程(单位 dps) ----
GYRO_FS_125DPS  = 125
GYRO_FS_250DPS  = 250
GYRO_FS_500DPS  = 500
GYRO_FS_1000DPS = 1000
GYRO_FS_2000DPS = 2000
GYRO_FS_4000DPS = 4000

# ---- 默认量程：当前固件为 ±2G / ±2000dps ----
#    （app_spi.c: App_Asm330SetParam(ASM330_ODR_833HZ, ASM330_FS_2G, ASM330_ODR_833HZ, ASM330_FS_2000DPS)）
DEFAULT_ACC_FS_G     = ACC_FS_2G            # 默认 ±2G
DEFAULT_GYRO_FS_DPS  = GYRO_FS_2000DPS      # 默认 ±2000dps

ACC_FS_CHOICES  = (ACC_FS_2G, ACC_FS_4G, ACC_FS_8G, ACC_FS_16G)
GYRO_FS_CHOICES = (GYRO_FS_125DPS, GYRO_FS_250DPS, GYRO_FS_500DPS,
                   GYRO_FS_1000DPS, GYRO_FS_2000DPS, GYRO_FS_4000DPS)


# ===========================================================================
# 四、灵敏度 define（mg/LSB、mdps/LSB，数据来自 ASM330LHH 数据手册）
#     以后换量程只需要改这一节，换算函数会自动使用新值。
# ===========================================================================

# ---- 加速度计灵敏度 LA_So (mg/LSB) ----
ACC_SENS_2G_MG_PER_LSB  = 0.061     # @LA_FS = ±2 g
ACC_SENS_4G_MG_PER_LSB  = 0.122     # @LA_FS = ±4 g
ACC_SENS_8G_MG_PER_LSB  = 0.244     # @LA_FS = ±8 g
ACC_SENS_16G_MG_PER_LSB = 0.488     # @LA_FS = ±16 g

# ---- 陀螺仪灵敏度 G_So (mdps/LSB) ----
GYRO_SENS_125DPS_MDPS_PER_LSB  = 4.37      # @G_FS = ±125 dps
GYRO_SENS_250DPS_MDPS_PER_LSB  = 8.75      # @G_FS = ±250 dps
GYRO_SENS_500DPS_MDPS_PER_LSB  = 17.5      # @G_FS = ±500 dps
GYRO_SENS_1000DPS_MDPS_PER_LSB = 35.0      # @G_FS = ±1000 dps
GYRO_SENS_2000DPS_MDPS_PER_LSB = 70.0      # @G_FS = ±2000 dps
GYRO_SENS_4000DPS_MDPS_PER_LSB = 140.0     # @G_FS = ±4000 dps

# ---- 量程 -> 灵敏度 查表（换算函数用这个表） ----
ACC_SENS_MG_PER_LSB: Dict[int, float] = {
    ACC_FS_2G:  ACC_SENS_2G_MG_PER_LSB,
    ACC_FS_4G:  ACC_SENS_4G_MG_PER_LSB,
    ACC_FS_8G:  ACC_SENS_8G_MG_PER_LSB,
    ACC_FS_16G: ACC_SENS_16G_MG_PER_LSB,
}

GYRO_SENS_MDPS_PER_LSB: Dict[int, float] = {
    GYRO_FS_125DPS:  GYRO_SENS_125DPS_MDPS_PER_LSB,
    GYRO_FS_250DPS:  GYRO_SENS_250DPS_MDPS_PER_LSB,
    GYRO_FS_500DPS:  GYRO_SENS_500DPS_MDPS_PER_LSB,
    GYRO_FS_1000DPS: GYRO_SENS_1000DPS_MDPS_PER_LSB,
    GYRO_FS_2000DPS: GYRO_SENS_2000DPS_MDPS_PER_LSB,
    GYRO_FS_4000DPS: GYRO_SENS_4000DPS_MDPS_PER_LSB,
}

# ---- 温度：ASM330LHH 温度灵敏度 256 LSB/℃，25℃ 为 0 LSB ----
TEMP_LSB_PER_DEGC = 256.0
TEMP_OFFSET_DEGC  = 25.0


def acc_sens_mg_per_lsb(fs_g: int = DEFAULT_ACC_FS_G) -> float:
    """取加速度计灵敏度(mg/LSB)。量程非法时抛 ValueError。"""
    try:
        return ACC_SENS_MG_PER_LSB[int(fs_g)]
    except KeyError:
        raise ValueError(
            "不支持的加速度量程 %r，可用量程：%s" % (fs_g, sorted(ACC_SENS_MG_PER_LSB))
        ) from None


def gyro_sens_mdps_per_lsb(fs_dps: int = DEFAULT_GYRO_FS_DPS) -> float:
    """取陀螺仪灵敏度(mdps/LSB)。量程非法时抛 ValueError。"""
    try:
        return GYRO_SENS_MDPS_PER_LSB[int(fs_dps)]
    except KeyError:
        raise ValueError(
            "不支持的陀螺仪量程 %r，可用量程：%s" % (fs_dps, sorted(GYRO_SENS_MDPS_PER_LSB))
        ) from None

# ===========================================================================
# 五、原始值 -> 物理量 换算函数（核心：输出 double，符号保持不变）
#     公式：物理量 = int16(原始值) * 灵敏度
#       加速度：acc_g     = raw * ACC_SENS_MG_PER_LSB / 1000.0     (mg -> g)
#       角速度：gyro_dps  = raw * GYRO_SENS_MDPS_PER_LSB / 1000.0  (mdps -> dps)
#       温度  ：temp_c    = raw / 256.0 + 25.0
#     int16 原始值先做符号扩展：0x8000..0xFFFF 视为负数，
#     再乘正系数，因此负值换算后仍然是负值（符号不会被破坏）。
# ===========================================================================

def to_int16(u16: int) -> int:
    """把 Modbus 读到的 16 位无符号寄存器值还原成有符号 int16（符号扩展）。

    例：0x0000 -> 0，0x7FFF -> 32767，0xFFFF -> -1，0x8000 -> -32768
    """
    value = int(u16) & 0xFFFF
    return value - 0x10000 if value >= 0x8000 else value


def accel_raw_to_mg(raw: int, fs_g: int = DEFAULT_ACC_FS_G) -> float:
    """加速度原始值 -> 毫 g(mg)，返回 double。

    :param raw:  结构体中的 int16 原始值（或 Modbus 读到的 uint16）
    :param fs_g: 加速度量程(g)，默认 ±2G
    例：raw=100  @±2g -> 6.1 mg；raw=-100 @±2g -> -6.1 mg
    """
    return float(to_int16(raw)) * acc_sens_mg_per_lsb(fs_g)


def accel_raw_to_g(raw: int, fs_g: int = DEFAULT_ACC_FS_G) -> float:
    """加速度原始值 -> g，返回 double（符号保持不变）。

    例：raw=100   @±2g -> 0.0061 g
        raw=-100  @±2g -> -0.0061 g
        raw=0x8000@±2g -> -1.998848 g
    """
    return accel_raw_to_mg(raw, fs_g) / 1000.0


def gyro_raw_to_mdps(raw: int, fs_dps: int = DEFAULT_GYRO_FS_DPS) -> float:
    """角速度原始值 -> 毫度每秒(mdps)，返回 double。

    例：raw=100 @±2000dps -> 7000.0 mdps
    """
    return float(to_int16(raw)) * gyro_sens_mdps_per_lsb(fs_dps)


def gyro_raw_to_dps(raw: int, fs_dps: int = DEFAULT_GYRO_FS_DPS) -> float:
    """角速度原始值 -> 度每秒(dps)，返回 double（符号保持不变）。

    例：raw=100   @±2000dps -> 7.0 dps
        raw=-100  @±2000dps -> -7.0 dps
        raw=0x8000@±2000dps -> -2293.76 dps
    """
    return gyro_raw_to_mdps(raw, fs_dps) / 1000.0


def temp_raw_to_celsius(raw: int) -> float:
    """温度原始值 -> 摄氏度(double)。ASM330LHH：256 LSB/℃，25℃ 对应 0 LSB。

    例：raw=0 -> 25.0 ℃；raw=-256 -> 24.0 ℃；raw=6400 -> 50.0 ℃
    """
    return float(to_int16(raw)) / TEMP_LSB_PER_DEGC + TEMP_OFFSET_DEGC


def decode_fifo_state(state: int) -> List[str]:
    """把 FIFO_State 位标志翻译成可读字符串列表。"""
    flags: List[str] = []
    for mask, text in ((FIFO_STATE_SENSOR_OK, "SENSOR_OK"),
                       (FIFO_STATE_SIM_MODE, "SIM_MODE"),
                       (FIFO_STATE_FIFO_WTM, "FIFO_WTM"),
                       (FIFO_STATE_FIFO_OVR, "FIFO_OVR"),
                       (FIFO_STATE_FIFO_FULL, "FIFO_FULL"),
                       (FIFO_STATE_FIFO_EMPTY, "FIFO_EMPTY"),
                       (FIFO_STATE_TAG_UNKNOWN, "TAG_UNKNOWN")):
        if int(state) & mask:
            flags.append(text)
    return flags

# ===========================================================================
# 六、数据结构与解析（Modbus 寄存器数组 -> 物理量）
# ===========================================================================

@dataclass
class ImuBlock:
    """一次读取得到的一组 IMU 数据（16 个样本）。所有物理量均为 double(float)。"""

    data_unread: int = 0                        # 未读取的 FIFO 批次数(0=没有新数据)
    acc_g: List[float] = field(default_factory=list)      # 16 个 X/Y/Z 加速度(g)
    gyro_dps: List[float] = field(default_factory=list)   # 16 个 X/Y/Z 角速度(dps)
    acc_raw: List[Tuple[int, int, int]] = field(default_factory=list)   # 原始值(便于调试)
    gyro_raw: List[Tuple[int, int, int]] = field(default_factory=list)
    temp_c: float = 0.0                         # 温度(℃)
    temp_raw: int = 0                           # 温度原始值
    tick_ms: int = 0                            # MCU 侧 HAL_GetTick(ms, 32 位)
    acc_fs_g: int = DEFAULT_ACC_FS_G            # 本次换算使用的加速度量程(g)
    gyro_fs_dps: int = DEFAULT_GYRO_FS_DPS      # 本次换算使用的陀螺仪量程(dps)
    acc_fs_from_reg: bool = False               # 量程是否来自寄存器(False=使用默认值)
    gyro_fs_from_reg: bool = False
    data_odr_hz: int = 0                        # 输出速率(Hz)
    fifo_state: int = 0                         # FIFO 状态位
    fifo_flags: List[str] = field(default_factory=list)
    pc_time: float = 0.0                        # 上位机本地时间(time.time())

    def meta_text(self) -> str:
        """一行元信息，便于打印。"""
        acc_src = "" if self.acc_fs_from_reg else "(默认)"
        gyr_src = "" if self.gyro_fs_from_reg else "(默认)"
        flags = ",".join(self.fifo_flags) if self.fifo_flags else "-"
        return ("tick=%dms unread=%d odr=%dHz acc_fs=+-%dg%s gyro_fs=+-%ddps%s "
                "state=0x%04X[%s] temp=%.3fC" % (
                    self.tick_ms, self.data_unread, self.data_odr_hz,
                    self.acc_fs_g, acc_src, self.gyro_fs_dps, gyr_src,
                    self.fifo_state, flags, self.temp_c))

    def sample_rows(self):
        """按样本逐行产出 dict（用于 CSV / pandas）。"""
        for i in range(len(self.acc_g)):
            ax, ay, az = self.acc_g[i]
            gx, gy, gz = self.gyro_dps[i]
            yield {
                "pc_time": self.pc_time,
                "tick_ms": self.tick_ms,
                "data_unread": self.data_unread,
                "data_odr_hz": self.data_odr_hz,
                "acc_fs_g": self.acc_fs_g,
                "gyro_fs_dps": self.gyro_fs_dps,
                "fifo_state": self.fifo_state,
                "sample_idx": i,
                "acc_x_g": ax, "acc_y_g": ay, "acc_z_g": az,
                "gyr_x_dps": gx, "gyr_y_dps": gy, "gyr_z_dps": gz,
                "temp_c": self.temp_c,
            }


def parse_asm330_block(words: Sequence[int],
                       acc_fs_g: int = DEFAULT_ACC_FS_G,
                       gyro_fs_dps: int = DEFAULT_GYRO_FS_DPS,
                       force_fs: bool = False,
                       pc_time: Optional[float] = None) -> ImuBlock:
    """把 104 个寄存器值解析成 ImuBlock（含 int16->double 换算）。

    :param words:      寄存器数组（元素为 16 位无符号值，长度 >= 104）
    :param acc_fs_g:   回退/强制使用的加速度量程(g)
    :param gyro_fs_dps:回退/强制使用的陀螺仪量程(dps)
    :param force_fs:   True 时忽略寄存器中的量程，强制使用入参量程
    :param pc_time:    上位机时间戳，默认取当前 time.time()
    :raises ValueError: 寄存器数量不足
    """
    if len(words) < ASM330_DATA_WORDS:
        raise ValueError("寄存器数量不足：需要 %d 个，实际 %d 个"
                         % (ASM330_DATA_WORDS, len(words)))

    # ---- 量程判定：优先用结构体上报值，非法/为 0 则回退默认值 ----
    reg_acc = int(words[REG_OFF_ACC_LEVEL])
    reg_gyro = int(words[REG_OFF_GYRO_LEVEL])
    if force_fs:
        acc_fs, acc_from_reg = int(acc_fs_g), False
        gyro_fs, gyro_from_reg = int(gyro_fs_dps), False
    else:
        if reg_acc in ACC_SENS_MG_PER_LSB:
            acc_fs, acc_from_reg = reg_acc, True
        else:
            acc_fs, acc_from_reg = int(acc_fs_g), False
        if reg_gyro in GYRO_SENS_MDPS_PER_LSB:
            gyro_fs, gyro_from_reg = reg_gyro, True
        else:
            gyro_fs, gyro_from_reg = int(gyro_fs_dps), False

    blk = ImuBlock(
        data_unread=int(words[REG_OFF_DATA_UNREAD]),
        temp_c=temp_raw_to_celsius(words[REG_OFF_TEMP]),
        temp_raw=to_int16(words[REG_OFF_TEMP]),
        tick_ms=(int(words[REG_OFF_TIME_HIGH]) << 16) | int(words[REG_OFF_TIME_LOW]),
        acc_fs_g=acc_fs,
        gyro_fs_dps=gyro_fs,
        acc_fs_from_reg=acc_from_reg,
        gyro_fs_from_reg=gyro_from_reg,
        data_odr_hz=int(words[REG_OFF_DATA_ODR]),
        fifo_state=int(words[REG_OFF_FIFO_STATE]),
        pc_time=time.time() if pc_time is None else float(pc_time),
    )
    blk.fifo_flags = decode_fifo_state(blk.fifo_state)

    for i in range(SAMPLES_PER_BLOCK):
        ax = to_int16(words[REG_OFF_ACC_X + i])
        ay = to_int16(words[REG_OFF_ACC_Y + i])
        az = to_int16(words[REG_OFF_ACC_Z + i])
        gx = to_int16(words[REG_OFF_GYR_X + i])
        gy = to_int16(words[REG_OFF_GYR_Y + i])
        gz = to_int16(words[REG_OFF_GYR_Z + i])

        blk.acc_raw.append((ax, ay, az))
        blk.gyro_raw.append((gx, gy, gz))
        blk.acc_g.append((accel_raw_to_g(ax, acc_fs),
                          accel_raw_to_g(ay, acc_fs),
                          accel_raw_to_g(az, acc_fs)))
        blk.gyro_dps.append((gyro_raw_to_dps(gx, gyro_fs),
                             gyro_raw_to_dps(gy, gyro_fs),
                             gyro_raw_to_dps(gz, gyro_fs)))
    return blk

# ===========================================================================
# 七、工具：Modbus CRC16（与固件一致性验证用）与异常类
# ===========================================================================

def crc16_modbus(data: bytes) -> int:
    """计算标准 Modbus CRC16（初值 0xFFFF，反射多项式 0xA001），返回 16 位值。

    线上按“低字节在前”发送。已用固件 Protocol/Source/crc16_lrc.c 的 crc16() 算法
    实测比对：'01 03 00 00 00 0A' -> 帧尾 'C5 CD'，与标准 Modbus 完全一致。
    """
    crc = 0xFFFF
    for byte in bytes(data):
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 0x0001 else crc >> 1
    return crc & 0xFFFF


class Asm330ModbusError(Exception):
    """上位机读取/通信过程中的通用错误。"""


class Asm330PortError(Asm330ModbusError):
    """串口打开/关闭相关错误（端口不存在、被占用、权限不足等）。"""


# ===========================================================================
# 八、串口列举/自动选择 辅助函数
# ===========================================================================

def list_serial_ports() -> List[Dict[str, object]]:
    """列出本机所有串口：device/description/hwid/vid/pid。"""
    if not _PYSERIAL_OK:                                   # pragma: no cover
        return []
    result: List[Dict[str, object]] = []
    for port in serial.tools.list_ports.comports():
        result.append({
            "device": port.device,
            "description": port.description,
            "hwid": port.hwid,
            "vid": port.vid,
            "pid": port.pid,
        })
    return result


def find_usb_serial_port() -> Optional[str]:
    """按常见 USB-TTL 芯片 VID 自动选择一个串口，找不到返回 None。"""
    for info in list_serial_ports():
        if info.get("vid") in USB_SERIAL_VIDS:
            return str(info["device"])
    ports = list_serial_ports()
    return str(ports[0]["device"]) if ports else None


# ===========================================================================
# 九、Modbus 主站客户端（串口开关由调用者显式调用 open()/close() 控制）
# ===========================================================================

class Asm330ModbusClient:
    """ASM330LHH 数据读取用 Modbus RTU **主站**客户端。

    设计要点
        * 只做主机（client）：读保持寄存器 0x03 或读输入寄存器 0x04；
          不提供任何写寄存器接口（写会破坏从机侧共享结构体）。
        * 串口“开/关”完全显式：open() / close() / reopen()，is_open 可查询；
          构造对象时不会自动打开串口（auto_open 默认为 False）。
        * pymodbus 3.x 版本自适应：自动识别 unit 参数名是 device_id(>=3.9) 还是 slave。

    例：
        cli = Asm330ModbusClient(port="COM5", baudrate=1500000, slave_addr=0x01)
        cli.open()
        try:
            blk = cli.read_block()
        finally:
            cli.close()
    """

    def __init__(self,
                 port: Optional[str] = None,
                 baudrate: int = DEFAULT_BAUDRATE,
                 slave_addr: int = DEFAULT_SLAVE_ADDR,
                 func_code: int = MB_FUNC_READ_HOLDING_REGISTERS,
                 start_addr: Optional[int] = None,
                 count: int = ASM330_DATA_WORDS,
                 timeout: float = DEFAULT_TIMEOUT,
                 retries: int = DEFAULT_RETRIES,
                 parity: str = DEFAULT_PARITY,
                 bytesize: int = DEFAULT_BYTESIZE,
                 stopbits: int = DEFAULT_STOPBITS,
                 reconnect_delay: float = 0.2,
                 auto_reconnect: bool = False,
                 framer=None,
                 verbose: bool = False,
                 auto_open: bool = False,
                 client_factory=None):
        if func_code not in (MB_FUNC_READ_HOLDING_REGISTERS, MB_FUNC_READ_INPUT_REGISTERS):
            raise ValueError("func_code 只支持 0x03(保持寄存器) 或 0x04(输入寄存器)")
        if not (1 <= count <= MB_MAX_READ_REGISTERS):
            raise ValueError("count 必须为 1..%d（固件限制）" % MB_MAX_READ_REGISTERS)

        self.port = port
        self.baudrate = int(baudrate)
        self.slave_addr = int(slave_addr)
        self.func_code = int(func_code)
        self.count = int(count)
        if start_addr is None:
            start_addr = (MB_REG_ASM330_BASE_HR
                          if func_code == MB_FUNC_READ_HOLDING_REGISTERS
                          else MB_REG_ASM330_BASE_IR)
        self.start_addr = int(start_addr)
        self.timeout = float(timeout)
        self.retries = int(retries)
        self.parity = parity
        self.bytesize = int(bytesize)
        self.stopbits = int(stopbits)
        self.reconnect_delay = float(reconnect_delay)
        self.auto_reconnect = bool(auto_reconnect)
        self.framer = framer
        self.verbose = bool(verbose)
        self._client_factory = client_factory
        self._client = None
        self._unit_kwarg = self._detect_unit_kwarg()
        self.open_count = 0                 # open() 成功次数（便于自检）
        self.close_count = 0                # close() 执行次数
        self.opened_at = 0.0
        self.closed_at = 0.0
        if auto_open:
            self.open()

    # ---------------- pymodbus 版本自适应 ----------------
    @staticmethod
    def _detect_unit_kwarg() -> str:
        """判断从机地址关键字：pymodbus>=3.9 为 device_id，早期版本为 slave。"""
        if not _PYMODBUS_OK:                                # pragma: no cover
            return "device_id"
        try:
            import inspect
            params = inspect.signature(
                ModbusSerialClient.read_holding_registers).parameters
            if "device_id" in params:
                return "device_id"
            if "slave" in params:
                return "slave"
        except (TypeError, ValueError):                     # pragma: no cover
            pass
        return "device_id"

    # ---------------- 串口 开 / 关 / 重开 ----------------
    def describe(self) -> str:
        """当前配置描述（用于打印）。"""
        fname = {MB_FUNC_READ_HOLDING_REGISTERS: "0x03 保持寄存器",
                 MB_FUNC_READ_INPUT_REGISTERS: "0x04 输入寄存器"}[self.func_code]
        return ("port=%s baud=%d %d%s%d slave=0x%02X %s start=%d count=%d timeout=%.2fs retries=%d"
                % (self.port, self.baudrate, self.bytesize, self.parity, self.stopbits,
                   self.slave_addr, fname, self.start_addr, self.count, self.timeout,
                   self.retries))

    @property
    def is_open(self) -> bool:
        """查询串口是否真的处于打开状态（同时检查 pymodbus 与底层 pyserial 句柄）。"""
        client = self._client
        if client is None:
            return False
        try:
            if not getattr(client, "connected", False):         # socket is not None
                return False
            sock = getattr(client, "socket", None)
            if sock is not None and not getattr(sock, "is_open", True):
                return False
            return True
        except Exception:                                       # pragma: no cover
            return False

    def _resolve_port(self) -> str:
        """解析并校验端口号：支持 'auto' 自动选择；端口不存在时给出可用列表。"""
        port = self.port
        if port is None or str(port).lower() == "auto":
            port = find_usb_serial_port()
            if not port:
                raise Asm330PortError(
                    "未找到可用串口，请检查 USB 转串口是否插入，或先用 --list-ports 查看")
            self.port = port
        port = str(port)
        if _PYSERIAL_OK and port.upper().startswith("COM"):
            names = [str(p.device) for p in serial.tools.list_ports.comports()]
            if port.upper() not in [n.upper() for n in names]:
                raise Asm330PortError(
                    "串口 %s 不存在（可能被拔出或端口号变化）。当前可用串口：%s"
                    % (port, names if names else "无"))
        return port

    @staticmethod
    def _probe_open_error(port: str) -> str:
        """用 pyserial 独占方式试开一次，把失败原因翻译成中文提示。"""
        if not _PYSERIAL_OK:                                     # pragma: no cover
            return ""
        try:
            handle = serial.Serial(port, timeout=0.05, exclusive=True)
            handle.close()
            return "端口可正常独占打开，请检查从机是否上电、波特率/从机地址/接线是否正确"
        except Exception as exc:                                # noqa: BLE001
            text = str(exc)
            low = text.lower()
            if isinstance(exc, PermissionError) or "access is denied" in low or "拒绝访问" in text \
                    or "被占用" in text or "denied" in low:
                return "串口 %s 被其他程序占用（如串口助手/调试器）或权限不足：%s" % (port, text)
            if "could not open port" in low or isinstance(exc, FileNotFoundError):
                return "串口 %s 不存在或已被拔出：%s" % (port, text)
            return "串口 %s 打开失败：%s" % (port, text)

    def open(self) -> bool:
        """显式打开串口。成功返回 True；失败抛 Asm330PortError（含中文原因）。

        说明：pymodbus 的 connect() 内部会吞掉异常只返回 False，因此这里在失败时
              额外用 pyserial 探测一次，以给出“端口不存在 / 被占用 / 权限不足”的明确提示。
        """
        if not _PYMODBUS_OK:
            raise Asm330ModbusError(
                "未安装 pymodbus，请先执行：python -m pip install pymodbus")
        if self.is_open:
            return True

        port = self._resolve_port()
        factory = self._client_factory or ModbusSerialClient
        kwargs = dict(baudrate=self.baudrate,
                      bytesize=self.bytesize,
                      parity=self.parity,
                      stopbits=self.stopbits,
                      timeout=self.timeout,
                      retries=self.retries)
        if self.framer is not None:                 # 默认即 RTU，一般无需传
            kwargs["framer"] = self.framer

        self._client = factory(port, **kwargs)
        try:
            ok = bool(self._client.connect())
        except Exception as exc:                    # noqa: BLE001  打开失败
            self.close()
            raise Asm330PortError("打开串口失败：%s；%s"
                                  % (exc, self._probe_open_error(port))) from exc
        if not ok:
            self.close()
            raise Asm330PortError("打开串口 %s 失败：%s" % (port, self._probe_open_error(port)))

        self._flush_buffers()
        self.open_count += 1
        self.opened_at = time.time()
        if self.verbose:
            print("[open] %s" % self.describe())
        return True

    def close(self) -> None:
        """显式关闭串口（幂等：重复调用不会报错）。"""
        client, self._client = self._client, None
        if client is not None:
            try:
                client.close()
            except Exception as exc:                # noqa: BLE001  关闭时的异常不影响退出
                if self.verbose:
                    print("[close] 忽略异常：%s" % exc)
        self.close_count += 1
        self.closed_at = time.time()
        if self.verbose:
            print("[close] port=%s 已关闭" % self.port)

    def reopen(self) -> bool:
        """关闭后重新打开（用于换端口/断线恢复）。"""
        self.close()
        if self.reconnect_delay > 0:
            time.sleep(self.reconnect_delay)
        return self.open()

    def _flush_buffers(self) -> None:
        """清空底层串口收发缓冲（防止上一次残留数据被当成应答）。"""
        sock = getattr(self._client, "socket", None)
        for name in ("reset_input_buffer", "reset_output_buffer"):
            func = getattr(sock, name, None)
            if callable(func):
                try:
                    func()
                except Exception:                   # noqa: BLE001  尽力而为
                    pass

    # ---------------- 上下文管理 / 析构兜底 ----------------
    def __enter__(self) -> "Asm330ModbusClient":
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def __del__(self):                              # pragma: no cover
        try:
            if getattr(self, "_client", None) is not None:
                self.close()
        except Exception:
            pass

    # ---------------- 读取寄存器 ----------------
    @staticmethod
    def _exc_code_text(code) -> str:
        """把异常码翻译成中文说明。"""
        try:
            value = int(getattr(code, "value", code))
        except (TypeError, ValueError):                         # pragma: no cover
            return "未知异常码：%r" % (code,)
        return MODBUS_EXCEPTION_TEXT.get(value, "未知异常码 0x%02X" % value)

    def _read_registers_once(self, address: int, count: int):
        """发起一次读请求（主站 -> 从机），返回 pymodbus 响应对象。"""
        unit_kw = {self._unit_kwarg: self.slave_addr}
        if self.func_code == MB_FUNC_READ_HOLDING_REGISTERS:
            return self._client.read_holding_registers(
                address=address, count=count, **unit_kw)
        return self._client.read_input_registers(
            address=address, count=count, **unit_kw)

    def read_raw_words(self, start_addr: Optional[int] = None,
                       count: Optional[int] = None) -> List[int]:
        """读取原始寄存器值（16 位无符号列表）。

        :raises Asm330ModbusError: 串口未打开、超时、从机异常等
        """
        if not self.is_open:
            raise Asm330ModbusError("串口未打开，请先调用 open()")
        addr = self.start_addr if start_addr is None else int(start_addr)
        num = self.count if count is None else int(count)
        if not (1 <= num <= MB_MAX_READ_REGISTERS):
            raise ValueError("count 必须为 1..%d（固件限制）" % MB_MAX_READ_REGISTERS)

        last_error = None
        for attempt in range(1, self.retries + 1):
            try:
                resp = self._read_registers_once(addr, num)
            except (ModbusIOException, ConnectionException, ModbusException) as exc:
                last_error = Asm330ModbusError("请求异常(%s)：%s" % (type(exc).__name__, exc))
            except Exception as exc:                            # noqa: BLE001
                last_error = Asm330ModbusError("通信失败：%s" % exc)
            else:
                if resp is None:
                    last_error = Asm330ModbusError("从机无响应（返回空响应对象）")
                elif resp.isError():
                    code = getattr(resp, "exception_code", None)
                    last_error = Asm330ModbusError(
                        "从机返回异常帧：%s" % self._exc_code_text(code))
                else:
                    regs = getattr(resp, "registers", None)
                    if regs is None:
                        last_error = Asm330ModbusError("应答中不含寄存器数据")
                    else:
                        return [int(v) & 0xFFFF for v in regs]

            if self.verbose:
                print("[read] 第 %d/%d 次失败：%s" % (attempt, self.retries, last_error))

            # 连接已断开（pymodbus 在连续失败后可能自行关闭连接）：按需重连
            if not self.is_open:
                self.close()
                if not self.auto_reconnect:
                    raise Asm330ModbusError(
                        "串口连接已断开：%s（auto_reconnect=False，可手动 reopen()）"
                        % last_error) from None
                time.sleep(self.reconnect_delay)
                self.open()

        raise Asm330ModbusError("读取寄存器失败（已重试 %d 次）：%s" % (self.retries, last_error))

    def read_block(self, start_addr: Optional[int] = None,
                   count: Optional[int] = None,
                   acc_fs_g: int = DEFAULT_ACC_FS_G,
                   gyro_fs_dps: int = DEFAULT_GYRO_FS_DPS,
                   force_fs: bool = False) -> ImuBlock:
        """读取一轮数据并换算成物理量（double）。

        :param acc_fs_g:    寄存器未给出量程时使用的加速度量程（默认 ±2G）
        :param gyro_fs_dps: 寄存器未给出量程时使用的陀螺仪量程（默认 ±2000dps）
        :param force_fs:    True 时无条件使用上面两个量程
        :returns: ImuBlock（acc_g / gyro_dps 均为 double 元组列表）
        """
        words = self.read_raw_words(start_addr=start_addr, count=count)
        return parse_asm330_block(words, acc_fs_g=acc_fs_g,
                                  gyro_fs_dps=gyro_fs_dps, force_fs=force_fs)


def open_asm330_client(port: Optional[str] = None, **kwargs) -> Asm330ModbusClient:
    """便捷函数：创建客户端并显式打开串口（等价于 open()），失败抛 Asm330PortError。

    例：cli = open_asm330_client("COM5"); ...; cli.close()
    """
    client = Asm330ModbusClient(port=port, **kwargs)
    client.open()
    return client

# ===========================================================================
# 十、命令行演示（本程序是主站；这里演示如何显式 open()/close()）
# ===========================================================================

CSV_FIELDS = ["pc_time", "tick_ms", "data_unread", "data_odr_hz", "acc_fs_g",
              "gyro_fs_dps", "fifo_state", "sample_idx",
              "acc_x_g", "acc_y_g", "acc_z_g",
              "gyr_x_dps", "gyr_y_dps", "gyr_z_dps", "temp_c"]


def print_ports() -> None:
    """打印本机串口列表。"""
    ports = list_serial_ports()
    print("本机串口（%d 个）：" % len(ports))
    if not ports:
        print("  无。请检查 USB 转串口是否插入、驱动是否安装。")
        return
    for info in ports:
        vid = info.get("vid")
        pid = info.get("pid")
        vidpid = ("%04X:%04X" % (vid, pid)) if (vid is not None and pid is not None) else "-"
        print("  %-8s %-45s VID:PID=%s" % (info["device"], info["description"], vidpid))


def print_block(block: ImuBlock, seq: int, show_raw: bool = False) -> None:
    """打印一组 16 个样本（换算后的 double）。"""
    print("[%04d] %s" % (seq, block.meta_text()))
    print("      idx |       AccX[g]       AccY[g]       AccZ[g] "
          "|      GyrX[dps]      GyrY[dps]      GyrZ[dps]")
    for i in range(len(block.acc_g)):
        acc = block.acc_g[i]
        gyr = block.gyro_dps[i]
        line = ("      %3d | %14.6f %14.6f %14.6f | %14.6f %14.6f %14.6f"
                % (i, acc[0], acc[1], acc[2], gyr[0], gyr[1], gyr[2]))
        if show_raw:
            a = block.acc_raw[i]
            g = block.gyro_raw[i]
            line += " | raw a=%6d,%6d,%6d g=%6d,%6d,%6d" % (
                a[0], a[1], a[2], g[0], g[1], g[2])
        print(line)

def build_arg_parser() -> argparse.ArgumentParser:
    """命令行参数（本程序为 Modbus 主站）。"""
    parser = argparse.ArgumentParser(
        description="ASM330LHH IMU 数据上位机读取程序（Modbus RTU 主机/Master，"
                    "默认 1500000bps，默认从机地址 0x01）",
        formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("-p", "--port", default=None,
                        help="串口号，如 COM5；填 auto 自动选择 USB 串口")
    parser.add_argument("-b", "--baudrate", type=int, default=DEFAULT_BAUDRATE,
                        help="波特率，默认 %(default)s（与固件 LPUART0_BAUDRATE 一致）")
    parser.add_argument("-s", "--slave", type=lambda v: int(v, 0), default=DEFAULT_SLAVE_ADDR,
                        help="从机地址，默认 0x01(LPUART1)； 485 那一路为 0x02")
    parser.add_argument("-r", "--register", type=int, default=MB_REG_ASM330_BASE_HR,
                        choices=[MB_REG_ASM330_BASE_HR, MB_REG_ASM330_BASE_IR],
                        help="寄存器基址：1000=保持寄存器(0x03)，5000=输入寄存器(0x04)")
    parser.add_argument("-n", "--count", type=int, default=0,
                        help="读取轮数，0 表示一直读取（Ctrl+C 停止），默认 0")
    parser.add_argument("-i", "--interval", type=float, default=0.02,
                        help="两轮读取之间的间隔秒数，默认 %(default)s")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT,
                        help="单次请求超时秒数，默认 %(default)s")
    parser.add_argument("--retries", type=int, default=DEFAULT_RETRIES,
                        help="超时重试次数，默认 %(default)s")
    parser.add_argument("--acc-fs", type=int, default=DEFAULT_ACC_FS_G,
                        choices=list(ACC_FS_CHOICES),
                        help="加速度量程(g)，寄存器未给量程时使用，默认 %(default)s")
    parser.add_argument("--gyro-fs", type=int, default=DEFAULT_GYRO_FS_DPS,
                        choices=list(GYRO_FS_CHOICES),
                        help="陀螺仪量程(dps)，寄存器未给量程时使用，默认 %(default)s")
    parser.add_argument("--force-fs", action="store_true",
                        help="强制使用 --acc-fs/--gyro-fs，忽略寄存器上报的量程")
    parser.add_argument("--raw", action="store_true", help="同时打印 int16 原始值")
    parser.add_argument("--csv", default=None, help="把数据保存为 CSV 文件")
    parser.add_argument("--list-ports", action="store_true", help="列出本机串口后退出")
    parser.add_argument("--open-test", action="store_true",
                        help="只做“打开串口 -> 打印配置 -> 关闭串口”，验证串口开关是否正常")
    parser.add_argument("--verbose", action="store_true", help="打印调试信息")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """命令行入口（演示显式 open()/close() 用法）。"""
    args = build_arg_parser().parse_args(argv)

    if args.list_ports:
        print_ports()
        return 0

    if args.port is None:
        print("错误：请用 -p 指定串口（或 -p auto 自动选择），也可先用 --list-ports 查看")
        return 2

    client = Asm330ModbusClient(port=args.port,
                                baudrate=args.baudrate,
                                slave_addr=args.slave,
                                func_code=(MB_FUNC_READ_HOLDING_REGISTERS
                                           if args.register == MB_REG_ASM330_BASE_HR
                                           else MB_FUNC_READ_INPUT_REGISTERS),
                                timeout=args.timeout,
                                retries=args.retries,
                                verbose=args.verbose)

    # ---- 显式打开串口（本程序的串口开关由调用者控制） ----
    try:
        client.open()
    except Asm330ModbusError as exc:
        print("打开串口失败：%s" % exc)
        return 3
    print("串口已打开：%s" % client.describe())

    if args.open_test:
        print("is_open = %s" % client.is_open)
        client.close()
        print("串口已关闭：is_open = %s" % client.is_open)
        return 0

    csv_file = None
    csv_writer = None
    if args.csv:
        csv_file = open(args.csv, "w", newline="", encoding="utf-8-sig")
        csv_writer = csv.DictWriter(csv_file, fieldnames=CSV_FIELDS)
        csv_writer.writeheader()

    seq = 0
    try:
        while (args.count <= 0) or (seq < args.count):
            try:
                block = client.read_block(acc_fs_g=args.acc_fs,
                                          gyro_fs_dps=args.gyro_fs,
                                          force_fs=args.force_fs)
            except Asm330ModbusError as exc:
                print("读取失败：%s" % exc)
                return 4
            seq += 1
            print_block(block, seq, show_raw=args.raw)
            if csv_writer is not None:
                csv_writer.writerows(block.sample_rows())
            if args.interval > 0:
                time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n用户中断（Ctrl+C）")
    finally:
        # ---- 无论正常结束还是异常/中断，都要显式关闭串口 ----
        if csv_file is not None:
            csv_file.close()
            print("CSV 已保存：%s" % args.csv)
        client.close()
        print("串口已关闭：is_open = %s（open=%d 次, close=%d 次）"
              % (client.is_open, client.open_count, client.close_count))
    return 0


if __name__ == "__main__":
    sys.exit(main())
