"""获取转台数据"""
import threading
import time
import queue
from turntable_2TD600_comm import *
from turntable_2FDT600WK_comm import *


# 转台数据
class TurntableData:
    """转台数据"""
    def __init__(self):
        self.inner_axis_position = 0.0  # 内轴位置
        self.inner_axis_speed = 0.0  # 内轴速度
        self.outer_axis_position = 0.0  # 外轴位置
        self.outer_axis_speed = 0.0  # 外轴速度
        self.is_turntable_data_available = False  # 指示转台数据是否有效的标志
        self.update_count = 0                      # 轮询线程更新计数，供实验记录器检测漏采
        self.last_update_time_sec = 0.0             # 最近一次缓存更新的主机墙钟时间(time.time)
        self.last_update_monotonic_ns = 0           # 最近一次缓存更新的单调时钟(ns)


# 转台状态
class TurntableState:
    """转台状态"""
    def __init__(self):
        self.inner_axis_run_mode_text = "空闲" # 转台内轴运动模式
        self.inner_axis_alarm_code = 0 # 报警代码
        self.is_inner_axis_in_enable = False # 转台内轴使能情况
        self.is_inner_axis_find_zero = False # 转台内轴找零情况
        self.is_inner_axis_in_place = True  # 转台内轴到位情况
        self.is_inner_axis_normal = True # 转台内轴正常情况
        self.is_inner_axis_is_lock = False # 转台内轴锁紧情况
        self.is_inner_axis_up_limit = False # 转台内轴触碰上限情况
        self.is_inner_axis_down_limit = False  # 转台内轴触碰下限情况
        self.is_inner_axis_over_speed = False # 转台内轴超速情况
        self.is_inner_axis_over_diff = False # 转台内轴超差情况
        self.is_inner_axis_driver_fault = False # 转台内轴驱动故障情况
        self.is_inner_axis_over_voltage = False # 转台内轴电压超限情况

        self.outer_axis_run_mode_text = "空闲" # 转台外轴运动模式
        self.outer_axis_alarm_code = 0 # 报警代码
        self.is_outer_axis_in_enable = False  # 转台外轴使能情况
        self.is_outer_axis_find_zero = False  # 转台外轴找零情况
        self.is_outer_axis_in_place = True # 转台外轴到位情况
        self.is_outer_axis_normal = True  # 转台外轴正常情况
        self.is_outer_axis_is_lock = False  # 转台外轴锁紧情况
        self.is_outer_axis_up_limit = False  # 转台外轴触碰上限情况
        self.is_outer_axis_down_limit = False # 转台外轴触碰下限情况
        self.is_outer_axis_over_speed = False  # 转台外轴超速情况
        self.is_outer_axis_over_diff = False  # 转台外轴超差情况
        self.is_outer_axis_driver_fault = False  # 转台外轴驱动故障情况
        self.is_outer_axis_over_voltage = False  # 转台外轴电压超限情况

        
# 转台通讯
class TurntableComm:
    """转台通讯"""
    def __init__(self):
        self.turntable_model = ""
        self.comm_port = 1
        self.comm_error_code = None
        self.thread_instance = None
        self.thread_lock = threading.Lock()
        self.terminate_thread_requst = False


turntableData = TurntableData()
turntableState = TurntableState()
turntableComm = TurntableComm()

# 标定专用转台反馈队列。轮询线程直接入队，避免GUI定时器只看到最新缓存而漏掉中间反馈。
TURNTABLE_FEEDBACK_QUEUE_MAX = 10000
_turntable_feedback_queue = queue.Queue(maxsize=TURNTABLE_FEEDBACK_QUEUE_MAX)
_turntable_feedback_queue_enabled = False
_turntable_feedback_queue_drop_count = 0
_turntable_feedback_queue_lock = threading.Lock()


def turntable_feedback_queue_set(enabled, clear=False):
    """启用/停用转台反馈队列；clear=True时清空旧记录并重置丢帧计数。"""
    global _turntable_feedback_queue_enabled, _turntable_feedback_queue_drop_count
    with _turntable_feedback_queue_lock:
        _turntable_feedback_queue_enabled = bool(enabled)
        if clear:
            while True:
                try:
                    _turntable_feedback_queue.get_nowait()
                except queue.Empty:
                    break
            _turntable_feedback_queue_drop_count = 0


