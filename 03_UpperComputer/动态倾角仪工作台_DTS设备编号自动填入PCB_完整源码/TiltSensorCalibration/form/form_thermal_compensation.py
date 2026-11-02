# -*- coding: utf-8 -*-
"""2FDT600WK temperature-compensation experiment page.

Real 2FDT motor DLL + real live MCU IMU frames; no simulated success path.
The field-proven original Snap7 PLC chamber is the default automatic path.
Manual control is an explicit fallback; unknown RS232 commands are never sent.
"""
import copy
import csv
import datetime
import json
import math
import os
from pathlib import Path
import queue
import time
import numpy as np
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox,
    QLabel, QPushButton, QCheckBox, QComboBox, QLineEdit, QDoubleSpinBox,
    QSpinBox, QPlainTextEdit, QProgressBar, QFileDialog, QMessageBox, QScrollArea)

from turntable_data_get import turntableComm, turntableData, turntableState
from turntable_2FDT600WK_comm import (INNER_ROTATION_AXIS, OUTER_ROTATION_AXIS,
    twoFDT600WK_SetAxisPosition, twoFDT600WK_SetAxisVelocity, twoFDT600WK_SetAxisStop)
from tilt_sensor_asm330_data_get import (tiltSensorComm, tiltSensorRawData,
    tilt_sensor_calibration_queue_set, tilt_sensor_calibration_frame_get_nowait,
    tilt_sensor_calibration_queue_drop_count_get)
from temperature_chamber_data_get import tcData, tcState, tcComm
from temperature_chamber_comm import tc_set_fixed_value_mode, tc_sp_set, tc_fixed_value_startup, tc_fixed_value_stop
from chamber_auto_guard import require_live_chamber, require_setpoint_ack, ChamberSafetyError
from debug import OFFLINE_DEBUG
from production_calibration import (load_profile, acc_fit_steps, acc_verify_steps,
    gyro_fit_steps, gyro_verify_steps, frame_average_sanitized, robust_segment)
from form_imu_calibration import _platform_gravity_vector, _platform_angular_rate
from thermal_compensation import save_models, build_gyro_zero_bias_model
from thermal_excel_report import export_thermal_xlsx

ROOT = Path(__file__).resolve().parents[1]
LOCKABLE = ('button_TurntableCommPortOpen', 'comboBox_TurntableModelSelect',
    'pushButton_InnerReturnZero','pushButton_OuterReturnZero','pushButton_AllReturnZero',
    'pushButton_InnerRun','pushButton_OuterRun','pushButton_AllRun',
    'pushButton_InnerRunForSpeedMode','pushButton_OuterRunForSpeedMode',
    'pushButton_InnerRunForSwayMode','pushButton_OuterRunForSwayMode')


def _angle_error(a,b):
    return (float(a)-float(b)+180) % 360-180


