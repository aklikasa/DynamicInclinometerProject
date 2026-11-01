"""测斜仪通讯模块"""
import ctypes
from ctypes import *
import time


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

    """


def mb_serial_close(port):
    """
    关闭Modbus串行通讯

    Args:
        port (int): COM号

    Returns:
        bool: Modbus串行通讯关闭成功，返回True。Modbus串行通讯关闭失败，返回False。

    Raises:

    Note:

    """


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


def tilt_sensor_data_get(port, comm_addr):
    """
    获取XXX倾角仪的数据

    Args:
        port (int): COM号
        comm_addr (int): 阵列通讯地址

    Returns:
        bool：倾角仪数据获取成功，返回True。否则，返回False。

    Raises:

    Note:

    """


def func_test():
    """
    测试各通讯函数

    Args:

    Returns:

    Raises:

    Note:

    """


def main():
    func_test()


if __name__ == '__main__':
    main()
