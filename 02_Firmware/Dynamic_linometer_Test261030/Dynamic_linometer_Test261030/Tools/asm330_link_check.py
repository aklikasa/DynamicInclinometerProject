# -*- coding: utf-8 -*-
"""
asm330_link_check.py —— ASM330 Modbus 链路快速自检（纯 pyserial，不依赖上位机工程）

功能
    1. 列出本机串口
    2. 以 Modbus RTU 主机身份读 保持寄存器 1000 起 104 个（功能码 0x03，与固件/上位机一致）
    3. 打印首帧收发 hex、解析后的各轴值，并统计：
       成功率、帧间隔(ms)、每帧 16 个样本的唯一值个数、全 0 帧数
    4. 结论提示：链路是否正常、数据是否真的在更新（全 0 = 固件没往寄存器区写数据）

用法（在工程根目录下执行）
    python Tools\asm330_link_check.py                        # 列串口 + 默认读 20 帧
    python Tools\asm330_link_check.py -p COM5                # 指定串口
    python Tools\asm330_link_check.py -p COM5 -n 100 -i 0.02 # 读100帧、20ms节拍
    python Tools\asm330_link_check.py -p COM5 --raw          # 额外打印每帧前4个原始值
    python Tools\asm330_link_check.py --list-ports           # 只列串口

寄存器映射（与固件 ASM330_DATA / 上位机 tilt_sensor_asm330_def.py 一致）
    0=未读批次数, 1..16=AccX, 17..32=AccY, 33..48=AccZ,
    49..64=GyrX, 65..80=GyrY, 81..96=GyrZ, 97=温度, 98/99=时间低/高16位,
    100=加速度量程, 101=陀螺仪量程, 102=ODR, 103=FIFO状态
"""
import argparse
import time

import serial
import serial.tools.list_ports

DEFAULT_BAUDRATE = 1500000
DEFAULT_SLAVE = 1
REG_BASE = 1000
REG_NUM = 104
SAMPLE_NUM = 16
OFF_UNREAD = 0
OFF_ACC_X, OFF_ACC_Y, OFF_ACC_Z = 1, 17, 33
OFF_GYR_X, OFF_GYR_Y, OFF_GYR_Z = 49, 65, 81
OFF_TEMP, OFF_TIME_LOW, OFF_TIME_HIGH = 97, 98, 99
OFF_ACC_LEVEL, OFF_GYRO_LEVEL, OFF_DATA_ODR, OFF_FIFO_STATE = 100, 101, 102, 103
ACC_LSB_MG_TABLE = {2: 0.061, 4: 0.122, 8: 0.244, 16: 0.488}
GYRO_LSB_MDPS_TABLE = {125: 4.37, 250: 8.75, 500: 17.5, 1000: 35.0, 2000: 70.0, 4000: 140.0}


def crc16(data_arr):
    """标准Modbus CRC16（线上低字节先发）"""
    crc = 0xFFFF
    for value in bytes(data_arr):
        crc ^= value
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if (crc & 0x0001) else (crc >> 1)
    return crc & 0xFFFF


def to_int16(value):
    """16位无符号 -> int16"""
    return value - 65536 if value >= 32768 else value


def build_request(slave_addr, base, num):
    """构造读保持寄存器请求帧"""
    body = [slave_addr, 0x03, (base >> 8) & 0xFF, base & 0xFF, (num >> 8) & 0xFF, num & 0xFF]
    crc = crc16(body)
    return bytes(body + [crc & 0xFF, (crc >> 8) & 0xFF])


def parse_registers(response):
    """把应答帧解析成104个寄存器值；失败返回(None, 原因)"""
    expect_len = 5 + REG_NUM * 2
    if len(response) == 0:
        return None, "无应答(超时)"
    if len(response) != expect_len:
        return None, "应答长度不符: %d(期望%d)" % (len(response), expect_len)
    if response[1] & 0x80:
        return None, "从机异常帧 异常码=0x%02X" % response[2]
    if response[1] != 0x03:
        return None, "功能码不符: 0x%02X" % response[1]
    if response[2] != REG_NUM * 2:
        return None, "字节数不符: %d(期望%d)" % (response[2], REG_NUM * 2)
    if ((response[-1] << 8) | response[-2]) != crc16(response[:-2]):
        return None, "CRC错误"
    registers = []
    for i in range(REG_NUM):
        registers.append((response[3 + i * 2] << 8) | response[4 + i * 2])
    return registers, ""


