"""测斜仪(ASM330 IMU)通讯模块"""
import os
import time
import serial
import serial.tools.list_ports

import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))                             # 本模块目录
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'debug'))  # 调试配置目录
from debug import *
from tilt_sensor_asm330_def import *


serial_instance = None                                  # Modbus串口实例
serial_port = ""                                        # 当前已打开的串口名
response_timeout_ms = INC_RESPONSE_TIMEOUT_MS_DEFAULT    # 应答超时时间(ms)
mb_raw_data = {}                                        # 最近一次读取到的原始数据（缓存）
mb_error_code = MB_ERROR_CODE_FREE                      # 最近一次通讯错误码(细化分档)
mb_exception_code = 0                                   # 从机异常帧的异常码
mb_last_tx_hex = ""                                     # 最近一次发送帧(hex,便于排障)
mb_last_rx_hex = ""                                     # 最近一次接收帧(hex,便于排障)


def _inc_comm_port_name_get(port):
    """
    把COM号统一成串口名字符串

    Args:
        port (int/str): COM号，如5、"COM5"

    Returns:
        str: 串口名，如"COM5"

    Raises:

    Note:

    """
    port_str = str(port).strip()
    if (not port_str.upper().startswith("COM")) and port_str.isdigit():
        port_str = "COM" + port_str
    return port_str.upper()


def _mb_crc16(data_arr):
    """
    计算标准Modbus CRC16（初值0xFFFF，反射多项式0xA001）

    Args:
        data_arr (list/bytes): 参与校验的数据

    Returns:
        int: 16位CRC值（线上按低字节先发、高字节后发）

    Raises:

    Note:
        已与MCU固件的crc16算法比对：'01 03 00 00 00 0A' -> 线上'C5 CD'

    """
    crc = 0xFFFF
    for data in bytes(data_arr):
        crc ^= data
        for i in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc = crc >> 1
    return crc & 0xFFFF



# 设备 UID 仅用于生产设备身份显示，不参与传感器寄存器和常规轮询统计。
DEVICE_UID_REG_ADDR = 0x0BB8  # 保持寄存器3000
DEVICE_UID_REG_COUNT = 6     # 6 * 2 = 12字节（96位 MCU UID）


def device_uid_to_sn(uid_data):
    """把12字节 MCU UID 稳定映射为 DTS+6位十进制编号；非有效 UID 返回空串。"""
    import hashlib

    if not isinstance(uid_data, (bytes, bytearray)) or len(uid_data) != 12:
        return ""
    if uid_data == b"\x00" * 12 or uid_data == b"\xff" * 12:
        return ""
    digest = hashlib.sha256(bytes(uid_data)).digest()
    number = int.from_bytes(digest[:8], "big") % 1000000
    return "DTS%06d" % number