def turntable_feedback_get_nowait():
    """非阻塞读取一条转台反馈；队列为空时抛出queue.Empty。"""
    return _turntable_feedback_queue.get_nowait()


def turntable_feedback_queue_drop_count_get():
    with _turntable_feedback_queue_lock:
        return _turntable_feedback_queue_drop_count


def _turntable_feedback_queue_put():
    global _turntable_feedback_queue_drop_count
    with _turntable_feedback_queue_lock:
        if not _turntable_feedback_queue_enabled:
            return
        item = {
            "wall_time_sec": float(turntableData.last_update_time_sec),
            "wall_time_ns": int(turntableData.last_update_time_sec * 1e9),
            "monotonic_time_ns": int(turntableData.last_update_monotonic_ns),
            "update_count": int(turntableData.update_count),
            "inner_position_deg": float(turntableData.inner_axis_position),
            "inner_speed_dps": float(turntableData.inner_axis_speed),
            "outer_position_deg": float(turntableData.outer_axis_position),
            "outer_speed_dps": float(turntableData.outer_axis_speed),
            "inner_run_mode": turntableState.inner_axis_run_mode_text,
            "outer_run_mode": turntableState.outer_axis_run_mode_text,
            "inner_enable": turntableState.is_inner_axis_in_enable,
            "outer_enable": turntableState.is_outer_axis_in_enable,
            "inner_normal": turntableState.is_inner_axis_normal,
            "outer_normal": turntableState.is_outer_axis_normal,
            "inner_find_zero": turntableState.is_inner_axis_find_zero,
            "outer_find_zero": turntableState.is_outer_axis_find_zero,
            "inner_up_limit": turntableState.is_inner_axis_up_limit,
            "inner_down_limit": turntableState.is_inner_axis_down_limit,
            "outer_up_limit": turntableState.is_outer_axis_up_limit,
            "outer_down_limit": turntableState.is_outer_axis_down_limit,
            "inner_over_speed": turntableState.is_inner_axis_over_speed,
            "outer_over_speed": turntableState.is_outer_axis_over_speed,
            "inner_over_diff": turntableState.is_inner_axis_over_diff,
            "outer_over_diff": turntableState.is_outer_axis_over_diff,
            "inner_driver_fault": turntableState.is_inner_axis_driver_fault,
            "outer_driver_fault": turntableState.is_outer_axis_driver_fault,
            "inner_over_voltage": turntableState.is_inner_axis_over_voltage,
            "outer_over_voltage": turntableState.is_outer_axis_over_voltage,
        }
        try:
            _turntable_feedback_queue.put_nowait(item)
        except queue.Full:
            _turntable_feedback_queue_drop_count += 1


def thread_of_turntable_data_get_create_and_start(turntable_name):
    """
    创建并启动转台数据获取线程

    Args:
        turntable_name (str): 转台名称

    Returns:

    Raises:

    Note:

    """
    if turntable_name == "2TD600":
        thread_instance = threading.Thread(target=thread_func_of_turntable_2TD600_data_get)
    elif turntable_name == "2FDT600WK":
        thread_instance = threading.Thread(target=thread_func_of_turntable_2FDT600WK_data_get)
    turntableComm.thread_instance = thread_instance
    thread_instance.start()


