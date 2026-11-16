"""阿泰可CHF420TC-Y高低温试验箱通讯相关"""
import time

# 本机WMI异常保护(同main.py)：platform.system() 走WMI查询在本机会卡死，
# snap7导入时会调用它。这里置为"不支持"让platform回退到 getwindowsversion()。
import platform as _platform_guard
if hasattr(_platform_guard, '_wmi_query'):
    def _wmi_query_disabled(*args, **kwargs):
        raise OSError("not supported")
    _platform_guard._wmi_query = _wmi_query_disabled

from snap7 import client
from plc_comm import *

import sys
sys.path.append(sys.path[0] + '\\debug')
from debug import *


client_instance = None


def tc_connect(ip: str):
    """
    连接高低温试验箱

    Args:
        ip (str): 高低温试验箱的IPV4地址

    Returns:
        bool: 连接高低温试验箱成功，返回True。连接高低温试验箱失败，返回False。

    """
    if OFFLINE_DEBUG:
        return True

    global client_instance
    client_instance = plc_connect(ip)
    if client_instance is None:
        return False
    return True


def tc_disconnect():
    """
    断开连接高低温试验箱

    Args:

    Returns:
        None

    """
    if OFFLINE_DEBUG:
        return

    global client_instance
    plc_disconnect(client_instance)
    client_instance = None


def tc_connect_state_get():
    """
    获取温箱连接状态

    Args:

    Returns:
        bool: 已连接，返回True。未连接，返回False。

    """
    if OFFLINE_DEBUG:
        return True

    return plc_connect_state_get(client_instance)


def tc_fixed_value_startup():
    """
    启动高低温试验箱定值运行

    Args:

    Returns:
        bool: 启动高低温试验箱定值运行成功，返回True。启动高低温试验箱定值运行失败，返回False。

    """
    if OFFLINE_DEBUG:
        return True

    return plc_v_write(client_instance, 954, 0, True)


def tc_fixed_value_stop():
    """
    停止高低温试验箱定值运行

    Args:

    Returns:
        bool: 停止高低温试验箱定值运行成功，返回True。停止高低温试验箱定值运行失败，返回False。

    """
    if OFFLINE_DEBUG:
        return True

    return plc_v_write(client_instance, 954, 0, False)


def tc_fixed_value_state_get():
    """
    获取高低温试验箱定值运行状态

    Args:

    Returns:
        bool: 获取成功，返回True或False(True为启动，False为停止)；获取失败，返回None

    """
    if OFFLINE_DEBUG:
        return True

    return plc_v_read(client_instance, 954, 0)


def tc_set_fixed_value_mode():
    """
    设置高低温试验箱为定值模式

    Args:

    Returns:
        bool: 设置成功，返回True。设置失败，返回False。

    """
    if OFFLINE_DEBUG:
        return True

    return plc_v_write(client_instance, 2130, 2, False)


def tc_set_program_mode():
    """
    设置高低温试验箱为程序模式

    Args:

    Returns:
        bool: 设置成功，返回True。设置失败，返回False。

    """
    if OFFLINE_DEBUG:
        return True

    return plc_v_write(client_instance, 2130, 2, True)


def tc_run_mode_get():
    """
    获取运行模式

    Args:

    Returns:
        bool: 获取成功，返回True或False(True为程序模式，False为定值模式)；获取失败，返回None

    """
    if OFFLINE_DEBUG:
        return False

    return plc_v_read(client_instance, 2130, 2)


def tc_lighting_on():
    """
    打开照明

    Args:

    Returns:
        bool: 设置成功，返回True。设置失败，返回False。

    """
    if OFFLINE_DEBUG:
        return True

    return plc_m_write(client_instance, 3, 6, True)


def tc_lighting_off():
    """
    关闭照明

    Args:

    Returns:
        bool: 设置成功，返回True。设置失败，返回False。

    """
    if OFFLINE_DEBUG:
        return True

    return plc_m_write(client_instance, 3, 6, False)


def tc_lighting_state_get():
    """
    获取照明开关状态

    Args:

    Returns:
        bool: 获取成功，返回True或False(True为照明开，False为照明关)；获取失败，返回None

    """
    if OFFLINE_DEBUG:
        return False

    return plc_m_read(client_instance, 3, 6)


def tc_run_state_get():
    """
    获取设备运行状态

    Args:

    Returns:
        bool: 获取成功，返回True或False(True为运行，False为停机)；获取失败，返回None

    """
    if OFFLINE_DEBUG:
        return True

    return plc_v_read(client_instance, 504, 0)


def tc_pv_get():
    """
    获取实测温度

    Args:

    Returns:
        float: 获取实测温度成功，返回温度值。获取实测温度失败，返回None。

    """
    if OFFLINE_DEBUG:
        return 25.0

    value = plc_vw_read(client_instance, 2100)
    if value is None:
        return None
    temp = value / 10.0
    return temp