def mb_device_uid_read(comm_addr):
    """静默读取MCU UID，成功返回12字节；旧固件、CRC异常、超时均返回None。

    必须由原采集线程、在 tiltSensorComm.thread_lock 保护下调用。
    此函数不修改实时采集的错误码/最后TX-RX/统计，避免干扰既有功能。
    """
    if OFFLINE_DEBUG or serial_instance is None or not serial_instance.is_open:
        return None

    request = bytes([comm_addr, MB_FUNC_READ_HOLDING_REGISTERS,
                     (DEVICE_UID_REG_ADDR >> 8) & 0xFF, DEVICE_UID_REG_ADDR & 0xFF,
                     0x00, DEVICE_UID_REG_COUNT])
    crc = _mb_crc16(request)
    request += bytes([crc & 0xFF, (crc >> 8) & 0xFF])

    previous_timeout = None
    try:
        previous_timeout = serial_instance.timeout
        # 旧固件可能只返回5字节异常帧，限制查询等待时间，避免阻塞采样太久。
        serial_instance.timeout = min(0.5, previous_timeout) if previous_timeout is not None else 0.5
        serial_instance.reset_input_buffer()
        serial_instance.write(request)
        header = serial_instance.read(3)
        if len(header) != 3 or header[0] != comm_addr:
            return None
        if header[1] == (MB_FUNC_READ_HOLDING_REGISTERS | MB_EXCEPTION_FLAG):
            # 校验完整的5字节异常帧，但不向界面报告错误。
            tail = serial_instance.read(2)
            frame = header + tail
            if len(frame) != 5 or _mb_crc16(frame[:-2]) != int.from_bytes(frame[-2:], "little"):
                return None
            return None
        if header[1] != MB_FUNC_READ_HOLDING_REGISTERS or header[2] != DEVICE_UID_REG_COUNT * 2:
            return None
        tail = serial_instance.read(DEVICE_UID_REG_COUNT * 2 + 2)
        frame = header + tail
        if len(frame) != 3 + DEVICE_UID_REG_COUNT * 2 + 2:
            return None
        if _mb_crc16(frame[:-2]) != int.from_bytes(frame[-2:], "little"):
            return None
        uid = bytes(frame[3:-2])
        return uid if device_uid_to_sn(uid) else None
    except Exception:
        return None
    finally:
        if previous_timeout is not None:
            try:
                serial_instance.timeout = previous_timeout
            except Exception:
                pass


def _win_timer_resolution_set(enable):
    '''
    请求/释放Windows定时器精度(1ms)

    Args:
        enable (bool): True=请求1ms精度；False=释放

    Returns:
        bool: 设置成功返回True；非Windows或调用失败返回False

    Raises:

    Note:
        Win10 2004+该请求为进程级，不影响其它程序；节拍已用精确配速保证，这里只是双保险。

    '''
    if os.name != 'nt':
        return False
    try:
        import ctypes
        if enable:
            return ctypes.windll.winmm.timeBeginPeriod(1) == 0
        return ctypes.windll.winmm.timeEndPeriod(1) == 0
    except:
        return False


def mb_serial_open(port, baudrate):
    """
    打开Modbus串行通讯

    Args:
        port (int): COM号
        baudrate (int): 波特率

    Returns:
        bool: Modbus串行通讯打开成功，返回True。Modbus串行通讯打开失败，返回False。

    Raises:

    Note:
        串口参数固定为8N1；若之前已打开其他串口，会先关闭旧串口。

    """
    if OFFLINE_DEBUG:
        return True

    global serial_instance
    global serial_port

    port_name = _inc_comm_port_name_get(port)
    if (serial_instance != None) and serial_instance.is_open:
        if port_name == serial_port:
            return True
        mb_serial_close(serial_port)  # 换端口，先关闭旧串口

    try:
        serial_instance = serial.Serial(port=port_name,
                                        baudrate=baudrate,
                                        bytesize=INC_SERIAL_DATA_BITS,
                                        stopbits=INC_SERIAL_STOP_BITS,
                                        parity=INC_SERIAL_PARITY,
                                        timeout=response_timeout_ms / 1000.0)
    except:
        serial_instance = None
        serial_port = ""
        return False

    serial_port = port_name
    _win_timer_resolution_set(MB_USE_WIN_TIMER_RESOLUTION)
    return True


def mb_serial_close(port):
    """
    关闭Modbus串行通讯

    Args:
        port (int): COM号

    Returns:
        bool: Modbus串行通讯关闭成功，返回True。Modbus串行通讯关闭失败，返回False。

    Raises:

    Note:
        模块内只维护一个串口实例，关闭时会把当前已打开的串口关掉。

    """
    if OFFLINE_DEBUG:
        return True

    global serial_instance
    global serial_port

    if serial_instance != None:
        try:
            serial_instance.close()
        except:
            pass
    serial_instance = None
    serial_port = ""
    _win_timer_resolution_set(False)
    return True