def thread_func_of_turntable_2TD600_data_get():
    """
    获取转台2TD600数据的线程

    Args:

    Returns:

    Raises:

    Note:

    """
    turntableData.is_turntable_data_available = False

    while True:
        # 处理线程退出请求
        if turntableComm.terminate_thread_requst:
            turntableComm.terminate_thread_requst = False
            turntableComm.thread_instance = None
            turntableData.is_turntable_data_available = False
            break

        # 获取转台数据
        # 获取内轴位置
        turntableComm.thread_lock.acquire()
        position = twoTD600_getPositionRaw(INNER_ROTATION_AXIS)
        turntableComm.thread_lock.release()
        turntableData.inner_axis_position = position
        # 获取外轴位置
        turntableComm.thread_lock.acquire()
        position = twoTD600_getPositionRaw(OUTER_ROTATION_AXIS)
        turntableComm.thread_lock.release()
        turntableData.outer_axis_position = position
        # 获取内轴速度
        turntableComm.thread_lock.acquire()
        speed = twoTD600_getSpeedRaw(INNER_ROTATION_AXIS)
        turntableComm.thread_lock.release()
        turntableData.inner_axis_speed = speed
        # 获取外轴速度
        turntableComm.thread_lock.acquire()
        speed = twoTD600_getSpeedRaw(OUTER_ROTATION_AXIS)
        turntableComm.thread_lock.release()
        turntableData.outer_axis_speed = speed

        # 获取转台状态
        # 获取内轴运行模式
        turntableComm.thread_lock.acquire()
        run_mode_text = twoTD600_getRunMode(INNER_ROTATION_AXIS)
        turntableComm.thread_lock.release()
        turntableState.inner_axis_run_mode_text = run_mode_text
        # 获取内轴的使能情况
        turntableComm.thread_lock.acquire()
        inner_enable = twoTD600_getAxisEnable(INNER_ROTATION_AXIS)
        turntableComm.thread_lock.release()
        if not inner_enable:
            turntableState.is_inner_axis_in_enable = False
        elif inner_enable:
            turntableState.is_inner_axis_in_enable = True
        # 获取内轴的找零情况
        turntableComm.thread_lock.acquire()
        find_zero = twoTD600_getAxisFindZero(INNER_ROTATION_AXIS)
        turntableComm.thread_lock.release()
        if not find_zero:
            turntableState.is_inner_axis_find_zero = False
        elif find_zero:
            turntableState.is_inner_axis_find_zero = True
        # 获取内轴的到位情况
        turntableComm.thread_lock.acquire()
        place_in = twoTD600_getAxisMoveInPlace(INNER_ROTATION_AXIS)
        turntableComm.thread_lock.release()
        if not place_in:
            turntableState.is_inner_axis_in_place = False
        elif place_in:
            turntableState.is_inner_axis_in_place = True
        # 获取内轴的正常情况
        turntableComm.thread_lock.acquire()
        normal = twoTD600_getAxisNormal(INNER_ROTATION_AXIS)
        turntableComm.thread_lock.release()
        if not normal:
            turntableState.is_inner_axis_normal = False
        elif normal:
            turntableState.is_inner_axis_normal = True
        # 获取内轴的锁紧情况
        turntableComm.thread_lock.acquire()
        lock = twoTD600_getAxisLock(INNER_ROTATION_AXIS)
        turntableComm.thread_lock.release()
        if not lock:
            turntableState.is_inner_axis_is_lock = False
        elif lock:
            turntableState.is_inner_axis_is_lock = True
        # 获取内轴触碰上限情况
        turntableComm.thread_lock.acquire()
        up_limit = twoTD600_getAxisUpLimit(INNER_ROTATION_AXIS)
        turntableComm.thread_lock.release()
        if not up_limit:
            turntableState.is_inner_axis_up_limit = False
        elif up_limit:
            turntableState.is_inner_axis_up_limit = True
        # 获取内轴触碰下限情况
        turntableComm.thread_lock.acquire()
        down_limit = twoTD600_getAxisDownLimit(INNER_ROTATION_AXIS)
        turntableComm.thread_lock.release()
        if not down_limit:
            turntableState.is_inner_axis_down_limit = False
        elif down_limit:
            turntableState.is_inner_axis_down_limit = True
        # 获取内轴超速情况
        turntableComm.thread_lock.acquire()
        over_speed = twoTD600_getAxisOverSpeed(INNER_ROTATION_AXIS)
        turntableComm.thread_lock.release()
        if not over_speed:
            turntableState.is_inner_axis_over_speed = False
        elif over_speed:
            turntableState.is_inner_axis_over_speed = True
        # 获取内轴超差情况
        turntableComm.thread_lock.acquire()
        over_diff = twoTD600_getAxisOverDiff(INNER_ROTATION_AXIS)
        turntableComm.thread_lock.release()
        if not over_diff:
            turntableState.is_inner_axis_over_diff = False
        elif over_diff:
            turntableState.is_inner_axis_over_diff = True
        # 获取内轴驱动故障情况
        turntableComm.thread_lock.acquire()
        driver_fault = twoTD600_getAxisDriverFault(INNER_ROTATION_AXIS)
        turntableComm.thread_lock.release()
        if not driver_fault:
            turntableState.is_inner_axis_driver_fault = False
        elif driver_fault:
            turntableState.is_inner_axis_driver_fault = True
        # 获取内轴电压超限情况
        turntableComm.thread_lock.acquire()
        over_voltage = twoTD600_getAxisOverVoltage(INNER_ROTATION_AXIS)
        turntableComm.thread_lock.release()
        if not over_voltage:
            turntableState.is_inner_axis_over_voltage = False
        elif over_voltage:
            turntableState.is_inner_axis_over_voltage = True

        # 获取外轴运行模式
        turntableComm.thread_lock.acquire()
        run_mode_text = twoTD600_getRunMode(OUTER_ROTATION_AXIS)
        turntableComm.thread_lock.release()
        turntableState.outer_axis_run_mode_text = run_mode_text
        # 获取外轴的使能情况
        turntableComm.thread_lock.acquire()
        outer_enable = twoTD600_getAxisEnable(OUTER_ROTATION_AXIS)
        turntableComm.thread_lock.release()
        if not outer_enable:
            turntableState.is_outer_axis_in_enable = False
        elif outer_enable:
            turntableState.is_outer_axis_in_enable = True
        # 获取外轴的找零情况
        turntableComm.thread_lock.acquire()
        find_zero = twoTD600_getAxisFindZero(OUTER_ROTATION_AXIS)
        turntableComm.thread_lock.release()
        if not find_zero:
            turntableState.is_outer_axis_find_zero = False
        elif find_zero:
            turntableState.is_outer_axis_find_zero = True
        # 获取外轴的到位情况
        turntableComm.thread_lock.acquire()
        place_in = twoTD600_getAxisMoveInPlace(OUTER_ROTATION_AXIS)
        turntableComm.thread_lock.release()
        if not place_in:
            turntableState.is_outer_axis_in_place = False
        elif place_in:
            turntableState.is_outer_axis_in_place = True
        # 获取外轴的正常情况
        turntableComm.thread_lock.acquire()
        normal = twoTD600_getAxisNormal(OUTER_ROTATION_AXIS)
        turntableComm.thread_lock.release()
        if not normal:
            turntableState.is_outer_axis_normal = False
        elif normal:
            turntableState.is_outer_axis_normal = True
        # 获取外轴的锁紧情况
        turntableComm.thread_lock.acquire()
        lock = twoTD600_getAxisLock(OUTER_ROTATION_AXIS)
        turntableComm.thread_lock.release()
        if not lock:
            turntableState.is_outer_axis_is_lock = False
        elif lock:
            turntableState.is_outer_axis_is_lock = True
        # 获取内轴触碰上限情况
        turntableComm.thread_lock.acquire()
        up_limit = twoTD600_getAxisUpLimit(OUTER_ROTATION_AXIS)
        turntableComm.thread_lock.release()
        if not up_limit:
            turntableState.is_outer_axis_up_limit = False
        elif up_limit:
            turntableState.is_outer_axis_up_limit = True
        # 获取外轴触碰上限情况
        turntableComm.thread_lock.acquire()
        down_limit = twoTD600_getAxisDownLimit(OUTER_ROTATION_AXIS)
        turntableComm.thread_lock.release()
        if not down_limit:
            turntableState.is_outer_axis_down_limit = False
        elif down_limit:
            turntableState.is_outer_axis_down_limit = True
        # 获取外轴超速情况
        turntableComm.thread_lock.acquire()
        over_speed = twoTD600_getAxisOverSpeed(OUTER_ROTATION_AXIS)
        turntableComm.thread_lock.release()
        if not over_speed:
            turntableState.is_outer_axis_over_speed = False
        elif over_speed:
            turntableState.is_outer_axis_over_speed = True
        # 获取外轴超差情况
        turntableComm.thread_lock.acquire()
        over_diff = twoTD600_getAxisOverDiff(OUTER_ROTATION_AXIS)
        turntableComm.thread_lock.release()
        if not over_diff:
            turntableState.is_outer_axis_over_diff = False
        elif over_diff:
            turntableState.is_outer_axis_over_diff = True
        # 获取外轴驱动故障情况
        turntableComm.thread_lock.acquire()
        driver_fault = twoTD600_getAxisDriverFault(OUTER_ROTATION_AXIS)
        turntableComm.thread_lock.release()
        if not driver_fault:
            turntableState.is_outer_axis_driver_fault = False
        elif driver_fault:
            turntableState.is_outer_axis_driver_fault = True
        # 获取外轴电压超限情况
        turntableComm.thread_lock.acquire()
        over_voltage = twoTD600_getAxisOverVoltage(OUTER_ROTATION_AXIS)
        turntableComm.thread_lock.release()
        if not over_voltage:
            turntableState.is_outer_axis_over_voltage = False
        elif over_voltage:
            turntableState.is_outer_axis_over_voltage = True

        turntableData.is_turntable_data_available = True
        turntableData.update_count += 1
        turntableData.last_update_time_sec = time.time()
        turntableData.last_update_monotonic_ns = time.perf_counter_ns()
        _turntable_feedback_queue_put()

        time.sleep(0.05)


