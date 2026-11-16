"""获取测斜仪(ASM330 IMU)数据"""
import os
import time
import threading
import queue
import xml.etree.ElementTree as Et

import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))                             # 本模块目录
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'debug'))  # 调试配置目录
from debug import *
from tilt_sensor_asm330_comm import *
from tilt_sensor_asm330_def import *
from tilt_sensor_asm330_csv import *


# IMU标定专用帧队列。由采集线程在每次收到有效帧时入队，避免GUI定时器漏掉新帧。
CALIBRATION_FRAME_QUEUE_MAX = 10000
_calibration_frame_queue = queue.Queue(maxsize=CALIBRATION_FRAME_QUEUE_MAX)
_calibration_frame_queue_enabled = False
_calibration_frame_queue_drop_count = 0
_calibration_frame_queue_lock = threading.Lock()


def tilt_sensor_calibration_queue_set(enabled, clear=False):
    """启用/停用标定帧队列；clear=True时清空旧帧并重置丢帧计数。"""
    global _calibration_frame_queue_enabled, _calibration_frame_queue_drop_count
    with _calibration_frame_queue_lock:
        _calibration_frame_queue_enabled = bool(enabled)
        if clear:
            while True:
                try:
                    _calibration_frame_queue.get_nowait()
                except queue.Empty:
                    break
            _calibration_frame_queue_drop_count = 0


def tilt_sensor_calibration_frame_get_nowait():
    """非阻塞读取一帧标定数据；队列为空时抛出queue.Empty。"""
    return _calibration_frame_queue.get_nowait()


def tilt_sensor_calibration_queue_drop_count_get():
    with _calibration_frame_queue_lock:
        return _calibration_frame_queue_drop_count


def _tilt_sensor_calibration_frame_queue_put(wall_time_ns, monotonic_time_ns, frame_interval_ms):
    global _calibration_frame_queue_drop_count
    # 把控制锁持有到入队结束，保证停止记录时不会出现“停用后又入队”的竞态。
    with _calibration_frame_queue_lock:
        if not _calibration_frame_queue_enabled:
            return
        with tiltSensorRawData.data_lock:
            frame = {
                "frame_update_count": int(tiltSensorRawData.data_update_count),
                "wall_time_ns": int(wall_time_ns),
                "monotonic_time_ns": int(monotonic_time_ns),
                "frame_interval_ms": float(frame_interval_ms),
                "acc_x_raw_arr": list(tiltSensorRawData.acc_x_raw_arr),
                "acc_y_raw_arr": list(tiltSensorRawData.acc_y_raw_arr),
                "acc_z_raw_arr": list(tiltSensorRawData.acc_z_raw_arr),
                "gyr_x_raw_arr": list(tiltSensorRawData.gyr_x_raw_arr),
                "gyr_y_raw_arr": list(tiltSensorRawData.gyr_y_raw_arr),
                "gyr_z_raw_arr": list(tiltSensorRawData.gyr_z_raw_arr),
                "acc_g_arr": [tuple(v) for v in tiltSensorRawData.acc_g_arr],
                "gyr_dps_arr": [tuple(v) for v in tiltSensorRawData.gyr_dps_arr],
                "temp_raw": int(tiltSensorRawData.temp_raw),
                "temp_c": float(tiltSensorRawData.temp_c),
                "tick_ms": int(tiltSensorRawData.tick_ms),
                "data_unread": int(tiltSensorRawData.data_unread),
                "data_odr": int(tiltSensorRawData.data_odr),
                "fifo_state": int(tiltSensorRawData.fifo_state),
                "acc_fs": int(tiltSensorRawData.acc_fs),
                "gyro_fs": int(tiltSensorRawData.gyro_fs),
            }
        try:
            _calibration_frame_queue.put_nowait(frame)
        except queue.Full:
            _calibration_frame_queue_drop_count += 1



# 数据未更新判定：通讯正常、但连续这么多秒收到的都是"数据未更新(6轴96个原始值全0)"的帧时，
#   才认为"无数据"并在界面上提示；在此之前仍按"通讯正常"显示(避免把设备没数据误报成通讯故障)
DATA_NO_UPDATE_SEC = 5.0


