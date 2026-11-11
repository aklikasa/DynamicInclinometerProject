"""转台控制界面"""
import os
import re
import time
import math
import ctypes
from datetime import *
from qt_dialogs import filedialog, messagebox
import serial
import serial.tools.list_ports
import threading
from PySide6.QtGui import QRegularExpressionValidator, QFont
from PySide6.QtWidgets import QPushButton, QMessageBox
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
import turntable_2FDT600WK_comm as wk_comm  # 手动定位专用；不改自动标定调用的底层函数
from turntable_data_get import *
from temperature_chamber_data_get import *
from auto_run_state import *
from motion_speed_guard import MAX_ABS_SPEED_DPS, target_speed_allowed, sway_peak_speed, feedback_overspeed


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

        # 保留原版的轴状态 / 运动控制两个页签；把旧 COM 下拉框位置改为使能按钮。
        # 自动发现端口不会发送任何控制/运动命令。
        self.comboBox_TurntableCommPortSelect.hide()
        self.pushButton_TurntableCommPortRefresh.hide()
        self._2fdt_enable_button = QPushButton("使能两轴", ui.groupBox_TurntablePortSelect)
        self._2fdt_enable_button.setGeometry(10, 64, 191, 25)
        self._2fdt_enable_button.setEnabled(False)
        self._2fdt_enable_button.setToolTip("先自动连接并确认两轴状态；点击后需确认设备安全，不会自动回零")
        self._2fdt_enable_button.clicked.connect(self._enable_2fdt_axes)
        self._2fdt_enable_button.hide()
        self._2fdt_scan_log = ''
        self._speed_limit_tripped = False
        self._speed_limit_last_count = -1
        # 仅跟踪在“转台”页手动发起的 WK 位置指令；不参与自动标定流程。
        self._wk_manual_position_pending = {}
        self._wk_manual_position_timer = QTimer()
        self._wk_manual_position_timer.setInterval(250)
        self._wk_manual_position_timer.timeout.connect(self._wk_manual_position_tick)

        # WK 手动控制只为内轴提供“就近到 0°”；外轴保留厂家原始回零按钮。
        # 不修改 Designer UI、自动标定逻辑或转台通信模块。
        zero_group = ui.groupBox_TurntableReturnZeroController
        self._wk_inner_near_zero_btn = QPushButton('内轴就近到0°', zero_group)
        self._wk_inner_near_zero_btn.setGeometry(63, 68, 118, 20)
        self._wk_inner_near_zero_btn.setEnabled(False)
        self._wk_inner_near_zero_btn.setToolTip(
            '普通绝对位置运动：内轴就近定位到 0°，不执行机械找零，不重建零位基准')
        self._wk_inner_near_zero_btn.hide()
        self._wk_inner_near_zero_btn.clicked.connect(self._wk_manual_inner_near_zero_click)

        # 初始化输入限制
        self.lineEdit_input_restrictions()

        # 读取、解析、获取user_habits.xml文件中的内容
        tree = Et.parse('config.xml')
        root = tree.getroot()
        self.comboBox_TurntableModelSelect = MyComboBox(ui.comboBox_TurntableModelSelect)
        self.comboBox_TurntableModelSelect.resize(93, 31)
        for turntable_model in root.iter('TurntableModel_UserSelected'):
            self.comboBox_TurntableModelSelect.clear()
            self.comboBox_TurntableModelSelect.addItems(['2TD600', '2FDT600WK'])
            self.comboBox_TurntableModelSelect.setCurrentText(str(turntable_model.text or '2FDT600WK'))

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
        # 软件限速反馈监测（硬件限速 / 急停仍需独立生效）。
        self.timer_SpeedLimitMonitor = self.create_timer(100, self._monitor_speed_limit)

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
        self.comboBox_TurntableModelSelect.currentTextChanged.connect(self._turntable_model_view_update)
        self._turntable_model_view_update(self.comboBox_TurntableModelSelect.currentText())

    # ============ 2FDT600WK 专用、厂家协议驱动的安全连接流程 ============
    @staticmethod
    def _2fdt_port_number(name):
        match = re.fullmatch(r"COM([1-9][0-9]*)", str(name or "").strip(), re.IGNORECASE)
        return int(match.group(1)) if match else None

    def _2fdt_note(self, message):
        # Original control layout stays untouched. Messages are in the status bar and console,
        # and are available from the connect button tooltip, not a large log widget.
        msg = str(message)
        print("[2FDT600WK] " + msg.replace("\n", " | "))
        self.button_TurntableCommPortOpen.setToolTip(msg)
        try:
            self._main_window_ui.statusbar.showMessage(msg.splitlines()[0], 12000)
        except (AttributeError, RuntimeError):
            pass

    def _2fdt_select_ports(self):
        """Passive receive-only scan: identify $1 inner / $2 outer by real state frames.

        Never assume a COM port is a turntable based on its name or ability to open.
        Do not issue motor commands during discovery.
        """
        from turntable_2fdt_autodetect import scan_axes
        inner = str(self.turntable_2FDT600WK_inner_axis_comm_port or '').strip().upper()
        outer = str(self.turntable_2FDT600WK_outer_axis_comm_port or '').strip().upper()
        self.button_TurntableCommPortOpen.setEnabled(False)
        try:
            def progress(message):
                self._2fdt_note(message + "\n只接收状态，不发送指令，请勿操作转台。")
                QCoreApplication.processEvents()
            mapping, details = scan_axes(preferred=(inner, outer), progress=progress)
        finally:
            self.button_TurntableCommPortOpen.setEnabled(True)
        self._2fdt_scan_log = '\n'.join(details)
        if not mapping:
            msg = ("未收到可确认内外轴身份的转台状态帧。\n"
                   "转台 DLL 的 -9 表示状态数据等待超时。\n"
                   "检查测控箱供电、USB-RS422 驱动/接线、串口占用。\n"
                   "这次未发送使能或运动命令。\n\n"
                   + self._2fdt_scan_log)
            self._2fdt_note(msg)
            messagebox.showerror("2FDT600WK 自动识别失败", msg)
            return None
        selected = mapping[1].upper(), mapping[2].upper()
        self._2fdt_note(f"被动识别成功：内轴 {selected[0]}，外轴 {selected[1]}。\n"
                        "接下来用厂商 DLL 验证状态（不会自动使能或回零）。\n"
                        + self._2fdt_scan_log)
        return selected

    def _2fdt_read_states(self):
        """仅使用 DLL 读取两轴最新状态；缺失回报时不推断已使能。"""
        states = {}
        with turntableComm.thread_lock:
            for axis, name in ((INNER_ROTATION_AXIS, "内轴"), (OUTER_ROTATION_AXIS, "外轴")):
                alarm, mode, angle, err = [0], [0], [0.0], [0]
                ok = twoFDT600WK_getAxisStateInfo(axis, alarm, mode, angle, err)
                states[axis] = dict(ok=bool(ok), alarm=alarm[0], state=mode[0],
                                    angle=angle[0], error=err[0], name=name)
        return states

    def _2fdt_read_states_retry(self, timeout=2.0):
        deadline = time.monotonic() + timeout
        latest = {}
        while time.monotonic() < deadline:
            latest = self._2fdt_read_states()
            if all(info['ok'] for info in latest.values()):
                return latest
            QCoreApplication.processEvents()
            time.sleep(0.10)
        return latest

    @staticmethod
    def _2fdt_state_summary(states):
        lines = []
        names = {0: '空闲/未使能', 1: '伺服/已使能', 2: '回零', 3: '定位中',
                 4: '速率运行', 5: '速率稳定', 6: '摇摆', 7: '摇摆稳定',
                 8: '停车中', 9: '多圈定位中'}
        for axis in (INNER_ROTATION_AXIS, OUTER_ROTATION_AXIS):
            info = states.get(axis, {'name': '轴', 'ok': False, 'error': '无反馈'})
            if not info['ok']:
                lines.append(f"{info['name']}：通信/状态读取失败（错误码 {info['error']}）")
            else:
                lines.append(f"{info['name']}：状态 {info['state']}（{names.get(info['state'], '未知')}），"
                             f"报警 {info['alarm']}，角度 {info['angle']:.4f}°")
        return '\n'.join(lines)

    def _open_2fdt_checked(self):
        selected = self._2fdt_select_ports()
        if selected is None:
            return
        inner_port, outer_port = (self._2fdt_port_number(s) for s in selected)
        if not inner_port or not outer_port:
            messagebox.showerror("串口异常", "只能选择 Windows COMn 格式的端口。")
            return
        self._2fdt_enable_button.setEnabled(False)
        turntableData.is_turntable_data_available = False
        opened_axes = []
        failed = None
        with turntableComm.thread_lock:
            for axis, port in ((INNER_ROTATION_AXIS, inner_port), (OUTER_ROTATION_AXIS, outer_port)):
                error = [0]
                try:
                    ok = twoFDT600WK_openAxisPort(axis, port, 115200, error)
                except Exception as exc:
                    ok = False
                    error[0] = str(exc)
                if not ok:
                    failed = f"{'内轴' if axis == INNER_ROTATION_AXIS else '外轴'} COM{port} 打开失败：{error[0]}"
                    break
                opened_axes.append(axis)
                # 原版错误地在 OpenPort 之前执行 SetTimeout，此处移动到 OpenPort 之后。
                timeout_error = [0]
                try:
                    timeout_ok = twoFDT600WK_setAxisTimeout(axis, 1000, timeout_error)
                except Exception as exc:
                    timeout_ok = False
                    timeout_error[0] = str(exc)
                if not timeout_ok:
                    failed = f"COM{port} 通信超时设置失败：{timeout_error[0]}"
                    break
            if failed:
                for axis in reversed(opened_axes):
                    try:
                        twoFDT600WK_closeAxisPort(axis, [0])
                    except Exception:
                        pass
        if failed:
            self._2fdt_note(failed)
            messagebox.showerror("2FDT600WK 连接失败", failed)
            return
        # DLL OpenPort 会重置超时配置表；在两个串口均打开之后重新设置双轴超时。
        with turntableComm.thread_lock:
            for axis in (INNER_ROTATION_AXIS, OUTER_ROTATION_AXIS):
                e = [0]
                if not twoFDT600WK_setAxisTimeout(axis, 1000, e):
                    for a in (INNER_ROTATION_AXIS, OUTER_ROTATION_AXIS):
                        twoFDT600WK_closeAxisPort(a, [0])
                    msg = f"重新设置轴 {axis} 超时失败：{e[0]}"
                    self._2fdt_note(msg)
                    messagebox.showerror('2FDT600WK 通信设置失败', msg)
                    return
        states = self._2fdt_read_states_retry(timeout=2.5)
        summary = self._2fdt_state_summary(states)
        if not all(info['ok'] for info in states.values()):
            with turntableComm.thread_lock:
                for axis in (INNER_ROTATION_AXIS, OUTER_ROTATION_AXIS):
                    twoFDT600WK_closeAxisPort(axis, [0])
            self._2fdt_note("打开串口但未收到有效转台反馈：\n" + summary)
            messagebox.showerror("2FDT600WK 状态反馈失败",
                                 "串口能打开不代表测控箱已建立通讯。\n" + summary +
                                 "\n检查轴 COM 是否对应正确、控制箱供电、USB-RS422 线缆。")
            return
        self.turntable_2FDT600WK_inner_axis_comm_port = selected[0]
        self.turntable_2FDT600WK_outer_axis_comm_port = selected[1]
        self.button_TurntableCommPortOpen.setText("关闭转台")
        self.comboBox_TurntableModelSelect.setEnabled(False)
        self.comboBox_TurntableCommPortSelect.setEnabled(False)
        self.pushButton_TurntableCommPortRefresh.setEnabled(False)
        self._2fdt_enable_button.setEnabled(True)
        self.all_pushbutton_setEnabled(False)  # 未确认使能前禁止位置/速度/回零动作
        # 停止按钮在连接期间始终可用，以便发生异常时及时请求停车。
        self.pushButton_InnerStop.setEnabled(True)
        self.pushButton_OuterStop.setEnabled(True)
        self.pushButton_AllStop.setEnabled(True)
        self._2fdt_note("通信已建立（尚未自动使能、未回零）。\n" + summary)
        for axis, is_inner in ((INNER_ROTATION_AXIS, True), (OUTER_ROTATION_AXIS, False)):
            info = states[axis]
            if is_inner:
                turntableState.is_inner_axis_in_enable = info['state'] != 0
                turntableState.inner_axis_alarm_code = info['alarm']
            else:
                turntableState.is_outer_axis_in_enable = info['state'] != 0
                turntableState.outer_axis_alarm_code = info['alarm']
        turntableComm.terminate_thread_requst = False
        thread_of_turntable_data_get_create_and_start('2FDT600WK')
        self._speed_limit_tripped = False
        self._speed_limit_last_count = -1
        self.start_all_timers()
        # 两轴尚未完成使能前，不能使用“未使能”作为故障触发自动断电。
        self.timer_TurntableFaultMonitor.stop()
        self.record_user_habits()

    def _enable_2fdt_axes(self):
        if self.turntable_model != '2FDT600WK' or self.button_TurntableCommPortOpen.text() != '关闭转台' or self._speed_limit_tripped:
            return
        states = self._2fdt_read_states_retry(timeout=1.5)
        if not all(x['ok'] and x['alarm'] == 0 and x['state'] in (0, 1) for x in states.values()):
            msg = "使能前状态检查未通过：\n" + self._2fdt_state_summary(states)
            self._2fdt_note(msg)
            messagebox.showerror("不能使能", msg + "\n须两轴均无报警，且处于空闲/伺服状态。")
            return
        if any(x['state'] == 0 for x in states.values()):
            answer = QMessageBox.question(self._main_window_ui, "确认转台安全状态",
                        "确认两轴实际静止，轴系机械锁已松开，转动范围无人/障碍物，测控箱急停已释放？\n"
                        "按“是”后仅使能电机，不执行回零或旋转。",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
        for axis, name in ((INNER_ROTATION_AXIS, '内轴'), (OUTER_ROTATION_AXIS, '外轴')):
            if states[axis]['state'] == 1:
                continue
            with turntableComm.thread_lock:
                error = [0]
                ok = twoFDT600WK_SetAxisEnable(axis, error)
            if not ok:
                msg = f"{name}使能命令发送失败，DLL 错误码 {error[0]}。"
                self._2fdt_note(msg + "\n" + self._2fdt_state_summary(self._2fdt_read_states()))
                messagebox.showerror("2FDT600WK 使能失败", msg)
                return
            # 厂家文档：mo=1 不单独应答，须收到 1# 伺服状态才能确认。
            deadline = time.monotonic() + 2.5
            confirmed = False
            while time.monotonic() < deadline:
                after = self._2fdt_read_states()
                if after[axis]['ok'] and after[axis]['alarm'] != 0:
                    break
                if after[axis]['ok'] and after[axis]['state'] == 1:
                    confirmed = True
                    break
                QCoreApplication.processEvents()
                time.sleep(0.10)
            if not confirmed:
                msg = f"{name}未确认进入 1# 伺服状态，请检查轴是否真正静止、急停和驱动报警。\n"
                self._2fdt_note(msg + self._2fdt_state_summary(self._2fdt_read_states()))
                messagebox.showerror("2FDT600WK 未确认使能", msg)
                return
        verified = self._2fdt_read_states_retry(timeout=1.0)
        if not all(x['ok'] and x['alarm'] == 0 and x['state'] == 1 for x in verified.values()):
            self._2fdt_note("两轴使能状态未全部确认：\n" + self._2fdt_state_summary(verified))
            return
        self.all_pushbutton_setEnabled(True)
        self._2fdt_enable_button.setEnabled(False)
        self.turntable_fault_conut = 0
        self.timer_TurntableFaultMonitor.start()
        self._2fdt_note("两轴已确认进入 1# 伺服状态。回零需另外手动点击。\n" +
                        self._2fdt_state_summary(verified))

    def _close_2fdt_checked(self):
        if self.button_TurntableCommPortOpen.text() != '关闭转台':
            return
        states = self._2fdt_read_states_retry(timeout=1.0)
        if not all(x['ok'] for x in states.values()):
            messagebox.showerror("无法确认转台安全状态",
                    "两轴状态反馈不完整，不能假设电机已停。\n请先通过现场控制器确认安全状态。\n" +
                    self._2fdt_state_summary(states))
            return
        for axis, info in states.items():
            if info['state'] not in (0, 1):
                with turntableComm.thread_lock:
                    e = [0]
                    ok = twoFDT600WK_SetAxisStop(axis, e)
                if not ok:
                    messagebox.showerror("停车失败", f"{info['name']} 停车指令异常 {e[0]}，保持通信连接。")
                    return
        # 等待回到非运动状态；需要新状态数据，不依赖陈旧缓存。
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            states = self._2fdt_read_states()
            if all(x['ok'] and x['state'] in (0, 1) for x in states.values()):
                break
            QCoreApplication.processEvents()
            time.sleep(0.10)
        if not all(x['ok'] and x['state'] in (0, 1) for x in states.values()):
            messagebox.showerror("未确认安全停车", "状态仍表明转台在运动或通信异常，保持连接。\n" + self._2fdt_state_summary(states))
            return
        # 位置稳定二次验证；避免数据瞬间误判为静止。
        first = states
        time.sleep(0.30)
        second = self._2fdt_read_states()
        for axis in (INNER_ROTATION_AXIS, OUTER_ROTATION_AXIS):
            a, b = first[axis], second[axis]
            delta = abs((b['angle'] - a['angle'] + 180) % 360 - 180) if b['ok'] else 360
            if not b['ok'] or b['state'] not in (0, 1) or delta > 0.05:
                messagebox.showerror("未确认静止", f"{a['name']} 状态/角度不稳定，不能安全断开。")
                return
        # 先释放电机，再以 0# 反馈确认；失败时保持端口供诊断。
        for axis, info in second.items():
            if info['state'] == 1:
                with turntableComm.thread_lock:
                    e = [0]
                    ok = twoFDT600WK_SetAxisDisable(axis, e)
                if not ok:
                    messagebox.showerror("释放电机失败", f"{info['name']} DLL 错误码 {e[0]}，保持连接。")
                    return
        deadline = time.monotonic() + 2.0
        released = False
        while time.monotonic() < deadline:
            last = self._2fdt_read_states()
            if all(x['ok'] and x['state'] == 0 for x in last.values()):
                released = True
                break
            QCoreApplication.processEvents()
            time.sleep(0.10)
        if not released:
            messagebox.showerror("未确认电机释放", "未看到两轴都回到 0# 空闲状态，保持连接。\n" +
                                 self._2fdt_state_summary(last))
            return
        # 停止后台轮询后才关 DLL 端口，避免读写并发。
        thread = turntableComm.thread_instance
        if thread is not None:
            turntableComm.terminate_thread_requst = True
            thread.join(timeout=3.0)
            if thread.is_alive():
                messagebox.showerror("后台线程未停止", "轮询线程尚未退出，暂不关闭串口以免并发访问 DLL。")
                return
        else:
            turntableComm.terminate_thread_requst = False
        with turntableComm.thread_lock:
            for axis in (INNER_ROTATION_AXIS, OUTER_ROTATION_AXIS):
                e = [0]
                if not twoFDT600WK_closeAxisPort(axis, e):
                    messagebox.showerror("关闭串口失败", f"轴 {axis} 关闭串口失败：{e[0]}")
                    return
        self.stop_all_timers()
        self.all_pushbutton_setEnabled(False)
        self.all_signal_button_restore_default_state()
        self.button_TurntableCommPortOpen.setText("打开转台")
        self.comboBox_TurntableModelSelect.setEnabled(True)
        self.comboBox_TurntableCommPortSelect.setEnabled(True)
        self.pushButton_TurntableCommPortRefresh.setEnabled(True)
        self._2fdt_enable_button.setEnabled(False)
        self._speed_limit_tripped = False
        self.record_user_habits()

    def _2td_pick_port_without_dialog(self):
        """Use remembered Windows port only when still present, or unique eligible serial port.

        2TD600 lacks a verified receive-only device signature in the attached materials.
        Never send unknown commands to every Windows COM port to guess the device.
        """
        ports = [p.device.upper() for p in serial.tools.list_ports.comports()]
        remembered = str(self.turntable_2TD600_comm_port or '').strip().upper()
        if remembered in ports:
            self._2fdt_note(f'2TD600 使用已保存端口 {remembered}（尚需 DLL 验证通信）。')
            return remembered
        # Exclude IMU and two saved 2FDT600WK ports from automatic fallback.
        exclude = {str(self.turntable_2FDT600WK_inner_axis_comm_port or '').upper(),
                   str(self.turntable_2FDT600WK_outer_axis_comm_port or '').upper()}
        try:
            root = Et.parse('config.xml').getroot()
            imu = root.findtext('IncCommPort')
            if imu: exclude.add(imu.strip().upper())
        except Exception:
            pass
        candidates = [p for p in ports if p not in exclude and p != 'COM1' and p != 'COM2']
        if len(candidates) == 1:
            self._2fdt_note(f'2TD600 仅发现一个候选端口 {candidates[0]}（还需确认设备通信）。')
            return candidates[0]
        messagebox.showwarning('2TD600 串口无法安全确定',
            '没有找到已保存的 2TD600 串口，且无法唯一识别转台设备。\n'
            f'候选串口：{", ".join(candidates) or "无"}。\n'
            '由于尚无 2TD600 的可靠被动状态帧协议，软件不会向未知设备盲发指令。\n'
            '可在 config.xml 的 Turntable2TD600CommPort 中设置一次正确 COM 口。')
        return None

    def _turntable_model_view_update(self, model):
        # Original motion controls and state widgets remain visible; only COM selector is hidden.
        self.comboBox_TurntableCommPortSelect.hide()
        self.pushButton_TurntableCommPortRefresh.hide()
        is_2fdt = str(model) == '2FDT600WK'
        self._2fdt_enable_button.setVisible(is_2fdt)
        self._wk_inner_near_zero_btn.setVisible(is_2fdt)
        if not is_2fdt:
            self._2fdt_enable_button.setEnabled(False)
            self._wk_inner_near_zero_btn.setEnabled(False)

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
        # 2FDT600WK 两个轴的端口通过厂商 $1/$2 状态帧被动识别；
        # 之后连接/使能采用安全、可确认流程，不改变原有运动控制界面。
        if combobox_text == '2FDT600WK':
            if self.button_TurntableCommPortOpen.text() == '打开转台':
                self._open_2fdt_checked()
            else:
                self._close_2fdt_checked()
            return

        # 调用 DLL 打开串口。2TD600 使用本页当前选中的 COM 口；2FDT600WK 仍使用配置文件中的双轴端口。
        if self.button_TurntableCommPortOpen.text() == "打开转台":
            if self.turntable_model == "2TD600":
                selected_port = self._2td_pick_port_without_dialog()
                if not selected_port:
                    return
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

            # 每次真正重新建立连接才允许解除上次软件限速锁定。
            self._speed_limit_tripped = False
            self._speed_limit_last_count = -1
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
            self._speed_limit_tripped = False
            self.button_TurntableCommPortOpen.setText("打开转台")
            self.comboBox_TurntableModelSelect.setEnabled(True)
            self.comboBox_TurntableCommPortSelect.setEnabled(True)
            self.pushButton_TurntableCommPortRefresh.setEnabled(True)

    @staticmethod
    def _wk_manual_target(current_angle, requested_angle, absolute):
        """仅供手动控制：位置目标 + 方向，不影响自动标定的原厂位置函数。

        WK 厂家协议：普通位置指令的角度在 [0,360)，0=顺时针，1=逆时针。
        相对正角度按顺时针、负角度按逆时针；绝对目标选最短弧。
        单圈位置协议不表达多圈操作，因此拒绝相对 >=360° 的请求。
        """
        current = float(current_angle)
        request = float(requested_angle)
        if not math.isfinite(current) or not math.isfinite(request):
            raise ValueError('角度必须是有限数值。')
        if not (0 <= current <= 360):
            raise ValueError(f'当前角度反馈超出 0~360° 范围：{current:g}°。')
        current %= 360.0
        if absolute:
            if not (0 <= request < 360):
                raise ValueError('WK 单圈绝对目标角度必须为 0° 至小于 360°。')
            target = request
            cw = (target - current) % 360.0
            ccw = (current - target) % 360.0
            direction = 0 if cw <= ccw else 1
            travel = min(cw, ccw)
        else:
            if not (0 < abs(request) < 360):
                raise ValueError('WK 手动相对增量必须非零且绝对值小于 360°；多圈运动需单独协议。')
            target = (current + request) % 360.0
            direction = 0 if request > 0 else 1
            travel = abs(request)
        # 厂商位置字段精度为 0.0001°，将“360.0000”规范化为“0.0000”。
        target = round(target, 4) % 360.0
        return target, direction, travel

    def _wk_manual_position(self, axis, angle, speed, absolute):
        """仅手动按钮调用。使用 WK DLL 位置指令，不修改自动流程共用的通信模块。"""
        if self.button_TurntableCommPortOpen.text() != '关闭转台':
            return False, 'WK 尚未建立通信连接。'
        if autoRunState.auto_run_state != '停止':
            return False, '自动标定/自动运动正在运行，禁止同时发送手动位置指令。'
        name = '内轴' if axis == INNER_ROTATION_AXIS else '外轴'
        speed = float(speed)
        # 设备说明书的额定值，不是新增的 ±10°/s 软件限速。
        max_speed = 200.0 if axis == INNER_ROTATION_AXIS else 100.0
        if not (math.isfinite(speed) and 0.001 <= speed <= max_speed):
            return False, f'{name}手动位置运动速度应为 0.001～{max_speed:g}°/s（正数）。'
        alarm, state, current, error = [0], [0], [0.0], [0]
        ok = twoFDT600WK_getAxisStateInfo(axis, alarm, state, current, error)
        if not ok:
            return False, f'{name}位置反馈无效；DLL 错误码 {error[0]}。禁止盲发运动指令。'
        if alarm[0] != 0:
            return False, f'{name}有控制器报警 {alarm[0]}，禁止手动位置运行。'
        if state[0] != 1:
            return False, (f'{name}当前状态码 {state[0]}，不是 1# 伺服待命；'
                           '请先确认使能且机械静止。普通位置指令不要求先回零。')
        try:
            target, direction, travel = self._wk_manual_target(current[0], angle, absolute)
        except ValueError as exc:
            return False, str(exc)
        if travel < 0.0001:
            return False, f'{name}已处于目标角度附近，无需再发送位置指令。'

        # 仅在手动路径显式指定运动方向：原封装固定 direction=0，会造成反向绕远路。
        # DLL 的函数签名与已投入使用的低层封装保持一致。
        func = wk_comm.turntableDll.SetAxisPosition
        func.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint8,
                         ctypes.c_uint16, ctypes.c_float, ctypes.c_float]
        func.restype = ctypes.c_int
        port = wk_comm.axisPorts[axis]
        if not port:
            return False, f'{name}没有有效 WK 通信端口。'
        code = func(port, axis, direction, 10, speed, target)
        if code != 0:
            return False, f'{name} WK 位置指令调用失败：DLL 错误码 {code}。'
        self._wk_manual_position_pending[axis] = {
            'target': target, 'since': time.monotonic(), 'speed': speed,
            'reported': False, 'name': name,
        }
        if not self._wk_manual_position_timer.isActive():
            self._wk_manual_position_timer.start()
        description = (f'{name}手动位置指令：当前位置 {current[0]:.4f}° → '
                       f'目标 {target:.4f}°；方向 {"顺时针" if direction == 0 else "逆时针"}；'
                       f'计划转角 {travel:.4f}°；目标速度 {speed:g}°/s。')
        print('[WK 手动位置] ' + description)
        return True, description

    def _wk_manual_position_tick(self):
        """仅核对手动位置命令反馈；发现误入连续速率/摇摆模式时发出停车请求。"""
        pending = self._wk_manual_position_pending
        if not pending:
            self._wk_manual_position_timer.stop()
            return
        # 自动作业开始时放弃手动跟踪，不干预自动作业；自动动作路径本身不做任何修改。
        if (self.turntable_model != '2FDT600WK'
                or self.button_TurntableCommPortOpen.text() != '关闭转台'
                or autoRunState.auto_run_state != '停止'):
            pending.clear()
            self._wk_manual_position_timer.stop()
            return
        warnings = []
        for axis, spec in list(pending.items()):
            alarm, state, angle, error = [0], [0], [0.0], [0]
            with turntableComm.thread_lock:
                ok = twoFDT600WK_getAxisStateInfo(axis, alarm, state, angle, error)
                if ok and state[0] in (4, 5, 6, 7, 9):
                    # 用户发的是位置指令，控制器却处于速率/摇摆/多圈状态：主动请求停机。
                    stop_error = [0]
                    stop_ok = twoFDT600WK_SetAxisStop(axis, stop_error)
                else:
                    stop_ok, stop_error = None, [0]
            if not ok:
                pending.pop(axis, None)
                warnings.append(f'{spec["name"]}手动位置状态反馈失败（DLL {error[0]}），无法确认是否停止；请现场检查。')
                continue
            if alarm[0] != 0:
                pending.pop(axis, None)
                warnings.append(f'{spec["name"]}控制器报警 {alarm[0]}，请通过现场控制器确认停止。')
                continue
            if state[0] in (4, 5, 6, 7, 9):
                pending.pop(axis, None)
                warnings.append(f'{spec["name"]}手动位置命令后反馈状态 {state[0]}，不是位置模式 3；'
                                f'已请求停车：{stop_ok}，错误码 {stop_error[0]}。请检查实际机械运动。')
                continue
            if state[0] == 3:
                spec['reported'] = True
                continue
            if state[0] == 1:
                # 给控制器执行位置指令预留反馈时间，避免刚发送后读到上一帧伺服状态。
                if not spec['reported'] and time.monotonic() - spec['since'] < 1.0:
                    continue
                difference = abs((float(angle[0]) - spec['target'] + 180.0) % 360.0 - 180.0)
                pending.pop(axis, None)
                if difference <= 0.05:
                    print(f'[WK 手动位置] {spec["name"]}反馈到位：{angle[0]:.4f}°，目标 {spec["target"]:.4f}°。')
                else:
                    warnings.append(f'{spec["name"]}已返回伺服状态，但目标 {spec["target"]:.4f}°、'
                                    f'实际 {angle[0]:.4f}°，未确认位置到位。')
            elif state[0] in (0, 2, 8):
                pending.pop(axis, None)
                warnings.append(f'{spec["name"]}位置命令执行期间转入状态 {state[0]}，'
                                '未确认位置到位；请核对机械状态。')
        if not pending:
            self._wk_manual_position_timer.stop()
        if warnings:
            messagebox.showwarning('WK 手动位置控制反馈异常', '\n'.join(warnings))

    def _set_position_for_axis(self, axis, angle, speed, absolute):
        """按所选模式执行绝对位置或相对位置运动。返回 (成功, 详细信息)。"""
        # 2TD600 的调用保持原样；2FDT600WK 的修复仅在手动界面路径生效。
        if self.turntable_model == '2FDT600WK':
            return self._wk_manual_position(axis, angle, speed, absolute)
        if self.turntable_model == '2TD600':
            if not target_speed_allowed(speed):
                return False, f'目标速率必须大于 0 且不得超过 {MAX_ABS_SPEED_DPS:g}°/s。'
            if self._speed_limit_tripped:
                return False, '软件限速已触发，请检查设备，确认安全后断开并重新连接。'
            if absolute:
                ret = twoTD600_SetAxisPosition(axis, angle, speed)
            else:
                ret = twoTD600_SetAxisOpposition(axis, angle, speed)
            return bool(ret), ''
        return False, '请先连接并选择转台型号。'

    @staticmethod
    def _parse_position_values(angle_text, speed_text):
        angle = float(angle_text)
        speed = float(speed_text)
        if not numpy.isfinite(angle) or not numpy.isfinite(speed):
            raise ValueError("角度和速率必须是有限数值。")
        if abs(speed) < 1e-9:
            raise ValueError("目标速率不能为 0。")
        # 速度上限按转台型号在发送指令前分别判断；WK 不套用新增的 ±10°/s 限制。
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
            messagebox.showinfo("", f"内轴{mode}运动指令已发送。" + (f"\n{detail}" if detail and self.turntable_model == "2FDT600WK" else ""))
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
            messagebox.showinfo("", f"外轴{mode}运动指令已发送。" + (f"\n{detail}" if detail and self.turntable_model == "2FDT600WK" else ""))
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
        messagebox.showinfo("", "内轴、外轴位置运动指令已发送。" + (f"\n{inner_detail}\n{outer_detail}" if self.turntable_model == "2FDT600WK" else ""))

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

    def _wk_manual_inner_near_zero_click(self):
        """仅 WK 内轴：用普通位置模式沿最短弧到 0°，不执行厂家机械回零。"""
        if self.turntable_model != '2FDT600WK':
            return
        axis = INNER_ROTATION_AXIS
        if self.button_TurntableCommPortOpen.text() != '关闭转台':
            messagebox.showwarning('WK 就近到0°', '请先连接并使能 2FDT600WK 转台。')
            return
        if autoRunState.auto_run_state != '停止':
            messagebox.showwarning('WK 就近到0°', '自动任务正在运行，不允许手动运动。')
            return
        name = '内轴'
        # 在发运动命令前只读实际状态，确认当前角度来自设备。
        with turntableComm.thread_lock:
            alarm, mode, angle, err = [0], [0], [0.0], [0]
            ok = twoFDT600WK_getAxisStateInfo(axis, alarm, mode, angle, err)
        if not ok or alarm[0] != 0 or mode[0] != 1:
            messagebox.showwarning('WK 就近到0°',
                f'{name}不能执行定位：状态读取={ok}，状态码={mode[0]}，'
                f'报警码={alarm[0]}，DLL码={err[0]}；需处于1#伺服待命、无报警。')
            return
        try:
            _, direction, distance = self._wk_manual_target(angle[0], 0.0, True)
        except ValueError as exc:
            messagebox.showerror('WK 就近到0°', str(exc))
            return
        if distance < 0.0001:
            self._notify_homing_started(f'{name}已经接近绝对 0°，无需再发位置运动。')
            return
        answer = QMessageBox.question(
            self._main_window_ui, 'WK 就近到0°确认',
            f'{name}当前角度 {angle[0]:.4f}°；将沿较短路径'
            f'{"顺时针" if direction == 0 else "逆时针"}转动约 {distance:.4f}°至 0°，目标速度 1°/s。\n'
            '这不是机械找零，也不会重新建立机械零位。请确认运动范围、负载、线缆和急停安全。是否继续？',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        # 复用上传版本已确认的手动位置命令与位置状态轮询；不触及自动标定。
        with turntableComm.thread_lock:
            accepted, detail = self._wk_manual_position(axis, 0.0, 1.0, True)
        if accepted:
            self._notify_homing_started(detail + '（就近定位，不是机械找零）。')
        else:
            messagebox.showerror('WK 就近到0°失败', detail)

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

    def _wk_manual_velocity_diagnostic(self, message):
        """Record WK manual velocity native call stages; a native DLL crash may bypass Python try/except.

        Never includes IMU measurements or device configuration. The file is local to the project.
        """
        from datetime import datetime as _datetime
        import faulthandler
        try:
            path = os.path.abspath('WK_手动速率诊断.log')
            if getattr(self, '_wk_velocity_fault_path', '') != path:
                handle = open(path, 'a', encoding='utf-8', buffering=1)
                faulthandler.enable(file=handle, all_threads=True)
                self._wk_velocity_fault_handle = handle
                self._wk_velocity_fault_path = path
            handle = self._wk_velocity_fault_handle
            handle.write(f'[{_datetime.now().isoformat(timespec="seconds")}] {message}\n')
            handle.flush()
        except (OSError, RuntimeError, ValueError):
            pass  # Diagnostic file failure must never start or prevent a motion command.

    def _wk_manual_signed_velocity(self, axis, speed, accel):
        """WK manual-only signed velocity path shared by inner and outer axes.

        0=inner, 2=outer; 0=clockwise, 1=counterclockwise.
        DLL expects unsigned direction/acceleration and a positive float speed magnitude.
        Does not modify temperature compensation, auto calibration, or mechanical homing.
        """
        if axis not in (INNER_ROTATION_AXIS, OUTER_ROTATION_AXIS):
            return False, 'WK 轴号无效。'
        name = '内轴' if axis == INNER_ROTATION_AXIS else '外轴'
        if self.button_TurntableCommPortOpen.text() != '关闭转台':
            return False, 'WK 尚未连接。'
        if autoRunState.auto_run_state != '停止':
            return False, '自动任务正在运行，拒绝手动速率命令。'
        if axis in self._wk_manual_position_pending:
            return False, f'{name}手动位置任务未确认结束，请先停车并确认静止。'
        try:
            speed = float(speed)
            accel = int(accel)
            if not math.isfinite(speed) or abs(speed) < 0.001:
                return False, f'{name}速率无效。'
            if not (1 <= accel <= (100 if axis == INNER_ROTATION_AXIS else 50)):
                return False, f'{name}加速度越界。'
        except (TypeError, ValueError, OverflowError):
            return False, f'{name}速率或加速度类型无效。'
        alarm, state, position, err = [0], [0], [0.0], [0]
        ok = twoFDT600WK_getAxisStateInfo(axis, alarm, state, position, err)
        if not ok:
            return False, f'{name}状态读取失败：DLL={err[0]}。'
        if alarm[0] != 0 or state[0] != 1:
            return False, (f'{name}状态 {state[0]}、报警 {alarm[0]}；'
                           '需处于1#伺服待命、无报警，换向前先停车。')
        port = wk_comm.axisPorts[axis]
        if not isinstance(port, int) or port <= 0:
            return False, f'{name} COM 通信端口无效。'
        direction = 0 if speed > 0 else 1
        magnitude = float(abs(speed))
        func = wk_comm.turntableDll.SetAxisVelocity
        # Match the existing vendor 64-bit DLL ABI; arguments are never negative at the C boundary.
        func.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint8,
                         ctypes.c_uint16, ctypes.c_float]
        func.restype = ctypes.c_int
        self._wk_manual_velocity_diagnostic(
            f'ENTER axis={axis} port={port} direction={direction} '
            f'accel={accel} speed_abs={magnitude:g} state={state[0]} alarm={alarm[0]}')
        try:
            code = func(port, axis, direction, accel, magnitude)
        except Exception as exc:
            self._wk_manual_velocity_diagnostic(
                f'PYTHON_EXCEPTION axis={axis} direction={direction} {type(exc).__name__}: {exc}')
            return False, f'{name} DLL 调用异常：{exc!r}。'
        self._wk_manual_velocity_diagnostic(
            f'RETURN axis={axis} direction={direction} result={code}')
        if code != 0:
            return False, f'{name} WK 速率指令 DLL 错误码 {code}。'
        movement = '顺时针' if direction == 0 else '逆时针'
        return True, (f'{movement}，方向码 {direction}，速率 {magnitude:g}°/s，'
                      f'加速度 {accel}°/s²；DLL成功仅代表指令已发送。')

    def _wk_manual_inner_signed_velocity(self, speed, accel):
        return self._wk_manual_signed_velocity(INNER_ROTATION_AXIS, speed, accel)

    def _wk_manual_outer_signed_velocity(self, speed, accel):
        return self._wk_manual_signed_velocity(OUTER_ROTATION_AXIS, speed, accel)

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

        # WK 的厂家 DLL 加速度参数类型为 uint16；先校验再显式转换为整数。
        # 此修正仅作用于 WK 手动速率模式，不改变自动标定与 2TD600 路径。
        if self.turntable_model == '2FDT600WK':
            max_speed = 200.0 if axis == INNER_ROTATION_AXIS else 100.0
            max_accel = 100 if axis == INNER_ROTATION_AXIS else 50
            if not (0.001 <= abs(speed) <= max_speed):
                messagebox.showerror('参数无效', f'{axis_label}WK 速率幅值应在 0.001～{max_speed:g}°/s。')
                return
            if not (1 <= accel <= max_accel and accel.is_integer()):
                messagebox.showerror('参数无效', f'{axis_label}WK 加速度必须是 1～{max_accel} 的整数（°/s²）。')
                return
            accel = int(accel)
        # 仅 2TD600 保留原有 ±10°/s 软件限制；WK 不新增该限制。
        if self.turntable_model == "2TD600":
            if not target_speed_allowed(speed):
                messagebox.showwarning("转台限速保护", f"{axis_label}目标速率 {speed:g}°/s 超出上限 {MAX_ABS_SPEED_DPS:g}°/s，已拒绝运动指令。")
                return
            if self._speed_limit_tripped:
                messagebox.showwarning("转台限速保护", "已发生限速触发，确认安全后断开并重新连接转台。")
                return
        turntableComm.thread_lock.acquire()
        try:
            if self.turntable_model == "2TD600":
                ret = twoTD600_SetAxisVelocity(axis, speed, accel)
                detail = ""
            elif self.turntable_model == "2FDT600WK":
                if axis == INNER_ROTATION_AXIS:
                    ret, detail = self._wk_manual_inner_signed_velocity(speed, accel)
                else:
                    # 外轴手动速率单独修复符号方向，不修改自动温补或共用DLL封装。
                    ret, detail = self._wk_manual_outer_signed_velocity(speed, accel)
            else:
                ret = False
                detail = "请先连接并选择转台型号。"
        except Exception as exc:
            ret, detail = False, repr(exc)
        finally:
            turntableComm.thread_lock.release()

        if ret:
            if self.turntable_model == '2FDT600WK':
                # Continuous velocity runs until STOP. Avoid a blocking modal dialog while moving.
                self._2fdt_note(f'{axis_label}速率命令已发送：{detail}；请使用对应轴停车按钮停止。')
            else:
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
        # 正弦摇摆最大角速度 = 2π × 幅度(°) × 频率(Hz)。
        try:
            amp = float(inner_sway_ampl_text)
            freq = float(inner_sway_freq_text)
            peak = sway_peak_speed(amp, freq)
            if self.turntable_model == "2TD600" and (peak > MAX_ABS_SPEED_DPS or self._speed_limit_tripped):
                raise ValueError(f"摇摆理论峰值 {peak:.2f}°/s，超过 {MAX_ABS_SPEED_DPS:g}°/s 限速，或已触发限速锁定")
        except (TypeError, ValueError) as exc:
            messagebox.showwarning("转台摇摆限速", str(exc))
            return
        # 正弦摇摆最大角速度 = 2π × 幅度(°) × 频率(Hz)。
        try:
            amp = float(outer_sway_ampl_text)
            freq = float(outer_sway_freq_text)
            peak = sway_peak_speed(amp, freq)
            if self.turntable_model == "2TD600" and (peak > MAX_ABS_SPEED_DPS or self._speed_limit_tripped):
                raise ValueError(f"摇摆理论峰值 {peak:.2f}°/s，超过 {MAX_ABS_SPEED_DPS:g}°/s 限速，或已触发限速锁定")
        except (TypeError, ValueError) as exc:
            messagebox.showwarning("转台摇摆限速", str(exc))
            return
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

    def _monitor_speed_limit(self):
        """收到新的速度反馈时检查；超限发两轴停车，保持锁定。

        本机制不是硬件安全联锁，停机距离、反馈/通信延迟不可保证。
        """
        # 该新增的软件 ±10°/s 反馈限速仅保留给 2TD600。
        # 2FDT600WK 按原始 WK 工程运行，不因该软件阈值自动停车。
        if self.turntable_model == '2FDT600WK':
            return
        if self._speed_limit_tripped or self.button_TurntableCommPortOpen.text() != '关闭转台':
            return
        if not turntableData.is_turntable_data_available:
            return
        count = int(getattr(turntableData, 'update_count', 0) or 0)
        if count == self._speed_limit_last_count:
            return
        self._speed_limit_last_count = count
        last_ns = int(getattr(turntableData, 'last_update_monotonic_ns', 0) or 0)
        if last_ns <= 0 or (time.perf_counter_ns() - last_ns) > 750_000_000:
            return
        inn = float(turntableData.inner_axis_speed)
        out = float(turntableData.outer_axis_speed)
        if not feedback_overspeed(inn, out):
            return
        self._speed_limit_tripped = True
        self.all_pushbutton_setEnabled(False)
        self.pushButton_InnerStop.setEnabled(True)
        self.pushButton_OuterStop.setEnabled(True)
        self.pushButton_AllStop.setEnabled(True)
        self.timer_TurntableFaultMonitor.stop()
        self._2fdt_enable_button.setEnabled(False)
        results = []
        if turntableComm.thread_lock.acquire(timeout=0.5):
            try:
                for axis in (INNER_ROTATION_AXIS, OUTER_ROTATION_AXIS):
                    try:
                        if self.turntable_model == '2FDT600WK':
                            ok = bool(twoFDT600WK_SetAxisStop(axis, [0]))
                        else:
                            ok = bool(twoTD600_SetAxisStop(axis))
                        results.append(ok)
                    except Exception:
                        results.append(False)
            finally:
                turntableComm.thread_lock.release()
        else:
            results = [False, False]
        msg = (f'检测到反馈超速：内轴 {inn:.3f}°/s，外轴 {out:.3f}°/s，软件限值 ±{MAX_ABS_SPEED_DPS:g}°/s。\n'
               f'已尝试发送两轴停车命令（返回：{results}）。后续运动已锁定。\n'
               '请立即检查实际转速、急停及机械安全条件；软件指令不保证瞬时停车。')
        # 不使用阻塞式警告框；保持“停车”和硬件状态操作可用。
        self._speed_alarm_dialog = QMessageBox(self.pushButton_closeWindows)
        self._speed_alarm_dialog.setIcon(QMessageBox.Critical)
        self._speed_alarm_dialog.setWindowTitle('转台超速保护触发')
        self._speed_alarm_dialog.setText(msg)
        self._speed_alarm_dialog.setModal(False)
        self._speed_alarm_dialog.show()

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
        if InnerEnable is None:
            self.pushButton_InnerEnable.setText("状态未知")
            self.pushButton_InnerEnable.setStyleSheet('background: #eee; color: #555;')
        elif not InnerEnable:
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
        if OuterEnable is None:
            self.pushButton_OuterEnable.setText("状态未知")
            self.pushButton_OuterEnable.setStyleSheet('background: #eee; color: #555;')
        elif not OuterEnable:
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
        self._wk_inner_near_zero_btn.setEnabled(enable and self.turntable_model == '2FDT600WK')
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
        self.timer_SpeedLimitMonitor.start()

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
        self.timer_SpeedLimitMonitor.stop()

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

        # 保存自动发现成功的内外轴串口，下次只作为扫描顺序参考，并不跳过身份验证。
        for tag, value in (
            ('Turntable2FDT600WKInnerAxisCommPort', self.turntable_2FDT600WK_inner_axis_comm_port),
            ('Turntable2FDT600WKOuterAxisCommPort', self.turntable_2FDT600WK_outer_axis_comm_port),
        ):
            if value:
                node = root.find(tag)
                if node is not None:
                    node.text = str(value)
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

        # 控件已显示“连接”表示用户完成断开；勿用后台残留的 is_connected
        # 再向已释放的 PLC 连接写指令。只有真实连接存在时才执行安全停机确认。
        # 在真实界面里以“连接/断开”按钮为准；无 Qt 的模拟测试没有该对象。
        window = getattr(self, '_main_window_ui', None)
        chamber_button = getattr(window, 'pushButton_ConnectTC', None)
        chamber_user_connected = (chamber_button.text() == "断开") if chamber_button is not None else bool(tcComm.is_connected)
        if not chamber_user_connected:
            tcComm.is_connected = False
        if chamber_user_connected and tcComm.is_connected:
            # 连接中退出：先停止定值并验证 PLC 反馈。
            try:
                if not tcComm.thread_lock.acquire(timeout=1.0):
                    raise TimeoutError("温箱通讯锁超过 1 秒未释放")
                try:
                    result = tc_fixed_value_stop()
                finally:
                    tcComm.thread_lock.release()
                if result is False:
                    raise RuntimeError("温箱控制器未接收停止定值指令")
                with tcComm.thread_lock:
                    fixed = tc_fixed_value_state_get()
                    running = tc_run_state_get()
                if fixed is None or running is None or fixed or running:
                    raise RuntimeError("温箱运行状态未确认为停止，请先在温箱页面核实")
            except Exception as exc:
                QMessageBox.warning(self.pushButton_closeWindows,
                                    "温箱未完成安全关闭",
                                    f"温箱停车/停止定值失败：{exc}\n请确认设备状态后再退出。")
                return

        if chamber_user_connected and not tcComm.is_connected:
            QMessageBox.warning(self.pushButton_closeWindows, "温箱状态未知",
                                "温箱界面仍显示连接但通信已中断，无法确认停机。请检查实体控制器。")
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