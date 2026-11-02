"""转台控制界面"""
import os
import re
import time
from datetime import *
from qt_dialogs import filedialog, messagebox
import serial
import serial.tools.list_ports
import threading
from PySide6.QtGui import QRegularExpressionValidator, QFont
from PySide6.QtCore import QRegularExpression, QTimer , QRegularExpressionMatch, QCoreApplication
import xml.etree.ElementTree as Et
import openpyxl
from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill
import numpy

import sys
sys.path.append(sys.path[0]+'\\form')
sys.path.append(sys.path[0]+'\\turntable')
sys.path.append(sys.path[0]+'\\temperature_chamber')
sys.path.append(sys.path[0]+'\\tilt_sensor_calibration')
sys.path.append(sys.path[0] + '\\debug')
from ui_utils import *
from turntable_2TD600_comm import *
from turntable_2FDT600WK_comm import *
from turntable_data_get import *
from temperature_chamber_data_get import *
from auto_run_state import *


class FormTurntableCtrl:

    def __init__(self, main_window_ui):
        #
        # 创建控件
        #
        ui = main_window_ui
        self._main_window_ui = ui

        # 校准主界面分页栏
        self.tabWidget_CalMain = ui.tabWidget_CalMain

        # 关闭按钮
        self.pushButton_closeWindows = ui.pushButton_closeWindows

        # 转台型号选择
        self.button_TurntableCommPortOpen = ui.button_TurntableCommPortOpen
        self.comboBox_TurntableModelSelect = ui.comboBox_TurntableModelSelect
        self.comboBox_TurntableCommPortSelect = ui.comboBox_TurntableCommPortSelect
        self.pushButton_TurntableCommPortRefresh = ui.pushButton_TurntableCommPortRefresh

        # 转台回零
        self.pushButton_InnerReturnZero = ui.pushButton_InnerReturnZero
        self.pushButton_OuterReturnZero = ui.pushButton_OutterReturnZero
        self.pushButton_AllReturnZero = ui.pushButton_AllReturnZero

        # 内轴状态
        self.textEdit_InnerCurrentPosition = ui.textEdit_InnerCurrentPosition
        self.textEdit_InnerCurrentSpeed = ui.textEdit_InnerCurrentSpeed
        self.pushButton_InnerRunMode = ui.pushButton_InnerRunMode
        self.pushButton_InnerEnable = ui.pushButton_InnerEnable
        self.pushButton_InnerReturnToZero = ui.pushButton_InnerReturnToZero
        self.pushButton_InnerMoveInPlace = ui.pushButton_InnerMoveInPlace
        self.pushButton_InnerModel = ui.pushButton_InnerModel
        self.pushButton_InnerLockState = ui.pushButton_InnerLockState
        self.pushButton_InnerUpLimit = ui.pushButton_InnerUpLimit
        self.pushButton_InnerDownLimit = ui.pushButton_InnerDownLimit
        self.pushButton_InnerOverSpeed = ui.pushButton_InnerOverSpeed
        self.pushButton_InnerOverDiff = ui.pushButton_InnerOverDiff
        self.pushButton_InnerDriverFault = ui.pushButton_InnerDriverFault
        self.pushButton_InnerOverVoltage = ui.pushButton_InnerOverVoltage

        # 外轴状态
        self.textEdit_outerCurrentPosition = ui.textEdit_OutterCurrentPosition
        self.textEdit_outerCurrentSpeed = ui.textEdit_outterCurrentSpeed
        self.pushButton_OuterRunMode = ui.pushButton_OuterRunMode
        self.pushButton_OuterEnable = ui.pushButton_OuterEnable
        self.pushButton_OuterReturnToZero = ui.pushButton_OuterReturnToZero
        self.pushButton_OuterMoveInPlace = ui.pushButton_OuterMoveInPlace
        self.pushButton_OuterModel = ui.pushButton_OuterModel
        self.pushButton_OuterLockState = ui.pushButton_OuterLockState
        self.pushButton_OuterUpLimit = ui.pushButton_OuterUpLimit
        self.pushButton_OuterDownLimit = ui.pushButton_OuterDownLimit
        self.pushButton_OuterOverSpeed = ui.pushButton_OuterOverSpeed
        self.pushButton_OuterOverDiff = ui.pushButton_OuterOverDiff
        self.pushButton_OuterDriverFault = ui.pushButton_OuterDriverFault
        self.pushButton_OuterOverVoltage = ui.pushButton_OuterOverVoltage

        # 内轴位置运行控制
        self.lineEdit_InnerRotationAngleSet = ui.lineEdit_InnerRotationAngleSet
        self.comboBox_InnerPositionMode = ui.comboBox_InnerPositionMode
        self.lineEdit_InnerRotationSpeedSet = ui.lineEdit_InnerRotationSpeedSet
        self.pushButton_InnerRun = ui.pushButton_InnerRun
        self.pushButton_InnerStop = ui.pushButton_InnerStop

        # 外轴位置运行控制
        self.lineEdit_outerRotationAngleSet = ui.lineEdit_outerRotationAngleSet
        self.comboBox_OuterPositionMode = ui.comboBox_OuterPositionMode
        self.lineEdit_outerRotationSpeedSet = ui.lineEdit_outerRotationSpeedSet
        self.pushButton_OuterRun = ui.pushButton_OutterRun
        self.pushButton_OuterStop = ui.pushButton_OutterStop

        # 内外轴位置运行控制
        self.pushButton_AllRun = ui.pushButton_AllRun
        self.pushButton_AllStop = ui.pushButton_AllStop

        # 内轴速率运行控制
        self.lineEdit_InnerRotationSpeedForSpeedMode = ui.lineEdit_InnerRotationSpeedForSpeedMode
        self.lineEdit_InnerRotationAccelForSpeedMode = ui.lineEdit_InnerRotationAccelForSpeedMode
        self.pushButton_InnerRunForSpeedMode = ui.pushButton_InnerRunForSpeedMode
        self.pushButton_InnerStopForSpeedMode = ui.pushButton_InnerStopForSpeedMode

        # 外轴速率运行控制
        self.lineEdit_OuterRotationSpeedForSpeedMode = ui.lineEdit_OuterRotationSpeedForSpeedMode
        self.lineEdit_OuterRotationAccelForSpeedMode = ui.lineEdit_OuterRotationAccelForSpeedMode
        self.pushButton_OuterRunForSpeedMode = ui.pushButton_OuterRunForSpeedMode
        self.pushButton_OuterStopForSpeedMode = ui.pushButton_OuterStopForSpeedMode

        # 内轴摇摆运行控制
        self.lineEdit_InnerSwayAmplForSwayMode = ui.lineEdit_InnerSwayAmplForSwayMode
        self.lineEdit_InnerSwayFreqForSwayMode = ui.lineEdit_InnerSwayFreqForSwayMode
        self.pushButton_InnerRunForSwayMode = ui.pushButton_InnerRunForSwayMode
        self.pushButton_InnerStopForSwayMode = ui.pushButton_InnerStopForSwayMode

        # 外轴摇摆运行控制
        self.lineEdit_OuterSwayAmplForSwayMode = ui.lineEdit_OuterSwayAmplForSwayMode
        self.lineEdit_OuterSwayFreqForSwayMode = ui.lineEdit_OuterSwayFreqForSwayMode
        self.pushButton_OuterRunForSwayMode = ui.pushButton_OuterRunForSwayMode
        self.pushButton_OuterStopForSwayMode = ui.pushButton_OuterStopForSwayMode

        #
        # 初始化控件
        #
        self.pushButton_InnerReturnZero.setEnabled(False)
        self.pushButton_OuterReturnZero.setEnabled(False)
        self.pushButton_AllReturnZero.setEnabled(False)

        font = QFont("Arial", 13)
        font.setBold(True)
        self.textEdit_InnerCurrentPosition.setFont(font) # 设置QTextEdit中字体大小和加粗
        self.textEdit_InnerCurrentSpeed.setFont(font)
        self.textEdit_outerCurrentPosition.setFont(font)
        self.textEdit_outerCurrentSpeed.setFont(font)

        self.lineEdit_InnerRotationAngleSet.setText(str(10))
        self.comboBox_InnerPositionMode.setCurrentIndex(0)  # 默认相对位置，兼容旧版行为
        self.lineEdit_InnerRotationSpeedSet.setText(str(10))
        self.pushButton_InnerRun.setEnabled(False)
        self.pushButton_InnerStop.setEnabled(False)

        self.lineEdit_outerRotationAngleSet.setText(str(10))
        self.comboBox_OuterPositionMode.setCurrentIndex(0)  # 默认相对位置，兼容旧版行为
        self.lineEdit_outerRotationSpeedSet.setText(str(10))
        self.pushButton_OuterRun.setEnabled(False)
        self.pushButton_OuterStop.setEnabled(False)

        self.pushButton_AllRun.setEnabled(False)
        self.pushButton_AllStop.setEnabled(False)

        self.lineEdit_InnerRotationSpeedForSpeedMode.setText(str(10))
        self.lineEdit_InnerRotationAccelForSpeedMode.setText(str(10))
        self.pushButton_InnerRunForSpeedMode.setEnabled(False)
        self.pushButton_InnerStopForSpeedMode.setEnabled(False)

        self.lineEdit_OuterRotationSpeedForSpeedMode.setText(str(10))
        self.lineEdit_OuterRotationAccelForSpeedMode.setText(str(10))
        self.pushButton_OuterRunForSpeedMode.setEnabled(False)
        self.pushButton_OuterStopForSpeedMode.setEnabled(False)

        self.lineEdit_InnerSwayAmplForSwayMode.setText(str(1))
        self.lineEdit_InnerSwayFreqForSwayMode.setText(str(1))
        self.pushButton_InnerRunForSwayMode.setEnabled(False)
        self.pushButton_InnerStopForSwayMode.setEnabled(False)

        self.lineEdit_OuterSwayAmplForSwayMode.setText(str(1))
        self.lineEdit_OuterSwayFreqForSwayMode.setText(str(1))
        self.pushButton_OuterRunForSwayMode.setEnabled(False)
        self.pushButton_OuterStopForSwayMode.setEnabled(False)

        # 初始化输入限制
        self.lineEdit_input_restrictions()

        # 读取、解析、获取user_habits.xml文件中的内容
        tree = Et.parse('config.xml')
        root = tree.getroot()
        self.comboBox_TurntableModelSelect = MyComboBox(ui.comboBox_TurntableModelSelect)
        self.comboBox_TurntableModelSelect.resize(93, 31)
        for turntable_model in root.iter('TurntableModel_UserSelected'):
            self.comboBox_TurntableModelSelect.clear()
            self.comboBox_TurntableModelSelect.addItem(str(turntable_model.text))

        # 设置按钮点击事件函数
        self.button_TurntableCommPortOpen.clicked.connect(self.button_TurntableCommPortOpen_Click)
        self.pushButton_TurntableCommPortRefresh.clicked.connect(self.refresh_turntable_comm_ports)
        self.pushButton_InnerRun.clicked.connect(self.pushButton_InnerRun_Click)
        self.pushButton_OuterRun.clicked.connect(self.pushButton_OuterRun_Click)
        self.pushButton_InnerReturnZero.clicked.connect(self.pushButton_InnerReturnZero_Click)
        self.pushButton_OuterReturnZero.clicked.connect(self.pushButton_OuterReturnZero_Click)
        self.pushButton_AllReturnZero.clicked.connect(self.pushButton_AllAxisReturnZero_Click)
        self.pushButton_InnerStop.clicked.connect(self.pushButton_InnerStop_Click)
        self.pushButton_OuterStop.clicked.connect(self.pushButton_OuterStop_Click)
        self.pushButton_AllRun.clicked.connect(self.pushButton_AllRun_Click)
        self.pushButton_AllStop.clicked.connect(self.pushButton_AllStop_Click)
        self.pushButton_InnerRunForSpeedMode.clicked.connect(self.pushButton_InnerRunForSpeedMode_Click)
        self.pushButton_OuterRunForSpeedMode.clicked.connect(self.pushButton_OuterRunForSpeedMode_Click)
        self.pushButton_InnerStopForSpeedMode.clicked.connect(self.pushButton_InnerStopForSpeedMode_Click)
        self.pushButton_OuterStopForSpeedMode.clicked.connect(self.pushButton_OuterStopForSpeedMode_Click)
        self.pushButton_InnerRunForSwayMode.clicked.connect(self.pushButton_InnerRunForSwayMode_Click)
        self.pushButton_OuterRunForSwayMode.clicked.connect(self.pushButton_OuterRunForSwayMode_Click)
        self.pushButton_InnerStopForSwayMode.clicked.connect(self.pushButton_InnerStopForSwayMode_Click)
        self.pushButton_OuterStopForSwayMode.clicked.connect(self.pushButton_OuterStopForSwayMode_Click)
        self.pushButton_closeWindows.clicked.connect(self.pushButton_closeWindows_Click)

        #
        # 创建定时器
        #
        # 创建实时获取并显示两个轴位置和速度的定时器
        self.timer_InnerAxisPositionAndSpeedDisplay = self.create_timer(100,
                                                                        self.timer_InnerAxisPositionAndSpeedDisplay_Tick)
        self.timer_OuterAxisPositionAndSpeedDisplay = self.create_timer(100,
                                                                        self.timer_OuterAxisPositionAndSpeedDisplay_Tick)
        # 创建实时获取并显示内轴状态的定时器
        self.timer_InnerAxisStateDisplay = self.create_timer(100, self.timer_InnerAxisStateDisplay_Tick)

        # 创建实时获取并显示外轴状态的定时器
        self.timer_OuterAxisStateDisplay = self.create_timer(100, self.timer_OuterAxisStateDisplay_Tick)

        # 创建转台故障监测定时器
        self.timer_TurntableFaultMonitor = self.create_timer(3000, self.timer_TurntableFaultMonitor_Tick)

        #
        # 其他全局变量
        #
        self.turntable_model = ""
        self.turntable_2TD600_comm_port = ""
        self.turntable_2FDT600WK_inner_axis_comm_port = ""
        self.turntable_2FDT600WK_outer_axis_comm_port = ""
        self.turntable_fault_conut = 0 # 转台故障计数
        self.TURNTABLE_FAULT_COUNT_THRESHOLD = 5  # 转台故障计数阈值

        #
        # 获取用户习惯
        #
        self.get_user_habits()

        #
        # 设置相应界面是否显示
        #
        self.widget_visible_set()

    def button_TurntableCommPortOpen_Click(self):
        """
            "button_TurntableCommPortOpen"按钮的鼠标点击事件
            打开转台通信、使能内轴和外轴
        """
        # 检查是否选择了转台型号
        combobox_text = self.comboBox_TurntableModelSelect.currentText()
        if combobox_text == "":
            messagebox.showerror("", "转台型号未选择！")
            return
        self.turntable_model = combobox_text
        turntableComm.turntable_model = combobox_text

        # 调用 DLL 打开串口。2TD600 使用本页当前选中的 COM 口；2FDT600WK 仍使用配置文件中的双轴端口。
        if self.button_TurntableCommPortOpen.text() == "打开转台":
            if self.turntable_model == "2TD600":
                selected_port = self.comboBox_TurntableCommPortSelect.currentData()
                selected_port = str(selected_port or self.turntable_2TD600_comm_port or "").strip()
                match = re.fullmatch(r"COM(\d+)", selected_port, flags=re.IGNORECASE)
                if not match:
                    messagebox.showerror("串口未选择", "请先刷新并选择 2TD600 实际连接的 COM 口。")
                    return
                port = int(match.group(1))
                self.turntable_2TD600_comm_port = f"COM{port}"
            turntableComm.thread_lock.acquire()
            if self.turntable_model == "2TD600":
                ret = twoTD600_openPort(port, 115200)
                if not ret:
                    messagebox.showerror("", "转台通讯口打开失败！！")
                    turntableComm.thread_lock.release()
                    return
            elif self.turntable_model == "2FDT600WK":
                comm_error_code = [0]
                twoFDT600WK_setAxisTimeout(INNER_ROTATION_AXIS, 1000, comm_error_code)
                twoFDT600WK_setAxisTimeout(OUTER_ROTATION_AXIS, 1000, comm_error_code)
                port = int(self.turntable_2FDT600WK_inner_axis_comm_port[3:])
                comm_error_code = [0]
                ret = twoFDT600WK_openAxisPort(INNER_ROTATION_AXIS, port, 115200, comm_error_code)
                if not ret:
                    messagebox.showerror("", "转台内轴通讯口打开失败！！" + "错误码 = " + str(comm_error_code[0]))
                    turntableComm.thread_lock.release()
                    return
                port = int(self.turntable_2FDT600WK_outer_axis_comm_port[3:])
                comm_error_code = [0]
                ret = twoFDT600WK_openAxisPort(OUTER_ROTATION_AXIS, port, 115200, comm_error_code)
                if not ret:
                    messagebox.showerror("", "转台外轴通讯口打开失败！！" + "错误码 = " + str(comm_error_code[0]))
                    twoFDT600WK_closeAxisPort(INNER_ROTATION_AXIS, comm_error_code)
                    turntableComm.thread_lock.release()
                    return
            turntableComm.thread_lock.release()
            # 通信已打开后切换为“关闭转台”，即使后续启动步骤报错，用户也能通过同一按钮清理连接。
            self.button_TurntableCommPortOpen.setText("关闭转台")
            self.comboBox_TurntableModelSelect.setEnabled(False)
            self.comboBox_TurntableCommPortSelect.setEnabled(False)
            self.pushButton_TurntableCommPortRefresh.setEnabled(False)

            # 使能内轴和外轴
            turntableComm.thread_lock.acquire()
            if self.turntable_model == "2TD600":
                ret = twoTD600_SetAxisEnable(INNER_ROTATION_AXIS)
                if not ret:
                    messagebox.showerror("", "内轴使能失败！")
                    turntableComm.thread_lock.release()
                    return
                time.sleep(0.1)
                ret = twoTD600_SetAxisEnable(OUTER_ROTATION_AXIS)
                if not ret:
                    messagebox.showerror("", "外轴使能失败！")
                    turntableComm.thread_lock.release()
                    return
            elif self.turntable_model == "2FDT600WK":
                comm_error_code = [0]
                ret = twoFDT600WK_SetAxisEnable(INNER_ROTATION_AXIS, comm_error_code)
                if not ret:
                    messagebox.showerror("", "内轴使能失败！" + "错误码 = " + str(comm_error_code[0]))
                    turntableComm.thread_lock.release()
                    return
                ret = twoFDT600WK_SetAxisEnable(OUTER_ROTATION_AXIS, comm_error_code)
                if not ret:
                    messagebox.showerror("", "外轴使能失败！" + "错误码 = " + str(comm_error_code[0]))
                    turntableComm.thread_lock.release()
                    return
            turntableComm.thread_lock.release()

            # 使能轴后，需要延时一段时间，才能执行其他动作
            time.sleep(0.5)

            # 先启动状态反馈线程，再执行可能引起轴运动的回零指令。
            # 若回零指令失败，关闭按钮仍可通过反馈确认停车后再断使能、关闭通信。
            turntable_name = '2TD600'
            if self.turntable_model == "2TD600":
                turntable_name = '2TD600'
            elif self.turntable_model == "2FDT600WK":
                turntable_name = '2FDT600WK'
            thread_of_turntable_data_get_create_and_start(turntable_name)

            # 转台2FDT600WK回零
            turntableComm.thread_lock.acquire()
            if self.turntable_model == "2FDT600WK":
                comm_error_code = [0]
                ret = twoFDT600WK_SetAxisFindZero(INNER_ROTATION_AXIS, comm_error_code)
                if not ret:
                    messagebox.showerror("", "内轴回零失败！" + "错误码 = " + str(comm_error_code[0]))
                    turntableComm.thread_lock.release()
                    return
                ret = twoFDT600WK_SetAxisFindZero(OUTER_ROTATION_AXIS, comm_error_code)
                if not ret:
                    messagebox.showerror("", "外轴回零失败！" + "错误码 = " + str(comm_error_code[0]))
                    turntableComm.thread_lock.release()
                    return
            turntableComm.thread_lock.release()

            # 按钮全部设置为可点击
            self.all_pushbutton_setEnabled(True)
            # 启动所有定时器
            self.start_all_timers()
            # 记录本次用户的使用习惯
            self.record_user_habits()
        else:
            # 只有转台当前确实已连接时，才需要停车后再关闭通讯。
            # 应用关闭前若转台未连接，不能向未连接的DLL发送停车命令。
            need_controlled_stop = (
                self.button_TurntableCommPortOpen.text() == "关闭转台"
                and turntableComm.thread_instance is not None
            )
            if need_controlled_stop:
                # 关闭通讯前先请求两轴受控停车，并等待新的反馈确认速率接近0。
                # 这只是软件停车保护，不能替代转台硬件急停。
                try:
                    turntableComm.thread_lock.acquire()
                    if self.turntable_model == "2TD600":
                        stop_inner = twoTD600_SetAxisStop(INNER_ROTATION_AXIS)
                        stop_outer = twoTD600_SetAxisStop(OUTER_ROTATION_AXIS)
                    elif self.turntable_model == "2FDT600WK":
                        comm_error_code = [0]
                        stop_inner = twoFDT600WK_SetAxisStop(INNER_ROTATION_AXIS, comm_error_code)
                        stop_outer = twoFDT600WK_SetAxisStop(OUTER_ROTATION_AXIS, comm_error_code)
                    else:
                        stop_inner = stop_outer = False
                except Exception as exc:
                    messagebox.showerror("", "发送转台停车命令异常：" + str(exc))
                    return
                finally:
                    try:
                        turntableComm.thread_lock.release()
                    except RuntimeError:
                        pass
                if not stop_inner or not stop_outer:
                    messagebox.showerror("", "转台停车命令未全部成功，暂不关闭通讯。请检查设备并使用硬件急停（如有必要）。")
                    return

                feedback_count_before_stop = getattr(turntableData, "update_count", 0)
                stop_deadline = time.monotonic() + 5.0
                stopped_confirmed = False
                while time.monotonic() < stop_deadline:
                    feedback_is_fresh = getattr(turntableData, "update_count", 0) > feedback_count_before_stop
                    if self.turntable_model == "2TD600":
                        # 2TD600轮询线程读取实际角速度反馈。
                        stopped_condition = (
                            abs(float(turntableData.inner_axis_speed)) <= 0.05 and
                            abs(float(turntableData.outer_axis_speed)) <= 0.05
                        )
                    elif self.turntable_model == "2FDT600WK":
                        # 2FDT600WK当前轮询模块未更新角速度缓存，使用运行模式反馈确认停车状态。
                        stopped_condition = (
                            turntableState.inner_axis_run_mode_text in ("空闲", "伺服") and
                            turntableState.outer_axis_run_mode_text in ("空闲", "伺服")
                        )
                    else:
                        stopped_condition = False
                    if feedback_is_fresh and stopped_condition:
                        stopped_confirmed = True
                        break
                    time.sleep(0.05)
                if not stopped_confirmed:
                    messagebox.showwarning("", "等待两轴停止超时或未收到新的反馈，通讯保持打开。请检查实际速度，必要时使用硬件急停。")
                    return

            # 只有确认两轴反馈速率接近0后，才终止数据线程并关闭通讯。
            # 若启动流程在数据线程创建前失败，不留下终止请求，避免下次启动线程立即退出。
            if turntableComm.thread_instance is not None:
                turntableComm.terminate_thread_requst = True
                while turntableComm.thread_instance is not None:
                    time.sleep(0.01)
            else:
                turntableComm.terminate_thread_requst = False

            # 内轴和外轴断电
            turntableComm.thread_lock.acquire()
            if self.turntable_model == "2TD600":
                ret = twoTD600_SetAxisDisable(INNER_ROTATION_AXIS)
                if not ret:
                    messagebox.showerror("", "内轴断电失败！")
                time.sleep(0.1)
                ret = twoTD600_SetAxisDisable(OUTER_ROTATION_AXIS)
                if not ret:
                    messagebox.showerror("", "外轴断电失败！")
            elif self.turntable_model == "2FDT600WK":
                comm_error_code = [0]
                ret = twoFDT600WK_SetAxisDisable(INNER_ROTATION_AXIS, comm_error_code)
                if not ret:
                    messagebox.showerror("", "内轴断电失败！" + "错误码 = " + str(comm_error_code[0]))
                ret = twoFDT600WK_SetAxisDisable(OUTER_ROTATION_AXIS, comm_error_code)
                if not ret:
                    messagebox.showerror("", "外轴断电失败！" + "错误码 = " + str(comm_error_code[0]))
            turntableComm.thread_lock.release()

            # 等待一段时间
            time.sleep(0.1)

            # 关闭串口
            turntableComm.thread_lock.acquire()
            if self.turntable_model == "2TD600":
                twoTD600_closePort()
            elif self.turntable_model == "2FDT600WK":
                comm_error_code = [0]
                twoFDT600WK_closeAxisPort(INNER_ROTATION_AXIS, comm_error_code)
                twoFDT600WK_closeAxisPort(OUTER_ROTATION_AXIS, comm_error_code)
            turntableComm.thread_lock.release()

            # 记录本次用户的使用习惯
            self.record_user_habits()

            # 按钮全部设置为不可点击
            self.all_pushbutton_setEnabled(False)

            # 关闭所有定时器
            self.stop_all_timers()

            # 信号灯与数据框恢复默认设置
            self.all_signal_button_restore_default_state()
            self.button_TurntableCommPortOpen.setText("打开转台")
            self.comboBox_TurntableModelSelect.setEnabled(True)
            self.comboBox_TurntableCommPortSelect.setEnabled(True)
            self.pushButton_TurntableCommPortRefresh.setEnabled(True)

    def _set_position_for_axis(self, axis, angle, speed, absolute):
        """按所选模式执行绝对位置或相对位置运动。返回 (成功, 详细信息)。"""
        if self.turntable_model == "2TD600":
            if absolute:
                ret = twoTD600_SetAxisPosition(axis, angle, speed)
            else:
                ret = twoTD600_SetAxisOpposition(axis, angle, speed)
            return bool(ret), ""
        elif self.turntable_model == "2FDT600WK":
            comm_error_code = [0]
            if absolute:
                ret = twoFDT600WK_SetAxisPosition(axis, angle, speed, comm_error_code)
            else:
                ret = twoFDT600WK_SetAxisOpposition(axis, angle, speed, comm_error_code)
            return bool(ret), f"错误码 = {comm_error_code[0]}"
        return False, "请先连接并选择转台型号。"

    @staticmethod
    def _parse_position_values(angle_text, speed_text):
        angle = float(angle_text)
        speed = float(speed_text)
        if not numpy.isfinite(angle) or not numpy.isfinite(speed):
            raise ValueError("角度和速率必须是有限数值。")
        if speed <= 0:
            raise ValueError("位置运动的目标速率必须大于 0；方向由目标角/增量角决定。")
        return angle, speed

    def pushButton_InnerRun_Click(self):
        """内轴位置运动：由下拉框选择绝对位置或相对位置。"""
        try:
            angle, speed = self._parse_position_values(
                self.lineEdit_InnerRotationAngleSet.text(),
                self.lineEdit_InnerRotationSpeedSet.text())
        except (TypeError, ValueError) as exc:
            messagebox.showerror("参数无效", f"内轴位置参数无效：{exc}")
            return
        absolute = self.comboBox_InnerPositionMode.currentIndex() == 1
        turntableComm.thread_lock.acquire()
        try:
            ret, detail = self._set_position_for_axis(INNER_ROTATION_AXIS, angle, speed, absolute)
        except Exception as exc:
            ret, detail = False, repr(exc)
        finally:
            turntableComm.thread_lock.release()
        if ret:
            mode = "绝对位置" if absolute else "相对位置"
            messagebox.showinfo("", f"内轴{mode}运动指令已发送。")
        else:
            messagebox.showerror("", "内轴运转失败！" + (f"\n{detail}" if detail else ""))

    def pushButton_OuterRun_Click(self):
        """外轴位置运动：由下拉框选择绝对位置或相对位置。"""
        try:
            angle, speed = self._parse_position_values(
                self.lineEdit_outerRotationAngleSet.text(),
                self.lineEdit_outerRotationSpeedSet.text())
        except (TypeError, ValueError) as exc:
            messagebox.showerror("参数无效", f"外轴位置参数无效：{exc}")
            return
        absolute = self.comboBox_OuterPositionMode.currentIndex() == 1
        turntableComm.thread_lock.acquire()
        try:
            ret, detail = self._set_position_for_axis(OUTER_ROTATION_AXIS, angle, speed, absolute)
        except Exception as exc:
            ret, detail = False, repr(exc)
        finally:
            turntableComm.thread_lock.release()
        if ret:
            mode = "绝对位置" if absolute else "相对位置"
            messagebox.showinfo("", f"外轴{mode}运动指令已发送。")
        else:
            messagebox.showerror("", "外轴运转失败！" + (f"\n{detail}" if detail else ""))

    def pushButton_AllRun_Click(self):
        """按两个轴各自的模式，依次发送位置运动命令。"""
        try:
            inner_angle, inner_speed = self._parse_position_values(
                self.lineEdit_InnerRotationAngleSet.text(), self.lineEdit_InnerRotationSpeedSet.text())
            outer_angle, outer_speed = self._parse_position_values(
                self.lineEdit_outerRotationAngleSet.text(), self.lineEdit_outerRotationSpeedSet.text())
        except (TypeError, ValueError) as exc:
            messagebox.showerror("参数无效", f"多轴位置参数无效：{exc}")
            return

        inner_absolute = self.comboBox_InnerPositionMode.currentIndex() == 1
        outer_absolute = self.comboBox_OuterPositionMode.currentIndex() == 1
        turntableComm.thread_lock.acquire()
        try:
            inner_ret, inner_detail = self._set_position_for_axis(
                INNER_ROTATION_AXIS, inner_angle, inner_speed, inner_absolute)
            if not inner_ret:
                messagebox.showerror("", "内轴运转失败！" + (f"\n{inner_detail}" if inner_detail else ""))
                return
            time.sleep(0.1)
            outer_ret, outer_detail = self._set_position_for_axis(
                OUTER_ROTATION_AXIS, outer_angle, outer_speed, outer_absolute)
            if not outer_ret:
                messagebox.showerror("", "外轴运转失败！" + (f"\n{outer_detail}" if outer_detail else ""))
                return
        except Exception as exc:
            messagebox.showerror("", f"多轴位置运动异常：{exc}")
            return
        finally:
            turntableComm.thread_lock.release()
        messagebox.showinfo("", "内轴、外轴位置运动指令已发送。")

    def pushButton_InnerStop_Click(self):
        """
            "pushButton_InnerStop"按钮的鼠标点击事件
            内轴停车函数，运动过程中手动停止运转
        """
        turntableComm.thread_lock.acquire()
        if self.turntable_model == "2TD600":
            ret = twoTD600_SetAxisStop(INNER_ROTATION_AXIS)
            if ret:
                messagebox.showinfo("", "内轴停车中...")
            else:
                messagebox.showerror("", "内轴停车失败！")
        elif self.turntable_model == "2FDT600WK":
            comm_error_code = [0]
            ret = twoFDT600WK_SetAxisStop(INNER_ROTATION_AXIS, comm_error_code)
            if ret:
                messagebox.showinfo("", "内轴停车中...")
            else:
                messagebox.showerror("", "内轴停车失败！" + "错误码 = " + str(comm_error_code[0]))
        turntableComm.thread_lock.release()


    def pushButton_OuterStop_Click(self):
        """
            "pushButton_OuterStop"按钮的鼠标点击事件
            外轴停车函数，运动过程中手动停止运转
        """
        turntableComm.thread_lock.acquire()
        if self.turntable_model == "2TD600":
            ret = twoTD600_SetAxisStop(OUTER_ROTATION_AXIS)
            if ret:
                messagebox.showinfo("", "外轴停车中...")
            else:
                messagebox.showerror("", "外轴停车失败！")
        elif self.turntable_model == "2FDT600WK":
            comm_error_code = [0]
            ret = twoFDT600WK_SetAxisStop(OUTER_ROTATION_AXIS, comm_error_code)
            if ret:
                messagebox.showinfo("", "外轴停车中...")
            else:
                messagebox.showerror("", "外轴停车失败！" + "错误码 = " + str(comm_error_code[0]))
        turntableComm.thread_lock.release()


    def pushButton_AllStop_Click(self):
        turntableComm.thread_lock.acquire()
        if self.turntable_model == "2TD600":
            ret = twoTD600_SetAxisStop(INNER_ROTATION_AXIS)
            if not ret:
                messagebox.showerror("", "内轴停车失败！")
                turntableComm.thread_lock.release()
                return
            time.sleep(0.1)
            ret = twoTD600_SetAxisStop(OUTER_ROTATION_AXIS)
            if not ret:
                messagebox.showerror("", "外轴停车失败！")
                turntableComm.thread_lock.release()
                return
        elif self.turntable_model == "2FDT600WK":
            comm_error_code = [0]
            ret = twoFDT600WK_SetAxisStop(INNER_ROTATION_AXIS, comm_error_code)
            if not ret:
                messagebox.showerror("", "内轴停车失败！" + "错误码 = " + str(comm_error_code[0]))
                turntableComm.thread_lock.release()
                return
            ret = twoFDT600WK_SetAxisStop(OUTER_ROTATION_AXIS, comm_error_code)
            if not ret:
                messagebox.showerror("", "外轴停车失败！" + "错误码 = " + str(comm_error_code[0]))
                turntableComm.thread_lock.release()
                return
        turntableComm.thread_lock.release()
        messagebox.showinfo("", "内轴,外轴停车中...")

    def _notify_homing_started(self, text):
        """非阻塞反馈；仅代表回零指令已接受，并不代表两轴已到零位。"""
        from PySide6.QtWidgets import QStatusBar
        bar = self._main_window_ui.findChild(QStatusBar, "statusbar")
        if bar is not None:
            bar.showMessage(text, 12000)
        print(f"[转台] {text}")

    def _send_home_commands(self, axes):
        """原厂找零指令保持不变；通信锁始终在 finally 中释放。"""
        if self.turntable_model not in ("2TD600", "2FDT600WK"):
            messagebox.showwarning("转台未连接", "请先连接转台后再执行回零。")
            return
        errors = []
        try:
            with turntableComm.thread_lock:
                for idx, (axis, label) in enumerate(axes):
                    if self.turntable_model == "2TD600":
                        ret = twoTD600_SetAxisFindZero(axis, 10, 10)
                        detail = ""
                    else:
                        comm_error_code = [0]
                        ret = twoFDT600WK_SetAxisFindZero(axis, comm_error_code)
                        detail = f"错误码 = {comm_error_code[0]}"
                    if not ret:
                        errors.append(f"{label}回零指令失败" + (f"；{detail}" if detail else ""))
                        break
                    if idx + 1 < len(axes) and self.turntable_model == "2TD600":
                        time.sleep(0.1)
        except Exception as exc:
            errors.append(f"发送回零命令时发生异常：{exc}")
        if errors:
            messagebox.showerror("转台回零失败", "\n".join(errors) + "\n请检查轴状态和硬件安全条件。")
        else:
            self._notify_homing_started("回零命令已发送，等待转台反馈确认到位；可在转台状态区查看进度。")

    def pushButton_InnerReturnZero_Click(self):
        """内轴机械回零（不阻塞 UI 弹窗）。"""
        self._send_home_commands(((INNER_ROTATION_AXIS, "内轴"),))

    def pushButton_OuterReturnZero_Click(self):
        """外轴机械回零（不阻塞 UI 弹窗）。"""
        self._send_home_commands(((OUTER_ROTATION_AXIS, "外轴"),))

    def pushButton_AllAxisReturnZero_Click(self):
        """先内轴后外轴下发找零；保持厂商原始指令顺序。"""
        self._send_home_commands(((INNER_ROTATION_AXIS, "内轴"),
                                  (OUTER_ROTATION_AXIS, "外轴")))

    def _start_velocity_axis(self, axis, speed_text, accel_text, axis_label):
        """启动指定轴的连续速率运动，目标速率和角加速度均由界面输入。"""
        try:
            speed = float(speed_text)
            accel = float(accel_text)
            if not numpy.isfinite(speed) or not numpy.isfinite(accel):
                raise ValueError("速率和加速度必须是有限数值。")
            if abs(speed) < 1e-9:
                raise ValueError("目标速率不能为 0；如需停止，请使用停车按钮。")
            if accel <= 0:
                raise ValueError("目标角加速度必须大于 0。")
        except (TypeError, ValueError) as exc:
            messagebox.showerror("参数无效", f"{axis_label}速率运动参数无效：{exc}")
            return

        turntableComm.thread_lock.acquire()
        try:
            if self.turntable_model == "2TD600":
                ret = twoTD600_SetAxisVelocity(axis, speed, accel)
                detail = ""
            elif self.turntable_model == "2FDT600WK":
                comm_error_code = [0]
                ret = twoFDT600WK_SetAxisVelocity(axis, speed, accel, comm_error_code)
                detail = f"错误码 = {comm_error_code[0]}"
            else:
                ret = False
                detail = "请先连接并选择转台型号。"
        except Exception as exc:
            ret, detail = False, repr(exc)
        finally:
            turntableComm.thread_lock.release()

        if ret:
            messagebox.showinfo("", f"{axis_label}速率运动指令已发送。目标速率 {speed:g}°/s，加速度 {accel:g}°/s²。")
        else:
            messagebox.showerror("", f"{axis_label}运转失败！" + (f"\n{detail}" if detail else ""))

    def pushButton_InnerRunForSpeedMode_Click(self):
        self._start_velocity_axis(
            INNER_ROTATION_AXIS,
            self.lineEdit_InnerRotationSpeedForSpeedMode.text(),
            self.lineEdit_InnerRotationAccelForSpeedMode.text(),
            "内轴")

    def pushButton_OuterRunForSpeedMode_Click(self):
        self._start_velocity_axis(
            OUTER_ROTATION_AXIS,
            self.lineEdit_OuterRotationSpeedForSpeedMode.text(),
            self.lineEdit_OuterRotationAccelForSpeedMode.text(),
            "外轴")

    def pushButton_InnerStopForSpeedMode_Click(self):
        """
            "pushButton_InnerStopForSpeedMode"按钮的鼠标点击事件
            内轴停车函数，运动过程中手动停止运转
        """
        turntableComm.thread_lock.acquire()
        if self.turntable_model == "2TD600":
            ret = twoTD600_SetAxisStop(INNER_ROTATION_AXIS)
            if ret:
                messagebox.showinfo("", "内轴停车中...")
            else:
                messagebox.showerror("", "内轴停车失败！")
        elif self.turntable_model == "2FDT600WK":
            comm_error_code = [0]
            ret = twoFDT600WK_SetAxisStop(INNER_ROTATION_AXIS, comm_error_code)
            if ret:
                messagebox.showinfo("", "内轴停车中...")
            else:
                messagebox.showerror("", "内轴停车失败！" + "错误码 = " + str(comm_error_code[0]))
        turntableComm.thread_lock.release()


    def pushButton_OuterStopForSpeedMode_Click(self):
        """
            "pushButton_OuterStopForSpeedMode"按钮的鼠标点击事件
            外轴停车函数，运动过程中手动停止运转
        """
        turntableComm.thread_lock.acquire()
        if self.turntable_model == "2TD600":
            ret = twoTD600_SetAxisStop(OUTER_ROTATION_AXIS)
            if ret:
                messagebox.showinfo("", "外轴停车中...")
            else:
                messagebox.showerror("", "外轴停车失败！")
        elif self.turntable_model == "2FDT600WK":
            comm_error_code = [0]
            ret = twoFDT600WK_SetAxisStop(OUTER_ROTATION_AXIS, comm_error_code)
            if ret:
                messagebox.showinfo("", "外轴停车中...")
            else:
                messagebox.showerror("", "外轴停车失败！" + "错误码 = " + str(comm_error_code[0]))
        turntableComm.thread_lock.release()

    def pushButton_InnerRunForSwayMode_Click(self):
        """
            "pushButton_InnerRunForSwayMode"按钮的鼠标点击事件
            获取内轴手动控制器设置的摇摆幅度、摇摆频率，并启动内轴
        """
        inner_sway_ampl_text = self.lineEdit_InnerSwayAmplForSwayMode.text()
        inner_sway_freq_text = self.lineEdit_InnerSwayFreqForSwayMode.text()
        # 单轴执行相对运动
        turntableComm.thread_lock.acquire()
        if self.turntable_model == "2TD600":
            ret = twoTD600_SetAxisSway(INNER_ROTATION_AXIS, float(inner_sway_ampl_text), float(inner_sway_freq_text))
            if ret:
                messagebox.showinfo("", "内轴运转中...")
            else:
                messagebox.showerror("", "内轴运转失败！")
        elif self.turntable_model == "2FDT600WK":
            comm_error_code = [0]
            ret = twoFDT600WK_SetAxisSway(INNER_ROTATION_AXIS, float(inner_sway_ampl_text), float(inner_sway_freq_text),
                                                comm_error_code)
            if ret:
                messagebox.showinfo("", "内轴运转中...")
            else:
                messagebox.showerror("", "内轴运转失败！" + "错误码 = " + str(comm_error_code[0]))
        turntableComm.thread_lock.release()

    def pushButton_InnerStopForSwayMode_Click(self):
        """
            "pushButton_InnerStopForSwayMode"按钮的鼠标点击事件
            内轴停车函数，运动过程中手动停止运转
        """
        turntableComm.thread_lock.acquire()
        if self.turntable_model == "2TD600":
            ret = twoTD600_SetAxisStop(INNER_ROTATION_AXIS)
            if ret:
                messagebox.showinfo("", "内轴停车中...")
            else:
                messagebox.showerror("", "内轴停车失败！")
        elif self.turntable_model == "2FDT600WK":
            comm_error_code = [0]
            ret = twoFDT600WK_SetAxisStop(INNER_ROTATION_AXIS, comm_error_code)
            if ret:
                messagebox.showinfo("", "内轴停车中...")
            else:
                messagebox.showerror("", "内轴停车失败！" + "错误码 = " + str(comm_error_code[0]))
        turntableComm.thread_lock.release()

    def pushButton_OuterRunForSwayMode_Click(self):
        """
            "pushButton_OuterRunForSwayMode"按钮的鼠标点击事件
            获取外轴手动控制器设置的摇摆幅度、摇摆频率，并启动外轴
        """
        outer_sway_ampl_text = self.lineEdit_OuterSwayAmplForSwayMode.text()
        outer_sway_freq_text = self.lineEdit_OuterSwayFreqForSwayMode.text()
        # 单轴执行相对运动
        turntableComm.thread_lock.acquire()
        if self.turntable_model == "2TD600":
            ret = twoTD600_SetAxisSway(OUTER_ROTATION_AXIS, float(outer_sway_ampl_text), float(outer_sway_freq_text))
            if ret:
                messagebox.showinfo("", "外轴运转中...")
            else:
                messagebox.showerror("", "外轴运转失败！")
        elif self.turntable_model == "2FDT600WK":
            comm_error_code = [0]
            ret = twoFDT600WK_SetAxisSway(OUTER_ROTATION_AXIS, float(outer_sway_ampl_text), float(outer_sway_freq_text),
                                                comm_error_code)
            if ret:
                messagebox.showinfo("", "外轴运转中...")
            else:
                messagebox.showerror("", "外轴运转失败！" + "错误码 = " + str(comm_error_code[0]))
        turntableComm.thread_lock.release()

    def pushButton_OuterStopForSwayMode_Click(self):
        """
            "pushButton_OuterStopForSwayMode"按钮的鼠标点击事件
            外轴停车函数，运动过程中手动停止运转
        """
        turntableComm.thread_lock.acquire()
        if self.turntable_model == "2TD600":
            ret = twoTD600_SetAxisStop(OUTER_ROTATION_AXIS)
            if ret:
                messagebox.showinfo("", "外轴停车中...")
            else:
                messagebox.showerror("", "外轴停车失败！")
        elif self.turntable_model == "2FDT600WK":
            comm_error_code = [0]
            ret = twoFDT600WK_SetAxisStop(OUTER_ROTATION_AXIS, comm_error_code)
            if ret:
                messagebox.showinfo("", "外轴停车中...")
            else:
                messagebox.showerror("", "外轴停车失败！" + "错误码 = " + str(comm_error_code[0]))
        turntableComm.thread_lock.release()

    def timer_InnerAxisPositionAndSpeedDisplay_Tick(self):
        """
            定时获取和显示内轴的实时位置和速度
        """
        position = turntableData.inner_axis_position
        self.textEdit_InnerCurrentPosition.setText(f"{position:.4f}")
        speed = turntableData.inner_axis_speed
        self.textEdit_InnerCurrentSpeed.setText(f"{speed:.4f}")

    def timer_OuterAxisPositionAndSpeedDisplay_Tick(self):
        """
            获取外轴的实时位置和速度
        """
        position = turntableData.outer_axis_position
        self.textEdit_outerCurrentPosition.setText(f"{position:.4f}")
        speed = turntableData.outer_axis_speed
        self.textEdit_outerCurrentSpeed.setText(f"{speed:.4f}")
        # threadLock.acquire()
        # current_position = twoTD600_getPosition(OUTER_ROTATION_AXIS)
        # threadLock.release()
        # # 截取至小数点后第四位
        # re_current_position = "%.4f" % current_position
        # self.textEdit_outerCurrentPosition.setText(re_current_position)
        # turntableData.outer_axis_position = float(re_current_position)
        #
        # threadLock.acquire()
        # current_speed = twoTD600_getSpeed(OUTER_ROTATION_AXIS)
        # threadLock.release()
        # # 截取至小数点后第四位
        # re_current_speed = "%.4f" % current_speed
        # self.textEdit_outerCurrentSpeed.setText(re_current_speed)

    def timer_InnerAxisStateDisplay_Tick(self):
        """
         定时获取和显示内轴状态
        """
        # 获取和显示内轴运行模式
        inner_axis_run_mode_text = turntableState.inner_axis_run_mode_text
        self.pushButton_InnerRunMode.setText(inner_axis_run_mode_text)

        # 获取和显示内轴的使能情况
        InnerEnable = turntableState.is_inner_axis_in_enable
        if not InnerEnable:
            self.pushButton_InnerEnable.setText("未使能")
            self.pushButton_InnerEnable.setStyleSheet('background: #f9e9e9; color: #a35d5d; border: 1px solid #eccaca; border-radius: 7px;')
        elif InnerEnable:
            self.pushButton_InnerEnable.setText("已使能")
            self.pushButton_InnerEnable.setStyleSheet('background: #e9f3ed; color: #43745b; border: 1px solid #cce1d3; border-radius: 7px;')

        # 获取内轴的找零情况
        InnerToZero = turntableState.is_inner_axis_find_zero
        if not InnerToZero:
            self.pushButton_InnerReturnToZero.setText("未找零")
            self.pushButton_InnerReturnToZero.setStyleSheet('background: #f9e9e9; color: #a35d5d; border: 1px solid #eccaca; border-radius: 7px;')
        elif InnerToZero:
            self.pushButton_InnerReturnToZero.setText("已找零")
            self.pushButton_InnerReturnToZero.setStyleSheet('background: #e9f3ed; color: #43745b; border: 1px solid #cce1d3; border-radius: 7px;')

        # 获取内轴的到位情况
        InnerMove = turntableState.is_inner_axis_in_place
        if not InnerMove:
            self.pushButton_InnerMoveInPlace.setText("未到位")
            self.pushButton_InnerMoveInPlace.setStyleSheet('background: #f9e9e9; color: #a35d5d; border: 1px solid #eccaca; border-radius: 7px;')
            turntableData.is_inner_axis_in_place = False
        elif InnerMove:
            self.pushButton_InnerMoveInPlace.setText("已到位")
            self.pushButton_InnerMoveInPlace.setStyleSheet('background: #e9f3ed; color: #43745b; border: 1px solid #cce1d3; border-radius: 7px;')
            turntableData.is_inner_axis_in_place = True

        # 获取内轴的正常情况
        is_inner_axis_normal = turntableState.is_inner_axis_normal
        if not is_inner_axis_normal:
            self.pushButton_InnerModel.setText("异常" + "(" + str(turntableState.inner_axis_alarm_code) + ")")
            self.pushButton_InnerModel.setStyleSheet('background: #f9e9e9; color: #a35d5d; border: 1px solid #eccaca; border-radius: 7px;')
        elif is_inner_axis_normal:
            self.pushButton_InnerModel.setText("正常")
            self.pushButton_InnerModel.setStyleSheet('background: #e9f3ed; color: #43745b; border: 1px solid #cce1d3; border-radius: 7px;')

        # 获取内轴的锁紧情况
        InnerLock = turntableState.is_inner_axis_is_lock
        if not InnerLock:
            self.pushButton_InnerLockState.setText("未锁紧")
            self.pushButton_InnerLockState.setStyleSheet('background: #e9f3ed; color: #43745b; border: 1px solid #cce1d3; border-radius: 7px;')
        elif InnerLock:
            self.pushButton_InnerLockState.setText("已锁紧")
            self.pushButton_InnerLockState.setStyleSheet('background: #f9e9e9; color: #a35d5d; border: 1px solid #eccaca; border-radius: 7px;')

        # 获取内轴的触碰上限位情况
        InnerUpLimit = turntableState.is_inner_axis_up_limit
        if not InnerUpLimit:
            self.pushButton_InnerUpLimit.setText("上限位")
            self.pushButton_InnerUpLimit.setStyleSheet('background: #e9f3ed; color: #43745b; border: 1px solid #cce1d3; border-radius: 7px;')
        elif InnerUpLimit:
            self.pushButton_InnerUpLimit.setText("触碰上限")
            self.pushButton_InnerUpLimit.setStyleSheet('background: #f9e9e9; color: #a35d5d; border: 1px solid #eccaca; border-radius: 7px;')

        # 获取内轴的触碰下限位情况
        InnerDownLimit = turntableState.is_inner_axis_down_limit
        if not InnerDownLimit:
            self.pushButton_InnerDownLimit.setText("下限位")
            self.pushButton_InnerDownLimit.setStyleSheet('background: #e9f3ed; color: #43745b; border: 1px solid #cce1d3; border-radius: 7px;')
        elif InnerDownLimit:
            self.pushButton_InnerDownLimit.setText("触碰下限")
            self.pushButton_InnerDownLimit.setStyleSheet('background: #f9e9e9; color: #a35d5d; border: 1px solid #eccaca; border-radius: 7px;')

        # 获取内轴的超速情况
        InnerOverSpeed = turntableState.is_inner_axis_over_speed
        if not InnerOverSpeed:
            self.pushButton_InnerOverSpeed.setText("未超速")
            self.pushButton_InnerOverSpeed.setStyleSheet('background: #e9f3ed; color: #43745b; border: 1px solid #cce1d3; border-radius: 7px;')
        elif InnerOverSpeed:
            self.pushButton_InnerOverSpeed.setText("已超速")
            self.pushButton_InnerOverSpeed.setStyleSheet('background: #f9e9e9; color: #a35d5d; border: 1px solid #eccaca; border-radius: 7px;')

        # 获取内轴的超差情况
        InnerOverDiff = turntableState.is_inner_axis_over_diff
        if not InnerOverDiff:
            self.pushButton_InnerOverDiff.setText("未超差")
            self.pushButton_InnerOverDiff.setStyleSheet('background: #e9f3ed; color: #43745b; border: 1px solid #cce1d3; border-radius: 7px;')
        elif InnerOverDiff:
            self.pushButton_InnerOverDiff.setText("已超差")
            self.pushButton_InnerOverDiff.setStyleSheet('background: #f9e9e9; color: #a35d5d; border: 1px solid #eccaca; border-radius: 7px;')

        # 获取内轴的驱动故障情况
        InnerDriverFault = turntableState.is_inner_axis_driver_fault
        if not InnerDriverFault:
            self.pushButton_InnerDriverFault.setText("驱动正常")
            self.pushButton_InnerDriverFault.setStyleSheet('background: #e9f3ed; color: #43745b; border: 1px solid #cce1d3; border-radius: 7px;')
        elif InnerDriverFault:
            self.pushButton_InnerDriverFault.setText("驱动故障")
            self.pushButton_InnerDriverFault.setStyleSheet('background: #f9e9e9; color: #a35d5d; border: 1px solid #eccaca; border-radius: 7px;')

        # 获取内轴的电压状况
        InnerOverVoltage = turntableState.is_inner_axis_over_voltage
        if not InnerOverVoltage:
            self.pushButton_InnerOverVoltage.setText("电压正常")
            self.pushButton_InnerOverVoltage.setStyleSheet('background: #e9f3ed; color: #43745b; border: 1px solid #cce1d3; border-radius: 7px;')
        elif InnerOverVoltage:
            self.pushButton_InnerOverVoltage.setText("电压超限")
            self.pushButton_InnerOverVoltage.setStyleSheet('background: #f9e9e9; color: #a35d5d; border: 1px solid #eccaca; border-radius: 7px;')

    def timer_OuterAxisStateDisplay_Tick(self):
        """
            定时获取和显示外轴状态
        """
        # 获取外轴的当前运动模式
        outer_axis_run_mode_text = turntableState.outer_axis_run_mode_text
        self.pushButton_OuterRunMode.setText(outer_axis_run_mode_text)

        # 获取外轴的使能情况
        OuterEnable = turntableState.is_outer_axis_in_enable
        if not OuterEnable:
            self.pushButton_OuterEnable.setText("未使能")
            self.pushButton_OuterEnable.setStyleSheet('background: #f9e9e9; color: #a35d5d; border: 1px solid #eccaca; border-radius: 7px;')
        elif OuterEnable:
            self.pushButton_OuterEnable.setText("已使能")
            self.pushButton_OuterEnable.setStyleSheet('background: #e9f3ed; color: #43745b; border: 1px solid #cce1d3; border-radius: 7px;')

        # 获取外轴的找零情况
        OuterToZero = turntableState.is_outer_axis_find_zero
        if not OuterToZero:
            self.pushButton_OuterReturnToZero.setText("未找零")
            self.pushButton_OuterReturnToZero.setStyleSheet('background: #f9e9e9; color: #a35d5d; border: 1px solid #eccaca; border-radius: 7px;')
        elif OuterToZero:
            self.pushButton_OuterReturnToZero.setText("已找零")
            self.pushButton_OuterReturnToZero.setStyleSheet('background: #e9f3ed; color: #43745b; border: 1px solid #cce1d3; border-radius: 7px;')

        # 获取外轴的到位情况
        OuterMove = turntableState.is_outer_axis_in_place
        if not OuterMove:
            self.pushButton_OuterMoveInPlace.setText("未到位")
            self.pushButton_OuterMoveInPlace.setStyleSheet('background: #f9e9e9; color: #a35d5d; border: 1px solid #eccaca; border-radius: 7px;')
            turntableData.is_outer_axis_in_place = False
        elif OuterMove:
            self.pushButton_OuterMoveInPlace.setText("已到位")
            self.pushButton_OuterMoveInPlace.setStyleSheet('background: #e9f3ed; color: #43745b; border: 1px solid #cce1d3; border-radius: 7px;')
            turntableData.is_outer_axis_in_place = True

        # 获取外轴的正常情况
        is_outer_axis_normal = turntableState.is_outer_axis_normal
        if not is_outer_axis_normal:
            self.pushButton_OuterModel.setText("异常" + "(" + str(turntableState.outer_axis_alarm_code) + ")")
            self.pushButton_OuterModel.setStyleSheet('background: #f9e9e9; color: #a35d5d; border: 1px solid #eccaca; border-radius: 7px;')
        elif is_outer_axis_normal:
            self.pushButton_OuterModel.setText("正常")
            self.pushButton_OuterModel.setStyleSheet('background: #e9f3ed; color: #43745b; border: 1px solid #cce1d3; border-radius: 7px;')

        # 获取外轴的锁紧情况
        OuterLock = turntableState.is_outer_axis_is_lock
        if not OuterLock:
            self.pushButton_OuterLockState.setText("未锁紧")
            self.pushButton_OuterLockState.setStyleSheet('background: #e9f3ed; color: #43745b; border: 1px solid #cce1d3; border-radius: 7px;')
        elif OuterLock:
            self.pushButton_OuterLockState.setText("已锁紧")
            self.pushButton_OuterLockState.setStyleSheet('background: #f9e9e9; color: #a35d5d; border: 1px solid #eccaca; border-radius: 7px;')

        # 获取外轴的触碰上限位情况
        OuterUpLimit = turntableState.is_outer_axis_up_limit
        if not OuterUpLimit:
            self.pushButton_OuterUpLimit.setText("上限位")
            self.pushButton_OuterUpLimit.setStyleSheet('background: #e9f3ed; color: #43745b; border: 1px solid #cce1d3; border-radius: 7px;')
        elif OuterUpLimit:
            self.pushButton_OuterUpLimit.setText("触碰上限")
            self.pushButton_OuterUpLimit.setStyleSheet('background: #f9e9e9; color: #a35d5d; border: 1px solid #eccaca; border-radius: 7px;')

        # 获取外轴的触碰下限位情况
        OuterDownLimit = turntableState.is_outer_axis_down_limit
        if not OuterDownLimit:
            self.pushButton_OuterDownLimit.setText("下限位")
            self.pushButton_OuterDownLimit.setStyleSheet('background: #e9f3ed; color: #43745b; border: 1px solid #cce1d3; border-radius: 7px;')
        elif OuterDownLimit:
            self.pushButton_OuterDownLimit.setText("触碰下限")
            self.pushButton_OuterDownLimit.setStyleSheet('background: #f9e9e9; color: #a35d5d; border: 1px solid #eccaca; border-radius: 7px;')

        # 获取外轴的超速情况
        OuterOverSpeed = turntableState.is_outer_axis_over_speed
        if not OuterOverSpeed:
            self.pushButton_OuterOverSpeed.setText("未超速")
            self.pushButton_OuterOverSpeed.setStyleSheet('background: #e9f3ed; color: #43745b; border: 1px solid #cce1d3; border-radius: 7px;')
        elif OuterOverSpeed:
            self.pushButton_OuterOverSpeed.setText("已超速")
            self.pushButton_OuterOverSpeed.setStyleSheet('background: #f9e9e9; color: #a35d5d; border: 1px solid #eccaca; border-radius: 7px;')

        # 获取外轴的超差情况
        OuterOverDiff = turntableState.is_outer_axis_over_diff
        if not OuterOverDiff:
            self.pushButton_OuterOverDiff.setText("未超差")
            self.pushButton_OuterOverDiff.setStyleSheet('background: #e9f3ed; color: #43745b; border: 1px solid #cce1d3; border-radius: 7px;')
        elif OuterOverDiff:
            self.pushButton_OuterOverDiff.setText("已超差")
            self.pushButton_OuterOverDiff.setStyleSheet('background: #f9e9e9; color: #a35d5d; border: 1px solid #eccaca; border-radius: 7px;')

        # 获取外轴的驱动故障情况
        OuterDriverFault = turntableState.is_outer_axis_driver_fault
        if not OuterDriverFault:
            self.pushButton_OuterDriverFault.setText("驱动正常")
            self.pushButton_OuterDriverFault.setStyleSheet('background: #e9f3ed; color: #43745b; border: 1px solid #cce1d3; border-radius: 7px;')
        elif OuterDriverFault:
            self.pushButton_OuterDriverFault.setText("驱动故障")
            self.pushButton_OuterDriverFault.setStyleSheet('background: #f9e9e9; color: #a35d5d; border: 1px solid #eccaca; border-radius: 7px;')

        # 获取外轴的电压状况
        OuterOverVoltage = turntableState.is_outer_axis_over_voltage
        if not OuterOverVoltage:
            self.pushButton_OuterOverVoltage.setText("电压正常")
            self.pushButton_OuterOverVoltage.setStyleSheet('background: #e9f3ed; color: #43745b; border: 1px solid #cce1d3; border-radius: 7px;')
        elif OuterOverVoltage:
            self.pushButton_OuterOverVoltage.setText("电压超限")
            self.pushButton_OuterOverVoltage.setStyleSheet('background: #f9e9e9; color: #a35d5d; border: 1px solid #eccaca; border-radius: 7px;')

    def timer_TurntableFaultMonitor_Tick(self):
        """
        定时监测转台故障
        """
        if OFFLINE_DEBUG:
            return
        if self.turntable_fault_check():
            self.turntable_fault_conut += 1
        else:
            self.turntable_fault_conut = 0 # 转台连续故障N次才进行处理！！！
        if self.turntable_fault_conut == self.TURNTABLE_FAULT_COUNT_THRESHOLD:
            # 防止重复错误提示！！！
            self.timer_TurntableFaultMonitor.stop()
            self.turntable_fault_conut = self.TURNTABLE_FAULT_COUNT_THRESHOLD + 1
            # 内轴、外轴断电
            turntableComm.thread_lock.acquire()
            if self.turntable_model == "2TD600":
                ret = twoTD600_SetAxisDisable(INNER_ROTATION_AXIS)
                # if not ret:
                #    messagebox.showerror("", "内轴断电失败！") # 注释掉，防止在未打开转台串口时提示出错！
                time.sleep(0.1)  # 等待一段时间
                ret = twoTD600_SetAxisDisable(OUTER_ROTATION_AXIS)
                # if not ret:
                #     messagebox.showerror("", "外轴断电失败！")
            elif self.turntable_model == "2FDT600WK":
                comm_error_code = [0]
                ret = twoFDT600WK_SetAxisDisable(INNER_ROTATION_AXIS, comm_error_code)
                # if not ret:
                #     messagebox.showerror("", "内轴断电失败！" + "错误码 = " + str(comm_error_code[0]))
                ret = twoFDT600WK_SetAxisDisable(OUTER_ROTATION_AXIS, comm_error_code)
                # if not ret:
                #     messagebox.showerror("", "外轴断电失败！" + "错误码 = " + str(comm_error_code[0]))
            turntableComm.thread_lock.release()
            # 更新自动运行状态相关信息
            if autoRunState.auto_run_state != "停止":
                autoRunState.thread_lock.acquire()
                autoRunState.auto_run_state = "错误"
                autoRunState.auto_run_info +="转台故障！" + "\r\n"
                autoRunState.thread_lock.release()
                # 记录错误信息至日志
                # 请求中止加速度计校准
                #thread_of_acc_cal_terminate()
                # 请求并等待X-MARK校准线程退出
                #thread_of_xmark_cal_terminate()
                # 给出提示
                messagebox.showerror("", "转台故障！")
                autoRunState.thread_lock.acquire()
                autoRunState.auto_run_state = "停止"
                # autoRunState.button_text_AccCalRun = "自动运行"
                # autoRunState.button_text_TpsCalRun = "自动运行"
                # autoRunState.button_text_XMARKCalRun = "自动运行"
                autoRunState.thread_lock.release()
            else:
                messagebox.showerror("", "转台故障！")

    def all_pushbutton_setEnabled(self, enable):
        """
            设置所有按钮为可点击
        """
        self.pushButton_InnerRun.setEnabled(enable)
        self.pushButton_OuterRun.setEnabled(enable)
        self.pushButton_InnerStop.setEnabled(enable)
        self.pushButton_OuterStop.setEnabled(enable)
        self.pushButton_InnerReturnZero.setEnabled(enable)
        self.pushButton_OuterReturnZero.setEnabled(enable)
        self.pushButton_AllReturnZero.setEnabled(enable)
        self.pushButton_AllRun.setEnabled(enable)
        self.pushButton_AllStop.setEnabled(enable)
        self.pushButton_InnerRunForSpeedMode.setEnabled(enable)
        self.pushButton_OuterRunForSpeedMode.setEnabled(enable)
        self.pushButton_InnerStopForSpeedMode.setEnabled(enable)
        self.pushButton_OuterStopForSpeedMode.setEnabled(enable)
        self.pushButton_InnerRunForSwayMode.setEnabled(enable)
        self.pushButton_OuterRunForSwayMode.setEnabled(enable)
        self.pushButton_InnerStopForSwayMode.setEnabled(enable)
        self.pushButton_OuterStopForSwayMode.setEnabled(enable)

    def start_all_timers(self):
        """
            启动所有定时器
        """
        # 内轴实时位置和速度获取和显示定时器
        self.timer_InnerAxisPositionAndSpeedDisplay.start()
        # 外轴实时位置和速度获取和显示定时器
        self.timer_OuterAxisPositionAndSpeedDisplay.start()
        # 内轴状态获取和显示定时器
        self.timer_InnerAxisStateDisplay.start()
        # 外轴状态获取和显示定时器
        self.timer_OuterAxisStateDisplay.start()
        # 转台故障监测定时器
        self.turntable_fault_conut = 0
        self.timer_TurntableFaultMonitor.start()

    def stop_all_timers(self):
        """
            停止所有定时器
        """
        # 内轴实时位置和速度获取和显示定时器
        self.timer_InnerAxisPositionAndSpeedDisplay.stop()
        # 外轴实时位置和速度获取和显示定时器
        self.timer_OuterAxisPositionAndSpeedDisplay.stop()
        # 内轴状态获取和显示定时器
        self.timer_InnerAxisStateDisplay.stop()
        # 外轴状态获取和显示定时器
        self.timer_OuterAxisStateDisplay.stop()
        # 转台故障监测定时器
        self.timer_TurntableFaultMonitor.stop()

    def all_signal_button_restore_default_state(self):
        """
            点击关闭转台按钮后，状态灯，lineEdit恢复默认状态
        """
        # 清空内外轴实时速度和角度
        self.textEdit_InnerCurrentPosition.clear()
        self.textEdit_outerCurrentPosition.clear()
        self.textEdit_InnerCurrentSpeed.clear()
        self.textEdit_outerCurrentSpeed.clear()
        # 清空用户设置的内轴，外轴的转动角度和转动速率
        self.lineEdit_InnerRotationAngleSet.clear()
        self.lineEdit_InnerRotationSpeedSet.clear()
        self.lineEdit_outerRotationAngleSet.clear()
        self.lineEdit_outerRotationSpeedSet.clear()
        # 内轴的状态灯
        self.pushButton_InnerRunMode.setText("运动模式")
        self.pushButton_InnerEnable.setText("使能状态")
        self.pushButton_InnerEnable.setStyleSheet("background: #f2f4f5; color: #88929a; border: 1px solid #dfe4e8; border-radius: 7px;")
        self.pushButton_InnerReturnToZero.setText("找零状态")
        self.pushButton_InnerReturnToZero.setStyleSheet("background: #f2f4f5; color: #88929a; border: 1px solid #dfe4e8; border-radius: 7px;")
        self.pushButton_InnerMoveInPlace.setText("到位状态")
        self.pushButton_InnerMoveInPlace.setStyleSheet("background: #f2f4f5; color: #88929a; border: 1px solid #dfe4e8; border-radius: 7px;")
        self.pushButton_InnerModel.setText("内轴状态")
        self.pushButton_InnerModel.setStyleSheet("background: #f2f4f5; color: #88929a; border: 1px solid #dfe4e8; border-radius: 7px;")
        self.pushButton_InnerLockState.setText("锁紧状态")
        self.pushButton_InnerLockState.setStyleSheet("background: #f2f4f5; color: #88929a; border: 1px solid #dfe4e8; border-radius: 7px;")
        self.pushButton_InnerUpLimit.setText("上限位状态")
        self.pushButton_InnerUpLimit.setStyleSheet("background: #f2f4f5; color: #88929a; border: 1px solid #dfe4e8; border-radius: 7px;")
        self.pushButton_InnerDownLimit.setText("下限位状态")
        self.pushButton_InnerDownLimit.setStyleSheet("background: #f2f4f5; color: #88929a; border: 1px solid #dfe4e8; border-radius: 7px;")
        self.pushButton_InnerOverSpeed.setText("超速状态")
        self.pushButton_InnerOverSpeed.setStyleSheet("background: #f2f4f5; color: #88929a; border: 1px solid #dfe4e8; border-radius: 7px;")
        self.pushButton_InnerOverDiff.setText("超差状态")
        self.pushButton_InnerOverDiff.setStyleSheet("background: #f2f4f5; color: #88929a; border: 1px solid #dfe4e8; border-radius: 7px;")
        self.pushButton_InnerDriverFault.setText("驱动状态")
        self.pushButton_InnerDriverFault.setStyleSheet("background: #f2f4f5; color: #88929a; border: 1px solid #dfe4e8; border-radius: 7px;")
        self.pushButton_InnerOverVoltage.setText("电压状态")
        self.pushButton_InnerOverVoltage.setStyleSheet("background: #f2f4f5; color: #88929a; border: 1px solid #dfe4e8; border-radius: 7px;")
        # 外轴的状态灯
        self.pushButton_OuterRunMode.setText("运动模式")
        self.pushButton_OuterEnable.setText("使能状态")
        self.pushButton_OuterEnable.setStyleSheet("background: #f2f4f5; color: #88929a; border: 1px solid #dfe4e8; border-radius: 7px;")
        self.pushButton_OuterReturnToZero.setText("找零状态")
        self.pushButton_OuterReturnToZero.setStyleSheet("background: #f2f4f5; color: #88929a; border: 1px solid #dfe4e8; border-radius: 7px;")
        self.pushButton_OuterMoveInPlace.setText("到位状态")
        self.pushButton_OuterMoveInPlace.setStyleSheet("background: #f2f4f5; color: #88929a; border: 1px solid #dfe4e8; border-radius: 7px;")
        self.pushButton_OuterModel.setText("外轴状态")
        self.pushButton_OuterModel.setStyleSheet("background: #f2f4f5; color: #88929a; border: 1px solid #dfe4e8; border-radius: 7px;")
        self.pushButton_OuterLockState.setText("锁紧状态")
        self.pushButton_OuterLockState.setStyleSheet("background: #f2f4f5; color: #88929a; border: 1px solid #dfe4e8; border-radius: 7px;")
        self.pushButton_OuterUpLimit.setText("上限位状态")
        self.pushButton_OuterUpLimit.setStyleSheet("background: #f2f4f5; color: #88929a; border: 1px solid #dfe4e8; border-radius: 7px;")
        self.pushButton_OuterDownLimit.setText("下限位状态")
        self.pushButton_OuterDownLimit.setStyleSheet("background: #f2f4f5; color: #88929a; border: 1px solid #dfe4e8; border-radius: 7px;")
        self.pushButton_OuterOverSpeed.setText("超速状态")
        self.pushButton_OuterOverSpeed.setStyleSheet("background: #f2f4f5; color: #88929a; border: 1px solid #dfe4e8; border-radius: 7px;")
        self.pushButton_OuterOverDiff.setText("超差状态")
        self.pushButton_OuterOverDiff.setStyleSheet("background: #f2f4f5; color: #88929a; border: 1px solid #dfe4e8; border-radius: 7px;")
        self.pushButton_OuterDriverFault.setText("驱动状态")
        self.pushButton_OuterDriverFault.setStyleSheet("background: #f2f4f5; color: #88929a; border: 1px solid #dfe4e8; border-radius: 7px;")
        self.pushButton_OuterOverVoltage.setText("电压状态")
        self.pushButton_OuterOverVoltage.setStyleSheet("background: #f2f4f5; color: #88929a; border: 1px solid #dfe4e8; border-radius: 7px;")

    def refresh_turntable_comm_ports(self):
        """枚举当前可用串口；保留配置端口，方便设备暂时未插入时提示用户。"""
        previous = self.comboBox_TurntableCommPortSelect.currentData()
        saved = str(self.turntable_2TD600_comm_port or "").strip()
        target = str(previous or saved)
        self.comboBox_TurntableCommPortSelect.clear()
        ports = []
        try:
            ports = list(serial.tools.list_ports.comports())
        except Exception as exc:
            messagebox.showwarning("串口枚举失败", f"无法枚举串口：{exc}")
        for info in ports:
            self.comboBox_TurntableCommPortSelect.addItem(
                f"{info.device} — {info.description}", str(info.device))
        if saved and all(self.comboBox_TurntableCommPortSelect.itemData(i) != saved
                         for i in range(self.comboBox_TurntableCommPortSelect.count())):
            self.comboBox_TurntableCommPortSelect.addItem(f"{saved}（配置值，当前未发现）", saved)
        if self.comboBox_TurntableCommPortSelect.count() == 0:
            self.comboBox_TurntableCommPortSelect.addItem("未发现串口", "")
        idx = self.comboBox_TurntableCommPortSelect.findData(target)
        if idx >= 0:
            self.comboBox_TurntableCommPortSelect.setCurrentIndex(idx)
        elif self.comboBox_TurntableCommPortSelect.count() > 0:
            self.comboBox_TurntableCommPortSelect.setCurrentIndex(0)

    def get_user_habits(self):
        """
            获取“user_habits.xml”文件中记录的用户上一次使用软件的习惯
        """
        # 读取、解析、获取user_habits.xml文件中的内容
        tree = Et.parse('config.xml')
        root = tree.getroot()

        # 获取上一次记录的用户选择的转台型号
        for turntable_model in root.iter('TurntableModel_UserSelected'):
            self.comboBox_TurntableModelSelect.setCurrentText(str(turntable_model.text))

        # 获取转台2TD600的通讯端口号
        for comm_port in root.iter('Turntable2TD600CommPort'):
             self.turntable_2TD600_comm_port = str(comm_port.text)

        # 获取转台2FDT600WK的通讯端口号
        for comm_port in root.iter('Turntable2FDT600WKInnerAxisCommPort'):
             self.turntable_2FDT600WK_inner_axis_comm_port = str(comm_port.text)
        for comm_port in root.iter('Turntable2FDT600WKOuterAxisCommPort'):
             self.turntable_2FDT600WK_outer_axis_comm_port = str(comm_port.text)

        self.refresh_turntable_comm_ports()

    def record_user_habits(self):
        """
            记录用户关闭转台前的设置
        """
        # 读取、解析、获取user_habits.xml文件中的内容
        tree = Et.parse('config.xml')
        root = tree.getroot()

        # 记录本次使用过程中选择的转台型号
        used_turnTable_model = self.comboBox_TurntableModelSelect.currentText()
        if used_turnTable_model != "":
            for turnTable_model in root.iter('TurntableModel_UserSelected'):
                turnTable_model.text = used_turnTable_model
        if self.turntable_2TD600_comm_port:
            for comm_port in root.iter('Turntable2TD600CommPort'):
                comm_port.text = self.turntable_2TD600_comm_port

        tree.write('config.xml')

    def lineEdit_input_restrictions(self):
        """
            设置控件”lineEdit_InnerRotationAngleSet“，”lineEdit_InnerRotationSpeedSet“，
            ”lineEdit_outerRotationAngleSet“，”lineEdit_outerRotationSpeedSet“
            只能输入数字,避免使用转台时由于输入内容错误出现故障
        """
        # 创建正则表达式，限制只能输入数字
        regex = QRegularExpression(r"[0-9\-.]+")
        validator = QRegularExpressionValidator(regex)
        self.lineEdit_InnerRotationAngleSet.setValidator(validator)
        self.lineEdit_InnerRotationSpeedSet.setValidator(validator)
        self.lineEdit_outerRotationAngleSet.setValidator(validator)
        self.lineEdit_outerRotationSpeedSet.setValidator(validator)

    def create_timer(self, interval, task):
        """
            创建自定义QTimer，方便多次调用
        """
        timer = QTimer()
        timer.timeout.connect(task)
        timer.setInterval(interval)
        return timer

    def turntable_fault_check(self):
        """
        检查转台是否发生故障
        """
        if (turntableState.inner_axis_alarm_code != 0) or \
           (not turntableState.is_inner_axis_in_enable) or \
           (not turntableState.is_inner_axis_normal) or \
           (turntableState.is_inner_axis_is_lock) or \
           (turntableState.is_inner_axis_up_limit) or \
           (turntableState.is_inner_axis_down_limit) or \
           (turntableState.is_inner_axis_over_speed) or \
           (turntableState.is_inner_axis_over_diff) or \
           (turntableState.is_inner_axis_driver_fault) or \
           (turntableState.is_inner_axis_over_voltage) or \
           (turntableState.outer_axis_alarm_code != 0) or \
           (not turntableState.is_outer_axis_in_enable) or \
           (not turntableState.is_outer_axis_normal) or \
           (turntableState.is_outer_axis_is_lock) or \
           (turntableState.is_outer_axis_up_limit) or \
           (turntableState.is_outer_axis_down_limit) or \
           (turntableState.is_outer_axis_over_speed) or \
           (turntableState.is_outer_axis_over_diff) or \
           (turntableState.is_outer_axis_driver_fault) or \
           (turntableState.is_outer_axis_over_voltage):
            return True
        else:
            return False

    def pushButton_closeWindows_Click(self):
        """关闭工作台（保守退出）。

        本窗口不直接对运行中的实体转台执行断电：请先使用已有的“关闭转台”
        流程完成停车和断开。未连接设备时不调用厂商 DLL；线程退出均有上限。
        """
        # 正在进行自动标定时，先在标定页面中止任务并核实转台停止，
        # 不能通过关闭窗口绕过标定状态机中的安全检查。
        # 原软件的转台关闭操作已经有停车/反馈确认，这里不再复制一套控制逻辑。
        if (self.button_TurntableCommPortOpen.text() == "关闭转台"
                or turntableComm.thread_instance is not None):
            QMessageBox.warning(
                self.pushButton_closeWindows,
                "请先安全断开转台",
                "转台仍处于连接或反馈线程运行状态。\n"
                "请先在转台页面点击‘关闭转台’，确认已停车并断开，"
                "再退出软件。若设备状态异常，请使用硬件急停并检查现场。"
            )
            return

        # 未连接转台时不调用 SetAxisDisable / closePort；原代码无论是否
        # 连接均调用厂商 DLL，并在 while True 中无限等待反馈线程结束。
        # 温箱轮询线程可能尚未创建，也可能阻塞于网络通信；所有等待设上限。
        tc_thread = tcComm.thread_instance
        if tc_thread is not None:
            tcComm.terminate_thread_requst = True
            if tc_thread is threading.current_thread():
                QMessageBox.warning(self.pushButton_closeWindows,
                                    "暂时无法退出", "温箱线程状态异常，请检查连接后重试。")
                return
            try:
                tc_thread.join(timeout=2.0)
            except RuntimeError as exc:
                QMessageBox.warning(self.pushButton_closeWindows,
                                    "温箱线程异常", str(exc))
                return
            if tc_thread.is_alive():
                QMessageBox.warning(self.pushButton_closeWindows,
                                    "温箱未完成断开",
                                    "温箱采集线程尚未退出，已停止继续等待，避免界面假死。\n"
                                    "请先在温箱页面断开设备，之后重试退出。")
                return
        else:
            tcComm.terminate_thread_requst = False

        if tcComm.is_connected:
            # 延用原停止定值流程，但仅在温箱实际连接时发送命令。
            try:
                if not tcComm.thread_lock.acquire(timeout=1.0):
                    raise TimeoutError("温箱通讯锁超过 1 秒未释放")
                try:
                    result = tc_fixed_value_stop()
                finally:
                    tcComm.thread_lock.release()
                if result is False:
                    raise RuntimeError("温箱控制器未确认停止定值运行")
            except Exception as exc:
                QMessageBox.warning(self.pushButton_closeWindows,
                                    "温箱未完成安全关闭",
                                    f"温箱停车/停止定值失败：{exc}\n请确认设备状态后再退出。")
                return

        try:
            self.record_user_habits()
        except (OSError, ValueError, Et.ParseError) as exc:
            # 保存最近使用设置失败不应妨碍用户关闭软件；输出到 PyCharm 控制台。
            print(f"[退出] 保存 config.xml 失败：{exc}", file=sys.stderr)

        # 不依赖星号导入得到的 QApplication 名称，避免退出阶段对象查找错误。
        # Qt 正常退出后由 main.py 已有的 aboutToQuit 连接清理 IMU/实验 CSV。
        QCoreApplication.quit()

    def widget_visible_set(self):
        """
        根据配置文件里的配置，设置相应界面是否显示
        """
        # 读取配置文件里的配置，然后确定某个界面是否使能
        form_turntable_visible = False

        config_file_path = 'config.xml'
        form_turntable_visible_text = xml_read(config_file_path, 'FormTurntableVisible')
        if form_turntable_visible_text == 'True':
            form_turntable_visible = True
        else:
            form_turntable_visible = False

        # 根据某个校准项目是否使能，设置相应校准界面是否显示
        if not form_turntable_visible:
            remove_tab_by_name(self.tabWidget_CalMain, "转台")


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