# 测斜仪原始数据
class TiltSensorRawData:
    """测斜仪原始数据"""
    def __init__(self):
        # 各轴原始值（int16，符号已扩展）
        self.acc_x_raw_arr = [0] * INC_SAMPLE_NUM
        self.acc_y_raw_arr = [0] * INC_SAMPLE_NUM
        self.acc_z_raw_arr = [0] * INC_SAMPLE_NUM
        self.gyr_x_raw_arr = [0] * INC_SAMPLE_NUM
        self.gyr_y_raw_arr = [0] * INC_SAMPLE_NUM
        self.gyr_z_raw_arr = [0] * INC_SAMPLE_NUM
        self.temp_raw = 0                       # 温度原始值
        # 结构体附加信息
        self.data_unread = 0                    # 未读取的FIFO批次数(0=本次没有新数据)
        self.tick_ms = 0                        # 采样时间(HAL_GetTick, ms)
        self.acc_fs = ACC_FS_DEFAULT            # 本次换算使用的加速度量程(g)
        self.gyro_fs = GYRO_FS_DEFAULT          # 本次换算使用的陀螺仪量程(dps)
        self.data_odr = 0                       # 输出速率(Hz)
        self.fifo_state = 0                     # FIFO状态位
        # 换算后的物理量（double）
        self.acc_g_arr = [(0.0, 0.0, 0.0)] * INC_SAMPLE_NUM     # 加速度(g)
        self.gyr_dps_arr = [(0.0, 0.0, 0.0)] * INC_SAMPLE_NUM   # 角速度(dps)
        self.temp_c = 0.0                       # 温度(℃)
        self.temp_c_arr = [0.0] * INC_SAMPLE_NUM  # 温度数组(16个样本同值，每帧只有一个温度)
        # 量程来源标志与数据更新计数
        self.acc_fs_from_reg = False            # 本次量程是否来自结构体
        self.gyro_fs_from_reg = False
        self.acc_fs_ever_valid = False          # 是否读到过有效量程(固件量程固定，字段偶尔为0时保持上次值)
        self.gyro_fs_ever_valid = False
        self.data_update_count = 0              # 数据更新次数
        self.is_data_valid = False              # 本次数据是否有效(固件未就绪时空帧为False)
        self.data_lock = threading.Lock()         # 原始数据快照锁，供记录器一致地复制一帧


# 测斜仪通讯
class TiltSensorComm:
    """测斜仪通讯"""
    def __init__(self):
        self.comm_port = INC_COMM_PORT_DEFAULT          # COM号
        self.comm_addr = INC_COMM_ADDR_DEFAULT          # 从机通讯地址
        self.baudrate = INC_BAUDRATE_DEFAULT            # 波特率
        self.response_timeout_ms = INC_RESPONSE_TIMEOUT_MS_DEFAULT  # 应答超时(ms)
        self.mb_error_code_arr = []                     # 上位机与各从机的通讯错误码
        self.comm_error_code = MB_ERROR_CODE_FREE       # 最近一次通讯错误码
        self.comm_error_count = 0                       # 连续通讯失败次数
        self.comm_rate = 0.0                            # 通讯速率(实际轮询帧率,帧/s)
        self.comm_rate_count = 0                        # 帧率统计计数
        self.comm_rate_time_sec = time.time()           # 帧率统计起始时间
        self.array_num = INC_ARRAY_NUM_DEFAULT          # 阵列数
        self.segment_num = INC_SEGMENT_NUM_DEFAULT      # 段数
        self.average_num = INC_AVERAGE_NUM_DEFAULT      # 平均次数
        self.average_num_aia = INC_AVERAGE_NUM_AIA_DEFAULT  # AIA平均次数
        self.aia_enable = INC_AIA_ENABLE_DEFAULT        # AIA使能
        self.thread_instance = None                     # 数据获取线程
        self.thread_lock = threading.Lock()             # 通讯互斥锁
        self.terminate_thread_requst = False            # 线程退出请求
        self.queue_clear_requst = False                 # 清缓冲请求
        self.is_serial_opened = False                   # 串口是否已打开
        self.device_uid_raw = ""                        # 12字节UID的HEX显示缓存（供内部追溯）
        self.device_sn = ""                             # 已映射的DTS+6位SN，旧固件时为空
        self.device_uid_checked = False                 # 每次连接只查询一次
        self.is_data_available = False                  # 数据是否有效
        self.poll_interval_ms = MB_POLL_INTERVAL_MS_DEFAULT  # 轮询节拍(ms)，0=全速
        self.frame_time_ms = 0.0                        # 单帧读写耗时(ms)
        self.csv_frame_count = 0                        # CSV记录帧序号(只统计有效帧)
        self.data_zero_start_time_sec = 0.0             # 连续"数据未更新(全0帧)"的起始时刻(0=当前无此状态)
        self.is_data_no_update = False                   # 通讯正常但数据长时间未更新(界面提示"无数据")
        self.frame_interval_ms = 0.0                    # 相邻两帧实测间隔(ms)
        self.last_frame_time_sec = 0.0                  # 上一帧完成时刻(perf_counter)
        self.last_success_time_sec = 0.0                # 最后一次成功时刻(time.time)
        self.last_success_time_text = ""                # 最后一次成功时刻文字(供界面显示)
        self.comm_success_count = 0                     # 成功帧数
        self.comm_total_count = 0                       # 总帧数(含失败)


