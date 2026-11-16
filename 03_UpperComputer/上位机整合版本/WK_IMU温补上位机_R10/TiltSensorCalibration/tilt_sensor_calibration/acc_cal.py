"""加速度计校准等等"""
import os
import shutil
import time
from datetime import *
import numpy
import math
from qt_dialogs import filedialog, messagebox
import threading
import openpyxl
from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill


import sys
sys.path.append(sys.path[0] + '\\tilt_sensor')
sys.path.append(sys.path[0] + '\\turntable')
sys.path.append(sys.path[0] + '\\ellipsoid')
sys.path.append(sys.path[0] + '\\lm')
sys.path.append(sys.path[0] + '\\tilt_sensor_calibration')
sys.path.append(sys.path[0] + '\\temperature_chamber')
sys.path.append(sys.path[0] + '\\acc_tdc')
sys.path.append(sys.path[0] + '\\debug')
#from inc_comm import *
#from inc_cal import *
from turntable_2TD600_comm import *
from turntable_data_get import *
from ellipsoid_fitting import *
from lm_algorithm import *
from auto_run_state import *
from temperature_chamber_comm import *
from temperature_chamber_data_get import *
#from acc_tdc_process import *
from debug import *

#
# 数据结构定义
#

class TemperatureCtrl:
    """温度控制数据结构"""

    def __init__(self):
        self.tc_sp_str_arr = [] # 温箱温度设定值
        self.temperature_deviation = 0.5 # 温度偏差
        self.temperature_hit_count = 10 # 温度命中次数
        self.temperature_wait_time = 480 # 温度等待时间，单位分钟
        self.temperature_hold_time = 30 # 保温时间，单位分钟
        self.temperature_control_enable = False


class CalCtrl:
    """校准控制数据结构"""

    def __init__(self):
        self.cal_name = ""
        self.pos_gxyz_excel_file_directory_path = ""
        self.cal_result_excel_file_directory_path = ""
        self.turntable_positions = None
        self.cal_enable = False
        self.average_num = 1000
        self.aia_enable = True
        self.cal_data_upload_enable = True


class AccCalCtrl:
    """控制加速度计等等校准的数据结构"""

    def __init__(self):
        # 温控
        self.temperature_ctrl = TemperatureCtrl()

        # 校准控制
        self.cal_ctrl_of_acc_cal = CalCtrl()
        self.cal_ctrl_of_acc_cal.cal_name = "加速度计校准"
        self.cal_ctrl_of_total_acceleration_check = CalCtrl()
        self.cal_ctrl_of_total_acceleration_check.cal_name = "总加速度检验"

        # lm计算使能
        self.lm_calculate_enable = False

        # 加速度计温漂补偿计算使能
        self.acc_tdc_calcu_enable = False

        # 温度传感器补偿计算
        self.tps_comp_calcu_enable = False

        # 转台运行参数
        self.inner_axis_speed = 10
        self.outer_axis_speed = 10

        # 进度条
        self.progress_value_ellipsoid_fitting = 0 # 各步骤分配的进度值
        self.progress_value_lm_calculate = 0
        self.progress_value_total_acceleration_check = 0

        # 运行次数控制
        self.acc_cal_rerun_requst = False # 重新运行加速度计校准的请求
        self.run_num = 1 # 运行次数
        self.run_count = 0 # 运行计数器

        # 线程相关
        self.thread_instance = None
        self.terminate_thread_requst = False


accCalCtrl = AccCalCtrl()

#
# 生成转台运转位置
#

def ellipsoid_lm_fitting_turntable_positions_creat(position_num):
    """
    生成椭球/LM拟合转台运转的位置

    Args:
        position_num (int): 位置数

    Returns:
        ndarray: 转台运转的位置

    """
    if position_num <= 6:
        position_num = 6
        position_array = numpy.zeros((position_num, 2))  # 运转的目标位置
        position_array[0] = [0.0000, 360.0000]
        position_array[1] = [0.0000, 90.0000]
        position_array[2] = [0.0000, 270.0000]
        position_array[3] = [90.0000, 90.0000]
        position_array[4] = [270.0000, 90.0000]
        position_array[5] = [0.0000, 180.0000]
    else:
        position_num_sqrt = int(numpy.sqrt(position_num))
        position_num = position_num_sqrt * position_num_sqrt
        angle_interval = 360.0 / position_num_sqrt
        angle_inner = 0.0
        angle_outer = 0.0
        position_array = numpy.zeros((position_num, 2))  # 运转的目标位置
        for i in range(position_num):
            position_array[i] = [angle_inner, angle_outer]
            angle_outer += angle_interval
            if angle_outer >= 360.0:
                angle_outer = 0.0
                angle_inner += angle_interval

    return position_array


def total_acceleration_check_turntable_positions_creat():
    """
    生成总加速度检验转台运转的位置

    Args:
        None

    Returns:
        ndarray: 转台运转的位置

    """
    try:
        acc_cal_position_num, x = accCalCtrl.cal_ctrl_of_acc_cal.turntable_positions.shape
    except:
        acc_cal_position_num = 64

    if acc_cal_position_num == 64:
        position_num = 16
        position_array = numpy.zeros((position_num, 2))  # 运转的目标位置
        position_array[0] = [0.0, 22.0]
        position_array[1] = [0.0, 72.0]
        position_array[2] = [0.0, 144.0]
        position_array[3] = [0.0, 288.0]
        position_array[4] = [60.0, 22.0]
        position_array[5] = [60.0, 72.0]
        position_array[6] = [60.0, 144.0]
        position_array[7] = [60.0, 288.0]
        position_array[8] = [120.0, 22.0]
        position_array[9] = [120.0, 72.0]
        position_array[10] = [120.0, 144.0]
        position_array[11] = [120.0, 288.0]
        position_array[12] = [240.0, 22.0]
        position_array[13] = [240.0, 72.0]
        position_array[14] = [240.0, 144.0]
        position_array[15] = [240.0, 288.0]
    else:
        position_num = 6
        position_array = numpy.zeros((position_num, 2))  # 运转的目标位置
        position_array[0] = [108.0, 36.0]
        position_array[1] = [108.0, 180.0]
        position_array[2] = [108.0, 324.0]
        position_array[3] = [252.0, 36.0]
        position_array[4] = [252.0, 180.0]
        position_array[5] = [252.0, 324.0]

    return position_array


