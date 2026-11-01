"""转台2FDT600WK通讯模块"""
import ctypes
from ctypes import *

# 内轴编号
INNER_ROTATION_AXIS = 0
# 外轴编号
OUTER_ROTATION_AXIS = 2

axisPorts = [0, 0, 0] # 轴对应的串口号


turntableDll = CDLL("./2FDT600WK.dll")


def twoFDT600WK_openAxisPort(axis, port, baudrate, comm_error_code):
    """
    打开转台轴通讯口

    Args:
        axis (int): 轴编号
        port (int): COM号
        baudrate (int):波特率，默认115200
        comm_error_code (list): 通讯错误码

    Returns:
        bool: 转台串口打开成功，返回True。转台串口打开失败，返回False。

    Raises:

    Note:

    """
    turntableDll.OpenPort.argtypes = [
                                      ctypes.c_int,
                                      ctypes.c_int
                                     ]
    turntableDll.OpenPort.restype = ctypes.c_int
    comm_error_code[0] = turntableDll.OpenPort(port, baudrate)
    if comm_error_code[0] == 0:
        axisPorts[axis] = port
        ret = True
    else:
        ret = False

    return ret


def twoFDT600WK_closeAxisPort(axis, comm_error_code):
    """
    关闭转台轴通讯口

    Args:
        axis (int): 轴编号
        comm_error_code (list): 通讯错误码

    Returns:
        bool: 转台轴串口关闭成功，返回True。转台轴串口关闭失败，返回False。

    Raises:

    Note:

    """
    turntableDll.ClosePort.argtypes = [
                                      ctypes.c_int
                                     ]
    turntableDll.ClosePort.restype = ctypes.c_int
    port = axisPorts[axis]
    comm_error_code[0] = turntableDll.ClosePort(port)
    if comm_error_code[0] == 0:
        ret = True
    else:
        ret = False

    return ret


def twoFDT600WK_setAxisTimeout(axis, timeout, comm_error_code):
    """
    设置转台轴通讯口的超时时间

    Args:
        axis (int): 轴编号
        timeout (int): 超时时间(毫秒)
        comm_error_code (list): 通讯错误码

    Returns:
        bool: 设置成功，返回True。设置失败，返回False。

    Raises:

    Note:

    """
    turntableDll.SetTimeout.argtypes = [
                                      ctypes.c_int,
                                      ctypes.c_int
                                      ]
    turntableDll.SetTimeout.restype = ctypes.c_int
    port = axisPorts[axis]
    comm_error_code[0] = turntableDll.SetTimeout(port, timeout)
    if comm_error_code[0] == 0:
        ret = True
    else:
        ret = False

    return ret


def twoFDT600WK_getAxisStateInfo(axis, alarm_code, state_code, angle, comm_error_code):
    """
    获取单个轴的状态信息

    Args:
        axis (int)：轴号；0表示内轴，1表示中轴，2表示外轴。
        alarm_code (list): 报警代码
        state_code (list): 状态代码
        angle (list): 当前绝对角度值
        comm_error_code (list): 通讯错误码

    Returns:
        bool：成功获取单个轴的状态信息，返回True。否则，返回False。

    Raises:

    Note:

    """
    port = axisPorts[axis]
    alarm_code_temp = c_byte(0)
    state_code_temp = c_byte(0)
    angle_temp = c_float(0.0)
    comm_error_code[0] = turntableDll.GetStateInfo(port, axis, byref(alarm_code_temp), byref(state_code_temp), byref(angle_temp))
    if comm_error_code[0] != 0:
        return False

    alarm_code[0] = alarm_code_temp.value
    state_code[0] = state_code_temp.value
    angle[0] = angle_temp.value

    return True


def twoFDT600WK_getAxisFindZero(axis, is_find_zero, comm_error_code):
    """
    获取单个轴的找零情况

    Args:
        axis (int)：轴号；0表示内轴，1表示中轴，2表示外轴。
        is_find_zero (list): Ture表示轴已找零；False表示轴未找零。
        comm_error_code (list): 通讯错误码

    Returns:
        bool：获取成功，返回True; 获取失败，返回False。

    Raises:

    Note:

    """
    alarm_code = [0]
    state_code = [0]
    angle = [0.0]
    ret = twoFDT600WK_getAxisStateInfo(axis, alarm_code, state_code, angle, comm_error_code)
    if not ret:
        return False

    if state_code[0] == 2:
        is_find_zero[0] = True # 回零执行中表示轴已找零
    else:
        return False

    return True