tiltSensorRawData = TiltSensorRawData()
tiltSensorComm = TiltSensorComm()

def tilt_sensor_user_habits_get(config_file_path='config.xml'):
    """
    读取config.xml中倾角仪相关参数

    Args:
        config_file_path (str): 配置文件路径，默认"config.xml"

    Returns:
        bool: 读取成功，返回True。读取失败（文件不存在或内容非法），返回False（各参数保留默认值）。

    Raises:

    Note:
        读取IncCommPort、IncBaudrate、IncArrayNum、IncSegmentNum、IncAverageNum、
        IncAverageNumAIA、IncAIAEnable、IncDataSaveDir(数据记录目录)；单项读取失败只影响该项，其余照常读取。

    """
    try:
        tree = Et.parse(config_file_path)
        root = tree.getroot()
    except:
        return False

    for item in root.iter('IncCommPort'):
        if (item.text != None) and (str(item.text).strip() != ""):
            tiltSensorComm.comm_port = str(item.text).strip()
    for item in root.iter('IncBaudrate'):
        try:
            tiltSensorComm.baudrate = int(str(item.text).strip())
        except:
            pass
    for item in root.iter('IncArrayNum'):
        try:
            tiltSensorComm.array_num = int(str(item.text).strip())
        except:
            pass
    for item in root.iter('IncSegmentNum'):
        try:
            tiltSensorComm.segment_num = int(str(item.text).strip())
        except:
            pass
    for item in root.iter('IncAverageNum'):
        try:
            tiltSensorComm.average_num = int(str(item.text).strip())
        except:
            pass
    for item in root.iter('IncAverageNumAIA'):
        try:
            tiltSensorComm.average_num_aia = int(str(item.text).strip())
        except:
            pass
    for item in root.iter('IncAIAEnable'):
        tiltSensorComm.aia_enable = (str(item.text).strip().lower() == "true")
    for item in root.iter('IncDataSaveDir'):
        if (item.text != None) and (str(item.text).strip() != ""):
            csv_dir_set(str(item.text).strip())                 # 数据记录目录(界面"数据记录"页可改)
    for item in root.iter('IncPollIntervalMs'):
        try:
            tiltSensorComm.poll_interval_ms = int(str(item.text).strip())
        except:
            pass
    return True


def tilt_sensor_comm_open():
    """
    打开测斜仪通讯（按当前参数：串口号/波特率/应答超时）

    Args:
        None

    Returns:
        bool: 打开成功，返回True。打开失败，返回False。

    Raises:

    Note:
        串口号与波特率来自config.xml（读取失败时为tilt_sensor_asm330_def.py中的默认值）。

    """
    if not mb_serial_open(tiltSensorComm.comm_port, tiltSensorComm.baudrate):
        tiltSensorComm.is_serial_opened = False
        return False
    mb_serial_set_response_timeout(tiltSensorComm.comm_port, tiltSensorComm.response_timeout_ms)
    tiltSensorComm.is_serial_opened = True
    tiltSensorComm.comm_error_count = 0
    tiltSensorComm.device_uid_raw = ""
    tiltSensorComm.device_sn = ""
    tiltSensorComm.device_uid_checked = False
    return True


