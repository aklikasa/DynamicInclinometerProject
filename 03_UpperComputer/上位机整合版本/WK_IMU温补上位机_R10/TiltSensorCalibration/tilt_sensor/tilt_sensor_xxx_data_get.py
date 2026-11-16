"""获取倾角仪数据"""

import threading
import time
import os
from qt_dialogs import filedialog, messagebox
from collections import *

from tilt_sensor_comm import *
from tilt_sensor_def import *


# 倾角仪原始数据
class TiltSensorRawData:
    """测斜仪原始数据（旧版占位类，当前主程序未使用）"""
    def __init__(self):
        pass


# 倾角仪通讯
class TiltSensorComm:
    """倾角仪通讯"""
    def __init__(self):
        self.comm_port = 3
        self.mb_error_code_arr = []  # 上位机与每一个阵列的MTP通讯错误码
        self.thread_instance = None
        self.thread_lock = threading.Lock()
        self.terminate_thread_requst = False
        self.comm_rate = 0.0 # 通讯速率


tiltSensorRawData = TiltSensorRawData()
tiltSensorComm = TiltSensorComm()


def thread_of_tilt_sensor_data_get_create_and_start():
    """
    创建并启动倾角仪数据获取线程

    Args:

    Returns:

    Raises:

    Note:

    """
    t = threading.Thread(target=thread_func_of_tilt_sensor_data_get)
    tiltSensorComm.thread_instance = t
    t.start()


def thread_func_of_tilt_sensor_data_get():
    """
    倾角仪数据获取线程

    Args:

    Returns:

    Raises:

    Note:

    """

