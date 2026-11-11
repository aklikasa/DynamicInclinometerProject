# -*- coding: utf-8 -*-
"""2FDT600WK temperature-compensation experiment page.

Real 2FDT motor DLL + real live MCU IMU frames; no simulated success path.
The field-proven original Snap7 PLC chamber is the default automatic path.
Manual control is an explicit fallback; unknown RS232 commands are never sent.
"""
import copy
import ctypes
import csv
import datetime
import json
import math
import os
from pathlib import Path
import queue
import sys
import webbrowser
import time
import numpy as np
from PySide6.QtCore import QTimer, QProcess, QProcessEnvironment
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox,
    QLabel, QPushButton, QCheckBox, QComboBox, QLineEdit, QDoubleSpinBox,
    QSpinBox, QPlainTextEdit, QProgressBar, QFileDialog, QMessageBox, QScrollArea)

from turntable_data_get import (turntableComm, turntableData, turntableState,
    turntable_feedback_queue_set, turntable_feedback_get_nowait,
    turntable_feedback_queue_drop_count_get)
from turntable_2FDT600WK_comm import (INNER_ROTATION_AXIS, OUTER_ROTATION_AXIS,
    twoFDT600WK_SetAxisVelocity, twoFDT600WK_SetAxisStop)
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
from production_cycle_protocol import (PROTOCOL as R4_PROTOCOL, generate_temperature_plan,
    FIT_RATES_DPS as R4_FIT_RATES, VALID_RATES_DPS as R4_VERIFY_RATES,
    check_user_hardware_clearance)
from production_ramp import FIELDS as R5_RAMP_FIELDS
from production_r5_cycle import decide_transition, write_cycle_manifest
from thermal_variable_temperature import (parse_temperatures, temperature_splits,
    separate_temperature_plan, steps_for_temperature,
    save_variable_models, save_optional_gyro_bias)
from thermal_excel_report import export_thermal_xlsx
from thermal_model_completion import fully_accepted_sensors
from thermal_analysis_publisher import publish_sensor_reports
from thermal_model_selection import run_thermal_model_selection
from thermal_run_resume import (RESUME_SCHEMA, atomic_write_json, validate_resume,
                                validate_appendable_raw_files)
from thermal_chip_stability import chip_stability_status
from thermal_chamber_stability import (chamber_stability_status, chamber_band_status)
from thermal_gyro_multirate import (
    FIT_RATES_DPS, VERIFY_RATES_DPS, PILOT_FIT_RATES_DPS, PILOT_VERIFY_RATES_DPS,
    LOW_SPEED_FIT_RATES_DPS, LOW_SPEED_VERIFY_RATES_DPS, configure_thermal_gyro_profile,
    wk_signed_velocity, conservative_sweep_degrees,
    parse_rate_list, validate_rate_lists)