def tilt_sensor_comm_close():
    """
    关闭测斜仪通讯

    Args:
        None

    Returns:
        bool: 关闭成功，返回True。关闭失败，返回False。

    Raises:

    Note:

    """
    csv_close()                     # 关闭串口前先把记录文件写好并关闭
    ret = mb_serial_close(tiltSensorComm.comm_port)
    tiltSensorComm.is_serial_opened = False
    tiltSensorComm.is_data_available = False
    tiltSensorComm.device_uid_raw = ""
    tiltSensorComm.device_sn = ""
    tiltSensorComm.device_uid_checked = False
    return ret


def tilt_sensor_raw_data_process(raw_data):
    """
    将一帧IMU原始数据换算为物理量并原子更新共享快照。
    记录器可通过 tiltSensorRawData.data_lock 获取一致的帧快照。
    """
    if not raw_data:
        return False

    raw_all_zero = True
    for key_name in ("acc_x_raw_arr", "acc_y_raw_arr", "acc_z_raw_arr",
                     "gyr_x_raw_arr", "gyr_y_raw_arr", "gyr_z_raw_arr"):
        for raw_value in raw_data[key_name]:
            if raw_value != 0:
                raw_all_zero = False
                break
        if not raw_all_zero:
            break

    if raw_all_zero:
        with tiltSensorRawData.data_lock:
            tiltSensorRawData.is_data_valid = False
        return True

    # 先在局部变量中计算，最后一次性更新共享数据，避免记录器读到跨帧混合数据。
    with tiltSensorRawData.data_lock:
        acc_fs_in = raw_data["acc_fs"]
        gyro_fs_in = raw_data["gyro_fs"]

        if acc_fs_is_valid(acc_fs_in):
            acc_fs = acc_fs_in
            acc_fs_from_reg = True
            acc_fs_ever_valid = True
        elif tiltSensorRawData.acc_fs_ever_valid:
            acc_fs = tiltSensorRawData.acc_fs
            acc_fs_from_reg = False
            acc_fs_ever_valid = True
        else:
            acc_fs = ACC_FS_DEFAULT
            acc_fs_from_reg = False
            acc_fs_ever_valid = False

        if gyro_fs_is_valid(gyro_fs_in):
            gyro_fs = gyro_fs_in
            gyro_fs_from_reg = True
            gyro_fs_ever_valid = True
        elif tiltSensorRawData.gyro_fs_ever_valid:
            gyro_fs = tiltSensorRawData.gyro_fs
            gyro_fs_from_reg = False
            gyro_fs_ever_valid = True
        else:
            gyro_fs = GYRO_FS_DEFAULT
            gyro_fs_from_reg = False
            gyro_fs_ever_valid = False

        raw_arrays = {
            "acc_x_raw_arr": list(raw_data["acc_x_raw_arr"]),
            "acc_y_raw_arr": list(raw_data["acc_y_raw_arr"]),
            "acc_z_raw_arr": list(raw_data["acc_z_raw_arr"]),
            "gyr_x_raw_arr": list(raw_data["gyr_x_raw_arr"]),
            "gyr_y_raw_arr": list(raw_data["gyr_y_raw_arr"]),
            "gyr_z_raw_arr": list(raw_data["gyr_z_raw_arr"]),
        }
        acc_g_arr = []
        gyr_dps_arr = []
        for i in range(INC_SAMPLE_NUM):
            acc_g_arr.append((
                accel_raw_to_g(raw_data["acc_x_raw_arr"][i], acc_fs),
                accel_raw_to_g(raw_data["acc_y_raw_arr"][i], acc_fs),
                accel_raw_to_g(raw_data["acc_z_raw_arr"][i], acc_fs)
            ))
            gyr_dps_arr.append((
                gyro_raw_to_dps(raw_data["gyr_x_raw_arr"][i], gyro_fs),
                gyro_raw_to_dps(raw_data["gyr_y_raw_arr"][i], gyro_fs),
                gyro_raw_to_dps(raw_data["gyr_z_raw_arr"][i], gyro_fs)
            ))

        temp_raw = raw_data["temp_raw"]
        temp_c = temp_raw_to_celsius(temp_raw)

        for name, values in raw_arrays.items():
            setattr(tiltSensorRawData, name, values)
        tiltSensorRawData.temp_raw = temp_raw
        tiltSensorRawData.data_unread = raw_data["data_unread"]
        tiltSensorRawData.tick_ms = raw_data["tick_ms"]
        tiltSensorRawData.data_odr = raw_data["data_odr"]
        tiltSensorRawData.fifo_state = raw_data["fifo_state"]
        tiltSensorRawData.acc_fs = acc_fs
        tiltSensorRawData.gyro_fs = gyro_fs
        tiltSensorRawData.acc_fs_from_reg = acc_fs_from_reg
        tiltSensorRawData.gyro_fs_from_reg = gyro_fs_from_reg
        tiltSensorRawData.acc_fs_ever_valid = acc_fs_ever_valid
        tiltSensorRawData.gyro_fs_ever_valid = gyro_fs_ever_valid
        tiltSensorRawData.acc_g_arr = acc_g_arr
        tiltSensorRawData.gyr_dps_arr = gyr_dps_arr
        tiltSensorRawData.temp_c = temp_c
        tiltSensorRawData.temp_c_arr = [temp_c] * INC_SAMPLE_NUM
        tiltSensorRawData.is_data_valid = True
        tiltSensorRawData.data_update_count += 1
    return True


