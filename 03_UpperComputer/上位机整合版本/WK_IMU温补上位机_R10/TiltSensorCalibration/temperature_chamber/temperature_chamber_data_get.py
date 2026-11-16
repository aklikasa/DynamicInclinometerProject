"""获取高低温试验箱数据"""
import threading
import time
from temperature_chamber_comm import *


# 温箱数据
class TcData:
    """温箱数据"""
    def __init__(self):
        self.pv = 25.0  # 实测温度值
        self.is_fixed_value_rate_on = False # 定值速率开关状态
        self.temperature_rate = 2.0 # 温度速率
        self.sp = 25.0 # 设置的温度值
        self.is_tc_data_available = False  # 指示温箱数据是否有效的标志
        self.pv_update_monotonic = 0.0  # 新鲜度：只在真实读取PV成功时更新
        self.sp_update_monotonic = 0.0  # 新鲜度：只在真实读取SP成功时更新


# 温箱状态
class TcState:
    """温箱状态"""
    def __init__(self):
        self.is_device_running = False # 设备运行状态
        self.is_fixed_value_startup = False # 定值启动/停止状态
        self.is_fixed_value_mode = True # 定值/程序模式
        self.is_lighting_on = False # 照明ON/OFF
        self.alarm_value = 0 # 报警值
        self.is_device_fault = False # 设备故障
        self.alarm_update_monotonic = 0.0
        self.fault_update_monotonic = 0.0
        self.run_update_monotonic = 0.0
        self.fixed_start_update_monotonic = 0.0
        self.mode_update_monotonic = 0.0


# 温箱通讯
class TcComm:
    """温箱通讯"""
    def __init__(self):
        self.ip = 1
        self.is_connected = False
        self.is_comm_error = False
        self.thread_instance = None
        self.thread_lock = threading.Lock()
        self.terminate_thread_requst = False
        self.is_pv_get_failed = False # 指示PV值是否读取失败的标志位
        self.sp_to_set = 25.0 # 待设置的sp值
        self.is_sp_set_failed = False # 指示sp值是否设置失败的标志位
        self.sp_set_requst = False # sp设置请求
        self.sp_set_and_wait_quit_requst = False # 函数tc_sp_set_and_wait_multithread退出请求


tcData = TcData()
tcState = TcState()
tcComm = TcComm()


def thread_of_tc_data_get_create_and_start():
    """
    创建并启动温箱数据获取线程

    Args:

    Returns:

    Raises:

    Note:

    """
    thread_instance = threading.Thread(target=thread_func_of_tc_data_get)
    tcComm.thread_instance = thread_instance
    thread_instance.start()


def thread_of_tc_data_get_terminate():
    """
    中止温箱数据获取线程

    Args:

    Returns:

    Raises:

    Note:

    """
    # 请求终止温箱数据获取线程
    tcComm.terminate_thread_requst = True
    while True:
        if tcComm.thread_instance == None:
            break