def twoFDT600WK_getAxisRunMode(axis, run_mode_text, comm_error_code):
    """
    获取单个轴的运行模式

    Args:
        axis (int)：轴号；0表示内轴，1表示中轴，2表示外轴。
        run_mode_text (list): 运行模式的字符描述
        comm_error_code (list): 通讯错误码

    Returns:
        bool：获取成功，返回True; 获取失败，返回False。

    Raises:

    Note:

    """
    alarm_code = [0]
    state_code = [0]
    angle = [0.0]
    ret = twoFDT600WK_getAxisStateInfo(axis, alarm_code, state_code, angle, comm_error_code)
    if not ret :
        return False

    match state_code[0]:
        case 0:
            run_mode_text[0] = "空闲"
        case 1:
            run_mode_text[0] = "伺服"
        case 2:
            run_mode_text[0] = "回零执行中"
        case 3:
            run_mode_text[0] = "位置执行中"
        case 4:
            run_mode_text[0] = "速率执行中"
        case 5:
            run_mode_text[0] = "速率稳定"
        case 6:
            run_mode_text[0] = "摇摆执行中"
        case 7:
            run_mode_text[0] = "摇摆稳定"
        case 8:
            run_mode_text[0] = "停车执行中"
        case 9:
            run_mode_text[0] = "多圈位置执行中"
        case _:
            run_mode_text[0] = ""

    return True


def twoFDT600WK_getAxisEnable(axis, is_axis_enable, comm_error_code):
    """
    获取单个轴的使能情况

    Args:
        axis (int)：轴号；0表示内轴，1表示中轴，2表示外轴。
        is_axis_enable (list): Ture表示轴已使能；False表示轴未使能。
        comm_error_code (list): 通讯错误码

    Returns:
        bool：获取成功，返回True; 获取失败，返回False。

    Raises:

    Note:

    """
    alarm_code = [0]
    state_code = [0]
    angle = [0.0]
    ret = twoFDT600WK_getAxisStateInfo(axis, alarm_code, state_code, angle, comm_error_code)
    if not ret:
        return False

    if state_code[0] == 0:
        is_axis_enable[0] = False # 空闲状态表示轴未使能
    else:
        is_axis_enable[0] = True  # 其他状态表示轴已使能

    return True


def twoFDT600WK_getAxisMoveInPlace(axis, is_axis_in_place, comm_error_code):
    """
    获取单个轴的到位情况

    Args:
        axis (int)：轴号；0表示内轴，1表示中轴，2表示外轴。
        is_axis_in_place (list): Ture表示已到位；False表示未到位。
        comm_error_code (list): 通讯错误码

    Returns:
        bool：获取成功，返回True; 获取失败，返回False。

    Raises:

    Note:

    """
    alarm_code = [0]
    state_code = [0]
    angle = [0.0]
    ret = twoFDT600WK_getAxisStateInfo(axis, alarm_code, state_code, angle, comm_error_code)
    if not ret :
        return False

    if state_code[0] == 1:
        is_axis_in_place[0] = True # 伺服状态表示到位
    else:
        is_axis_in_place[0] = False

    return True


def twoFDT600WK_getAxisNormal(axis, is_axis_normal, alarm_code, comm_error_code):
    """
    获取单个轴的正常情况

    Args:
        axis (int)：轴号；0表示内轴，1表示中轴，2表示外轴。
        is_axis_normal (list): Ture表示轴正常；False表示轴报警。
        alarm_code (list): 报警代码
        comm_error_code (list): 通讯错误码

    Returns:
        bool：获取成功，返回True; 获取失败，返回False。

    Raises:

    Note:

    """
    alarm_code_temp = [0]
    state_code = [0]
    angle = [0.0]
    ret = twoFDT600WK_getAxisStateInfo(axis, alarm_code_temp, state_code, angle, comm_error_code)
    if not ret :
        return False

    alarm_code[0] = alarm_code_temp[0]
    if alarm_code[0] == 0:
        is_axis_normal[0] = True  # 无报警表示轴正常
    else:
        is_axis_normal[0] = False # 报警表示轴异常

    return True


