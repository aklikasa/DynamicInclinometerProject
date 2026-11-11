"""转台2FDT600WK通讯模块"""
import ctypes
import math
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
    # Explicitly declare output argument types for reliable ctypes calls.
    turntableDll.GetStateInfo.argtypes = [ctypes.c_int, ctypes.c_int,
                                          ctypes.POINTER(ctypes.c_byte),
                                          ctypes.POINTER(ctypes.c_byte),
                                          ctypes.POINTER(ctypes.c_float)]
    turntableDll.GetStateInfo.restype = ctypes.c_int
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


# 2FDT600WK 协议没有单独的“已找零”状态位。
# 其状态码 2 仅表示“回零执行中”；零位状态需结合运行状态和绝对角度判断。
# 手册角度反馈分辨率为 0.0001°，这里使用 0.01°作为界面零位判定容差。
ZERO_POSITION_TOLERANCE_DEG = 0.01


def twoFDT600WK_classify_zero_status(state_code, angle_deg,
                                     tolerance_deg=ZERO_POSITION_TOLERANCE_DEG):
    """
    根据 2FDT600WK 状态码和绝对角度判断当前零位状态。

    注意：该协议没有独立的“已找零”标志，因此这里判断的是“当前是否已到达
    绝对零位”，不是设备内部是否保存了某个独立的回零完成标志。
    """
    try:
        state = int(state_code)
        angle = float(angle_deg)
        tolerance = float(tolerance_deg)
    except (TypeError, ValueError):
        return False, "状态未知"

    if not (0.0 <= tolerance < 180.0):
        return False, "状态未知"
    if not math.isfinite(angle) or not (0.0 <= angle < 360.0):
        return False, "状态未知"

    if state == 2:
        return False, "回零中"

    # 只有空闲或伺服状态才允许判定“已到零位”。
    # 位置/速率/摇摆/停车等执行状态下，即使瞬时经过 0°也不能报已回零。
    if state in (0, 1):
        normalized_angle = angle % 360.0
        distance_to_zero = min(normalized_angle, 360.0 - normalized_angle)
        if distance_to_zero <= tolerance:
            return True, "已到零位"
        return False, "未到零位"

    if state in (3, 4, 5, 6, 7, 8, 9):
        return False, "运动中"

    return False, "状态未知"


def twoFDT600WK_getAxisZeroStatus(axis, is_at_zero, zero_status_text,
                                  comm_error_code,
                                  tolerance_deg=ZERO_POSITION_TOLERANCE_DEG):
    """
    获取 2FDT600WK 当前零位状态。

    成功读取状态信息时返回 True；is_at_zero 表示当前是否处于绝对零位容差内。
    zero_status_text 为“回零中 / 已到零位 / 未到零位 / 运动中 / 状态未知”。
    """
    alarm_code = [0]
    state_code = [0]
    angle = [0.0]
    ret = twoFDT600WK_getAxisStateInfo(
        axis, alarm_code, state_code, angle, comm_error_code
    )
    if not ret:
        is_at_zero[0] = False
        zero_status_text[0] = "状态未知"
        return False

    at_zero, status_text = twoFDT600WK_classify_zero_status(
        state_code[0], angle[0], tolerance_deg
    )
    is_at_zero[0] = at_zero
    zero_status_text[0] = status_text
    return True


def twoFDT600WK_getAxisFindZero(axis, is_find_zero, comm_error_code):
    """
    兼容旧调用接口：对 2FDT600WK 返回“当前是否已到绝对零位”。

    注意：这不是厂家独立的 homed 标志；厂家协议只提供运行状态码和绝对角度。
    """
    zero_status_text = ["状态未知"]
    return twoFDT600WK_getAxisZeroStatus(
        axis, is_find_zero, zero_status_text, comm_error_code
    )


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
