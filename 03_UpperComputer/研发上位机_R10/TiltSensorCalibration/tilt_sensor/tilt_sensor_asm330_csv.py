"""测斜仪(ASM330 IMU)数据CSV记录模块"""
import os
import sys
import time
import datetime
import threading

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'debug'))
from debug import *
from tilt_sensor_asm330_def import *


#
# 记录参数定义
#
CSV_DIR_DEFAULT = r'D:\倾角仪数据'      # 默认记录目录(可用config.xml的IncDataSaveDir配置，也可在界面"数据记录"页选择)
csv_dir_path = CSV_DIR_DEFAULT          # 当前记录目录(由config.xml/界面设置)
csv_pause_enable = True                 # 默认禁止自动记录；仅界面“开始记录”按钮显式打开CSV
CSV_FLUSH_INTERVAL_SEC = 0.2            # 写盘线程批量写入间隔(s)
CSV_BUFFER_MAX_LINES = 20000            # 缓冲上限(行)，超出丢弃并计数
CSV_IDLE_CLOSE_SEC = 10                 # 无有效数据超过该秒数时自动关闭当前记录文件
CSV_FRAME_INTERVAL_MAX_MS = 100.0       # 时间铺展用帧间隔上限(ms)：16个样本的真实跨度只有约19ms(固件833Hz)，
                                        # 首帧或停顿后实测间隔可能远大于此，按上限铺展避免把停顿平摊到样本上
CSV_HEADER = ["timestamp", "time_ms_since_start", "frame_index", "sample_index",
              "acc_x_g", "acc_y_g", "acc_z_g",
              "gyr_x_dps", "gyr_y_dps", "gyr_z_dps",
              "temp_c", "temp_raw",
              "acc_fs_g", "gyro_fs_dps",
              "mcu_tick_ms", "mcu_sample_ms", "frame_interval_ms", "data_unread"]

csv_file = None                         # 记录文件句柄
csv_file_path = ""                      # 记录文件完整路径
csv_enable = False                      # 是否正在记录
csv_row_count = 0                       # 已写入行数
csv_drop_count = 0                      # 丢弃行数(缓冲溢出/写盘失败)
csv_buffer = []                         # 待写缓冲(采集线程写入，写盘线程取走)
csv_lock = threading.Lock()             # 缓冲互斥锁
csv_thread_instance = None              # 写盘线程
csv_terminate_requst = False            # 写盘线程退出请求
csv_start_time_sec = 0.0                # 记录开始时刻(相对时间列基准)
csv_first_frame = True                  # 首帧标志(把记录起点对齐到第一个样本时刻)
csv_last_sample_time_us = 0             # 上一个写出样本的时刻(µs整数，保证时间戳严格递增)
csv_start_time_us = 0                   # 记录起点(µs整数，相对时间列基准)
csv_write_error = ""                    # 最近一次写盘错误信息


def csv_dir_set(path):
    """
    设置记录目录（只记录路径，不创建目录）

    Args:
        path (str): 记录目录路径，如 "D:\\倾角仪数据"

    Returns:
        None

    Raises:

    Note:
        目录不存在时不会创建（按需求：路径不存在就不记录），由csv_dir_is_valid判断。

    """
    global csv_dir_path
    csv_dir_path = str(path).strip()


def csv_dir_path_get():
    """
    取当前配置的记录目录（不管是否存在，供界面显示）

    Args:
        None

    Returns:
        str: 配置的记录目录路径

    Raises:

    Note:

    """
    return csv_dir_path


def csv_dir_is_valid():
    """
    判断记录目录是否存在

    Args:
        None

    Returns:
        bool: 目录存在返回True；路径为空或目录不存在返回False

    Raises:

    Note:
        不存在就不记录（方便用U盘/网络盘做记录目录：没插盘时只是不记录，不会自动乱建目录）。

    """
    if (csv_dir_path is None) or (str(csv_dir_path).strip() == ""):
        return False
    return os.path.isdir(csv_dir_path)


def csv_dir_get():
    """
    获取记录目录

    Args:
        None

    Returns:
        str: 记录目录路径；目录不存在或为空时返回空字符串（调用方据此不记录）

    Raises:

    Note:

    """
    if csv_dir_is_valid():
        return csv_dir_path
    return ""