class FormThermalCompensation:
    def __init__(self, ui, turntable_form, ambient_form):
        self.ui, self.turntable_form, self.ambient_form = ui, turntable_form, ambient_form
        self.task = None
        self._locked_buttons = {}
        self._locked_tc_buttons = {}
        self._locked_ambient_buttons = {}
        self.page = QWidget()
        self.page.setObjectName('page_ImuThermalCompensation')
        self._make_ui()
        ui.tabWidget_CalMain.addTab(self.page, 'IMU 自动温补')
        self.timer = QTimer(self.page)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

    def _make_ui(self):
        outer = QVBoxLayout(self.page)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        layout = QVBoxLayout(body)
        scroll.setWidget(body)
        outer.addWidget(scroll)

        desc = QLabel('2FDT600WK 温补。优先复用已在本机实测设温成功的 Snap7/PLC 温箱接口：自动设温、回读确认、等待PV和芯片热平衡、真实转台/IMU采集。'
                      '仅在PLC不可用且操作员主动选择时使用人工设温。拟合结果为研发候选，不覆盖常温参数。')
        desc.setWordWrap(True)
        desc.setStyleSheet('color:#795c26;background:#fbf4e5;padding:8px;border-radius:7px')
        layout.addWidget(desc)
        box = QGroupBox('实验配置（温度点按输入顺序执行）')
        g = QGridLayout(box)
        g.addWidget(QLabel('PCB 唯一编号'),0,0)
        self.sn = QLineEdit()
        self.sn.setPlaceholderText('连接后自动填入；不支持UID时手动输入')
        self.sn.setToolTip('与IMU标定页自动同步PCB编号；温补记录也保存此编号')
        g.addWidget(self.sn,0,1)
        g.addWidget(QLabel('温度工况 ℃'),1,0)
        self.temperatures = QLineEdit('-20, 0, 25, 45, 70')
        self.temperatures.setToolTip('其中拟合点默认第 1、3、5 个；验证点为第 2、4 个')
        g.addWidget(self.temperatures,1,1,1,3)
        g.addWidget(QLabel('温箱方式'),2,0)
        self.chamber_mode = QComboBox()
        self.chamber_mode.addItem('自动控温：使用原上位机已验证的 Snap7/PLC 温箱（推荐）', 'plc')
        self.chamber_mode.addItem('人工设温：仅限PLC不可用时（逐点确认）', 'manual')
        g.addWidget(self.chamber_mode,2,1,1,3)
        self.chamber_mode.currentIndexChanged.connect(self._on_chamber_mode_changed)
        g.addWidget(QLabel('原温箱实测 PV ℃'),3,0)
        self.manual_pv = QDoubleSpinBox()
        self.manual_pv.setRange(-45,110)
        self.manual_pv.setDecimals(2)
        self.manual_pv.setValue(25)
        g.addWidget(self.manual_pv,3,1)
        self.confirm_temp = QPushButton('确认本温度点已到温')
        self.confirm_temp.setEnabled(False)
        self.confirm_temp.clicked.connect(self._confirm_temperature)
        g.addWidget(self.confirm_temp,3,2,1,2)
        self.plc_telemetry = QLabel('PLC 反馈：等待连接；自动模式禁止使用离线/缓存温度')
        self.plc_telemetry.setWordWrap(True)
        g.addWidget(self.plc_telemetry,8,0,1,4)
        g.addWidget(QLabel('热平衡最短时长 (秒)'),4,0)
        self.dwell = QSpinBox(); self.dwell.setRange(300,7200); self.dwell.setValue(1800)
        g.addWidget(self.dwell,4,1)
        g.addWidget(QLabel('每工况采样 (秒)'),4,2)
        self.sample_seconds = QSpinBox(); self.sample_seconds.setRange(5,120); self.sample_seconds.setValue(5)
        g.addWidget(self.sample_seconds,4,3)
        g.addWidget(QLabel('静置等待 (秒)'),5,0)
        self.settle = QSpinBox(); self.settle.setRange(3,60); self.settle.setValue(3)
        g.addWidget(self.settle,5,1)
        g.addWidget(QLabel('姿态运动速度 °/s'),5,2)
        self.move_speed = QDoubleSpinBox(); self.move_speed.setRange(0.2,5); self.move_speed.setValue(2)
        g.addWidget(self.move_speed,5,3)
        self.dynamic = QCheckBox('执行 GYRO 三轴正反速率温补（±1/±2/±5 拟合；±1.5/±3.5 验证）')
        self.dynamic.setChecked(True)
        g.addWidget(self.dynamic,6,0,1,4)
        self.return_ambient = QCheckBox('PLC自动控温完成后自动回到 25°C，确认PV到温后再结束任务')
        self.return_ambient.setChecked(True)
        g.addWidget(self.return_ambient,9,0,1,4)
        g.addWidget(QLabel('保存目录'),7,0)
        self.output = QLineEdit(str(Path.home()/'IMU_Thermal_Experiments'))
        g.addWidget(self.output,7,1,1,2)
        browse = QPushButton('选择…'); browse.clicked.connect(self._browse)
        g.addWidget(browse,7,3)
        layout.addWidget(box)
        group = QGroupBox('启动条件与安全确认')
        gh = QVBoxLayout(group)
        self.check_axis = QCheckBox('已在实机核对 2FDT 内/外轴与 P 坐标系的方向、零位、正转定义；已完成找零')
        self.check_safe = QCheckBox('已确认装夹、配平、线缆、机械范围、门禁和硬件急停；全过程安排人员监护')
        self.check_sensor = QCheckBox('已核对 MCU 量程/ODR 不变、温度传感器有效，且现有常温标定不会被覆盖')
        for w in (self.check_axis,self.check_safe,self.check_sensor): gh.addWidget(w)
        self.check_plc = QCheckBox('已在这台如洋温箱上实测验证：原温箱页面能读取PV、设定SP，并确实发生升/降温（PLC自动模式必选）')
        gh.addWidget(self.check_plc)
        self._on_chamber_mode_changed()
        layout.addWidget(group)
        row = QHBoxLayout()
        self.start_button = QPushButton('启动自动温补实验')
        self.start_button.clicked.connect(self.start)
        self.stop_button = QPushButton('中止并停车')
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(lambda: self._abort('操作员主动中止'))
        row.addWidget(self.start_button,2); row.addWidget(self.stop_button,1)
        layout.addLayout(row)
        self.label = QLabel('状态：空闲');self.label.setWordWrap(True)
        layout.addWidget(self.label)
        self.progress = QProgressBar(); layout.addWidget(self.progress)
        self.log = QPlainTextEdit(); self.log.setReadOnly(True);self.log.setMinimumHeight(145)
        layout.addWidget(self.log)
        layout.addStretch(1)

    def _on_chamber_mode_changed(self, *args):
        auto = self.chamber_mode.currentData()=='plc'
        self.manual_pv.setEnabled(not auto)
        self.check_plc.setEnabled(auto)
        if auto:
            self.confirm_temp.setEnabled(False)
            self.plc_telemetry.setText('PLC自动控温：任务启动前检查PV/SP/运行/报警读取新鲜度；写SP后必须回读确认。')
        else:
            self.plc_telemetry.setText('人工模式：必须逐温度点在面板设温和确认PV，不发送任何未知RS-232命令。')

    @staticmethod
    def _plc_snapshot():
        return {'connected':tcComm.is_connected,
            'data_available':tcData.is_tc_data_available,
            'pv_failed':tcComm.is_pv_get_failed,
            'pv':float(tcData.pv), 'sp':float(tcData.sp),
            'pv_updated':tcData.pv_update_monotonic,
            'sp_updated':tcData.sp_update_monotonic,
            'alarm':tcState.alarm_value, 'fault':tcState.is_device_fault,
            'alarm_updated':tcState.alarm_update_monotonic,
            'fault_updated':tcState.fault_update_monotonic,
            'running':tcState.is_device_running,
            'fixed_started':tcState.is_fixed_value_startup,
            'fixed_mode':tcState.is_fixed_value_mode,
            'run_updated':tcState.run_update_monotonic,
            'started_updated':tcState.fixed_start_update_monotonic,
            'mode_updated':tcState.mode_update_monotonic}

    def _require_plc(self, now):
        data=self._plc_snapshot()
        require_live_chamber(data,now)
        return data

    def _issue_plc_setpoint(self, target):
        if OFFLINE_DEBUG:
            raise RuntimeError('离线调试模式禁止向温箱发自动设温命令')
        self._require_plc(time.monotonic())
        with tcComm.thread_lock:
            # Exactly the same proven PLC writes as the original temperature page.
            # No RS232 vendor command is guessed here.
            ok_mode=tc_set_fixed_value_mode()
            ok_sp=tc_sp_set(float(target)) if ok_mode else False
            ok_start=tc_fixed_value_startup() if ok_sp else False
        if not (ok_mode and ok_sp and ok_start):
            raise RuntimeError('PLC定值模式/设温/启动写入失败（不能继续温补）')

    def _browse(self):
        path = QFileDialog.getExistingDirectory(self.page,'选择实验根目录',self.output.text())
        if path:self.output.setText(path)

    def _log(self, message):
        self.log.appendPlainText(datetime.datetime.now().strftime('%H:%M:%S')+' '+message)
        if self.task:
            self.task['events'].append({'timestamp':datetime.datetime.now().isoformat(), 'message':message})

    def _valid_device(self):
        if turntableComm.turntable_model != '2FDT600WK':
            raise ValueError('必须在转台页连接 2FDT600WK；严禁错用 2TD600')
        if not turntableData.is_turntable_data_available or time.time()-turntableData.last_update_time_sec>3:
            raise ValueError('转台实测反馈离线/超时')
        if not (turntableState.is_inner_axis_in_enable and turntableState.is_outer_axis_in_enable):
            raise ValueError('两轴没有全部使能')
        if not (turntableState.is_inner_axis_normal and turntableState.is_outer_axis_normal):
            raise ValueError('转台报警或未处于正常状态')
        if (turntableState.is_inner_axis_over_diff or turntableState.is_outer_axis_over_diff or
                turntableState.is_inner_axis_driver_fault or turntableState.is_outer_axis_driver_fault):
            raise ValueError('转台伺服超差/驱动故障')
        if not tiltSensorComm.is_serial_opened or not tiltSensorComm.is_data_available:
            raise ValueError('IMU 串口未连接或数据无效')
        if self.ambient_form._auto_task is not None or self.ambient_form.recording:
            raise ValueError('常温自动任务或原始记录运行中；不能并行启动')
        with tiltSensorRawData.data_lock:
            if not tiltSensorRawData.is_data_valid or tiltSensorRawData.data_update_count <= 0:
                raise ValueError('IMU 没有真实有效的新测量数据')

    def _motion_status(self):
        self._valid_device()
        if not np.all(np.isfinite([turntableData.inner_axis_position, turntableData.outer_axis_position,
                                   turntableData.inner_axis_speed, turntableData.outer_axis_speed])):
            raise ValueError('转台反馈包含 NaN/Inf')

    def _stopped(self):
        return abs(turntableData.inner_axis_speed) < 0.05 and abs(turntableData.outer_axis_speed) < 0.05

    def _move(self, inner, outer):
        if not self._stopped():
            raise ValueError('两轴未停车，不允许发送定位命令')
        if not all(math.isfinite(v) and 0 <= v <= 360 for v in (inner,outer)):
            raise ValueError('目标角超出已审核 0–360° 工况范围')
        with turntableComm.thread_lock:
            code=[0]
            ok1=twoFDT600WK_SetAxisPosition(INNER_ROTATION_AXIS,float(inner),float(self.move_speed.value()),code)
            ok2=twoFDT600WK_SetAxisPosition(OUTER_ROTATION_AXIS,float(outer),float(self.move_speed.value()),code) if ok1 else False
        if not (ok1 and ok2):
            raise RuntimeError(f'2FDT 定位指令失败：code={code[0]}')

    def _rate_command(self,axis,rate):
        if abs(rate)>5.0 or not math.isfinite(rate):
            raise ValueError('超出温补试验速度 5°/s 安全限幅')
        with turntableComm.thread_lock:
            code=[0]
            ok=twoFDT600WK_SetAxisVelocity(INNER_ROTATION_AXIS if axis=='inner' else OUTER_ROTATION_AXIS,
                                         float(rate),1,code)
        if not ok:raise RuntimeError(f'2FDT 匀速指令失败：{code[0]}')

    def _stop_axes(self):
        results=[]
        with turntableComm.thread_lock:
            for axis in (INNER_ROTATION_AXIS,OUTER_ROTATION_AXIS):
                code=[0]
                try: results.append(bool(twoFDT600WK_SetAxisStop(axis,code)))
                except Exception:results.append(False)
        return all(results)

    def _lock_ui(self, locked):
        for w in (self.sn,self.temperatures,self.chamber_mode,self.dwell,self.sample_seconds,
                  self.settle,self.move_speed,self.dynamic,self.output,self.return_ambient):
            w.setEnabled(not locked)
        if not locked:self._on_chamber_mode_changed()
        if locked:
            for name in LOCKABLE:
                w=getattr(self.turntable_form,name,None)
                if w is not None:
                    self._locked_buttons[name]=w.isEnabled()
                    w.setEnabled(False)
            for name in ('button_accel_plan','button_gyro_plan','button_compare_acc',
                         'button_compare_gyro','button_alignment_check','button_record_start'):
                w=getattr(self.ambient_form,name,None)
                if w is not None:
                    self._locked_ambient_buttons[name]=w.isEnabled()
                    w.setEnabled(False)
            if self.chamber_mode.currentData()=='plc':
                for name in ('pushButton_Set','pushButton_RunStop','pushButton_ConnectTC'):
                    w=getattr(self.ui,name,None)
                    if w is not None:
                        self._locked_tc_buttons[name]=w.isEnabled()
                        w.setEnabled(False)
        else:
            for name,old in self._locked_ambient_buttons.items():
                w=getattr(self.ambient_form,name,None)
                if w is not None:w.setEnabled(old)
            self._locked_ambient_buttons.clear()
            for name,old in self._locked_tc_buttons.items():
                w=getattr(self.ui,name,None)
                if w is not None:w.setEnabled(old)
            self._locked_tc_buttons.clear()
            for name,old in self._locked_buttons.items():
                w=getattr(self.turntable_form,name,None)
                if w is not None:w.setEnabled(old)
            self._locked_buttons.clear()

    @staticmethod
    def _steps(dynamic,profile):
        steps=[]
        for row in acc_fit_steps()+acc_verify_steps():
            steps.append({**row,'sensor':'acc', 'reference_kind':'gravity'})
        # At each temperature collect zero rate at two independent orientations.
        for split, name in (('fit','GYRO_ZERO_FIT'),('validate','GYRO_ZERO_VAL')):
            steps.append({'mode':'static','step_id':name,'split':split,'sensor':'gyro',
                          'inner_deg':0.0,'outer_deg':0.0,'sample_seconds':max(20 if split=='fit' else 10,
                                                      float(profile['timing']['gyro_zero_seconds'] if split=='fit' else 10))})
        if dynamic:
            for row in gyro_fit_steps(profile)+gyro_verify_steps(profile):
                if row['mode']=='rate': steps.append({**row,'sensor':'gyro'})
        return steps

    def start(self):
        if self.task is not None:return
        try:
            self._valid_device()
            if not all(w.isChecked() for w in (self.check_axis,self.check_safe,self.check_sensor)):
                raise ValueError('必须确认全部安全项、坐标系和标定配置')
            if OFFLINE_DEBUG:raise ValueError('禁止在OFFLINE_DEBUG下启动真实温补实验')
            if not self._stopped():raise ValueError('开始前两轴必须静止')
            temperatures=[float(s.strip()) for s in self.temperatures.text().replace('，',',').split(',')]
            if len(temperatures)<5 or len(set(temperatures))!=len(temperatures) or any(not -40<=t<=85 for t in temperatures):
                raise ValueError('首轮须提供至少 5 个不同温度点，范围 -40～85℃')
            if temperatures!=sorted(temperatures):
                raise ValueError('当前流程要求温度点从低到高排列；完整温度循环请单独做第二次实验')
            profile=copy.deepcopy(load_profile(str(ROOT)))
            profile['quality']['temperature_min_c']=-45.0
            profile['quality']['temperature_max_c']=90.0
            profile['quality']['temperature_span_max_c']=0.5
            # GYRO 参考速度不从指令猜测，而来自转台编码器角度差分。
            if self.dynamic.isChecked() and not turntableData.is_turntable_data_available:
                raise ValueError('动态温补没有可用的转台反馈测速')
            if self.chamber_mode.currentData()=='plc':
                if not self.check_plc.isChecked():
                    raise ValueError('PLC自动控温前必须确认原上位机在本设备上实测设温成功')
                if OFFLINE_DEBUG:raise ValueError('OFFLINE_DEBUG 模式禁止真实自动控温实验')
                self._require_plc(time.monotonic())
            if not self.sn.text().strip():raise ValueError('PCB 唯一编号必填')
            folder=Path(self.output.text().strip()).expanduser().resolve()/('THERM_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S'))
            folder.mkdir(parents=True,exist_ok=False)
            steps=self._steps(self.dynamic.isChecked(),profile)
            # Preserve original run config and raw units; never overwrite ambient calibration.
            self.task={'run_dir':str(folder),'device_sn':self.sn.text().strip(),
                'temps':temperatures,'temp_i':0,'steps':steps,'step_i':0,'rows':[],
                'events':[],'profile':profile,'phase':'next_temperature',
                'phase_start':time.monotonic(),'stable_since':None,'frames':[],
                'frame_count':0,'last_frame':None,'chip_trace':[], 'retry_count':0,
                'baseline_config':(tiltSensorRawData.acc_fs,tiltSensorRawData.gyro_fs,tiltSensorRawData.data_odr),
                'last_imu_count':int(tiltSensorRawData.data_update_count),'last_imu_change':time.monotonic(),
                'dynamic':self.dynamic.isChecked(),'manual':self.chamber_mode.currentData()=='manual',
                'return_ambient':self.return_ambient.isChecked(),
                'axis_model':'outer_x_inner_z', 'temperature_split_by_setpoint':{
                   t: ('validate' if i%2 else 'fit') for i,t in enumerate(temperatures)}}
            if len([t for t in temperatures if self.task['temperature_split_by_setpoint'][t]=='fit'])<3:
                raise ValueError('至少三个拟合温度点')
            with (folder/'experiment_config.json').open('w',encoding='utf-8') as f:
                json.dump({'device_sn':self.task['device_sn'],'temperature_setpoints_c':temperatures,
                    'temperature_split':self.task['temperature_split_by_setpoint'],
                    'axis_model_confirmed_by_operator':True,'chamber_control':self.chamber_mode.currentData(),
                    'gyro_dynamic':self.dynamic.isChecked(),'quality_profile':profile,
                    'chamber_control_verified_by_operator':self.check_plc.isChecked(),
                    'chamber_plc_ip':str(tcComm.ip) if self.chamber_mode.currentData()=='plc' else None,
                    'return_to_25c_on_success':bool(self.return_ambient.isChecked()),
                    'production_release':False},f,ensure_ascii=False,indent=2)
            self._raw_file=(folder/'imu_frame_means.csv').open('w',newline='',encoding='utf-8-sig')
            self._raw_writer=csv.writer(self._raw_file)
            self._raw_jsonl=(folder/'imu_full_frames.jsonl').open('w',encoding='utf-8')
            self._raw_writer.writerow(['utc','target_temp_c','step','frame_update_count','imu_temp_c',
                'chamber_pv_c','inner_deg','outer_deg','inner_rate_dps','outer_rate_dps',
                'acc_x_g','acc_y_g','acc_z_g','gyro_x_dps','gyro_y_dps','gyro_z_dps','feedback_age_ms'])
            tilt_sensor_calibration_queue_set(True,clear=True)
            self._lock_ui(True)
            self.start_button.setEnabled(False);self.stop_button.setEnabled(True)
            self._log('任务已启动：'+str(folder))
            self._tick()
        except Exception as exc:
            if self.task is not None:self._abort('启动失败：'+str(exc))
            else:QMessageBox.warning(self.page,'未能启动温补',str(exc))

    def _confirm_temperature(self):
        t=self.task
        if not t or t['phase']!='wait_manual':return
        target=t['temps'][t['temp_i']]
        actual=float(self.manual_pv.value())
        if abs(actual-target)>2.0:
            QMessageBox.warning(self.page,'温度未达到','手动输入的温箱 PV 与目标相差超过 2℃')
            return
        t['manual_confirmed_pv']=actual
        t['phase']='thermal_stability'
        t['phase_start']=time.monotonic()
        t['chip_trace']=[]
        self.confirm_temp.setEnabled(False)
        self._log(f'人工到温确认：目标 {target}℃；实测 {actual}℃。开始 IMU 内温稳定检查')

    def _frame_sample(self,frame):
        t=self.task
        if t is None:return
        stamp=int(frame.get('monotonic_time_ns',0) or 0)
        fb=int(turntableData.last_update_monotonic_ns or 0)
        if stamp<=0 or fb<=0 or abs(stamp-fb)>250_000_000:return
        if stamp*1e-9 < t['sample_start']:return
        if frame.get('data_odr')!=t['baseline_config'][2] or (frame.get('acc_fs'),frame.get('gyro_fs'))!=t['baseline_config'][:2]:
            raise ValueError('实验中途 IMU 量程或 ODR 发生变化')
        acc,nacc,naccok=frame_average_sanitized(frame['acc_g_arr'],3.,True)
        gyro,ngyr,ngyrok=frame_average_sanitized(frame['gyr_dps_arr'],6.,True)
        if acc is None or gyro is None:return
        pv=t['manual_confirmed_pv'] if t['manual'] else tcData.pv
        sample={'acc':acc.tolist(),'gyro':gyro.tolist(),
                'acc_raw_samples':nacc,'acc_accepted_samples':naccok,
                'gyro_raw_samples':ngyr,'gyro_accepted_samples':ngyrok,
                'inner_deg':float(turntableData.inner_axis_position),
                'outer_deg':float(turntableData.outer_axis_position),
                'inner_rate_dps':float(turntableData.inner_axis_speed),
                'outer_rate_dps':float(turntableData.outer_axis_speed),
                'temp_c':float(frame.get('temp_c')),
                'feedback_age_ms':abs(stamp-fb)/1.e6}
        t['frames'].append(sample)
        self._raw_jsonl.write(json.dumps({'frame':frame,'step_id':t['steps'][t['step_i']]['step_id'],
            'target_temp_c':t['temps'][t['temp_i']]},ensure_ascii=False)+'\n')
        self._raw_writer.writerow([datetime.datetime.now(datetime.timezone.utc).isoformat(),
            t['temps'][t['temp_i']],t['steps'][t['step_i']]['step_id'],frame.get('frame_update_count'),
            sample['temp_c'],pv,sample['inner_deg'],sample['outer_deg'],
            sample['inner_rate_dps'],sample['outer_rate_dps'],*sample['acc'],*sample['gyro'],sample['feedback_age_ms']])
        t['frame_count']+=1

    def _collect(self):
        # Drain a limited number every tick; the recording queue is bounded and drop-checking is mandatory.
        t=self.task
        for _ in range(200):
            try:f=tilt_sensor_calibration_frame_get_nowait()
            except queue.Empty:break
            if t['phase']=='sample':self._frame_sample(f)

    def _save_partial(self, status, reason):
        t=self.task
        if not t:return
        folder=Path(t['run_dir'])
        with (folder/'temperature_measurements.json').open('w',encoding='utf-8') as f:
            json.dump({'status':status,'reason':reason,'device_sn':t['device_sn'],
                'rows':t['rows'],'events':t['events'],'imu_frame_count':t['frame_count'],
                'imu_queue_drops':tilt_sensor_calibration_queue_drop_count_get()},f,ensure_ascii=False,indent=2)
        with (folder/'temperature_measurements.csv').open('w',newline='',encoding='utf-8-sig') as f:
            w=csv.writer(f)
            w.writerow(['target_temperature_c','temperature_split','step_id','sensor','mode','split',
                        'temperature_mean_c','reference_x','reference_y','reference_z','measured_x','measured_y','measured_z','accepted_frames'])
            for row in t['rows']:
                measure=row.get('acc_raw_mean_g') if row['sensor']=='acc' else row.get('gyro_raw_mean_dps')
                w.writerow([row['temperature_target_c'],row['temperature_split'],row['step_id'],row['sensor'],
                            row['mode'],row['split'],row['temperature_mean_c'],*row['reference'],*measure,row['accepted_frames']])
        if getattr(self,'_raw_file',None):self._raw_file.flush()
        if getattr(self,'_raw_jsonl',None):self._raw_jsonl.flush()

    def _finish(self, success, reason):
        t=self.task
        if t is None:return
        stopped=self._stop_axes()
        if not success and not t['manual']:
            # Stop PLC fixed-temperature control on abort; a failed command is
            # never treated as proof that the heater/cooler is safely off.
            try:
                with tcComm.thread_lock:
                    chamber_stopped=bool(tc_fixed_value_stop()) if tcComm.is_connected else False
                self._log('异常中止：已尝试停止PLC温箱定值运行，返回='+str(chamber_stopped)+
                          '。必须在原温箱面板现场确认状态。')
            except Exception as stop_exc:
                self._log('PLC温箱停止指令异常：'+str(stop_exc)+'；请现场确认/采取安全措施')
        try:
            self._log('结束：'+reason+'；两轴停车指令'+('已发送' if stopped else '失败（请使用硬件急停）'))
            self._save_partial('COMPLETED' if success and stopped else 'INCOMPLETE',reason)
            if success and stopped:
                # Candidate fitting cannot overwrite or replace ambient data.
                result=save_models(t['run_dir'],t['rows'],('acc','gyro') if t['dynamic'] else ('acc',),1)
                try:
                    z=build_gyro_zero_bias_model(t['rows'])
                    with (Path(t['run_dir'])/'thermal_gyro_bias_only_candidate.json').open('w',encoding='utf-8') as f:
                        json.dump(z,f,ensure_ascii=False,indent=2)
                except ValueError as exc:self._log('GYRO静态偏置拟合不通过：'+str(exc))
                export_thermal_xlsx(t['run_dir'],t['rows'],result)
                self._log('温补候选模型：'+str(result['sensors']))
        finally:
            tilt_sensor_calibration_queue_set(False)
            self._lock_ui(False)
            self.start_button.setEnabled(True);self.stop_button.setEnabled(False)
            self.confirm_temp.setEnabled(False)
            self.task=None
            for obj in (getattr(self,'_raw_file',None),getattr(self,'_raw_jsonl',None)):
                try:
                    if obj:obj.close()
                except Exception:pass
            self.label.setText('完成' if success and stopped else '中止/未完成：'+reason)
            if not stopped:
                QMessageBox.critical(self.page,'停车未确认','软件停车命令失败，请立即使用现场硬件急停并排查')

    def _abort(self,reason):
        if self.task is None:return
        # Never claim successful stop if this command fails; controlled termination only.
        self._finish(False,reason)

    def _tick(self):
        t=self.task
        if t is None:return
        now=time.monotonic()
        try:
            self._motion_status()
            if tilt_sensor_calibration_queue_drop_count_get()>0:
                raise ValueError('IMU记录队列丢帧；拒绝继续温补实验')
            with tiltSensorRawData.data_lock:
                imu_count=int(tiltSensorRawData.data_update_count)
                config_now=(tiltSensorRawData.acc_fs,tiltSensorRawData.gyro_fs,tiltSensorRawData.data_odr)
            if config_now!=t['baseline_config']:
                raise ValueError('IMU 量程或 ODR 变化')
            if imu_count!=t['last_imu_count']:
                t['last_imu_count']=imu_count
                t['last_imu_change']=now
            elif now-t['last_imu_change']>5.0:
                raise ValueError('IMU 数据更新已停止超过 5 秒，拒绝把旧温度当作热平衡')
            self._collect()
            if not t['manual']:
                chamber=self._require_plc(now)
                target=t['temps'][t['temp_i']] if t['temp_i']<len(t['temps']) else None
                if target is not None and t['phase'] not in ('next_temperature','verify_plc_sp'):
                    require_setpoint_ack(chamber,target)
            if t['phase']=='next_temperature':
                if t['temp_i']>=len(t['temps']):
                    if not t['manual'] and t['return_ambient']:
                        self._issue_plc_setpoint(25.0)
                        t['phase']='verify_return'
                        t['phase_start']=now
                        t['pv_stable_since']=None
                        self._log('全部工况已完成：PLC自动回温25℃，等待SP回读和PV稳定后结束')
                        return
                    self._finish(True,'全部温度点与独立验证采集完成（人工模式或未启用自动回25℃）')
                    return
                if not self._stopped():raise ValueError('换温前两轴未静止')
                target=t['temps'][t['temp_i']]
                if not t['manual']:
                    self._issue_plc_setpoint(target)
                    t['phase']='verify_plc_sp'
                    self._log(f'已通过原PLC驱动请求设温 {target}℃；等待SP回读及运行状态确认')
                else:
                    t['phase']='wait_manual'
                    self._log(f'请在原温箱控制面板手工设为 {target}℃，读取实测 PV 并输入，达到目标后点击确认。不会自动发送未知 RS232 指令。')
                t['phase_start']=now
                self.confirm_temp.setEnabled(t['manual'])
            elif t['phase']=='verify_return':
                try:
                    require_setpoint_ack(chamber,25.0)
                except ChamberSafetyError:
                    if now-t['phase_start']>90:
                        raise ValueError('自动回25℃时SP回读/运行状态90秒未确认')
                    return
                t['phase']='wait_return'
                t['phase_start']=now
                t['pv_stable_since']=None
            elif t['phase']=='wait_return':
                require_setpoint_ack(chamber,25.0)
                if abs(chamber['pv']-25.0)<=1.0:
                    if t['pv_stable_since'] is None:t['pv_stable_since']=now
                    if now-t['pv_stable_since']>=30.0:
                        self._finish(True,'全部温补工况完成，并已自动回到25℃±1℃持续30秒')
                        return
                else:t['pv_stable_since']=None
                if now-t['phase_start']>21600:
                    raise ValueError('结束回25℃超时6小时')
            elif t['phase']=='verify_plc_sp':
                chamber=self._require_plc(now)
                try:
                    require_setpoint_ack(chamber,t['temps'][t['temp_i']])
                except ChamberSafetyError:
                    if now-t['phase_start']>90:
                        raise ValueError('温箱SP回读/运行状态在90秒内未确认，停止自动温补')
                    self.label.setText(f'等待温箱SP回读：目标{t["temps"][t["temp_i"]]}℃，回读{chamber["sp"]:.2f}℃')
                    return
                t['phase']='wait_plc';t['phase_start']=now;t['pv_stable_since']=None
                self._log(f'温箱SP回读匹配、运行模式确认；实测PV={chamber["pv"]:.2f}℃')
            elif t['phase']=='wait_manual':
                self.label.setText(f'温度 {t["temp_i"]+1}/{len(t["temps"])}：等待人工确认 {t["temps"][t["temp_i"]]}℃')
                return
            elif t['phase']=='wait_plc':
                if tcState.is_device_fault or not tcData.is_tc_data_available or not tcComm.is_connected:
                    raise ValueError('PLC温箱故障或通信丢失')
                pv=float(chamber['pv'])
                if abs(pv-t['temps'][t['temp_i']])<=1.0:
                    if t.get('pv_stable_since') is None:t['pv_stable_since']=now
                    if now-t['pv_stable_since']>=30.0:
                        t['phase']='thermal_stability';t['phase_start']=now;t['chip_trace']=[]
                        self._log('PLC 实时PV连续30秒在目标±1℃内，开始芯片热平衡检查')
                else:t['pv_stable_since']=None
                if now-t['phase_start']>21600:raise ValueError('温箱到温超时 6 小时')
            elif t['phase']=='thermal_stability':
                if not self._stopped():raise ValueError('温度稳定等待时转台发生运动')
                pv=t['manual_confirmed_pv'] if t['manual'] else float(chamber['pv'])
                if abs(pv-t['temps'][t['temp_i']])>2:
                    raise ValueError('温箱实际温度已偏离目标 ±2℃')
                with tiltSensorRawData.data_lock:
                    chip=float(tiltSensorRawData.temp_c)
                if not math.isfinite(chip) or not -45<=chip<=90:
                    raise ValueError('IMU 内温读数异常')
                if now-t['phase_start']>21600:
                    raise ValueError('芯片温度无法在 6 小时内达到热平衡')
                t['chip_trace'].append((now,chip))
                t['chip_trace']=[v for v in t['chip_trace'] if now-v[0]<=120]
                enough=now-t['phase_start']>=self.dwell.value()
                recent=[v[1] for v in t['chip_trace'] if now-v[0]<=60]
                stable=(len(recent)>=20 and max(recent)-min(recent)<=0.2)
                self.label.setText(f'温度 {t["temps"][t["temp_i"]]}℃：芯片 {chip:.2f}℃，保温 {now-t["phase_start"]:.0f}/{self.dwell.value()}s，最近60s波动 {max(recent)-min(recent) if recent else 0:.3f}℃')
                if enough and stable and abs(chip-pv)<=10:
                    t['step_i']=0;t['phase']='position';t['phase_start']=now
                    self._log('热平衡检查通过，开始本温度的转台工况')
            elif t['phase']=='position':
                if t['step_i']>=len(t['steps']):
                    t['temp_i']+=1;t['phase']='next_temperature';t['phase_start']=now
                    self._save_partial('RUNNING','完成一个温度点')
                    return
                step=t['steps'][t['step_i']]
                self._move(step['inner_deg'],step['outer_deg'])
                t['phase']='wait_position';t['phase_start']=now;t['stable_since']=None
                self._log(f'姿态运动 {step["step_id"]} -> 内 {step["inner_deg"]} / 外 {step["outer_deg"]}°')
            elif t['phase']=='wait_position':
                step=t['steps'][t['step_i']]
                in_place=(self._stopped() and turntableState.is_inner_axis_in_place and turntableState.is_outer_axis_in_place
                     and abs(_angle_error(turntableData.inner_axis_position,step['inner_deg']))<=0.2
                     and abs(_angle_error(turntableData.outer_axis_position,step['outer_deg']))<=0.2)
                if in_place:
                    if t['stable_since'] is None:t['stable_since']=now
                    if now-t['stable_since']>=1.0:
                        t['phase']='settle';t['phase_start']=now
                else:t['stable_since']=None
                if now-t['phase_start']>240:raise ValueError('转台姿态到位超时')
            elif t['phase']=='settle':
                if not self._stopped():raise ValueError('静置阶段转台仍在运动')
                if now-t['phase_start']>=self.settle.value():
                    step=t['steps'][t['step_i']]
                    if step['mode']=='rate':
                        self._rate_command(step['rotation_axis'],step['target_rate_dps'])
                        t['phase']='wait_rate';t['phase_start']=now;t['stable_since']=None
                    else:self._begin_sample(now)
            elif t['phase']=='wait_rate':
                step=t['steps'][t['step_i']]
                speed=turntableData.inner_axis_speed if step['rotation_axis']=='inner' else turntableData.outer_axis_speed
                ref=step['target_rate_dps']
                if abs(speed-ref)<=max(.2,abs(ref)*.15):
                    if t['stable_since'] is None:t['stable_since']=now
                    if now-t['stable_since']>=1:self._begin_sample(now)
                else:t['stable_since']=None
                if now-t['phase_start']>30:raise ValueError('动态 GYRO 实际速率未稳定到目标')
            elif t['phase']=='sample':
                step=t['steps'][t['step_i']]
                dur=float(step.get('sample_seconds',self.sample_seconds.value()))
                if now-t['sample_start']>=dur:
                    try:
                        stats=robust_segment(t['frames'],step['mode'],t['profile'],
                            target_rate=step.get('target_rate_dps'),axis=step.get('rotation_axis'),
                            static_sensor=step['sensor'])
                    except ValueError as exc:
                        if t['retry_count']>=2:
                            raise ValueError(f'{step["step_id"]} 质量检查连续三次失败：{exc}')
                        t['retry_count']+=1
                        self._log(f'{step["step_id"]} 采样质量拒绝 {t["retry_count"]}/2：{exc}，准备重新采样')
                        if step['mode']=='rate':
                            if not self._stop_axes():raise ValueError('重试前停车命令失败')
                            t['phase']='wait_stop_retry';t['phase_start']=now
                        else:
                            t['phase']='wait_position';t['phase_start']=now;t['stable_since']=None
                        t['frames']=[]
                        return
                    t['retry_count']=0
                    if step['mode']=='rate':
                        ref=_platform_angular_rate(stats['inner_actual_mean_deg'],stats['outer_actual_mean_deg'],
                            stats['inner_rate_mean_dps'],stats['outer_rate_mean_dps'],t['axis_model'])
                    elif step['sensor']=='acc':
                        ref=_platform_gravity_vector(stats['inner_actual_mean_deg'],stats['outer_actual_mean_deg'],t['axis_model'])
                    else:ref=np.zeros(3)
                    row={**stats,'reference':ref.tolist(),'step_id':step['step_id'],
                        'split':step['split'],'mode':step['mode'],'sensor':step['sensor'],
                        'temperature_split':t['temperature_split_by_setpoint'][t['temps'][t['temp_i']]],
                        'temperature_target_c':t['temps'][t['temp_i']]}
                    t['rows'].append(row)
                    self._log(f'采样完成 {step["step_id"]}；有效帧 {stats["accepted_frames"]}/{stats["frame_count"]}')
                    if step['mode']=='rate':
                        if not self._stop_axes():raise ValueError('动态段停车命令失败')
                        t['phase']='wait_stop';t['phase_start']=now
                    else:
                        t['step_i']+=1;t['phase']='position';t['phase_start']=now
            elif t['phase'] in ('wait_stop','wait_stop_retry'):
                if self._stopped():
                    if t['phase']=='wait_stop':t['step_i']+=1
                    t['phase']='position';t['phase_start']=now
                if now-t['phase_start']>30:raise ValueError('无法确认双轴停车')
            if not t['manual'] and t['phase'] not in ('next_temperature','verify_plc_sp'):
                self.plc_telemetry.setText(f'PLC实时：PV={chamber["pv"]:.2f}℃ / SP={chamber["sp"]:.2f}℃；运行={chamber["running"]}；报警={chamber["alarm"]}')
            if t['phase'] in ('verify_return','wait_return'):
                self.progress.setValue(99)
                self.label.setText(f'采集完成，正在自动回25℃：PV={chamber["pv"]:.2f}℃，SP={chamber["sp"]:.2f}℃')
                return
            steps_total=len(t['temps'])*len(t['steps'])
            done=t['temp_i']*len(t['steps'])+t['step_i']
            self.progress.setValue(int(100*done/max(steps_total,1)))
            if t['phase'] not in ('thermal_stability','wait_manual'):
                self.label.setText(f'温度 {t["temp_i"]+1}/{len(t["temps"])}：{t["temps"][t["temp_i"]]}℃，'
                                  f'工况 {t["step_i"]+1}/{len(t["steps"])}，阶段 {t["phase"]}')
        except Exception as exc:
            self._abort(f'自动温补中止：{exc}')

    def _begin_sample(self,now):
        t=self.task
        t['phase']='sample';t['sample_start']=now;t['frames']=[]
        self._log('开始采集 '+t['steps'][t['step_i']]['step_id'])

    def shutdown(self):
        self.timer.stop()
        if self.task is not None:self._abort('程序退出，终止温补任务')
