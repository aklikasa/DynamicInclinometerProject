"""倾角仪校准界面"""
import os
import time
from datetime import *
from qt_dialogs import filedialog, messagebox
import serial
import serial.tools.list_ports
import threading
from PySide6.QtGui import QRegularExpressionValidator, QFont
from PySide6.QtCore import QRegularExpression, QTimer , QRegularExpressionMatch, Qt
import xml.etree.ElementTree as Et
import openpyxl
from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill
import numpy
import shutil

import sys
sys.path.append(sys.path[0]+'\\form')
sys.path.append(sys.path[0] + '\\tilt_sensor')
sys.path.append(sys.path[0]+'\\turntable')
sys.path.append(sys.path[0] + '\\temperature_chamber')
sys.path.append(sys.path[0] + '\\tilt_sensor_calibration')
sys.path.append(sys.path[0] + '\\debug')
from ui_utils import *
#from form_inc import *
#from inc_data_get import *
#from inc_cal import *
from turntable_2TD600_comm import *
from turntable_2FDT600WK_comm import *
from turntable_data_get import *
from temperature_chamber_data_get import *
from auto_run_state import *
from acc_cal import *
from debug import *
from tilt_sensor_asm330_def import *
from tilt_sensor_asm330_data_get import *
from tilt_sensor_asm330_csv import *
from device_sn_autofill import DeviceSnAutoFill