def tc_sp_set(temp_value):
    """
    设定温度目标值

    Args:
        temp_value (float): 温度值

    Returns:
        bool: 设置成功，返回True。设置失败，返回False。

    """
    if OFFLINE_DEBUG:
        return True

    value = (int)(temp_value * 10)
    return plc_vw_write(client_instance, 2110, value)


def tc_sp_get():
    """
    获取设定温度目标值

    Args:

    Returns:
        float: 获取成功，返回设定温度目标值。获取失败，返回None。

    """
    if OFFLINE_DEBUG:
        return 25.0

    value = plc_vw_read(client_instance, 2106)
    if value is None:
        return None
    temp = value / 10.0
    return temp


def tc_fixed_value_rate_on():
    """
    打开定值速率开关

    Args:

    Returns:
        bool: 设置成功，返回True。设置失败，返回False。

    """
    if OFFLINE_DEBUG:
        return True

    return plc_v_write(client_instance, 504, 1, True)


def tc_fixed_value_rate_off():
    """
    关闭定值速率开关

    Args:

    Returns:
        bool: 设置成功，返回True。设置失败，返回False。

    """
    if OFFLINE_DEBUG:
        return True

    return plc_v_write(client_instance, 504, 1, False)


def tc_fixed_value_rate_state_get():
    """
    获取定值速率开关状态

    Args:

    Returns:
        bool: 获取成功，返回True或False(True为打开，False为关闭)；获取失败，返回None

    """
    if OFFLINE_DEBUG:
        return False

    return plc_v_read(client_instance, 504, 1)


def tc_fixed_value_rate_set(rate):
    """
    设置定值温度速率

    Args:
        rate (float): 速率值
    Returns:
        bool: 设置成功，返回True。设置失败，返回False。

    """
    if OFFLINE_DEBUG:
        return True

    value = (int)(rate * 10)
    return plc_vw_write(client_instance, 2188, value)


def tc_fixed_value_rate_get():
    """
    获取定值温度速率值

    Args:

    Returns:
        float: 获取成功，返回速率值；获取失败，返回None。

    """
    if OFFLINE_DEBUG:
        return 0.0

    value = plc_vw_read(client_instance, 2188)
    if value is None:
        return None
    rate = value / 10.0
    return rate


def tc_ultra_high_temperature_set(temp_value):
    """
    设定超高温值

    Args:
        temp_value (float): 超高温值

    Returns:
        bool: 设置成功，返回True。设置失败，返回False。

    """
    if OFFLINE_DEBUG:
        return True

    value = (int)(temp_value * 10)
    return plc_vw_write(client_instance, 916, value)


def tc_ultra_low_temperature_set(temp_value):
    """
    设定超低温值

    Args:
        temp_value (float): 超低温值

    Returns:
        bool: 设置成功，返回True。设置失败，返回False。

    """
    if OFFLINE_DEBUG:
        return True

    value = (int)(temp_value * 10)
    return plc_vw_write(client_instance, 918, value)


def tc_alarm_sound_on():
    """
    开启报警音

    Args:

    Returns:
        bool: 设置成功，返回True。设置失败，返回False。

    """
    if OFFLINE_DEBUG:
        return True

    return plc_v_write(client_instance, 600, 0, False)


def tc_alarm_sound_off():
    """
    关闭报警音

    Args:

    Returns:
        bool: 设置成功，返回True。设置失败，返回False。

    """
    if OFFLINE_DEBUG:
        return True

    return plc_v_write(client_instance, 600, 0, True)


def tc_alarm_sound_state_get():
    """
    获取报警音开启状态

    Args:

    Returns:
        bool: 获取成功，返回True或False(True为关闭，False为开启)；获取失败，返回None

    """
    if OFFLINE_DEBUG:
        return False

    return plc_v_read(client_instance, 600, 0)


def tc_device_fault_state_get():
    """
    获取设备故障状态

    Args:

    Returns:
        bool: 获取成功，返回True或False(True为设备故障，False为设备正常)；获取失败，返回None

    """
    if OFFLINE_DEBUG:
        return False

    return plc_v_read(client_instance, 601, 0)