def mb_serial_set_response_timeout(port, ms):
    """
    设Modbus串行通讯的通讯超时时间

    Args:
        port (int): COM号
        ms (int): 通讯超时时间，单位毫秒

    Returns:
        None

    Raises:

    Note:

    """
    global response_timeout_ms
    response_timeout_ms = ms
    if serial_instance != None:
        try:
            serial_instance.timeout = ms / 1000.0
        except:
            pass

def _mb_read_holding_registers(comm_addr, reg_addr, reg_num):
    """
    读取从机保持寄存器（Modbus功能码0x03）

    Args:
        comm_addr (int): 从机地址
        reg_addr (int): 寄存器起始地址
        reg_num (int): 寄存器数量（1~126，固件限制）

    Returns:
        list: 读取成功，返回寄存器值列表（16位无符号）；读取失败，返回None。

    Raises:

    Note:
        超时、CRC错误、异常帧、长度不符等情况统一返回None，不抛异常。

    """
    global mb_error_code, mb_exception_code, mb_last_tx_hex, mb_last_rx_hex

    if OFFLINE_DEBUG:
        mb_error_code = MB_ERROR_CODE_TIMEOUT
        return None

    if serial_instance == None:
        mb_error_code = MB_ERROR_CODE_SERIAL_NOT_OPEN
        return None
    if (reg_num < 1) or (reg_num > MB_MAX_READ_REGISTERS):
        mb_error_code = MB_ERROR_CODE_FRAME
        return None

    # 请求帧：从机地址 + 功能码 + 起始地址 + 寄存器数量 + CRC16
    request = [comm_addr, MB_FUNC_READ_HOLDING_REGISTERS,
               (reg_addr >> 8) & 0xFF, reg_addr & 0xFF,
               (reg_num >> 8) & 0xFF, reg_num & 0xFF]
    crc = _mb_crc16(request)
    request.append(crc & 0xFF)
    request.append((crc >> 8) & 0xFF)
    mb_last_tx_hex = ' '.join('%02X' % value for value in request)

    # 应答帧长度：从机地址1 + 功能码1 + 字节数1 + 数据2*reg_num + CRC2
    response_len = 5 + reg_num * 2
    try:
        serial_instance.reset_input_buffer()
        serial_instance.write(bytes(request))
        response = serial_instance.read(response_len)
    except:
        mb_error_code = MB_ERROR_CODE_TIMEOUT
        return None
    mb_last_rx_hex = ' '.join('%02X' % value for value in response)

    if len(response) != response_len:
        mb_error_code = MB_ERROR_CODE_TIMEOUT      # 无应答或应答不全
        return None
    if response[0] != comm_addr:
        mb_error_code = MB_ERROR_CODE_FRAME
        return None
    if response[1] == (MB_FUNC_READ_HOLDING_REGISTERS | MB_EXCEPTION_FLAG):
        mb_exception_code = response[2]
        mb_error_code = MB_ERROR_CODE_EXCEPTION
        return None  # 从机异常帧
    if response[1] != MB_FUNC_READ_HOLDING_REGISTERS:
        mb_error_code = MB_ERROR_CODE_FRAME
        return None
    if response[2] != (reg_num * 2):
        mb_error_code = MB_ERROR_CODE_FRAME
        return None
    crc_geted = (response[response_len - 1] << 8) | response[response_len - 2]
    if crc_geted != _mb_crc16(response[:response_len - 2]):
        mb_error_code = MB_ERROR_CODE_CRC
        return None

    registers = []
    for i in range(reg_num):
        registers.append((response[3 + i * 2] << 8) | response[4 + i * 2])
    mb_error_code = MB_ERROR_CODE_FREE
    return registers