def thread_func_of_turntable_2FDT600WK_data_get():
    """
    获取转台2FDT600WK数据的线程

    Args:

    Returns:

    Raises:

    Note:

    """
    turntableData.is_turntable_data_available = False
    # 2FDT 原代码从未更新两轴速度；角度差分是实时实测参考的必要前置。
    last_feedback = None

    while True:
        # 处理线程退出请求
        if turntableComm.terminate_thread_requst:
            turntableComm.terminate_thread_requst = False
            turntableComm.thread_instance = None
            turntableData.is_turntable_data_available = False
            break

        # 获取转台数据
        # 获取内轴位置
        position = [0.0]
        comm_error_code = [0]
        turntableComm.thread_lock.acquire()
        ret = twoFDT600WK_getAxisPosition(INNER_ROTATION_AXIS, position, comm_error_code)
        turntableComm.thread_lock.release()
        inner_ok = bool(ret)
        if ret:
            turntableData.inner_axis_position = position[0]
        # 获取外轴位置
        turntableComm.thread_lock.acquire()
        ret = twoFDT600WK_getAxisPosition(OUTER_ROTATION_AXIS, position, comm_error_code)
        turntableComm.thread_lock.release()
        outer_ok = bool(ret)
        if ret:
            turntableData.outer_axis_position = position[0]
        now_feedback = time.monotonic()
        if inner_ok and outer_ok and last_feedback is not None:
            dt = now_feedback - last_feedback[0]
            if 0.04 < dt < 3.0:
                # 连续旋转时可能跨 0°/360°；差分取周期最小角。
                def delta(new, old):
                    return (new - old + 180.0) % 360.0 - 180.0
                turntableData.inner_axis_speed = delta(turntableData.inner_axis_position, last_feedback[1]) / dt
                turntableData.outer_axis_speed = delta(turntableData.outer_axis_position, last_feedback[2]) / dt
            else:
                turntableData.is_turntable_data_available = False
        else:
            turntableData.is_turntable_data_available = False
        if inner_ok and outer_ok:
            last_feedback = (now_feedback, turntableData.inner_axis_position, turntableData.outer_axis_position)
        else:
            last_feedback = None
            turntableData.is_turntable_data_available = False

        # 获取转台状态
        # 内轴运行模式
        run_mode_text = [""]
        comm_error_code = [0]
        turntableComm.thread_lock.acquire()
        ret = twoFDT600WK_getAxisRunMode(INNER_ROTATION_AXIS, run_mode_text, comm_error_code)
        turntableComm.thread_lock.release()
        if ret:
            turntableState.inner_axis_run_mode_text = run_mode_text[0]
        # 外轴运行模式
        run_mode_text = [""]
        comm_error_code = [0]
        turntableComm.thread_lock.acquire()
        ret = twoFDT600WK_getAxisRunMode(OUTER_ROTATION_AXIS, run_mode_text, comm_error_code)
        turntableComm.thread_lock.release()
        if ret:
            turntableState.outer_axis_run_mode_text = run_mode_text[0]
        # 内轴使能情况
        is_axis_enable = [False]
        comm_error_code = [0]
        turntableComm.thread_lock.acquire()
        ret = twoFDT600WK_getAxisEnable(INNER_ROTATION_AXIS, is_axis_enable, comm_error_code)
        turntableComm.thread_lock.release()
        if ret:
            turntableState.is_inner_axis_in_enable = is_axis_enable[0]
        # 外轴使能情况
        is_axis_enable = [False]
        comm_error_code = [0]
        turntableComm.thread_lock.acquire()
        ret = twoFDT600WK_getAxisEnable(OUTER_ROTATION_AXIS, is_axis_enable, comm_error_code)
        turntableComm.thread_lock.release()
        if ret:
            turntableState.is_outer_axis_in_enable = is_axis_enable[0]
        # 内轴找零情况
        is_find_zero = [False]
        comm_error_code = [0]
        turntableComm.thread_lock.acquire()
        ret = twoFDT600WK_getAxisFindZero(INNER_ROTATION_AXIS, is_find_zero, comm_error_code)
        turntableComm.thread_lock.release()
        if ret:
            turntableState.is_inner_axis_find_zero = is_find_zero[0]
        # 外轴找零情况
        is_find_zero = [False]
        comm_error_code = [0]
        turntableComm.thread_lock.acquire()
        ret = twoFDT600WK_getAxisFindZero(OUTER_ROTATION_AXIS, is_find_zero, comm_error_code)
        turntableComm.thread_lock.release()
        if ret:
            turntableState.is_outer_axis_find_zero = is_find_zero[0]
        # 内轴到位情况
        is_axis_in_place = [False]
        comm_error_code = [0]
        turntableComm.thread_lock.acquire()
        ret = twoFDT600WK_getAxisMoveInPlace(INNER_ROTATION_AXIS, is_axis_in_place, comm_error_code)
        turntableComm.thread_lock.release()
        if ret:
            turntableState.is_inner_axis_in_place = is_axis_in_place[0]
        # 外轴到位情况
        is_axis_in_place = [False]
        comm_error_code = [0]
        turntableComm.thread_lock.acquire()
        ret = twoFDT600WK_getAxisMoveInPlace(OUTER_ROTATION_AXIS, is_axis_in_place, comm_error_code)
        turntableComm.thread_lock.release()
        if ret:
            turntableState.is_outer_axis_in_place = is_axis_in_place[0]
        # 内轴是否正常情况
        is_axis_normal = [True]
        alarm_code = [0]
        comm_error_code = [0]
        turntableComm.thread_lock.acquire()
        ret = twoFDT600WK_getAxisNormal(INNER_ROTATION_AXIS, is_axis_normal, alarm_code, comm_error_code)
        turntableComm.thread_lock.release()
        if ret:
            turntableState.is_inner_axis_normal = is_axis_normal[0]
            turntableState.inner_axis_alarm_code = alarm_code[0]
        # 外轴是否正常
        is_axis_normal = [True]
        alarm_code = [0]
        comm_error_code = [0]
        turntableComm.thread_lock.acquire()
        ret = twoFDT600WK_getAxisNormal(OUTER_ROTATION_AXIS, is_axis_normal, alarm_code, comm_error_code)
        turntableComm.thread_lock.release()
        if ret:
            turntableState.is_outer_axis_normal = is_axis_normal[0]
            turntableState.outer_axis_alarm_code = alarm_code[0]
        # 内轴是否伺服环超差
        is_axis_over_diff = [False]
        comm_error_code = [0]
        turntableComm.thread_lock.acquire()
        ret = twoFDT600WK_getAxisOverDiff(INNER_ROTATION_AXIS, is_axis_over_diff, comm_error_code)
        turntableComm.thread_lock.release()
        if ret:
            turntableState.is_inner_axis_over_diff = is_axis_over_diff[0]
        # 外轴是否伺服环超差
        is_axis_over_diff = [False]
        comm_error_code = [0]
        turntableComm.thread_lock.acquire()
        ret = twoFDT600WK_getAxisOverDiff(OUTER_ROTATION_AXIS, is_axis_over_diff, comm_error_code)
        turntableComm.thread_lock.release()
        if ret:
            turntableState.is_outer_axis_over_diff = is_axis_over_diff[0]
        # 内轴是否驱动器报警
        is_axis_driver_fault = [False]
        comm_error_code = [0]
        turntableComm.thread_lock.acquire()
        ret = twoFDT600WK_getAxisDriverFault(INNER_ROTATION_AXIS, is_axis_driver_fault, comm_error_code)
        turntableComm.thread_lock.release()
        if ret:
            turntableState.is_inner_axis_driver_fault = is_axis_driver_fault[0]
        # 外轴是否驱动器报警
        is_axis_driver_fault = [False]
        comm_error_code = [0]
        turntableComm.thread_lock.acquire()
        ret = twoFDT600WK_getAxisDriverFault(OUTER_ROTATION_AXIS, is_axis_driver_fault, comm_error_code)
        turntableComm.thread_lock.release()
        if ret:
            turntableState.is_outer_axis_driver_fault = is_axis_driver_fault[0]

        turntableData.is_turntable_data_available = bool(inner_ok and outer_ok and last_feedback is not None)
        turntableData.update_count += 1
        turntableData.last_update_time_sec = time.time()
        turntableData.last_update_monotonic_ns = time.perf_counter_ns()
        _turntable_feedback_queue_put()

        time.sleep(0.05)