def thread_func_of_tc_data_get():
    """
    获取温箱数据的线程

    Args:

    Returns:

    Raises:

    Note:

    """
    tcData.is_tc_data_available = False

    while True:
        # 处理线程退出请求
        if tcComm.terminate_thread_requst:
            tcComm.terminate_thread_requst = False
            tcComm.thread_instance = None
            tcData.is_tc_data_available = False
            break

        # 获取温箱连接状态
        tcComm.thread_lock.acquire()
        tcComm.is_connected = tc_connect_state_get()
        tcComm.thread_lock.release()

        # 获取温箱数据
        comm_try_count = 10  # 通讯尝试次数
        is_pv_get_failed = True
        for i in range(comm_try_count): # pv值很重要，所以需要多次获取！！！
            tcComm.thread_lock.acquire()
            data_geted = tc_pv_get()
            tcComm.thread_lock.release()
            if data_geted != None:
                tcData.pv = data_geted
                tcData.pv_update_monotonic = time.monotonic()
                is_pv_get_failed = False
                tcComm.is_comm_error = False
                break
            else:
                tcComm.is_comm_error = True
        tcComm.is_pv_get_failed = is_pv_get_failed
        if is_pv_get_failed:
            tcData.is_tc_data_available = False

        tcComm.thread_lock.acquire()
        data_geted = tc_fixed_value_rate_state_get()
        tcComm.thread_lock.release()
        if data_geted != None:
            tcData.is_fixed_value_rate_on = data_geted
            tcComm.is_comm_error = False
        else:
            tcComm.is_comm_error = True

        tcComm.thread_lock.acquire()
        data_geted = tc_sp_get()
        tcComm.thread_lock.release()
        if data_geted != None:
            tcData.sp = data_geted
            tcData.sp_update_monotonic = time.monotonic()
            tcComm.is_comm_error = False
        else:
            tcComm.is_comm_error = True

        tcComm.thread_lock.acquire()
        data_geted = tc_fixed_value_rate_get()
        tcComm.thread_lock.release()
        if data_geted != None:
            tcData.temperature_rate = data_geted
            tcComm.is_comm_error = False
        else:
            tcComm.is_comm_error = True

        # 获取温箱状态
        tcComm.thread_lock.acquire()
        data_geted = tc_run_state_get()
        tcComm.thread_lock.release()
        if data_geted != None:
            tcState.is_device_running = data_geted
            tcState.run_update_monotonic = time.monotonic()
            tcComm.is_comm_error = False
        else:
            tcComm.is_comm_error = True

        tcComm.thread_lock.acquire()
        data_geted = tc_fixed_value_state_get()
        tcComm.thread_lock.release()
        if data_geted != None:
            tcState.is_fixed_value_startup = data_geted
            tcState.fixed_start_update_monotonic = time.monotonic()
            tcComm.is_comm_error = False
        else:
            tcComm.is_comm_error = True

        tcComm.thread_lock.acquire()
        data_geted = tc_run_mode_get()
        tcComm.thread_lock.release()
        if data_geted != None:
            tcState.is_fixed_value_mode = not data_geted
            tcState.mode_update_monotonic = time.monotonic()
            tcComm.is_comm_error = False
        else:
            tcComm.is_comm_error = True

        tcComm.thread_lock.acquire()
        data_geted = tc_alarm_value_get()
        tcComm.thread_lock.release()
        if data_geted != None:
            tcState.alarm_value = data_geted
            tcState.alarm_update_monotonic = time.monotonic()
            tcComm.is_comm_error = False
        else:
            tcComm.is_comm_error = True

        tcComm.thread_lock.acquire()
        data_geted = tc_device_fault_state_get()
        tcComm.thread_lock.release()
        if data_geted != None:
            tcState.is_device_fault = data_geted
            tcState.fault_update_monotonic = time.monotonic()
            tcComm.is_comm_error = False
        else:
            tcComm.is_comm_error = True

        tcComm.thread_lock.acquire()
        data_geted = tc_lighting_state_get()
        tcComm.thread_lock.release()
        if data_geted != None:
            tcState.is_lighting_on = data_geted
            tcComm.is_comm_error = False
        else:
            tcComm.is_comm_error = True

        tcData.is_tc_data_available = not is_pv_get_failed

        # 设置sp
        if tcComm.sp_set_requst:
            comm_try_count = 10  # 通讯尝试次数
            is_sp_set_failed = True
            for i in range(comm_try_count):
                tcComm.thread_lock.acquire()
                time.sleep(3)
                ret = tc_sp_set(tcComm.sp_to_set)
                time.sleep(3)
                tcComm.thread_lock.release()
                if ret:
                    is_sp_set_failed = False
                    tcComm.is_comm_error = False
                    break
                else:
                    tcComm.is_comm_error = True
            tcComm.is_sp_set_failed = is_sp_set_failed
            tcComm.sp_set_requst = False

        time.sleep(0.5)


def tc_sp_set_and_wait_multithread(sp, deviation, pv_check_count, timeout):
    """
    设置温箱温度设定值，并等待温箱温度到达温度设定值的偏差范围内，且最多等待timeout时间。(多线程适用)

    Args:
        sp (float): 温箱温度设定值
        deviation (float): 温度偏差值
        pv_check_count (int): PV检查次数
        timeout (int): 等待超时时间，单位分钟

    Returns:
        int: 温箱温度设定值设置失败，返回-1。
             温箱温度设定值设置成功，但温箱在timeout时间内未到达温度设定值的偏差范围内，返回-2。
             终止等待，返回-3。
             温箱温度设定值设置成功，且温箱在timeout时间内到达温度设定值的偏差范围内，返回0。

    Note:

    """
    # return 0 # 离线调试用！

    time_begin_sec = time.time()

    # 设置温度值
    tcComm.sp_set_requst = True
    tcComm.sp_to_set = sp
    while True: # 等待设置sp完成
        if tcComm.sp_set_and_wait_quit_requst:
            tcComm.sp_set_and_wait_quit_requst = False
            return -3
        if not tcComm.sp_set_requst:
            break
        if (time.time() - time_begin_sec) > (timeout * 60):
            return -2
    if tcComm.is_sp_set_failed:
        return -1

    # 等待温箱温度到达温度设定值的偏差范围内
    while True:
        if tcComm.sp_set_and_wait_quit_requst:
            tcComm.sp_set_and_wait_quit_requst = False
            return -3
        # 每隔一段时间读取并检查温箱温度值
        is_pv_equal_sp = True
        for i in range(pv_check_count):
            if tcComm.sp_set_and_wait_quit_requst:
                tcComm.sp_set_and_wait_quit_requst = False
                return -3
            if tcComm.is_pv_get_failed:
                return -1
            pv = tcData.pv
            # 检查温箱温度是否到达温度设定值的偏差范围内
            if (pv < (sp - deviation)) or (pv > (sp + deviation)):
                is_pv_equal_sp = False
                break
            # 每1分钟检查一次PV值
            wait_time = 60
            time_begin = time.time()
            while True:
                if tcComm.sp_set_and_wait_quit_requst:
                    tcComm.sp_set_and_wait_quit_requst = False
                    return -3
                if (time.time() - time_begin) > wait_time:
                    break

        if is_pv_equal_sp:
            return 0
        else:
            time_end_sec = time.time()
            if (time_end_sec - time_begin_sec) > (timeout * 60):
                return -2