def twoFDT600WK_getAxisOverDiff(axis, is_axis_over_diff, comm_error_code):
    """
    获取单个轴是否伺服环超差

    Args:
        axis (int)：轴号；0表示内轴，1表示中轴，2表示外轴。
        is_axis_over_diff (list): Ture表示伺服环超差；False表示伺服环未超差。
        comm_error_code (list): 通讯错误码

    Returns:
        bool：获取成功，返回True; 获取失败，返回False。

    Raises:

    Note:

    """
    alarm_code = [0]
    state_code = [0]
    angle = [0.0]
    ret = twoFDT600WK_getAxisStateInfo(axis, alarm_code, state_code, angle, comm_error_code)
    if not ret :
        return False

    if alarm_code[0] == 2:
        is_axis_over_diff[0] = True
    else:
        is_axis_over_diff[0] = False

    return True


def twoFDT600WK_getAxisDriverFault(axis, is_axis_driver_fault, comm_error_code):
    """
    获取单个轴的驱动器故障情况

    Args:
        axis (int)：轴号；0表示内轴，1表示中轴，2表示外轴。
        is_axis_driver_fault (list): Ture表示驱动器故障；False表示驱动器正常。
        comm_error_code (list): 通讯错误码

    Returns:
        bool：获取成功，返回True; 获取失败，返回False。

    Raises:

    Note:

    """
    alarm_code = [0]
    state_code = [0]
    angle = [0.0]
    ret = twoFDT600WK_getAxisStateInfo(axis, alarm_code, state_code, angle, comm_error_code)
    if not ret :
        return False

    if alarm_code[0] == 1:
        is_axis_driver_fault[0] = True
    else:
        is_axis_driver_fault[0] = False

    return True


def twoFDT600WK_getAxisPosition(axis, position, comm_error_code):
    """
    获取单个轴的当前角位置

    Args:
        axis (int)：轴号；0表示内轴，1表示中轴，2表示外轴。
        position (list): 轴的当前角位置
        comm_error_code (list): 通讯错误码

    Returns:
        bool：获取成功，返回True; 获取失败，返回False。

    Raises:

    Note:

    """
    alarm_code = [0]
    state_code = [0]
    angle = [0.0]
    ret = twoFDT600WK_getAxisStateInfo(axis, alarm_code, state_code, angle, comm_error_code)
    if not ret :
         return False

    str_position = "%.4f" % angle[0] # 截取至小数点后第四位
    position[0] = float(str_position)

    return True


def twoFDT600WK_SetAxisEnable(axis, comm_error_code):
    """
    单个轴加载使能，给驱动器和电机供电

    Args:
        Axis (int)：轴号；0表示内轴，1表示中轴，2表示外轴。
        comm_error_code (list): 通讯错误码

    Returns:
        bool: False表示失败；True表示成功。

    Raises:

    Note:

    """
    turntableDll.SetAxisEnable.argtypes = [ctypes.c_int, ctypes.c_int]
    turntableDll.SetAxisEnable.restype = ctypes.c_int
    port = axisPorts[axis]
    comm_error_code[0] = turntableDll.SetAxisEnable(port, axis)
    if comm_error_code[0] == 0:
        ret = True
    else:
        ret = False

    return ret


def twoFDT600WK_SetAxisDisable(axis, comm_error_code):
    """
    单个轴断开使能，给驱动器和电机断电

    Args:
        Axis (int)：轴号；0表示内轴，1表示中轴，2表示外轴。
        comm_error_code (list): 通讯错误码

    Returns:
        bool:False表示失败；True表示成功。

    Raises:

    Note:

    """
    turntableDll.SetAxisDisable.argtypes = [ctypes.c_int, ctypes.c_int]
    turntableDll.SetAxisDisable.restype = ctypes.c_int
    port = axisPorts[axis]
    comm_error_code[0] = turntableDll.SetAxisDisable(port, axis)
    if comm_error_code[0] == 0:
        ret = True
    else:
        ret = False

    return ret


def twoFDT600WK_SetAxisFindZero(axis, comm_error_code):
    """
    单个轴执行找零运动

    Args:
        axis (int)：轴号；0表示内轴，1表示中轴，2表示外轴。
        comm_error_code (list): 通讯错误码

    Returns:
        bool: False表示失败；True表示成功。

    Raises:

    Note:

    """
    turntableDll.SetAxisFindZero.argtypes = [
                                             ctypes.c_int,
                                             ctypes.c_int
                                            ]
    turntableDll.SetAxisFindZero.restype = ctypes.c_int
    port = axisPorts[axis]
    comm_error_code[0] = turntableDll.SetAxisFindZero(port, axis)
    if comm_error_code[0] == 0:
        ret = True
    else:
        ret = False

    return ret