def tilt_sensor_acc_g_average_get():
    """
    取最近一帧16个样本的加速度平均值

    Args:
        None

    Returns:
        tuple: (gx, gy, gz) 平均加速度值(double, 单位g)；暂无数据时返回None

    Raises:

    Note:
        供加速度计校准等算法取当前静止位置下的加速度值使用。

    """
    if tiltSensorRawData.data_update_count == 0:
        return None
    acc_x_sum = 0.0
    acc_y_sum = 0.0
    acc_z_sum = 0.0
    for i in range(len(tiltSensorRawData.acc_g_arr)):
        acc_x_sum += tiltSensorRawData.acc_g_arr[i][0]
        acc_y_sum += tiltSensorRawData.acc_g_arr[i][1]
        acc_z_sum += tiltSensorRawData.acc_g_arr[i][2]
    sample_num = len(tiltSensorRawData.acc_g_arr)
    if sample_num == 0:
        return None
    return (acc_x_sum / sample_num, acc_y_sum / sample_num, acc_z_sum / sample_num)


def tilt_sensor_gyr_dps_average_get():
    """
    取最近一帧16个样本的角速度平均值

    Args:
        None

    Returns:
        tuple: (gx, gy, gz) 平均角速度值(double, 单位dps)；暂无数据时返回None

    Raises:

    Note:

    """
    if tiltSensorRawData.data_update_count == 0:
        return None
    gyr_x_sum = 0.0
    gyr_y_sum = 0.0
    gyr_z_sum = 0.0
    for i in range(len(tiltSensorRawData.gyr_dps_arr)):
        gyr_x_sum += tiltSensorRawData.gyr_dps_arr[i][0]
        gyr_y_sum += tiltSensorRawData.gyr_dps_arr[i][1]
        gyr_z_sum += tiltSensorRawData.gyr_dps_arr[i][2]
    sample_num = len(tiltSensorRawData.gyr_dps_arr)
    if sample_num == 0:
        return None
    return (gyr_x_sum / sample_num, gyr_y_sum / sample_num, gyr_z_sum / sample_num)


def thread_of_tilt_sensor_data_get_create_and_start():
    """
    创建并启动倾角仪数据获取线程

    Args:
        None

    Returns:
        None

    Raises:

    Note:
        线程已在运行时直接返回；串口未打开时会先尝试打开，失败也会启动线程，
        线程内每秒重试，串口地址改对后自动连上并开始记录。

    """
    if tiltSensorComm.thread_instance != None:
        return
    if not tiltSensorComm.is_serial_opened:
        tilt_sensor_comm_open()   # 先尝试打开；失败也没关系，线程内会每秒重试(串口地址改对后自动连上)
    t = threading.Thread(target=thread_func_of_tilt_sensor_data_get)
    t.daemon = True                     # 主程序退出时不阻塞
    tiltSensorComm.thread_instance = t
    t.start()


def thread_of_tilt_sensor_data_get_terminate():
    """
    中止倾角仪数据获取线程

    Args:
        None

    Returns:
        None

    Raises:

    Note:
        请求退出后等待数据获取线程结束（thread_instance为空）再返回。

    """
    tiltSensorComm.terminate_thread_requst = True
    while True:
        if tiltSensorComm.thread_instance == None:
            break
        time.sleep(0.01)