def tc_alarm_value_get():
    """
    获取报警值

    Args:

    Returns:
        int: 报警值

    """
    if OFFLINE_DEBUG:
        return 0

    alarm_value = 0
    # R404A压缩机断路器
    value = plc_m_read(client_instance, 25, 0)
    if value:
        alarm_value |= (1 << 0)
    # R23压缩机短路器
    value = plc_m_read(client_instance, 25, 1)
    if value:
        alarm_value |= (1 << 1)
    # R404A压缩机热过载
    value = plc_m_read(client_instance, 25, 2)
    if value:
        alarm_value |= (1 << 2)
    # R23压缩机热过载
    value = plc_m_read(client_instance, 25, 3)
    if value:
        alarm_value |= (1 << 3)
    # R404超压报警
    value = plc_m_read(client_instance, 25, 4)
    if value:
        alarm_value |= (1 << 4)
    # R23超压报警
    value = plc_m_read(client_instance, 25, 5)
    if value:
        alarm_value |= (1 << 5)
    # R404油压报警
    value = plc_m_read(client_instance, 26, 0)
    if value:
        alarm_value |= (1 << 6)
    # R23油压报警
    value = plc_m_read(client_instance, 26, 1)
    if value:
        alarm_value |= (1 << 7)
    # 冷凝水
    value = plc_m_read(client_instance, 26, 3)
    if value:
        alarm_value |= (1 << 8)
    # 电源故障
    value = plc_m_read(client_instance, 27, 2)
    if value:
        alarm_value |= (1 << 9)
    # 紧急停止
    value = plc_m_read(client_instance, 27, 3)
    if value:
        alarm_value |= (1 << 10)
    # 风机过载
    value = plc_m_read(client_instance, 27, 4)
    if value:
        alarm_value |= (1 << 11)
    # 风机热保护
    value = plc_m_read(client_instance, 27, 5)
    if value:
        alarm_value |= (1 << 12)
    # 超高温
    value = plc_m_read(client_instance, 27, 7)
    if value:
        alarm_value |= (1 << 13)
    # 超低温
    value = plc_m_read(client_instance, 28, 2)
    if value:
        alarm_value |= (1 << 14)
    # 水箱1缺水
    value = plc_m_read(client_instance, 28, 3)
    if value:
        alarm_value |= (1 << 15)
    # 加湿器1缺水
    value = plc_m_read(client_instance, 28, 4)
    if value:
        alarm_value |= (1 << 16)
    # 加热器温度高
    value = plc_m_read(client_instance, 28, 5)
    if value:
        alarm_value |= (1 << 17)
    # 加湿器温度高
    value = plc_m_read(client_instance, 28, 6)
    if value:
        alarm_value |= (1 << 18)
    # 控制器模块故障
    value = plc_m_read(client_instance, 29, 3)
    if value:
        alarm_value |= (1 << 19)
    # 变频器故障
    value = plc_m_read(client_instance, 29, 5)
    if value:
        alarm_value |= (1 << 20)

    return alarm_value


def tc_sp_set_and_wait(sp, deviation, timeout, terminate_wait_request):
    """
    设置温箱温度设定值，并等待温箱温度到达温度设定值的偏差范围内，且最多等待timeout时间。(单线程适用)

    Args:
        sp (float): 温箱温度设定值
        deviation (float): 温度偏差值
        timeout (int): 等待超时时间，单位分钟
        terminate_wait_request (bool): 终止等待请求

    Returns:
        int: 温箱温度设定值设置失败，返回-1。
             温箱温度设定值设置成功，但温箱在timeout时间内未到达温度设定值的偏差范围内，返回-2。
             终止等待，返回-3。
             温箱温度设定值设置成功，且温箱在timeout时间内到达温度设定值的偏差范围内，返回0。

    Note:
        thread_of_tc_data_get线程运行时，其它线程调用此函数会引起b'CLI : Job pending'异常（原因估计是snap7内部数据堵塞导致！），导致这里的PLC通讯经常失败！
        所以，只适合单线程调用！！！

    """
    #return 0 # 离线调试用！

    try_count = 16 # 通讯尝试次数
    pv_check_count = 10 # PV值检查次数

    # 尝试多次设置温度值
    is_tc_comm_fail = True
    for i in range(try_count):
        if terminate_wait_request:
            return -3
        #tcComm.thread_lock.acquire()
        #time.sleep(1) # 让thread_func_of_tc_data_get里的PLC通讯数据传送完毕，否则会引起b'CLI : Job pending'异常，导致这里的通讯经常失败！
        ret = tc_sp_set(sp)
        #time.sleep(1)
        #tcComm.thread_lock.release()
        if ret:
            is_tc_comm_fail = False
            break
    if is_tc_comm_fail:
        return -1

    # 等待温箱温度到达温度设定值的偏差范围内
    time_begin_sec = time.time()
    while True:
        # 每隔一段时间读取并多次检查温箱温度值
        is_pv_equal_sp = True
        for i in range(pv_check_count):
            pv = 0
            if terminate_wait_request:
                return -3
            # 尝试多次获取温度值
            is_tc_comm_fail = True
            for i in range(try_count):
                if terminate_wait_request:
                    return -3
                #tcComm.thread_lock.acquire()
                #time.sleep(1)
                pv = tc_pv_get()
                #time.sleep(1)
                #tcComm.thread_lock.release()
                if pv != None:
                    is_tc_comm_fail = False
                    break
            if is_tc_comm_fail:
                return -1
            # 检查温箱温度是否到达温度设定值的偏差范围内
            if (pv < (sp - deviation)) or (pv > (sp + deviation)):
                is_pv_equal_sp = False
            time.sleep(60) # 每1分钟检查一次PV值

        if is_pv_equal_sp:
            return 0
        else:
            time_end_sec = time.time()
            if (time_end_sec - time_begin_sec) > (timeout * 60):
                return -2


