"""原工程 ASM330 Modbus RTU 协议的独立封装。
来源：tilt_sensor_asm330_comm.py / tilt_sensor_asm330_def.py。
读取 1000 起共 104 个保持寄存器，每帧16组XYZ加速度/角速度。
"""
from __future__ import annotations
from dataclasses import dataclass
import statistics

ACC_SCALE_MG = {2: .061, 4: .122, 8: .244, 16: .488}
GYRO_SCALE_MDPS = {125: 4.37, 250: 8.75, 500: 17.5, 1000: 35., 2000: 70., 4000: 140.}
WORDS = 104


def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for value in data:
        crc ^= value
        for _ in range(8):
            crc = (crc >> 1) ^ (0xA001 if crc & 1 else 0)
    return crc & 0xFFFF


def signed16(val: int) -> int:
    val &= 0xFFFF
    return val - 0x10000 if val >= 0x8000 else val


class IMUProtocolError(RuntimeError):
    pass


@dataclass
class IMUFrame:
    tick_ms: int
    unread: int
    acc_fs: int
    gyro_fs: int
    acc_fs_reported: bool
    gyro_fs_reported: bool
    odr: int
    fifo: int
    temp_c: float
    accel_g: tuple[float, float, float]
    gyro_dps: tuple[float, float, float]
    valid: bool
    accel_samples_g: tuple = ()


def decode(words: list[int], previous_acc_fs: int = 2, previous_gyro_fs: int = 2000) -> IMUFrame:
    if len(words) != WORDS:
        raise IMUProtocolError(f'寄存器数量错误：{len(words)}，应为104')
    acc_reported = words[100] in ACC_SCALE_MG
    gyro_reported = words[101] in GYRO_SCALE_MDPS
    acc_fs = words[100] if acc_reported else previous_acc_fs
    gyro_fs = words[101] if gyro_reported else previous_gyro_fs
    if acc_fs not in ACC_SCALE_MG: acc_fs = 2
    if gyro_fs not in GYRO_SCALE_MDPS: gyro_fs = 2000
    def avg(offset, multiplier):
        return statistics.fmean(signed16(v) * multiplier for v in words[offset:offset+16])
    acc = tuple(avg(off, ACC_SCALE_MG[acc_fs] / 1000) for off in (1, 17, 33))
    gyro = tuple(avg(off, GYRO_SCALE_MDPS[gyro_fs] / 1000) for off in (49, 65, 81))
    # 与旧工程一致：六轴96个样本全零才标记无新数据；unread=0不自动判无效
    any_samples = any(words[i] != 0 for i in range(1, 97))
    return IMUFrame((words[99] << 16) | words[98], words[0], acc_fs, gyro_fs,
                    acc_reported, gyro_reported, words[102], words[103],
                    signed16(words[97]) / 256 + 25, acc, gyro, bool(any_samples),
                    tuple(tuple(signed16(words[off+i])*ACC_SCALE_MG[acc_fs]/1000 for off in (1,17,33)) for i in range(16)))


def read_registers(serial_port, addr: int = 1) -> list[int]:
    if not 1 <= addr <= 247:
        raise ValueError('从机地址应为1–247')
    payload = bytes([addr, 3, 0x03, 0xE8, 0, WORDS])  # 0x03E8 = 1000
    crc = crc16(payload)
    serial_port.reset_input_buffer()
    serial_port.write(payload + crc.to_bytes(2, 'little'))
    # Modbus exception response is 5 bytes, so read header first (avoid blocking for 213 bytes)
    head = serial_port.read(3)
    if len(head) != 3:
        raise IMUProtocolError('无应答 / 应答头超时')
    if head[0] != addr:
        raise IMUProtocolError(f'从机地址不匹配：{head[0]}')
    if head[1] == 0x83:
        tail = serial_port.read(2)
        if len(tail) != 2 or crc16(head) != int.from_bytes(tail, 'little'):
            raise IMUProtocolError('Modbus 异常帧 CRC 错误')
        raise IMUProtocolError(f'Modbus 异常码 0x{head[2]:02X}')
    if head[1] != 3 or head[2] != 208:
        raise IMUProtocolError('应答功能码或字节数错误')
    tail = serial_port.read(210)  # data 208 + CRC 2
    if len(tail) != 210:
        raise IMUProtocolError(f'数据长度不足：{len(tail)}/210')
    response = head + tail
    if crc16(response[:-2]) != int.from_bytes(response[-2:], 'little'):
        raise IMUProtocolError('CRC16 校验失败')
    data = response[3:-2]
    return [int.from_bytes(data[i:i+2], 'big') for i in range(0, len(data), 2)]