def tilt_sensor_data_get(port, comm_addr, raw_data=None, comm_error_code=None):
    """
    获取测斜仪(ASM330 IMU)的原始数据

    Args:
        port (int): COM号
        comm_addr (int): 从机通讯地址
        raw_data (dict): 输出参数，原始数据写入此字典（可为None）
        comm_error_code (list): 输出参数，通讯错误码写入此列表的第0个元素（可为None）

    Returns:
        bool：测斜仪数据获取成功，返回True。否则，返回False。

    Raises:

    Note:
        读取的寄存器为ASM330_DATA结构体（保持寄存器1000起104个），
        各轴原始值为int16（已做符号扩展），量程/温度/采样时间一并返回；
        最近一次结果同时缓存在模块变量mb_raw_data中。

    """
    if comm_error_code != None:
        comm_error_code[0] = MB_ERROR_CODE_FREE

    registers = _mb_read_holding_registers(comm_addr, MB_REG_BASE_HR, ASM330_DATA_WORDS)
    if registers == None:
        if comm_error_code != None:
            comm_error_code[0] = mb_error_code     # 细化错误码(超时/CRC/帧格式/从机异常)
        return False

    raw_data_geted = {}
    raw_data_geted["data_unread"] = registers[REG_OFF_DATA_UNREAD]
    raw_data_geted["tick_ms"] = (registers[REG_OFF_TIME_HIGH] << 16) | registers[REG_OFF_TIME_LOW]
    raw_data_geted["acc_fs"] = registers[REG_OFF_ACC_LEVEL]
    raw_data_geted["gyro_fs"] = registers[REG_OFF_GYRO_LEVEL]
    raw_data_geted["data_odr"] = registers[REG_OFF_DATA_ODR]
    raw_data_geted["fifo_state"] = registers[REG_OFF_FIFO_STATE]
    raw_data_geted["temp_raw"] = to_int16(registers[REG_OFF_TEMP])
    raw_data_geted["acc_x_raw_arr"] = [to_int16(registers[REG_OFF_ACC_X + i]) for i in range(INC_SAMPLE_NUM)]
    raw_data_geted["acc_y_raw_arr"] = [to_int16(registers[REG_OFF_ACC_Y + i]) for i in range(INC_SAMPLE_NUM)]
    raw_data_geted["acc_z_raw_arr"] = [to_int16(registers[REG_OFF_ACC_Z + i]) for i in range(INC_SAMPLE_NUM)]
    raw_data_geted["gyr_x_raw_arr"] = [to_int16(registers[REG_OFF_GYR_X + i]) for i in range(INC_SAMPLE_NUM)]
    raw_data_geted["gyr_y_raw_arr"] = [to_int16(registers[REG_OFF_GYR_Y + i]) for i in range(INC_SAMPLE_NUM)]
    raw_data_geted["gyr_z_raw_arr"] = [to_int16(registers[REG_OFF_GYR_Z + i]) for i in range(INC_SAMPLE_NUM)]

    mb_raw_data.update(raw_data_geted)
    if raw_data != None:
        raw_data.update(raw_data_geted)
    return True

def mb_last_tx_hex_get():
    '''
    取最近一次发送的请求帧(hex文本)

    Args:
        None

    Returns:
        str: 如 "01 03 03 E8 00 68 C4 54"

    Raises:

    Note:

    '''
    return mb_last_tx_hex


def mb_last_rx_hex_get():
    '''
    取最近一次收到的应答帧(hex文本)

    Args:
        None

    Returns:
        str: 应答帧hex文本(无应答时为空)

    Raises:

    Note:

    '''
    return mb_last_rx_hex


def mb_error_code_get():
    '''
    取最近一次通讯错误码(细化分档)

    Args:
        None

    Returns:
        int: MB_ERROR_CODE_* 之一

    Raises:

    Note:
        供其它模块查询(避免from ... import *取到的是导入时刻的副本)

    '''
    return mb_error_code


def mb_exception_code_get():
    '''
    取最近一次从机异常帧的异常码

    Args:
        None

    Returns:
        int: 从机异常码(0表示无)

    Raises:

    Note:

    '''
    return mb_exception_code


