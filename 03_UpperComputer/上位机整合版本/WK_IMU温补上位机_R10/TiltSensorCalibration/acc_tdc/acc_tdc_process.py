import os
import openpyxl
import numpy as np
import re
import pandas as pd

import sys
sys.path.append(sys.path[0] + '\\inc')
from inc_def import *


def acc_tdc_process(ellipsoid_result_excel_file_path):
    """
    根据椭球结果excel文件，计算温度范围和各项系数，并写入excel文件。

    Args:
        ellipsoid_result_excel_file_path (str): 椭球结果excel文件路径。

    Returns:
        int:  0 - 处理成功
             -1 - 处理失败
    """
    # 打开椭球结果excel文件
    try:
        wb = openpyxl.load_workbook(ellipsoid_result_excel_file_path)
    except:
        return -1

    # 读取"汇总"表数据
    try:
        ws = wb['汇总']
        data = [[cell.value for cell in row] for row in ws.iter_rows()]
        headers = data[0]
        data = data[1:]
        # 获取温度、零偏和灵敏度数据的列索引
        temperature_col = headers.index('温度')
        zero_offset_x_col = headers.index('X0')
        zero_offset_y_col = headers.index('Y0')
        zero_offset_z_col = headers.index('Z0')
        sensitivity_x_col = headers.index('A')
        sensitivity_y_col = headers.index('B')
        sensitivity_z_col = headers.index('C')
        # 提取数据并转换为 NumPy 数组
        temperatures = np.array([float(row[temperature_col].split('℃')[0]) for row in data])
        zero_offset_x = np.array([row[zero_offset_x_col] for row in data])
        zero_offset_y = np.array([row[zero_offset_y_col] for row in data])
        zero_offset_z = np.array([row[zero_offset_z_col] for row in data])
        sensitivity_x = np.array([row[sensitivity_x_col] for row in data])
        sensitivity_y = np.array([row[sensitivity_y_col] for row in data])
        sensitivity_z = np.array([row[sensitivity_z_col] for row in data])
    except:
        wb.close()
        return -1
    wb.close()

    # 多项式拟合
    try:
        # 计算多项式系数
        coeffs_zero_offset_x = np.polyfit(temperatures, zero_offset_x, 3)
        coeffs_zero_offset_y = np.polyfit(temperatures, zero_offset_y, 3)
        coeffs_zero_offset_z = np.polyfit(temperatures, zero_offset_z, 3)
        coeffs_sensitivity_x = np.polyfit(temperatures, sensitivity_x, 3)
        coeffs_sensitivity_y = np.polyfit(temperatures, sensitivity_y, 3)
        coeffs_sensitivity_z = np.polyfit(temperatures, sensitivity_z, 3)
        # 计算温度范围
        min_temperature = np.min(temperatures)
        max_temperature = np.max(temperatures)
        temperature_range = f'{min_temperature}℃-{max_temperature}℃'
    except:
        return -2

    # 将多项式拟合系数导出到excel文件
    try:
        wb = openpyxl.Workbook()
        wb.remove(wb['Sheet'])
        sheet_names = ['X0', 'Y0', 'Z0', 'A', 'B', 'C']
        coeffs_list = [
            coeffs_zero_offset_x, coeffs_zero_offset_y, coeffs_zero_offset_z,
            coeffs_sensitivity_x, coeffs_sensitivity_y, coeffs_sensitivity_z
        ]
        for i, sheet_name in enumerate(sheet_names):
            ws = wb.create_sheet(sheet_name)
            ws.append(['温度范围', 'coef0', 'coef1', 'coef2', 'coef3'])
            ws.append(
                [temperature_range, coeffs_list[i][3], coeffs_list[i][2], coeffs_list[i][1], coeffs_list[i][0]])
        file_name, file_ext = os.path.splitext(ellipsoid_result_excel_file_path)
        new_file_name = file_name.replace("ellipsoid", "acc_tdc") + file_ext
        wb.save(new_file_name)
    except:
        return -1

    return 0


def tps_cal_process(acc_data_excel_file_path):
    """
    读取加速度数据excel文件中的温箱温度和温度传感器温度，获取温度传感器25℃下的输出AD值和计算多项式拟合系数，并将结果保存到新的excel文件中。

    Args:
        acc_data_excel_file_path (str): 加速度数据excel文件路径

    Returns:
        int:  0 - 处理成功
             -1 - 处理失败
    """
    # 获取温度传感器25℃下的输出AD值和计算多项式拟合系数
    try:
        x = []
        y = []
        sheet_data = pd.read_excel(acc_data_excel_file_path, sheet_name=None)
        ad_value_at_25 = sheet_data['25.0℃_起始'].loc[0, '温度传感器AD值']
        try:
            inc_model = sheet_data['info'].loc[0, '测斜仪型号']
        except:
            inc_model = ''
        scale_factor = ADXL355_TEMP_SENSOR_SCALE_FACTOR_DEFAULT
        if inc_model == INC_MODEL_H:
            scale_factor = ADXL355_TEMP_SENSOR_SCALE_FACTOR_DEFAULT
        elif inc_model == INC_MODEL_M:
            scale_factor = SCA3300_TEMP_SENSOR_SCALE_FACTOR_DEFAULT
        else:
            scale_factor = ADXL355_TEMP_SENSOR_SCALE_FACTOR_DEFAULT
        for key in sheet_data.keys():
            if re.match(r'^\d+', key):
                expected_tempture = sheet_data[key].loc[0, '温箱温度']
                expected_ad_value = convert_temperature_to_ad_value(expected_tempture, scale_factor, ad_value_at_25)
                y.append(expected_ad_value)
                temperature_sensor_ad_value = sheet_data[key].loc[0, '温度传感器AD值']
                x.append(temperature_sensor_ad_value)
            else:
                continue
        coefficients = np.polyfit(x, y, 3)
    except:
        return -1

    # 将结果保存到新的excel文件中
    try:
        filename = os.path.basename(acc_data_excel_file_path)
        sn = filename.split('_')[0]
        result_filename = f"{sn}_tps_cal_result.xlsx"
        result_directory_path = os.path.dirname(acc_data_excel_file_path)
        result_filepath = os.path.join(result_directory_path, result_filename)

        with pd.ExcelWriter(result_filepath) as writer:
            pd.DataFrame({"AD_Value_at_25℃": [ad_value_at_25]}).to_excel(writer, sheet_name="Offset", index=False)
            coef_df = pd.DataFrame([coefficients[::-1]], columns=[f"coef{i}" for i in range(len(coefficients))])
            coef_df.to_excel(writer, sheet_name="ScaleFactor", index=False)
    except:
        return -1

    return 0


def convert_temperature_to_ad_value(temperature, sensitivity, ad_value_at_25):
    """
    将温度转化为其原始的AD值

    Args:
        temperature (float): 温度值
        sensitivity (float): 温度传感器的灵敏度
        ad_value_at_25 (float): 温度传感器的25℃下的AD输出值

    Returns:
        float: 温度传感器的AD输出值
    """
    ad_value = (temperature - 25.0) * sensitivity + ad_value_at_25
    return ad_value