def main():
    parser = argparse.ArgumentParser(description="ASM330 Modbus 链路快速自检")
    parser.add_argument("-p", "--port", default=None, help="串口名，如 COM5（不填=自动选第一个串口）")
    parser.add_argument("-b", "--baudrate", type=int, default=DEFAULT_BAUDRATE, help="波特率，默认1500000")
    parser.add_argument("-s", "--slave", type=lambda v: int(v, 0), default=DEFAULT_SLAVE, help="从机地址，默认1")
    parser.add_argument("-n", "--frames", type=int, default=20, help="读取帧数，默认20")
    parser.add_argument("-i", "--interval", type=float, default=0.02, help="帧间隔(秒)，默认0.02(20ms)")
    parser.add_argument("--timeout", type=float, default=0.3, help="应答超时(秒)，默认0.3")
    parser.add_argument("--raw", action="store_true", help="额外打印每帧前4个原始值")
    parser.add_argument("--list-ports", action="store_true", help="只列出串口后退出")
    args = parser.parse_args()

    ports = list(serial.tools.list_ports.comports())
    print("========== 串口列表（%d个） ==========" % len(ports))
    for port_info in ports:
        print("    %-8s %s" % (port_info.device, port_info.description))
    if args.list_ports:
        return
    port_name = args.port
    if (port_name is None) and ports:
        port_name = ports[0].device
    if port_name is None:
        print("没有可用串口！")
        return

    print("========== 打开 %s @ %d 8N1 从机=%d 寄存器=%d起%d个 ==========" %
          (port_name, args.baudrate, args.slave, REG_BASE, REG_NUM))
    try:
        serial_instance = serial.Serial(port=port_name, baudrate=args.baudrate, bytesize=8,
                                        parity=serial.PARITY_NONE, stopbits=1, timeout=args.timeout)
    except Exception as exc:
        print("    打开失败：%s" % exc)
        return

    request = build_request(args.slave, REG_BASE, REG_NUM)
    print("    请求帧 = " + ' '.join('%02X' % value for value in request))
    success_count = 0
    zero_frame_count = 0
    interval_arr = []
    unique_arr = []
    first_ok_printed = False
    last_time_sec = 0.0
    for frame_index in range(1, args.frames + 1):
        try:
            serial_instance.reset_input_buffer()
            serial_instance.write(request)
            serial_instance.flush()
            response = serial_instance.read(5 + REG_NUM * 2)
        except Exception as exc:
            print("    第%d帧 读串口异常：%s" % (frame_index, exc))
            continue
        now_sec = time.perf_counter()
        if last_time_sec > 0:
            interval_arr.append((now_sec - last_time_sec) * 1000.0)
        last_time_sec = now_sec
        registers, reason = parse_registers(response)
        if registers is None:
            print("    第%d帧 失败：%s    RX = %s" %
                  (frame_index, reason, ' '.join('%02X' % value for value in response[:24]) or '(空)'))
            time.sleep(args.interval)
            continue
        success_count += 1
        acc_x_arr = [to_int16(registers[OFF_ACC_X + i]) for i in range(SAMPLE_NUM)]
        unique_count = len(set(acc_x_arr))
        unique_arr.append(unique_count)
        data_values = registers[OFF_UNREAD:OFF_FIFO_STATE + 1]
        if all(value == 0 for value in data_values):
            zero_frame_count += 1
        tick_ms = (registers[OFF_TIME_HIGH] << 16) | registers[OFF_TIME_LOW]
        if not first_ok_printed:
            first_ok_printed = True
            acc_level = registers[OFF_ACC_LEVEL]
            gyro_level = registers[OFF_GYRO_LEVEL]
            print("    RX = " + ' '.join('%02X' % value for value in response[:24]) + ' ... (共%d字节)' % len(response))
            print("    tick=%dms  未读批次=%d  量程=%sg/%sdps  ODR=%sHz  FIFO=0x%04X  温度raw=%d" %
                  (tick_ms, registers[OFF_UNREAD], acc_level, gyro_level,
                   registers[OFF_DATA_ODR], registers[OFF_FIFO_STATE], to_int16(registers[OFF_TEMP])))
            acc_lsb = ACC_LSB_MG_TABLE.get(acc_level, ACC_LSB_MG_TABLE[2]) / 1000.0
            gyro_lsb = GYRO_LSB_MDPS_TABLE.get(gyro_level, GYRO_LSB_MDPS_TABLE[2000]) / 1000.0
            print("    换算 acc_x前4 = %s g     gyr_x前4 = %s dps" %
                  (['%.6f' % (acc_x_arr[i] * acc_lsb) for i in range(4)],
                   ['%.3f' % (to_int16(registers[OFF_GYR_X + i]) * gyro_lsb) for i in range(4)]))
        if args.raw:
            print("    第%-3d帧 tick=%-8d acc_x=%s acc_y=%s" %
                  (frame_index, tick_ms,
                   [to_int16(registers[OFF_ACC_X + i]) for i in range(4)],
                   [to_int16(registers[OFF_ACC_Y + i]) for i in range(4)]))
        time.sleep(args.interval)
    serial_instance.close()

    print("========== 统计 ==========")
    print("    成功率 = %d/%d%s" % (success_count, args.frames,
                                   "" if success_count == 0 else " (%.0f%%)" % (success_count * 100.0 / args.frames)))
    if interval_arr:
        print("    帧间隔 = 最小%.2fms 平均%.2fms 最大%.2fms" %
              (min(interval_arr), sum(interval_arr) / len(interval_arr), max(interval_arr)))
    if unique_arr:
        print("    每帧acc_x唯一值 = 平均%.2f/%d" % (sum(unique_arr) / len(unique_arr), SAMPLE_NUM))
    print("    全0数据帧 = %d/%d" % (zero_frame_count, success_count))
    print("========== 结论 ==========")
    if success_count == 0:
        print("    通讯失败：检查 串口/波特率(1500000)/接线(TX-RX交叉、共地)/从机地址/TX使能")
    elif zero_frame_count == success_count:
        print("    通讯正常但数据全为0 -> 固件没把ASM330数据写进寄存器区：")
        print("        检查 App_Asm330DataRefreshTxDone() 里 s_DirFillCnt 是否达到16，")
        print("        以及直接模式采样函数 App_Asm330DirectSample() 是否被周期调用")
        print("        （Core/Src/main.c 主循环里那行若被注释，永远凑不满16个样本 -> 每次应答都全0）")
    else:
        print("    链路与数据均正常（有效数据帧 %d/%d）" % (success_count - zero_frame_count, success_count))


if __name__ == '__main__':
    main()

