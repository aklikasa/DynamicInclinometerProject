"""温箱界面相关"""
import os
import time
from datetime import *
from qt_dialogs import filedialog, messagebox
from PySide6.QtWidgets import *
from PySide6.QtUiTools import QUiLoader
from PySide6.QtCore import Signal, QPoint, QObject, QTimer

import sys
sys.path.append(sys.path[0] + '\\temperature_chamber')
from temperature_chamber_data_get import *


class FormTc:
    def __init__(self, main_window_ui):
        #
        # 创建控件
        #
        ui = main_window_ui

        self.tabWidget_CalMain = ui.tabWidget_CalMain

        self.lineEdit_ip = ui.lineEdit_ip
        self.pushButton_ConnectTC = ui.pushButton_ConnectTC

        self.lineEdit_UltraHighTemperature = ui.lineEdit_UltraHighTemperature
        self.lineEdit_UltraLowTemperature = ui.lineEdit_UltraLowTemperature
        self.checkBox_fixedValueRateOnOff = ui.checkBox_fixedValueRateOnOff
        self.lineEdit_fixedValueRate = ui.lineEdit_fixedValueRate
        self.lineEdit_SettingTemperature = ui.lineEdit_SettingTemperature
        self.pushButton_lightingOnOff = ui.pushButton_lightingOnOff
        self.pushButton_Set = ui.pushButton_Set

        self.pushButton_RunStop = ui.pushButton_RunStop
        self.label_FixedValueRateState = ui.label_fixedValueRateState
        self.textBrowser_MeasuredTemperature = ui.textBrowser_MeasuredTemperature

        self.textBrowser_TemperatureRate = ui.textBrowser_TemperatureRate
        self.textBrowser_SettingTemperature = ui.textBrowser_SettingTemperature

        self.pushButton_RunState = ui.pushButton_RunState
        self.pushButton_FixedValueState = ui.pushButton_FixedValueState
        self.pushButton_RunMode = ui.pushButton_RunMode
        self.pushButton_lightingState = ui.pushButton_lightingState
        self.pushButton_AlarmState = ui.pushButton_AlarmState
        self.pushButton_DeviceFaultState = ui.pushButton_DeviceFaultState
        self.pushButton_CommState = ui.pushButton_CommState
        self.pushButton_ConnectedState = ui.pushButton_ConnectedState

        #
        # 初始化控件
        #
        self.lineEdit_ip.setText('192.168.0.10')

        self.pushButton_ConnectTC.setText("连接")
        self.pushButton_ConnectTC.clicked.connect(self.pushButton_ConnectTC_Click)

        self.pushButton_RunStop.setText("运行")
        self.pushButton_RunStop.clicked.connect(self.pushButton_RunStop_Click)
        if not OFFLINE_DEBUG:
            self.pushButton_RunStop.setEnabled(False)
        else:
            self.pushButton_RunStop.setEnabled(True)

        self.pushButton_Set.clicked.connect(self.pushButton_Set_Click)

        self.lineEdit_UltraHighTemperature.setText("90")
        self.lineEdit_UltraLowTemperature.setText("-45")
        self.checkBox_fixedValueRateOnOff.setChecked(False)
        self.lineEdit_fixedValueRate.setText("2")
        self.lineEdit_SettingTemperature.setText("25")
        self.pushButton_lightingOnOff.setText("照明打开")
        self.pushButton_lightingOnOff.clicked.connect(self.pushButton_lightingOnOff_Click)
        self.pushButton_lightingOnOff.setEnabled(False)
        self.pushButton_Set.setEnabled(False)

        self.textBrowser_MeasuredTemperature.setText(" ")
        self.label_FixedValueRateState.setText(" ")
        self.textBrowser_TemperatureRate.clear()
        self.textBrowser_SettingTemperature.clear()

        self.pushButton_RunState.setText("设备运行/停机")
        self.pushButton_FixedValueState.setText("定值启动/停止")
        self.pushButton_RunMode.setText("定值/程序模式")
        self.pushButton_lightingState.setText("照明开/关")
        self.pushButton_AlarmState.setText("报警值")
        self.pushButton_DeviceFaultState.setText("设备故障")
        self.pushButton_CommState.setText("通讯正常")
        self.pushButton_ConnectedState.setText("未连接")

        #
        # 创建定时器
        #
        self.timer_TemperatureDisplay = self.create_timer(100, self.timer_TemperatureDisplay_Tick)
        self.timer_TcStateDisplay = self.create_timer(100, self.timer_TcStateDisplay_Tick)
        self.timer_TcFaultMonitor = self.create_timer(3000, self.timer_TcFaultMonitor_Tick)


        #
        # 其它
        #
        # 温箱故障计数
        self.tc_fault_conut = 0
        self.TC_FAULT_COUNT_THRESHOLD = 5  # 温箱故障计数阈值

    def pushButton_ConnectTC_Click(self):
        """
            "pushButton_ConnectTC"按钮的鼠标点击事件函数
        """
        # 检查是否输入了ip地址
        text = self.lineEdit_ip.text()
        if text == "":
            messagebox.showerror("", "请输入温箱ip地址！")
            return
        ip = text

        # 连接/断开处理
        if self.pushButton_ConnectTC.text() == "连接":
            # 连接温箱
            tcComm.thread_lock.acquire()
            ret = tc_connect(ip)
            tcComm.thread_lock.release()
            if not ret:
                messagebox.showerror("", "温箱连接失败！")
                return

            # 创建并启动温箱数据获取线程
            thread_of_tc_data_get_create_and_start()

            # 按钮全部设置为可点击
            self.all_pushbutton_setEnabled(True)

            # 启动相关定时器
            self.timer_TemperatureDisplay.start()
            self.timer_TcStateDisplay.start()

            # 根据定值启动/停止状态对运行停止按钮赋值
            if tcState.is_fixed_value_startup:
                self.pushButton_RunStop.setText("停止")
            else:
                self.pushButton_RunStop.setText("运行")

            self.pushButton_ConnectTC.setText("断开")
        else:
            # 请求终止温箱数据获取线程
            tcComm.terminate_thread_requst = True
            while True:
                if tcComm.thread_instance == None:
                    break

            # 断开连接
            tcComm.thread_lock.acquire()
            tc_disconnect()
            tcComm.thread_lock.release()

            # 设置栏控件设置为使能状态
            self.lineEdit_UltraHighTemperature.setEnabled(True)
            self.lineEdit_UltraLowTemperature.setEnabled(True)
            self.checkBox_fixedValueRateOnOff.setEnabled(True)
            self.lineEdit_fixedValueRate.setEnabled(True)

            # 按钮全部设置为不可点击
            self.all_pushbutton_setEnabled(False)

            # 关闭相关定时器
            self.timer_TemperatureDisplay.stop()
            self.timer_TcStateDisplay.stop()

            # 信号灯与数据框恢复默认设置
            self.all_signal_button_restore_default_state()
            self.pushButton_ConnectTC.setText("连接")

    def pushButton_RunStop_Click(self):
        """
            "pushButton_RunStop"按钮的鼠标点击事件函数
        """
        if self.pushButton_RunStop.text() == "运行":
            # 检查温箱是否故障
            if tcState.is_device_fault or (tcState.alarm_value != 0):
                messagebox.showerror("", "温箱故障或报警！不能启动温箱运行")
                return

            if not OFFLINE_DEBUG:
                # 设置温箱相关参数
                self.pushButton_Set_Click()

                # 启动温箱定值运行
                tcComm.thread_lock.acquire()
                ret = tc_fixed_value_startup()
                tcComm.thread_lock.release()
                if not ret:
                    messagebox.showerror("", "启动温箱定值运行失败！")
                    return

            # 启动相关定时器
            self.tc_fault_conut = 0
            self.timer_TcFaultMonitor.start()

            # 设置栏控件设置为不使能状态
            # self.lineEdit_UltraHighTemperature.setEnabled(False)
            # self.lineEdit_UltraLowTemperature.setEnabled(False)
            # self.checkBox_fixedValueRateOnOff.setEnabled(False)
            # self.lineEdit_fixedValueRate.setEnabled(False)

            self.pushButton_RunStop.setText("停止")
        else:
            # 停止温箱定值运行
            tcComm.thread_lock.acquire()
            ret = tc_fixed_value_stop()
            tcComm.thread_lock.release()
            if not ret:
                messagebox.showerror("", "停止温箱定值运行失败！")
            # 停止相关定时器
            self.timer_TcFaultMonitor.stop()
            self.pushButton_RunStop.setText("运行")

    def pushButton_lightingOnOff_Click(self):
        """
            "pushButton_lightingOnOff"按钮的鼠标点击事件函数
        """
        if self.pushButton_lightingOnOff.text() == "照明打开":
            tcComm.thread_lock.acquire()
            ret = tc_lighting_on()
            tcComm.thread_lock.release()
            if not ret:
                messagebox.showerror("", "照明打开失败！")
                return
            self.pushButton_lightingOnOff.setText("照明关闭")
        elif self.pushButton_lightingOnOff.text() == "照明关闭":
            tcComm.thread_lock.acquire()
            ret = tc_lighting_off()
            tcComm.thread_lock.release()
            if not ret:
                messagebox.showerror("", "照明关闭失败！")
                return
            self.pushButton_lightingOnOff.setText("照明打开")

    def pushButton_Set_Click(self):
        """
            "pushButton_Set"按钮的鼠标点击事件函数
        """
        # 超高温设置
        temp_value = float(self.lineEdit_UltraHighTemperature.text())
        tcComm.thread_lock.acquire()
        ret = tc_ultra_high_temperature_set(temp_value)
        tcComm.thread_lock.release()
        if not ret:
            messagebox.showerror("", "超高温设置失败！")
            #return
        # 超低温设置
        temp_value = float(self.lineEdit_UltraLowTemperature.text())
        tcComm.thread_lock.acquire()
        ret = tc_ultra_low_temperature_set(temp_value)
        tcComm.thread_lock.release()
        if not ret:
            messagebox.showerror("", "超低温设置失败！")
            #return
        # 定值速率开关
        if self.checkBox_fixedValueRateOnOff.isChecked():
            tcComm.thread_lock.acquire()
            ret = tc_fixed_value_rate_on()
            tcComm.thread_lock.release()
            if not ret:
                messagebox.showerror("", "打开定值速率失败！")
                return
        else:
            tcComm.thread_lock.acquire()
            ret = tc_fixed_value_rate_off()
            tcComm.thread_lock.release()
            if not ret:
                messagebox.showerror("", "关闭定值速率失败！")
                return
        # 定值速率
        fixed_value_rate = float(self.lineEdit_fixedValueRate.text())
        tcComm.thread_lock.acquire()
        ret = tc_fixed_value_rate_set(fixed_value_rate)
        tcComm.thread_lock.release()
        if not ret:
            messagebox.showerror("", "定值速率设置失败！")
            return
        # 设定温度目标值
        temp_value = float(self.lineEdit_SettingTemperature.text())
        tcComm.thread_lock.acquire()
        ret = tc_sp_set(temp_value)
        tcComm.thread_lock.release()
        if not ret:
            messagebox.showerror("", "温度目标值设置失败！")
            return

    def all_pushbutton_setEnabled(self, enable):
        """
            设置所有按钮为可点击
        """
        self.pushButton_lightingOnOff.setEnabled(enable)
        self.pushButton_Set.setEnabled(enable)
        self.pushButton_RunStop.setEnabled(enable)

    def all_signal_button_restore_default_state(self):
        """
            点击断开连接按钮后，状态灯，lineEdit恢复默认状态
        """
        # 清空温箱数据显示框
        self.textBrowser_MeasuredTemperature.setText(" ")
        self.label_FixedValueRateState.setText(" ")
        self.textBrowser_TemperatureRate.clear()
        self.textBrowser_SettingTemperature.clear()

        # 温箱状态灯
        self.pushButton_RunState.setText("设备运行/停机")
        self.pushButton_RunState.setStyleSheet('background: #f0f2f3; color: #7f8991; border: 1px solid #d6dce0; border-radius: 7px;')

        self.pushButton_FixedValueState.setText("定值运行/停止")
        self.pushButton_FixedValueState.setStyleSheet('background: #f0f2f3; color: #7f8991; border: 1px solid #d6dce0; border-radius: 7px;')

        self.pushButton_RunMode.setText("定值/程序模式")
        self.pushButton_RunMode.setStyleSheet('background: #f0f2f3; color: #7f8991; border: 1px solid #d6dce0; border-radius: 7px;')

        self.pushButton_lightingState.setText("照明开/关")
        self.pushButton_lightingState.setStyleSheet('background: #f0f2f3; color: #7f8991; border: 1px solid #d6dce0; border-radius: 7px;')

        self.pushButton_AlarmState.setText("报警值")
        self.pushButton_AlarmState.setStyleSheet('background: #f0f2f3; color: #7f8991; border: 1px solid #d6dce0; border-radius: 7px;')

        self.pushButton_DeviceFaultState.setText("设备故障")
        self.pushButton_DeviceFaultState.setStyleSheet('background: #f0f2f3; color: #7f8991; border: 1px solid #d6dce0; border-radius: 7px;')

        self.pushButton_CommState.setText("通讯正常")
        self.pushButton_CommState.setStyleSheet('background: #f0f2f3; color: #7f8991; border: 1px solid #d6dce0; border-radius: 7px;')

        self.pushButton_ConnectedState.setText("未连接")
        self.pushButton_ConnectedState.setStyleSheet('background: #f0f2f3; color: #7f8991; border: 1px solid #d6dce0; border-radius: 7px;')

    def timer_TemperatureDisplay_Tick(self):
        """
        定时获取和显示温箱实测温度等
        """
        self.textBrowser_MeasuredTemperature.setText(str(tcData.pv) + "℃")
        self.textBrowser_TemperatureRate.setText(str(tcData.temperature_rate))
        self.textBrowser_SettingTemperature.setText(str(tcData.sp))
        if tcData.is_fixed_value_rate_on:
            self.label_FixedValueRateState.setText("开")
        else:
            self.label_FixedValueRateState.setText("关")

    def timer_TcStateDisplay_Tick(self):
        """
        定时获取和显示温箱状态等
        """
        # 设备运行/停机
        if tcState.is_device_running:
            self.pushButton_RunState.setText("设备运行")
            self.pushButton_RunState.setStyleSheet('background: #e9f3ed; color: #43745b; border: 1px solid #cce1d3; border-radius: 7px;')
        else:
            self.pushButton_RunState.setText("设备停机")
            self.pushButton_RunState.setStyleSheet('background: #f0f2f3; color: #7f8991; border: 1px solid #d6dce0; border-radius: 7px;')

        # 定值启动/停止
        if tcState.is_fixed_value_startup:
            self.pushButton_FixedValueState.setText("定值运行")
            self.pushButton_FixedValueState.setStyleSheet('background: #e9f3ed; color: #43745b; border: 1px solid #cce1d3; border-radius: 7px;')
        else:
            self.pushButton_FixedValueState.setText("定值停止")
            self.pushButton_FixedValueState.setStyleSheet('background: #f0f2f3; color: #7f8991; border: 1px solid #d6dce0; border-radius: 7px;')

        # 定值/程序模式
        if tcState.is_fixed_value_mode:
            self.pushButton_RunMode.setText("定值模式")
            self.pushButton_RunMode.setStyleSheet('background: #f0f2f3; color: #7f8991; border: 1px solid #d6dce0; border-radius: 7px;')
        else:
            self.pushButton_RunMode.setText("程序模式")
            self.pushButton_RunMode.setStyleSheet('background: #f0f2f3; color: #7f8991; border: 1px solid #d6dce0; border-radius: 7px;')

        # 照明开/关
        if tcState.is_lighting_on:
            self.pushButton_lightingState.setText("照明开")
            self.pushButton_lightingState.setStyleSheet('background: #e9f3ed; color: #43745b; border: 1px solid #cce1d3; border-radius: 7px;')
        else:
            self.pushButton_lightingState.setText("照明关")
            self.pushButton_lightingState.setStyleSheet('background: #f0f2f3; color: #7f8991; border: 1px solid #d6dce0; border-radius: 7px;')

        # 报警值
        if tcState.alarm_value != 0:
            self.pushButton_AlarmState.setText("报警" + "("+ str(tcState.alarm_value) + ")")
            self.pushButton_AlarmState.setStyleSheet('background: #f9e9e9; color: #a35d5d; border: 1px solid #eccaca; border-radius: 7px;')
        else:
            self.pushButton_AlarmState.setText("未报警")
            self.pushButton_AlarmState.setStyleSheet('background: #e9f3ed; color: #43745b; border: 1px solid #cce1d3; border-radius: 7px;')

        # 设备故障
        if tcState.is_device_fault:
            self.pushButton_DeviceFaultState.setText("设备故障")
            self.pushButton_DeviceFaultState.setStyleSheet('background: #f9e9e9; color: #a35d5d; border: 1px solid #eccaca; border-radius: 7px;')
        else:
            self.pushButton_DeviceFaultState.setText("设备正常")
            self.pushButton_DeviceFaultState.setStyleSheet('background: #e9f3ed; color: #43745b; border: 1px solid #cce1d3; border-radius: 7px;')

        # 通讯状态
        if not tcComm.is_comm_error:
            self.pushButton_CommState.setText("通讯正常")
            self.pushButton_CommState.setStyleSheet('background: #e9f3ed; color: #43745b; border: 1px solid #cce1d3; border-radius: 7px;')
        else:
            self.pushButton_CommState.setText("通讯错误")
            self.pushButton_CommState.setStyleSheet('background: #f9e9e9; color: #a35d5d; border: 1px solid #eccaca; border-radius: 7px;')

        # 连接状态
        if tcComm.is_connected:
            self.pushButton_ConnectedState.setText("已连接")
            self.pushButton_ConnectedState.setStyleSheet('background: #e9f3ed; color: #43745b; border: 1px solid #cce1d3; border-radius: 7px;')
        else:
            self.pushButton_ConnectedState.setText("未连接")
            self.pushButton_ConnectedState.setStyleSheet('background: #f9e9e9; color: #a35d5d; border: 1px solid #eccaca; border-radius: 7px;')

    def timer_TcFaultMonitor_Tick(self):
        """
        定时监测温箱故障
        """
        if tcState.is_device_fault or (tcState.alarm_value != 0):
            self.tc_fault_conut += 1
        else:
            self.tc_fault_conut = 0 # 温箱连续故障N次才进行处理！！！
        if self.tc_fault_conut == self.TC_FAULT_COUNT_THRESHOLD:
            # 防止重复错误提示！！！
            self.timer_TcFaultMonitor.stop()
            self.tc_fault_conut = self.TC_FAULT_COUNT_THRESHOLD + 1
            # 停止温箱定值运行
            tcComm.thread_lock.acquire()
            ret = tc_fixed_value_stop()
            tcComm.thread_lock.release()
            # 更新自动运行状态相关信息
            if autoRunState.auto_run_state != "停止":
                autoRunState.thread_lock.acquire()
                autoRunState.auto_run_state = "错误"
                autoRunState.auto_run_info +="温箱故障或报警！" + "\r\n"
                autoRunState.thread_lock.release()
                # 记录错误信息至日志
                # 请求中止加速度计校准
                #thread_of_acc_cal_terminate()
                # 请求并等待温度传感器校准线程退出
                #thread_of_tps_cal_terminate()
                # 请求并等待X-MARK校准线程退出
                #thread_of_xmark_cal_terminate()
                # 给出提示
                messagebox.showerror("", "温箱故障或报警！")
                autoRunState.thread_lock.acquire()
                autoRunState.auto_run_state = "停止"
                # autoRunState.button_text_AccCalRun = "自动运行"
                # autoRunState.button_text_TpsCalRun = "自动运行"
                # autoRunState.button_text_XMARKCalRun = "自动运行"
                autoRunState.thread_lock.release()
            else:
                messagebox.showerror("", "温箱故障或报警！")

    def create_timer(self, interval, task):
        """
            创建自定义QTimer，方便多次调用
        """
        timer = QTimer()
        timer.timeout.connect(task)
        timer.setInterval(interval)
        return timer