def func_test():
    """
    测试各通讯函数

    Args:
        None

    Returns:
        None

    Raises:

    Note:
        1、列出串口；2、打开config.xml中指定的串口；3、读取一帧IMU数据并换算为double；
        4、关闭串口。可在源码目录直接运行本文件进行自测。

    """
    # 串口列表
    print("========== 串口列表 ==========")
    for port_info in serial.tools.list_ports.comports():
        print("    " + str(port_info.device) + "    " + str(port_info.description))

    comm_port = INC_COMM_PORT_DEFAULT
    comm_addr = INC_COMM_ADDR_DEFAULT
    baudrate = INC_BAUDRATE_DEFAULT

    # 打开串口
    ret = mb_serial_open(comm_port, baudrate)
    print("========== 打开串口 ==========")
    print("    串口 = " + str(comm_port) + "    波特率 = " + str(baudrate) + "    结果 = " + str(ret))
    if not ret:
        return
    mb_serial_set_response_timeout(comm_port, INC_RESPONSE_TIMEOUT_MS_DEFAULT)

    # 读取一帧数据
    raw_data = {}
    comm_error_code = [0]
    ret = tilt_sensor_data_get(comm_port, comm_addr, raw_data, comm_error_code)
    print("========== 读取数据 ==========")
    print("    从机地址 = " + str(comm_addr) + "    结果 = " + str(ret) + "    错误码 = " + str(comm_error_code[0]))
    if ret:
        acc_fs = raw_data["acc_fs"]
        gyro_fs = raw_data["gyro_fs"]
        print("    未读批次数 = " + str(raw_data["data_unread"]) +
              "    ODR = " + str(raw_data["data_odr"]) + "Hz" +
              "    采样时间 = " + str(raw_data["tick_ms"]) + "ms")
        print("    加速度量程 = " + str(acc_fs) + "g(有效:" + str(acc_fs_is_valid(acc_fs)) + ")" +
              "    陀螺仪量程 = " + str(gyro_fs) + "dps(有效:" + str(gyro_fs_is_valid(gyro_fs)) + ")" +
              "    FIFO状态 = " + str(fifo_state_text_arr_get(raw_data["fifo_state"])))
        if not acc_fs_is_valid(acc_fs):
            acc_fs = ACC_FS_DEFAULT
        if not gyro_fs_is_valid(gyro_fs):
            gyro_fs = GYRO_FS_DEFAULT
        print("    温度 = %.3f℃" % temp_raw_to_celsius(raw_data["temp_raw"]))
        print("    序号 |        AccX(g)        AccY(g)        AccZ(g) |      GyrX(dps)      GyrY(dps)      GyrZ(dps)")
        for i in range(INC_SAMPLE_NUM):
            acc_x = accel_raw_to_g(raw_data["acc_x_raw_arr"][i], acc_fs)
            acc_y = accel_raw_to_g(raw_data["acc_y_raw_arr"][i], acc_fs)
            acc_z = accel_raw_to_g(raw_data["acc_z_raw_arr"][i], acc_fs)
            gyr_x = gyro_raw_to_dps(raw_data["gyr_x_raw_arr"][i], gyro_fs)
            gyr_y = gyro_raw_to_dps(raw_data["gyr_y_raw_arr"][i], gyro_fs)
            gyr_z = gyro_raw_to_dps(raw_data["gyr_z_raw_arr"][i], gyro_fs)
            print("    %4d | %14.6f %14.6f %14.6f | %14.6f %14.6f %14.6f" %
                  (i, acc_x, acc_y, acc_z, gyr_x, gyr_y, gyr_z))

    # 关闭串口
    ret = mb_serial_close(comm_port)
    print("========== 关闭串口 ==========")
    print("    串口 = " + str(comm_port) + "    结果 = " + str(ret))


def main():
    func_test()


if __name__ == '__main__':
    main()