def _sleep_until(next_time_sec):
    '''
    精确等待到指定时刻(不受Windows定时器粒度影响)

    Args:
        next_time_sec (float): 目标时刻(perf_counter时间基准)

    Returns:
        None

    Raises:

    Note:
        先用time.sleep粗睡到目标前2ms，再用短自旋精调到目标时刻，
        避免Windows默认定时器粒度(15.6ms)造成的节拍抖动。

    '''
    now_sec = time.perf_counter()
    if next_time_sec > now_sec:
        time.sleep(max(0.0, next_time_sec - now_sec - 0.002))
        while time.perf_counter() < next_time_sec:
            pass


def tilt_sensor_comm_error_text_get():
    '''
    把通讯错误码翻译成界面可读文字

    Args:
        None

    Returns:
        str: 错误描述文字

    Raises:

    Note:

    '''
    if tiltSensorComm.comm_error_code == MB_ERROR_CODE_FREE:
        return "正常"
    if tiltSensorComm.comm_error_code == MB_ERROR_CODE_TIMEOUT:
        return "无应答(超时)"
    if tiltSensorComm.comm_error_code == MB_ERROR_CODE_FRAME:
        return "帧格式错"
    if tiltSensorComm.comm_error_code == MB_ERROR_CODE_CRC:
        return "CRC错"
    if tiltSensorComm.comm_error_code == MB_ERROR_CODE_EXCEPTION:
        return "从机异常(0x%02X)" % mb_exception_code_get()
    if tiltSensorComm.comm_error_code == MB_ERROR_CODE_SERIAL_NOT_OPEN:
        return "串口未打开"
    return "通讯失败(%d)" % tiltSensorComm.comm_error_code


