"""转台2TD-600通讯模块"""
import ctypes
from ctypes import *

# 内轴编号
INNER_ROTATION_AXIS = 0
# 外轴编号
OUTER_ROTATION_AXIS = 2

turntableDll = CDLL("./2TD600.dll")


def twoTD600_openPort(port, baudrate):
    """
    打开转台通讯口

    Args:
        port (int): COM号
        Baudrate (int):波特率，默认115200

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
    ret_dll = turntableDll.OpenPort(port, baudrate)
    if ret_dll == 1:
        ret = True
    elif ret_dll == 0:
        ret = False

    return ret


def twoTD600_closePort():
    """
    关闭转台通讯口

    Args:

    Returns:

    Raises:

    Note:

    """
    turntableDll.ClosePort()


def twoTD600_getRunMode(Axis):
    """
    获取单个轴的当前运动模式

    Args:
        Axis (int)：轴号；0表示内轴，1表示中轴，2表示外轴。

    Returns:
        str: 运行模式的字符描述

    Raises:

    Note:

    """
    turntableDll.GetRunMode.argtypes = [ctypes.c_int]
    turntableDll.GetRunMode.restype = ctypes.c_int
    ret_dll = turntableDll.GetRunMode(Axis)
    match ret_dll:
        # 依据《2TD-600 双轴转台使用维护说明书》附录 A.2 状态表：
        # 0 空闲；2 静止；3 位置；4 速率；5 摇摆；6 找零；8 相对位置；20 停止。
        case 0:
            inner_run_mode_text = "空闲"
        case 2:
            inner_run_mode_text = "静止"
        case 3:
            inner_run_mode_text = "绝对位置运动"
        case 4:
            inner_run_mode_text = "速率运动"
        case 5:
            inner_run_mode_text = "摇摆运动"
        case 6:
            inner_run_mode_text = "找零运动"
        case 8:
            inner_run_mode_text = "相对位置运动"
        case 20:
            inner_run_mode_text = "停止"
        case _:
            inner_run_mode_text = ""

    return inner_run_mode_text


def twoTD600_getAxisEnable(Axis):
    """
    获取单个轴的使能情况

    Args:
        Axis (int)：轴号；0表示内轴，1表示中轴，2表示外轴。
    Returns:
        bool: 轴的使能情况。False	表示未使能；True	表示已使能。
    Raises:

    Note:

    """
    turntableDll.GetAxisEnable.argtypes = [ctypes.c_int]
    turntableDll.GetAxisEnable.restype = ctypes.c_int
    ret_dll = turntableDll.GetAxisEnable(Axis)
    if ret_dll == 1:
        ret = True
    elif ret_dll == 0:
        ret = False

    return ret


def twoTD600_getAxisFindZero(Axis):
    """
    获取单个轴的找零情况

    Args:
        Axis (int)：轴号；0表示内轴，1表示中轴，2表示外轴。
    Returns:
        bool: 轴的找零情况。False	表示未找零；True	表示已找零。
    Raises:

    Note:

    """
    turntableDll.GetAxisFindZero.argtypes = [ctypes.c_int]
    turntableDll.GetAxisFindZero.restype = ctypes.c_int
    ret_dll = turntableDll.GetAxisFindZero(Axis)
    if ret_dll == 1:
        ret = True
    elif ret_dll == 0:
        ret = False

    return ret


def twoTD600_getAxisMoveInPlace(Axis):
    """
    获取单个轴的到位情况

    Args:
        Axis (int)：轴号；0表示内轴，1表示中轴，2表示外轴。
    Returns:
        bool：轴的到位情况。
            如果当前是位置运动，到位表示到达目标位置。
            如果当前是速率运动，到位表示到达目标速率。
            如果当前是摇摆运动，到位表示到达目标频率和幅值。
            如果当前是找零运动，到位表示已经完成找零过程，并回到物理零位。
            False	表示未到位；
            Ture	表示已到位。
    Raises:

    Note:

    """
    turntableDll.GetAxisMoveInPlace.argtypes = [ctypes.c_int]
    turntableDll.GetAxisMoveInPlace.restype = ctypes.c_int
    ret_dll = turntableDll.GetAxisMoveInPlace(Axis)
    if ret_dll == 1:
        ret = True
    elif ret_dll == 0:
        ret = False

    return ret


def twoTD600_getAxisNormal(Axis):
    """
    获取单个轴的正常情况

    Args:
        Axis (int)：轴号；0表示内轴，1表示中轴，2表示外轴。
    Returns:
        bool：轴的正常情况。
            False	表示异常；
            True	表示正常。
    Raises:

    Note:

    """
    turntableDll.GetAxisNormal.argtypes = [ctypes.c_int]
    turntableDll.GetAxisNormal.restype = ctypes.c_int
    ret_dll = turntableDll.GetAxisNormal(Axis)
    if ret_dll == 1:
        ret = True
    elif ret_dll == 0:
        ret = False

    return ret


def twoTD600_getAxisLock(Axis):
    """
    获取单个轴的锁紧情况

    Args:
        Axis (int)：轴号；0表示内轴，1表示中轴，2表示外轴。
    Returns:
        bool：轴的锁紧情况。
            False	表示未锁紧；
            True	表示已锁紧。
    Raises:

    Note:

    """
    turntableDll.GetAxisLock.argtypes = [ctypes.c_int]
    turntableDll.GetAxisLock.restype = ctypes.c_int
    ret_dll = turntableDll.GetAxisLock(Axis)
    if ret_dll == 1:
        ret = True
    elif ret_dll == 0:
        ret = False

    return ret


def twoTD600_getAxisUpLimit(Axis):
    """
    获取单个轴的触碰上限位情况

    Args:
        Axis (int)：轴号；0表示内轴，1表示中轴，2表示外轴。
    Returns:
        bool：轴的触碰上限位情况。
            True	表示触碰了上限位；
            False	表示未触碰上限位。
    Raises:

    Note:

    """
    turntableDll.GetAxisUpLimit.argtypes = [ctypes.c_int]
    turntableDll.GetAxisUpLimit.restype = ctypes.c_int
    ret_dll = turntableDll.GetAxisUpLimit(Axis)
    if ret_dll == 1:
        ret = True
    elif ret_dll == 0:
        ret = False

    return ret


def twoTD600_getAxisDownLimit(Axis):
    """
    获取单个轴的触碰下限位情况

    Args:
        Axis (int)：轴号；0表示内轴，1表示中轴，2表示外轴。
    Returns:
        bool：轴的触碰下限位情况。
            True	表示触碰下限位；
            False	表示未触碰下限位。
    Raises:

    Note:

    """
    turntableDll.GetAxisDownLimit.argtypes = [ctypes.c_int]
    turntableDll.GetAxisDownLimit.restype = ctypes.c_int
    ret_dll = turntableDll.GetAxisDownLimit(Axis)
    if ret_dll == 1:
        ret = True
    elif ret_dll == 0:
        ret = False

    return ret


def twoTD600_getAxisOverSpeed(Axis):
    """
    获取单个轴的超速情况

    Args:
        Axis (int)：轴号；0表示内轴，1表示中轴，2表示外轴。
    Returns:
        bool:轴的超速情况。
            True	表示超速；
            False	表示未超速。
    Raises:

    Note:

    """
    turntableDll.GetAxisOverSpeed.argtypes = [ctypes.c_int]
    turntableDll.GetAxisOverSpeed.restype = ctypes.c_int
    ret_dll = turntableDll.GetAxisOverSpeed(Axis)
    if ret_dll == 1:
        ret = True
    elif ret_dll == 0:
        ret = False

    return ret


def twoTD600_getAxisOverDiff(Axis):
    """
    获取单个轴的超差情况

    Args:
        Axis (int)：轴号；0表示内轴，1表示中轴，2表示外轴。
    Returns:
        bool:轴的超差情况。
            True	表示超差；
            False	表示未超差。
    Raises:

    Note:

    """
    turntableDll.GetAxisOverDiff.argtypes = [ctypes.c_int]
    turntableDll.GetAxisOverDiff.restype = ctypes.c_int
    ret_dll = turntableDll.GetAxisOverDiff(Axis)
    if ret_dll == 1:
        ret = True
    elif ret_dll == 0:
        ret = False

    return ret


def twoTD600_getAxisDriverFault(Axis):
    """
    获取单个轴的驱动故障情况

    Args:
        Axis (int)：轴号；0表示内轴，1表示中轴，2表示外轴。
    Returns:
        bool:轴的驱动故障情况。
            True	表示发生驱动故障。
            False	表示未发生驱动故障。
    Raises:

    Note:

    """
    turntableDll.GetAxisDriverFault.argtypes = [ctypes.c_int]
    turntableDll.GetAxisDriverFault.restype = ctypes.c_int
    ret_dll = turntableDll.GetAxisDriverFault(Axis)
    if ret_dll == 1:
        ret = True
    elif ret_dll == 0:
        ret = False

    return ret


def twoTD600_getAxisOverVoltage(Axis):
    """
    获取单个轴的电压超限情况

    Args:
        Axis (int)：轴号；0表示内轴，1表示中轴，2表示外轴。
    Returns:
        bool:轴的电压超限情况。
            True	表示发生电压超限；
            False	表示未发生电压超限。
    Raises:

    Note:

    """
    turntableDll.GetAxisOverVoltage.argtypes = [ctypes.c_int]
    turntableDll.GetAxisOverVoltage.restype = ctypes.c_int
    ret_dll = turntableDll.GetAxisOverVoltage(Axis)
    if ret_dll == 1:
        ret = True
    elif ret_dll == 0:
        ret = False

    return ret


def twoTD600_getPosition(Axis):
    """
    获取单个轴的当前角位置

    Args:
        Axis (int)：轴号；0表示内轴，1表示中轴，2表示外轴。
    Returns:
        float: 轴的当前角位置
    Raises:

    Note:

    """
    turntableDll.GetPosition.argtypes = [ctypes.c_int]
    turntableDll.GetPosition.restype = ctypes.c_double
    position = turntableDll.GetPosition(Axis)
    str_position = "%.4f" % position # 截取至小数点后第四位
    position = float(str_position)
    return position


def twoTD600_getPositionRaw(Axis):
    """读取DLL返回的原始角位置浮点值，不在通讯层提前舍入（供实验原始记录使用）。"""
    turntableDll.GetPosition.argtypes = [ctypes.c_int]
    turntableDll.GetPosition.restype = ctypes.c_double
    return float(turntableDll.GetPosition(Axis))


def twoTD600_getSpeedRaw(Axis):
    """读取DLL返回的原始角速度浮点值，不在通讯层提前舍入（供实验原始记录使用）。"""
    turntableDll.GetSpeed.argtypes = [ctypes.c_int]
    turntableDll.GetSpeed.restype = ctypes.c_double
    return float(turntableDll.GetSpeed(Axis))


def twoTD600_getSpeed(Axis):
    """
    获取单个轴的当前角速率

    Args:
        Axis (int)：轴号；0表示内轴，1表示中轴，2表示外轴。
    Returns:
        float: 轴的当前角速率
    Raises:

    Note:

    """
    turntableDll.GetSpeed.argtypes = [ctypes.c_int]
    turntableDll.GetSpeed.restype = ctypes.c_double
    speed = turntableDll.GetSpeed(Axis)
    str_speed = "%.4f" % speed # 截取至小数点后第四位
    speed = float(str_speed)
    return speed


def twoTD600_SetAxisEnable(Axis):
    """
    单个轴加载使能，给驱动器和电机供电

    Args:
        Axis (int)：轴号；0表示内轴，1表示中轴，2表示外轴。
    Returns:
            bool: False表示失败；True表示成功。
    Raises:

    Note:

    """
    turntableDll.SetAxisEnable.argtypes = [ctypes.c_int]
    turntableDll.SetAxisEnable.restype = ctypes.c_int
    ret_dll = turntableDll.SetAxisEnable(Axis)
    if ret_dll == 1:
        ret = True
    elif ret_dll == 0:
        ret = False

    return ret


def twoTD600_SetAxisDisable(Axis):
    """
    单个轴断开使能，给驱动器和电机断电

    Args:
        Axis (int)：轴号；0表示内轴，1表示中轴，2表示外轴。
    Returns:
        bool:False表示失败；True表示成功。
    Raises:

    Note:

    """
    turntableDll.SetAxisDisable.argtypes = [ctypes.c_int]
    turntableDll.SetAxisDisable.restype = ctypes.c_int
    ret_dll = turntableDll.SetAxisDisable(Axis)
    if ret_dll == 1:
        ret = True
    elif ret_dll == 0:
        ret = False

    return ret


def twoTD600_SetAllAxisEnable(Number):
    """
    全部轴加载使能，给驱动器和电机供电。

    Args:
        Number (int)：轴号；0表示内轴，1表示中轴，2表示外轴。
    Returns:
        bool: False表示失败；True表示成功。
    Raises:

    Note:

    """
    turntableDll.SetAllAxisEnable.argtypes = [ctypes.c_int]
    turntableDll.SetAllAxisEnable.restype = ctypes.c_int
    ret_dll = turntableDll.SetAllAxisEnable(Number)
    if ret_dll == 1:
        ret = True
    elif ret_dll == 0:
        ret = False

    return ret


def twoTD600_SetAllAxisDisable(Number):
    """
    全部轴断开使能，给驱动器和电机断电。

    Args:
        Number (int)：轴号；0表示内轴，1表示中轴，2表示外轴。
    Returns:
        bool: False	表示失败；True	表示成功。
    Raises:

    Note:

    """
    turntableDll.SetAllAxisDisable.argtypes = [ctypes.c_int]
    turntableDll.SetAllAxisDisable.restype = ctypes.c_int
    ret_dll = turntableDll.SetAllAxisDisable(Number)
    if ret_dll == 1:
        ret = True
    elif ret_dll == 0:
        ret = False

    return ret


def twoTD600_SetAxisAction(Axis, RunMode, Param1, Param2):
    """
    单个轴执行运动

    Args:
        Axis (int)：轴号；0表示内轴，1表示中轴，2表示外轴。
        RunMode (int)：	运动模式。
                        0	停车运动		目标值1传0；目标值2传0；
                        1	绝对位置运动	目标值1传目标绝对位置；目标值2传目标速率；
                        2	相对位置运动	目标值1传目标相对位置；目标值2传目标速率；
                        3	速率运动		目标值1传目标速率；目标值2传目标加速度；
                        4	摇摆运动		目标值1传目标幅值；目标值2传目标频率；
                        5	找零运动		目标值1传目标速率；目标值2传目标加速度；
        Param1 (double)：	目标值1。
        Param2 (double)：	目标值2。
    Returns:
        bool: False表示失败；True表示成功。
    Raises:

    Note:

    """
    turntableDll.SetAxisAction.argtypes = [
                                            ctypes.c_int,
                                            ctypes.c_int,
                                            ctypes.c_double,
                                            ctypes.c_double
                                          ]
    turntableDll.SetAxisAction.restype = ctypes.c_int
    ret_dll = turntableDll.SetAxisAction(Axis, RunMode, Param1, Param2)
    if ret_dll == 1:
        ret = True
    elif ret_dll == 0:
        ret = False

    return ret


def twoTD600_SetUniteAxisAction(Axis, RunMode, Param1, Param2, Init, RunImmediately):
    """
    多个轴联合执行运动

    Args:
        Axis (int)：轴号；0表示内轴，1表示中轴，2表示外轴。
        RunMode (int)：	运动模式。
                        0	停车运动		目标值1传0；目标值2传0；
                        1	绝对位置运动	目标值1传目标绝对位置；目标值2传目标速率；
                        2	相对位置运动	目标值1传目标相对位置；目标值2传目标速率；
                        3	速率运动		目标值1传目标速率；目标值2传目标加速度；
                        4	摇摆运动		目标值1传目标幅值；目标值2传目标频率；
                        5	找零运动		目标值1传目标速率；目标值2传目标加速度；
        Param1 (double)：	目标值1。
        Param2 (double)：	目标值2。
        Init (bool)：	    是否初始化(联合运动中的第一个轴为true)。
        RunImmediately (bool)：是否执行运动(联合运动中的最后一个轴为true)。
    Returns:
        bool: False表示失败；True表示成功。
    Raises:

    Note:

    """
    turntableDll.SetUniteAxisAction.argtypes = [
                                                ctypes.c_int,
                                                ctypes.c_int,
                                                ctypes.c_double,
                                                ctypes.c_double,
                                                ctypes.c_bool,
                                                ctypes.c_bool
                                               ]
    turntableDll.SetUniteAxisAction.restype = ctypes.c_int
    ret_dll = turntableDll.SetUniteAxisAction(Axis, RunMode, Param1, Param2, Init, RunImmediately)
    if ret_dll == 1:
        ret = True
    elif ret_dll == 0:
        ret = False

    return ret


def twoTD600_SetAxisFindZero(Axis, TargetSpeed, TargetAccel):
    """
    单个轴执行找零运动

    Args:
        Axis (int)：轴号；0表示内轴，1表示中轴，2表示外轴。
        TargetSpeed (double)：目标速率。
        TargetAccel (double)：目标加速度。
    Returns:
        bool: False表示失败；True表示成功。
    Raises:

    Note:

    """
    turntableDll.SetAxisFindZero.argtypes = [
                                             ctypes.c_int,
                                             ctypes.c_double,
                                             ctypes.c_double
                                            ]
    turntableDll.SetAxisFindZero.restype = ctypes.c_int
    ret_dll = turntableDll.SetAxisFindZero(Axis, TargetSpeed, TargetAccel)
    if ret_dll == 1:
        ret = True
    elif ret_dll == 0:
        ret = False

    return ret


def twoTD600_SetAxisPosition(Axis, TargetPos, TargetSpeed):
    """
    单个轴执行绝对位置运动

    Args:
        Axis (int)：轴号；0表示内轴，1表示中轴，2表示外轴。
        TargetPos (double)：目标绝对位置。
        TargetSpeed (double)：目标速率。
    Returns:
        bool: False表示失败；True表示成功。
    Raises:

    Note:

    """
    turntableDll.SetAxisPosition.argtypes = [
                                             ctypes.c_int,
                                             ctypes.c_double,
                                             ctypes.c_double
                                            ]
    turntableDll.SetAxisPosition.restype = ctypes.c_int
    ret_dll = turntableDll.SetAxisPosition(Axis, TargetPos, TargetSpeed)
    if ret_dll == 1:
        ret = True
    elif ret_dll == 0:
        ret = False

    return ret


def twoTD600_SetAxisOpposition(Axis, TargetPos, TargetSpeed):
    """
    单个轴执行相对位置运动

    Args:
        Axis (int)：轴号；0表示内轴，1表示中轴，2表示外轴。
        TargetPos (double)：目标相对位置。
        TargetSpeed (double)：目标速率。
    Returns:
        bool: False表示失败；True表示成功。
    Raises:

    Note:

    """
    turntableDll.SetAxisOpposition.argtypes = [
                                               ctypes.c_int,
                                               ctypes.c_double,
                                               ctypes.c_double
                                              ]
    turntableDll.SetAxisOpposition.restype = ctypes.c_int
    ret_dll = turntableDll.SetAxisOpposition(Axis, TargetPos, TargetSpeed)
    if ret_dll == 1:
        ret = True
    elif ret_dll == 0:
        ret = False

    return ret


def twoTD600_SetAxisVelocity(Axis, TargetSpeed, TargetAccel):
    """
    单个轴执行速率运动

    Args:
        Axis (int)：轴号；0表示内轴，1表示中轴，2表示外轴。
        TargetSpeed (double)：目标速率。
        TargetAccel (double)：目标加速度。
    Returns:
        bool: False表示失败；True表示成功。
    Raises:

    Note:

    """
    turntableDll.SetAxisVelocity.argtypes = [
                                             ctypes.c_int,
                                             ctypes.c_double,
                                             ctypes.c_double
                                            ]
    turntableDll.SetAxisVelocity.restype = ctypes.c_int
    ret_dll = turntableDll.SetAxisVelocity(Axis, TargetSpeed, TargetAccel)
    if ret_dll == 1:
        ret = True
    elif ret_dll == 0:
        ret = False

    return ret


def twoTD600_SetAxisSway(Axis, TargetAmpl, TargetFreq):
    """
    单个轴执行摇摆运动

    Args:
        Axis (int)：轴号；0表示内轴，1表示中轴，2表示外轴。
        TargetAmpl (double)：目标幅值。
        TargetFreq (double)：目标频率。
    Returns:
        bool: False表示失败；True表示成功。
    Raises:

    Note:

    """
    turntableDll.SetAxisSway.argtypes = [
                                         ctypes.c_int,
                                         ctypes.c_double,
                                         ctypes.c_double
                                        ]
    turntableDll.SetAxisSway.restype = ctypes.c_int
    ret_dll = turntableDll.SetAxisSway(Axis, TargetAmpl, TargetFreq)
    if ret_dll == 1:
        ret = True
    elif ret_dll == 0:
        ret = False

    return ret


def twoTD600_SetAxisStop(Axis):
    """
    单个轴执行停车运动

    Args:
        Axis (int)：轴号；0表示内轴，1表示中轴，2表示外轴。
    Returns:
        bool: False表示失败；True表示成功。
    Raises:

    Note:

    """
    turntableDll.SetAxisStop.argtypes = [ctypes.c_int]
    turntableDll.SetAxisStop.restype = ctypes.c_int
    ret_dll = turntableDll.SetAxisStop(Axis)
    if ret_dll == 1:
        ret = True
    elif ret_dll == 0:
        ret = False

    return ret