def turntable_run_and_data_record(positions, acc_data_excel_file_directory_path, temperature_str):
    """
    控制转台运转至目标位置并记录当前位置下的加速度值至excel文件

    Args:
        positions (ndarray): 运转的位置
        acc_data_excel_file_directory_path (str): 加速度数据excel文件所在的目录路径
        temperature_str (string): 温度值(包含℃等字符)

    Returns:
        int: 0  - 转台运转和数据记录成功
             -1 - 外部请求中止自动运行线程
             -2 - 转台内轴通讯失败
             -3 - 转台外轴通讯失败
             1  - excel文件操作失败

    """
    is_error = False
    # 控制转台转动至指定位置
    inner_axis_speed = accCalCtrl.inner_axis_speed
    outer_axis_speed = accCalCtrl.outer_axis_speed
    # 不再施加统一 ±10°/s 软件限速；仅拒绝零值、NaN/Inf 等无效速度。
    from motion_speed_guard import target_speed_allowed
    if not target_speed_allowed(inner_axis_speed) or not target_speed_allowed(outer_axis_speed):
        messagebox.showerror("转台参数无效", "自动运行的轴速度必须为非零有限数值。")
        return -1
    position_num, position_dim = positions.shape
    for pos_index in range(position_num):
        if terminate_thread_requst_check():
            return -1
        inner_axis_pos_to_run, outer_axis_pos_to_run = positions[pos_index]
        # 内轴旋转至指定位置
        if turntableComm.turntable_model == "2TD600":
            ret = True
            n = 5
            for try_count in range(n):  # 尝试多次设置，提高成功率！！！
                turntableComm.thread_lock.acquire()
                ret = twoTD600_SetAxisPosition(INNER_ROTATION_AXIS, inner_axis_pos_to_run, inner_axis_speed)
                turntableComm.thread_lock.release()
                if not ret:
                    time.sleep(1)  # 等待1秒，重新设置
                else:
                    break
            if not ret:
                messagebox.showerror("", "内轴通讯失败！")
                return -2
        elif turntableComm.turntable_model == "2FDT600WK":
            comm_error_code = [0]
            ret = True
            n = 5
            for try_count in range(n):  # 尝试多次设置，提高成功率！！！
                turntableComm.thread_lock.acquire()
                ret = twoFDT600WK_SetAxisPosition(INNER_ROTATION_AXIS, inner_axis_pos_to_run, inner_axis_speed, comm_error_code)
                turntableComm.thread_lock.release()
                if not ret:
                    time.sleep(1)  # 等待1秒，重新设置
                else:
                    break
            if not ret:
                messagebox.showerror("", "内轴通讯失败！" + "错误码 = " + str(comm_error_code[0]))
                return -2
        if terminate_thread_requst_check():
            return -1
        time.sleep(0.1)  # 等待100ms
        if terminate_thread_requst_check():
            return -1
        # 外轴旋转至指定位置
        if turntableComm.turntable_model == "2TD600":
            ret = True
            n = 5
            for try_count in range(n):  # 尝试多次设置，提高成功率！！！
                turntableComm.thread_lock.acquire()
                ret = twoTD600_SetAxisPosition(OUTER_ROTATION_AXIS, outer_axis_pos_to_run, outer_axis_speed)
                turntableComm.thread_lock.release()
                if not ret:
                    time.sleep(1)  # 等待1秒，重新设置
                else:
                    break
            if not ret:
                messagebox.showerror("", "外轴运转失败！")
                return -3
        elif turntableComm.turntable_model == "2FDT600WK":
            comm_error_code = [0]
            ret = True
            n = 5
            for try_count in range(n):  # 尝试多次设置，提高成功率！！！
                turntableComm.thread_lock.acquire()
                ret = twoFDT600WK_SetAxisPosition(OUTER_ROTATION_AXIS, outer_axis_pos_to_run, outer_axis_speed, comm_error_code)
                turntableComm.thread_lock.release()
                if not ret:
                    time.sleep(1)  # 等待1秒，重新设置
                else:
                    break
            if not ret:
                messagebox.showerror("", "外轴运转失败！" + "错误码 = " + str(comm_error_code[0]))
                return -3
        if terminate_thread_requst_check():
            return -1
        time.sleep(1)  # 等待1s
        if terminate_thread_requst_check():
            return -1
        # 等待内外轴到位
        while True:
            if terminate_thread_requst_check():
                return -1
            if OFFLINE_DEBUG:
                is_inner_axis_in_place = True
                is_outer_axis_in_place = True
            else:
                is_inner_axis_in_place = turntableState.is_inner_axis_in_place
                is_outer_axis_in_place = turntableState.is_outer_axis_in_place
            if is_inner_axis_in_place and is_outer_axis_in_place:
                break
        # 内外轴到位后，等待适当的时间后记录加速度值至excel文件
        if is_inner_axis_in_place and is_outer_axis_in_place:
            # 等待适当的时间，让加速度数据获取完成
            time_start = time.time()
            average_num_aia = incPara.average_num_aia
            time1_ms = average_num_aia * 16 * 3  # 每个加速度计板平均算法处理数据的时间
            time2_ms = 10 * INC_ARRAY_SEGMENT_NUM_MAX  # RS485通讯板读取8个加速度计板数据的时间
            time3_ms = 43 * incPara.array_num  # PC与所有阵列通讯的时间
            time_total_ms = time1_ms + time2_ms + time3_ms + 1000  # 额外加1s，保险一些！
            time_total_sec = time_total_ms / 1000.0
            while (time.time() - time_start) <= time_total_sec:  # 内外轴到位后等待适当时间后再记录加速度值
                if terminate_thread_requst_check():
                    return -1
            if not incPara.aia_enable: # NoAIA处理
                incRawData.queue_clear_requst = True
                while incRawData.queue_clear_requst:
                    if terminate_thread_requst_check():
                        return -1
                while not incRawData.inc_array_data_is_available:
                    if terminate_thread_requst_check():
                        return -1
            # 把加速度数据等写入相应的位置-原始加速度值excel文件
            for inc_segment_index_comm_cuccessful in incSegmentIndexCommSuccessfulArr:
                inc_segment_index_of_max_segment_num = inc_segment_index_comm_cuccessful.inc_segment_index_of_max_segment_num
                inc_segment_index = inc_segment_index_comm_cuccessful.inc_segment_index
                if terminate_thread_requst_check():
                    return -1
                sn = incPara.segment_sn_arr[inc_segment_index_of_max_segment_num]
                excel_file_name = sn + "_pos_gxyz" + ".xlsx"
                excel_file_path = os.path.join(acc_data_excel_file_directory_path, excel_file_name)
                try:
                    excel_work_book = openpyxl.load_workbook(excel_file_path)
                    excel_sheet_name = temperature_str
                    sheet = excel_work_book[excel_sheet_name]
                    list_temp = []
                    list_temp.append(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                    list_temp.append(str(turntableData.inner_axis_position) + "/" + str(turntableData.outer_axis_position))
                    list_temp.append(str(round(incGValue.inc_accelerometer_g_value_arr[inc_segment_index_of_max_segment_num].gx, 8)))
                    list_temp.append(str(round(incGValue.inc_accelerometer_g_value_arr[inc_segment_index_of_max_segment_num].gy, 8)))
                    list_temp.append(str(round(incGValue.inc_accelerometer_g_value_arr[inc_segment_index_of_max_segment_num].gz, 8)))
                    list_temp.append(str(tcData.pv))
                    list_temp.append(str(round(incGValueNewCalcuCtrl.inc_accelerometer_temperature_arr[inc_segment_index], 1)))
                    if incGValue.inc_accelerometer_g_value_error_flag_arr[inc_segment_index_of_max_segment_num]:
                        list_temp.append("无效")
                    else:
                        list_temp.append("有效")
                    list_temp.append(str(round(incGValueNewCalcuCtrl.inc_accelerometer_temperature_data_arr[inc_segment_index], 3)))
                    for i in range(len(list_temp)):
                        row = pos_index + 2 # 第2行开始是数据
                        col = i + 1
                        sheet.cell(row, col).value = list_temp[i]
                    excel_work_book.save(excel_file_path)
                    excel_work_book.close()
                except:
                    is_error = True

        autoRunState.progress_bar_value += 1  # 进度加1

    if is_error:
        return 1

    return 0


#
# 各个校准处理
#

def ellipsoidal_fitting_process(acc_data_excel_file_path):
    """
    1、对指定加速度数据excel文件进行椭球拟合，然后把椭球拟合结果写入excel文件并存入当前目录和exe目录的calibration目录
    2、汇总椭球拟合结果excel文件的各张表的数据

    Args:
        acc_data_excel_file_path (str): 加速度数据excel文件路径

    Returns:
        int: 0  - 椭球拟合成功
             -1 - excel文件操作失败
             -2 - 位置-原始加速度值excel文件无效
             -3 - 椭球拟合失败
             -4 - 拷贝至exe//calibration出错
    """
    error_code = 0

    ret = pos_gxyz_excel_file_check("acc_cal", acc_data_excel_file_path)
    if ret < 0:
        return -2

    # 在当前目录下创建椭球拟合结果excel文件(如果文件已存在，则覆盖之！)
    ellipsoid_result_excel_file_directory = os.path.dirname(acc_data_excel_file_path)
    sn = os.path.basename(acc_data_excel_file_path).split('_')[0]
    ellipsoid_result_excel_file_name = sn + "_ellipsoid_" + "result" + ".xlsx"
    ellipsoid_result_excel_file_path = os.path.join(ellipsoid_result_excel_file_directory, ellipsoid_result_excel_file_name)
    try:
        excel_work_book = openpyxl.Workbook()  # 覆盖原文件
        for excel_sheet in excel_work_book.worksheets:  # 删除默认表
            excel_work_book.remove_sheet(excel_sheet)
        acc_data_excel_work_book = openpyxl.load_workbook(acc_data_excel_file_path) # 获取加速度数据excel文件的所有表名
        acc_data_excel_sheet_names = acc_data_excel_work_book.sheetnames
        acc_data_excel_work_book.close()
        excel_sheet_index = 0
        for excel_sheet_name in acc_data_excel_sheet_names:
            excel_work_book.create_sheet(index=excel_sheet_index, title=excel_sheet_name)
            if excel_sheet_name != "info":
                sheet = excel_work_book[excel_sheet_name]
                list_temp = ["X0", "Y0", "Z0", "A", "B", "C"]
                sheet.append(list_temp)  # 添加表头
            excel_sheet_index += 1
        excel_work_book.save(ellipsoid_result_excel_file_path)
        excel_work_book.close()
    except:
        return -1

    # 打开加速度数据excel文件、椭球拟合或LM结果excel文件
    try:
        acc_data_excel_work_book = openpyxl.load_workbook(acc_data_excel_file_path)
    except:
        return -1
    try:
        ellipsoid_result_excel_work_book = openpyxl.load_workbook(ellipsoid_result_excel_file_path)
    except:
        acc_data_excel_work_book.close()
        return -1

    # 读取加速度数据excel文件的每张表的加速度数据，进行椭球拟合，把椭球拟合结果写入椭球拟合结果excel文件
    for excel_sheet_name in acc_data_excel_work_book.sheetnames:
        # 不处理info表！！！
        if excel_sheet_name == "info":
            continue
        # 读取每张表的加速度数据
        try:
            sheet = acc_data_excel_work_book[excel_sheet_name]
            ndarray = numpy.zeros((sheet.max_row - 1, 3))
            for row in range(2, sheet.max_row + 1, 1):  # 注意：行列下标都是从1开始！
                ndarray[row - 2] = [sheet.cell(row, 3).value, sheet.cell(row, 4).value, sheet.cell(row, 5).value]
        except:
            error_code = -1
            continue
        # 椭球拟合
        result = ellipsoid_fitting(ndarray)
        if result == None:
            error_code = -3
            continue
        # 把椭球拟合结果写入当前目录下的椭球拟合结果excel文件
        try:
            sheet = ellipsoid_result_excel_work_book[excel_sheet_name]
            for i in range(6):       # 写入椭球拟合结果
                sheet.cell(2, i + 1).value = result[i]
            ellipsoid_result_excel_work_book.save(ellipsoid_result_excel_file_path)
        except:
            error_code = -1

    # 把加速度数据excel文件的info表的内容拷贝至当前目录下的椭球拟合结果excel文件
    try:
        row = 1
        col = 1
        for iter_row in acc_data_excel_work_book["info"].iter_rows():
            for cell in iter_row:
                ellipsoid_result_excel_work_book["info"].cell(row, col).value = cell.value
                col = col + 1
            row = row + 1
            col = 1
        ellipsoid_result_excel_work_book["info"].cell(2, 1).value = "椭球拟合结果"
        ellipsoid_result_excel_work_book.save(ellipsoid_result_excel_file_path)
    except:
        error_code = -1

    # 关闭加速度数据excel文件、椭球拟合结果excel文件
    acc_data_excel_work_book.close()
    ellipsoid_result_excel_work_book.save(ellipsoid_result_excel_file_path)
    ellipsoid_result_excel_work_book.close()

    # 汇总当前目录下的椭球拟合结果excel文件的各张表的数据
    try:
        ellipsoid_result_excel_work_book = openpyxl.load_workbook(ellipsoid_result_excel_file_path)
    except:
        error_code = -1
    try:
        if len(ellipsoid_result_excel_work_book.sheetnames) > 2: # 如果椭球拟合结果excel文件存在多个表，则进行结果汇总
            excel_sheet_name_stat = "汇总"
            ellipsoid_result_excel_sheet_index = len(ellipsoid_result_excel_work_book.sheetnames)
            ellipsoid_result_excel_work_book.create_sheet(index=ellipsoid_result_excel_sheet_index, title=excel_sheet_name_stat)
            sheet_stat = ellipsoid_result_excel_work_book[excel_sheet_name_stat]
            list_temp = ["X0", "Y0", "Z0", "A", "B", "C", "温度"]
            sheet_stat.append(list_temp)  # 添加表头
            for excel_sheet_name in ellipsoid_result_excel_work_book.sheetnames:
                if (excel_sheet_name != excel_sheet_name_stat) and (excel_sheet_name != "info"):
                    sheet = ellipsoid_result_excel_work_book[excel_sheet_name]
                    list_temp = [sheet.cell(2, 1).value,
                                 sheet.cell(2, 2).value,
                                 sheet.cell(2, 3).value,
                                 sheet.cell(2, 4).value,
                                 sheet.cell(2, 5).value,
                                 sheet.cell(2, 6).value,
                                 excel_sheet_name]
                    sheet_stat.append(list_temp)
            ellipsoid_result_excel_work_book.save(ellipsoid_result_excel_file_path)
        ellipsoid_result_excel_work_book.close()
    except:
        ellipsoid_result_excel_work_book.close()
        error_code = -1

    # 把当前目录下的椭球拟合结果excel文件拷贝至exe//calibration
    exe_path = os.path.dirname(os.path.realpath(sys.argv[0]))
    target_directory_path = os.path.join(exe_path, 'calibration')
    try:
        shutil.copy2(ellipsoid_result_excel_file_path, target_directory_path)
    except:
        return -4

    return error_code


def ellipsoid_result_qualified_check(ellipsoid_result_excel_file_path, total_acceleration_check_excel_file_path):
    """
    检验椭球结果excel文件里的椭球结果是否合格

    Args:
        ellipsoid_result_excel_file_path (str): 椭球结果excel文件路径
        total_acceleration_check_excel_file_path (str): 总加速度检验excel文件路径

    Returns:
        int: 0  - 检验成功
             -1 - excel文件操作失败
             -2 - 椭球结果excel文件无效
             -3 - 总加速度检验excel文件无效
             -4 - 拷贝至exe//calibration出错
             -5 - 椭球结果不合格
    """
    # 检查椭球结果excel文件
    ret = ellipsoid_result_excel_file_check(ellipsoid_result_excel_file_path)
    if ret != 0:
        return -2

    # 检查总加速度检验excel文件
    ret = total_acceleration_check_excel_file_check(total_acceleration_check_excel_file_path)
    if ret != 0:
        return -3

    # 打开椭球结果excel文件和总加速度检验excel文件
    try:
        ellipsoid_result_excel_work_book = openpyxl.load_workbook(ellipsoid_result_excel_file_path)
    except:
        return -1
    try:
        total_acceleration_check_excel_work_book = openpyxl.load_workbook(total_acceleration_check_excel_file_path)
    except:
        ellipsoid_result_excel_work_book.close()
        return -1
    # 设置每张表的椭球结果是否合格
    is_all_qualified = True
    try:
        for excel_sheet_name in ellipsoid_result_excel_work_book.sheetnames:
            # info表不用处理！！！
            if excel_sheet_name == "info" or excel_sheet_name == "汇总":
                continue
            x0 = 0
            y0 = 0
            z0 = 0
            a = 0
            b = 0
            c = 0
            is_qualified = True
            # 检查椭球结果是否为有效数字或空
            try:
                x0 = float(ellipsoid_result_excel_work_book[excel_sheet_name].cell(2, 1).value)
                y0 = float(ellipsoid_result_excel_work_book[excel_sheet_name].cell(2, 2).value)
                z0 = float(ellipsoid_result_excel_work_book[excel_sheet_name].cell(2, 3).value)
                a  = float(ellipsoid_result_excel_work_book[excel_sheet_name].cell(2, 4).value)
                b  = float(ellipsoid_result_excel_work_book[excel_sheet_name].cell(2, 5).value)
                c  = float(ellipsoid_result_excel_work_book[excel_sheet_name].cell(2, 6).value)
            except:
                is_qualified = False
            # 检查灵敏度是否在正常范围
            sensitivity_min = 0.9
            sensitivity_max = 1.2
            if (a < sensitivity_min) or (a > sensitivity_max):
                is_qualified = False
            if (b < sensitivity_min) or (b > sensitivity_max):
                is_qualified = False
            if (c < sensitivity_min) or (c > sensitivity_max):
                is_qualified = False
            # 检查总加速度是否合格
            try:
                for row in range(2, total_acceleration_check_excel_work_book[excel_sheet_name].max_row + 1, 1):
                    if total_acceleration_check_excel_work_book[excel_sheet_name].cell(row, 18).value == "不合格":
                        is_qualified = False
                        break
            except: # 总加速度检验excel文件里不包含对应表名，则维持原结果
                is_qualified = is_qualified
            if not is_qualified:
                ellipsoid_result_excel_work_book[excel_sheet_name].cell(2, 7).value = "不合格"
            else:
                ellipsoid_result_excel_work_book[excel_sheet_name].cell(2, 7).value = "合格"
            if not is_qualified:
                is_all_qualified = False
            ellipsoid_result_excel_work_book[excel_sheet_name].cell(1, 7).value = "是否合格"
            ellipsoid_result_excel_work_book.save(ellipsoid_result_excel_file_path)
    except:
        ellipsoid_result_excel_work_book.close()
        total_acceleration_check_excel_work_book.close()
        return -1

    ellipsoid_result_excel_work_book.save(ellipsoid_result_excel_file_path)
    ellipsoid_result_excel_work_book.close()
    total_acceleration_check_excel_work_book.close()

    # 把当前目录下的椭球拟合结果excel文件拷贝至exe//calibration
    exe_path = os.path.dirname(os.path.realpath(sys.argv[0]))
    target_directory_path = os.path.join(exe_path, 'calibration')
    try:
        shutil.copy2(ellipsoid_result_excel_file_path, target_directory_path)
    except:
        return -4

    if not is_all_qualified:
        return -5

    return 0


def lm_calculation_process(acc_data_excel_file_path, iterations, iteration_termination_condition, penalty_factor):
    """
    对指定加速度数据excel文件进行LM计算，然后把LM计算结果写入excel文件并存入当前目录和exe目录的calibration目录

    Args:
        acc_data_excel_file_path (str): 加速度数据excel文件路径
        iterations (int): 迭代次数
        iteration_termination_condition (float): 迭代终止条件
        penalty_factor (float): 惩罚因子

    Returns:
        bool: LM计算成功，返回True。LM计算错误，返回False。

    """
    # 在当前目录下创建LM计算结果excel文件(如果文件已存在，则覆盖之！)
    lm_result_excel_file_directory = os.path.dirname(acc_data_excel_file_path)
    sn = os.path.basename(acc_data_excel_file_path).split('_')[0]
    lm_result_excel_file_name = sn + "_lm_" + "result" + ".xlsx"
    lm_result_excel_file_path = lm_result_excel_file_directory + "/" + lm_result_excel_file_name
    lm_result_excel_work_book = openpyxl.Workbook()  # 如果文件已经存在，则重新创建并覆盖原文件！
    lm_result_excel_work_book.save(lm_result_excel_file_path)
    lm_result_excel_work_book.close()
    lm_result_excel_sheet_index = 0

    # 在exe目录的calibration目录下创建LM计算结果excel文件(如果文件已存在，则覆盖之！)
    exe_path = os.path.dirname(os.path.realpath(sys.argv[0]))
    lm_result_excel_file_directory = os.path.join(exe_path, 'calibration')
    sn = os.path.basename(acc_data_excel_file_path).split('_')[0]
    lm_result_excel_file_name = sn + "_lm_" + "result" + ".xlsx"
    lm_result_excel_file_path_on_exe = os.path.join(lm_result_excel_file_directory, lm_result_excel_file_name)
    lm_result_excel_work_book = openpyxl.Workbook()  # 如果文件已经存在，则重新创建并覆盖原文件！
    lm_result_excel_work_book.save(lm_result_excel_file_path_on_exe)
    lm_result_excel_work_book.close()
    lm_result_excel_sheet_index = 0

    # 读取加速度数据excel文件的每个表的加速度数据，然后进行LM计算
    acc_data_excel_work_book = openpyxl.load_workbook(acc_data_excel_file_path)
    for excel_sheet_name in acc_data_excel_work_book.sheetnames:
        sheet = acc_data_excel_work_book[excel_sheet_name]
        ndarray = numpy.zeros((sheet.max_row - 1, 3))
        for row in range(2, sheet.max_row + 1, 1):  # 注意：行列下标都是从1开始！
            ndarray[row - 2] = [sheet.cell(row, 3).value, sheet.cell(row, 4).value, sheet.cell(row, 5).value]

        # 椭球拟合
        ellipsoid_result = ellipsoid_fitting(ndarray)
        if ellipsoid_result == None:
            acc_data_excel_work_book.close()
            return False

        # LM计算
        lm_result = lm(ndarray, iterations, iteration_termination_condition, penalty_factor, ellipsoid_result)
        if lm_result == None:
            acc_data_excel_work_book.close()
            return False

        # 把LM计算结果写入当前目录下的excel文件
        lm_result_excel_work_book = openpyxl.load_workbook(lm_result_excel_file_path)
        lm_result_excel_work_book.create_sheet(index=lm_result_excel_sheet_index, title=excel_sheet_name)
        sheet = lm_result_excel_work_book[excel_sheet_name]
        list_temp = ["T1", "T2", "T3", "S1", "S2", "S3", "B1", "B2", "B3"]
        sheet.append(list_temp)  # 添加表头
        for i in range(9):       # 写入LM计算结果
            sheet.cell(2, i + 1).value = lm_result[i]
        lm_result_excel_work_book.save(lm_result_excel_file_path)
        lm_result_excel_work_book.close()

        # 把LM计算结果写入exe目录的calibration目录下的excel文件
        lm_result_excel_work_book = openpyxl.load_workbook(lm_result_excel_file_path_on_exe)
        lm_result_excel_work_book.create_sheet(index=lm_result_excel_sheet_index, title=excel_sheet_name)
        sheet = lm_result_excel_work_book[excel_sheet_name]
        list_temp = ["T1", "T2", "T3", "S1", "S2", "S3", "B1", "B2", "B3"]
        sheet.append(list_temp)  # 添加表头
        for i in range(9):       # 写入LM计算结果
            sheet.cell(2, i + 1).value = lm_result[i]
        lm_result_excel_work_book.save(lm_result_excel_file_path_on_exe)
        lm_result_excel_work_book.close()

        lm_result_excel_sheet_index += 1

    acc_data_excel_work_book.close()
    return True


def total_acceleration_check(acc_data_excel_file_path, ellipsoid_or_lm_result_excel_file_path):
    """
    根据椭球拟合或LM结果excel文件，对指定加速度数据excel文件进行总加速度检验，然后把总加速度检验结果写入excel文件并存入当前文件夹

    Args:
        acc_data_excel_file_path (str): 加速度数据excel文件路径
        ellipsoid_or_lm_result_excel_file_path (str): 椭球拟合或LM结果excel文件

    Returns:
        int: 0  - 总加速度检验成功
             -1 - excel文件操作失败
             -2 - 位置-原始加速度值excel文件无效
             -3 - 椭球拟合结果文件无效
             -4 - 拷贝至exe//calibration出错
             -5 - 总加速度不合格
    """
    error_code = 0
    qualified = True

    # 检查位置-原始加速度值excel文件是否有效
    ret = pos_gxyz_excel_file_check("total_acceleration_check", acc_data_excel_file_path)
    if ret != 0:
        return -2

    # 判断是椭球拟合结果文件还是LM结果文件
    ellipsoid_or_lm_result_excel_file_type = "ellipsoid"
    ellipsoid_or_lm_result_excel_file_name = os.path.basename(ellipsoid_or_lm_result_excel_file_path)
    if "ellipsoid" in ellipsoid_or_lm_result_excel_file_name:
        ellipsoid_or_lm_result_excel_file_type = "ellipsoid"
    elif "lm" in ellipsoid_or_lm_result_excel_file_name:
        ellipsoid_or_lm_result_excel_file_type = "lm"

    # 检查椭球拟合结果文件是否有效
    if ellipsoid_or_lm_result_excel_file_type == "ellipsoid":
        ret = ellipsoid_result_excel_file_check(ellipsoid_or_lm_result_excel_file_path)
        if ret != 0:
            return -3

    # 创建总加速度检验文件
    try:
        acc_data_excel_work_book = openpyxl.load_workbook(acc_data_excel_file_path)
        acc_data_excel_sheet_names = acc_data_excel_work_book.sheetnames
        acc_data_excel_work_book.close()
        acc_data_excel_file_directory = os.path.dirname(acc_data_excel_file_path)
        sn = os.path.basename(acc_data_excel_file_path).split('_')[0]
        total_acceleration_check_excel_file_name = sn + "_total_acceleration_check" + ".xlsx"
        total_acceleration_check_excel_file_path = os.path.join(acc_data_excel_file_directory, total_acceleration_check_excel_file_name)
        excel_work_book = openpyxl.Workbook()  # 覆盖原验证文件
        for excel_sheet in excel_work_book.worksheets:  # 删除默认表
            excel_work_book.remove_sheet(excel_sheet)
        excel_sheet_index = 0
        for excel_sheet_name in acc_data_excel_sheet_names:
            excel_work_book.create_sheet(index=excel_sheet_index, title=excel_sheet_name)
            if excel_sheet_name != "info":
                sheet = excel_work_book[excel_sheet_name]
                list_temp = ["TimeStamp", "Pos", "",
                             "GX", "GX_New", "", "GY", "GY_New", "", "GZ", "GZ_New", "",
                             "TotalAcc", "TotalAcc_New", "", "TotalAcc_New-1G", "", "是否合格"]
                sheet.append(list_temp)  # 添加表头
            excel_sheet_index += 1
        excel_work_book.save(total_acceleration_check_excel_file_path)
        excel_work_book.close()
    except:
        return -1

    # 打开加速度数据excel文件、椭球拟合或LM结果excel文件、总加速度检验excel文件
    try:
        acc_data_excel_work_book = openpyxl.load_workbook(acc_data_excel_file_path)
    except:
        return -1
    try:
        ellipsoid_or_lm_result_excel_work_book = openpyxl.load_workbook(ellipsoid_or_lm_result_excel_file_path)
    except:
        acc_data_excel_work_book.close()
        return -1
    try:
        total_acceleration_check_excel_work_book = openpyxl.load_workbook(total_acceleration_check_excel_file_path)
    except:
        acc_data_excel_work_book.close()
        ellipsoid_or_lm_result_excel_work_book.close()
        return -1

    # 逐行读取加速度数据excel文件每张表的加速度值、根据椭球拟合或LM结果计算新的加速度值、计算总加速度值并写入验证文件
    for excel_sheet_name in acc_data_excel_work_book.sheetnames:
        if excel_sheet_name == "info":
            break
        # 从椭球拟合或LM结果excel文件读取椭球拟合或LM结果
        try:
            ellipsoid_or_lm_result_excel_sheet = ellipsoid_or_lm_result_excel_work_book[excel_sheet_name]
        except:
            acc_data_excel_work_book.close()
            ellipsoid_or_lm_result_excel_work_book.close()
            total_acceleration_check_excel_work_book.close()
            return -1
        ellipsoid_result = [0, 0, 0, 0, 0, 0]
        lm_result = [0, 0, 0, 0, 0, 0, 0, 0, 0]
        if ellipsoid_or_lm_result_excel_file_type == "ellipsoid":
            try:
                ellipsoid_result = [float(ellipsoid_or_lm_result_excel_sheet.cell(2, 1).value),
                                    float(ellipsoid_or_lm_result_excel_sheet.cell(2, 2).value),
                                    float(ellipsoid_or_lm_result_excel_sheet.cell(2, 3).value),
                                    float(ellipsoid_or_lm_result_excel_sheet.cell(2, 4).value),
                                    float(ellipsoid_or_lm_result_excel_sheet.cell(2, 5).value),
                                    float(ellipsoid_or_lm_result_excel_sheet.cell(2, 6).value)]
            except:
                acc_data_excel_work_book.close()
                ellipsoid_or_lm_result_excel_work_book.close()
                total_acceleration_check_excel_work_book.close()
                return -3
        elif ellipsoid_or_lm_result_excel_file_type == "lm":
            try:
                lm_result = [float(ellipsoid_or_lm_result_excel_sheet.cell(2, 1).value),
                             float(ellipsoid_or_lm_result_excel_sheet.cell(2, 2).value),
                             float(ellipsoid_or_lm_result_excel_sheet.cell(2, 3).value),
                             float(ellipsoid_or_lm_result_excel_sheet.cell(2, 4).value),
                             float(ellipsoid_or_lm_result_excel_sheet.cell(2, 5).value),
                             float(ellipsoid_or_lm_result_excel_sheet.cell(2, 6).value),
                             float(ellipsoid_or_lm_result_excel_sheet.cell(2, 7).value),
                             float(ellipsoid_or_lm_result_excel_sheet.cell(2, 8).value),
                             float(ellipsoid_or_lm_result_excel_sheet.cell(2, 9).value)]
            except:
                acc_data_excel_work_book.close()
                ellipsoid_or_lm_result_excel_work_book.close()
                total_acceleration_check_excel_work_book.close()
                return -3

        # 获取总加速度检验excel文件的表
        try:
            total_acceleration_check_excel_sheet = total_acceleration_check_excel_work_book[excel_sheet_name]
        except:
            acc_data_excel_work_book.close()
            ellipsoid_or_lm_result_excel_work_book.close()
            total_acceleration_check_excel_work_book.close()
            return -1

        # 逐行读取加速度数据excel文件每张表的加速度值
        try:
            acc_data_excel_sheet = acc_data_excel_work_book[excel_sheet_name]
        except:
            acc_data_excel_work_book.close()
            ellipsoid_or_lm_result_excel_work_book.close()
            total_acceleration_check_excel_work_book.close()
            return -1
        acc_data_etc = ["", "", 0.0, 0.0, 0.0]
        for row in range(2, acc_data_excel_sheet.max_row + 1, 1):  # 注意：行列下标都是从1开始！
            try:
                acc_data_etc = [acc_data_excel_sheet.cell(row, 1).value,
                                acc_data_excel_sheet.cell(row, 2).value,
                                float(acc_data_excel_sheet.cell(row, 3).value),
                                float(acc_data_excel_sheet.cell(row, 4).value),
                                float(acc_data_excel_sheet.cell(row, 5).value)]
            except:
                acc_data_excel_work_book.close()
                ellipsoid_or_lm_result_excel_work_book.close()
                total_acceleration_check_excel_work_book.close()
                return -2
            gx = acc_data_etc[2]
            gy = acc_data_etc[3]
            gz = acc_data_etc[4]
            gx_new = 0.0
            gy_new = 0.0
            gz_new = 0.0
            if ellipsoid_or_lm_result_excel_file_type == "ellipsoid":
                X0 = ellipsoid_result[0]
                Y0 = ellipsoid_result[1]
                Z0 = ellipsoid_result[2]
                A = ellipsoid_result[3]
                B = ellipsoid_result[4]
                C = ellipsoid_result[5]
                gx_new = (gx - X0) / A
                gy_new = (gy - Y0) / B
                gz_new = (gz - Z0) / C
            elif ellipsoid_or_lm_result_excel_file_type == "lm":
                T1 = lm_result[0]
                T2 = lm_result[1]
                T3 = lm_result[2]
                S1 = lm_result[3]
                S2 = lm_result[4]
                S3 = lm_result[5]
                B1 = lm_result[6]
                B2 = lm_result[7]
                B3 = lm_result[8]
                gx_new = S1 * (gx + B1) + T3 * S2 * (gy + B2) - T2 * S3 * (gz + B3)
                gy_new = S2 * (gy + B2) + T1 * S3 * (gz + B3) - T3 * S1 * (gx + B1)
                gz_new = S3 * (gz + B3) + T2 * S1 * (gx + B1) - T1 * S2 * (gy + B2)
            total_acc_new = numpy.sqrt(gx_new * gx_new + gy_new * gy_new + gz_new * gz_new)
            total_acc_old = numpy.sqrt(gx * gx + gy * gy + gz * gz)
            total_acc_new_diff_from_1 = numpy.abs(total_acc_new - 1)
            total_acc_min = 0.99 # 总加速度范围
            total_acc_max = 1.01
            if (total_acc_new < total_acc_min) or (total_acc_new > total_acc_max):
                is_qualified = "不合格"
                qualified = False
            else:
                is_qualified = "" # 合格的不提示，方便一眼看出不合格！！！
            list_temp = [acc_data_etc[0], acc_data_etc[1], "", gx, gx_new, "", gy, gy_new, "", gz, gz_new, "",
                         total_acc_old, total_acc_new, "", total_acc_new_diff_from_1, "", is_qualified]
            total_acceleration_check_excel_sheet.append(list_temp)

    # 把加速度数据excel文件的info表的内容拷贝至当前目录下的总加速度检验excel文件
    try:
        row = 1
        col = 1
        for iter_row in acc_data_excel_work_book["info"].iter_rows():
            for cell in iter_row:
                total_acceleration_check_excel_work_book["info"].cell(row, col).value = cell.value
                col = col + 1
            row = row + 1
            col = 1
        total_acceleration_check_excel_work_book["info"].cell(2, 1).value = "总加速度检验结果"
        total_acceleration_check_excel_work_book.save(total_acceleration_check_excel_file_path)
    except:
        error_code = -1

    # 关闭所有excel
    acc_data_excel_work_book.close()
    ellipsoid_or_lm_result_excel_work_book.close()
    total_acceleration_check_excel_work_book.save(total_acceleration_check_excel_file_path)
    total_acceleration_check_excel_work_book.close()

    # 把当前目录下的总加速度检验excel文件拷贝至exe//calibration
    exe_path = os.path.dirname(os.path.realpath(sys.argv[0]))
    target_directory_path = os.path.join(exe_path, 'calibration')
    try:
        shutil.copy2(total_acceleration_check_excel_file_path, target_directory_path)
    except:
        return -4

    if not qualified:
        return -5

    return error_code


#
# excel文件校验
#

def pos_gxyz_excel_file_check(cal_type, pos_gxyz_excel_file_path):
    """
    检查位置-原始加速度值excel文件是否有效

    Args:
        cal_type (str): 校准类别
        pos_gxyz_excel_file_path (str): 位置-原始加速度值excel文件文件路径

    Returns:
        int: 0  - 位置-原始加速度值excel文件有效
             -1 - excel文件操作出错
             -2 - info表的文件类别不正确
             -3 - 行数不正确
             -4 - Pos栏不正确
             -5 - 原始加速度值不正确
             -6 - 表名不一致
             -7 - 温箱pv值与sp值不一致
             -8 - 温度传感器测量值与sp值不一致
    """
    # 打开位置-原始加速度数据excel文件
    try:
        acc_data_excel_work_book = openpyxl.load_workbook(pos_gxyz_excel_file_path)
    except:
        return -1

    # 根据校准类别，检查info表的文件类别
    try:
        file_type_in_excel = acc_data_excel_work_book["info"].cell(2, 1).value
        file_type = "xx"
        if cal_type == "acc_cal":
            file_type = "位置-原始加速度值(加速度计校准)"
        elif cal_type == "total_acceleration_check":
            file_type = "位置-原始加速度值(总加速度检验)"
        elif cal_type == "acc_turntable_misalign_cal":
            file_type = "位置-原始加速度值(加速度计与转台安装误差校准)"
        elif cal_type == "acc_calibration_angle_check":
            file_type = "位置-原始加速度值(加速度计校准角度检验)"
        elif cal_type == "acc_temperature_drift_verify":
            file_type = "位置-原始加速度值(加速度计温漂验证)"
        if (file_type_in_excel != file_type):
            acc_data_excel_work_book.close()
            return -2
    except:
        acc_data_excel_work_book.close()
        return -1

    # 检查每张表的行数是否等于(转台位置数+1)
    try:
        turntable_pos_num = int(acc_data_excel_work_book["info"].cell(2, 4).value)
        for excel_sheet_name in acc_data_excel_work_book.sheetnames:
            # info表不用处理！！！
            if excel_sheet_name == "info":
                continue
            if acc_data_excel_work_book[excel_sheet_name].max_row != (turntable_pos_num + 1):
                acc_data_excel_work_book.close()
                return -3
    except:
        acc_data_excel_work_book.close()
        return -1

    # 根据校准类别，检查每张表的Pos栏是否正确
    try:
        turntable_positions = None
        if cal_type == "acc_cal":
            position_num = int(acc_data_excel_work_book["info"].cell(2, 14).value)
            turntable_positions = ellipsoid_lm_fitting_turntable_positions_creat(position_num)
        elif cal_type == "total_acceleration_check":
            turntable_positions = total_acceleration_check_turntable_positions_creat()
        elif cal_type == "acc_turntable_misalign_cal":
            position_num = int(acc_data_excel_work_book["info"].cell(2, 14).value)
            inner_axis_init_position = float(acc_data_excel_work_book["info"].cell(2, 15).value[:-1])
            outer_axis_init_position = 0.0
            axis_step1 = int(acc_data_excel_work_book["info"].cell(2, 16).value)
            axis_step2 = int(acc_data_excel_work_book["info"].cell(2, 17).value)
            axis_step3 = int(acc_data_excel_work_book["info"].cell(2, 18).value)
            is_long_steel_pipe_misalign_cal = False
            if acc_data_excel_work_book["info"].cell(2, 19).value == "是":
                is_long_steel_pipe_misalign_cal = True
            is_single_axis_misalign_cal = False
            if acc_data_excel_work_book["info"].cell(2, 20).value == "是":
                is_single_axis_misalign_cal = True
            if not is_long_steel_pipe_misalign_cal:
                turntable_positions = acc_turntable_misailgn_cal_positions_creat(position_num, inner_axis_init_position, outer_axis_init_position, is_single_axis_misalign_cal, axis_step1, axis_step2, axis_step3)
            else:
                turntable_positions = long_steel_pipe_misailgn_cal_positions_creat(position_num, inner_axis_init_position, outer_axis_init_position, axis_step1, axis_step2, axis_step3)
        elif cal_type == "acc_calibration_angle_check":
            inner_axis_init_position = float(acc_data_excel_work_book["info"].cell(2, 14).value[:-1])
            angle_range = float(acc_data_excel_work_book["info"].cell(2, 15).value[:-1])
            angle_interval = float(acc_data_excel_work_book["info"].cell(2, 16).value[:-1])
            turntable_positions = acc_calibration_angle_check_turntable_positions_creat(inner_axis_init_position, angle_range, angle_interval)
        elif cal_type == "acc_temperature_drift_verify":
            turntable_positions = acc_temperature_drift_verify_turntable_positions_creat()
        for excel_sheet_name in acc_data_excel_work_book.sheetnames:
            # info表不用处理！！！
            if excel_sheet_name == "info":
                continue
            turntable_position_index = 0
            row_start = 2
            row_num = acc_data_excel_work_book[excel_sheet_name].max_row
            for row in range(row_start, row_num + 1, 1):  # 注意：行列下标都是从1开始！
                inner_axis_pos_to_run, outer_axis_pos_to_run = turntable_positions[turntable_position_index]
                inner_axis_pos_recorded = float(acc_data_excel_work_book[excel_sheet_name].cell(row, 2).value.split("/")[0])
                outer_axis_pos_recorded = float(acc_data_excel_work_book[excel_sheet_name].cell(row, 2).value.split("/")[1])
                pos_error_max = 0.005 # 误差允许范围
                if (inner_axis_pos_to_run >= 1.0) and (inner_axis_pos_to_run <= 359.000):
                    inner_axis_pos_diff = math.fabs(inner_axis_pos_to_run - inner_axis_pos_recorded)
                    if inner_axis_pos_diff > pos_error_max:
                        acc_data_excel_work_book.close()
                        return -4
                else: # 处理0.0度转台显示360.0度的问题！！！
                    if (math.fabs(math.fabs(inner_axis_pos_to_run - inner_axis_pos_recorded) - 360) > pos_error_max) and (math.fabs(inner_axis_pos_to_run - inner_axis_pos_recorded) > pos_error_max):
                        acc_data_excel_work_book.close()
                        return -4
                if (outer_axis_pos_to_run >= 1.0) and (outer_axis_pos_to_run <= 359.000):
                    outer_axis_pos_diff = math.fabs(outer_axis_pos_to_run - outer_axis_pos_recorded)
                    if outer_axis_pos_diff > pos_error_max:
                        acc_data_excel_work_book.close()
                        return -4
                else: # 处理0.0度转台显示360.0度的问题！！！
                    if (math.fabs(math.fabs(outer_axis_pos_to_run - outer_axis_pos_recorded) - 360) > pos_error_max) and (math.fabs(outer_axis_pos_to_run - outer_axis_pos_recorded) > pos_error_max):
                        acc_data_excel_work_book.close()
                        return -4
                turntable_position_index += 1
    except:
        acc_data_excel_work_book.close()
        return -1

    # 检查每张表的原始加速度值是否正常
    try:
        for excel_sheet_name in acc_data_excel_work_book.sheetnames:
            # info表不用处理！！！
            if excel_sheet_name == "info":
                continue
            row_start = 2
            row_num = acc_data_excel_work_book[excel_sheet_name].max_row
            for row in range(row_start, row_num + 1, 1):  # 注意：行列下标都是从1开始！
                if acc_data_excel_work_book[excel_sheet_name].cell(row, 8).value != "有效":
                    return -5
                gx = float(acc_data_excel_work_book[excel_sheet_name].cell(row, 3).value)
                gy = float(acc_data_excel_work_book[excel_sheet_name].cell(row, 4).value)
                gz = float(acc_data_excel_work_book[excel_sheet_name].cell(row, 5).value)
                g_error_max = 1.5
                if (math.fabs(gx) > g_error_max) or (math.fabs(gy) > g_error_max) or (math.fabs(gz) > g_error_max):
                    acc_data_excel_work_book.close()
                    return -5
    except:
        acc_data_excel_work_book.close()
        return -1

    # 检查温箱设定温度值是否与实际记录的温度值、温度传感器测量值一致
    try:
        if acc_data_excel_work_book["info"].cell(2, 6).value == "是":
            temperature_control_enable = True
        else:
            temperature_control_enable = False
        temperature_deviation = float(acc_data_excel_work_book["info"].cell(2, 8).value[:-1])
        if temperature_control_enable: # 温控使能后才需要检查
            tc_sp_str_arr = acc_data_excel_work_book["info"].cell(2, 7).value.split(",")
            i = 0
            for excel_sheet_name in acc_data_excel_work_book.sheetnames:
                # info表不用处理！！！
                if excel_sheet_name == "info":
                    continue
                # 检查表名是否一致
                if excel_sheet_name != tc_sp_str_arr[i]:
                    acc_data_excel_work_book.close()
                    return -6
                i += 1
                # 检查温箱设定温度值是否与实际记录的温度值一致
                tc_sp_str = excel_sheet_name.split("_")[0]
                tc_sp = float(tc_sp_str[:-1])
                row_start = 2
                row_num = acc_data_excel_work_book[excel_sheet_name].max_row
                for row in range(row_start, row_num + 1, 1):  # 注意：行列下标都是从1开始！
                    tc_pv = float(acc_data_excel_work_book[excel_sheet_name].cell(row, 6).value)
                    tps_value = float(acc_data_excel_work_book[excel_sheet_name].cell(row, 7).value)
                    temperature_error_max = 5.0 + temperature_deviation
                    if math.fabs(tc_pv - tc_sp) > temperature_error_max:
                        acc_data_excel_work_book.close()
                        return -7
                    # if math.fabs(tps_value - tc_sp) > temperature_error_max:
                    #     acc_data_excel_work_book.close()
                    #     return -8
    except:
        acc_data_excel_work_book.close()
        return -1

    # 关闭excel
    acc_data_excel_work_book.close()

    return 0


def ellipsoid_result_excel_file_check(ellipsoid_result_excel_file_path):
    """
    检查椭球结果excel文件是否有效

    Args:
        ellipsoid_result_excel_file_path (str): 椭球结果excel文件路径

    Returns:
        int: 0  - 椭球结果excel文件有效
             -1 - excel文件操作出错
             -2 - info表的文件类别不正确
             -3 - 椭球结果不合格

    """
    # 打开椭球结果excel文件
    try:
        ellipsoid_result_excel_work_book = openpyxl.load_workbook(ellipsoid_result_excel_file_path)
    except:
        return -1

    # 检查info表的文件类别是否为"椭球拟合结果"
    try:
        if ellipsoid_result_excel_work_book["info"].cell(2, 1).value != "椭球拟合结果":
            ellipsoid_result_excel_work_book.close()
            return -2
    except:
        ellipsoid_result_excel_work_book.close()
        return -1

    # 检查每张表的椭球结果是否为有效数字或空或0
    try:
        for excel_sheet_name in ellipsoid_result_excel_work_book.sheetnames:
            # info表不用处理！！！
            if excel_sheet_name == "info":
                continue
            try:
                x0 = float(ellipsoid_result_excel_work_book[excel_sheet_name].cell(2, 1).value)
                y0 = float(ellipsoid_result_excel_work_book[excel_sheet_name].cell(2, 2).value)
                z0 = float(ellipsoid_result_excel_work_book[excel_sheet_name].cell(2, 3).value)
                a  = float(ellipsoid_result_excel_work_book[excel_sheet_name].cell(2, 4).value)
                b  = float(ellipsoid_result_excel_work_book[excel_sheet_name].cell(2, 5).value)
                c  = float(ellipsoid_result_excel_work_book[excel_sheet_name].cell(2, 6).value)
            except:
                ellipsoid_result_excel_work_book.close()
                return -3
            if (a == 0) or (b == 0) or (c == 0):
                return -3
            if (abs(a) < 0.9) or (abs(a) > 1.2):
                return -3
            if (abs(b) < 0.9) or (abs(b) > 1.2):
                return -3
            if (abs(c) < 0.9) or (abs(c) > 1.2):
                return -3
            if ellipsoid_result_excel_work_book[excel_sheet_name].cell(2, 7).value == "不合格":
                ellipsoid_result_excel_work_book.close()
                return -3
    except:
        ellipsoid_result_excel_work_book.close()
        return -1

    # 关闭excel
    ellipsoid_result_excel_work_book.close()

    return 0


def total_acceleration_check_excel_file_check(total_acceleration_check_excel_file_path):
    """
    检查总加速度检验excel文件是否有效

    Args:
        total_acceleration_check_excel_file_path (str): 总加速度检验excel文件路径

    Returns:
        int: 0  - 总加速度检验excel文件有效
             -1 - excel文件操作出错
             -2 - info表的文件类别不正确
             -3 - 行数不正确
             -4 - 总加速度不正确
    """
    # 打开总加速度检验excel文件
    try:
        total_acceleration_check_excel_work_book = openpyxl.load_workbook(total_acceleration_check_excel_file_path)
    except:
        return -1

    # 检查info表的文件类别是否为"总加速度检验结果"
    try:
        if total_acceleration_check_excel_work_book["info"].cell(2, 1).value != "总加速度检验结果":
            total_acceleration_check_excel_work_book.close()
            return -2
    except:
        total_acceleration_check_excel_work_book.close()
        return -1

    # 检查每张表的行数是否等于(转台位置数+1)
    try:
        turntable_pos_num = int(total_acceleration_check_excel_work_book["info"].cell(2, 4).value)
        for excel_sheet_name in total_acceleration_check_excel_work_book.sheetnames:
            # info表不用处理！！！
            if excel_sheet_name == "info":
                continue
            if total_acceleration_check_excel_work_book[excel_sheet_name].max_row != (turntable_pos_num + 1):
                total_acceleration_check_excel_work_book.close()
                return -3
    except:
        total_acceleration_check_excel_work_book.close()
        return -1

    # 检查每张表的总加速度值是否为有效数字或空
    try:
        for excel_sheet_name in total_acceleration_check_excel_work_book.sheetnames:
            # info表不用处理！！！
            if excel_sheet_name == "info":
                continue
            row_start = 2
            row_num = total_acceleration_check_excel_work_book[excel_sheet_name].max_row
            try:
                for row in range(row_start, row_num + 1, 1):  # 注意：行列下标都是从1开始！
                    total_acceleration = float(total_acceleration_check_excel_work_book[excel_sheet_name].cell(row, 14).value)
            except:
                total_acceleration_check_excel_work_book.close()
                return -4
    except:
        total_acceleration_check_excel_work_book.close()
        return -1

    # 关闭excel
    total_acceleration_check_excel_work_book.close()

    return 0


#
# 温控
#

def tc_sps_creat(start_temperature, temperature_range1, temperature_range2, temperature_interval):
    """
    生成温漂校准各个温箱温度设定值

    Args:
        start_temperature (float): 起始温度
        temperature_range1 (float): 温度范围下限
        temperature_range2 (float): 温度范围上限
        temperature_interval (float): 温度间隔

    Returns:
        []: 温箱温度设定值集合

    """
    tc_sp_str_arr = []
    tc_sp_str_arr.append(str(start_temperature) + "℃" + "_起始")
    prev_temperature = start_temperature
    next_temperature = 0.0
    while True:  # start_temperature->temperature_range2升温
        next_temperature = prev_temperature + temperature_interval
        tc_sp_str_arr.append(str(next_temperature) + "℃" + "_升温")
        prev_temperature = next_temperature
        if next_temperature >= temperature_range2:
            break
    while True:  # temperature_range2->temperature_range1降温
        next_temperature = prev_temperature - temperature_interval
        tc_sp_str_arr.append(str(next_temperature) + "℃" + "_降温")
        prev_temperature = next_temperature
        if next_temperature <= temperature_range1:
            break
    while True:  # temperature_range1->start_temperature升温
        next_temperature = prev_temperature + temperature_interval
        tc_sp_str_arr.append(str(next_temperature) + "℃" + "_升温")
        prev_temperature = next_temperature
        if next_temperature >= start_temperature:
            break

    return tc_sp_str_arr

#
# 线程
#

def terminate_thread_requst_check():
    """
    检查是否有中止加速度计校准线程的请求

    Returns:
        bool: 有中止自动运行线程的请求，返回True。否则，返回False。

    """
    if accCalCtrl.terminate_thread_requst:
        accCalCtrl.terminate_thread_requst = False
        return True
    else:
        return False


def thread_of_acc_cal_terminate():
    """
    终止加速度计校准线程

    Args:

    Returns:

    Raises:

    Note:

    """
    # 请求终止加速度计校准线程
    tcComm.sp_set_and_wait_quit_requst = True
    accCalCtrl.terminate_thread_requst = True
    while True:
        if accCalCtrl.thread_instance == None:
            break
    accCalCtrl.terminate_thread_requst = False
    tcComm.sp_set_and_wait_quit_requst = False


def thread_of_acc_cal_create_and_start():
    """
    创建并启动加速度计校准线程

    Args:

    Returns:

    Raises:

    Note:

    """
    accCalCtrl.thread_instance = threading.Thread(target=thread_func_of_acc_cal)
    accCalCtrl.thread_instance.start()


def thread_func_of_acc_cal():
    """
        加速度计校准线程
    """
    def pos_gxyz_excel_file_valid_set(pos_gxyz_excel_file_path, sheet_name, row, is_valid):
        """
        设置位置-原始加速度值excel文件的某张表的某行数据是否有效

        Args:
            pos_gxyz_excel_file_path (str): 位置-原始加速度值excel文件路径
            sheet_name (str): 表名
            row (int): 行号
            is_valid (bool): True表示该行数据有效；False表示该行数据无效。

        Returns:
            int: 错误码，0表示设置成功，负数表示设置失败。

        Raises:

        Note:

        """
        # 打开位置-原始加速度数据excel文件
        try:
            acc_data_excel_work_book = openpyxl.load_workbook(pos_gxyz_excel_file_path)
        except:
            return -1

        # 设置相应行的数据是否有效
        try:
            if row == 0xffff: # row等于0xffff表示所有行
                row_num = int(acc_data_excel_work_book["info"].cell(2, 4).value)
                for row in range(2, row_num+2):
                    if is_valid:
                        acc_data_excel_work_book[sheet_name].cell(row, 8).value = "有效"
                    else:
                        acc_data_excel_work_book[sheet_name].cell(row, 8).value = "无效"
            else:
                if is_valid:
                    acc_data_excel_work_book[sheet_name].cell(row, 8).value = "有效"
                else:
                    acc_data_excel_work_book[sheet_name].cell(row, 8).value = "无效"
            acc_data_excel_work_book.save(pos_gxyz_excel_file_path)
        except:
            acc_data_excel_work_book.close()
            return -2

        acc_data_excel_work_book.close()

        return 0

    def array_average_num_aia_set_fail_handle(cal_ctrl_instance,
                                              tc_sp_str,
                                              array_index,
                                              mtp_error_code_pc,
                                              mtp_error_code_acc_arr):
        """
        校准项目对应的阵列内平均次数设置失败处理：
        1、把阵列对应节的位置-原始加速度值excel文件的数据设置为无效
        2、自动运行状态灯和信息栏给出相应提示

        Args:
            cal_ctrl_instance (class): CalCtrl类实例
            tc_sp_str (str): 温箱温度设定值
            array_index (int): 阵列索引(从0开始！)
            mtp_error_code_pc (int): PC与阵列的通讯错误码
            mtp_error_code_acc_arr (list): RS485通讯板与8个加速度计板的通讯错误码

        Returns:
            int: 错误码，0表示处理成功，负数表示处理失败。

        Raises:

        Note:

        """
        is_error = False
        # 确定待处理的节序列号
        segment_sn_failed_arr = []
        if mtp_error_code_pc != 0:
            for i in range(INC_ARRAY_SEGMENT_NUM_MAX):
                segment_index = array_index * INC_ARRAY_SEGMENT_NUM_MAX + i
                segment_sn_failed_arr.append(incPara.segment_sn_arr[segment_index])
        else:
            for i in range(INC_ARRAY_SEGMENT_NUM_MAX):
                if mtp_error_code_acc_arr[i] != 0:
                    segment_index = array_index * INC_ARRAY_SEGMENT_NUM_MAX + i
                    segment_sn_failed_arr.append(incPara.segment_sn_arr[segment_index])
        # 把节对应的位置-原始加速度值excel文件的数据设置为无效
        for segment_sn in segment_sn_failed_arr:
            pos_gxyz_excel_file_directory_path = cal_ctrl_instance.pos_gxyz_excel_file_directory_path
            pos_gxyz_excel_file_name = segment_sn + "_pos_gxyz" + ".xlsx"
            pos_gxyz_excel_file_path = os.path.join(pos_gxyz_excel_file_directory_path, pos_gxyz_excel_file_name)
            ret = pos_gxyz_excel_file_valid_set(pos_gxyz_excel_file_path, tc_sp_str, 0xffff, False)
            if ret != 0:
                is_error = True
                autoRunState.thread_lock.acquire()
                autoRunState.auto_run_state = "错误"
                autoRunState.auto_run_info += "(" + tc_sp_str + "-" + cal_ctrl_instance.cal_name + ")" + pos_gxyz_excel_file_path + "数据有效性设置失败! " + "返回值 = " + str(ret) + "\r\n"
                autoRunState.thread_lock.release()

        # 自动运行信息栏增加错误提示
        autoRunState.thread_lock.acquire()
        autoRunState.auto_run_state = "错误"
        comm_error_str = str(mtp_error_code_pc) + " "
        for i in range(INC_ARRAY_SEGMENT_NUM_MAX):
            comm_error_str += str(mtp_error_code_acc_arr[i]) + " "
        autoRunState.auto_run_info += "(" + tc_sp_str + cal_ctrl_instance.cal_name + ")" + "平均次数设置失败! " + "错误码 = " + comm_error_str + "(" + "阵列" + str(
            array_index + 1) + ")" + "\r\n"
        autoRunState.thread_lock.release()

        if is_error:
            return -1
        else:
            return 0

    def inc_average_num_aia_set(cal_ctrl_instance, tc_sp_str):
        """
            设置校准项目对应的测斜仪平均次数

        Args:
            cal_ctrl_instance (class): CalCtrl类实例
            tc_sp_str (str): 温箱sp值

        Returns:
            bool: 测斜仪平均次数设置成功，返回True; 设置失败，返回False

        Raises:

        Note:
        """
        is_error = False
        # 获取平均次数
        aia_enable = cal_ctrl_instance.aia_enable
        average_num = cal_ctrl_instance.average_num
        if not aia_enable:
            incPara.average_num = average_num
            incPara.average_num_aia = 1
            incPara.aia_enable = False
        else:
            incPara.average_num = 1
            incPara.average_num_aia = average_num
            incPara.aia_enable = True
        # 设置测斜仪所有阵列的平均次数
        average_num_aia = incPara.average_num_aia
        mtp_error_code_pc = [0]
        mtp_error_code_acc_arr = [0, 0, 0, 0, 0, 0, 0, 0]
        array_index_comm_prev = -1
        for inc_segment_index_comm_cuccessful in incSegmentIndexCommSuccessfulArr:
            array_index = inc_segment_index_comm_cuccessful.array_index
            if array_index == array_index_comm_prev:
                continue
            array_index_comm_prev = array_index
            array_comm_addr = incPara.array_comm_addr_arr[array_index]
            ret = True
            n = 5
            for try_count in range(n):  # 尝试多次设置，提高成功率！！！
                incComm.thread_lock.acquire()
                ret = inc_array_average_num_aia_set(incComm.comm_port,
                                                    array_comm_addr,
                                                    average_num_aia,
                                                    True,
                                                    mtp_error_code_pc,
                                                    mtp_error_code_acc_arr)
                incComm.thread_lock.release()
                if not ret:
                    time.sleep(1)  # 等待1秒，重新设置
                else:
                    break
            if not ret: # 阵列平均次数设置失败处理！！！
                error_code = array_average_num_aia_set_fail_handle(cal_ctrl_instance,
                                                                   tc_sp_str,
                                                                   array_index,
                                                                   mtp_error_code_pc[0],
                                                                   mtp_error_code_acc_arr)
                if error_code != 0:
                    is_error = True
            else:
                for segment_index in range(INC_ARRAY_SEGMENT_NUM_MAX):
                    if mtp_error_code_acc_arr[segment_index] != 0:
                        if segment_index == inc_segment_index_comm_cuccessful.array_segment_index:
                            error_code = array_average_num_aia_set_fail_handle(cal_ctrl_instance,
                                                                               tc_sp_str,
                                                                               array_index,
                                                                               mtp_error_code_pc[0],
                                                                               mtp_error_code_acc_arr)
                            if error_code != 0:
                                is_error = True

            if len(incSegmentIndexCommSuccessfulArr) > 1:
                t = inc_array_comm_recover_time_get(incPara.inc_model)
                time.sleep(t)

        if is_error:
            return False
        else:
            return True

    def running_error_handle():
        """
            运行错误处理

        Args:

        Returns:

        Raises:

        Note:
        """
        autoRunState.thread_lock.acquire()
        autoRunState.auto_run_state = "停止"
        autoRunState.thread_lock.release()
        autoRunState.progress_bar_value = 0
        accCalCtrl.thread_instance = None
        autoRunState.button_text_AccCalRun = "自动运行"

    def running_alarm_handle(tip):
        """
            运行报警处理

        Args:
            tip (str): 报警提示信息

        Returns:

        Raises:

        Note:
        """
        autoRunState.thread_lock.acquire()
        autoRunState.auto_run_state = "报警"
        autoRunState.auto_run_info += tip
        autoRunState.thread_lock.release()

    while True:
        # 中止线程请求处理
        if terminate_thread_requst_check():
            accCalCtrl.thread_instance = None
            autoRunState.progress_bar_value = 0
            return

        # 每个温度下，设置温箱温度，并等待温箱温度到达设定温度，然后控制转台运转至目标位置并记录当前位置下的加速度值至excel文件
        for tc_sp_str in accCalCtrl.temperature_ctrl.tc_sp_str_arr:
            tc_sp = float(tc_sp_str.split("℃")[0])

            # 设置温箱温度，并等待温箱温度到达设定温度
            if accCalCtrl.temperature_ctrl.temperature_control_enable:
                # 如果有零下温度，需要给测斜仪断电，温度到达后给测斜仪重新上电
                is_inc_power_off = False
                if ((tcData.pv <= 0.0) and (tc_sp >= 0.0)) or ((tcData.pv >= 0.0) and (tc_sp < 5.0)):
                    mtp_error_code = [0]
                    ret = True
                    n = 5
                    for try_count in range(n):  # 尝试多次设置，提高成功率！！！
                        incComm.thread_lock.acquire()
                        ret = cc_power_off(incComm.comm_port, mtp_error_code)  # 关闭通讯转换器电源输出
                        incComm.thread_lock.release()
                        if not ret:
                            time.sleep(1)  # 等待1秒，重新设置
                        else:
                            break
                    if not ret:
                        autoRunState.thread_lock.acquire()
                        autoRunState.auto_run_state = "错误"
                        autoRunState.auto_run_info += "通讯转换器电源关闭失败！" + "错误码 = " + str(mtp_error_code[0]) + "\r\n"
                        autoRunState.thread_lock.release()
                        messagebox.showerror("", "运行出错！")
                        running_error_handle()
                        return
                    is_inc_power_off = True

                # 设置温箱温度，并等待温箱温度到达设定温度
                autoRunState.progress_info = "设置并等待温箱温度到达" + str(tc_sp) + "℃"
                temperature_deviation = accCalCtrl.temperature_ctrl.temperature_deviation
                if tc_sp <= 0.0:
                    if temperature_deviation < 1.0:
                        temperature_deviation = 1.0 # 温箱零度以下，偏差太小会导致温度等待经常失败！！！
                ret = tc_sp_set_and_wait_multithread(tc_sp, temperature_deviation, accCalCtrl.temperature_ctrl.temperature_hit_count, accCalCtrl.temperature_ctrl.temperature_wait_time)
                if ret != 0:
                    autoRunState.thread_lock.acquire()
                    autoRunState.auto_run_state = "错误"
                    autoRunState.auto_run_info += "设置并等待温箱" + str(tc_sp) + "℃" + "失败！" + "返回值 = " + str(ret) + "\r\n"
                    autoRunState.thread_lock.release()
                    messagebox.showerror("", "运行出错！")
                    running_error_handle()
                    return

                # 保温一段时间
                autoRunState.progress_info = "保温" + str(tc_sp) + "℃" + "一段时间"
                wait_time = accCalCtrl.temperature_ctrl.temperature_hold_time * 60 # 分钟
                time_begin = time.time()
                while True:
                    if terminate_thread_requst_check():
                        accCalCtrl.thread_instance = None
                        autoRunState.progress_bar_value = 0
                        return
                    if (time.time() - time_begin) > wait_time:
                        break

                # 如果测斜仪已断电，需要重新给测斜仪上电
                if is_inc_power_off:
                    # 重新给测斜仪上电
                    mtp_error_code = [0]
                    ret = True
                    n = 5
                    for try_count in range(n):  # 尝试多次设置，提高成功率！！！
                        incComm.thread_lock.acquire()
                        ret = cc_power_on(incComm.comm_port, mtp_error_code)  # 开启通讯转换器电源输出
                        incComm.thread_lock.release()
                        if not ret:
                            time.sleep(1)  # 等待1秒，重新设置
                        else:
                            break
                    if not ret:
                        autoRunState.thread_lock.acquire()
                        autoRunState.auto_run_state = "错误"
                        autoRunState.auto_run_info += "通讯转换器电源打开失败！" + "错误码 = " + str(mtp_error_code[0]) + "\r\n"
                        autoRunState.thread_lock.release()
                        messagebox.showerror("", "运行出错！")
                        running_error_handle()
                        return
                    is_inc_power_off = False
                    time.sleep(5)  # 等待一段时间，让RS485通讯板上电启动

            # 设置平均次数
            # 控制转台运转至目标位置并记录当前位置下的加速度值至excel文件
            if accCalCtrl.cal_ctrl_of_acc_cal.cal_enable:
                # 设置平均次数
                autoRunState.progress_info = "(" + str(tc_sp) + "℃" + "-" + accCalCtrl.cal_ctrl_of_acc_cal.cal_name + ")" + "设置平均次数..."
                inc_average_num_aia_set(accCalCtrl.cal_ctrl_of_acc_cal, tc_sp_str)
                # 控制转台运转至目标位置并记录当前位置下的加速度值至excel文件
                autoRunState.progress_info = "(" + str(tc_sp) + "℃" + "-" + accCalCtrl.cal_ctrl_of_acc_cal.cal_name + ")" + "控制转台运转至目标位置并记录加速度值..."
                ret = turntable_run_and_data_record(accCalCtrl.cal_ctrl_of_acc_cal.turntable_positions, accCalCtrl.cal_ctrl_of_acc_cal.pos_gxyz_excel_file_directory_path, tc_sp_str)
                if ret != 0:
                    if ret < 0:
                        running_error_handle()
                        return
                    else:
                        tip = "(" + str(tc_sp) + "℃" + "-" + accCalCtrl.cal_ctrl_of_acc_cal.cal_name + ")" + "控制转台运转至目标位置并记录加速度值出现了错误？！" + "\r\n"
                        running_alarm_handle(tip)
            if accCalCtrl.cal_ctrl_of_total_acceleration_check.cal_enable:
                # 设置平均次数
                autoRunState.progress_info = "(" + str(tc_sp) + "℃" + "-" + accCalCtrl.cal_ctrl_of_total_acceleration_check.cal_name + ")" + "设置平均次数..."
                inc_average_num_aia_set(accCalCtrl.cal_ctrl_of_total_acceleration_check, tc_sp_str)
                # 控制转台运转至目标位置并记录当前位置下的加速度值至excel文件
                autoRunState.progress_info = "(" + str(tc_sp) + "℃" + "-" + accCalCtrl.cal_ctrl_of_total_acceleration_check.cal_name + ")" + "控制转台运转至目标位置并记录加速度值..."
                ret = turntable_run_and_data_record(accCalCtrl.cal_ctrl_of_total_acceleration_check.turntable_positions, accCalCtrl.cal_ctrl_of_total_acceleration_check.pos_gxyz_excel_file_directory_path, tc_sp_str)
                if ret != 0:
                    if ret < 0:
                        running_error_handle()
                        return
                    else:
                        tip = "(" + str(tc_sp) + "℃" + "-" + accCalCtrl.cal_ctrl_of_total_acceleration_check.cal_name + ")" + "控制转台运转至目标位置并记录加速度值出现了错误？！" + "\r\n"
                        running_alarm_handle(tip)
            if accCalCtrl.cal_ctrl_of_acc_turntable_misalign_cal.cal_enable:
                # 设置平均次数
                autoRunState.progress_info = "(" + str(tc_sp) + "℃" + "-" + accCalCtrl.cal_ctrl_of_acc_turntable_misalign_cal.cal_name + ")" + "设置平均次数..."
                inc_average_num_aia_set(accCalCtrl.cal_ctrl_of_acc_turntable_misalign_cal, tc_sp_str)
                # 控制转台运转至目标位置并记录当前位置下的加速度值至excel文件
                autoRunState.progress_info = "(" + str(tc_sp) + "℃" + "-" + accCalCtrl.cal_ctrl_of_acc_turntable_misalign_cal.cal_name + ")" + "控制转台运转至目标位置并记录加速度值..."
                ret = turntable_run_and_data_record(accCalCtrl.cal_ctrl_of_acc_turntable_misalign_cal.turntable_positions, accCalCtrl.cal_ctrl_of_acc_turntable_misalign_cal.pos_gxyz_excel_file_directory_path, tc_sp_str)
                if ret != 0:
                    if ret < 0:
                        running_error_handle()
                        return
                    else:
                        tip = "(" + str(tc_sp) + "℃" + "-" + accCalCtrl.cal_ctrl_of_acc_turntable_misalign_cal.cal_name + ")" + "控制转台运转至目标位置并记录加速度值出现了错误？！" + "\r\n"
                        running_alarm_handle(tip)
            if accCalCtrl.cal_ctrl_of_acc_calibration_angle_check.cal_enable:
                # 设置平均次数
                autoRunState.progress_info = "(" + str(tc_sp) + "℃" + "-" + accCalCtrl.cal_ctrl_of_acc_calibration_angle_check.cal_name + ")" + "设置平均次数..."
                inc_average_num_aia_set(accCalCtrl.cal_ctrl_of_acc_calibration_angle_check, tc_sp_str)
                # 控制转台运转至目标位置并记录当前位置下的加速度值至excel文件
                autoRunState.progress_info = "(" + str(tc_sp) + "℃" + "-" + accCalCtrl.cal_ctrl_of_acc_calibration_angle_check.cal_name + ")" + "控制转台运转至目标位置并记录加速度值..."
                ret = turntable_run_and_data_record(accCalCtrl.cal_ctrl_of_acc_calibration_angle_check.turntable_positions, accCalCtrl.cal_ctrl_of_acc_calibration_angle_check.pos_gxyz_excel_file_directory_path, tc_sp_str)
                if ret != 0:
                    if ret < 0:
                        running_error_handle()
                        return
                    else:
                        tip = "(" + str(tc_sp) + "℃" + "-" + accCalCtrl.cal_ctrl_of_acc_calibration_angle_check.cal_name + ")" + "控制转台运转至目标位置并记录加速度值出现了错误？！" + "\r\n"
                        running_alarm_handle(tip)
            if accCalCtrl.cal_ctrl_of_acc_temperature_drift_verify.cal_enable:
                # 设置平均次数
                autoRunState.progress_info = "(" + str(tc_sp) + "℃" + "-" + accCalCtrl.cal_ctrl_of_acc_temperature_drift_verify.cal_name + ")" + "设置平均次数..."
                inc_average_num_aia_set(accCalCtrl.cal_ctrl_of_acc_temperature_drift_verify, tc_sp_str)
                # 控制转台运转至目标位置并记录当前位置下的加速度值至excel文件
                autoRunState.progress_info = "(" + str(tc_sp) + "℃" + "-" + accCalCtrl.cal_ctrl_of_acc_temperature_drift_verify.cal_name + ")" + "控制转台运转至目标位置并记录加速度值..."
                ret = turntable_run_and_data_record(accCalCtrl.cal_ctrl_of_acc_temperature_drift_verify.turntable_positions, accCalCtrl.cal_ctrl_of_acc_temperature_drift_verify.pos_gxyz_excel_file_directory_path, tc_sp_str)
                if ret != 0:
                    if ret < 0:
                        running_error_handle()
                        return
                    else:
                        tip = "(" + str(tc_sp) + "℃" + "-" + accCalCtrl.cal_ctrl_of_acc_temperature_drift_verify.cal_name + ")" + "控制转台运转至目标位置并记录加速度值出现了错误？！" + "\r\n"
                        running_alarm_handle(tip)

        # 椭球拟合
        if accCalCtrl.cal_ctrl_of_acc_cal.cal_enable:
            autoRunState.progress_info = "椭球拟合..."
            pos_gxyz_excel_files_path = [os.path.join(accCalCtrl.cal_ctrl_of_acc_cal.pos_gxyz_excel_file_directory_path, file) for file in
                                         os.listdir(accCalCtrl.cal_ctrl_of_acc_cal.pos_gxyz_excel_file_directory_path)]
            for pos_gxyz_excel_file_path in pos_gxyz_excel_files_path:
                ret = ellipsoidal_fitting_process(pos_gxyz_excel_file_path)
                if ret != 0:
                    tip = pos_gxyz_excel_file_path + "椭球拟合失败！" + "返回值 = " + str(ret) + "\r\n"
                    running_alarm_handle(tip)
        autoRunState.progress_bar_value += accCalCtrl.progress_value_ellipsoid_fitting

        # 温度传感器校准计算
        if accCalCtrl.cal_ctrl_of_acc_cal.cal_enable and accCalCtrl.tps_comp_calcu_enable:
            autoRunState.progress_info = "温度传感器校准计算..."
            pos_gxyz_excel_files_path = []
            for file_name in os.listdir(accCalCtrl.cal_ctrl_of_acc_cal.cal_result_excel_file_directory_path):
                if "pos_gxyz" in file_name:
                    pos_gxyz_excel_files_path.append(os.path.join(accCalCtrl.cal_ctrl_of_acc_cal.cal_result_excel_file_directory_path, file_name))
            for pos_gxyz_excel_file_path in pos_gxyz_excel_files_path:
                ret = pos_gxyz_excel_file_check("acc_cal", pos_gxyz_excel_file_path)
                if ret == 0:
                    ret = tps_cal_process(pos_gxyz_excel_file_path)
                    if ret != 0:
                        tip = pos_gxyz_excel_file_path + "温度传感器校准计算失败！" + "返回值 = " + str(ret) + "\r\n"
                        running_alarm_handle(tip)
                    if (ret == 0) and (accCalCtrl.cal_ctrl_of_acc_cal.cal_data_upload_enable): # 上传校准数据文件至服务器
                        file_directory = os.path.dirname(pos_gxyz_excel_file_path)
                        sn = os.path.basename(pos_gxyz_excel_file_path).split('_')[0]
                        file_name = sn + "_tps_cal_result" + ".xlsx"
                        file_path = os.path.join(file_directory, file_name)
                        file_path_to_upload = file_path
                        err_msg = ['']
                        ftp_app = FTPApp()
                        ret = ftp_app.inc_cal_data_file_upload(file_path_to_upload, err_msg)
                        if not ret:
                            tip = file_path_to_upload + '上传失败！' + '错误提示：' + err_msg[0] + "\r\n"
                            running_alarm_handle(tip)
                else:
                    tip = "温度传感器校准计算：" + pos_gxyz_excel_file_path + "无效！" + "返回值 = " + str(ret) + "\r\n"
                    running_alarm_handle(tip)

        # LM计算
        if accCalCtrl.lm_calculate_enable:
            autoRunState.progress_info = "LM计算..."
            i = 0
        autoRunState.progress_bar_value += accCalCtrl.progress_value_lm_calculate

        # 总加速度检验
        if accCalCtrl.cal_ctrl_of_total_acceleration_check.cal_enable:
            autoRunState.progress_info = "总加速度检验..."
            pos_gxyz_excel_files_path = [os.path.join(accCalCtrl.cal_ctrl_of_total_acceleration_check.pos_gxyz_excel_file_directory_path, file) for file in
                                         os.listdir(accCalCtrl.cal_ctrl_of_total_acceleration_check.pos_gxyz_excel_file_directory_path)]
            for pos_gxyz_excel_file_path in pos_gxyz_excel_files_path:
                # 检查并确定椭球拟合或LM结果excel文件路径（选择exe//calibration目录下的椭球拟合或LM结果文件）
                sn = os.path.basename(pos_gxyz_excel_file_path).split("_")[0]
                exe_path = os.path.dirname(os.path.realpath(sys.argv[0]))
                ellipsoid_or_lm_result_excel_file_directory_path = os.path.join(exe_path, 'calibration')
                ellipsoid_result_excel_file_name = sn + "_ellipsoid_" + "result" + ".xlsx"
                ellipsoid_result_excel_file_path = os.path.join(ellipsoid_or_lm_result_excel_file_directory_path,
                                                                ellipsoid_result_excel_file_name)
                ellipsoid_or_lm_result_excel_file_path = ellipsoid_result_excel_file_path
                if not os.path.exists(ellipsoid_result_excel_file_path): # 优先选择椭球拟合结果，如果椭球拟合结果文件不存在，则选择LM校准结果文件
                    lm_result_excel_file_name = sn + "_lm_" + "result" + ".xlsx"
                    lm_result_excel_file_path = os.path.join(ellipsoid_or_lm_result_excel_file_directory_path,
                                                             lm_result_excel_file_name)
                    ellipsoid_or_lm_result_excel_file_path = lm_result_excel_file_path
                    if not os.path.exists(lm_result_excel_file_path):
                        tip = lm_result_excel_file_path + "不存在！" + "\r\n"
                        running_alarm_handle(tip)
                        continue
                # 总加速度检验
                ret = total_acceleration_check(pos_gxyz_excel_file_path, ellipsoid_or_lm_result_excel_file_path)
                if ret != 0:
                    if ret == -5:
                        tip = pos_gxyz_excel_file_path + "总加速度不合格！" + "返回值 = " + str(ret) + "\r\n"
                    else:
                        tip = pos_gxyz_excel_file_path + "总加速度检验失败！" + "返回值 = " + str(ret) + "\r\n"
                    running_alarm_handle(tip)
        autoRunState.progress_bar_value += accCalCtrl.progress_value_total_acceleration_check

        # 检验椭球结果是否合格，如果合格则进行加速度计温漂补偿计算
        if accCalCtrl.cal_ctrl_of_acc_cal.cal_enable and accCalCtrl.cal_ctrl_of_total_acceleration_check.cal_enable:
            autoRunState.progress_info = "检验椭球结果是否合格..."
            # 收集椭球结果excel文件
            ellipsoid_result_excel_files_path = []
            for file_name in os.listdir(accCalCtrl.cal_ctrl_of_acc_cal.cal_result_excel_file_directory_path):
                if "ellipsoid_result" in file_name:
                    ellipsoid_result_excel_files_path.append(os.path.join(accCalCtrl.cal_ctrl_of_acc_cal.cal_result_excel_file_directory_path, file_name))
            # 检验椭球结果是否合格
            for ellipsoid_result_excel_file_path in ellipsoid_result_excel_files_path:
                sn = os.path.basename(ellipsoid_result_excel_file_path).split('_')[0]
                total_acceleration_check_excel_file_name = sn + "_total_acceleration_check" + ".xlsx"
                total_acceleration_check_excel_file_path = os.path.join(accCalCtrl.cal_ctrl_of_total_acceleration_check.cal_result_excel_file_directory_path,
                                                                        total_acceleration_check_excel_file_name)
                ret = ellipsoid_result_qualified_check(ellipsoid_result_excel_file_path, total_acceleration_check_excel_file_path)
                if ret != 0:
                    if ret == -5:
                        tip = ellipsoid_result_excel_file_path + "椭球结果不合格！" + "返回值 = " + str(ret) + "\r\n"
                    else:
                        tip = ellipsoid_result_excel_file_path + "检验椭球结果是否合格失败！" + "返回值 = " + str(ret) + "\r\n"
                    running_alarm_handle(tip)
                else:
                    if accCalCtrl.acc_tdc_calcu_enable:
                        ret = acc_tdc_process(ellipsoid_result_excel_file_path)
                        if ret != 0:
                            tip = ellipsoid_result_excel_file_path + "温漂补偿计算失败！" + "返回值 = " + str(ret) + "\r\n"
                            running_alarm_handle(tip)
                        if (ret == 0) and (accCalCtrl.cal_ctrl_of_acc_cal.cal_data_upload_enable):  # 上传校准数据文件至服务器
                            file_directory = os.path.dirname(ellipsoid_result_excel_file_path)
                            sn = os.path.basename(ellipsoid_result_excel_file_path).split('_')[0]
                            file_name = sn + "_acc_tdc_result" + ".xlsx"
                            file_path = os.path.join(file_directory, file_name)
                            file_path_to_upload = file_path
                            err_msg = ['']
                            ftp_app = FTPApp()
                            ret = ftp_app.inc_cal_data_file_upload(file_path_to_upload, err_msg)
                            if not ret:
                                tip = file_path_to_upload + '上传失败！' + '错误提示：' + err_msg[0] + "\r\n"
                                running_alarm_handle(tip)

        # 运行结束，给出提示，退出线程
        autoRunState.progress_info = "运行结束"
        autoRunState.button_text_AccCalRun = "自动运行"
        accCalCtrl.thread_instance = None
        # 判断是否需要重新运行
        accCalCtrl.run_count = accCalCtrl.run_count + 1
        if accCalCtrl.run_count < accCalCtrl.run_num:
            accCalCtrl.acc_cal_rerun_requst = True
        else:
            accCalCtrl.run_count = 0
            if (autoRunState.auto_run_state == "错误") or (autoRunState.auto_run_state == "报警"):
                messagebox.showerror("", "运行出错！")
            else:
                messagebox.showinfo("", "运行成功")
        autoRunState.thread_lock.acquire()
        autoRunState.auto_run_state = "停止"
        autoRunState.thread_lock.release()
        autoRunState.progress_bar_value = 0
        autoRunState.progress_info = ""

        # 退出线程
        return