def thread_func_of_tilt_sensor_data_get():
    """
    倾角仪数据获取线程

    Args:
        None

    Returns:
        None

    Raises:

    Note:
        循环读取一帧ASM330数据（保持寄存器1000起104个），并把原始int16值换算为double
        写入tiltSensorRawData；连续通讯失败次数过多时会关闭串口，下一轮自动重开。

    """
    tiltSensorComm.is_data_available = False
    tiltSensorComm.comm_error_count = 0
    tiltSensorComm.comm_success_count = 0
    tiltSensorComm.comm_total_count = 0
    tiltSensorComm.last_frame_time_sec = 0.0
    tiltSensorComm.csv_frame_count = 0
    tiltSensorComm.data_zero_start_time_sec = 0.0
    tiltSensorComm.is_data_no_update = False
    period_sec = tiltSensorComm.poll_interval_ms / 1000.0
    next_time_sec = time.perf_counter()

    while True:
        # 处理线程退出请求
        if tiltSensorComm.terminate_thread_requst:
            tiltSensorComm.terminate_thread_requst = False
            tiltSensorComm.thread_instance = None
            tiltSensorComm.is_data_available = False
            csv_close()
            break

        # 处理清缓冲请求（把最近一帧数据作废，等待下一帧）
        if tiltSensorComm.queue_clear_requst:
            tiltSensorComm.queue_clear_requst = False
            tiltSensorComm.is_data_available = False

        # 串口未打开时先打开
        if (not tiltSensorComm.is_serial_opened) and (not tilt_sensor_comm_open()):
            tiltSensorComm.comm_error_code = MB_ERROR_CODE_SERIAL_NOT_OPEN
            time.sleep(1)

        if tiltSensorComm.is_serial_opened:
            # 串口成功打开后的首次轮询里，由唯一通信线程先尝试一次 UID 查询。
            # 失败/固件不支持时静默忽略，之后继续原有的104寄存器采样。
            if not tiltSensorComm.device_uid_checked:
                tiltSensorComm.device_uid_checked = True
                with tiltSensorComm.thread_lock:
                    uid_bytes = mb_device_uid_read(tiltSensorComm.comm_addr)
                if uid_bytes is not None:
                    tiltSensorComm.device_uid_raw = uid_bytes.hex().upper()
                    tiltSensorComm.device_sn = device_uid_to_sn(uid_bytes)

            # 读取一帧原始数据
            time_begin_sec = time.perf_counter()
            raw_data = {}
            comm_error_code = [0]
            tiltSensorComm.thread_lock.acquire()
            ret = tilt_sensor_data_get(tiltSensorComm.comm_port, tiltSensorComm.comm_addr,
                                       raw_data, comm_error_code)
            tiltSensorComm.thread_lock.release()
            tiltSensorComm.frame_time_ms = round((time.perf_counter() - time_begin_sec) * 1000.0, 2)

            # 实测帧间隔（首帧用配置节拍兜底）
            time_frame_wall_ns = time.time_ns()
            time_frame_wall_sec = time_frame_wall_ns / 1e9
            time_frame_monotonic_ns = time.perf_counter_ns()
            time_frame_sec = time_frame_monotonic_ns / 1e9
            if tiltSensorComm.last_frame_time_sec > 0:
                frame_interval_ms = (time_frame_sec - tiltSensorComm.last_frame_time_sec) * 1000.0
            else:
                frame_interval_ms = float(tiltSensorComm.poll_interval_ms)
            tiltSensorComm.last_frame_time_sec = time_frame_sec
            if frame_interval_ms <= 0:
                frame_interval_ms = float(tiltSensorComm.poll_interval_ms)
            tiltSensorComm.comm_total_count += 1

            if ret:
                tilt_sensor_raw_data_process(raw_data)
                tiltSensorComm.comm_error_code = MB_ERROR_CODE_FREE
                tiltSensorComm.comm_error_count = 0
                tiltSensorComm.comm_success_count += 1
                tiltSensorComm.mb_error_code_arr = [MB_ERROR_CODE_FREE] * tiltSensorComm.array_num
                if tiltSensorRawData.is_data_valid:
                    # 收到真正的新数据：清掉"数据未更新"计时，界面按"通讯正常"显示
                    tiltSensorComm.data_zero_start_time_sec = 0.0
                    tiltSensorComm.is_data_no_update = False
                    tiltSensorComm.is_data_available = True
                    tiltSensorComm.frame_interval_ms = round(frame_interval_ms, 3)
                    tiltSensorComm.last_success_time_sec = time.time()
                    tiltSensorComm.last_success_time_text = time.strftime("%Y-%m-%d %H:%M:%S")
                    # 标定专用队列由采集线程直接入队，避免GUI刷新节拍造成整帧漏采。
                    _tilt_sensor_calibration_frame_queue_put(
                        time_frame_wall_ns, time_frame_monotonic_ns, frame_interval_ms
                    )
                    # 串口读取只负责实时显示。CSV仅由用户点击“开始记录”时显式打开。
                    tiltSensorComm.csv_frame_count += 1
                    csv_write_frame(tiltSensorComm.csv_frame_count,
                                    tiltSensorRawData.acc_g_arr, tiltSensorRawData.gyr_dps_arr,
                                    tiltSensorRawData.temp_c, tiltSensorRawData.temp_raw,
                                    tiltSensorRawData.acc_fs, tiltSensorRawData.gyro_fs,
                                    tiltSensorRawData.tick_ms, tiltSensorComm.frame_interval_ms,
                                    tiltSensorRawData.data_unread, time_frame_wall_sec)
                else:
                    # 通讯成功、但这一帧的数据没有更新(固件还没把新样本填进寄存器区，6轴96个原始值全0)：
                    #   这不算通讯失败！——5秒内界面仍显示"通讯正常"(绿)，只有连续DATA_NO_UPDATE_SEC秒
                    #   都收不到新数据时才提示"无数据"(绿底文字)，避免把"设备没数据"误报成"通讯故障"。
                    if tiltSensorComm.data_zero_start_time_sec <= 0.0:
                        tiltSensorComm.data_zero_start_time_sec = time.time()
                    if (time.time() - tiltSensorComm.data_zero_start_time_sec) >= DATA_NO_UPDATE_SEC:
                        tiltSensorComm.is_data_no_update = True
                        tiltSensorComm.is_data_available = False
                    else:
                        tiltSensorComm.is_data_available = True
                    tiltSensorComm.frame_interval_ms = 0.0
                # 通讯速率(实际轮询帧率)：每满1秒统计一次，避免瞬时值乱跳
                tiltSensorComm.comm_rate_count += 1
                time_rate_sec = time.time() - tiltSensorComm.comm_rate_time_sec
                if time_rate_sec >= 1.0:
                    tiltSensorComm.comm_rate = round(tiltSensorComm.comm_rate_count / time_rate_sec, 1)
                    tiltSensorComm.comm_rate_count = 0
                    tiltSensorComm.comm_rate_time_sec = time.time()
            else:
                tiltSensorComm.comm_error_code = comm_error_code[0]
                tiltSensorComm.comm_error_count += 1
                tiltSensorComm.is_data_available = False          # 本次没读到数据：界面不再显示"通讯正常"
                tiltSensorComm.comm_rate = 0.0
                tiltSensorComm.frame_interval_ms = 0.0
                tiltSensorComm.mb_error_code_arr = [comm_error_code[0]] * tiltSensorComm.array_num
                if tiltSensorComm.comm_error_count >= 10:
                    # 连续失败过多：关闭记录文件与串口，等1s后重新打开（例如USB被拔出后重插）
                    csv_close()
                    tilt_sensor_comm_close()
                    time.sleep(1)

        # 手动记录期间不因暂时无新数据而自动结束；串口关闭/通讯连续失败时仍会执行收尾。

        # 轮询节拍配速（绝对时刻配速，不受Windows定时器粒度影响；节拍为0时全速）
        if period_sec > 0:
            next_time_sec += period_sec
            now_sec = time.perf_counter()
            if next_time_sec < now_sec:
                next_time_sec = now_sec
            _sleep_until(next_time_sec)
        else:
            next_time_sec = time.perf_counter()