import turntable_2FDT600WK_comm as wk_comm
from thermal_runtime_guard import ThermalRuntimeGuard
from thermal_temperature_policy import policy_for
from thermal_reference_diagnostics import inspect_feedback
from thermal_incomplete_report import export_incomplete_xlsx
from thermal_result_readiness import (build_result_readiness, write_result_readiness,
                                      missing_planned_conditions)

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
        self._wk_rate_guard = None
        self._raw_file = None
        self._raw_jsonl = None
        self._feedback_jsonl = None
        self._r5_cycle = None  # one-click dual pass with two independent checkpoint folders
        self._r5_ramp = None   # purely passive stationary slope capture
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
        box = QGroupBox('实验配置（拟合/独立验证温度分别输入，自动合并升序执行）')
        g = QGridLayout(box)
        g.addWidget(QLabel('PCB 唯一编号'),0,0)
        self.sn = QLineEdit()
        self.sn.setPlaceholderText('连接后自动填入；不支持UID时手动输入')
        self.sn.setToolTip('与IMU标定页自动同步PCB编号；温补记录也保存此编号')
        g.addWidget(self.sn,0,1)
        g.addWidget(QLabel('拟合温度工况 ℃'),1,0)
        self.fit_temperatures = QLineEdit('20, 25, 30, 35, 40')
        self.fit_temperatures.setObjectName('thermal_fit_temperatures')
        self.fit_temperatures.setToolTip('只在这些温度执行ACC/GYRO标定和独立工况测试；逗号分隔、升序、不重复。一次/二次/三次模型至少需要3/4/5个拟合温度点。')
        g.addWidget(self.fit_temperatures,1,1,1,3)
        g.addWidget(QLabel('独立验证温度 ℃'),2,0)
        self.validation_temperatures = QLineEdit('22.5, 27.5, 32.5, 37.5')
        self.validation_temperatures.setObjectName('thermal_validation_temperatures')
        self.validation_temperatures.setToolTip('只执行ACC/GYRO独立测试工况；不参与PV校正、温补拟合或模型选型。须位于拟合温度范围内，不能与拟合温度重复。')
        g.addWidget(self.validation_temperatures,2,1,1,3)
        self.temperature_plan_note = QLabel('拟合温度：完整标定+独立工况测试；独立验证温度：仅采独立测试工况。合并后从低温向高温运行，每点保温门槛相同。28套模型=A0+T0/T1/T2×B/C/D×1/2/3次；至少5个拟合温度点才能可靠比较三次模型。')
        self.temperature_plan_note.setWordWrap(True)
        self.temperature_plan_note.setStyleSheet('color:#795c26')
        g.addWidget(self.temperature_plan_note,13,0,1,4)
        # Production scans are two physically distinct runs. Repeat setpoints
        # MUST NOT share the existing (temperature, step_id) commit key.
        production = QGroupBox('R5 −40～85℃生产研究：自动双向/单向；统一分段温补与独立验证')
        pg = QGridLayout(production)
        pg.addWidget(QLabel('扫描任务'),0,0)
        self.production_mode = QComboBox()
        self.production_mode.addItem('原研发温补（用户自定义温度）','legacy')
        self.production_mode.addItem('R5 一次启动自动升温＋降温（推荐：-40→85→-40）','combined')
        self.production_mode.addItem('生产研发验证：升温 −40→+85℃','warming')
        self.production_mode.addItem('生产研发验证：降温 +85→−40℃','cooling')
        self.production_mode.setObjectName('r5_scan_direction')
        self.production_mode.setCurrentIndex(self.production_mode.findData('combined'))
        self.production_mode.currentIndexChanged.connect(self._on_production_mode_changed)
        pg.addWidget(self.production_mode,0,1,1,3)
        pg.addWidget(QLabel('批次ID（升/降温必须完全相同）'),1,0)
        self.production_batch_id = QLineEdit('')
        self.production_batch_id.setPlaceholderText('例如 DTS724148_P20261109_A')
        self.production_batch_id.setObjectName('r4_production_batch_id')
        pg.addWidget(self.production_batch_id,1,1,1,3)
        pg.addWidget(QLabel('最终曲线策略'),2,0)
        self.production_curve_policy=QComboBox()
        self.production_curve_policy.addItem('统一一条曲线（默认；双向独立验收，失败不强行平均）','single')
        self.production_curve_policy.addItem('方向差研究模式（不允许直接烧录）','research_directional')
        self.production_curve_policy.setObjectName('r5_curve_policy')
        pg.addWidget(self.production_curve_policy,2,1,1,3)
        self.production_load_preset = QPushButton('加载−40～85℃/5℃采样方案与保守GYRO速率')
        self.production_load_preset.clicked.connect(self._apply_production_preset)
        pg.addWidget(self.production_load_preset,3,0,1,4)
        self.production_clearance = QCheckBox('已现场核实：温箱、PCB、线缆、夹具、滑环/运动路径、急停与全天值守适用于−40～85℃双向试验')
        self.production_clearance.setChecked(False)
        self.production_clearance.setObjectName('r4_hardware_approval')
        self.production_clearance.setToolTip('操作前核实外部PLC/温控器硬件保护与厂家适温；该确认不代表程序取得计量认证。')
        pg.addWidget(self.production_clearance,4,0,1,4)
        self.production_analyze = QPushButton('合并本批升温+降温结果 → 生成HTML质量/热滞后/六轴报告')
        self.production_analyze.clicked.connect(self._run_production_analysis)
        pg.addWidget(self.production_analyze,5,0,1,4)
        self.production_info = QLabel('生产验证方案：26个5℃设定点，14个拟合温度＋12个独立温度；'
                                     '每个方向单独执行并存档，防止相同温度点覆盖。两趟均COMPLETED后才合并。'
                                     '研究性系数不直接烧录，不宣称计量或六轴物理对齐认证。')
        self.production_info.setWordWrap(True)
        pg.addWidget(self.production_info,6,0,1,4)
        layout.addWidget(production)
        ramp = QGroupBox('R5 温度斜坡验证记录（独立于逐点稳态温补；不控制温箱斜坡）')
        rl=QVBoxLayout(ramp)
        self.ramp_approval=QCheckBox('已使用温箱厂家认可的斜坡程序；WK两轴已停车、IMU固定不动；全过程有人值守')
        self.ramp_approval.setChecked(False)
        rl.addWidget(self.ramp_approval)
        rr=QHBoxLayout()
        self.ramp_start_button=QPushButton('开始记录真实温度斜坡（~1Hz连续采样）')
        self.ramp_start_button.clicked.connect(self._start_r5_ramp)
        self.ramp_stop_button=QPushButton('结束斜坡记录（不发送PLC控制命令）')
        self.ramp_stop_button.setEnabled(False)
        self.ramp_stop_button.clicked.connect(self._stop_r5_ramp)
        rr.addWidget(self.ramp_start_button);rr.addWidget(self.ramp_stop_button)
        rl.addLayout(rr)
        self.ramp_info=QLabel('先完成全温双向稳态标定；斜坡记录使用同批次ID。温箱斜坡设定需要在已验证的厂家温控程序完成。')
        self.ramp_info.setWordWrap(True)
        rl.addWidget(self.ramp_info)
        layout.addWidget(ramp)
        g.addWidget(QLabel('预期 GYRO 量程（仅核对，不写入设备）'),14,0)
        self.expected_gyro_fs = QComboBox()
        for value in (125,250,500,1000,2000,4000):
            self.expected_gyro_fs.addItem(f'±{value}°/s',value)
        self.expected_gyro_fs.setCurrentIndex(self.expected_gyro_fs.findData(250))
        g.addWidget(self.expected_gyro_fs,14,1)
        self.gyro_fs_note = QLabel('你已将陀螺仪设置为±250 dps，启动时核对实时数据换算量程；更改此处不会修改MCU。')
        self.gyro_fs_note.setWordWrap(True)
        g.addWidget(self.gyro_fs_note,14,2,1,2)
        g.addWidget(QLabel('温箱方式'),3,0)
        self.chamber_mode = QComboBox()
        self.chamber_mode.addItem('自动控温：使用原上位机已验证的 Snap7/PLC 温箱（推荐）', 'plc')
        self.chamber_mode.addItem('人工设温：仅限PLC不可用时（逐点确认）', 'manual')
        g.addWidget(self.chamber_mode,3,1,1,3)
        self.chamber_mode.currentIndexChanged.connect(self._on_chamber_mode_changed)
        g.addWidget(QLabel('原温箱实测 PV ℃'),4,0)
        self.manual_pv = QDoubleSpinBox()
        self.manual_pv.setRange(-45,110)
        self.manual_pv.setDecimals(2)
        self.manual_pv.setValue(25)
        g.addWidget(self.manual_pv,4,1)
        self.confirm_temp = QPushButton('确认本温度点已到温')
        self.confirm_temp.setEnabled(False)
        self.confirm_temp.clicked.connect(self._confirm_temperature)
        g.addWidget(self.confirm_temp,4,2,1,2)
        self.plc_telemetry = QLabel('PLC 反馈：等待连接；自动模式禁止使用离线/缓存温度')
        self.plc_telemetry.setWordWrap(True)
        g.addWidget(self.plc_telemetry,9,0,1,4)
        g.addWidget(QLabel('共同热平衡时间 (秒)'),5,0)
        self.dwell = QSpinBox(); self.dwell.setRange(300,7200); self.dwell.setValue(1800)
        g.addWidget(self.dwell,5,1)
        self.chip_stability_only = QCheckBox('快速模式：跳过正式热浸与温箱两级稳定判据（仅流程测试用）')
        self.chip_stability_only.setToolTip('快速模式仅用于自动流程/转台联调：PLC PV在目标±1℃连续30秒后，再检查芯片最近60秒真实新帧波动≤0.2℃；跳过正式30分钟共同热平衡和最终PV±0.1℃/5分钟检查。正式温补请取消勾选。')
        self.chip_stability_only.setChecked(False)
        self.chip_stability_only.toggled.connect(self._on_thermal_mode_changed)
        g.addWidget(self.chip_stability_only,15,0,1,4)
        g.addWidget(QLabel('每工况采样 (秒)'),5,2)
        self.sample_seconds = QSpinBox(); self.sample_seconds.setRange(5,120); self.sample_seconds.setValue(5)
        g.addWidget(self.sample_seconds,5,3)
        g.addWidget(QLabel('静置等待 (秒)'),6,0)
        self.settle = QSpinBox(); self.settle.setRange(3,60); self.settle.setValue(3)
        g.addWidget(self.settle,6,1)
        g.addWidget(QLabel('姿态运动速度 °/s'),6,2)
        self.move_speed = QDoubleSpinBox(); self.move_speed.setRange(0.2,5); self.move_speed.setValue(2)
        g.addWidget(self.move_speed,6,3)
        self.dynamic = QCheckBox('GYRO 多速率标定（默认低中速≤30°/s；60°/s为单独可选高速模式）')
        self.dynamic.setChecked(True)
        g.addWidget(self.dynamic,7,0,1,4)
        self.gyro_rate_mode = QComboBox()
        self.gyro_rate_mode.addItem('低速优先：拟合 1/2/3/5/10/20/30；验证 1.5/2.5/4/7.5/15/25', 'low_speed')
        self.gyro_rate_mode.addItem('传统低中速：拟合 1/5/15/30，验证 1.5/3.5/10/20/25', 'pilot')
        self.gyro_rate_mode.addItem('高速研发：≤60°/s；拟合 1/5/15/30/60，验证 1.5/3.5/10/20/45', 'full')
        self.gyro_rate_mode.addItem('自定义：拟合与独立验证速率分别输入（单位°/s，自动正反转）', 'custom')
        self.gyro_rate_mode.setToolTip('新实验默认选择自定义，速率直接可改；也可选低速优先、传统或高速预设。每个幅值自动执行±方向、三轴。启动后锁定并写入断点配置。')
        self.gyro_rate_mode.setCurrentIndex(self.gyro_rate_mode.findData('custom'))
        g.addWidget(self.gyro_rate_mode, 16, 0, 1, 4)
        g.addWidget(QLabel('GYRO拟合速率 °/s'),17,0)
        self.gyro_fit_rates = QLineEdit('1, 2, 3, 5, 10, 20, 30')
        self.gyro_fit_rates.setObjectName('thermal_gyro_fit_rates')
        self.gyro_fit_rates.setToolTip('当前为可编辑自定义方案。正数幅值逗号分隔、无重复；自动三轴±正反向。建议多覆盖1～5°/s低速段，同时保留10/20/30°/s；可设0.1～60°/s。小于1°/s应额外核验转台测速精度和采样时长。')
        g.addWidget(self.gyro_fit_rates,17,1,1,3)
        g.addWidget(QLabel('GYRO独立验证速率 °/s'),18,0)
        self.gyro_verify_rates = QLineEdit('1.5, 2.5, 4, 7.5, 15, 25')
        self.gyro_verify_rates.setObjectName('thermal_gyro_verify_rates')
        self.gyro_verify_rates.setToolTip('可编辑的独立验证幅值，必须与拟合速率严格不重合，优先位于拟合速度范围内；自动做三轴±正反向。')
        g.addWidget(self.gyro_verify_rates,18,1,1,3)
        self.gyro_rate_mode.currentIndexChanged.connect(self._on_gyro_rate_mode_changed)
        self._on_gyro_rate_mode_changed()
        g.addWidget(QLabel('GYRO 转动加速度 °/s²'),11,0)
        self.gyro_accel = QSpinBox(); self.gyro_accel.setRange(1,50); self.gyro_accel.setValue(30)
        self.gyro_accel.setToolTip('仅用于温补动态GYRO；外轴额定最大50°/s²。')
        g.addWidget(self.gyro_accel,11,1)
        # 温补GYRO不设固定累计转角上限；只保留真实反馈、方向、超时与停车保护。
        self.gyro_safety_note = QLabel('普通数据质检失败只进入有限补测队列；不会放宽任何ACC/GYRO或WK速度质量阈值。'
                                      '高速模式含60°/s连续旋转风险，必须实机验证滑环、线缆、装夹和急停。')
        self.gyro_safety_note.setWordWrap(True)
        self.gyro_safety_note.setStyleSheet('color:#8a5421')
        g.addWidget(self.gyro_safety_note,12,0,1,4)
        self.return_ambient = QCheckBox('采集完成后回到25℃（可选）；随后自动请求PLC停止定值运行并核对停止反馈')
        self.return_ambient.setChecked(True)
        g.addWidget(self.return_ambient,10,0,1,4)
        g.addWidget(QLabel('保存目录'),8,0)
        self.output = QLineEdit(str(Path.home()/'IMU_Thermal_Experiments'))
        g.addWidget(self.output,8,1,1,2)
        browse = QPushButton('选择…'); browse.clicked.connect(self._browse)
        g.addWidget(browse,8,3)
        layout.addWidget(box)

        stability_box = QGroupBox('温补温度策略：生产自适应 / 研发连续 / 严格恒温')
        sg = QGridLayout(stability_box)
        self.thermal_quality_mode = QComboBox()
        self.thermal_quality_mode.addItem('研发连续温补V3（PV最终±1.0℃、芯片60秒≤0.25℃；逐工况温度可追溯）','continuous')
        self.thermal_quality_mode.addItem('生产自适应（推荐：12姿态完整联合拟合，跨姿态温差仅记录）','production_adaptive')
        self.thermal_quality_mode.addItem('严格恒温R6（保留严格PV/芯片门槛；跨姿态温差也只记录）','strict')
        self.thermal_quality_mode.setObjectName('thermal_quality_mode')
        sg.addWidget(QLabel('温度质检模式'),4,0)
        sg.addWidget(self.thermal_quality_mode,4,1,1,3)
        sg.addWidget(QLabel('初步到温观察时间 (秒)'),0,0)
        self.pv_initial_seconds = QSpinBox(); self.pv_initial_seconds.setRange(60,1800); self.pv_initial_seconds.setValue(300)
        sg.addWidget(self.pv_initial_seconds,0,1)
        sg.addWidget(QLabel('初步PV极差上限 (°C)'),0,2)
        self.pv_initial_range = QDoubleSpinBox(); self.pv_initial_range.setRange(0.05,2.0); self.pv_initial_range.setDecimals(2); self.pv_initial_range.setSingleStep(0.05); self.pv_initial_range.setValue(0.30)
        sg.addWidget(self.pv_initial_range,0,3)
        sg.addWidget(QLabel('初步PV斜率上限 (°C/min)'),1,0)
        self.pv_initial_slope = QDoubleSpinBox(); self.pv_initial_slope.setRange(0.005,1.0); self.pv_initial_slope.setDecimals(3); self.pv_initial_slope.setSingleStep(0.005); self.pv_initial_slope.setValue(0.055)
        sg.addWidget(self.pv_initial_slope,1,1)
        sg.addWidget(QLabel('最终PV允许偏差 (°C)'),1,2)
        self.pv_final_tolerance = QDoubleSpinBox(); self.pv_final_tolerance.setRange(0.05,5.0); self.pv_final_tolerance.setDecimals(2); self.pv_final_tolerance.setSingleStep(0.05); self.pv_final_tolerance.setValue(0.10)
        sg.addWidget(self.pv_final_tolerance,1,3)
        sg.addWidget(QLabel('最终PV连续稳定时间 (秒)'),2,0)
        self.pv_final_seconds = QSpinBox(); self.pv_final_seconds.setRange(60,1800); self.pv_final_seconds.setValue(300)
        sg.addWidget(self.pv_final_seconds,2,1)
        self.formal_gate_note = QLabel('正式PLC模式：PV进入目标±1°C后，连续观察5分钟（极差≤0.30°C、线性斜率≤0.055°C/min）；再累计共同热平衡1800秒；最后PV在目标±0.10°C内连续5分钟，并通过芯片60秒波动≤0.20°C检查。')
        self.formal_gate_note.setWordWrap(True)
        self.formal_gate_note.setStyleSheet('color:#795c26')
        sg.addWidget(self.formal_gate_note,3,0,1,4)
        # R6 production: operators may adjust QUALITY thresholds before starting.
        # None of these edits disable the PLC's independent hardware protection.
        sg.addWidget(QLabel('单温度温漂暂停次数上限（达到后停止整场实验，不跳温）'),5,0,1,2)
        self.thermal_max_holds = QSpinBox()
        self.thermal_max_holds.setObjectName('thermal_max_quality_holds')
        self.thermal_max_holds.setRange(1,100); self.thermal_max_holds.setValue(5)
        self.thermal_max_holds.setToolTip('超限后WK安全停车、存档INCOMPLETE，后续温度不自动执行。')
        sg.addWidget(self.thermal_max_holds,5,2)
        sg.addWidget(QLabel('单温度累计等待上限（分钟；超限停止整场实验）'),6,0,1,2)
        self.thermal_max_wait_minutes = QSpinBox()
        self.thermal_max_wait_minutes.setObjectName('thermal_max_stabilization_wait_minutes')
        self.thermal_max_wait_minutes.setRange(15,720); self.thermal_max_wait_minutes.setValue(120)
        self.thermal_max_wait_minutes.setToolTip('PLC到温/热浸/复稳累计超时将安全中止并保留断点，不再跨温度跳过。')
        sg.addWidget(self.thermal_max_wait_minutes,6,2)
        sg.addWidget(QLabel('单次停车后温度恢复上限（分钟；超限停止整场实验）'),7,0,1,2)
        self.thermal_recovery_wait_minutes = QSpinBox()
        self.thermal_recovery_wait_minutes.setObjectName('thermal_recovery_wait_minutes')
        self.thermal_recovery_wait_minutes.setRange(5,360); self.thermal_recovery_wait_minutes.setValue(60)
        sg.addWidget(self.thermal_recovery_wait_minutes,7,2)
        sg.addWidget(QLabel('生产实验不允许跳过温度点或缺失步骤；完整12姿态联合拟合、跨姿态芯片温差只记录，设备故障仍安全中止。'),8,0,1,4)
        # Starting temperature must be reached BY PLC before WK is allowed to move.
        # These bands are quality gates, separate from independent PLC hard protection.
        sg.addWidget(QLabel('初步到温PV允许偏差 (℃)'),9,0)
        self.pv_initial_band=QDoubleSpinBox();self.pv_initial_band.setObjectName('pv_initial_band_c')
        self.pv_initial_band.setRange(0.2,5.0);self.pv_initial_band.setDecimals(2)
        self.pv_initial_band.setSingleStep(0.1);self.pv_initial_band.setValue(1.0)
        sg.addWidget(self.pv_initial_band,9,1)
        sg.addWidget(QLabel('共同热浸PV允许偏差 (℃)'),9,2)
        self.pv_soak_band=QDoubleSpinBox();self.pv_soak_band.setObjectName('pv_soak_band_c')
        self.pv_soak_band.setRange(0.2,5.0);self.pv_soak_band.setDecimals(2)
        self.pv_soak_band.setSingleStep(0.1);self.pv_soak_band.setValue(1.0)
        sg.addWidget(self.pv_soak_band,9,3)
        gate_hint=QLabel('三个准入条件独立：初步到温→按许可区间累计热浸→最终PV连续稳定和芯片稳定；只有全部合格才启动转台。')
        gate_hint.setWordWrap(True);sg.addWidget(gate_hint,10,0,1,4)
        layout.addWidget(stability_box)

        arrive_box=QGroupBox('PLC直接设定目标温度（不分级设SP；WK在到温期间停车）')
        ar=QVBoxLayout(arrive_box)
        auto_note=QLabel('每个温度点直接调用原PLC设温接口写入目标SP；保留SP回读、PLC运行状态、'
                         'PV与芯片温度检查及WK安全停车确认。取消原R6的每级5℃中间设温。'
                         '请在首次−40℃/高温试验前现场确认温箱厂家允许直接跨温度设定，'
                         '并确认PCB、线缆、夹具、热冲击和温箱自身的升降温保护；'
                         '软件写目标SP不意味着PLC会以指定速率变化。')
        auto_note.setWordWrap(True);ar.addWidget(auto_note)
        layout.addWidget(arrive_box)

        runtime_box = QGroupBox('运行中温度质量阈值（可编辑；启动后冻结并写入配置，不覆盖PLC硬安全）')
        rt = QGridLayout(runtime_box)
        def runtime_spin(key, value, lower, upper, step, decimals=2):
            w = QDoubleSpinBox(); w.setObjectName('runtime_'+key)
            w.setRange(lower, upper);w.setDecimals(decimals)
            w.setSingleStep(step);w.setValue(value)
            return w
        self.runtime_pv_follow_final=QCheckBox('运行期间PV暂停偏差跟随“最终PV允许偏差”（勾选后不会偷偷使用±1℃）')
        self.runtime_pv_follow_final.setObjectName('runtime_pv_follow_final')
        self.runtime_pv_follow_final.setChecked(True)
        rt.addWidget(self.runtime_pv_follow_final,0,0,1,4)
        rt.addWidget(QLabel('运行PV暂停偏差 (℃)'),1,0)
        self.runtime_pv_pause=runtime_spin('pv_pause_c', 1.0,0.05,5.0,0.1)
        rt.addWidget(self.runtime_pv_pause,1,1)
        rt.addWidget(QLabel('连续超过时间 (秒)'),1,2)
        self.runtime_pv_hold=QSpinBox();self.runtime_pv_hold.setObjectName('runtime_pv_hold_seconds')
        self.runtime_pv_hold.setRange(5,1800);self.runtime_pv_hold.setValue(60)
        rt.addWidget(self.runtime_pv_hold,1,3)
        rt.addWidget(QLabel('重新热浸PV偏差 (℃)'),2,0)
        self.runtime_resoak_pv=runtime_spin('resoak_pv_c',3.0,0.10,7.0,0.1)
        rt.addWidget(self.runtime_resoak_pv,2,1)
        rt.addWidget(QLabel('连续超过时间 (秒)'),2,2)
        self.runtime_resoak_hold=QSpinBox();self.runtime_resoak_hold.setObjectName('runtime_resoak_hold_seconds')
        self.runtime_resoak_hold.setRange(5,1800);self.runtime_resoak_hold.setValue(60)
        rt.addWidget(self.runtime_resoak_hold,2,3)
        rt.addWidget(QLabel('芯片60秒极差上限 (℃)'),3,0)
        self.runtime_chip_span=runtime_spin('chip_span_c',0.3,0.05,3.0,0.05)
        rt.addWidget(self.runtime_chip_span,3,1)
        rt.addWidget(QLabel('持续超限 (秒)'),3,2)
        self.runtime_chip_span_hold=QSpinBox();self.runtime_chip_span_hold.setObjectName('runtime_chip_span_hold_seconds')
        self.runtime_chip_span_hold.setRange(5,1800);self.runtime_chip_span_hold.setValue(60)
        rt.addWidget(self.runtime_chip_span_hold,3,3)
        rt.addWidget(QLabel('芯片5分钟斜率上限 (℃/min)'),4,0)
        self.runtime_chip_slope=runtime_spin('chip_slope_c_per_min',0.10,0.005,2.0,0.01,3)
        rt.addWidget(self.runtime_chip_slope,4,1)
        rt.addWidget(QLabel('持续超限 (秒)'),4,2)
        self.runtime_chip_slope_hold=QSpinBox();self.runtime_chip_slope_hold.setObjectName('runtime_chip_slope_hold_seconds')
        self.runtime_chip_slope_hold.setRange(5,1800);self.runtime_chip_slope_hold.setValue(120)
        rt.addWidget(self.runtime_chip_slope_hold,4,3)
        rt.addWidget(QLabel('恢复时PV最大偏差 (℃)'),5,0)
        self.runtime_recovery_pv=runtime_spin('recovery_pv_c',0.75,0.05,5.0,0.05)
        rt.addWidget(self.runtime_recovery_pv,5,1)
        rt.addWidget(QLabel('恢复时芯片60秒极差 (℃)'),5,2)
        self.runtime_recovery_chip_span=runtime_spin('recovery_chip_span_c',0.2,0.02,2.0,0.02)
        rt.addWidget(self.runtime_recovery_chip_span,5,3)
        rt.addWidget(QLabel('恢复时芯片5分钟斜率 (℃/min)'),6,0)
        self.runtime_recovery_chip_slope=runtime_spin('recovery_chip_slope_c_per_min',0.08,0.005,1.0,0.005,3)
        rt.addWidget(self.runtime_recovery_chip_slope,6,1)
        self.runtime_quality_note=QLabel('注意：这些是采集质量门槛，不是设备硬安全限值；运行时可调节范围受到边界限制。'
            'PV暂停阈值必须低于重新热浸阈值，恢复阈值必须低于暂停阈值。任何缺失都不会自动跳过。')
        self.runtime_quality_note.setWordWrap(True)
        rt.addWidget(self.runtime_quality_note,7,0,1,4)
        layout.addWidget(runtime_box)
        self.runtime_pv_follow_final.toggled.connect(self._on_runtime_follow_changed)
        self.pv_final_tolerance.valueChanged.connect(self._on_runtime_follow_changed)
        self._on_runtime_follow_changed()
        self.thermal_quality_mode.currentIndexChanged.connect(self._on_quality_policy_changed)
        self._on_quality_policy_changed()
        rate_quality_box = QGroupBox('GYRO转台独立测速质检（仅本次温补实验，可自行设置）')
        rq = QGridLayout(rate_quality_box)
        def new_quality_spin(value, minimum, maximum, step, decimals=3):
            w=QDoubleSpinBox();w.setDecimals(decimals);w.setRange(minimum,maximum)
            w.setSingleStep(step);w.setValue(value)
            return w
        rq.addWidget(QLabel('低速差分波动上限 (°/s)'),0,0)
        self.wk_std_low=new_quality_spin(0.180,0.080,0.350,0.010)
        self.wk_std_low.setObjectName('thermal_wk_std_low')
        rq.addWidget(self.wk_std_low,0,1)
        rq.addWidget(QLabel('≥25°/s波动上限 (°/s)'),0,2)
        self.wk_std_high=new_quality_spin(0.240,0.100,0.600,0.010)
        self.wk_std_high.setObjectName('thermal_wk_std_high')
        self.wk_std_high.setToolTip('默认0.240°/s；最大允许输入0.600仅供已核实编码器参考噪声后的专项研发。超过0.350需单独确认；不等于放宽机械稳速/安全要求。')
        rq.addWidget(self.wk_std_high,0,3)
        rq.addWidget(QLabel('平均速度偏差上限 (°/s)'),1,0)
        self.wk_mean_error=new_quality_spin(0.300,0.100,0.500,0.025)
        rq.addWidget(self.wk_mean_error,1,1)
        rq.addWidget(QLabel('前后半段斜率差上限 (°/s)'),1,2)
        self.wk_slope_delta=new_quality_spin(0.360,0.100,0.600,0.020)
        rq.addWidget(self.wk_slope_delta,1,3)
        rq.addWidget(QLabel('位置回归残差RMS上限 (°)'),2,0)
        self.wk_position_residual=new_quality_spin(0.350,0.050,0.600,0.025)
        rq.addWidget(self.wk_position_residual,2,1)
        self.wk_quality_note=QLabel('推荐：低速0.180、≥25°/s为0.240°/s（之前30°/s差分测速噪声接近0.180）。'
            '无论怎样调整，仍须通过独立编码器方向、平均速度、斜率趋势、位置回归、反馈时效、采样质量及真实停车检查。'
            '此设置只对新实验有效，启动后锁定并写入配置/报告；大于0.350°/s需额外风险确认，放宽不等于计量认证。')
        self.wk_quality_note.setWordWrap(True)
        rq.addWidget(self.wk_quality_note,3,0,1,4)
        layout.addWidget(rate_quality_box)
        recovery_temp_note = QLabel(
            'R7生产自适应：12姿态保持一整组，跨姿态芯片均温相差2℃或更多不会因此丢弃已接受工况；'
            '报告记录实际温差，每工况以自己的芯片均温参与同一套联合温补拟合。'
            '仍保留单工况质量、PLC/WK硬保护、SP回读及真实停车确认；'
            '设备长时间未能满足开始前稳定门槛时仍会保存断点并安全中止，不会自动跳温。'
            'R7不增加额外正增益百分比验收门槛。')
        recovery_temp_note.setWordWrap(True)
        recovery_temp_note.setStyleSheet('color:#795c26')
        layout.addWidget(recovery_temp_note)

        group = QGroupBox('启动条件与安全确认')
        gh = QVBoxLayout(group)
        self.check_axis = QCheckBox('已在实机核对 2FDT 内/外轴与 P 坐标系的方向、零位、正转定义；已完成找零')
        self.check_safe = QCheckBox('已确认装夹、配平、线缆、机械范围、门禁和硬件急停；全过程安排人员监护')
        self.check_sensor = QCheckBox('已核对 MCU 量程/ODR 不变、温度传感器有效，且现有常温标定不会被覆盖')
        for w in (self.check_axis,self.check_safe,self.check_sensor): gh.addWidget(w)
        self.check_highspeed = QCheckBox('高速速率 >30°/s：已核实温箱内线缆、滑环及对应速率的连续运行安全')
        self.check_highspeed.setToolTip('勾选不代表设备厂家已批准。需要实测确认能在当前装夹和温箱内安全旋转。')
        gh.addWidget(self.check_highspeed)
        self.check_plc = QCheckBox('已在这台如洋温箱上实测验证：原温箱页面能读取PV、设定SP，并确实发生升/降温（PLC自动模式必选）')
        gh.addWidget(self.check_plc)
        self._on_chamber_mode_changed()
        layout.addWidget(group)
        recovery_box = QGroupBox('正式实验前检查 / 失败后续做（不重做已完成工况）')
        recovery_layout = QGridLayout(recovery_box)
        self.preflight_button = QPushButton('预检查全部速率与预计转角（不让设备运动）')
        self.preflight_button.clicked.connect(self._preview_preflight)
        recovery_layout.addWidget(self.preflight_button,0,0,1,4)
        self.resume_checkbox = QCheckBox('从已有未完成实验继续（需要同一PCB、温度点与全部原始配置）')
        recovery_layout.addWidget(self.resume_checkbox,1,0,1,4)
        self.resume_directory = QLineEdit()
        self.resume_directory.setPlaceholderText('选择之前生成的 THERM_年月日_时间 实验文件夹')
        recovery_layout.addWidget(self.resume_directory,2,0,1,3)
        self.resume_browse = QPushButton('选择未完成实验目录…')
        self.resume_browse.clicked.connect(self._browse_resume)
        recovery_layout.addWidget(self.resume_browse,2,3)
        hint = QLabel('每个成功工况立即存档。续做重新设温并检查芯片热平衡，仅跳过已完成的合格工况；正在运行/异常工况会重做。')
        hint.setWordWrap(True)
        recovery_layout.addWidget(hint,3,0,1,4)
        layout.addWidget(recovery_box)
        # 与旧常温IMU标定共用12+12 ACC姿态和A/B/C数学方案，
        # 但电机控制只走当前2FDT600WK温控转台，绝不调用旧2TD600 DLL。
        wk_compare_box = QGroupBox('转台对照试验：任意稳定温度下的单点IMU标定（非温补；不改现有参数）')
        wc = QVBoxLayout(wk_compare_box)
        wk_compare_note = QLabel(
            '复用原IMU常温标定：ACC 12拟合+12独立姿态验证、原生产质量配置、'
            'A/B/C三方案及同格式Excel报告。仅改为当前2FDT600WK的真实双轴控制/反馈。'
            '不改变PLC设温，不执行15温度点，不覆盖旧转台标定参数。'
            '允许任意有效实测温度（不再限定20～30℃）；但单次实验必须保持温度稳定。'
            '同一Excel包含ACC拟合/独立验证的模长相对1g的RMSE和三维向量RMSE。')
        wk_compare_note.setWordWrap(True)
        wc.addWidget(wk_compare_note)
        wk_compare_opts = QHBoxLayout()
        self.wk_ambient_gravity_sign = QComboBox()
        self.wk_ambient_gravity_sign.addItem('基座静止比力 +Z / +1g', 1)
        self.wk_ambient_gravity_sign.addItem('基座静止比力 -Z / -1g', -1)
        self.wk_ambient_gravity_sign.setToolTip('必须与以前常温IMU标定采用的重力符号一致')
        wk_compare_opts.addWidget(QLabel('参考重力定义'))
        wk_compare_opts.addWidget(self.wk_ambient_gravity_sign)
        self.wk_ambient_include_gyro = QCheckBox('连同GYRO旧常温工艺一起对照（拟合±1/2/5，验证±1.5/3.5°/s）')
        self.wk_ambient_include_gyro.setChecked(False)
        wk_compare_opts.addWidget(self.wk_ambient_include_gyro)
        wc.addLayout(wk_compare_opts)
        self.wk_ambient_start = QPushButton('启动单点IMU对照标定（当前WK转台，默认先测ACC）')
        self.wk_ambient_start.setObjectName('button_WKAmbientComparison')
        self.wk_ambient_start.setToolTip('不限20～30℃；记录真实温度；新建独立WK_AMBIENT_COMPARE目录，走原12拟合/12验证及A/B/C算法，不操作PLC。')
        self.wk_ambient_start.clicked.connect(self._start_wk_ambient_comparison)
        wc.addWidget(self.wk_ambient_start)
        self.wk_ambient_rebuild = QPushButton('离线重算已有WK对照报告（拟合/验证/模长RMSE，不重新采集）')
        self.wk_ambient_rebuild.setToolTip('读取已保存WK_AMBIENT_COMPARE目录的24姿态结果，不连接或运动转台，不改旧标定参数。')
        self.wk_ambient_rebuild.clicked.connect(self._reanalyze_wk_ambient_run)
        wc.addWidget(self.wk_ambient_rebuild)
        layout.addWidget(wk_compare_box)
        self.reanalyze_button = QPushButton('离线分析完整/部分完成实验（ACC与GYRO独立出报告）')
        self.reanalyze_button.setToolTip('选择COMPLETED或PARTIAL_COMPLETED实验目录；分别检查ACC/GYRO是否完整；完整传感器独立出28模型报告，不写入硬件。')
        self.reanalyze_button.clicked.connect(self._reanalyze_saved_run)
        layout.addWidget(self.reanalyze_button)
        row = QHBoxLayout()
        self.start_button = QPushButton('启动自动温补实验')
        self.start_button.clicked.connect(self.start)
        self.stop_button = QPushButton('中止并停车')
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(lambda: self._abort('操作员主动中止'))
        row.addWidget(self.start_button,2); row.addWidget(self.stop_button,1)
        layout.addLayout(row)
        self.rearm_thermal_button = QPushButton('仅人工温箱兼容路径：温漂人工恢复（PLC自动模式不需要点击）')
        self.rearm_thermal_button.setEnabled(False)
        self.rearm_thermal_button.clicked.connect(self._rearm_thermal_hold)
        self.rearm_thermal_button.setVisible(False)  # full PLC runs use autonomous bounded recovery
        layout.addWidget(self.rearm_thermal_button)
        self.label = QLabel('状态：空闲');self.label.setWordWrap(True)
        layout.addWidget(self.label)
        self.progress = QProgressBar(); layout.addWidget(self.progress)
        self.selection_result = QLabel('28套温补候选：待完成实验；PV仅供拟合温度校正，运行时仅依赖芯片温度；独立温度不参与排名。')
        self.selection_result.setWordWrap(True)
        layout.addWidget(self.selection_result)
        self.log = QPlainTextEdit(); self.log.setReadOnly(True);self.log.setMinimumHeight(145)
        layout.addWidget(self.log)
        layout.addStretch(1)

    def _reanalyze_saved_run(self):
        """Read-only offline analysis. PARTIAL only when sensor plan is provably full."""
        if self.task is not None:
            QMessageBox.warning(self.page,'离线分析不可用','温补采集进行中，禁止同时处理实验文件。')
            return
        folder=QFileDialog.getExistingDirectory(self.page,'选择已完成或部分完成的温补实验目录',
                                                 self.output.text())
        if not folder:return
        try:
            root=Path(folder)
            checkpoint=json.loads((root/'temperature_measurements.json').read_text(encoding='utf-8'))
            if checkpoint.get('status') not in ('COMPLETED','PARTIAL_COMPLETED'):
                raise ValueError('仅能对COMPLETED/PARTIAL_COMPLETED存档离线分析，不能将运行中数据当作结果')
            rows=checkpoint.get('rows')
            if not isinstance(rows,list) or not rows:raise ValueError('没有可用的已接受逐工况记录')
            config=json.loads((root/'experiment_config.json').read_text(encoding='utf-8'))
            sensors=fully_accepted_sensors(config,checkpoint)
            if not sensors:
                raise ValueError('ACC/GYRO均缺少必需工况；只生成缺失报告，不输出不完整模型')
            temps=[float(x) for x in config['temperature_setpoints_c']]
            stamp=datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
            output=root/('模型优选离线复算_'+stamp)
            result=publish_sensor_reports(output,rows,temps,sensors,source_folder=root)
            info='；'.join(f'{k.upper()}：{v.get("selected_id") or "未选出"} / {v.get("status_text",v.get("status"))}'
                          for k,v in result['selection']['sensors'].items())
            self.selection_result.setText('离线研发分析：'+info)
            self._log('离线独立报告已保存：'+result['combined_workbook'])
            QMessageBox.information(self.page,'离线复算完成',
                    '研发报告：'+result['combined_workbook']+'\n'+info+
                    '\nACC/GYRO分别有独立Excel与Markdown说明；不会写入MCU。')
        except Exception as exc:
            self._log('离线分析失败：'+str(exc))
            QMessageBox.warning(self.page,'离线分析失败',str(exc))

    def _reanalyze_wk_ambient_run(self):
        """Rebuild A/B/C + old-style C Excel from recorded WK rows, no hardware IO."""
        if self.task is not None:
            QMessageBox.warning(self.page,'离线复算不可用','采集进行中，不允许同时读写实验报告。')
            return
        directory=QFileDialog.getExistingDirectory(
            self.page,'选择已完成的WK_AMBIENT_COMPARE实验目录',self.output.text())
        if not directory:return
        try:
            original=Path(directory)
            config=json.loads((original/'experiment_config.json').read_text(encoding='utf-8'))
            if config.get('experiment_kind')!='wk_ambient_comparison':
                raise ValueError('所选目录并非WK单点IMU对照实验，禁止混用温补数据')
            checkpoint=json.loads((original/'temperature_measurements.json').read_text(encoding='utf-8'))
            if checkpoint.get('status')!='COMPLETED':
                raise ValueError('原实验尚未完整完成，不能把部分数据误报为标定完成')
            rows=checkpoint.get('rows',[])
            if not isinstance(rows,list) or not rows:
                raise ValueError('未发现原始已接受工况记录')
            profile=config.get('quality_profile')
            if not isinstance(profile,dict):
                raise ValueError('旧工艺配置快照不存在，不能擅自改用另一工艺重算')
            immutable=config.get('resume_immutable_config') or {}
            output=original/('WK单点报告离线重算_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S'))
            output.mkdir(parents=False,exist_ok=False)
            from wk_ambient_comparison import export_ambient_comparison
            report,paths=export_ambient_comparison(
                output,rows,profile,
                axis_model=immutable.get('axis_model','outer_x_inner_z'),
                gravity_sign=int(config.get('gravity_sign',immutable.get('gravity_sign',1))),
                device_serial=config.get('device_sn',checkpoint.get('device_sn','未记录')),
                include_gyro=bool(config.get('gyro_dynamic',False)))
            summary='；'.join(f'{x.upper()}：{v["status"]}' for x,v in report['models'].items())
            self._log('WK单点旧数据报告离线重算完成：'+str(output))
            self.selection_result.setText('WK单点对照新报告：'+str(output))
            QMessageBox.information(self.page,'WK单点报告离线重算完成',
                '已输出拟合/验证与模长RMSE新报告：\n'+str(output)+'\n'+summary+
                '\n没有重新采集、没有操作转台或PLC。')
        except Exception as exc:
            self._log('WK单点报告离线重算失败：'+str(exc))
            QMessageBox.warning(self.page,'WK单点离线重算失败',str(exc))

    def _on_production_mode_changed(self, *_args):
        if hasattr(self,'production_mode') and self.production_mode.currentData() in ('warming','cooling','combined'):
            self.production_info.setText('R5双向扫描：一个按钮依次执行升温及降温，但两趟分别独立存档；首趟必须在−40℃附近开始，'+
                                         '升到85℃停车并确认PLC停止后自动接降温；末趟结束回25℃。请先加载方案并确认现场安全。'
                                         '本软件不提供量产自动放行；真实机械零位/六轴坐标仍须独立验证。')

    def _apply_production_preset(self):
        if self.task is not None:
            QMessageBox.warning(self.page,'任务进行中','禁止在运行过程中修改双向扫描配置')
            return
        direction=str(self.production_mode.currentData())
        if direction=='combined':direction='warming'
        if direction not in ('warming','cooling'):
            QMessageBox.information(self.page,'先选择任务','请先在扫描任务中选择“升温”或“降温”。')
            return
        plan=generate_temperature_plan(direction)
        self.fit_temperatures.setText(', '.join(f'{x:g}' for x in plan['fit_temperatures_c']))
        self.validation_temperatures.setText(', '.join(f'{x:g}' for x in plan['validation_temperatures_c']))
        self.gyro_rate_mode.setCurrentIndex(self.gyro_rate_mode.findData('custom'))
        self.gyro_fit_rates.setText(', '.join(f'{x:g}' for x in R4_FIT_RATES))
        self.gyro_verify_rates.setText(', '.join(f'{x:g}' for x in R4_VERIFY_RATES))
        self.dynamic.setChecked(True)
        self.chamber_mode.setCurrentIndex(self.chamber_mode.findData('plc'))
        self.thermal_quality_mode.setCurrentIndex(self.thermal_quality_mode.findData('production_adaptive'))
        self.chip_stability_only.setChecked(False)
        self.dwell.setValue(1800)
        self.sample_seconds.setValue(8)
        self.pv_initial_seconds.setValue(180)
        self.pv_initial_range.setValue(0.8)
        self.pv_initial_slope.setValue(0.15)
        self.pv_final_tolerance.setValue(0.75)
        self.pv_final_seconds.setValue(180)
        self._on_runtime_follow_changed()
        self.production_info.setText('已加载：'+direction+'，温度顺序：'+', '.join(f'{x:g}' for x in plan['temperature_setpoints_c'])+
             '℃。双向自动模式由升温结束后安全接续降温。PV容差根据设备能力必须现场确认，芯片60秒稳定和全程工况监控仍保留。'
             '如设备达不到门槛将暂停/留下缺失，不应放宽后虚报合格。')

    def _run_production_analysis(self):
        if getattr(self,'_r4_analysis_proc',None) is not None and self._r4_analysis_proc.state()!=QProcess.NotRunning:
            QMessageBox.information(self.page,'正在分析','上一项离线分析仍在运行')
            return
        root=QFileDialog.getExistingDirectory(self.page,'选择包含同批次升温与降温两次THERM_记录的父文件夹',str(Path(self.output.text()).expanduser()))
        if not root:return
        self._run_r5_analysis_from_folder(root)

    def _run_r5_analysis_from_folder(self,root):
        if getattr(self,'_r4_analysis_proc',None) is not None and self._r4_analysis_proc.state()!=QProcess.NotRunning:
            self._log('合并分析已有任务执行中，本次跳过');return
        self._r4_analysis_proc=QProcess(self.page)
        self._r4_analysis_proc.setProgram(sys.executable)
        env=QProcessEnvironment.systemEnvironment()
        env.insert('PYTHONIOENCODING','utf-8')
        self._r4_analysis_proc.setProcessEnvironment(env)
        args=[str(ROOT/'production_cycle_analysis.py'),str(root),
              '--model-policy',str(self.production_curve_policy.currentData())]
        if self.production_batch_id.text().strip():
            args.extend(['--batch-id',self.production_batch_id.text().strip()])
        self._r4_analysis_proc.setArguments(args)
        self._r4_analysis_proc.setWorkingDirectory(str(ROOT))
        self._r4_analysis_proc.setProcessChannelMode(QProcess.MergedChannels)
        self.production_analyze.setEnabled(False)
        self._r4_analysis_proc.finished.connect(self._production_analysis_finished)
        self._r4_analysis_proc.start()
        self._log('R5联合离线分析已启动（独立斜坡/六轴验证，绝不连接设备）：'+str(root))

    def _production_analysis_finished(self,exit_code,exit_status):
        self.production_analyze.setEnabled(True)
        out=bytes(self._r4_analysis_proc.readAllStandardOutput()).decode('utf-8',errors='replace')
        self._log('R5离线分析返回代码='+str(exit_code)+'：'+out[-1500:])
        if exit_code:
            QMessageBox.warning(self.page,'离线分析未完成',out[-2500:] or '详见运行环境和实验批次完整性')
            return
        line=next((x for x in out.splitlines() if x.startswith('双向温补报告已生成:')),None)
        if line:
            target=Path(line.split(':',1)[1].strip())
            if target.is_file():
                webbrowser.open(target.as_uri())
                QMessageBox.information(self.page,'双向报告已生成',str(target))
                return
        QMessageBox.information(self.page,'处理完成',out[-1800:])

    def _on_runtime_follow_changed(self, *_args):
        if not hasattr(self, 'runtime_pv_pause'):return
        enabled=bool(self.runtime_pv_follow_final.isChecked())
        if enabled:
            limit=float(self.pv_final_tolerance.value())
            self.runtime_pv_pause.setValue(limit)
            if self.runtime_recovery_pv.value()>=limit:
                self.runtime_recovery_pv.setValue(max(0.05,round(limit*0.75,2)))
        self.runtime_pv_pause.setEnabled(self.task is None and not enabled)

    def _runtime_policy_from_ui(self):
        from thermal_production_quality import validated_runtime_policy
        params={
            'pv_pause_c':float(self.pv_final_tolerance.value()) if self.runtime_pv_follow_final.isChecked()
                         else float(self.runtime_pv_pause.value()),
            'pv_hold_seconds':float(self.runtime_pv_hold.value()),
            'resoak_pv_c':float(self.runtime_resoak_pv.value()),
            'resoak_hold_seconds':float(self.runtime_resoak_hold.value()),
            'chip_span_c':float(self.runtime_chip_span.value()),
            'chip_span_hold_seconds':float(self.runtime_chip_span_hold.value()),
            'chip_slope_c_per_min':float(self.runtime_chip_slope.value()),
            'chip_slope_hold_seconds':float(self.runtime_chip_slope_hold.value()),
            'recovery_pv_c':float(self.runtime_recovery_pv.value()),
            'recovery_chip_span_c':float(self.runtime_recovery_chip_span.value()),
            'recovery_chip_slope_c_per_min':float(self.runtime_recovery_chip_slope.value())}
        return validated_runtime_policy(params)

    def _on_quality_policy_changed(self, *_args):
        if not hasattr(self, 'thermal_quality_mode') or self.task is not None:
            return
        policy=policy_for(str(self.thermal_quality_mode.currentData()))
        self.dwell.setValue(policy['dwell_seconds'])
        for attr, key in (('pv_initial_seconds','pv_initial_window_seconds'),
                          ('pv_initial_range','pv_initial_range_c'),
                          ('pv_initial_slope','pv_initial_slope_c_per_min'),
                          ('pv_final_tolerance','pv_final_tolerance_c'),
                          ('pv_final_seconds','pv_final_stable_seconds')):
            getattr(self, attr).setValue(policy[key])
        self.pv_initial_band.setValue(policy['pv_initial_band_c'])
        self.pv_soak_band.setValue(policy['soak_band_c'])
        self._on_runtime_follow_changed()
        self._on_thermal_mode_changed()

    def _new_guard(self):
        t=self.task
        # NEVER rebuild from a hard-coded production dictionary or mutable UI:
        # the experiment's frozen, auditable values are the sole source.
        limits=t.get('runtime_temperature_guard_policy')
        if limits is None:
            limits=policy_for(str(t.get('temperature_quality_mode','strict')))['runtime']
        return ThermalRuntimeGuard(t['temps'][t['temp_i']],**limits)

    def _thermal_band(self, key):
        mode=self.task.get('temperature_quality_mode','strict')
        return float(policy_for(mode)[key])

    def _on_thermal_mode_changed(self, *args):
        # 快速模式跳过正式热浸与两级温箱稳定判据；人工模式无法读取连续PLC PV，保留人工确认路径。
        quick = self.chip_stability_only.isChecked()
        self.dwell.setEnabled(self.task is None and not quick)
        formal_plc = (self.task is None and not quick and self.chamber_mode.currentData() == 'plc')
        for widget in (self.pv_initial_seconds, self.pv_initial_range, self.pv_initial_slope,
                       self.pv_final_tolerance, self.pv_final_seconds):
            widget.setEnabled(formal_plc)
        if hasattr(self, 'formal_gate_note'):
            if quick:
                self.formal_gate_note.setText('当前为快速流程测试模式：跳过正式共同热平衡和最终PV精确稳定检查，不建议将该模式数据直接用于正式温补模型。')
            elif self.chamber_mode.currentData() == 'manual':
                self.formal_gate_note.setText('当前为人工设温模式：无法连续读取PLC PV，因此不执行两级温箱PV判据；采用人工确认、共同热平衡时间及芯片温度稳定检查。正式温补建议使用PLC自动模式。')
            else:
                self.formal_gate_note.setText('PLC采样门槛：先观察新鲜PV→至少保温设定时长→最终PV连续稳定+芯片60秒稳定。研发连续模式保留每工况真实温度，温差较大时在报告中标记研发风险；严格恒温保留原版判据。')

    def _on_chamber_mode_changed(self, *args):
        auto = self.chamber_mode.currentData()=='plc'
        self.manual_pv.setEnabled(not auto)
        self.check_plc.setEnabled(auto)
        if auto:
            self.confirm_temp.setEnabled(False)
            self.plc_telemetry.setText('PLC自动控温：连接且报警正常即可点击开始；自动到首温、SP回读、PV/芯片稳定均由程序完成。')
        else:
            self.plc_telemetry.setText('人工模式：必须逐温度点在面板设温和确认PV，不发送任何未知RS-232命令。')
        self._on_thermal_mode_changed()

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

    def _browse_resume(self):
        path = QFileDialog.getExistingDirectory(self.page, '选择未完成的THERM实验目录',
                                                self.resume_directory.text() or self.output.text())
        if path:
            self.resume_directory.setText(path)
            self.resume_checkbox.setChecked(True)

    def _on_gyro_rate_mode_changed(self, *_args):
        mode = self.gyro_rate_mode.currentData()
        if mode in ('pilot', 'full', 'low_speed'):
            presets = {
                'pilot': (PILOT_FIT_RATES_DPS, PILOT_VERIFY_RATES_DPS),
                'full': (FIT_RATES_DPS, VERIFY_RATES_DPS),
                'low_speed': (LOW_SPEED_FIT_RATES_DPS, LOW_SPEED_VERIFY_RATES_DPS),
            }
            fit, verify = presets[mode]
            self.gyro_fit_rates.setText(', '.join(f'{v:g}' for v in fit))
            self.gyro_verify_rates.setText(', '.join(f'{v:g}' for v in verify))
        editable = mode == 'custom' and self.task is None
        self.gyro_fit_rates.setReadOnly(not editable)
        self.gyro_verify_rates.setReadOnly(not editable)

    def _selected_rates(self):
        """Use exactly the displayed plan, not hidden hard-coded speed points."""
        mode = self.gyro_rate_mode.currentData()
        if mode == 'custom':
            return validate_rate_lists(
                parse_rate_list(self.gyro_fit_rates.text(), 'GYRO拟合速率'),
                parse_rate_list(self.gyro_verify_rates.text(), 'GYRO独立验证速率'))
        if mode == 'full':
            return FIT_RATES_DPS, VERIFY_RATES_DPS
        if mode == 'low_speed':
            return LOW_SPEED_FIT_RATES_DPS, LOW_SPEED_VERIFY_RATES_DPS
        return PILOT_FIT_RATES_DPS, PILOT_VERIFY_RATES_DPS

    def _preview_preflight(self):
        """仅作速度参数校验和转角风险提示；不发送电机或PLC指令。"""
        try:
            if not self.dynamic.isChecked():
                QMessageBox.information(self.page,'温补预检查','当前未启用GYRO动态多速率；仅做ACC/静态GYRO采集。')
                return
            accel = int(self.gyro_accel.value())
            sample_seconds = int(self.sample_seconds.value())
            rates_fit,rates_val=self._selected_rates()
            speeds = sorted(set(rates_fit + rates_val))
            # 预检查只展示风险/可行性，不发送运动命令，故不要求安全勾选。
            # 真正启动时任何大于30°/s的自定义/预设工况都必须先人工确认。
            lines=['各目标速率的保守单段累计转角估算（仅供安全评估，不作为软件限额）：',
                   f'每个拟合温度：GYRO动态拟合{6*len(rates_fit)}项，GYRO工况验证{6*len(rates_val)}项；每个独立验证温度：GYRO动态{6*len(rates_val)}项',
                   '速率点更多，自动运行总时长会增加；低速每段角位移较小，请检查反馈分辨率及采样时长。',
                   '本次拟合：'+str(rates_fit)+'；独立验证：'+str(rates_val),
                   '（包含加减速、至少1秒稳速等待及0.5秒余量）','']
            for speed in speeds:
                # 检查两轴额定角速度及整数加速度范围，负转使用相同幅值。
                for axis in ('inner','outer'):
                    wk_signed_velocity(+speed,accel,axis)
                    wk_signed_velocity(-speed,accel,axis)
                degrees=conservative_sweep_degrees(speed,accel,sample_seconds)
                lines.append(f'{speed:g}°/s：预计约 {degrees:.1f}°；无固定累计角度拦截')
            lines.append('')
            if speeds[-1] > 30:
                lines.append('高速风险：本次含>30°/s工况，正式启动前必须勾选高速安全确认。')
            if rates_val[0] < rates_fit[0] or rates_val[-1] > rates_fit[-1]:
                lines.append('警告：部分独立验证速率超出拟合范围，属于外推验证，不代表区间内性能。')
            lines.append('结果：当前速率与加速度参数检查通过。')
            lines.append('此检查不证明温箱内的线缆/装夹、制动距离、负转及急停已经实机验收。')
            lines.append('正式实验前须核实连续多圈运动条件；运行中保留反馈/方向/超时/停车保护。')
            QMessageBox.information(self.page,'WK 温补启动前参数检查','\n'.join(lines))
        except Exception as exc:
            QMessageBox.warning(self.page,'温补预检查失败',str(exc))

    def _resume_immutable(self, temperatures, profile, splits=None):
        return {
            'device_sn':self.sn.text().strip(),
            'temperature_model_degree':3,
            'temperature_fit_split':{str(float(temp)):role for temp,role in (splits if splits is not None else temperature_splits(temperatures)).items()},
            'temperature_setpoints_c':temperatures,
            'temperature_schedule_kind':'separate_fit_validation_v1' if splits is not None else 'legacy_automatic_split',
            'fit_temperature_setpoints_c':[v for v in temperatures if splits is not None and splits[v]=='fit'],
            'validation_temperature_setpoints_c':[v for v in temperatures if splits is not None and splits[v]=='validate'],
            'chamber_control':self.chamber_mode.currentData(),
            'gyro_dynamic':bool(self.dynamic.isChecked()),
            'gyro_rate_mode':str(self.gyro_rate_mode.currentData()),
            'quality_profile':profile,
            'gyro_fit_rates_dps':list(self._selected_rates()[0]),
            'gyro_verify_rates_dps':list(self._selected_rates()[1]),
            'gyro_acceleration_dps2':int(self.gyro_accel.value()),
            'chamber_plc_ip':str(tcComm.ip) if self.chamber_mode.currentData()=='plc' else None,
            'return_to_25c_on_success':bool(self.return_ambient.isChecked()),
            'sample_seconds':int(self.sample_seconds.value()),
            'thermal_stability_seconds':int(self.dwell.value()),
            'thermal_gate_mode': ('quick_chip_only' if self.chip_stability_only.isChecked() else
                                  policy_for(str(self.thermal_quality_mode.currentData()))['gate'] if self.chamber_mode.currentData()=='plc' else 'manual_legacy'),
            'pv_initial_band_c':float(self.pv_initial_band.value()),
            'pv_soak_band_c':float(self.pv_soak_band.value()),
            'pv_initial_window_seconds':int(self.pv_initial_seconds.value()),
            'pv_initial_range_c':float(self.pv_initial_range.value()),
            'pv_initial_slope_c_per_min':float(self.pv_initial_slope.value()),
            'pv_final_tolerance_c':float(self.pv_final_tolerance.value()),
            'pv_final_stable_seconds':int(self.pv_final_seconds.value()),
            'thermal_max_quality_holds':int(self.thermal_max_holds.value()),
            'thermal_max_wait_minutes':int(self.thermal_max_wait_minutes.value()),
            'thermal_recovery_wait_minutes':int(self.thermal_recovery_wait_minutes.value()),
            'runtime_temperature_guard_policy':self._runtime_policy_from_ui(),
            'temperature_advance_requires_full_completion':True,
            'chip_stability_window_seconds':60,
            'chip_stability_range_c':policy_for(str(self.thermal_quality_mode.currentData()))['chip_gate_60s_span_c'],
            **({'chip_stability_only_60s':True} if self.chip_stability_only.isChecked() else {}),
            'settle_seconds':int(self.settle.value()),
            'acc_move_speed_dps':float(self.move_speed.value()),
            'axis_model':'outer_x_inner_z',
            'gyro_expected_fs_dps': int(self.expected_gyro_fs.currentData()),
            'imu_sensor_config': {key:value for key,value in self._sensor_config_snapshot().items()
                                  if key != 'gyro_fs_reported_by_mcu'},
        }

    @staticmethod
    def _sensor_config_snapshot():
        # Do not rely on software's default 2000 dps when the chip was changed to 250 dps.
        with tiltSensorRawData.data_lock:
            return {'acc_fs_g':int(tiltSensorRawData.acc_fs),
                    'gyro_fs_dps':int(tiltSensorRawData.gyro_fs),
                    'data_odr':int(tiltSensorRawData.data_odr),
                    'gyro_fs_reported_by_mcu':bool(tiltSensorRawData.gyro_fs_ever_valid)}

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
        # 串口线程允许一次轮询出现空帧；is_data_valid/is_data_available 是瞬时状态，
        # 不可拿来当自动温补每100ms的硬中止条件。必须看最近真实有效帧的时间。
        # 无效帧不会增加 data_update_count，也不会入标定队列。
        if not tiltSensorComm.is_serial_opened:
            raise ValueError('IMU 串口未连接')
        if self.ambient_form._auto_task is not None or self.ambient_form.recording:
            raise ValueError('常温自动任务或原始记录运行中；不能并行启动')
        with tiltSensorRawData.data_lock:
            imu_count = int(tiltSensorRawData.data_update_count)
        last_success = float(getattr(tiltSensorComm, 'last_success_time_sec', 0.0) or 0.0)
        age = time.time() - last_success
        if imu_count <= 0 or not math.isfinite(age) or last_success <= 0.0 or age > 5.0 or age < -1.0:
            raise ValueError('IMU 连续超过5秒没有真实有效的新测量数据，'
                             '或尚未收到有效帧；检查串口、MCU FIFO 与数据采样')

    def _motion_status(self):
        self._valid_device()
        if not np.all(np.isfinite([turntableData.inner_axis_position, turntableData.outer_axis_position,
                                   turntableData.inner_axis_speed, turntableData.outer_axis_speed])):
            raise ValueError('转台反馈包含 NaN/Inf')

    def _stopped(self):
        return abs(turntableData.inner_axis_speed) < 0.05 and abs(turntableData.outer_axis_speed) < 0.05

    @staticmethod
    def _wk_thermal_position_plan(current_angle, target_angle):
        """仅用于 WK 自动温补姿态定位：普通单圈目标，选择最短弧及厂家方向码。"""
        current = float(current_angle)
        target = float(target_angle)
        if (not math.isfinite(current) or not math.isfinite(target)
                or not 0.0 <= current <= 360.0 or not 0.0 <= target <= 360.0):
            raise ValueError('WK 姿态角反馈/目标必须在 0～360° 且为有限值')
        # WK 角位置命令只接受 [0,360)，与手动位置控制一样将 360 规范化为 0。
        current %= 360.0
        target = round(target % 360.0, 4) % 360.0
        clockwise = (target - current) % 360.0
        anticlockwise = (current - target) % 360.0
        return target, (0 if clockwise <= anticlockwise else 1), min(clockwise, anticlockwise)

    def _move(self, inner, outer):
        """WK温补专用有向姿态定位；按已验证的ACC流程分轴发送并确认启动。"""
        if bool(getattr(self.turntable_form, '_speed_limit_tripped', False)):
            raise ValueError('转台超速已触发，禁止温补运动。')
        if not self._stopped():
            raise ValueError('两轴未停车，不允许发送定位命令')
        if not all(math.isfinite(float(v)) and 0 <= float(v) <= 360 for v in (inner, outer)):
            raise ValueError('目标角超出已审核 0–360° 工况范围')
        speed = float(self.move_speed.value())
        if not math.isfinite(speed) or not 0.2 <= speed <= 5.0:
            raise ValueError('温补姿态速度必须为 0.2～5°/s')

        # 先读取两轴状态并生成计划。距离不超过0.2°时视为已在目标附近，
        # 不向该轴发送零转角位置指令，避免无意义指令干扰另一轴的运动启动。
        candidates = []
        skipped = []
        with turntableComm.thread_lock:
            for axis, name, requested in ((INNER_ROTATION_AXIS, '内轴', inner),
                                          (OUTER_ROTATION_AXIS, '外轴', outer)):
                alarm, state, actual, error = [0], [0], [0.0], [0]
                read_ok = wk_comm.twoFDT600WK_getAxisStateInfo(
                    axis, alarm, state, actual, error)
                if not read_ok or alarm[0] != 0 or state[0] != 1:
                    raise RuntimeError(f'WK温补{name}定位前状态不允许运行：'
                                       f'状态={state[0]} 报警={alarm[0]} DLL={error[0]}')
                target, direction, travel = self._wk_thermal_position_plan(actual[0], requested)
                port = wk_comm.axisPorts[axis]
                if not port:
                    raise RuntimeError(f'WK温补{name}没有有效串口')
                if travel <= 0.2:
                    skipped.append((name, actual[0], target, travel))
                    continue
                candidates.append((axis, name, port, requested))

        for name, current, target, travel in skipped:
            self._log(f'温补姿态{name}：当前位置 {current:.4f}°，目标 {target:.4f}°，'
                      f'差值 {travel:.4f}°≤0.2°，跳过无效位置指令')

        func = wk_comm.turntableDll.SetAxisPosition
        func.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint8,
                         ctypes.c_uint16, ctypes.c_float, ctypes.c_float]
        func.restype = ctypes.c_int
        watch = {}
        for index, (axis, name, port, requested) in enumerate(candidates):
            # 与已有ACC自动定位流程保持一致：每轴单独加锁发送，轴间留出100ms。
            # 发送前再次读取本轴状态，避免把旧状态当作当前状态。
            with turntableComm.thread_lock:
                alarm, state, actual, error = [0], [0], [0.0], [0]
                read_ok = wk_comm.twoFDT600WK_getAxisStateInfo(
                    axis, alarm, state, actual, error)
                if not read_ok or alarm[0] != 0 or state[0] != 1:
                    raise RuntimeError(f'WK温补{name}发送位置指令前状态变化：'
                                       f'状态={state[0]} 报警={alarm[0]} DLL={error[0]}')
                target, direction, travel = self._wk_thermal_position_plan(actual[0], requested)
                if travel <= 0.2:
                    self._log(f'温补姿态{name}：发送前已进入目标附近，跳过位置指令')
                    continue
                result = int(func(port, axis, direction, 10, speed, target))
            if result != 0:
                raise RuntimeError(f'WK温补{name}位置指令失败：DLL={result}')

            sent_at = time.monotonic()
            watch[axis] = {
                'name': name,
                'start_angle': float(actual[0]),
                'target': float(target),
                'sent_at': sent_at,
                'started': False,
            }
            self._log(f'温补姿态{name}：{float(actual[0]):.4f}°→{target:.4f}°，'
                      f'{"顺时针" if direction == 0 else "逆时针"} {travel:.4f}°，'
                      f'速度 {speed:g}°/s；DLL返回0，等待控制器确认启动')
            if index < len(candidates) - 1:
                time.sleep(0.1)

        if self.task is not None:
            self.task['position_watch'] = watch
        if not watch and not skipped:
            self._log('温补姿态：两轴均无需运动，跳过位置指令')

    def _check_position_command_started(self, now):
        """DLL返回成功后，短时确认WK已进入位置运动或反馈角度确实变化。"""
        if self.task is None:
            return
        watch = self.task.get('position_watch') or {}
        for axis, spec in watch.items():
            if spec.get('started'):
                continue
            alarm, state, angle, error = [0], [0], [0.0], [0]
            with turntableComm.thread_lock:
                ok = wk_comm.twoFDT600WK_getAxisStateInfo(axis, alarm, state, angle, error)
            elapsed = float(now) - float(spec['sent_at'])
            if not ok:
                raise RuntimeError(f'WK温补{spec["name"]}定位启动确认失败：状态读取DLL={error[0]}')
            if alarm[0] != 0:
                raise RuntimeError(f'WK温补{spec["name"]}定位启动时控制器报警={alarm[0]}')

            current = float(angle[0])
            state_code = int(state[0])
            alarm_code = int(alarm[0])
            moved = abs(_angle_error(current, spec['start_angle'])) > 0.05
            reached = abs(_angle_error(current, spec['target'])) <= 0.2
            axis_speed = (turntableData.inner_axis_speed if axis == INNER_ROTATION_AXIS
                          else turntableData.outer_axis_speed)
            if state_code == 3 or moved or abs(float(axis_speed)) >= 0.05 or reached:
                spec['started'] = True
                self._log(f'温补姿态{spec["name"]}定位启动已确认：状态={state_code}，'
                          f'反馈角度={current:.4f}°，目标={spec["target"]:.4f}°')
                continue
            if state_code != 1 and elapsed >= 0.5:
                raise RuntimeError(f'WK温补{spec["name"]}位置指令后出现非预期状态={state_code}，'
                                   f'报警={alarm_code}，当前角度={current:.4f}°')
            if state_code == 1 and elapsed >= 2.0:
                raise RuntimeError(f'WK温补{spec["name"]}位置指令DLL返回0，但2秒后仍为1#伺服待命，'
                                   f'角度未变化（起始={spec["start_angle"]:.4f}°，'
                                   f'当前={current:.4f}°，目标={spec["target"]:.4f}°）；'
                                   '已提前判定指令未启动，不再空等240秒')

    def _rate_command(self,axis,rate):
        if bool(getattr(self.turntable_form, '_speed_limit_tripped', False)):
            raise ValueError('转台超速已触发，禁止温补运动。')
        if self.task is None or self.task.get('phase') not in ('settle',):
            raise ValueError('非温补动态工况阶段，禁止发送速率指令')
        direction, acceleration, speed = wk_signed_velocity(float(rate), int(self.gyro_accel.value()), axis)
        if not self._stopped():
            raise ValueError('两轴尚未停车，禁止温补速率运动')
        axis_id = INNER_ROTATION_AXIS if axis == 'inner' else OUTER_ROTATION_AXIS
        with turntableComm.thread_lock:
            # 仅温补动态GYRO使用本路径；原WK封装固定 direction=0 不支持负速率。
            alarm, state, actual, error = [0], [0], [0.0], [0]
            ok_state = wk_comm.twoFDT600WK_getAxisStateInfo(axis_id, alarm, state, actual, error)
            if not ok_state or alarm[0] != 0 or state[0] != 1:
                raise RuntimeError(f'WK{axis}未处于1#伺服待命/无报警状态：state={state[0]}, alarm={alarm[0]}, DLL={error[0]}')
            port = wk_comm.axisPorts[axis_id]
            if not port:
                raise RuntimeError(f'WK{axis}尚未设置有效串口')
            func = wk_comm.turntableDll.SetAxisVelocity
            func.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint8,
                             ctypes.c_uint16, ctypes.c_float]
            func.restype = ctypes.c_int
            code = func(port, axis_id, direction, acceleration, speed)
        if code != 0:
            raise RuntimeError(f'WK{axis}动态速率指令失败（DLL={code}，速度={rate:g}°/s）')
        self._wk_rate_guard = {
            'axis':axis, 'last_feedback_count':int(turntableData.update_count),
            'started':time.monotonic()}
        self._log(f'GYRO速率命令：{axis}方向码={direction}，实际传参速率={speed:g}°/s，'
                  f'加速度={acceleration}°/s²，计划签名速率={rate:+g}°/s')

    def _check_rate_feedback(self):
        """速率工况编码器反馈看门狗，不按累计转角限制正常多圈运动。"""
        guard = self._wk_rate_guard
        if guard is None:
            return
        # 设备运行期间必须持续收到真实编码器反馈；无反馈应立即进入异常停车路径。
        if not turntableData.is_turntable_data_available or time.monotonic() - (
                float(turntableData.last_update_monotonic_ns)*1e-9) > 0.75:
            raise ValueError('温补高速工况转台反馈陈旧/无效，发起停车')
        count = int(turntableData.update_count)
        if count == guard['last_feedback_count']:
            if time.monotonic()-guard['started']>0.75:
                raise ValueError('温补速率运动期间编码器反馈未更新，发起停车')
            return
        guard['last_feedback_count'] = count
        guard['started'] = time.monotonic()
        observed_speed = float(turntableData.inner_axis_speed if guard['axis']=='inner'
                               else turntableData.outer_axis_speed)
        if not math.isfinite(observed_speed):
            raise ValueError('速率反馈非有限值，请求停车')

    def _stop_axes(self):
        results=[]
        with turntableComm.thread_lock:
            for axis in (INNER_ROTATION_AXIS,OUTER_ROTATION_AXIS):
                code=[0]
                try: results.append(bool(twoFDT600WK_SetAxisStop(axis,code)))
                except Exception:results.append(False)
        self._wk_rate_guard = None
        return all(results)

    def _wk_stop_confirmed(self, task, now):
        """核实速率段停车完成，防止 8# 停车执行中被误认为 1# 可定位。

        GetStateInfo 返回的是厂家的实机状态。必须有停车指令之后的新编码器反馈，
        两轴速度均接近零，且两轴都连续 0.5s 确认为 1#、无报警。
        8# 只允许等待，不发送使能/位置/速率命令；状态异常由上层安全中止。
        """
        count = int(turntableData.update_count)
        baseline = task.get('stop_feedback_count')
        if baseline is not None and count <= baseline:
            task['stop_ready_since'] = None
            return False, '停车指令之后尚未收到新的转台编码器反馈'
        last_ns = int(getattr(turntableData, 'last_update_monotonic_ns', 0) or 0)
        if last_ns <= 0 or now - last_ns * 1e-9 > 1.0:
            task['stop_ready_since'] = None
            return False, '等待新的转台编码器状态反馈（反馈尚未更新）'

        observed = []
        with turntableComm.thread_lock:
            for axis, label in ((INNER_ROTATION_AXIS, '内轴'),
                                (OUTER_ROTATION_AXIS, '外轴')):
                alarm, state, angle, error = [0], [0], [0.0], [0]
                ok = wk_comm.twoFDT600WK_getAxisStateInfo(
                    axis, alarm, state, angle, error)
                if not ok:
                    task['stop_ready_since'] = None
                    return False, f'{label}控制器停车反馈暂不可用（DLL={error[0]}）'
                if int(alarm[0]) != 0:
                    raise RuntimeError(f'WK停车确认发现{label}报警={alarm[0]}，禁止下一项运动')
                code = int(state[0])
                if code not in (1, 4, 5, 8):
                    raise RuntimeError(f'WK停车后{label}状态={code}，不是可等待的伺服/速率/停车状态；禁止下一项运动')
                observed.append((label, code))

        status = '，'.join(f'{label}={code}#' for label, code in observed)
        if not self._stopped() or any(code != 1 for _, code in observed):
            task['stop_ready_since'] = None
            return False, status + '，等待速度归零且两轴均返回1#伺服待命'
        if task.get('stop_ready_since') is None:
            task['stop_ready_since'] = now
            return False, status + '，正在连续确认1#伺服待命'
        if now - task['stop_ready_since'] < 0.5:
            return False, status + '，等待1#伺服待命持续0.5秒'
        return True, status + '，停车已确认'

    def _begin_wk_stop_wait(self, task, now, retry=False):
        """只在已下发停车指令后调用。下一项不能提前越过厂家8#状态。"""
        task['phase'] = 'wait_stop_retry' if retry else 'wait_stop'
        task['phase_start'] = now
        task['stop_feedback_count'] = int(turntableData.update_count)
        task['stop_ready_since'] = None
        task['stop_wait_last_state'] = None

    def _lock_ui(self, locked):
        for w in (self.production_curve_policy,self.ramp_approval,self.ramp_start_button,self.wk_ambient_start,self.wk_ambient_rebuild,self.wk_ambient_include_gyro,self.wk_ambient_gravity_sign,
                  self.sn,self.fit_temperatures,self.validation_temperatures,self.chamber_mode,self.dwell,self.chip_stability_only,self.thermal_quality_mode,self.sample_seconds,
                  self.production_mode,self.production_batch_id,self.production_load_preset,self.production_clearance,
                  self.pv_initial_seconds,self.pv_initial_range,self.pv_initial_slope,
                  self.pv_final_tolerance,self.pv_final_seconds,
                  self.thermal_max_holds,self.thermal_max_wait_minutes,self.thermal_recovery_wait_minutes,
                  self.pv_initial_band,self.pv_soak_band,
                  self.runtime_pv_follow_final,self.runtime_pv_pause,self.runtime_pv_hold,
                  self.runtime_resoak_pv,self.runtime_resoak_hold,self.runtime_chip_span,
                  self.runtime_chip_span_hold,self.runtime_chip_slope,self.runtime_chip_slope_hold,
                  self.runtime_recovery_pv,self.runtime_recovery_chip_span,self.runtime_recovery_chip_slope,
                  self.settle,self.move_speed,self.dynamic,self.gyro_rate_mode,self.gyro_fit_rates,
                  self.gyro_verify_rates,self.output,self.return_ambient,
                  self.wk_std_low,self.wk_std_high,self.wk_mean_error,
                  self.wk_slope_delta,self.wk_position_residual,
                  self.gyro_accel,self.expected_gyro_fs,self.resume_checkbox,
                  self.resume_directory,self.resume_browse,self.preflight_button):
            w.setEnabled(not locked)
        if not locked:
            self._on_chamber_mode_changed()
            self._on_thermal_mode_changed()
            self._on_gyro_rate_mode_changed()
            self._on_runtime_follow_changed()
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
            if self.chamber_mode.currentData()=='plc' and not (self.task or {}).get('ambient_wk_compare'):
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

    def _start_wk_ambient_comparison(self):
        """Same ambient ACC/GYRO plan and A/B/C reports, with WK-only motion."""
        if self.task is not None:
            QMessageBox.warning(self.page, '任务冲突', '请先结束当前温补/对照任务。')
            return
        with tiltSensorRawData.data_lock:
            chip_temp = float(tiltSensorRawData.temp_c)
        if not math.isfinite(chip_temp):
            QMessageBox.warning(self.page, 'IMU温度无效',
                '芯片温度不是有效有限值。请确认IMU通信与温度传感器，禁止使用错误温度数据。')
            return
        if bool(getattr(tcComm, 'is_connected', False)) and bool(getattr(tcState, 'is_device_fault', False)):
            QMessageBox.warning(self.page, '温箱故障', 'PLC报告温箱故障，不能启动转台对照任务。')
            return
        # Read-only chamber sanity check: never send setpoint or run/stop commands.
        if (bool(getattr(tcComm, 'is_connected', False))
                and bool(getattr(tcData, 'is_tc_data_available', False))):
            pv=float(tcData.pv)
            if not math.isfinite(pv):
                QMessageBox.warning(self.page, '温箱PV无效',
                    'PLC提供的PV不是有效有限值，请检查温箱传感器与通信后再试。')
                return
        include_gyro = self.wk_ambient_include_gyro.isChecked()
        detail = ('ACC 12拟合＋12独立验证；再按旧工艺运行GYRO。' if include_gyro
                  else '只运行ACC 12拟合＋12独立验证；同时输出模长及向量RMSE。')
        reply = QMessageBox.question(self.page, '确认当前WK转台单点温度标定对照',
            f'当前芯片温度 {chip_temp:.2f}℃（记录为本次实测温度标签，不视为温箱SP）。\n{detail}\n'
            '本功能不会操作温箱PLC，也不会自动加热/冷却或停止温箱定值运行。\n'
            '必须现场确认：转台零位与原常温试验一致、IMU安装牢固、该温度已经热平衡、急停可用，'
            '运动全过程有人监护。\n'
            '原有标定系数不会被修改。是否开始？',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:return
        self.start(ambient_diagnostic=True)

    def _r5_effective_scan_direction(self):
        mode=str(self.production_mode.currentData())
        if mode=='combined':return self._r5_cycle['phase'] if self._r5_cycle else 'warming'
        return mode

    def _r5_cycle_manifest(self):
        if not self._r5_cycle:return True
        try:
            write_cycle_manifest(Path(self.output.text().strip()).expanduser().resolve(),self._r5_cycle)
            return True
        except Exception as exc:
            self._log('R5循环审计记录写入失败，禁止自动接续：'+str(exc))
            self._r5_cycle['status']='MANIFEST_WRITE_FAILED'
            return False

    def _r5_begin_second_pass(self):
        cycle=self._r5_cycle
        if not cycle or cycle.get('phase')!='cooling' or self.task is not None:return
        try:
            if not self._stopped():raise ValueError('接续降温前WK两轴停车状态未确认')
            plc=self._require_plc(time.monotonic())
            # R7 writes the cooling target SP directly, without staged arrival.
            # Fresh PLC feedback and physical WK stop have both been checked.
            if not cycle.get('approved') or not self.production_clearance.isChecked():
                raise ValueError('自动接续的操作员现场安全确认已失效')
            self._log('R5自动双向：升温任务完整结束，正在安全接续降温任务')
            self.start()  # all original WK, IMU, PLC, temperature safety checks execute again
            if self.task is None:
                raise ValueError('降温任务未能启动；检查上方启动错误记录')
        except Exception as exc:
            cycle['status']='FAILED_SECOND_START';cycle['reason']=str(exc)
            self._r5_cycle_manifest();self._r5_cycle=None
            self._log('R5接续降温失败，已停止自动流程：'+str(exc))
            QMessageBox.critical(self.page,'自动双向接续失败',str(exc)+
                '\n上位机没有尝试绕过设备安全检查。请现场核查温箱与转台状态。')

    def start(self, ambient_diagnostic=False):
        if self.task is not None:return
        if self._r5_ramp is not None:
            QMessageBox.warning(self.page,'斜坡记录进行中','请先结束斜坡记录，再运行稳态温补实验');return
        # 不复用上一次已关闭的原始文件句柄；启动校验失败时也能安全记录中止。
        self._raw_file=None
        self._raw_jsonl=None
        try:
            self._valid_device()
            if not all(w.isChecked() for w in (self.check_axis,self.check_safe,self.check_sensor)):
                raise ValueError('必须确认全部安全项、坐标系和标定配置')
            if OFFLINE_DEBUG:raise ValueError('禁止在OFFLINE_DEBUG下启动真实温补实验')
            if not self._stopped():raise ValueError('开始前两轴必须静止')
            if ambient_diagnostic:
                # Measured-chip-temperature label only; no chamber setpoint is issued.
                # It is never silently hard-coded to 25℃ on a non-ambient run.
                with tiltSensorRawData.data_lock:
                    comparison_chip_c=float(tiltSensorRawData.temp_c)
                if not math.isfinite(comparison_chip_c):
                    raise ValueError('WK单点标定的芯片温度读数无效')
                comparison_tag_c=round(comparison_chip_c, 3)
                plan={'temperature_setpoints_c':[comparison_tag_c],
                      'fit_temperatures_c':[comparison_tag_c],
                      'validation_temperatures_c':[],
                      'temperature_split':{comparison_tag_c:'fit'}}
                if self.resume_checkbox.isChecked():
                    raise ValueError('常温WK对照必须新建实验，不允许混用温补续做检查点')
            else:
                scan_direction=self._r5_effective_scan_direction()
                if self.production_mode.currentData()=='combined' and self._r5_cycle is None:
                    if self.resume_checkbox.isChecked():
                        raise ValueError('自动双向任务不能从旧单向检查点静默恢复；请用单方向续做功能')
                    self._r5_cycle={'phase':'warming','status':'STARTING',
                                    'batch_id':self.production_batch_id.text().strip(),
                                    'device_sn':self.sn.text().strip(),
                                    'runs':{},'approved':False,
                                    'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}
                if scan_direction in ('warming','cooling'):
                    batch=self.production_batch_id.text().strip()
                    if not batch or any(not(ch.isalnum() or ch in '_-.') for ch in batch):
                        raise ValueError('R4生产扫描须填写相同、安全的批次ID（仅能使用普通文字/数字/下划线）')
                    check_user_hardware_clearance(bool(self.production_clearance.isChecked()),
                        self.chamber_mode.currentData()=='plc',bool(self.chip_stability_only.isChecked()),
                        (str(self.thermal_quality_mode.currentData()) if self.thermal_quality_mode.currentData()=='production_adaptive' else self.thermal_quality_mode.currentData()=='strict'))
                    plan=generate_temperature_plan(scan_direction)
                    if (parse_temperatures(self.fit_temperatures.text())!=plan['fit_temperatures_c'] or
                        parse_temperatures(self.validation_temperatures.text())!=plan['validation_temperatures_c']):
                        raise ValueError('R4生产扫描使用固定5℃独立验证协议；请点“加载方案”，禁止手动改动温度表')
                    expected_fit=tuple(float(x) for x in R4_FIT_RATES)
                    expected_val=tuple(float(x) for x in R4_VERIFY_RATES)
                    if self._selected_rates()!=(expected_fit,expected_val):
                        raise ValueError('R4生产扫描速率必须与冻结方案一致；请重新加载')
                    response=(QMessageBox.Yes if (self._r5_cycle and
                        self._r5_cycle.get('approved') and scan_direction=='cooling') else
                        QMessageBox.warning(self.page,'核实生产扫描物理安全',
                        '准备启动'+('升温−40→85℃' if scan_direction=='warming' else '降温85→−40℃')+
                        '共26个温度点、时间可能极长。确认急停、真实测温、线缆、PCB上电可靠、值守和停机路径均已现场验证？'
                        '\n若温度质量或硬件报警不满足，将记录缺失/终止，绝不将未完成标为通过。',
                        QMessageBox.Yes|QMessageBox.No,QMessageBox.No))
                    if response!=QMessageBox.Yes:
                        raise ValueError('用户未在现场确认高低温安全')
                    if self._r5_cycle:self._r5_cycle['approved']=True
                else:
                    plan=separate_temperature_plan(self.fit_temperatures.text(),self.validation_temperatures.text())
            temperatures=plan['temperature_setpoints_c']
            splits=plan['temperature_split']
            sensor_config=self._sensor_config_snapshot()
            if not ambient_diagnostic and sensor_config['gyro_fs_dps'] != int(self.expected_gyro_fs.currentData()):
                raise ValueError('GYRO 实时数据换算量程为 ±{0} dps，但本次预期 ±{1} dps。'
                                 '请先确认 MCU 实际量程、上位机解析比例及串口状态，不能混用。'.format(
                                  sensor_config['gyro_fs_dps'], self.expected_gyro_fs.currentData()))
            profile=copy.deepcopy(load_profile(str(ROOT)))
            quality_mode=str(self.thermal_quality_mode.currentData())
            thermal_policy=policy_for(quality_mode)
            thermal_policy['runtime']=self._runtime_policy_from_ui()
            # 仅覆盖本次温补的工况副本；常温标定质量配置与速度点完全不改。
            rates_fit,rates_val=(list(profile['rates']['fit_dps']),list(profile['rates']['verify_dps'])) if ambient_diagnostic else self._selected_rates()
            high_speed=max(rates_fit+rates_val)>30.0
            if ambient_diagnostic:
                # Exactly the original ambient profile; do NOT overwrite its
                # nominal temperature limits, rate list or QA thresholds.
                rates_fit=list(profile['rates']['fit_dps'])
                rates_val=list(profile['rates']['verify_dps'])
            else:
                configure_thermal_gyro_profile(profile, fit_rates=rates_fit, verify_rates=rates_val)
            if (self.dynamic.isChecked() and not ambient_diagnostic):
                if high_speed and not self.check_highspeed.isChecked():
                    raise ValueError('拟合或独立验证速率超过30°/s：必须确认WK温箱内线缆、滑环及连续多圈运行安全')
                # 不设置人为累计角度上限；仍在启动前验证两轴速率/加速度参数。
                accel = int(self.gyro_accel.value())
                for rate in rates_fit + rates_val:
                    for axis in ('inner','outer'):
                        wk_signed_velocity(+rate,accel,axis)
                        wk_signed_velocity(-rate,accel,axis)
            if ambient_diagnostic and self.wk_ambient_include_gyro.isChecked():
                for speed in rates_fit+rates_val:
                    for axis in ('inner','outer'):
                        wk_signed_velocity(+speed,int(self.gyro_accel.value()),axis)
                        wk_signed_velocity(-speed,int(self.gyro_accel.value()),axis)
            if ambient_diagnostic:
                # The original ambient profile also had hidden 15～35℃ limits.
                # Replace the 15-35°C ambient restriction with the full plausible
                # instrument research range (-45 to +90°C); keep the original
                # 1℃ within-sample drift gate and
                # 3℃ whole-run spread check, static/rate QA, and all hardware guards.
                profile['quality']['temperature_min_c']=-45.0
                profile['quality']['temperature_max_c']=90.0
            else:
                profile['quality']['temperature_min_c']=-45.0
                profile['quality']['temperature_max_c']=90.0
                profile['quality']['temperature_span_max_c']=0.5
            # Thermal-only, operator-editable independent feedback limits.
            # Ambient quality profile JSON is deliberately NEVER modified.
            if not ambient_diagnostic and self.dynamic.isChecked() and float(self.wk_std_high.value()) > 0.350:
                answer=QMessageBox.warning(
                    self.page, '高速反馈波动上限超过常规试验区间',
                    '你将高速差分测速标准差上限提高到%.3f°/s（超过0.350）。\n'
                    '这可能使真实伺服速度波动被接受。只有在独立核实编码器反馈噪声、转台实际稳速性能、\n'
                    '正反转与停车安全后，才可将该值用于研发试验。\n'
                    '继续后仍保留方向、均速偏差、趋势、位置残差及停车检查；绝非生产批准。\n'
                    '是否确认使用这项经现场核实的研发阈值？' % float(self.wk_std_high.value()),
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                if answer != QMessageBox.Yes:
                    raise ValueError('未确认高于0.350°/s的高速反馈波动实验阈值')
            if not ambient_diagnostic:
                profile['quality']['rate_reference_std_max_dps']=float(self.wk_std_low.value())
                profile['quality']['rate_reference_high_speed_std_max_dps']=float(self.wk_std_high.value())
                profile['quality']['rate_reference_high_speed_start_dps']=25.0
                profile['quality']['rate_reference_error_max_dps']=float(self.wk_mean_error.value())
                profile['quality']['rate_reference_half_slope_difference_max_dps']=float(self.wk_slope_delta.value())
                profile['quality']['rate_reference_position_residual_rms_max_deg']=float(self.wk_position_residual.value())
            # GYRO 参考速度不从指令猜测，而来自转台编码器角度差分。
            if (self.dynamic.isChecked() or (ambient_diagnostic and self.wk_ambient_include_gyro.isChecked())) and not turntableData.is_turntable_data_available:
                raise ValueError('动态温补没有可用的转台反馈测速')
            if not ambient_diagnostic and self.chamber_mode.currentData()=='plc':
                if not self.check_plc.isChecked():
                    raise ValueError('PLC自动控温前必须确认原上位机在本设备上实测设温成功')
                if OFFLINE_DEBUG:raise ValueError('OFFLINE_DEBUG 模式禁止真实自动控温实验')
                current_pv=self._require_plc(time.monotonic())
                if not -45.0 <= float(current_pv['pv']) <= 90.0:
                    raise ValueError('当前温箱PV超出研究操作范围−45～90℃，禁止自动到温')
                first=float(temperatures[0])
                # 直接写目标SP；PLC/WK设备的硬安全、运行状态与新鲜PV仍须确认。
            if not self.sn.text().strip():raise ValueError('PCB 唯一编号必填')
            if ambient_diagnostic:
                all_steps=[{**row,'sensor':'acc','reference_kind':'gravity'}
                           for row in acc_fit_steps()+acc_verify_steps()]
                if self.wk_ambient_include_gyro.isChecked():
                    all_steps.extend({**row,'sensor':'gyro'}
                                     for row in gyro_fit_steps(profile)+gyro_verify_steps(profile))
                steps=[all_steps]
            else:
                all_steps=self._steps(self.dynamic.isChecked(),profile)
                steps=[steps_for_temperature(all_steps,splits[target]) for target in temperatures]
            # Include directional scan batch in immutable resume fingerprint.
            # The physical passes are separate folders; no duplicate temp/step keys.
            immutable=({'experiment_kind':'wk_ambient_comparison',
                        'device_sn':self.sn.text().strip(),
                        'original_ambient_profile':profile,
                        'axis_model':'outer_x_inner_z',
                        'gravity_sign':int(self.wk_ambient_gravity_sign.currentData()),
                        'step_ids':[r['step_id'] for r in all_steps]}
                       if ambient_diagnostic else self._resume_immutable(temperatures,profile,splits))
            if not ambient_diagnostic:
                direction=scan_direction
                if direction in ('warming','cooling'):
                    immutable['production_scan_direction']=direction
                    immutable['production_protocol']=R4_PROTOCOL
                    immutable['production_batch_id']=self.production_batch_id.text().strip()
            resume_state=None
            continuing=self.resume_checkbox.isChecked()
            if continuing:
                name=self.resume_directory.text().strip()
                if not name:raise ValueError('请选择需要续做的 THERM_ 实验目录')
                folder=Path(name).expanduser().resolve()
                if not folder.is_dir():raise ValueError('续做实验目录不存在')
                if not folder.name.startswith('THERM_'):
                    raise ValueError('续做目录必须为原程序创建的 THERM_... 目录')
                config=json.loads((folder/'experiment_config.json').read_text(encoding='utf-8'))
                checkpoint=json.loads((folder/'temperature_measurements.json').read_text(encoding='utf-8'))
                resume_state=validate_resume(config,checkpoint,immutable,temperatures,steps)
                validate_appendable_raw_files(folder,len(resume_state['rows']))
            else:
                folder=Path(self.output.text().strip()).expanduser().resolve()/((
                    'WK_AMBIENT_COMPARE_' if ambient_diagnostic else 'THERM_')+datetime.datetime.now().strftime('%Y%m%d_%H%M%S'))
                folder.mkdir(parents=True,exist_ok=False)
            recovered_rows=resume_state['rows'] if resume_state else []
            recovered_events=resume_state['events'] if resume_state else []
            recovered_count=resume_state['frame_count'] if resume_state else 0
            recovered_temp=resume_state['temp_index'] if resume_state else 0
            recovered_step=resume_state['step_index'] if resume_state else 0
            restored_progress=resume_state.get('task_progress',{}) if resume_state else {}
            if not ambient_diagnostic and restored_progress.get('thermal_auto_skipped_temperatures'):
                raise ValueError('旧任务已经自动跳过温度点：不能在禁止跳点的新工艺下直接续接；请先按缺失清单处理该批次。')
            # Preserve original run config and raw units; never overwrite ambient calibration.
            self.task={'run_dir':str(folder),'device_sn':self.sn.text().strip(),
                'temps':temperatures,'temp_i':recovered_temp,
                'steps_by_temperature':steps,
                'steps':steps[recovered_temp] if recovered_temp<len(temperatures) else [],'step_i':0,
                'resume_temp_index':recovered_temp if continuing else None,
                'resume_step_index':recovered_step if continuing else 0,
                'rows':list(recovered_rows), 'events':list(recovered_events),
                'profile':profile,'phase':'next_temperature',
                'phase_start':time.monotonic(),'stable_since':None,'frames':[],
                'frame_count':recovered_count,'last_frame':None,'chip_trace':[], 'retry_count':0,
                'baseline_config':(tiltSensorRawData.acc_fs,tiltSensorRawData.gyro_fs,tiltSensorRawData.data_odr),
                'last_imu_count':int(tiltSensorRawData.data_update_count),'last_imu_change':time.monotonic(),
                'ambient_wk_compare':bool(ambient_diagnostic),
                'gravity_sign':int(self.wk_ambient_gravity_sign.currentData()) if ambient_diagnostic else 1,
                'dynamic':(self.wk_ambient_include_gyro.isChecked() if ambient_diagnostic else self.dynamic.isChecked()),
                'manual':bool(ambient_diagnostic or self.chamber_mode.currentData()=='manual'),
                'chip_stability_only':False if ambient_diagnostic else self.chip_stability_only.isChecked(),
                'temperature_quality_mode':quality_mode,
                'chip_gate_60s_span_c':float(thermal_policy['chip_gate_60s_span_c']),
                'chip_5min_slope_gate_c_per_min':thermal_policy['chip_5min_slope_gate_c_per_min'],
                'temperature_group_warnings':list(restored_progress.get('temperature_group_warnings',[])),
                'temperature_group_audit':list(restored_progress.get('temperature_group_audit',[])),
                'ui_max_progress':int(restored_progress.get('ui_max_progress',0)),
                'thermal_gate_mode':('wk_ambient_no_plc_no_soak' if ambient_diagnostic else
                    ('quick_chip_only' if self.chip_stability_only.isChecked() else
                      thermal_policy['gate'] if self.chamber_mode.currentData()=='plc' else 'manual_legacy')),
                'pv_initial_band_c':float(self.pv_initial_band.value()),
                'pv_soak_band_c':float(self.pv_soak_band.value()),
                'pv_initial_seconds':int(self.pv_initial_seconds.value()),
                'pv_initial_range_c':float(self.pv_initial_range.value()),
                'pv_initial_slope_c_per_min':float(self.pv_initial_slope.value()),
                'pv_final_tolerance_c':float(self.pv_final_tolerance.value()),
                'pv_final_seconds':int(self.pv_final_seconds.value()),
                'pv_initial_trace':[], 'pv_initial_since':None, 'pv_initial_last_update':None,
                'pv_final_trace':[], 'pv_final_last_update':None,
                'thermal_elapsed_s':0.0, 'thermal_last_tick':None, 'thermal_pv_in_range':False,
                'temperature_wait_started':None,
                'thermal_max_quality_holds':int(self.thermal_max_holds.value()),
                'thermal_max_wait_minutes':int(self.thermal_max_wait_minutes.value()),
                'thermal_recovery_wait_minutes':int(self.thermal_recovery_wait_minutes.value()),
                'runtime_temperature_guard_policy':dict(thermal_policy['runtime']),
                'thermal_auto_skipped_temperatures':list(restored_progress.get('thermal_auto_skipped_temperatures',[])),
                'return_ambient':False if ambient_diagnostic else (
                    False if self._r5_cycle and scan_direction=='warming'
                    else self.return_ambient.isChecked()),
                'manual_confirmed_pv':comparison_chip_c if ambient_diagnostic else None,
                'axis_model':'outer_x_inner_z', 'thermal_gyro_acceleration_dps2':int(self.gyro_accel.value()),
                'temperature_split_by_setpoint':splits,
                'production_scan_direction':(scan_direction if not ambient_diagnostic else 'legacy'),
                'deferred_by_temp':dict(restored_progress.get('deferred_by_temp',{})),
                'replay_mode':bool(restored_progress.get('replay_mode',False)),
                'replay_queue':list(restored_progress.get('replay_queue',[])),
                'unresolved':list(restored_progress.get('unresolved',[])),
                'hold_count':int(restored_progress.get('thermal_hold_count',0)),
                'thermal_holds_per_temp':dict(restored_progress.get('thermal_holds_per_temp',{})),
                'thermal_recovery_seconds':120.0,
                'group_rechecks':dict(restored_progress.get('group_rechecks',{})),
                'guard':None,'rate_preflight_feedback':[], 'rate_sample_feedback':[]}
            if not continuing:
                atomic_write_json(folder/'experiment_config.json', {
                    'resume_schema_version':RESUME_SCHEMA,
                    'resume_immutable_config':immutable,
                    'device_sn':self.task['device_sn'],'temperature_setpoints_c':temperatures,
                    'fit_temperature_setpoints_c':plan['fit_temperatures_c'],
                    'validation_temperature_setpoints_c':plan['validation_temperatures_c'],
                    'temperature_schedule_kind':'wk_single_ambient_12_fit_12_validation_v1' if ambient_diagnostic else 'separate_fit_validation_v1',
                    'experiment_kind':'wk_ambient_comparison' if ambient_diagnostic else 'thermal_compensation',
                    'gravity_sign':self.task['gravity_sign'],
                    'reference_turntable_model':'2FDT600WK' if ambient_diagnostic else None,
                    'original_ambient_math_and_plan':bool(ambient_diagnostic),
                    'temperature_split':self.task['temperature_split_by_setpoint'],
                    'steps_per_temperature':[len(part) for part in steps],
                    'wk_comparison_measured_chip_tag_c':comparison_tag_c if ambient_diagnostic else None,
                    'wk_comparison_temperature_policy':'-45 to +90C measured chip plausibility range; keep original within-step and whole-run stability limits' if ambient_diagnostic else None,
                    'gyro_expected_full_scale_dps':int(self.expected_gyro_fs.currentData()),
                    'imu_sensor_config':sensor_config,
                    'temperature_polynomial_degree':3,
                    'thermal_stability_mode':('wk_ambient_no_plc_no_soak' if ambient_diagnostic else
                        ('quick_chip_only' if self.chip_stability_only.isChecked() else
                          thermal_policy['gate'] if self.chamber_mode.currentData()=='plc' else 'manual_legacy')),
                    'temperature_quality_mode':quality_mode,
                    'thermal_auto_failure_policy':{'version':'no_auto_skip_safe_abort_v2',
                        'temperature_quality_holds_limit':int(self.thermal_max_holds.value()),
                        'temperature_wait_limit_minutes':int(self.thermal_max_wait_minutes.value()),
                        'temperature_recovery_wait_limit_minutes':int(self.thermal_recovery_wait_minutes.value()),
                        'on_limit':'SAFE_ABORT_AND_SAVE_INCOMPLETE_NO_NEXT_TEMPERATURE',
                        'hardware_faults_never_auto_skipped':True,
                        'incomplete_steps_not_marked_accepted':True},
                    'thermal_policy_snapshot':thermal_policy,
                    'thermal_stability_seconds':int(self.dwell.value()),
                    'plc_setpoint_plan':{
                        'mode':'DIRECT_TARGET_SP_WITH_READBACK',
                        'no_intermediate_sp_stages':True,
                        'uses_existing_plc_sp_commands':True,
                        'physical_ramp_rate_managed_by_chamber':True},
                    'pv_initial_band_c':float(self.pv_initial_band.value()),
                    'pv_soak_band_c':float(self.pv_soak_band.value()),
                    'pv_initial_window_seconds':int(self.pv_initial_seconds.value()),
                    'pv_initial_range_c':float(self.pv_initial_range.value()),
                    'pv_initial_slope_c_per_min':float(self.pv_initial_slope.value()),
                    'pv_final_tolerance_c':float(self.pv_final_tolerance.value()),
                    'pv_final_stable_seconds':int(self.pv_final_seconds.value()),
                    'chip_stability_window_seconds':60,
                    'chip_stability_range_c':thermal_policy['chip_gate_60s_span_c'],
                    'runtime_temperature_guard_policy': {
                        'version': 'R6_GUI_CONFIGURED_FROZEN_RUNTIME_GUARD',
                        **thermal_policy['runtime'],
                        'explanation':'研发连续/严格恒温两种模式均保留PLC告警、IMU数据新鲜度、逐工况QA和真实停车确认'},
                    'temperature_plan_note': 'independent_holdout_tests_only_with_separate_temperature_inputs',
                    'axis_model_confirmed_by_operator':True,'chamber_control':('UNCHANGED_NO_PLC_COMMANDS' if ambient_diagnostic else self.chamber_mode.currentData()),
                    'gyro_dynamic':self.task['dynamic'],'quality_profile':profile,
                    'gyro_fit_rates_dps':list(rates_fit),'gyro_verify_rates_dps':list(rates_val),
                    'gyro_rate_mode':self.gyro_rate_mode.currentData(),
                    'gyro_acceleration_dps2':int(self.gyro_accel.value()),
                    'chamber_control_verified_by_operator':False if ambient_diagnostic else self.check_plc.isChecked(),
                    'chamber_plc_ip':None if ambient_diagnostic else (str(tcComm.ip) if self.chamber_mode.currentData()=='plc' else None),
                    'return_to_25c_on_success':False if ambient_diagnostic else bool(
                        (not self._r5_cycle or scan_direction=='cooling') and self.return_ambient.isChecked()),
                    'production_release':False,
                    'production_scan_direction':(scan_direction if not ambient_diagnostic else 'legacy'),
                    'production_protocol':(R4_PROTOCOL if not ambient_diagnostic and scan_direction in ('warming','cooling') else 'legacy'),
                    'production_automation':('R5_ONE_CLICK_TWO_INDEPENDENT_RUNS' if self._r5_cycle else 'manual'),
                    'production_batch_id':(self.production_batch_id.text().strip() if not ambient_diagnostic and scan_direction in ('warming','cooling') else '')})
            self._raw_file=(folder/'imu_frame_means.csv').open('a' if continuing else 'w',
                                                               newline='',encoding='utf-8' if continuing else 'utf-8-sig')
            self._raw_writer=csv.writer(self._raw_file)
            self._raw_jsonl=(folder/'imu_full_frames.jsonl').open('a' if continuing else 'w',encoding='utf-8')
            if not continuing:
                self._raw_writer.writerow(['utc','target_temp_c','step','frame_update_count','imu_temp_c',
                    'chamber_pv_c','inner_deg','outer_deg','inner_rate_dps','outer_rate_dps',
                    'acc_x_g','acc_y_g','acc_z_g','gyro_x_dps','gyro_y_dps','gyro_z_dps','feedback_age_ms'])
            self._feedback_jsonl=(folder/'wk_independent_position_feedback.jsonl').open(
                'a' if continuing else 'w',encoding='utf-8')
            turntable_feedback_queue_set(True,clear=True)
            tilt_sensor_calibration_queue_set(True,clear=True)
            self._lock_ui(True)
            self.start_button.setEnabled(False);self.stop_button.setEnabled(True)
            if self._r5_cycle:
                self._r5_cycle['runs'][scan_direction]=str(folder)
                self._r5_cycle['status']='RUNNING_'+scan_direction.upper()
                if not self._r5_cycle_manifest():
                    raise ValueError('循环审计状态无法写入磁盘，禁止开启未追溯的自动实验')
            self._log(('续做未完成实验，已完成工况 '+str(len(recovered_rows))+' 项：' if continuing else '任务已启动：')+str(folder))
            self._log(f'本次选择{len(temperatures)}个温度点：{temperatures}；'
                      f'拟合温度={plan["fit_temperatures_c"]}（完整工况）；独立验证温度={plan["validation_temperatures_c"]}（仅测试）；实测GYRO量程±{sensor_config["gyro_fs_dps"]} dps；'
                      f'MCU报告确认={sensor_config["gyro_fs_reported_by_mcu"]}')
            if not sensor_config['gyro_fs_reported_by_mcu']:
                self._log('警告：MCU未明确报告GYRO量程；本次仅供研发，不可作为正式发布参数。')
            self._log('温补GYRO多速率拟合：'+str(rates_fit)+'；独立验证：'+str(rates_val))
            self._log('转台独立测速质检（本实验自定义）：低速差分σ≤{:.3f}°/s、≥25°/s差分σ≤{:.3f}°/s、'
                      '平均速度偏差≤{:.3f}°/s、半段斜率差≤{:.3f}°/s、位置残差RMS≤{:.3f}°。'.format(
                          self.wk_std_low.value(),self.wk_std_high.value(),self.wk_mean_error.value(),
                          self.wk_slope_delta.value(),self.wk_position_residual.value()))
            self._log('温度策略='+quality_mode+'；'+thermal_policy['description']+'；运行期门槛='+str(thermal_policy['runtime'])+
                      '；生产严格不跳温/不跳步骤；暂停次数上限='+str(self.thermal_max_holds.value())+
                      '；温度等待上限='+str(self.thermal_max_wait_minutes.value())+'分钟；恢复等待上限='+
                      str(self.thermal_recovery_wait_minutes.value())+'分钟；达到上限则安全中止，保留数据与续做断点')
            if not ambient_diagnostic and not self.task['manual']:
                self._log('本次采用PLC直接目标SP：每个温度点一次写入目标值并核验SP/运行状态；'
                          '不设置中间SP步长；到温及热浸期间WK保持停车，PLC硬安全保护不受影响。')
            if ambient_diagnostic:
                self._log('WK常温IMU对照：不操作温箱PLC，不执行热浸；复用常温12+12姿态、原始常温质检与A/B/C报告；含GYRO='+str(self.task['dynamic']))
            if self.task['chip_stability_only'] and not ambient_diagnostic:
                self._log('温度模式=快速流程测试：PLC PV在目标±1℃连续30秒后，芯片60秒真实新帧范围≤0.2℃即开始；跳过正式共同热平衡和最终PV精确稳定检查。')
            elif self.task['manual'] and not ambient_diagnostic:
                self._log(f'温度模式=人工设温：人工确认到温后共同热平衡{self.dwell.value()}秒，并检查芯片最近60秒波动≤0.2℃；不执行连续PLC PV趋势门槛。')
            elif not ambient_diagnostic:
                self._log('温度模式=PLC：初步PV±{:.2f}℃连续观察{}秒（极差≤{:.2f}℃、斜率≤{:.3f}℃/min），热浸{}秒（PV±{:.2f}℃内有效累计），最终PV±{:.2f}℃连续{}秒，芯片60秒稳定。'.format(
                    self.pv_initial_band.value(),self.pv_initial_seconds.value(),
                    self.pv_initial_range.value(),self.pv_initial_slope.value(),
                    self.dwell.value(),self.pv_soak_band.value(),
                    self.pv_final_tolerance.value(),self.pv_final_seconds.value()))
            # 在任何转台/PLC运动前记录初始检查点；首次工况失败同样可以续做。
            self._save_partial('RUNNING','实验已启动；等待首个温度/恢复温度确认')
            self._tick()
        except Exception as exc:
            if self.task is not None:self._abort('启动失败：'+str(exc))
            else:
                if self._r5_cycle and self._r5_cycle.get('phase')=='warming':
                    self._r5_cycle['status']='FAILED_FIRST_START';self._r5_cycle['reason']=str(exc)
                    self._r5_cycle_manifest();self._r5_cycle=None
                QMessageBox.warning(self.page,'未能启动温补',str(exc))

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

    def _request_final_stop(self, now, reason):
        """Successful completion requires real 1# servo standstill confirmation."""
        t=self.task
        if not self._stop_axes():
            raise ValueError('任务结束WK停车命令失败，请立即现场处理')
        self._begin_wk_stop_wait(t,now)
        t['phase']='final_stop_wait'
        t['finish_success_reason']=reason
        self._log('采集流程结束；正在确认WK两轴已真实停车，尚未标记实验完成')

    def _begin_chamber_shutdown(self, now):
        """Request STOP in the original PLC API, then verify new RUN readbacks.

        No control action or status inference may be simulated here.
        The chamber's supply power is NOT switched off by this operation.
        """
        t=self.task
        if t.get('manual'):
            t['plc_stop_confirmed']=False
            self._finish(True,t['finish_success_reason']+'；人工温箱需现场手动停止')
            return
        if not t.get('final_stop_confirmed'):
            raise RuntimeError('WK实际停车未确认，禁止将任务标记完成')
        t['plc_stop_requested']=True
        t['plc_stop_confirmed']=False
        t['plc_stop_command_ok']=False
        t['plc_stop_command_time']=now
        try:
            with tcComm.thread_lock:
                t['plc_stop_command_ok']=bool(tc_fixed_value_stop()) if tcComm.is_connected else False
        except Exception as e:
            t['chamber_stop_error']=str(e)
        t['plc_stop_command_time']=time.monotonic()  # only AFTER the PLC write attempt
        t['phase']='verify_chamber_stop'
        t['phase_start']=t['plc_stop_command_time']
        self._save_partial('RUNNING','已结束采集和确认WK停车；正在验证PLC定值停机')
        self._log('结束阶段PLC停止定值运行命令：'+str(t['plc_stop_command_ok'])+
                  '；等待新鲜的定值运行/设备运行反馈，非电源断电')
        if not t['plc_stop_command_ok']:
            self._finish(True,t['finish_success_reason']+'；PLC停止命令失败，必须现场检查温箱')

    def _step_key(self, temp_index, step_index):
        t=self.task
        return (float(t['temps'][temp_index]),
                t['steps_by_temperature'][temp_index][step_index]['step_id'])

    def _accepted_step_keys(self):
        return {(float(r['temperature_target_c']),r['step_id']) for r in self.task['rows']}

    def _next_step_after_result(self, now):
        """Advance one planned position, or the next one-off deferred retry."""
        t=self.task
        t['retry_count']=0
        if t.get('replay_mode'):
            queue=t.get('replay_queue',[])
            t['step_i']=queue.pop(0) if queue else len(t['steps'])
        else:
            t['step_i']+=1
        t['phase']='position';t['phase_start']=now

    def _defer_current_step(self, now, reason):
        """Only quality/steady-speed failures reach here; motor/PLC faults abort."""
        t=self.task
        step=t['steps'][t['step_i']]
        entry={'temp_index':int(t['temp_i']),'step_index':int(t['step_i']),
               'temperature_target_c':float(t['temps'][t['temp_i']]),
               'step_id':step['step_id'],'sensor':step['sensor'],
               'rotation_axis':step.get('rotation_axis'),
               'target_rate_dps':step.get('target_rate_dps'),'reason':str(reason)}
        if t.get('replay_mode'):
            t['unresolved'].append(entry)
            self._log('补测仍不合格，列入缺失清单：'+str(entry['step_id'])+'；'+str(reason))
        else:
            by_temp=t['deferred_by_temp'].setdefault(str(t['temp_i']),[])
            if t['step_i'] not in by_temp:
                by_temp.append(t['step_i'])
            self._log('本工况重试耗尽，已记入本温度末尾待补测：'+step['step_id']+'；'+str(reason))
        t['retry_count']=0
        t['frames']=[]
        t.pop('pending_dynamic_row',None)
        if not t.get('ambient_wk_compare'):
            # R6: even the individual condition may not be silently skipped.
            self._halt_incomplete_temperature('工况 '+step['step_id']+' 多次质检仍失败：'+str(reason))
            return
        # Legacy ambient diagnostic retains its separate deferred workflow.
        # Dynamic segments cannot be skipped until both axes are ACTUALLY stopped.
        if step['mode']=='rate':
            if not self._stop_axes():
                raise ValueError('质量失败后停车命令失败：必须现场安全中止')
            self._begin_wk_stop_wait(t,now)
            t['phase']='wait_stop_defer'
        else:
            self._next_step_after_result(now)
            self._save_partial('RUNNING','待补测：'+step['step_id'])

    @staticmethod
    def _thermal_recovery_seconds(hold_count_this_temperature):
        """Back off after repeated drift, never restart every few seconds."""
        return (120.0, 180.0, 300.0, 600.0)[min(
            max(int(hold_count_this_temperature)-1, 0), 3)]

    def _rearm_thermal_hold(self):
        """Operator-approved retry from a latched, safely stopped thermal hold.

        This cannot bypass the 120 s post-stop recovery window, or change a
        machine fault into a recoverable temperature-quality event.
        """
        t = self.task
        if t is None or t.get('phase') != 'thermal_operator_hold':
            return
        try:
            now = time.monotonic()
            if not self._stopped():
                raise ValueError('WK尚未真实停车，禁止解除温漂暂停')
            self._require_plc(now)
            if t.get('guard') is None:
                t['guard'] = self._new_guard()
            t['guard'].begin_recovery(now)
            # Explicit operator intervention resets the per-temperature
            # rearm budget, not the total history retained in the report.
            t.setdefault('thermal_holds_per_temp', {})[str(t['temp_i'])] = 0
            t['thermal_recovery_seconds'] = 300.0
            t['phase'] = 'thermal_pause'
            t['phase_start'] = now
            self.rearm_thermal_button.setEnabled(False)
            self._log('操作员确认恢复：WK已静止，开始全新300秒温度恢复观察；此前数据不清空')
            self._save_partial('RUNNING', '人工确认后重新等待温漂稳定')
        except Exception as exc:
            QMessageBox.warning(self.page, '无法解除温漂暂停', str(exc))

    def _start_temperature_hold(self, now, reason, full_soak=False):
        t=self.task
        if t.get('phase') in ('wait_stop_thermal','thermal_pause','thermal_operator_hold'):
            return
        per_temp=t.setdefault('thermal_holds_per_temp',{})
        index=str(t['temp_i'])
        per_temp[index]=int(per_temp.get(index,0))+1
        t['thermal_recovery_seconds']=(max(300.0,self._thermal_recovery_seconds(per_temp[index]))
                                       if t.get('temperature_quality_mode') in ('continuous','production_adaptive') else
                                       self._thermal_recovery_seconds(per_temp[index]))
        t['hold_requires_soak']=bool(full_soak)
        t['hold_reason']=str(reason)
        t['hold_count']=int(t.get('hold_count',0))+1
        t['frames']=[]
        t.pop('pending_dynamic_row',None)
        self._log('温度质量暂停（工况不提交）：'+str(reason)+'；开始WK停车确认，不清空已接受工况')
        if not self._stop_axes():
            raise ValueError('温漂暂停停车命令发送失败')
        self._begin_wk_stop_wait(t,now)
        t['phase']='wait_stop_thermal'

    def _audit_current_temperature_groups(self):
        """R7: an entire group is still required; its across-pose die-T span
        is informational, never a reason to delete accepted pose records.

        Every condition has its own measured chip-temperature mean, and all
        complete FIT poses across FIT temperatures jointly identify ONE
        temperature-dependent matrix. This does not waive per-condition
        quality checks or permit skipped/missing steps.
        """
        t=self.task
        if t is None or t.get('ambient_wk_compare'):
            return False
        i=t['temp_i']
        temp=float(t['temps'][i])
        groups={}
        for row in t['rows']:
            if float(row['temperature_target_c'])==temp:
                groups.setdefault((row['sensor'],row['split']),[]).append(row)
        changed=False
        audit=t.setdefault('temperature_group_audit',[])
        for (sensor,split),rows in groups.items():
            if len(rows)<2:
                continue
            key=f'{i}:{sensor}:{split}'
            if any(item.get('key')==key for item in audit):
                continue
            measured=[float(row['temperature_mean_c']) for row in rows]
            span=max(measured)-min(measured)
            item={'key':key,'temperature_target_c':temp,'sensor':sensor,'split':split,
                  'chip_min_c':min(measured),'chip_max_c':max(measured),
                  'chip_span_c':round(span,6),'count':len(rows),
                  'decision':'KEEP_ACCEPTED_CONDITIONS_JOINT_FIT_PER_CONDITION_T',
                  'note':'组温差仅记录不作废；要求所有姿态完整，逐工况T进入同一套矩阵拟合'}
            audit.append(item)
            for row in rows:
                row['group_temperature_span_c']=round(span,6)
                row['group_temperature_audit']='INFO_ONLY_NOT_AN_INVALIDATION'
            self._log(f'{temp:g}℃ {sensor}/{split}完整工况组：'
                      f'{len(rows)}项，芯片实际均温从{min(measured):.3f}到{max(measured):.3f}℃，'
                      f'跨姿态温差{span:.3f}℃；保留全部已通过单工况质检的记录，'
                      '不按0.6℃或2℃整组作废。模型使用每工况实测芯片均温。')
            changed=True
        if changed:
            self._save_partial('RUNNING','完整组温度跨度存档（不作为组拒收条件）')
        return False

    def _skip_current_temperature_for_quality(self, now, reason):
        """Compatibility entry point: a production run MUST NEVER auto-skip."""
        self._halt_incomplete_temperature(reason)
        return
    def _halt_incomplete_temperature(self, reason):
        # Abort handles real WK stop verification, PLC stop request and the
        # INCOMPLETE checkpoint; never increment the temperature index.
        t=self.task
        if t is None:return
        temp=(t['temps'][t['temp_i']] if t['temp_i']<len(t['temps']) else '?')
        self._log(f'{temp}℃温度质量无法恢复：{reason}；禁止自动跳温，保留已接受工况和续做数据，安全中止整场实验')
        self._abort(f'{temp}℃工况未完整，禁止自动跳温；{reason}')

    def _advance_temperature(self, now):
        t=self.task
        if t['temp_i']<len(t['temps']):
            from thermal_production_quality import missing_at_temperature
            missing=missing_at_temperature(t['temps'][t['temp_i']],
                t['steps_by_temperature'][t['temp_i']],t['rows'])
            if missing:
                self._halt_incomplete_temperature(
                    f'本温度仍有{len(missing)}项未通过质检：'+', '.join(missing[:5]))
                return
        t['temp_i']+=1
        t['step_i']=0
        t['replay_mode']=False
        t['replay_queue']=[]
        t['guard']=None
        t['phase']='next_temperature';t['phase_start']=now
        t['steps']=(t['steps_by_temperature'][t['temp_i']]
                    if t['temp_i']<len(t['temps']) else [])
        self._save_partial('RUNNING','当前温度全部工况通过，已进入下一温度')

    def _wk_rate_quality_arguments(self, target_rate_dps):
        """Immutable experiment-local limits, selected by absolute target speed."""
        q=self.task['profile']['quality']
        high=abs(float(target_rate_dps))>=float(q.get('rate_reference_high_speed_start_dps',25.0))
        return {'max_error':float(q['rate_reference_error_max_dps']),
                'max_std':float(q.get('rate_reference_high_speed_std_max_dps',q['rate_reference_std_max_dps'])
                                if high else q['rate_reference_std_max_dps']),
                'max_slope_difference':float(q.get('rate_reference_half_slope_difference_max_dps',0.36)),
                'max_position_residual_rms':float(q.get('rate_reference_position_residual_rms_max_deg',0.35))}

    def _poll_reference_feedback(self):
        t=self.task
        # Collect each independent controller poll, not each repeated IMU frame.
        for _ in range(500):
            try:sample=turntable_feedback_get_nowait()
            except queue.Empty:break
            if not sample.get('monotonic_time_ns'):
                continue
            phase=t.get('phase')
            if phase in ('wait_rate','sample'):
                if phase=='sample' and (int(sample['monotonic_time_ns'])
                        < int(float(t.get('sample_start',0))*1e9)):
                    continue
                target='rate_preflight_feedback' if phase=='wait_rate' else 'rate_sample_feedback'
                t.setdefault(target,[]).append(sample)
                if phase=='wait_rate':
                    cutoff=time.perf_counter_ns()-10_000_000_000
                    t[target]=[x for x in t[target] if int(x['monotonic_time_ns'])>=cutoff]
            if self._feedback_jsonl:
                data={'temp_c':float(t['temps'][t['temp_i']]) if t['temp_i']<len(t['temps']) else None,
                      'phase':phase,'step_id':(t['steps'][t['step_i']]['step_id']
                         if t['step_i']<len(t['steps']) else None), 'feedback':sample}
                self._feedback_jsonl.write(json.dumps(data,ensure_ascii=False)+'\n')

    def _save_partial(self, status, reason):
        t=self.task
        if not t:return
        folder=Path(t['run_dir'])
        # 先确保原始帧落盘，再原子提交“已确认完成”的统计工况。
        for obj in (self._raw_file,self._raw_jsonl,getattr(self,'_feedback_jsonl',None)):
            if obj:
                obj.flush()
                os.fsync(obj.fileno())
        checkpoint={'status':status,'reason':reason,'device_sn':t['device_sn'],
            'rows':t['rows'],'events':t['events'],'imu_frame_count':t['frame_count'],
            'imu_queue_drops':tilt_sensor_calibration_queue_drop_count_get(),
            'task_progress':{'temp_index':t['temp_i'],'step_index':t['step_i'],
                'replay_mode':bool(t.get('replay_mode')),'replay_queue':list(t.get('replay_queue',[])),
                'deferred_by_temp':t.get('deferred_by_temp',{}),
                'unresolved':t.get('unresolved',[]),'thermal_hold_count':t.get('hold_count',0),
                'thermal_holds_per_temp':t.get('thermal_holds_per_temp',{}),
                'group_rechecks':t.get('group_rechecks',{}),
                'temperature_group_warnings':t.get('temperature_group_warnings',[]),
                'temperature_group_audit':t.get('temperature_group_audit',[]),
                'thermal_auto_skipped_temperatures':t.get('thermal_auto_skipped_temperatures',[]),
                'ui_max_progress':t.get('ui_max_progress',0)},
            'thermal_quality_mode':t.get('temperature_quality_mode','strict'),
            'chamber_shutdown':{'requested':bool(t.get('plc_stop_requested')),
                                'command_ok':bool(t.get('plc_stop_command_ok')),
                                'confirmed':bool(t.get('plc_stop_confirmed')),
                                'manual_mode':bool(t.get('manual'))}}
        # 先写CSV临时文件，再提交JSON检查点；断电时最多丢失最近未提交的一步。
        csv_path=folder/'temperature_measurements.csv'
        csv_tmp=folder/'temperature_measurements.csv.new'
        with csv_tmp.open('w',newline='',encoding='utf-8-sig') as f:
            w=csv.writer(f)
            w.writerow(['target_temperature_c','temperature_split','step_id','sensor','mode','split',
                        'target_rate_dps','rotation_axis','temperature_mean_c',
                        'reference_x','reference_y','reference_z','measured_x','measured_y','measured_z','accepted_frames'])
            for row in t['rows']:
                measure=row.get('acc_raw_mean_g') if row['sensor']=='acc' else row.get('gyro_raw_mean_dps')
                w.writerow([row['temperature_target_c'],row['temperature_split'],row['step_id'],row['sensor'],
                            row['mode'],row['split'],row.get('target_rate_dps'),row.get('rotation_axis'),
                            row['temperature_mean_c'],*row['reference'],*measure,row['accepted_frames']])
            f.flush();os.fsync(f.fileno())
        os.replace(csv_tmp,csv_path)
        atomic_write_json(folder/'temperature_measurements.json',checkpoint)

    def _finish_wk_ambient_comparison(self, success, reason, stopped, incomplete):
        """Isolate ambient A/B/C reporting from all thermal 28-model outputs."""
        t=self.task
        root=Path(t['run_dir'])
        accepted={(float(r['temperature_target_c']),r['step_id']) for r in t['rows']}
        missing=[step['step_id'] for step in t['steps_by_temperature'][0]
                 if (float(t['temps'][0]),step['step_id']) not in accepted]
        status='COMPLETED' if success and stopped and t.get('final_stop_confirmed') and not (incomplete or missing) else 'INCOMPLETE'
        try:
            self._save_partial(status,reason)
            atomic_write_json(root/'wk_ambient_run_status.json',{
                'status':status,'reason':reason,'device_sn':t['device_sn'],
                'accepted_count':len(t['rows']), 'planned_count':len(t['steps_by_temperature'][0]),
                'missing_step_ids':missing, 'wk_stop_confirmed':bool(t.get('final_stop_confirmed')),
                'chamber_plc_touched':False,'production_release':False,
                'measured_temperature_tag_c':float(t['temps'][0])})
            if status=='COMPLETED':
                try:
                    from wk_ambient_comparison import export_ambient_comparison
                    report,paths=export_ambient_comparison(root,t['rows'],t['profile'],
                        axis_model=t['axis_model'],gravity_sign=t['gravity_sign'],
                        device_serial=t['device_sn'],include_gyro=t['dynamic'])
                    for sensor,res in report['models'].items():
                        self._log('WK单点温度对照 '+sensor.upper()+': '+res['status']+
                                  '；三方案候选='+str(res.get('candidate_model')))
                    self._log('WK单点A/B/C：拟合/独立验证/模长/向量RMSE报告已输出：'+str(root))
                    self.selection_result.setText('WK单点三方案拟合与验证报告：'+str(root))
                except Exception as exc:
                    self._log('WK常温对照报告生成失败（原始数据已保存）：'+repr(exc))
                    self.selection_result.setText('WK常温对照报告失败：'+repr(exc))
            else:
                self._log(f'WK常温对照未完整：已接受{len(t["rows"])}，缺失{len(missing)}；'
                          '不生成虚假的完整A/B/C结论，原始检查点已保留。')
        finally:
            tilt_sensor_calibration_queue_set(False)
            turntable_feedback_queue_set(False)
            self._lock_ui(False)
            self.start_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.rearm_thermal_button.setEnabled(False)
            self.confirm_temp.setEnabled(False)
            self.task=None
            for obj in (getattr(self,'_raw_file',None),getattr(self,'_raw_jsonl',None),
                        getattr(self,'_feedback_jsonl',None)):
                try:
                    if obj:obj.close()
                except Exception:pass
            self.label.setText('WK单点对照完成；查看拟合/验证A/B/C和模长RMSE：'+str(root)
                if status=='COMPLETED' else 'WK常温对照中止/不完整：'+reason)
            if not t.get('final_stop_confirmed'):
                QMessageBox.warning(self.page,'WK停车确认',
                    '本任务未获得明确的正常结束停车标志。请现场确认两轴确已停车；'
                    '绝不能把发送停车命令等同于伺服安全状态。')

    def _finish(self, success, reason):
        t=self.task
        if t is None:return
        stopped=(True if t.get('final_stop_confirmed') else self._stop_axes())
        # Final completion is never confused with data completeness.
        # Never let an abort/automatic quality skip reach the end with an
        # empty missing list merely because retry bookkeeping was interrupted.
        registered={(int(x['temp_index']),int(x['step_index']))
                    for x in t.get('unresolved',[]) if 'temp_index' in x and 'step_index' in x}
        for entry in missing_planned_conditions(t.get('temps',[]),
                t.get('steps_by_temperature',[]),t.get('rows',[])):
            key=(entry['temp_index'],entry['step_index'])
            if key not in registered:
                t.setdefault('unresolved',[]).append(entry)
                registered.add(key)
        incomplete=bool(t.get('unresolved'))
        if t.get('ambient_wk_compare'):
            self._finish_wk_ambient_comparison(success,reason,stopped,incomplete)
            return
        # Compute COMPLETENESS against the actual plan, never only the retry list.
        # Equipment aborts and auto-skips must still produce an honest readiness audit.
        readiness=build_result_readiness(
            t.get('temps',[]),t.get('steps_by_temperature',[]),t.get('rows',[]),
            t.get('temperature_split_by_setpoint',{}),
            auto_skipped=t.get('thermal_auto_skipped_temperatures',[]))
        if readiness['total_missing']:
            incomplete=True
        if success and incomplete:
            reason=reason+f'；缺失{len(t["unresolved"])}项，已生成待补测报告，禁止正式模型推荐'
        if not success and not t['manual'] and not t.get('plc_stop_requested'):
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
            if t.get('thermal_auto_skipped_temperatures'):
                # Auto-skipped work must always be visible separately from
                # accepted data.  This report is NOT a release certificate.
                atomic_write_json(Path(t['run_dir'])/'thermal_auto_skip_summary.json',{
                    'production_release':False,
                    'policy':'quality_only_after_confirmed_stationary',
                    'skipped_temperatures':t['thermal_auto_skipped_temperatures'],
                    'unresolved_condition_count':len(t.get('unresolved',[])),
                    'unresolved_conditions':t.get('unresolved',[]),
                    'accepted_condition_count':len(t.get('rows',[])),
                    'note':'自动跳温不代表此温度合格；需按缺失项重新采集并重新评估28套模型'})
            if t.get('temperature_group_warnings'):
                atomic_write_json(Path(t['run_dir'])/'temperature_group_quality_warnings.json',
                                  {'mode':t.get('temperature_quality_mode'),
                                   'production_release':False,
                                   'warnings':t['temperature_group_warnings']})
            if t.get('temperature_group_audit'):
                atomic_write_json(Path(t['run_dir'])/'temperature_group_chip_temperature_audit.json',
                                  {'mode':t.get('temperature_quality_mode'),
                                   'not_a_release_certificate':True,
                                   'policy':'record_all_group_spans_without_0p6_or_2C_rejection',
                                   'groups':t['temperature_group_audit']})
            self._log('结束：'+reason+'；温箱定值停机确认='+str(t.get('plc_stop_confirmed',False))+'；WK实际停车状态'+
                      ('已确认' if t.get('final_stop_confirmed') else
                       '仅已发送停车指令，尚未获得真实状态确认' if stopped else
                       '停车指令失败（需现场硬件急停）'))
            status=('PARTIAL_COMPLETED' if incomplete else 'COMPLETED') if success and stopped else 'INCOMPLETE'
            self._save_partial(status,reason)
            try:
                write_result_readiness(t['run_dir'],readiness,experiment_status=status)
                self._log('已生成逐传感器温补结果可用性检查：thermal_result_readiness.json / .md')
            except Exception as readiness_exc:
                self._log('结果可用性审计导出失败：'+str(readiness_exc))
            if incomplete:
                export_incomplete_xlsx(t['run_dir'],t['rows'],t['unresolved'],t['temps'],reason)
                self._log('数据不完整，已输出thermal_incomplete_data_report.xlsx；不得视为28套模型验证通过')
                # Do not waste valid ACC data just because a GYRO dynamic
                # segment failed, or vice versa. Evaluate ONLY sensors whose
                # entire planned fit+validation grid was accepted. Keep the
                # research-only output in a conspicuously separate directory.
                accepted=self._accepted_step_keys()
                fully_complete=[]
                for sensor in ('acc','gyro'):
                    if sensor=='gyro' and not t['dynamic']:continue
                    planned={(float(temp),step['step_id'])
                             for temp,steps in zip(t['temps'],t['steps_by_temperature'])
                             for step in steps if step['sensor']==sensor}
                    if planned and planned.issubset(accepted):fully_complete.append(sensor)
                if fully_complete:
                    try:
                        subfolder=Path(t['run_dir'])/'PARTIAL_ONLY_COMPLETE_SENSORS_RESEARCH'
                        subfolder.mkdir(exist_ok=True)
                        sensors=tuple(fully_complete)
                        reported=publish_sensor_reports(
                            subfolder,t['rows'],t['temps'],sensors,source_folder=t['run_dir'],
                            quality_warnings=t.get('temperature_group_warnings',[]))
                        self.selection_result.setText('独立完整传感器研发报告：'+
                            '；'.join(f'{sensor.upper()} {v.get("selected_id") or "无"} / '
                                     f'{v.get("status_text",v.get("status"))}'
                                     for sensor,v in reported['selection']['sensors'].items()))
                        atomic_write_json(subfolder/'NOT_FOR_RELEASE.json',{
                            'status':'PARTIAL_OTHER_SENSOR_MISSING','complete_sensors':fully_complete,
                            'production_release':False,'warning':'另一传感器存在缺失工况，禁止整机生产放行'})
                        self._log('已保留完整传感器的单独研发分析：'+', '.join(fully_complete)+
                                  '；仍须补齐所有缺失工况才允许整机最终验收')
                    except Exception as partial_exc:
                        self._log('部分传感器研发分析失败（原始数据与缺失报告已保留）：'+str(partial_exc))
                # Even when NEITHER sensor is 100% complete, always attempt a
                # separate research-only PREVIEW with honest status and counts.
                # Missing independent holdout or insufficient fit rows leads to
                # NOT_EVALUATED; no coefficients or fake acceptance are created.
                preview_sensors=tuple(sensor for sensor in ('acc','gyro')
                    if (sensor=='acc' or t['dynamic'])
                    and sensor not in fully_complete)
                if preview_sensors:
                    try:
                        preview_folder=Path(t['run_dir'])/'PARTIAL_INCOMPLETE_SENSORS_RESEARCH'
                        preview_folder.mkdir(exist_ok=True)
                        output=publish_sensor_reports(
                            preview_folder,t['rows'],t['temps'],preview_sensors,
                            source_folder=t['run_dir'],
                            quality_warnings=t.get('temperature_group_warnings',[]))
                        atomic_write_json(preview_folder/'INCOMPLETE_DATA_NOT_FOR_RELEASE.json',{
                            'production_release':False,
                            'status':'PARTIAL_RESEARCH_ONLY',
                            'sensors':list(preview_sensors),
                            'completion':{s:readiness['sensors'][s] for s in preview_sensors},
                            'model_statuses':{s:output['selection']['sensors'].get(s,{}) .get('status')
                                              for s in preview_sensors},
                            'warning':'模型可拟合不等于全温覆盖或独立验证合格；缺失工况禁止当作合格'})
                        self._log('部分数据28模型研发预览已生成（不代表全部工况合格）：'
                                  +str(preview_folder))
                    except Exception as preview_exc:
                        self._log('部分数据模型预览不可用：'+str(preview_exc)
                                  +'；缺失情况及原始数据已保留')
            if success and stopped and not incomplete:
                # Candidate fitting cannot overwrite or replace ambient data.
                sensors=('acc','gyro') if t['dynamic'] else ('acc',)
                try:
                    report=publish_sensor_reports(t['run_dir'],t['rows'],t['temps'],sensors,
                                                  source_folder=t['run_dir'],
                                                  quality_warnings=t.get('temperature_group_warnings',[]))
                    info='；'.join(f'{sensor.upper()} {v.get("selected_id") or "无"} / '
                                  f'{v.get("status_text",v.get("status"))}'
                                  for sensor,v in report['selection']['sensors'].items())
                    self.selection_result.setText('28候选模型独立报告（研发）：'+info)
                    self._log('已生成ACC/GYRO独立报告及28套结构/系数明细：'+report['combined_workbook'])
                except Exception as selection_exc:
                    self.selection_result.setText('模型报告生成失败：'+str(selection_exc))
                    self._log(self.selection_result.text()+'；原始帧与检查点仍保留')
                # Legacy cubic is purely diagnostic and must never gate 28 models.
                try:
                    save_variable_models(t['run_dir'],t['rows'],t['temps'],sensors)
                except Exception as legacy_exc:
                    self._log('旧版三次诊断拟合不可用（不影响28模型报告）：'+str(legacy_exc))
                try:
                    save_optional_gyro_bias(t['run_dir'],t['rows'],t['temps'])
                except ValueError as exc:self._log('GYRO静态偏置拟合不通过：'+str(exc))
        finally:
            # Do not auto-start a new motion unless first pass COMPLETED and
            # genuine WK standstill + fresh PLC stopped feedback were verified.
            cycle=self._r5_cycle
            next_action=None
            if cycle and not t.get('ambient_wk_compare'):
                verdict=decide_transition(cycle['phase'],bool(success),bool(stopped),
                             bool(not incomplete),bool(t.get('final_stop_confirmed')),
                             bool(t.get('plc_stop_confirmed')))
                cycle['status']=verdict['status']
                cycle['reason']=str(reason)
                cycle['runs'][cycle['phase']]=str(t['run_dir'])
                if verdict['action']=='next':
                    cycle['phase']='cooling'
                    next_action='cooling'
                elif verdict['action']=='analyze':
                    next_action='analyze'
                else:
                    self._log('R5自动双向流程停止：'+verdict['reason'])
                if not self._r5_cycle_manifest():
                    next_action=None
                    self._log('R5循环状态保存失败；绝不继续自动运动或生成完整报告')
                    self._r5_cycle=None
                elif verdict['action']=='halt':self._r5_cycle=None
            tilt_sensor_calibration_queue_set(False)
            turntable_feedback_queue_set(False)
            self._lock_ui(False)
            self.start_button.setEnabled(True);self.stop_button.setEnabled(False)
            self.rearm_thermal_button.setEnabled(False)
            self.confirm_temp.setEnabled(False)
            self.task=None
            for obj in (getattr(self,'_raw_file',None),getattr(self,'_raw_jsonl',None),getattr(self,'_feedback_jsonl',None)):
                try:
                    if obj:obj.close()
                except Exception:pass
            self.label.setText(('采集部分完成：有待补测工况，见缺失报告' if incomplete else
                '采集已完成（仅研发候选，见报告）') if success and stopped else '中止/未完成：'+reason)
            if not t.get('manual') and not t.get('plc_stop_confirmed'):
                self.label.setText(self.label.text()+'；温箱定值运行停止未获PLC确认，必须现场检查！')
                QMessageBox.warning(self.page,'温箱停止未确认',
                    '实验采集状态已经保存，但没有PLC新鲜读数证明温箱定值运行已停止。'
                    '请立即在原温箱面板确认并按厂家程序安全停机；不要理解为自动断电。')
            if not stopped:
                QMessageBox.critical(self.page,'停车未确认','软件停车命令失败，请立即使用现场硬件急停并排查')
            if next_action=='cooling':
                # Call from the Qt event loop *after* task handles were closed.
                QTimer.singleShot(1000,self._r5_begin_second_pass)
            elif next_action=='analyze':
                self._log('R5双向采集已完成，自动启动同批次统一曲线及独立验证分析')
                self._r5_cycle=None
                QTimer.singleShot(1000,lambda: self._run_r5_analysis_from_folder(
                    str(Path(self.output.text().strip()).expanduser().resolve())))

    def _abort(self,reason):
        t=self.task
        if t is None or t.get('phase')=='abort_stop_wait':return
        # Stop chamber control immediately on failure; NEVER assume its actual
        # heater/refrigerator state from an accepted PLC command alone.
        if not t['manual']:
            try:
                with tcComm.thread_lock:
                    ok=bool(tc_fixed_value_stop()) if tcComm.is_connected else False
                t['plc_stop_requested']=True
                t['plc_stop_command_ok']=ok
                self._log('故障中止PLC停止请求='+str(ok)+'；须在温箱现场确认真实状态')
            except Exception as exc:
                self._log('PLC停止请求失败：'+str(exc)+'，必须现场核查')
        if not self._stop_axes():
            self._finish(False,reason+'；WK停车命令失败')
            return
        self._begin_wk_stop_wait(t,time.monotonic())
        t['phase']='abort_stop_wait'
        t['abort_reason']=reason
        self.label.setText('安全中止停车确认中；请现场监护WK两轴和温箱')


    def _start_r5_ramp(self):
        if self.task is not None or self._r5_ramp is not None:
            QMessageBox.warning(self.page,'运行冲突','稳态实验或斜坡记录尚未结束');return
        try:
            if not self.ramp_approval.isChecked():raise ValueError('请先现场确认温箱斜坡程序、WK停车和人员值守')
            self._valid_device()
            if not self._stopped():raise ValueError('WK两轴必须真实停车，禁止在转动时评价静态温漂')
            snap=self._require_plc(time.monotonic())
            batch=self.production_batch_id.text().strip();sn=self.sn.text().strip()
            if not batch or not sn or any(not(x.isalnum() or x in '_-.') for x in batch):
                raise ValueError('请填写本次稳态实验相同的批次ID和PCB编号')
            folder=Path(self.output.text().strip()).expanduser().resolve()
            folder.mkdir(parents=True,exist_ok=True)
            name='R5_RAMP_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.csv'
            path=folder/name
            handle=path.open('x',newline='',encoding='utf-8-sig')
            writer=csv.DictWriter(handle,fieldnames=R5_RAMP_FIELDS);writer.writeheader()
            self._r5_ramp={'file':handle,'writer':writer,'path':str(path),
                           'last_counter':-1,'last_sample':0.,'last_new':time.monotonic(),
                           'count':0,'sn':sn,'batch':batch,'last_plc_pv':snap['pv']}
            self._lock_ui(True)
            self.start_button.setEnabled(False);self.ramp_stop_button.setEnabled(True)
            self.ramp_info.setText('正在记录真实芯片温度、PLC PV、6轴新帧和WK停车状态：'+str(path))
            self._log('R5独立斜坡记录已开启（无PLC设温或WK运动命令）：'+str(path))
        except Exception as e:
            QMessageBox.warning(self.page,'无法启动斜坡记录',str(e))

    def _stop_r5_ramp(self,reason='用户结束斜坡记录'):
        recorder=self._r5_ramp
        if recorder is None:return
        self._r5_ramp=None
        try:
            recorder['file'].flush();os.fsync(recorder['file'].fileno())
            recorder['file'].close()
        finally:
            self._lock_ui(False);self.start_button.setEnabled(True)
            self.ramp_stop_button.setEnabled(False)
            self.ramp_info.setText(f'斜坡记录结束，共{recorder["count"]}条：'+recorder['path']+'；'+reason)
            self._log(self.ramp_info.text())

    def _r5_ramp_tick(self):
        r=self._r5_ramp
        if r is None:return
        now=time.monotonic()
        if now-r['last_sample']<1.0:return
        try:
            if not self._stopped():raise ValueError('WK停车条件失效，斜坡记录中止')
            snap=self._require_plc(now)
            with tiltSensorRawData.data_lock:
                count=int(tiltSensorRawData.data_update_count)
                valid=bool(tiltSensorRawData.is_data_valid)
                temp=float(tiltSensorRawData.temp_c)
                acc=np.asarray(tiltSensorRawData.acc_g_arr,float).copy()
                gyro=np.asarray(tiltSensorRawData.gyr_dps_arr,float).copy()
            if count==r['last_counter']:
                if now-r['last_new']>5:raise ValueError('IMU数据超过5秒没有新帧')
                return
            if not valid or acc.ndim!=2 or gyro.ndim!=2 or acc.shape[1:]!=(3,) or gyro.shape[1:]!=(3,):
                raise ValueError('IMU帧无效或六轴数据缺失')
            if not math.isfinite(temp) or not np.all(np.isfinite(acc)) or not np.all(np.isfinite(gyro)):
                raise ValueError('芯片温度/六轴测量含非有限数值')
            a=np.mean(acc,axis=0);g=np.mean(gyro,axis=0)
            values={'unix_s':time.time(),'chip_c':temp,'pv_c':float(snap['pv']),
                    'acc_x_g':a[0],'acc_y_g':a[1],'acc_z_g':a[2],
                    'gyro_x_dps':g[0],'gyro_y_dps':g[1],'gyro_z_dps':g[2],
                    'frame_count':count,'wk_stopped_confirmed':True,
                    'device_sn':r['sn'],'batch_id':r['batch']}
            r['writer'].writerow(values)
            r['last_counter']=count;r['last_sample']=now;r['last_new']=now
            r['count']+=1
            if r['count']%10==0:
                r['file'].flush()
                self.ramp_info.setText(f'斜坡正在记录：{r["count"]}条；芯片{temp:.2f}℃，PLC PV {snap["pv"]:.2f}℃。'
                                       ' 仅记录，不控制温箱斜坡。')
        except Exception as e:
            self._stop_r5_ramp('异常终止：'+str(e))
            QMessageBox.critical(self.page,'斜坡记录中断',str(e)+
                '\n请确认温箱厂家斜坡程序是否需要在设备面板停止；上位机未向PLC发送未知命令。')

    def _tick(self):
        t=self.task
        if t is None:
            if self._r5_ramp is not None:self._r5_ramp_tick()
            return
        now=time.monotonic()
        # Controlled emergency stop must not be blocked by missing PLC/IMU
        # feedback that originally triggered the abort.
        if t.get('phase')=='abort_stop_wait':
            try:
                ready,detail=self._wk_stop_confirmed(t,now)
                if ready:
                    t['final_stop_confirmed']=True
                    self._finish(False,t.get('abort_reason','安全中止'))
                    return
                if now-t['phase_start']>30:
                    self._finish(False,t.get('abort_reason','安全中止')+
                                 '；30秒内未确认实际停车，必须现场急停')
                    return
                self.label.setText('WK停车确认中：'+detail)
            except Exception as exc:
                self._finish(False,t.get('abort_reason','安全中止')+
                             '；停车状态无法确认：'+str(exc))
            return
        if t.get('phase')=='verify_chamber_stop':
            # No more sampling is underway.  IMU disconnects or changed
            # setpoints must not prevent saving completed data and an honest
            # chamber-stop status.  Only a *fresh* PLC stop readback confirms.
            try:
                snap=self._require_plc(time.monotonic())
                if (float(snap['started_updated'])>float(t.get('plc_stop_command_time',0))
                        and float(snap['run_updated'])>float(t.get('plc_stop_command_time',0))
                        and not bool(snap['fixed_started']) and not bool(snap['running'])):
                    t['plc_stop_confirmed']=True
                    self._log('PLC实际停止已确认：新的定值启动/设备运行反馈都为False；未切断主电源')
                    self._finish(True,t['finish_success_reason']+'；PLC定值停机回读已确认')
                    return
            except Exception as e:
                if not t.get('chamber_stop_feedback_warned'):
                    self._log('温箱停机回读暂不可用：'+str(e)+'；不得视为已经停止')
                    t['chamber_stop_feedback_warned']=True
            if now-t['phase_start']>90.0:
                self._finish(True,t['finish_success_reason']+'；无法确认PLC停止定值运行，必须现场检查')
            else:
                self.label.setText('WK已停车；正在核对温箱定值停止状态（未确认前不要无人值守）')
            return
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
            if getattr(self,'_feedback_jsonl',None) is not None:
                self._poll_reference_feedback()
                if turntable_feedback_queue_drop_count_get()>0:
                    raise ValueError('WK独立编码器反馈队列溢出，拒绝用缺失参考数据标定')
            self._collect()
            if not t['manual']:
                chamber=self._require_plc(now)
                # PLC采集线程可能刚好在本tick取now之后刷新PV时间戳；以快照之后的时刻作为状态机时刻。
                now=time.monotonic()
                target=t['temps'][t['temp_i']] if t['temp_i']<len(t['temps']) else None
                if target is not None and t['phase'] not in ('next_temperature','verify_plc_sp'):
                    require_setpoint_ack(chamber,target)
            # A quality pause is NOT a safety abort. Global motor/PLC/IMU faults
            # above are still hard errors. No new samples are accepted during hold.
            running_phases=('position','wait_position','settle','wait_rate','sample')
            if not t['manual'] and not t.get('chip_stability_only') and t['phase'] in running_phases:
                if t.get('guard') is None:
                    t['guard']=self._new_guard()
                with tiltSensorRawData.data_lock:
                    chip_now=float(tiltSensorRawData.temp_c)
                    chip_count_now=int(tiltSensorRawData.data_update_count)
                if t.get('temperature_quality_mode') in ('continuous','production_adaptive'):
                    deviation=abs(float(chamber['pv'])-float(t['temps'][t['temp_i']]))
                    active=bool(t.get('pv_quality_warning_active'))
                    if deviation>0.75 and not active:
                        t['pv_quality_warning_active']=True
                        self._log(f'研发连续模式温箱PV短时偏离{deviation:.2f}℃：只记录质量预警；'
                                  '超过更高限值且持续才会停车，单工况温度质检仍执行')
                    elif deviation<=0.5 and active:
                        t['pv_quality_warning_active']=False
                action,thermal_reason=t['guard'].observe(now,float(chamber['pv']),
                    float(chamber['pv_updated']),chip_now,chip_count_now)
                if action=='safety':
                    raise ValueError('温度传感器不可信：'+thermal_reason)
                if action=='resoak' or (action=='hold' and t['phase'] not in ('position','wait_position')):
                    self._start_temperature_hold(now,thermal_reason,action=='resoak')
                    return
                # ACC定位运动中的短期温度起伏不是有效采样段。
                # 非严重软报警留给停止后的settle阶段再判断，避免在转台运动途中频繁停车。
            # A temperature that cannot settle is a missing calibration point,
            # not automatically a motor/PLC hardware fault.  Limit how long the
            # PLC's staged quality gates may occupy the entire run. Machine
            # faults, stale PLC feedback and physical stop errors already
            # raise/abort ABOVE this block and are never skipped.
            if (not t['manual'] and t['phase'] in
                    ('wait_plc','thermal_soak','final_stability','thermal_stability')):
                started=t.get('temperature_wait_started')
                limit=60.0*float(t.get('thermal_max_wait_minutes',120))
                if started is not None and now-float(started)>=limit:
                    self._halt_incomplete_temperature(
                        f'到温/保温/稳定等待累计超过{limit/60:g}分钟')
                    return
            if t['phase']=='next_temperature':
                if t['temp_i']>=len(t['temps']):
                    if not t['manual'] and t['return_ambient']:
                        self._issue_plc_setpoint(25.0)
                        t['phase']='verify_return'
                        t['phase_start']=now
                        t['pv_stable_since']=None
                        self._log('全部工况已完成：PLC自动回温25℃，等待SP回读和PV稳定后结束')
                        return
                    self._request_final_stop(now,'全部温度点与独立验证采集完成（人工模式或未启用自动回25℃）')
                    return
                if not self._stopped():raise ValueError('换温前两轴未静止')
                # On resume, don't re-heat and re-soak already complete setpoints.
                needed=({self._step_key(t['temp_i'],i)
                          for i in range(len(t['steps_by_temperature'][t['temp_i']]))}
                        if 'steps_by_temperature' in t else None)
                if needed and needed.issubset(self._accepted_step_keys()):
                    self._log(f'恢复运行：温度{t["temps"][t["temp_i"]]}℃全部工况已完成，跳过重复热浸')
                    self._advance_temperature(now)
                    return
                target=t['temps'][t['temp_i']]
                if 'steps_by_temperature' in t:
                    t['steps']=t['steps_by_temperature'][t['temp_i']]
                if t.get('ambient_wk_compare'):
                    t['phase']='position'
                    t['step_i']=0
                    self._log('WK常温对照：直接进入12+12原常温姿态；不操作PLC/无温箱到温按钮')
                elif not t['manual']:
                    # Direct target SP (never emit any intermediate setpoint).
                    # Still require fresh PLC status/readback and WK stopped.
                    self._require_plc(now)
                    self._issue_plc_setpoint(target)
                    t['phase']='verify_plc_sp'
                    self._log(f'已通过原PLC驱动请求设温 {target}℃；等待SP回读及运行状态确认')
                else:
                    t['phase']='wait_manual'
                    self._log(f'请在原温箱控制面板手工设为 {target}℃，读取实测 PV 并输入，达到目标后点击确认。不会自动发送未知 RS232 指令。')
                t['phase_start']=now
                self.confirm_temp.setEnabled(t['manual'] and not t.get('ambient_wk_compare'))
            elif t['phase']=='final_stop_wait':
                ready, detail=self._wk_stop_confirmed(t,now)
                if ready:
                    t['final_stop_confirmed']=True
                    self._begin_chamber_shutdown(now)
                    return
                if now-t['phase_start']>30:
                    raise ValueError('结束阶段30秒未确认WK两轴1#待命，请现场检查：'+detail)
                self.label.setText('结束前WK真实停车确认：'+detail)
                return
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
                        self._request_final_stop(now,'全部温补工况完成，并已自动回到25℃±1℃持续30秒')
                        return
                else:t['pv_stable_since']=None
                # Optional return-to-ambient is not an unlimited waiting loop.
                # For this 5..40 C development range, issue an audited stop
                # request after a bounded wait; never claim 25 C was reached.
                if now-t['phase_start']>=3600.0:
                    pv_return=float(chamber['pv'])
                    if not 0.0<=pv_return<=45.0:
                        raise ValueError('自动回温超时且温箱PV不在0~45℃可审计停机区间；'
                                         '需要现场按厂家程序处理，不能假称安全回温')
                    t['return_ambient_unconfirmed']=True
                    self._log('自动回25℃超过60分钟仍未满足25±1℃连续30秒；'
                              '当前PV='+f'{pv_return:.2f}℃；将尝试PLC停止定值运行并记录回温未完成')
                    self._request_final_stop(now,
                        f'全部采集结束，但自动回25℃超过60分钟未完成（PV={pv_return:.2f}℃）；'
                        '已请求PLC定值停止，须查看停机回读及厂家停机要求')
                    return
                if now-t['phase_start']>21600:
                    raise ValueError('结束回25℃超时6小时')
            elif t['phase']=='wait_plc':
                if tcState.is_device_fault or not tcData.is_tc_data_available or not tcComm.is_connected:
                    raise ValueError('PLC温箱故障或通信丢失')
                pv=float(chamber['pv'])
                target=float(t['temps'][t['temp_i']])
                pv_stamp=min(float(chamber['pv_updated']),now)
                pv_age=now-pv_stamp
                pv_fresh=(0.0<=pv_age<=2.0)
                if t.get('chip_stability_only',False):
                    # 旧快速流程保留：PV±1℃连续30秒后，仅检查芯片60秒稳定。
                    if pv_fresh and abs(pv-target)<=1.0+1e-9:
                        if t.get('pv_stable_since') is None:t['pv_stable_since']=now
                        if now-t['pv_stable_since']>=30.0:
                            t['phase']='thermal_stability';t['phase_start']=now;t['chip_trace']=[]
                            t['last_chip_trace_count']=None
                            self._log('快速模式：PLC实时PV连续30秒在目标±1℃内，开始芯片60秒稳定检查（正式热浸已跳过）')
                    elif pv_fresh:
                        t['pv_stable_since']=None
                    self.label.setText(f'快速模式：等待温箱PV进入 {target:.2f}±1.00℃，当前PV={pv:.2f}℃'+
                                       ('' if pv_fresh else '（等待新鲜PV反馈）'))
                else:
                    # 正式PLC模式：进入±1℃只开启5分钟观察窗；还需极差与线性趋势同时合格。
                    if pv_fresh and abs(pv-target)<=float(t.get('pv_initial_band_c',1.0))+1e-9:
                        if t.get('pv_initial_since') is None:
                            t['pv_initial_since']=now
                            t['pv_initial_trace']=[]
                            t['pv_initial_last_update']=None
                            self._log(f'温箱PV首次进入目标±{(1.5 if t.get('temperature_quality_mode') in ('continuous','production_adaptive') else 1.0):.2f}℃，开始初步稳定观察：{target:.2f}℃')
                        if pv_stamp>float(t.get('pv_initial_last_update') or 0.0):
                            t['pv_initial_trace'].append((pv_stamp,pv))
                            t['pv_initial_last_update']=pv_stamp
                        window=float(t['pv_initial_seconds'])
                        t['pv_initial_trace']=[x for x in t['pv_initial_trace'] if now-x[0]<=window+20.0]
                        pv_stable,covered,pv_span,pv_slope=chamber_stability_status(
                            t['pv_initial_trace'],now,window_seconds=window,
                            max_range_c=t['pv_initial_range_c'],
                            max_abs_slope_c_per_min=t['pv_initial_slope_c_per_min'])
                        observed=max(0.0,now-float(t['pv_initial_since']))
                        self.label.setText(
                            f'初步到温观察：{observed:.0f}/{window:.0f}s；PV={pv:.2f}℃；'
                            f'窗口覆盖={covered:.0f}s；极差={pv_span:.3f}/{t["pv_initial_range_c"]:.2f}℃；'
                            f'斜率={pv_slope:+.3f}/{t["pv_initial_slope_c_per_min"]:.3f}℃/min')
                        if observed>=window and pv_stable:
                            t['phase']='thermal_soak';t['phase_start']=now
                            t['thermal_elapsed_s']=0.0;t['thermal_last_tick']=now;t['thermal_pv_in_range']=True
                            t['chip_trace']=[];t['last_chip_trace_count']=None
                            self._log(f'初步温箱稳定通过：窗口极差={pv_span:.3f}℃、斜率={pv_slope:+.3f}℃/min；开始共同热平衡计时')
                    elif pv_fresh:
                        if t.get('pv_initial_since') is not None:
                            self._log(f'初步到温观察重置：PV={pv:.2f}℃已离开目标温度许可范围')
                        t['pv_initial_since']=None;t['pv_initial_trace']=[];t['pv_initial_last_update']=None
                        self.label.setText(f'等待温箱初步到温：目标 {target:.2f}±{t.get("pv_initial_band_c",1.0):.2f}℃，当前PV={pv:.2f}℃')
                    else:
                        self.label.setText(f'初步到温观察：等待新鲜PLC PV反馈（当前反馈年龄{pv_age:.1f}s）')
                wait_start=float(t.get('temperature_wait_started') or t['phase_start'])
                if now-wait_start>21600:raise ValueError('温箱初步到温/稳定等待超时 6 小时')
            elif t['phase']=='thermal_soak':
                if not self._stopped():raise ValueError('共同热平衡阶段转台发生运动')
                pv=float(chamber['pv']);target=float(t['temps'][t['temp_i']])
                pv_age=now-min(float(chamber['pv_updated']),now)
                pv_fresh=(0.0<=pv_age<=2.0)
                in_band=pv_fresh and abs(pv-target)<=float(t.get('pv_soak_band_c',1.0))+1e-9
                last_tick=float(t.get('thermal_last_tick') or now)
                dt=max(0.0,now-last_tick)
                t['thermal_last_tick']=now
                if in_band:
                    if not t.get('thermal_pv_in_range',False):
                        t['thermal_pv_in_range']=True
                        self._log(f'温箱PV恢复到热浸容许范围内，继续累计共同热平衡（已累计{t["thermal_elapsed_s"]:.0f}s）')
                    else:
                        # QTimer周期约100ms；限制单次补记，避免界面卡顿后把停顿时间算入热浸。
                        t['thermal_elapsed_s']+=min(dt,1.0)
                else:
                    if t.get('thermal_pv_in_range',False):
                        if not pv_fresh:
                            self._log('温箱PV反馈超过2秒未更新，共同热平衡暂停累计；收到新鲜反馈后继续')
                        else:
                            self._log(f'温箱PV={pv:.2f}℃超出热浸许可范围，共同热平衡暂停累计；恢复后继续')
                    t['thermal_pv_in_range']=False
                with tiltSensorRawData.data_lock:
                    chip=float(tiltSensorRawData.temp_c)
                    chip_frame_count=int(tiltSensorRawData.data_update_count)
                if not math.isfinite(chip) or not -45<=chip<=90:
                    raise ValueError('IMU 内温读数异常')
                if chip_frame_count!=t.get('last_chip_trace_count'):
                    t['chip_trace'].append((now,chip));t['last_chip_trace_count']=chip_frame_count
                t['chip_trace']=[v for v in t['chip_trace'] if now-v[0]<=360]
                wait_start=float(t.get('temperature_wait_started') or t['phase_start'])
                if now-wait_start>21600:raise ValueError('共同热平衡阶段超过6小时仍未完成')
                self.label.setText(f'共同热平衡：有效累计 {t["thermal_elapsed_s"]:.0f}/{self.dwell.value()}s；'
                                   f'PV={pv:.2f}℃；目标={target:.2f}℃；'
                                   + ('温箱在范围内，计时中' if in_band else
                                      'PV反馈超过2秒未更新，计时暂停' if not pv_fresh else
                                      '温箱超出热浸许可范围，计时暂停'))
                if t['thermal_elapsed_s']>=self.dwell.value():
                    t['phase']='final_stability';t['phase_start']=now
                    t['pv_final_trace']=[];t['pv_final_last_update']=None
                    self._log('共同热平衡有效累计时间已满足；开始最终温箱±偏差连续稳定检查及芯片稳定检查')
            elif t['phase']=='final_stability':
                if not self._stopped():raise ValueError('最终温度稳定检查阶段转台发生运动')
                pv=float(chamber['pv']);target=float(t['temps'][t['temp_i']])
                final_tol=float(t['pv_final_tolerance_c']);final_window=float(t['pv_final_seconds'])
                pv_stamp=min(float(chamber['pv_updated']),now)
                pv_age=now-pv_stamp
                pv_fresh=(0.0<=pv_age<=2.0)
                if (t.get('temperature_quality_mode') not in ('continuous','production_adaptive') and pv_fresh
                    and abs(pv-target)>float(t.get('pv_soak_band_c',1.0))+1e-9):
                    self._log(f'最终稳定检查期间PV={pv:.2f}℃超出热浸许可±{t.get("pv_soak_band_c",1.0):.2f}℃；重新执行共同热平衡')
                    t['phase']='thermal_soak';t['phase_start']=now
                    t['thermal_elapsed_s']=0.0;t['thermal_last_tick']=now;t['thermal_pv_in_range']=False
                    t['pv_final_trace']=[];t['pv_final_last_update']=None
                    return
                if pv_fresh and abs(pv-target)<=final_tol+1e-9:
                    if pv_stamp>float(t.get('pv_final_last_update') or 0.0):
                        t['pv_final_trace'].append((pv_stamp,pv))
                        t['pv_final_last_update']=pv_stamp
                else:
                    if t['pv_final_trace']:
                        reason=('PLC PV反馈超过2秒未更新' if not pv_fresh else
                                f'PV={pv:.2f}℃超出目标±{final_tol:.2f}℃')
                        self._log('最终PV精确稳定计时重置：'+reason)
                    t['pv_final_trace']=[];t['pv_final_last_update']=None
                t['pv_final_trace']=[x for x in t['pv_final_trace'] if now-x[0]<=final_window+20.0]
                pv_final_ok,pv_covered,pv_max_dev=chamber_band_status(
                    t['pv_final_trace'],now,target_c=target,tolerance_c=final_tol,
                    window_seconds=final_window)
                with tiltSensorRawData.data_lock:
                    chip=float(tiltSensorRawData.temp_c)
                    chip_frame_count=int(tiltSensorRawData.data_update_count)
                if not math.isfinite(chip) or not -45<=chip<=90:
                    raise ValueError('IMU 内温读数异常')
                if chip_frame_count!=t.get('last_chip_trace_count'):
                    t['chip_trace'].append((now,chip));t['last_chip_trace_count']=chip_frame_count
                t['chip_trace']=[v for v in t['chip_trace'] if now-v[0]<=360]
                chip_gate=float(t.get('chip_gate_60s_span_c',
                    0.25 if t.get('temperature_quality_mode') in ('continuous','production_adaptive') else 0.20))
                chip_ok,chip_covered,chip_span=chip_stability_status(
                    t['chip_trace'],now,max_range_c=chip_gate)
                trend_ok=True
                die_slope=None
                if t.get('temperature_quality_mode') in ('continuous','production_adaptive'):
                    # Do not restart while the IMU has a substantial residual
                    # heat-lag.  The 300 s data are already gathered during the
                    # minimum 900 s soak; this adds no fixed wait when stable.
                    history=[(ts,val) for ts,val in t['chip_trace'] if now-ts<=300]
                    if len(history)>=30 and history[-1][0]-history[0][0]>=285:
                        xs=np.asarray([(ts-history[0][0])/60 for ts,_ in history])
                        ys=np.asarray([value for _,value in history])
                        die_slope=float(np.polyfit(xs,ys,1)[0])
                        trend_ok=abs(die_slope)<=float(t.get('chip_5min_slope_gate_c_per_min',0.20))
                    else:
                        trend_ok=False  # do not accept an unobserved trend
                    chip_ok=chip_ok and trend_ok
                wait_start=float(t.get('temperature_wait_started') or t['phase_start'])
                if now-wait_start>21600:raise ValueError('最终温度稳定/芯片稳定检查超过6小时')
                self.label.setText(f'最终检查：PV={pv:.2f}℃，目标偏差窗口 {pv_covered:.0f}/{final_window:.0f}s，'
                                   f'最大偏差={pv_max_dev:.3f}/{final_tol:.2f}℃；'
                                   f'芯片={chip:.2f}℃，60秒窗口={chip_covered:.0f}s，极差={chip_span:.3f}/{chip_gate:.2f}℃'+
                                   (f'；芯片5分钟趋势={die_slope:+.3f}℃/min（允许±{float(t.get("chip_5min_slope_gate_c_per_min",0.20)):.2f}）' if die_slope is not None else
                                    '；芯片5分钟趋势待足够新鲜数据' if t.get('temperature_quality_mode') in ('continuous','production_adaptive') else ''))
                if pv_final_ok and chip_ok and abs(chip-pv)<=10.0:
                    t['guard']=None  # new epoch; old temperature history is no longer relevant
                    if t.get('resume_temp_index')==t['temp_i']:
                        t['step_i']=t.pop('resume_step_index',0);t['resume_temp_index']=None
                        self._log(f'恢复点温度稳定检查通过，从本温度第{t["step_i"]+1}项继续（之前合格工况跳过）')
                    else:t['step_i']=0
                    t['phase']='position';t['phase_start']=now
                    self._log(f'正式温度门槛全部通过：共同热平衡={t["thermal_elapsed_s"]:.0f}s，'
                              f'PV最大偏差={pv_max_dev:.3f}℃，芯片60秒极差={chip_span:.3f}℃；开始本温度点标定')
            elif t['phase']=='thermal_stability':
                if not self._stopped():raise ValueError('温度稳定等待时转台发生运动')
                pv=t['manual_confirmed_pv'] if t['manual'] else float(chamber['pv'])
                if abs(pv-t['temps'][t['temp_i']])>2:
                    raise ValueError('温箱实际温度已偏离目标 ±2℃')
                if t.get('chip_stability_only',False) and not t['manual'] and abs(pv-t['temps'][t['temp_i']])>1:
                    # 快速模式温箱PV重新偏离目标±1℃：回到快速PV门槛。
                    t['phase']='wait_plc';t['phase_start']=now;t['pv_stable_since']=None
                    t['chip_trace']=[];t['last_chip_trace_count']=None
                    self._log('快速模式：温箱PV重新偏离目标±1℃，重置30秒PV与60秒芯片稳定计时')
                    return
                if t.get('chip_stability_only',False) and t['manual'] and abs(pv-t['temps'][t['temp_i']])>1:
                    raise ValueError('人工模式输入PV偏离目标±1℃；请重新确认温箱实际温度')
                with tiltSensorRawData.data_lock:
                    chip=float(tiltSensorRawData.temp_c)
                    chip_frame_count=int(tiltSensorRawData.data_update_count)
                if not math.isfinite(chip) or not -45<=chip<=90:
                    raise ValueError('IMU 内温读数异常')
                if now-t['phase_start']>21600:
                    raise ValueError('芯片温度无法在 6 小时内达到热平衡')
                # 避免短暂空帧时，把上一帧旧芯片温度重复算作新的稳定性测量。
                if chip_frame_count != t.get('last_chip_trace_count'):
                    t['chip_trace'].append((now,chip))
                    t['last_chip_trace_count']=chip_frame_count
                t['chip_trace']=[v for v in t['chip_trace'] if now-v[0]<=360]
                stable, observed_s, span_c = chip_stability_status(t['chip_trace'], now)
                stable = stable and (now - t['phase_start'] >= 60.0)
                quick=bool(t.get('chip_stability_only',False))
                enough=quick or now-t['phase_start']>=self.dwell.value()
                # 刚到温时即使芯片暂时不变，也必须先收集完整60秒真实温度新样本；
                # PLC PV重新偏离目标±1℃时不允许在快速模式下开始标定。
                pv_ok=(abs(pv-t['temps'][t['temp_i']])<=1.0 if quick else True)
                if quick:
                    self.label.setText(f'温度 {t["temps"][t["temp_i"]]}℃：芯片 {chip:.2f}℃；稳定窗口 {observed_s:.0f}/60s，'
                                       f'波动 {span_c:.3f}/0.2℃；温箱PV={pv:.2f}℃'+
                                       ('（等待PV恢复至±1℃）' if not pv_ok else ''))
                else:
                    self.label.setText(f'温度 {t["temps"][t["temp_i"]]}℃：芯片 {chip:.2f}℃，'
                                       f'保温 {now-t["phase_start"]:.0f}/{self.dwell.value()}s，'
                                       f'完整60s窗口波动 {span_c:.3f}℃')
                if enough and stable and pv_ok and abs(chip-pv)<=10:
                    if t.get('resume_temp_index') == t['temp_i']:
                        t['step_i']=t.pop('resume_step_index',0)
                        t['resume_temp_index']=None
                        self._log(f'恢复点温度重新热平衡通过，从本温度第 {t["step_i"]+1} 项继续（之前成功项跳过）')
                    else:
                        t['step_i']=0
                    t['phase']='position';t['phase_start']=now
                    self._log((f'芯片连续60秒稳定，芯片={chip:.2f}℃，PV={pv:.2f}℃，窗口温差={span_c:.3f}℃；'
                               + ('已忽略固定保温时长，开始本温度工况' if quick else
                                  '固定最短保温也已满足，开始本温度工况')))
            elif t['phase']=='thermal_operator_hold':
                # Legacy checkpoints may still contain the obsolete phase.
                if not self._stopped():raise ValueError('温漂等待期间转台没有安全停止')
                if not t['manual']:
                    self._halt_incomplete_temperature(
                        '旧版温漂等待状态不支持自动跨温度点；请检查并续做')
                    return
                self.label.setText('人工设温模式需人工设定下一温度；建议改用PLC自动控温')
                return
            elif t['phase']=='thermal_pause':
                if not self._stopped():raise ValueError('温度暂停期间转台没有安全停止')
                g=t.get('guard')
                with tiltSensorRawData.data_lock:
                    chip=float(tiltSensorRawData.temp_c)
                    chip_count=int(tiltSensorRawData.data_update_count)
                pv=float(chamber['pv'])
                if g is None:
                    g=t['guard']=self._new_guard()
                action,quality_reason=g.observe(now,pv,float(chamber['pv_updated']),chip,chip_count)
                # A physically impossible/invalid thermal sensor reading is
                # a REAL equipment/data fault, not a skippable quality drift.
                if action=='safety':
                    raise ValueError('温度传感器不可信，不能自动恢复/跳温：'+quality_reason)
                if action=='resoak':
                    t['resume_temp_index']=t['temp_i'];t['resume_step_index']=t['step_i']
                    t['thermal_elapsed_s']=0.0;t['thermal_last_tick']=now;t['thermal_pv_in_range']=False
                    t['temperature_wait_started']=now
                    t['phase']='thermal_soak';t['phase_start']=now
                    self._log(f'温度持续偏差严重，重新共同热平衡{self.dwell.value()}秒；之前合格工况保留待复核')
                    return
                recovery_seconds=float(t.get('thermal_recovery_seconds',120.0))
                if g.recovery_ready(now,pv,chip,seconds=recovery_seconds):
                    t['phase']='position';t['phase_start']=now
                    t['retry_count']=0
                    self._log(f'停车后全新PV连续{recovery_seconds:g}秒及芯片60秒重新稳定，通过恢复门槛；重采受影响工况')
                    return
                observed=max(0.0,now-float(g.recovery_since or now))
                self.label.setText('温漂安全暂停：PV={:.2f}℃ 芯片={:.2f}℃；停车后新反馈稳定观察{:.0f}/{:.0f}秒'.format(
                    pv,chip,observed,recovery_seconds))
                if now-t['phase_start']>60.0*float(t.get('thermal_recovery_wait_minutes',60)):
                    self._halt_incomplete_temperature(
                        f'停车后温度恢复等待超过{t.get("thermal_recovery_wait_minutes",60):g}分钟')
                    return
            elif t['phase']=='position':
                if t['step_i']>=len(t['steps']):
                    # At the end of the full pass and again after the deferred
                    # pass, validate that each fit/validation group is at one
                    # comparable chip temperature before model input commits.
                    if self._audit_current_temperature_groups():
                        if t.get('replay_mode'):
                            t['replay_mode']=False
                        # Newly invalidated group entries will be recovered by
                        # the same once-per-temperature back-fill queue below.
                    pending=t['deferred_by_temp'].get(str(t['temp_i']),[])
                    accepted=self._accepted_step_keys()
                    forbidden={(m['temp_index'],m['step_index']) for m in t['unresolved']}
                    pending=[i for i in pending if self._step_key(t['temp_i'],i) not in accepted
                             and (t['temp_i'],i) not in forbidden]
                    if not t.get('replay_mode') and pending:
                        t['replay_mode']=True
                        t['replay_queue']=sorted(set(pending))
                        t['step_i']=t['replay_queue'].pop(0)
                        t['retry_count']=0
                        self._log(f'本温度正常工况已巡检，开始补测{len(pending)}个未通过工况；不重做1800秒热浸')
                        self._save_partial('RUNNING','准备补测')
                        return
                    self._advance_temperature(now)
                    return
                if self._step_key(t['temp_i'],t['step_i']) in self._accepted_step_keys():
                    self._next_step_after_result(now)
                    return
                step=t['steps'][t['step_i']]
                self._move(step['inner_deg'],step['outer_deg'])
                t['phase']='wait_position';t['phase_start']=now;t['stable_since']=None
                self._log(f'姿态运动 {step["step_id"]} -> 内 {step["inner_deg"]} / 外 {step["outer_deg"]}°')
            elif t['phase']=='wait_position':
                step=t['steps'][t['step_i']]
                self._check_position_command_started(now)
                in_place=(self._stopped() and turntableState.is_inner_axis_in_place and turntableState.is_outer_axis_in_place
                     and abs(_angle_error(turntableData.inner_axis_position,step['inner_deg']))<=0.2
                     and abs(_angle_error(turntableData.outer_axis_position,step['outer_deg']))<=0.2)
                if in_place:
                    if t['stable_since'] is None:t['stable_since']=now
                    if now-t['stable_since']>=1.0:
                        t.pop('position_watch',None)
                        t['phase']='settle';t['phase_start']=now
                else:t['stable_since']=None
                if now-t['phase_start']>240:raise ValueError('转台姿态到位超时')
            elif t['phase']=='settle':
                if not self._stopped():raise ValueError('静置阶段转台仍在运动')
                if now-t['phase_start']>=self.settle.value():
                    step=t['steps'][t['step_i']]
                    if step['mode']=='rate':
                        self._rate_command(step['rotation_axis'],step['target_rate_dps'])
                        t['phase']='wait_rate';t['phase_start']=now;t['stable_since']=None;t['wrong_sign_since']=None
                        t['rate_preflight_feedback']=[]
                    else:self._begin_sample(now)
            elif t['phase']=='wait_rate':
                self._check_rate_feedback()
                step=t['steps'][t['step_i']]
                speed=turntableData.inner_axis_speed if step['rotation_axis']=='inner' else turntableData.outer_axis_speed
                ref=step['target_rate_dps']
                # 正负转向必须和编码器反馈一致；在明显反向时尽快停车，而不是等待30秒。
                if speed*ref < 0 and abs(speed) >= max(0.4,abs(ref)*0.08):
                    if t.get('wrong_sign_since') is None:t['wrong_sign_since']=now
                    elif now-t['wrong_sign_since']>=0.4:
                        raise ValueError(f'WK温补{step["rotation_axis"]}实际转向与目标{ref:+g}°/s相反（实测{speed:+.3f}°/s），请求停车')
                else:t['wrong_sign_since']=None
                if abs(speed-ref)<=max(.2,abs(ref)*.15):
                    if t['stable_since'] is None:t['stable_since']=now
                    if now-t['stable_since']>=1:
                        recent=[x for x in t.get('rate_preflight_feedback',[])
                                if (now-float(x['monotonic_time_ns'])*1e-9)<=4.5]
                        checked=inspect_feedback(recent,step['rotation_axis'],ref,
                            **self._wk_rate_quality_arguments(ref))
                        if checked.get('certified'):
                            self._begin_sample(now)
                else:t['stable_since']=None
                # Short bounded preflight; never prolong high-speed rotation
                # unboundedly to chase a passing statistical window.
                max_wait=8.0 if abs(ref)>=30 else 12.0
                if now-t['phase_start']>max_wait:
                    self._defer_current_step(now,'匀速窗口在限定时间内未通过独立转台反馈检查')
                    return
            elif t['phase']=='sample':
                step=t['steps'][t['step_i']]
                if step['mode']=='rate':
                    self._check_rate_feedback()
                dur=float(step.get('sample_seconds',self.sample_seconds.value()))
                if now-t['sample_start']>=dur:
                    try:
                        diag=None
                        if step['mode']=='rate' and 'rate_sample_feedback' in t:
                            diag=inspect_feedback(t.get('rate_sample_feedback',[]),
                                step['rotation_axis'],step['target_rate_dps'],
                                **self._wk_rate_quality_arguments(step['target_rate_dps']))
                        stats=robust_segment(t['frames'],step['mode'],t['profile'],
                            target_rate=step.get('target_rate_dps'),axis=step.get('rotation_axis'),
                            static_sensor=step['sensor'], reference_diagnostic=diag)
                    except ValueError as exc:
                        # 与常温自动标定共用同一份工艺质量配置：静态最多5次重试，
                        # 动态最多3次重试。只改变重试机会，绝不降低稳健采样质检阈值。
                        retry_key = ('rate_sample_max_retries' if step['mode']=='rate'
                                     else 'static_sample_max_retries')
                        max_retries = int(t['profile']['quality'].get(
                            retry_key, 3 if step['mode']=='rate' else 5))
                        if t['retry_count']>=max_retries:
                            self._defer_current_step(now,
                                f'质量检查共{max_retries + 1}次仍不合格：{exc}')
                            return
                        t['retry_count']+=1
                        self._log(
                            f'{step["step_id"]} 采样质量拒绝，重试{t["retry_count"]}/{max_retries}：'
                            f'{exc}；准备重新采样')
                        if step['mode']=='rate':
                            if not self._stop_axes():raise ValueError('重试前停车命令失败')
                            self._begin_wk_stop_wait(t,now,retry=True)
                        else:
                            t['phase']='wait_position';t['phase_start']=now;t['stable_since']=None
                        t['frames']=[]
                        return
                    t['retry_count']=0
                    if step['mode']=='rate':
                        ref=_platform_angular_rate(stats['inner_actual_mean_deg'],stats['outer_actual_mean_deg'],
                            stats['inner_rate_mean_dps'],stats['outer_rate_mean_dps'],t['axis_model'])
                    elif step['sensor']=='acc':
                        ref=(_platform_gravity_vector(stats['inner_actual_mean_deg'],stats['outer_actual_mean_deg'],
                              t['axis_model'],gravity_sign=t['gravity_sign']) if t.get('ambient_wk_compare')
                              else _platform_gravity_vector(stats['inner_actual_mean_deg'],stats['outer_actual_mean_deg'],
                              t['axis_model']))
                    else:ref=np.zeros(3)
                    row={**stats,'reference':ref.tolist(),'step_id':step['step_id'],
                        'inner_target_deg':step.get('inner_deg'),'outer_target_deg':step.get('outer_deg'),
                        'target_rate_dps':step.get('target_rate_dps'),
                        'rotation_axis':step.get('rotation_axis'),
                        'split':step['split'],'mode':step['mode'],'sensor':step['sensor'],
                        'temperature_split':t['temperature_split_by_setpoint'][t['temps'][t['temp_i']]],
                        'temperature_target_c':t['temps'][t['temp_i']]}
                    self._log(f'采样完成 {step["step_id"]}；有效帧 {stats["accepted_frames"]}/{stats["frame_count"]}')
                    if step['mode']=='rate':
                        # 动态工况必须确认停车才能提交有效工况；停车失败则续做重测。
                        t['pending_dynamic_row']=row
                        if not self._stop_axes():raise ValueError('动态段停车命令失败')
                        self._begin_wk_stop_wait(t,now)
                    else:
                        t['rows'].append(row)
                        self._next_step_after_result(now)
                        self._save_partial('RUNNING',f'逐工况存档：{step["step_id"]}')
            elif t['phase'] in ('wait_stop','wait_stop_retry','wait_stop_defer','wait_stop_thermal'):
                ready, detail = self._wk_stop_confirmed(t, now)
                if not ready:
                    # 状态8#是厂家停车执行中；不能只凭速度接近零就提前定位。
                    # 只在状态文字变化时写日志，避免100ms轮询刷屏。
                    if detail != t.get('stop_wait_last_state'):
                        t['stop_wait_last_state'] = detail
                        self._log('WK等待停车完成：'+detail)
                    self.label.setText('GYRO停车确认：'+detail)
                    if now-t['phase_start']>30:
                        raise ValueError('WK停车超过30秒仍未返回两轴1#伺服待命：'+detail+
                                         '；保留未确认工况，禁止自动重复使能或定位，请现场检查')
                    return
                if t['phase']=='wait_stop':
                    completed=t.pop('pending_dynamic_row',None)
                    if completed is None:raise ValueError('缺少确认停车的动态工况结果，禁止推进进度')
                    t['rows'].append(completed)
                    self._next_step_after_result(now)
                    self._save_partial('RUNNING',f'逐工况存档：{completed["step_id"]}')
                elif t['phase']=='wait_stop_defer':
                    self._next_step_after_result(now)
                    self._save_partial('RUNNING','当前不合格工况已安全停车，进入下一项')
                elif t['phase']=='wait_stop_thermal':
                    # Actual 8# -> 1# standstill is confirmed ABOVE this
                    # branch. Do not create an unattended human-click latch.
                    hold_count=int(t.get('thermal_holds_per_temp',{}).get(str(t['temp_i']),1))
                    hold_limit=int(t.get('thermal_max_quality_holds',5))
                    if not t.get('manual') and hold_count>=hold_limit:
                        self._halt_incomplete_temperature(
                            f'同一温度点温漂质量暂停累计{hold_count}次（上限{hold_limit}次）')
                        return
                    if t.get('hold_requires_soak'):
                        # Reheat only while bounded by the original time budget.
                        t['resume_temp_index']=t['temp_i'];t['resume_step_index']=t['step_i']
                        t['thermal_elapsed_s']=0.0;t['thermal_last_tick']=now
                        t['thermal_pv_in_range']=False
                        t['phase']='thermal_soak';t['phase_start']=now
                        t.setdefault('temperature_wait_started',now)
                    else:
                        t['phase']='thermal_pause';t['phase_start']=now
                        if t.get('guard') is None:
                            t['guard']=self._new_guard()
                        t['guard'].begin_recovery(now)
                        self._log(f'WK已安全停车；恢复观察从现在重新计时，需连续'
                                  f'{t.get("thermal_recovery_seconds",120):g}秒的新鲜PV与芯片数据')
                    self._save_partial('RUNNING','温漂停车已确认，自动等待恢复')
                else:
                    t['phase']='position';t['phase_start']=now
                self._log('WK停车已确认：'+detail+'；允许执行后续安全状态')
            if not t['manual'] and t['phase'] not in ('next_temperature','verify_plc_sp'):
                self.plc_telemetry.setText(f'PLC实时：PV={chamber["pv"]:.2f}℃ / SP={chamber["sp"]:.2f}℃；运行={chamber["running"]}；报警={chamber["alarm"]}')
            if t['phase'] in ('verify_return','wait_return'):
                self.progress.setValue(99)
                self.label.setText(f'采集完成，正在自动回25℃：PV={chamber["pv"]:.2f}℃，SP={chamber["sp"]:.2f}℃')
                return
            # Compatibility with older state-machine fixtures, which use a
            # homogeneous step schedule; production runs always carry the
            # explicit per-temperature plan.
            schedule=t.get('steps_by_temperature')
            if schedule is None:
                schedule=[t['steps'] for _ in t['temps']]
            steps_total=sum(len(part) for part in schedule)
            done=min(len({(float(r['temperature_target_c']),r['step_id']) for r in t.get('rows',[])
                          if 'temperature_target_c' in r and 'step_id' in r}),steps_total)
            t['ui_max_progress']=max(int(t.get('ui_max_progress',0)),int(100*done/max(steps_total,1)))
            self.progress.setValue(t['ui_max_progress'])
            if t['phase'] not in ('thermal_stability','wait_manual','wait_plc','thermal_soak','final_stability'):
                self.label.setText(f'温度 {t["temp_i"]+1}/{len(t["temps"])}：{t["temps"][t["temp_i"]]}℃，'
                                  f'工况 {t["step_i"]+1}/{len(t["steps"])}，已接受 {done}/{steps_total}，阶段 {t["phase"]}')
        except Exception as exc:
            self._abort(f'自动温补中止：{exc}')

    def _begin_sample(self,now):
        t=self.task
        t['rate_sample_feedback']=[]
        t['phase']='sample';t['sample_start']=now;t['frames']=[]
        self._log('开始采集 '+t['steps'][t['step_i']]['step_id'])

    def shutdown(self):
        if self._r5_ramp is not None:
            self._stop_r5_ramp('上位机关闭；需现场确认温箱斜坡程序状态')
        # Qt event loop is about to stop: asynchronous abort_stop_wait cannot
        # finish. Preserve the checkpoint synchronously and alert that hardware
        # stop has NOT been verified by the process-exit path.
        if self.task is not None:
            self._finish(False,'程序退出：已请求停车，但进程退出无法确认最终伺服状态；请现场检查')
        self.timer.stop()