class FormTiltSensorCal:

    def __init__(self, main_window_ui):
        #
        # 创建控件
        #
        ui = main_window_ui

        # 分页表控件
        self.tabWidget_CalMain = ui.tabWidget_CalMain
        self.tabWidget_IncCal = ui.tabWidget_IncCal
        self.tabWidget_TemperatureControl = ui.tabWidget_TemperatureControl
        self.tabWidget_CalItemParaSet = ui.tabWidget_CalItemParaSet
        self.tabWidget_CalRun = ui.tabWidget_CalRun

        # 加速度数据存储目录栏
        self.textEdit_AccDataSaveDirectory_Auto = ui.textEdit_AccDataSaveDirectory_Auto
        self.pushButton_AccDataSaveDirectorySelect_Auto = ui.pushButton_AccDataSaveDirectorySelect_Auto

        # 数据记录页：记录目录 + 手动开始/停止记录
        self.textEdit_AccDataSaveDirectory = ui.textEdit_AccDataSaveDirectory
        self.pushButton_AccDataSaveDirectorySelect = ui.pushButton_AccDataSaveDirectorySelect
        self.pushButton_DataRecordStart = ui.pushButton_DataRecordStart
        # 数据记录采用唯一的状态切换按钮（开始记录 ⇄ 停止记录）。
        self.pushButton_DataRecordStart.setText("开始记录")
        self.pushButton_DataRecordStart.setProperty("recording", False)
        self.lineEdit_AutoRunSpeedSet = ui.lineEdit_RotationSpeedSet

        # 温控设置栏
        self.comboBox_TemperatureControlMode = ui.comboBox_TemperatureControlMode
        self.lineEdit_OperatingTemperature = ui.lineEdit_OperatingTemperature
        self.lineEdit_StartTemperature = ui.lineEdit_StartTemperature
        self.lineEdit_TemperatureRange1 = ui.lineEdit_TemperatureRange1
        self.lineEdit_TemperatureRange2 = ui.lineEdit_TemperatureRange2
        self.lineEdit_TemperatureInterval = ui.lineEdit_TemperatureInterval
        self.lineEdit_TemperatureDeviation = ui.lineEdit_TemperatureDeviation
        self.lineEdit_TemperatureHitCount = ui.lineEdit_TemperatureHitCount
        self.lineEdit_TemperatureWaitTime = ui.lineEdit_TemperatureWaitTime
        self.lineEdit_TemperatureHoldTime = ui.lineEdit_TemperatureHoldTime
        self.lineEdit_RunNum = ui.lineEdit_RunNum
        self.checkBox_TemperatureControlEnable = ui.checkBox_TemperatureControlEnable

        # 校准项目参数设置栏
        # 加速度计校准
        self.lineEdit_PositionNumOfAccCal = ui.lineEdit_PositionNumOfAccCal
        self.lineEdit_AverageNumOfAccCal = ui.lineEdit_AverageNumOfAccCal
        self.checkBox_AIAEnableOfAccCal = ui.checkBox_AIAEnableOfAccCal
        self.checkBox_AccTdcCalcuEnable = ui.checkBox_AccTdcCalcuEnable
        self.checkBox_TpsCompCalcuEnable = ui.checkBox_TpsCompCalcuEnable
        self.checkBox_AccCalFTPPush = ui.checkBox_AccCalFTPPush
        # 总加速度检验
        self.lineEdit_AverageNumOfTotalAccelerationCheck = ui.lineEdit_AverageNumOfTotalAccelerationCheck
        self.checkBox_AIAEnableOfTotalAccelerationCheck = ui.checkBox_AIAEnableOfTotalAccelerationCheck
        # 自动运行栏
        self.checkBox_EllipsoidFitting = ui.checkBox_EllipsoidFitting
        self.checkBox_LMCalculate = ui.checkBox_LMCalcu
        self.checkBox_TotalAccelerationCheck = ui.checkBox_TotalAccelerationCheck
        self.pushButton_AccCalRun = ui.pushButton_AccCalRun

        # 状态栏
        self.pushButton_AutoRunStateLight = ui.pushButton_AutoRunStateLight
        self.textBrowser_AutoRunStateInfo = ui.textBrowser_AutoRunStateInfo
        self.label_AutoRunProgressInfo = ui.label_AutoRunProgressInfo
        self.progressBar_AutoRun = ui.progressBar_AutoRun

        # 倾角仪通讯栏
        self.comboBox_IncCommPortSelect = ui.comboBox_IncCommPortSelect  # 使用 .ui 中真实的下拉框
        self.button_IncCommPortOpen = ui.button_IncCommPortOpen
        # 柔性测斜仪 FTP 序列号页面已退役，不再取得该控件。
        self.pushButton_IncStateLight = ui.pushButton_IncStateLight
        self.textBrowser_IncStateInfo = ui.textBrowser_IncStateInfo
        # 信息栏用等宽字体且不自动换行，保证16组数据列对齐、行不被折断
        inc_info_font = QFont("Consolas", 9)
        inc_info_font.setStyleHint(QFont.Monospace)
        self.textBrowser_IncStateInfo.setFont(inc_info_font)
        self.textBrowser_IncStateInfo.setLineWrapMode(QTextEdit.NoWrap)
        self.inc_state_info_text = ""            # 上一次显示内容(内容没变就不刷新，避免闪烁)

        # 加速度数据页的实时数据表：滚动历史表（持续往下追加、保留最近INC_TABLE_KEEP_ROWS行，
        # 横/竖滚动条都保留，可往上翻看历史）
        #   列0~2 = 加速度X轴/Y轴/Z轴(g)，列3~5 = 陀螺仪X轴/Y轴/Z轴(dps)，
        #   列6   = 温度(℃)（每帧16行同值，放在最后一列）
        self.tableWidget_AccDataDisplay = ui.tableWidget_AccDataDisplay
        self.tableWidget_AccDataDisplay.setRowCount(0)
        self.tableWidget_AccDataDisplay.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.tableWidget_AccDataDisplay.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.tableWidget_AccDataDisplay.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.tableWidget_AccDataDisplay.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        inc_col_titles = ["加速度X轴(g)", "加速度Y轴(g)", "加速度Z轴(g)",
                          "陀螺仪X轴(dps)", "陀螺仪Y轴(dps)", "陀螺仪Z轴(dps)", "温度(℃)"]
        for inc_col in range(len(inc_col_titles)):
            inc_header_item = self.tableWidget_AccDataDisplay.horizontalHeaderItem(inc_col)
            if inc_header_item == None:
                inc_header_item = QTableWidgetItem(inc_col_titles[inc_col])
                self.tableWidget_AccDataDisplay.setHorizontalHeaderItem(inc_col, inc_header_item)
            else:
                inc_header_item.setText(inc_col_titles[inc_col])
            self.tableWidget_AccDataDisplay.setColumnHidden(inc_col, False)
        # "自动滚动刷新"复选框放在加速度数据区页签右上角(corner widget)，不挤占表格空间、永远可见
        #   勾选=表格自动跟随最新数据；取消=保持你翻看的位置
        self.checkBox_AccDataAutoScroll = QCheckBox("自动滚动刷新")
        self.checkBox_AccDataAutoScroll.setChecked(True)
        self.checkBox_AccDataAutoScroll.setToolTip("勾选：表格自动滚动到最新数据；取消：保持当前位置方便翻看历史")
        ui.tabWidget_AccDataManual.setCornerWidget(self.checkBox_AccDataAutoScroll)
        # 设备 UID 页：仅保留一个只读SN显示框，无读取按钮/错误文案。
        # 由既有采集线程在连接后自动查询，下方200ms GUI定时器负责刷新。
        self._device_uid_tab = QWidget()
        self._device_uid_tab.setObjectName("tab_DeviceUID")
        uid_layout = QVBoxLayout(self._device_uid_tab)
        uid_layout.setContentsMargins(20, 26, 20, 20)
        uid_layout.setSpacing(8)
        self.lineEdit_DeviceSN = QLineEdit(self._device_uid_tab)
        self.lineEdit_DeviceSN.setObjectName("lineEdit_DeviceSN")
        self.lineEdit_DeviceSN.setReadOnly(True)
        self.lineEdit_DeviceSN.setAlignment(Qt.AlignCenter)
        self.lineEdit_DeviceSN.setMinimumHeight(48)
        uid_font = QFont("Consolas", 18)
        uid_font.setStyleHint(QFont.Monospace)
        uid_font.setBold(True)
        self.lineEdit_DeviceSN.setFont(uid_font)
        self.lineEdit_DeviceSN.setToolTip("连接后自动显示DTS设备编号；不支持UID的固件保持空白")
        self._device_sn_auto_fill = DeviceSnAutoFill()  # 同步标定/温补页的PCB编号
        uid_layout.addWidget(self.lineEdit_DeviceSN)
        uid_layout.addStretch(1)
        ui.tabWidget_AccDataManual.addTab(self._device_uid_tab, "设备 UID")
        self.inc_table_frame_count = 0           # 已写入表格的帧号(避免同一帧重复追加)
        self.inc_was_connected = False           # 上一次刷新时串口是否已打开(用于断开瞬间清理旧数据)

        #
        # 初始化控件
        #
        # 加速度数据存储目录栏
        self.lineEdit_AutoRunSpeedSet.setText(str(10))

        # 温控设置栏
        self.comboBox_TemperatureControlMode.setCurrentIndex(1)
        self.lineEdit_OperatingTemperature.setText(str(25))
        self.lineEdit_StartTemperature.setText(str(25))
        self.lineEdit_TemperatureRange1.setText(str(-20))
        self.lineEdit_TemperatureRange2.setText(str(70))
        self.lineEdit_TemperatureInterval.setText(str(5))
        self.lineEdit_TemperatureDeviation.setText(str(0.5))
        self.lineEdit_TemperatureHitCount.setText(str(10))
        self.lineEdit_TemperatureWaitTime.setText(str(720))
        self.lineEdit_TemperatureHoldTime.setText(str(60))
        self.lineEdit_RunNum.setText(str(1))
        self.checkBox_TemperatureControlEnable.setChecked(False)

        # 校准项目参数设置栏
        self.lineEdit_PositionNumOfAccCal.setText(str(64)) # 椭球拟合位置数
        self.lineEdit_AverageNumOfAccCal.setText(str(500))
        self.checkBox_AIAEnableOfAccCal.setChecked(True)
        self.checkBox_AccTdcCalcuEnable.setChecked(True)
        self.checkBox_TpsCompCalcuEnable.setChecked(True)
        self.checkBox_AccCalFTPPush.setChecked(True)

        self.lineEdit_AverageNumOfTotalAccelerationCheck.setText(str(1000))
        self.checkBox_AIAEnableOfTotalAccelerationCheck.setChecked(True)

        # 自动运行栏
        self.pushButton_AccCalRun.setEnabled(True)
        self.pushButton_AccCalRun.setText("自动运行")
        self.checkBox_EllipsoidFitting.setChecked(True)
        self.checkBox_TotalAccelerationCheck.setChecked(False)
        self.checkBox_LMCalculate.setChecked(False)
        self.checkBox_LMCalculate.setVisible(False)

        # 状态栏
        self.pushButton_AutoRunStateLight.setText("")
        self.label_AutoRunProgressInfo.setText("")

        #
        # 设置按钮点击事件函数
        #
        self.pushButton_AccDataSaveDirectorySelect_Auto.clicked.connect(self.pushButton_AccDataSaveDirectorySelect_Auto_Click)
        # 数据记录页：选择目录 + 一个启动/停止切换按钮。
        self.pushButton_AccDataSaveDirectorySelect.clicked.connect(self.pushButton_AccDataSaveDirectorySelect_Click)
        self.pushButton_DataRecordStart.clicked.connect(self.pushButton_DataRecordToggle_Click)
        self.textEdit_AccDataSaveDirectory.textChanged.connect(self.textEdit_AccDataSaveDirectory_textChanged)
        self.pushButton_AccCalRun.clicked.connect(self.pushButton_AccCalRun_Click)
        self.button_IncCommPortOpen.clicked.connect(self.button_IncCommPortOpen_Click)

        #
        # 创建实时显示自动运行状态的定时器
        #
        # 创建自动运行状态显示定时器
        self.timer_AutoRunStateDisplay = self.create_timer(100, self.timer_AutoRunStateDisplay_Tick)
        self.timer_AutoRunStateDisplay.start()
        # 创建轮询重新运行请求的定时器
        self.timer_RerunRequstPoll = self.create_timer(10000, self.timer_RerunRequstPoll_Tick)
        self.timer_RerunRequstPoll.start()
        # 创建倾角仪通讯状态与数据显示定时器
        self.timer_IncStateDisplay = self.create_timer(200, self.timer_IncStateDisplay_Tick)
        self.timer_IncStateDisplay.start()
        # 程序退出时停止采集线程、关闭串口并写完CSV记录文件
        QApplication.instance().aboutToQuit.connect(self.on_app_quit)

        #
        # 初始化倾角仪通讯栏（串口列表与config.xml中的参数）
        #
        tilt_sensor_user_habits_get('config.xml')
        # 数据记录页显示config.xml里配置的记录目录
        self.textEdit_AccDataSaveDirectory.setText(csv_dir_path_get())
        self.button_IncCommPortOpen.setText("打开串口")
        self.pushButton_IncStateLight.setText("未连接")
        self.pushButton_IncStateLight.setStyleSheet(
            'background: #f0f2f3; color: #7f8991; border: 1px solid #d6dce0; border-radius: 12px; font-weight: 600;')
        self.textBrowser_IncStateInfo.clear()

        # 首次扫描，并定期刷新，支持软件启动后再插入 IMU USB 转串口设备
        self.refresh_inc_comm_ports()
        self.timer_IncPortRefresh = QTimer(ui)
        self.timer_IncPortRefresh.setInterval(1500)
        self.timer_IncPortRefresh.timeout.connect(self.refresh_inc_comm_ports)
        self.timer_IncPortRefresh.start()

        #
        # 获取用户习惯
        #
        self.get_user_habits()

        #
        # 设置相应界面是否显示
        #
        self.widget_visible_set()

    def pushButton_AccDataSaveDirectorySelect_Auto_Click(self):
        """
            "pushButton_AccDataSaveDirectorySelect_Auto"按钮的鼠标点击事件函数
        """
        directory = filedialog.askdirectory()
        self.textEdit_AccDataSaveDirectory_Auto.setText(directory)

    def pushButton_AccDataSaveDirectorySelect_Click(self):
        """
            "数据记录"页"选择文件夹"按钮：选择数据记录目录（正在记录时不允许修改）
        """
        if csv_is_enabled():
            messagebox.showerror("", "正在记录数据，不能修改记录目录！\r\n请先点\"停止记录\"，再修改路径。")
            return
        start_dir = csv_dir_path_get() if csv_dir_is_valid() else os.path.expanduser("~")
        directory = QFileDialog.getExistingDirectory(self.tabWidget_CalMain, "选择 CSV 记录文件夹", start_dir)
        if (directory == None) or (str(directory).strip() == ""):
            return
        directory = str(directory).strip()
        self.textEdit_AccDataSaveDirectory.setText(directory)
        csv_dir_set(directory)
        self.inc_data_save_dir_save(directory)
        if not csv_dir_is_valid():
            messagebox.showerror("", "所选记录目录不存在：\r\n" + directory + "\r\n该目录不存在时不会记录数据。")
        self.inc_state_info_text = ""
        self.timer_IncStateDisplay_Tick()

    def textEdit_AccDataSaveDirectory_textChanged(self):
        """
            "数据记录"页记录目录编辑框：手动输入路径时立即生效（正在记录时编辑框是只读的）
        """
        if csv_is_enabled():
            return
        csv_dir_set(self.textEdit_AccDataSaveDirectory.toPlainText())
        self.inc_state_info_text = ""

    def pushButton_DataRecordToggle_Click(self):
        """唯一入口：以文件写入状态为准，避免按钮文字与记录状态失配。"""
        if csv_is_enabled():
            self.pushButton_DataRecordPause_Click()
        else:
            self.pushButton_DataRecordStart_Click()
        self._sync_record_button()

    def _sync_record_button(self):
        """当记录异常退出、串口关闭或手动停止时仍能正确显示按钮状态。"""
        recording = bool(csv_is_enabled())
        label = "停止记录" if recording else "开始记录"
        if self.pushButton_DataRecordStart.text() != label:
            self.pushButton_DataRecordStart.setText(label)
        if self.pushButton_DataRecordStart.property("recording") != recording:
            self.pushButton_DataRecordStart.setProperty("recording", recording)
            style = self.pushButton_DataRecordStart.style()
            style.unpolish(self.pushButton_DataRecordStart)
            style.polish(self.pushButton_DataRecordStart)
            self.pushButton_DataRecordStart.update()

    def pushButton_DataRecordStart_Click(self):
        """连接 IMU 且目录有效时开始一段新的 CSV 记录。"""
        if not tiltSensorComm.is_serial_opened:
            messagebox.showwarning("", "请先在设备连接区打开 IMU 串口，再开始记录。")
            return
        if not csv_dir_is_valid():
            messagebox.showerror("", "记录目录不存在，无法记录：\r\n" + csv_dir_path_get() +
                                 "\r\n请确认路径存在（或点\"选择文件夹\"重新选择）。")
            self.timer_IncStateDisplay_Tick()
            return
        csv_pause_set(False)
        if not csv_open():
            csv_pause_set(True)
            messagebox.showerror("", "开始记录失败：" + csv_state_text_get())
            self.timer_IncStateDisplay_Tick()
            return
        self.inc_state_info_text = ""
        self.timer_IncStateDisplay_Tick()

    def pushButton_DataRecordPause_Click(self):
        """
            “停止记录”按钮：关闭当前CSV文件；之后继续显示数据但不写盘
        """
        csv_pause_set(True)
        csv_close()
        self.inc_state_info_text = ""
        self.timer_IncStateDisplay_Tick()

    def inc_data_save_dir_save(self, directory):
        """
            把数据记录目录写入config.xml的<IncDataSaveDir>

        Args:
            directory (str): 记录目录路径

        Returns:
            bool: 写入成功返回True

        Raises:

        Note:
            未记录时才会调用（记录中不允许改路径）。

        """
        try:
            tree = Et.parse('config.xml')
            root = tree.getroot()
            item = None
            for element in root.iter('IncDataSaveDir'):
                item = element
            if item == None:
                item = Et.SubElement(root, 'IncDataSaveDir')
            item.text = str(directory)
            tree.write('config.xml', encoding='utf-8', xml_declaration=False)
            return True
        except:
            return False

    def pushButton_AccCalRun_Click(self):
        """
            加速度计校准的"自动运行"按钮的鼠标点击事件函数
        """
        if self.pushButton_AccCalRun.text() == "自动运行":
            # 检查测斜仪是否已连接
            if not incRawData.inc_array_data_is_available:
                messagebox.showerror("", "未连接测斜仪！")
                return

            # 检查转台是否使能
            if not OFFLINE_DEBUG:
                if (not turntableState.is_inner_axis_in_enable) or (not turntableState.is_outer_axis_in_enable):
                    messagebox.showerror("", "未使能转台轴！")
                    return

            # 检查温箱是否运行
            if not OFFLINE_DEBUG:
                if self.checkBox_TemperatureControlEnable.isChecked():
                    if not tcState.is_fixed_value_startup:
                        messagebox.showerror("", "未启动温箱定值运行！")
                        return

            # 检查是否已选择存储加速度数据的根目录
            pos_gxyz_excel_file_root_directory_path = self.textEdit_AccDataSaveDirectory_Auto.toPlainText()
            if pos_gxyz_excel_file_root_directory_path == "":
                messagebox.showerror("", "没有选择加速度数据存储目录！")
                return

            # 温控预处理
            ret = self.temperature_ctrl_preprocess()
            if not ret:
                return

            # 检查是否已输入运行次数
            if self.lineEdit_RunNum.text() == "":
                messagebox.showerror("", "没有输入运行次数！")
                return
            accCalCtrl.run_num = int(self.lineEdit_RunNum.text())

            # 根据勾选框，确定是否需要进行椭球拟合等操作
            accCalCtrl.cal_ctrl_of_acc_cal.cal_enable = False
            accCalCtrl.cal_ctrl_of_total_acceleration_check.cal_enable = False
            accCalCtrl.cal_ctrl_of_acc_turntable_misalign_cal.cal_enable = False
            accCalCtrl.cal_ctrl_of_acc_calibration_angle_check.cal_enable = False
            accCalCtrl.cal_ctrl_of_acc_temperature_drift_verify.cal_enable = False
            if self.checkBox_EllipsoidFitting.isChecked():
                ret = self.acc_cal_preprocess()
                if not ret:
                    return
            if self.checkBox_TotalAccelerationCheck.isChecked():
                ret = self.total_acceleration_check_preprocess()
                if not ret:
                    return

            # 初始化进度条
            position_num_total = 0
            if self.checkBox_EllipsoidFitting.isChecked():
                position_num_total += accCalCtrl.cal_ctrl_of_acc_cal.turntable_positions.shape[0]
            if self.checkBox_TotalAccelerationCheck.isChecked():
                position_num_total += accCalCtrl.cal_ctrl_of_total_acceleration_check.turntable_positions.shape[0]
            position_num_total = position_num_total * len(accCalCtrl.temperature_ctrl.tc_sp_str_arr)
            self.progressBar_AccCalInit(position_num_total)

            # 创建并启动自动运行线程
            thread_of_acc_cal_create_and_start()

            # 保存参数
            self.record_user_habits()

            autoRunState.thread_lock.acquire()
            autoRunState.auto_run_info = ""  # 清空自动运行状态信息栏
            autoRunState.auto_run_state = "运行"
            autoRunState.thread_lock.release()
            autoRunState.button_text_AccCalRun = "停止"
            self.pushButton_AccCalRun.setText("停止")
            self.tabWidget_IncCal.setCurrentIndex(1) # 跳转至运行状态页面
        elif self.pushButton_AccCalRun.text() == "停止":
            thread_of_acc_cal_terminate()
            accCalCtrl.run_count = 0
            messagebox.showwarning("", "已中止运行！")
            autoRunState.thread_lock.acquire()
            autoRunState.auto_run_state = "停止"
            autoRunState.button_text_AccCalRun = "自动运行"
            autoRunState.thread_lock.release()
            self.pushButton_AccCalRun.setText("自动运行")

    def temperature_ctrl_preprocess(self):
        """
        温控预处理

        Args:
            None

        Returns:
            bool : 温控预处理成功，返回True；温控预处理失败，返回False

        """
        if not self.checkBox_TemperatureControlEnable.isChecked():
            segment_index = incSegmentIndexCommSuccessfulArr[0].inc_segment_index
            accCalCtrl.temperature_ctrl.tc_sp_str_arr = [str(round(incGValueNewCalcuCtrl.inc_accelerometer_temperature_arr[segment_index], 1)) + "℃"]
            accCalCtrl.temperature_ctrl.temperature_control_enable = False
            return True

        # 检查各个温控设置是否有效
        try:
            tc_sp_arr = self.lineEdit_OperatingTemperature.text().split("，")
            for tc_sp in tc_sp_arr:
                float(tc_sp)
            float(self.lineEdit_StartTemperature.text())
            float(self.lineEdit_TemperatureRange1.text())
            float(self.lineEdit_TemperatureRange2.text())
            float(self.lineEdit_TemperatureInterval.text())
            float(self.lineEdit_TemperatureDeviation.text())
            float(self.lineEdit_TemperatureHitCount.text())
            float(self.lineEdit_TemperatureWaitTime.text())
            float(self.lineEdit_TemperatureHoldTime.text())
        except:
            messagebox.showwarning("", "温控设置不正确！")
            return False

        # 获取温控设置
        tc_sp_str_arr = []
        temperature_control_mode = self.comboBox_TemperatureControlMode.currentText()
        if temperature_control_mode == "定值模式":
            tc_sp_arr = self.lineEdit_OperatingTemperature.text().split("，")
            tc_sp_str_arr = []
            for tc_sp in tc_sp_arr:
                tc_sp_str_arr.append(tc_sp + "℃")
        elif temperature_control_mode == "程序模式":
            start_temperature = float(self.lineEdit_StartTemperature.text())
            temperature_range1 = float(self.lineEdit_TemperatureRange1.text())
            temperature_range2 = float(self.lineEdit_TemperatureRange2.text())
            temperature_interval = float(self.lineEdit_TemperatureInterval.text())
            tc_sp_str_arr = tc_sps_creat(start_temperature,
                                         temperature_range1,
                                         temperature_range2,
                                         temperature_interval)
        accCalCtrl.temperature_ctrl.tc_sp_str_arr = tc_sp_str_arr
        accCalCtrl.temperature_ctrl.temperature_deviation = float(self.lineEdit_TemperatureDeviation.text())
        accCalCtrl.temperature_ctrl.temperature_hit_count = int(self.lineEdit_TemperatureHitCount.text())
        accCalCtrl.temperature_ctrl.temperature_wait_time = float(self.lineEdit_TemperatureWaitTime.text())
        accCalCtrl.temperature_ctrl.temperature_hold_time = float(self.lineEdit_TemperatureHoldTime.text())
        if self.checkBox_TemperatureControlEnable.isChecked():
            accCalCtrl.temperature_ctrl.temperature_control_enable = True
        else:
            accCalCtrl.temperature_ctrl.temperature_control_enable = False

        return True

    def acc_cal_preprocess(self):
        """
        加速度计校准预处理

        Args:
            None

        Returns:
            bool : 加速度计校准预处理成功，返回True；加速度计校准预处理失败，返回False

        """
        accCalCtrl.cal_ctrl_of_acc_cal.cal_enable = self.checkBox_EllipsoidFitting.isChecked()
        accCalCtrl.cal_ctrl_of_acc_cal.cal_data_upload_enable = self.checkBox_AccCalFTPPush.isChecked()
        accCalCtrl.lm_calculate_enable = self.checkBox_LMCalculate.isChecked()
        accCalCtrl.acc_tdc_calcu_enable = self.checkBox_AccTdcCalcuEnable.isChecked()
        accCalCtrl.tps_comp_calcu_enable = self.checkBox_TpsCompCalcuEnable.isChecked()

        # 检查是否已输入平均次数
        try:
            average_num = int(self.lineEdit_AverageNumOfAccCal.text())
            aia_enable = self.checkBox_AIAEnableOfAccCal.isChecked()
            accCalCtrl.cal_ctrl_of_acc_cal.average_num = average_num
            accCalCtrl.cal_ctrl_of_acc_cal.aia_enable = aia_enable
        except:
            messagebox.showerror("", "输入的加速度计校准平均次数不合法！")
            return False

        # 检查是否已输入位置数
        if self.lineEdit_PositionNumOfAccCal.text() == "":
            messagebox.showerror("", "没有输入椭球拟合位置数！")
            return False
        position_num = int(self.lineEdit_PositionNumOfAccCal.text())
        if position_num < 6:
            position_num = 6
            messagebox.showinfo("", "位置数必须大于等于6或平方根为整数！ ")
        elif position_num > 6:
            position_num_sqrt = round(numpy.sqrt(position_num))
            position_num = position_num_sqrt * position_num_sqrt
        self.lineEdit_PositionNumOfAccCal.setText(str(position_num))

        # 生成转台运转的位置坐标
        accCalCtrl.cal_ctrl_of_acc_cal.turntable_positions = ellipsoid_lm_fitting_turntable_positions_creat(position_num)

        # 创建存储加速度数据的目录:以"时间+位置数"命名
        try:
            pos_gxyz_excel_file_root_directory_path = self.textEdit_AccDataSaveDirectory_Auto.toPlainText()
            pos_gxyz_excel_file_directory_name = datetime.now().strftime("%Y%m%d%H%M%S") + "_椭球拟合_" + str(position_num) + "位置"
            pos_gxyz_excel_file_directory_path = os.path.join(pos_gxyz_excel_file_root_directory_path, pos_gxyz_excel_file_directory_name)
            os.mkdir(pos_gxyz_excel_file_directory_path)
            accCalCtrl.cal_ctrl_of_acc_cal.pos_gxyz_excel_file_directory_path = pos_gxyz_excel_file_directory_path
            accCalCtrl.cal_ctrl_of_acc_cal.cal_result_excel_file_directory_path = pos_gxyz_excel_file_directory_path
        except:
            return False

        # 创建存储加速度数据的文件
        try:
            pos_gxyz_excel_file_name = ""
            pos_gxyz_excel_file_path = ""
            excel_sheet_names = accCalCtrl.temperature_ctrl.tc_sp_str_arr
            excel_sheet_index = 0
            for inc_segment_index_comm_cuccessful in incSegmentIndexCommSuccessfulArr:
                segment_index = inc_segment_index_comm_cuccessful.inc_segment_index_of_max_segment_num
                sn = incPara.segment_sn_arr[segment_index]
                pos_gxyz_excel_file_name = sn + "_pos_gxyz" + ".xlsx"
                pos_gxyz_excel_file_path = os.path.join(pos_gxyz_excel_file_directory_path, pos_gxyz_excel_file_name)
                excel_work_book = openpyxl.Workbook()
                for excel_sheet in excel_work_book.worksheets:  # 删除默认表
                    excel_work_book.remove_sheet(excel_sheet)
                for excel_sheet_name in excel_sheet_names:
                    excel_work_book.create_sheet(index=excel_sheet_index, title=excel_sheet_name)
                    sheet = excel_work_book[excel_sheet_name]
                    list_temp = ["TimeStamp", "Pos"]
                    list_temp.append("G" + "X")
                    list_temp.append("G" + "Y")
                    list_temp.append("G" + "Z")
                    list_temp.append("温箱温度")
                    list_temp.append("温度传感器温度")
                    list_temp.append("数据有效性")
                    list_temp.append("温度传感器AD值")
                    sheet.append(list_temp)  # 添加表
                    excel_sheet_index += 1
                # 创建info表
                excel_sheet_name = "info"
                excel_work_book.create_sheet(index=excel_sheet_index, title=excel_sheet_name)
                sheet = excel_work_book[excel_sheet_name]
                list_temp = ["文件类别",
                             "序列号",
                             "运行次数",
                             "转台位置数",
                             "温控模式",
                             "温控开启",
                             "运行温度",
                             "温度偏差", "温度命中次数", "温度等待时间",
                             "保温时间",
                             "平均次数",
                             "转台型号",
                             "椭球拟合位置数",
                             "测斜仪型号"]
                sheet.append(list_temp)
                sheet.cell(2, 1).value = "位置-原始加速度值(加速度计校准)"
                sheet.cell(2, 2).value = sn
                sheet.cell(2, 3).value = self.lineEdit_RunNum.text()
                sheet.cell(2, 4).value = str(position_num)
                sheet.cell(2, 5).value = self.comboBox_TemperatureControlMode.currentText()
                if self.checkBox_TemperatureControlEnable.isChecked():
                    sheet.cell(2, 6).value = "是"
                else:
                    sheet.cell(2, 6).value = "否"
                tc_sp_strs = ""
                for tc_sp_str in accCalCtrl.temperature_ctrl.tc_sp_str_arr:
                    tc_sp_strs += tc_sp_str
                    tc_sp_strs += ","
                sheet.cell(2, 7).value = tc_sp_strs[:-1]
                sheet.cell(2, 8).value = self.lineEdit_TemperatureDeviation.text() + "℃"
                sheet.cell(2, 9).value = self.lineEdit_TemperatureHitCount.text() + "次"
                sheet.cell(2, 10).value = self.lineEdit_TemperatureWaitTime.text() + "分钟"
                sheet.cell(2, 11).value = self.lineEdit_TemperatureHoldTime.text() + "分钟"
                if aia_enable:
                    sheet.cell(2, 12).value = "AIA" + str(average_num)
                else:
                    sheet.cell(2, 12).value = "NoAIA" + str(average_num)
                sheet.cell(2, 13).value = turntableComm.turntable_model
                sheet.cell(2, 14).value = str(position_num)
                sheet.cell(2, 15).value = incPara.inc_model
                excel_work_book.save(pos_gxyz_excel_file_path)
                excel_work_book.close()
        except:
            return False

        return True

    def total_acceleration_check_preprocess(self):
        """
        总加速度检验预处理

        Args:
            None

        Returns:
            bool : 总加速度检验预处理成功，返回True；总加速度检验预处理失败，返回False

        """
        accCalCtrl.cal_ctrl_of_total_acceleration_check.cal_enable = self.checkBox_TotalAccelerationCheck.isChecked()

        # 检查是否已输入平均次数
        try:
            average_num = int(self.lineEdit_AverageNumOfTotalAccelerationCheck.text())
            aia_enable = self.checkBox_AIAEnableOfTotalAccelerationCheck.isChecked()
            accCalCtrl.cal_ctrl_of_total_acceleration_check.average_num = average_num
            accCalCtrl.cal_ctrl_of_total_acceleration_check.aia_enable = aia_enable
        except:
            messagebox.showerror("", "输入的总加速度检验平均次数不合法！")
            return False

        # 转台运转的位置数
        if self.lineEdit_PositionNumOfAccCal.text() == "64":
            position_num = 16
        elif self.lineEdit_PositionNumOfAccCal.text() == "25":
            position_num = 6
        else:
            position_num = 16

        # 检查exe目录下的calibration目录下是否存在椭球或LM拟合结果文件
        if not self.checkBox_EllipsoidFitting.isChecked(): # 勾选了椭球拟合，不需要检查！
            exe_path = os.path.dirname(os.path.realpath(sys.argv[0]))
            ellipsoid_or_lm_result_excel_file_directory_path = os.path.join(exe_path, 'calibration')
            for inc_segment_index_comm_cuccessful in incSegmentIndexCommSuccessfulArr:
                segment_index = inc_segment_index_comm_cuccessful.inc_segment_index_of_max_segment_num
                sn = incPara.segment_sn_arr[segment_index]
                ellipsoid_result_excel_file_name = sn + "_ellipsoid_result" + ".xlsx"
                lm_result_excel_file_name = sn + "_lm_result" + ".xlsx"
                ellipsoid_result_excel_file_path = os.path.join(ellipsoid_or_lm_result_excel_file_directory_path,
                                                                ellipsoid_result_excel_file_name)
                lm_result_excel_file_path = os.path.join(ellipsoid_or_lm_result_excel_file_directory_path,
                                                         lm_result_excel_file_name)
                if (not os.path.exists(ellipsoid_result_excel_file_path)) and \
                   (not os.path.exists(lm_result_excel_file_path)):
                    messagebox.showerror("",
                                         ellipsoid_result_excel_file_path + "或" + lm_result_excel_file_path + "不存在！")
                    return False

        # 生成转台运转的位置坐标
        accCalCtrl.cal_ctrl_of_total_acceleration_check.turntable_positions = total_acceleration_check_turntable_positions_creat()

        # 创建存储加速度数据的目录:以"时间+位置数"命名
        try:
            pos_gxyz_excel_file_root_directory_path = self.textEdit_AccDataSaveDirectory_Auto.toPlainText()
            pos_gxyz_excel_file_directory_name = datetime.now().strftime("%Y%m%d%H%M%S") + "_总加速度检验"
            pos_gxyz_excel_file_directory_path = os.path.join(pos_gxyz_excel_file_root_directory_path, pos_gxyz_excel_file_directory_name)
            os.mkdir(pos_gxyz_excel_file_directory_path)
            accCalCtrl.cal_ctrl_of_total_acceleration_check.pos_gxyz_excel_file_directory_path = pos_gxyz_excel_file_directory_path
            accCalCtrl.cal_ctrl_of_total_acceleration_check.cal_result_excel_file_directory_path = pos_gxyz_excel_file_directory_path
        except:
            return False

        # 创建存储加速度数据的文件
        try:
            pos_gxyz_excel_file_name = ""
            pos_gxyz_excel_file_path = ""
            excel_sheet_names = accCalCtrl.temperature_ctrl.tc_sp_str_arr
            excel_sheet_index = 0
            for inc_segment_index_comm_cuccessful in incSegmentIndexCommSuccessfulArr:
                segment_index = inc_segment_index_comm_cuccessful.inc_segment_index_of_max_segment_num
                sn = incPara.segment_sn_arr[segment_index]
                pos_gxyz_excel_file_name = sn + "_pos_gxyz" + ".xlsx"
                pos_gxyz_excel_file_path = os.path.join(pos_gxyz_excel_file_directory_path, pos_gxyz_excel_file_name)
                excel_work_book = openpyxl.Workbook()
                for excel_sheet in excel_work_book.worksheets:  # 删除默认表
                    excel_work_book.remove_sheet(excel_sheet)
                for excel_sheet_name in excel_sheet_names:
                    excel_work_book.create_sheet(index=excel_sheet_index, title=excel_sheet_name)
                    sheet = excel_work_book[excel_sheet_name]
                    list_temp = ["TimeStamp", "Pos"]
                    list_temp.append("G" + "X")
                    list_temp.append("G" + "Y")
                    list_temp.append("G" + "Z")
                    list_temp.append("温箱温度")
                    list_temp.append("温度传感器温度")
                    list_temp.append("数据有效性")
                    list_temp.append("温度传感器AD值")
                    sheet.append(list_temp)  # 添加表
                    excel_sheet_index += 1
                # 创建info表
                excel_sheet_name = "info"
                excel_work_book.create_sheet(index=excel_sheet_index, title=excel_sheet_name)
                sheet = excel_work_book[excel_sheet_name]
                list_temp = ["文件类别",
                             "序列号",
                             "运行次数",
                             "转台位置数",
                             "温控模式",
                             "温控开启",
                             "运行温度",
                             "温度偏差", "温度命中次数", "温度等待时间",
                             "保温时间",
                             "平均次数",
                             "转台型号",
                             "总加速度检验位置数",
                             "测斜仪型号"]
                sheet.append(list_temp)
                sheet.cell(2, 1).value = "位置-原始加速度值(总加速度检验)"
                sheet.cell(2, 2).value = sn
                sheet.cell(2, 3).value = self.lineEdit_RunNum.text()
                sheet.cell(2, 4).value = str(position_num)
                sheet.cell(2, 5).value = self.comboBox_TemperatureControlMode.currentText()
                if self.checkBox_TemperatureControlEnable.isChecked():
                    sheet.cell(2, 6).value = "是"
                else:
                    sheet.cell(2, 6).value = "否"
                tc_sp_strs = ""
                for tc_sp_str in accCalCtrl.temperature_ctrl.tc_sp_str_arr:
                    tc_sp_strs += tc_sp_str
                    tc_sp_strs += ","
                sheet.cell(2, 7).value = tc_sp_strs[:-1]
                sheet.cell(2, 8).value = self.lineEdit_TemperatureDeviation.text() + "℃"
                sheet.cell(2, 9).value = self.lineEdit_TemperatureHitCount.text() + "次"
                sheet.cell(2, 10).value = self.lineEdit_TemperatureWaitTime.text() + "分钟"
                sheet.cell(2, 11).value = self.lineEdit_TemperatureHoldTime.text() + "分钟"
                if aia_enable:
                    sheet.cell(2, 12).value = "AIA" + str(average_num)
                else:
                    sheet.cell(2, 12).value = "NoAIA" + str(average_num)
                sheet.cell(2, 13).value = turntableComm.turntable_model
                sheet.cell(2, 14).value = str(position_num)
                sheet.cell(2, 15).value = incPara.inc_model
                excel_work_book.save(pos_gxyz_excel_file_path)
                excel_work_book.close()
        except:
            return False

        return True

    def timer_AutoRunStateDisplay_Tick(self):
        """
            定时显示自动运行状态
        """
        if autoRunState.auto_run_state == "停止":
            color = "Gray"
        elif autoRunState.auto_run_state == "运行":
            color = "Green"
        elif autoRunState.auto_run_state == "错误":
            color = "Red"
        elif autoRunState.auto_run_state == "报警":
            color = "Yellow"
        else:
            color = "Gray"

        self.pushButton_AutoRunStateLight.setStyleSheet("background-color: " + color + ";")
        self.progressBar_AutoRun.setValue(autoRunState.progress_bar_value)
        self.pushButton_AccCalRun.setText(autoRunState.button_text_AccCalRun)
        self.label_AutoRunProgressInfo.setText(autoRunState.progress_info)
        if autoRunState.auto_run_state != "停止": # 自动运行停止后，不刷新信息栏，以方便看错误信息！
            self.textBrowser_AutoRunStateInfo.setText(autoRunState.auto_run_info)

    def timer_RerunRequstPoll_Tick(self):
        """轮询重新运行请求"""
        # 响应重新运行加速度计校准的请求
        if accCalCtrl.acc_cal_rerun_requst:
            accCalCtrl.acc_cal_rerun_requst = False
            self.pushButton_AccCalRun_Click()

    def get_user_habits(self):
        """
            获取“user_habits.xml”文件中记录的用户上一次使用软件的习惯
        """
        # 读取、解析、获取user_habits.xml文件中的内容
        tree = Et.parse('config.xml')
        root = tree.getroot()

    def record_user_habits(self):
        """
            记录用户在关闭转台串口前的设置
        """
        # 读取、解析、获取user_habits.xml文件中的内容
        tree = Et.parse('config.xml')
        root = tree.getroot()


        tree.write('config.xml')

    def create_timer(self, interval, task):
        """
            创建自定义QTimer，方便多次调用
        """
        timer = QTimer()
        timer.timeout.connect(task)
        timer.setInterval(interval)
        return timer

    def progressBar_AccCalInit(self, position_num):
        progress_value_acc_data_record = position_num
        total = (int)(position_num / 0.9) + 1 # 占90%进度
        remain = (int)(total * 0.1) + 1 # 其余占10%进度
        count = 6 # 剩余步骤数
        average = (int)(remain / count) + 1
        progress_value_ellipsoid_fitting = average
        progress_value_lm_calculate = average
        progress_value_total_acceleration_check = average
        progress_value_acc_turntable_misalign_calcu= average
        progress_value_acc_calibration_angle_check = average
        progress_value_acc_temperature_drift_verify = average
        progress_value_total = progress_value_acc_data_record + \
                               progress_value_ellipsoid_fitting + \
                               progress_value_lm_calculate + \
                               progress_value_total_acceleration_check + \
                               progress_value_acc_turntable_misalign_calcu + \
                               progress_value_acc_calibration_angle_check + \
                               progress_value_acc_temperature_drift_verify
        self.progressBar_AutoRun.setMinimum(0)
        self.progressBar_AutoRun.setMaximum(progress_value_total)
        self.progressBar_AutoRun.setValue(0)
        autoRunState.progress_bar_value = 0
        accCalCtrl.progress_value_ellipsoid_fitting = progress_value_ellipsoid_fitting
        accCalCtrl.progress_value_lm_calculate = progress_value_lm_calculate
        accCalCtrl.progress_value_total_acceleration_check = progress_value_total_acceleration_check
        accCalCtrl.progress_value_acc_turntable_misalign_calcu = progress_value_acc_turntable_misalign_calcu
        accCalCtrl.progress_value_acc_calibration_angle_check = progress_value_acc_calibration_angle_check
        accCalCtrl.progress_value_acc_temperature_drift_verify = progress_value_acc_temperature_drift_verify

    def refresh_inc_comm_ports(self):
        """刷新 IMU 可用串口；直接更新 .ui 中显示的下拉框。"""
        combo = self.comboBox_IncCommPortSelect
        if self.button_IncCommPortOpen.text() == "关闭串口":
            return
        try:
            if combo.view().isVisible():
                return
        except Exception:
            pass
        try:
            ports = [str(info.device) for info in serial.tools.list_ports.comports()]
        except Exception as exc:
            print(f"扫描 IMU 串口失败：{exc}")
            return
        existing = [combo.itemText(i) for i in range(combo.count())]
        current = combo.currentText()
        configured = str(getattr(tiltSensorComm, "comm_port", "") or "")
        if ports != existing or current not in ports:
            combo.blockSignals(True)
            try:
                combo.clear()
                combo.addItems(ports)
                if configured in ports:
                    combo.setCurrentText(configured)
                elif current in ports:
                    combo.setCurrentText(current)
                elif ports:
                    combo.setCurrentIndex(0)
                else:
                    combo.setCurrentIndex(-1)
            finally:
                combo.blockSignals(False)

    def button_IncCommPortOpen_Click(self):
        """
            "button_IncCommPortOpen"按钮的鼠标点击事件函数
            打开/关闭倾角仪(ASM330 IMU)通讯串口
        """
        # 读取config.xml中的倾角仪参数
        tilt_sensor_user_habits_get('config.xml')

        # 检查是否选择了串口
        combobox_text = self.comboBox_IncCommPortSelect.currentText()
        if combobox_text == "":
            messagebox.showerror("", "没有找到可用串口！" + "\r\n" + "请检查USB转串口是否插入、驱动是否已安装。")
            return
        tiltSensorComm.comm_port = combobox_text

        if self.button_IncCommPortOpen.text() == "打开串口":
            # 串口地址校验：地址不正确/不存在就弹错误框；用户不改则继续重试，数据仍记录在本地data文件夹
            inc_com_port_arr = []
            for inc_port_info in serial.tools.list_ports.comports():
                inc_com_port_arr.append(str(inc_port_info.device))
            inc_port_ok = True
            if str(combobox_text) not in inc_com_port_arr:
                inc_port_ok = False
                messagebox.showerror("", "串口地址不正确或不存在！" + "\r\n" +
                                     "当前选择 = " + str(combobox_text) + "\r\n" +
                                     "可用串口 = " + str(inc_com_port_arr) + "\r\n" +
                                     "请重新选择；若不修改，程序会继续尝试连接，" +
                                     "数据记录目录 = " + csv_dir_path_get())
            elif not tilt_sensor_comm_open():
                inc_port_ok = False
                messagebox.showerror("", "倾角仪串口打开失败！" + "\r\n" +
                                     "串口 = " + str(tiltSensorComm.comm_port) +
                                     "    波特率 = " + str(tiltSensorComm.baudrate) + "\r\n" +
                                     "程序会继续尝试连接，数据记录目录 = " + csv_dir_path_get())
            if inc_port_ok:
                self.textBrowser_IncStateInfo.clear()
            # 无论本次是否打开成功都启动数据线程：线程内每秒重试，连上后自动开始记录
            thread_of_tilt_sensor_data_get_create_and_start()
            self.button_IncCommPortOpen.setText("关闭串口")
        elif self.button_IncCommPortOpen.text() == "关闭串口":
            # 停止数据获取线程并关闭串口
            thread_of_tilt_sensor_data_get_terminate()
            tilt_sensor_comm_close()
            self.button_IncCommPortOpen.setText("打开串口")
            self.pushButton_IncStateLight.setText("未连接")
            self.pushButton_IncStateLight.setStyleSheet(
                'background: #f0f2f3; color: #7f8991; border: 1px solid #d6dce0; border-radius: 12px; font-weight: 600;')

    def _ms_to_time_text(self, ms_value):
        """
        把MCU的毫秒计数转成可读的HH:MM:SS.mmm

        Args:
            ms_value (int): 毫秒数

        Returns:
            str: 如 "00:16:11.483"

        Raises:

        Note:

        """
        total_ms = int(ms_value)
        hour = total_ms // 3600000
        minute = (total_ms // 60000) % 60
        second = (total_ms // 1000) % 60
        milli = total_ms % 1000
        return "%02d:%02d:%02d.%03d" % (hour, minute, second, milli)

    def on_app_quit(self):
        """
        程序退出时的清理：停止数据获取线程、关闭串口

        Args:
            None

        Returns:
            None

        Raises:

        Note:
            串口关闭内部会先把CSV记录文件写完并关闭，保证数据落盘。

        """
        try:
            thread_of_tilt_sensor_data_get_terminate()
        except:
            pass
        try:
            tilt_sensor_comm_close()
        except:
            pass
        try:
            # 退出时把当前记录目录保存到config.xml(手动输入的路径也能记住)
            self.inc_data_save_dir_save(csv_dir_path_get())
        except:
            pass

    def register_device_sn_field(self, line_edit, is_busy=None):
        """把需要填写 PCB 唯一编号的输入框接入现有 UID 自动识别流程。"""
        self._device_sn_auto_fill.register(line_edit, is_busy)
        # 页面注册时若 UID 已就绪，立即写入，无需等待下一次刷新。
        current_sn = tiltSensorComm.device_sn if tiltSensorComm.is_serial_opened else ""
        self._device_sn_auto_fill.update(current_sn)

    def timer_IncStateDisplay_Tick(self):
        """
            定时刷新倾角仪通讯状态（该框专门用于观察上位机与下位机通讯是否正常）
            状态灯：灰=未连接；黄=CRC校验错误；红=从机无回复/其它通讯错误；
                    绿=通讯正常；绿(文字"无数据")=通讯正常但连续≥DATA_NO_UPDATE_SEC秒没有新数据；
                    绿(文字"等待数据")=串口已打开、还没收到第一帧有效数据
        """
        # 未连接(含断开或连续失败被自动关闭)瞬间：清掉上一次的数据和统计，避免把旧数据当成当前数据显示
        if (not tiltSensorComm.is_serial_opened) and self.inc_was_connected:
            self.tableWidget_AccDataDisplay.setRowCount(0)
            self.inc_table_frame_count = tiltSensorRawData.data_update_count   # 同步帧号，避免旧帧又被补回表格
            self.inc_state_info_text = ""
        self.inc_was_connected = tiltSensorComm.is_serial_opened
        # 只展示成功读取并映射的DTS编号；关闭、断线或不支持UID时自动清空。
        device_sn = tiltSensorComm.device_sn if tiltSensorComm.is_serial_opened else ""
        if self.lineEdit_DeviceSN.text() != device_sn:
            self.lineEdit_DeviceSN.setText(device_sn)
        self._device_sn_auto_fill.update(device_sn)  # 同步 IMU标定、温补的PCB编号

        # 记录目录：正在记录时不允许修改（编辑框只读、选择按钮禁用）；未记录时才可以改
        inc_recording = csv_is_enabled()
        if self.textEdit_AccDataSaveDirectory.isReadOnly() != inc_recording:
            self.textEdit_AccDataSaveDirectory.setReadOnly(inc_recording)
        if self.pushButton_AccDataSaveDirectorySelect.isEnabled() == inc_recording:
            self.pushButton_AccDataSaveDirectorySelect.setEnabled(not inc_recording)
        self._sync_record_button()

        if not tiltSensorComm.is_serial_opened:
            light_text = "未连接"
            light_color = "Gray"
        elif tiltSensorComm.comm_error_code == MB_ERROR_CODE_CRC:
            light_text = "CRC校验错误"
            light_color = "yellow"
        elif tiltSensorComm.comm_error_code == MB_ERROR_CODE_TIMEOUT:
            light_text = "从机无回复"
            light_color = "red"
        elif tiltSensorComm.comm_error_code != MB_ERROR_CODE_FREE:
            light_text = tilt_sensor_comm_error_text_get()
            light_color = "red"
        elif tiltSensorComm.is_data_no_update:
            # 通讯是通的，只是设备连续≥DATA_NO_UPDATE_SEC秒没给新数据(读到的都是未更新帧)：
            #   仍用绿底，只把文字提示改成"无数据"，避免误报成通讯故障
            light_text = "无数据"
            light_color = "green"
        elif tiltSensorComm.is_data_available:
            light_text = "通讯正常"
            light_color = "green"
        else:
            # 串口已打开、但还没收到第一帧有效数据(例如刚点开串口)
            light_text = "等待数据"
            light_color = "green"
        if self.pushButton_IncStateLight.text() != light_text:
            self.pushButton_IncStateLight.setText(light_text)
        # 低饱和玻璃状态胶囊，避免运行时覆盖主题为刺眼的纯绿/纯红背景。
        light_palette = {
            "Gray": ("#f0f2f3", "#7f8991", "#d6dce0"),
            "green": ("#eaf3ee", "#42765e", "#c4dfd0"),
            "yellow": ("#faf3e4", "#956d30", "#ead8b0"),
            "red": ("#f9eaea", "#a45c5c", "#eccbcb"),
        }
        bg, fg, border = light_palette.get(light_color, light_palette["Gray"])
        light_style = ("background: %s; color: %s; border: 1px solid %s; "
                       "border-radius: 12px; font-weight: 600;") % (bg, fg, border)
        if self.pushButton_IncStateLight.styleSheet() != light_style:
            self.pushButton_IncStateLight.setStyleSheet(light_style)

        # 把最新一帧的16组数据追加到"加速度数据"页表格（滚动历史，温度16行同值）
        if tiltSensorRawData.data_update_count > self.inc_table_frame_count:
            inc_table = self.tableWidget_AccDataDisplay
            inc_scroll_bar = inc_table.verticalScrollBar()
            inc_scroll_before = inc_scroll_bar.value()
            inc_frame_index = tiltSensorRawData.data_update_count
            for inc_sample_index in range(len(tiltSensorRawData.acc_g_arr)):
                inc_acc_g = tiltSensorRawData.acc_g_arr[inc_sample_index]
                inc_gyr_dps = tiltSensorRawData.gyr_dps_arr[inc_sample_index]
                inc_text_arr = ["%.4f" % inc_acc_g[0], "%.4f" % inc_acc_g[1], "%.4f" % inc_acc_g[2],
                                "%.2f" % inc_gyr_dps[0], "%.2f" % inc_gyr_dps[1], "%.2f" % inc_gyr_dps[2],
                                "%.2f" % tiltSensorRawData.temp_c_arr[inc_sample_index]]
                inc_new_row = inc_table.rowCount()
                inc_table.insertRow(inc_new_row)
                for inc_col in range(7):
                    inc_item = QTableWidgetItem(inc_text_arr[inc_col])
                    inc_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    inc_table.setItem(inc_new_row, inc_col, inc_item)
                inc_table.setVerticalHeaderItem(inc_new_row,
                                                QTableWidgetItem("%d-%d" % (inc_frame_index, inc_sample_index)))
            # 保留行数：勾选=实时跟随(INC_TABLE_KEEP_ROWS行)；取消=暂停跟随但保留更多历史(便于任意翻看)
            inc_follow_bottom = self.checkBox_AccDataAutoScroll.isChecked()
            if inc_follow_bottom:
                inc_keep_rows = INC_TABLE_KEEP_ROWS
            else:
                inc_keep_rows = INC_TABLE_KEEP_ROWS_PAUSED
            inc_removed_rows = 0
            while inc_table.rowCount() > inc_keep_rows:
                inc_table.removeRow(0)
                inc_removed_rows += 1
            if inc_follow_bottom:
                inc_table.scrollToBottom()       # 勾选：自动跟随最新数据
            elif inc_removed_rows > 0:
                # 取消勾选：补偿被裁掉的旧行高度，保证你正在看的位置一动不动(可任意滑动)
                inc_row_height = inc_table.rowHeight(0)
                if inc_row_height <= 0:
                    inc_row_height = 20
                inc_scroll_bar.setValue(max(inc_scroll_bar.minimum(),
                                            inc_scroll_before - inc_removed_rows * inc_row_height))
            self.inc_table_frame_count = inc_frame_index

        if not tiltSensorComm.is_serial_opened:
            # 未连接：只显示连接参数，统计/收发报文/数据状态都不显示上一次的旧内容
            info = "串口 = %s    波特率 = %d    从机地址 = %d\r\n" % (
                tiltSensorComm.comm_port, tiltSensorComm.baudrate, tiltSensorComm.comm_addr)
            info += "通讯状态 = 未连接\r\n"
            info += "数据状态 = 未连接\r\n"
            info += "记录 = %s\r\n" % csv_state_text_get()
        else:
            success_rate = 0.0
            if tiltSensorComm.comm_total_count > 0:
                success_rate = tiltSensorComm.comm_success_count * 100.0 / tiltSensorComm.comm_total_count
            info = "串口 = %s    波特率 = %d    从机地址 = %d\r\n" % (
                tiltSensorComm.comm_port, tiltSensorComm.baudrate, tiltSensorComm.comm_addr)
            info += "轮询帧率 = %.1f帧/s    帧间隔 = %.3fms    单帧耗时 = %.2fms\r\n" % (
                tiltSensorComm.comm_rate, tiltSensorComm.frame_interval_ms, tiltSensorComm.frame_time_ms)
            info += "成功率 = %.1f%%(%d/%d)    最后成功 = %s\r\n" % (
                success_rate, tiltSensorComm.comm_success_count, tiltSensorComm.comm_total_count,
                tiltSensorComm.last_success_time_text)
            info += "通讯状态 = %s    错误码 = %d    未读批次 = %d\r\n" % (
                tilt_sensor_comm_error_text_get(), tiltSensorComm.comm_error_code,
                tiltSensorRawData.data_unread)
            if tiltSensorComm.data_zero_start_time_sec > 0:
                no_update_sec = time.time() - tiltSensorComm.data_zero_start_time_sec
                if tiltSensorComm.is_data_no_update:
                    data_state_text = "无数据(已%.1fs未更新)" % no_update_sec
                else:
                    data_state_text = "数据未更新(%.1fs)" % no_update_sec
            else:
                data_state_text = "正常"
            info += "数据状态 = %s\r\n" % data_state_text
            info += "发送 = %s\r\n" % mb_last_tx_hex_get()
            info += "接收 = %s\r\n" % mb_last_rx_hex_get()
            info += "记录 = %s\r\n" % csv_state_text_get()

        if info == self.inc_state_info_text:
            return
        self.inc_state_info_text = info
        scroll_bar = self.textBrowser_IncStateInfo.verticalScrollBar()
        scroll_value = scroll_bar.value()
        at_bottom = scroll_value >= (scroll_bar.maximum() - 4)
        self.textBrowser_IncStateInfo.setText(info)
        if at_bottom:
            scroll_bar.setValue(scroll_bar.maximum())
        else:
            scroll_bar.setValue(scroll_value)

    def SpinBox_IncArrayNum_valueChanged(self):
        """
        "SpinBox_IncArrayNum"控件的valueChanged事件函数
        """
        array_num = self.SpinBox_IncArrayNum.value()
        segment_num = array_num * 1
        self.lineEdit_IncSegmentNum.setText(str(segment_num))

    def widget_visible_set(self):
        """
        根据配置文件里的配置，设置相应界面是否显示
        """
        # 读取配置文件里的配置，然后确定某个界面是否使能
        form_inc_cal_visible = False
        form_temperature_control_visible = False
        form_acc_cal_visible = False
        form_total_acc_check_visible = False
        cal_item = ""

        config_file_path = 'config.xml'
        cal_item = xml_read(config_file_path, 'CalItem')

        form_inc_cal_visible_text = xml_read(config_file_path, 'FormIncCalVisible')
        if form_inc_cal_visible_text == 'True':
            form_inc_cal_visible = True
        else:
            form_inc_cal_visible = False

        config_file_path = 'config.xml'
        form_temperature_control_visible_text = xml_read(config_file_path, 'FormTemperatureControlVisible')
        if form_temperature_control_visible_text == 'True':
            form_temperature_control_visible = True
        else:
            form_temperature_control_visible = False

        config_file_path = 'config.xml'
        form_acc_cal_visible_text = xml_read(config_file_path, 'FormAccCalVisible')
        if form_acc_cal_visible_text == 'True':
            form_acc_cal_visible = True
        else:
            form_acc_cal_visible = False

        config_file_path = 'config.xml'
        form_total_acc_check_visible_text = xml_read(config_file_path, 'FormTotalAccCheckVisible')
        if form_total_acc_check_visible_text == 'True':
            form_total_acc_check_visible = True
        else:
            form_total_acc_check_visible = False

        # 根据界面显示与否，设置相应界面是否显示
        if not form_inc_cal_visible:
            remove_tab_by_name(self.tabWidget_CalMain, "测斜仪校准")

        if not form_temperature_control_visible:
            remove_tab_by_name(self.tabWidget_TemperatureControl, "温控设置")

        if not form_acc_cal_visible:
            remove_tab_by_name(self.tabWidget_CalItemParaSet, "加速度计校准")
            self.checkBox_EllipsoidFitting.setChecked(False)
            self.checkBox_EllipsoidFitting.setVisible(False)

        if not form_total_acc_check_visible:
            remove_tab_by_name(self.tabWidget_CalItemParaSet, "总加速度检验")
            self.checkBox_TotalAccelerationCheck.setChecked(False)
            self.checkBox_TotalAccelerationCheck.setVisible(False)


        # 旧版未定义的另外三个布尔变量会在关闭两项校准时引发 NameError。
        if (not form_acc_cal_visible) and (not form_total_acc_check_visible):
            remove_tab_by_name(self.tabWidget_CalRun, "加速度计校准")

        # 根据某个校准项目是否使能，设置相应校准界面的控件的默认值
        self.checkBox_TemperatureControlEnable.setChecked(False)

        self.checkBox_EllipsoidFitting.setChecked(False)
        self.checkBox_TotalAccelerationCheck.setChecked(False)
        self.checkBox_LMCalculate.setChecked(False)
        self.checkBox_AccTdcCalcuEnable.setChecked(False)
        self.checkBox_TpsCompCalcuEnable.setChecked(False)
        self.checkBox_AccCalFTPPush.setChecked(False)
        if cal_item == "AccCal":
            self.checkBox_TemperatureControlEnable.setChecked(True)
            self.checkBox_EllipsoidFitting.setChecked(True)
            self.checkBox_TotalAccelerationCheck.setChecked(True)
            self.checkBox_AccTdcCalcuEnable.setChecked(True)
            self.checkBox_TpsCompCalcuEnable.setChecked(True)
            self.checkBox_AccCalFTPPush.setChecked(True)

        if cal_item == "AllCal":
            self.checkBox_TemperatureControlEnable.setChecked(True)

    def copy_and_rename(self, src_file_path, dst_dir_path, new_name):
        """
        复制并重命名文件

        Args:
            src_file_path (str): 源文件路径
            dst_dir_path (str): 目标目录路径
            new_name (str): 新文件名

        Returns:

        Raises:

        Note:

        """
        # 复制文件
        shutil.copy2(src_file_path, dst_dir_path)
        # 构建新的文件路径
        new_path = os.path.join(dst_dir_path, new_name)
        # 重命名文件
        os.rename(os.path.join(dst_dir_path, os.path.basename(src_file_path)), new_path)

    def delete_files_in_directory(self, dir_path, err_msg):
        for filename in os.listdir(dir_path):
            file_path = os.path.join(dir_path, filename)
            try:
                if os.path.isfile(file_path):
                    os.unlink(file_path)  # 删除文件
            except Exception as e:
                err_msg[0] = f"Error deleting {file_path}: {e}"
                return False
        return True

class MyComboBox(QComboBox):
    """
        重写ComboBox的showPopup函数，达到显示转台型号的功能
    """

    def showPopup(self):
        self.clear()
        turntable_models = ["2TD600", "2FDT600WK"]
        for turntable_model in turntable_models:
            self.addItem(turntable_model)
        super().showPopup()


class ComboBox_AccToTurntableMisalignCalAxisSelect(QComboBox):
    """
        重写ComboBox的showPopup函数，达到显示转台型号的功能
    """

    def showPopup(self):
        self.clear()
        axises = ["X轴", "Y轴", "Z轴"]
        for axis in axises:
            self.addItem(axis)
        super().showPopup()


class ComboBox_XDQ1CommPortSelect(QComboBox):
    def showPopup(self):
        self.clear()
        com_ports = list(serial.tools.list_ports.comports())
        for port in com_ports:
            self.addItem(port.device)
        super().showPopup()


class comboBox_ObjectOfXMarkCal(QComboBox):
    """
        重写ComboBox的showPopup函数，达到显示XMARK校准对象的功能
    """
    def showPopup(self):
        self.clear()
        axises = ["单元", "接头"]
        for axis in axises:
            self.addItem(axis)
        super().showPopup()