def main():
    """
    本模块自测入口

    Args:
        None

    Returns:
        None

    Raises:

    Note:
        读取config.xml -> 打开串口 -> 启动数据获取线程 -> 打印5帧换算后的double数据 ->
        停止线程 -> 关闭串口。可在源码目录直接运行本文件进行自测。

    """
    config_file_path = 'config.xml'
    if not os.path.exists(config_file_path):
        config_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'config.xml')
    ret = tilt_sensor_user_habits_get(config_file_path)
    print("读取config.xml：" + str(ret) + "    串口 = " + str(tiltSensorComm.comm_port) +
          "    波特率 = " + str(tiltSensorComm.baudrate))

    if not tilt_sensor_comm_open():
        print("打开串口失败！")
        return

    thread_of_tilt_sensor_data_get_create_and_start()
    for i in range(5):
        time.sleep(0.5)
        if not tiltSensorComm.is_data_available:
            print("未获取到数据    错误码 = " + str(tiltSensorComm.comm_error_code))
            continue
        acc_g_average = tilt_sensor_acc_g_average_get()
        gyr_dps_average = tilt_sensor_gyr_dps_average_get()
        print("第%d帧：tick=%dms 未读=%d 帧间隔=%.3fms 加速度量程=%sg 陀螺仪量程=%sdps 温度=%.3f℃" %
              (tiltSensorRawData.data_update_count, tiltSensorRawData.tick_ms,
               tiltSensorRawData.data_unread, tiltSensorComm.frame_interval_ms,
               tiltSensorRawData.acc_fs, tiltSensorRawData.gyro_fs, tiltSensorRawData.temp_c))
        print("        平均加速度 = (%.6f, %.6f, %.6f) g    平均角速度 = (%.6f, %.6f, %.6f) dps" %
              (acc_g_average[0], acc_g_average[1], acc_g_average[2],
               gyr_dps_average[0], gyr_dps_average[1], gyr_dps_average[2]))

    print("单帧耗时 = %.2fms    帧间隔 = %.3fms    成功率 = %.1f%%(%d/%d)    最后成功 = %s" % (
        tiltSensorComm.frame_time_ms, tiltSensorComm.frame_interval_ms,
        (tiltSensorComm.comm_success_count * 100.0 / tiltSensorComm.comm_total_count) if (tiltSensorComm.comm_total_count > 0) else 0.0,
        tiltSensorComm.comm_success_count, tiltSensorComm.comm_total_count,
        tiltSensorComm.last_success_time_text))
    thread_of_tilt_sensor_data_get_terminate()
    tilt_sensor_comm_close()
    print("记录状态 =", csv_state_text_get())
    print("已停止数据获取并关闭串口。")


if __name__ == '__main__':
    main()