def csv_pause_set(enable):
    """
    设置/清除"暂停记录"状态

    Args:
        enable (bool): True=禁止自动自动开启记录；False=允许手动按钮调用csv_open()

    Returns:
        None

    Raises:

    Note:
        True 表示默认/停止状态；CSV不会因串口收到数据而自动打开。该标志不会删除已记录的文件。

    """
    global csv_pause_enable
    csv_pause_enable = bool(enable)


def csv_pause_get():
    """
    取"暂停记录"状态

    Args:
        None

    Returns:
        bool: 已暂停返回True

    Raises:

    Note:

    """
    return csv_pause_enable


def csv_writer_thread_func():
    """
    CSV写盘线程（批量写入，避免影响采集节拍）

    Args:
        None

    Returns:
        None

    Raises:

    Note:
        每CSV_FLUSH_INTERVAL_SEC秒把缓冲批量写入并flush；收到退出请求时把剩余缓冲写完再退出。

    """
    global csv_row_count, csv_drop_count, csv_buffer, csv_write_error, csv_terminate_requst, csv_thread_instance

    while True:
        if csv_terminate_requst:
            break
        lines = []
        csv_lock.acquire()
        if csv_buffer:
            lines = csv_buffer[:]
            del csv_buffer[:]
        csv_lock.release()
        if lines:
            try:
                csv_file.writelines(lines)
                csv_file.flush()
                csv_row_count += len(lines)
                csv_write_error = ""
            except Exception as exc:
                csv_write_error = str(exc)[:60]
                csv_drop_count += len(lines)
        time.sleep(CSV_FLUSH_INTERVAL_SEC)

    lines = []
    csv_lock.acquire()
    if csv_buffer:
        lines = csv_buffer[:]
        del csv_buffer[:]
    csv_lock.release()
    if lines:
        try:
            csv_file.writelines(lines)
            csv_file.flush()
            csv_row_count += len(lines)
        except:
            csv_drop_count += len(lines)
    csv_terminate_requst = False
    csv_thread_instance = None

def csv_is_enabled():
    '''
    查询当前是否正在记录

    Args:
        None

    Returns:
        bool: 正在记录返回True

    Raises:

    Note:
        供其它模块查询(避免from ... import *取到的是导入时刻的副本)

    '''
    return csv_enable


def csv_open():
    """
    打开CSV记录文件（文件名：tilt_sensor_年月日_时分秒.csv）

    Args:
        None

    Returns:
        bool: 打开成功返回True；失败返回False（原因见csv_write_error）

    Raises:

    Note:
        由界面“开始记录”按钮显式调用。打开串口或收到数据不会自动创建文件。

    """
    global csv_file, csv_file_path, csv_enable, csv_row_count, csv_drop_count
    global csv_buffer, csv_thread_instance, csv_start_time_sec, csv_write_error, csv_terminate_requst
    global csv_first_frame, csv_last_sample_time_us, csv_start_time_us

    if csv_enable:
        return True
    if csv_pause_enable:
        return False                                                   # 用户点了"暂停记录"：不自动开始记录
    csv_dir = csv_dir_get()
    if csv_dir == "":
        csv_write_error = "记录目录不存在: " + str(csv_dir_path)          # 路径存在性检查不通过 -> 不记录
        return False
    file_name = "tilt_sensor_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".csv"
    file_path = os.path.join(csv_dir, file_name)
    try:
        file_handle = open(file_path, 'w', encoding='utf-8-sig', newline='')
        file_handle.write(",".join(CSV_HEADER) + "\r\n")
        file_handle.flush()
    except Exception as exc:
        csv_write_error = str(exc)[:60]
        return False

    csv_file = file_handle
    csv_file_path = file_path
    csv_enable = True
    csv_row_count = 0
    csv_drop_count = 0
    csv_buffer = []
    csv_write_error = ""
    csv_start_time_sec = time.time()
    csv_first_frame = True
    csv_last_sample_time_us = 0
    csv_start_time_us = 0
    csv_terminate_requst = False
    writer_thread = threading.Thread(target=csv_writer_thread_func)
    writer_thread.daemon = True
    csv_thread_instance = writer_thread
    writer_thread.start()
    return True