def twoFDT600WK_SetAxisPosition(axis, target_pos, target_speed, comm_error_code):
    """
    单个轴执行绝对位置运动

    Args:
        axis (int)：轴号；0表示内轴，1表示中轴，2表示外轴。
        target_pos (double)：目标绝对位置。
        target_speed (double)：目标速率。
        comm_error_code (list): 通讯错误码

    Returns:
        bool: False表示失败；True表示成功。

    Raises:

    Note:

    """
    turntableDll.SetAxisPosition.argtypes = [
                                             ctypes.c_int,
                                             ctypes.c_int,
                                             ctypes.c_uint8,
                                             ctypes.c_uint16,
                                             ctypes.c_float,
                                             ctypes.c_float
                                            ]
    turntableDll.SetAxisPosition.restype = ctypes.c_int
    port = axisPorts[axis]
    comm_error_code[0] = turntableDll.SetAxisPosition(port, axis, 0, 10, target_speed, target_pos)
    if comm_error_code[0] == 0:
        ret = True
    else:
        ret = False

    return ret


def twoFDT600WK_SetAxisOpposition(axis, target_pos, target_speed, comm_error_code):
    """
    单个轴执行相对位置运动

    Args:
        axis (int)：轴号；0表示内轴，1表示中轴，2表示外轴。
        target_pos (double)：目标相对位置。
        target_speed (double)：目标速率。
        comm_error_code (list): 通讯错误码

    Returns:
        bool: False表示失败；True表示成功。

    Raises:

    Note:

    """
    position_cur = [0.0]
    ret = twoFDT600WK_getAxisPosition(axis, position_cur, comm_error_code)
    if not ret:
        return False

    position = position_cur[0] + target_pos
    ret = twoFDT600WK_SetAxisPosition(axis, position, target_speed, comm_error_code)
    if not ret:
        return False

    return True


def twoFDT600WK_SetAxisVelocity(axis, target_speed, target_accel, comm_error_code):
    """
    单个轴执行速率运动

    Args:
        axis (int)：轴号；0表示内轴，1表示中轴，2表示外轴。
        target_speed (double)：目标速率。
        target_accel (int)：目标加速度。
    Returns:
        bool: False表示失败；True表示成功。
    Raises:

    Note:

    """
    turntableDll.SetAxisVelocity.argtypes = [
                                             ctypes.c_int,
                                             ctypes.c_int,
                                             ctypes.c_uint8,
                                             ctypes.c_uint16,
                                             ctypes.c_float
                                            ]
    turntableDll.SetAxisVelocity.restype = ctypes.c_int
    port = axisPorts[axis]
    comm_error_code[0] = turntableDll.SetAxisVelocity(port, axis, 0, target_accel, target_speed)
    if comm_error_code[0] == 0:
        ret = True
    else:
        ret = False

    return ret


def twoFDT600WK_SetAxisSway(axis, target_ampl, target_freq, comm_error_code):
    """
    单个轴执行摇摆运动

    Args:
        Axis (int)：轴号；0表示内轴，1表示中轴，2表示外轴。
        target_ampl (double)：目标幅值。
        target_freq (double)：目标频率。
    Returns:
        bool: False表示失败；True表示成功。
    Raises:

    Note:

    """
    turntableDll.SetAxisSway.argtypes = [
                                         ctypes.c_int,
                                         ctypes.c_int,
                                         ctypes.c_float,
                                         ctypes.c_float
                                        ]
    turntableDll.SetAxisSway.restype = ctypes.c_int
    port = axisPorts[axis]
    comm_error_code[0] = turntableDll.SetAxisSway(port, axis, target_ampl, target_freq)
    if comm_error_code[0] == 0:
        ret = True
    else:
        ret = False

    return ret


def twoFDT600WK_SetAxisStop(axis, comm_error_code):
    """
    单个轴执行停车运动

    Args:
        axis (int)：轴号；0表示内轴，1表示中轴，2表示外轴。
        comm_error_code (list): 通讯错误码

    Returns:
        bool: False表示失败；True表示成功。

    Raises:

    Note:

    """
    turntableDll.SetAxisStop.argtypes = [ctypes.c_int, ctypes.c_int]
    turntableDll.SetAxisStop.restype = ctypes.c_int
    port = axisPorts[axis]
    comm_error_code[0] = turntableDll.SetAxisStop(port, axis)
    if comm_error_code[0] == 0:
        ret = True
    else:
        ret = False

    return ret