def csv_close():
    """
    关闭CSV记录文件（先让写盘线程把缓冲写完，再flush并关闭）

    Args:
        None

    Returns:
        bool: 关闭成功返回True

    Raises:

    Note:
        串口关闭、程序退出、长时间无数据时都会调用；关闭后csv_file_path仍保留供界面显示。

    """
    global csv_file, csv_enable, csv_thread_instance, csv_terminate_requst

    if not csv_enable:
        return True
    csv_terminate_requst = True
    wait_begin_sec = time.time()
    while (csv_thread_instance != None) and ((time.time() - wait_begin_sec) < 3.0):
        time.sleep(0.01)
    if csv_file != None:
        try:
            csv_file.flush()
            csv_file.close()
        except:
            pass
    csv_file = None
    csv_enable = False
    return True


def csv_write_frame(frame_index, acc_g_arr, gyr_dps_arr, temp_c, temp_raw,
                    acc_fs, gyro_fs, tick_ms, frame_interval_ms, data_unread,
                    time_frame_sec=None):
    """
    把一帧的16个样本按帧间隔均匀分配时间戳后写入缓冲（每样本一行）

    Args:
        frame_index (int): 帧序号(从1开始)
        acc_g_arr (list): 16个加速度样本(double,单位g)，元素为(gx,gy,gz)
        gyr_dps_arr (list): 16个角速度样本(double,单位dps)，元素为(gx,gy,gz)
        temp_c (float): 本帧温度(℃)，16行填同一个值
        temp_raw (int): 本帧温度原始值，16行填同一个值
        acc_fs (int): 加速度量程(g)
        gyro_fs (int): 陀螺仪量程(dps)
        tick_ms (int): 本帧MCU采样时间(HAL_GetTick,ms)
        frame_interval_ms (float): 实测帧间隔(ms)
        data_unread (int): 未读取批次数
        time_frame_sec (float): 本帧读取完成时刻(time.time())；None表示在本函数内取当前时刻

    Returns:
        int: 本次写入缓冲的行数；未记录时返回0

    Raises:

    Note:
        时间分配：dt为实测帧间隔(上限CSV_FRAME_INTERVAL_MAX_MS，防止首帧/停顿把样本时间摊开)，
        第i个样本时间 = 本帧读取时刻 - (15-i)*dt/16，即把16个样本均匀铺满当前帧间隔；
        温度/量程/MCU tick在16行中相同。

    """
    global csv_drop_count, csv_start_time_sec, csv_first_frame, csv_last_sample_time_us, csv_start_time_us

    if not csv_enable:
        return 0
    sample_num = len(acc_g_arr)
    if sample_num <= 0:
        return 0

    if time_frame_sec == None:
        time_frame_sec = time.time()
    # 帧间隔上限：首帧或长时间停顿后实测间隔会很大(如1s)，但16个样本的真实跨度只有约19ms，
    #   这里按上限铺展(列中写钳位后的值)，保证时间戳与mcu_sample_ms一致
    if frame_interval_ms > CSV_FRAME_INTERVAL_MAX_MS:
        frame_interval_ms = CSV_FRAME_INTERVAL_MAX_MS
    dt_sec = frame_interval_ms / 1000.0
    dt_sample_sec = dt_sec / sample_num
    time_first_sample_us = int(round((time_frame_sec - (sample_num - 1) * dt_sample_sec) * 1000000.0))
    if csv_first_frame:
        # 首帧：把记录时间基准对齐到本帧第一个样本，保证相对时间从0开始
        csv_start_time_us = time_first_sample_us
        csv_first_frame = False

    lines = []
    for i in range(sample_num):
        time_sample_us = int(round((time_frame_sec - (sample_num - 1 - i) * dt_sample_sec) * 1000000.0))
        # 保证时间戳严格递增(写入抖动/浮点精度都可能造成重复或倒挂，这里按µs整数钳位)
        if time_sample_us <= csv_last_sample_time_us:
            time_sample_us = csv_last_sample_time_us + 1
        csv_last_sample_time_us = time_sample_us
        mcu_sample_ms = tick_ms - (sample_num - 1 - i) * (frame_interval_ms / sample_num)
        acc_g = acc_g_arr[i]
        gyr_dps = gyr_dps_arr[i]
        time_text = datetime.datetime.fromtimestamp(time_sample_us // 1000000).strftime("%Y-%m-%d %H:%M:%S") + ".%06d" % (time_sample_us % 1000000)
        time_ms_since_start = (time_sample_us - csv_start_time_us) / 1000.0
        lines.append("%s,%.3f,%d,%d,%.9f,%.9f,%.9f,%.6f,%.6f,%.6f,%.3f,%d,%d,%d,%d,%.1f,%.3f,%d\r\n" % (
            time_text, time_ms_since_start, frame_index, i,
            acc_g[0], acc_g[1], acc_g[2], gyr_dps[0], gyr_dps[1], gyr_dps[2],
            temp_c, temp_raw, acc_fs, gyro_fs,
            tick_ms, mcu_sample_ms, frame_interval_ms, data_unread))

    csv_lock.acquire()
    if len(csv_buffer) < CSV_BUFFER_MAX_LINES:
        csv_buffer.extend(lines)
    else:
        csv_drop_count += len(lines)
    csv_lock.release()
    return len(lines)


def csv_file_name_get():
    """
    取记录文件名（不含路径）

    Args:
        None

    Returns:
        str: 文件名；未记录过返回空字符串

    Raises:

    Note:

    """
    if csv_file_path == "":
        return ""
    return os.path.basename(csv_file_path)


def csv_state_text_get():
    """
    获取记录状态文字（供界面显示）

    Args:
        None

    Returns:
        str: 如"记录中: tilt_sensor_20260924_101233.csv | 12345行 | 2.1MB | 丢0行"

    Raises:

    Note:

    """
    if csv_enable:
        file_size_mb = 0.0
        try:
            file_size_mb = os.path.getsize(csv_file_path) / 1048576.0
        except:
            pass
        text = "记录中: %s | %d行 | %.1fMB | 丢%d行 | 目录 = %s" % (
            csv_file_name_get(), csv_row_count, file_size_mb, csv_drop_count, csv_dir_path)
        if csv_write_error != "":
            text += " | 写盘错误:" + csv_write_error
        return text
    if not csv_dir_is_valid():
        return "未记录(记录目录不存在: %s)" % csv_dir_path
    if csv_pause_enable:
        return "未记录(等待手动开始)"
    if csv_file_path == "":
        return "未记录"
    return "已停止: %s | 共%d行 | 丢%d行" % (csv_file_name_get(), csv_row_count, csv_drop_count)


def main():
    """
    本模块自测：写入2帧(共32行)后关闭，并打印文件首尾行

    Args:
        None

    Returns:
        None

    Raises:

    Note:

    """
    print("记录目录:", csv_dir_get())
    acc_g_arr = [(0.001 * i, -0.002 * i, 0.003 * i) for i in range(INC_SAMPLE_NUM)]
    gyr_dps_arr = [(1.0 * i, -1.0 * i, 0.5 * i) for i in range(INC_SAMPLE_NUM)]
    print("打开记录:", csv_open(), "->", csv_file_name_get())
    n1 = csv_write_frame(1, acc_g_arr, gyr_dps_arr, 21.664, -849, 2, 2000, 1013290, 10.0, 1)
    n2 = csv_write_frame(2, acc_g_arr, gyr_dps_arr, 21.664, -849, 2, 2000, 1013300, 10.0, 1)
    print("两帧写入行数:", n1, n2)
    time.sleep(0.5)
    print("状态:", csv_state_text_get())
    print("关闭:", csv_close())
    print("状态:", csv_state_text_get())
    try:
        with open(csv_file_path, encoding='utf-8-sig') as file_handle:
            lines = file_handle.readlines()
        print("文件总行数:", len(lines))
        for line in lines[:4]:
            print("   ", line.strip())
        print("   ...")
        print("   ", lines[-1].strip())
    except Exception as exc:
        print("读取文件失败:", exc)


if __name__ == '__main__':
    main()
