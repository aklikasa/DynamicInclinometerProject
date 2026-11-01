# -*- coding: utf-8 -*-
"""IMU 标定实验页（第一版：转台单步控制 + 可追溯数据记录）。

本版刻意不执行整套自动运动序列，也不在界面内拟合标定参数。
先验证设备通讯、单步速率控制、数据完整记录与实验溯源。
"""
import csv
import datetime
import json
import os
import re
import sys
import time
import platform
import queue
import numpy as np

import serial.tools.list_ports
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QFormLayout,
    QGroupBox, QLabel, QPushButton, QComboBox, QDoubleSpinBox, QCheckBox,
    QLineEdit, QFileDialog, QPlainTextEdit, QMessageBox, QScrollArea, QFrame, QSpinBox, QProgressBar,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView
)

# form_tilt_sensor_cal.py 会把这些模块目录加入 sys.path；这里也按当前文件位置补齐，
# 避免从 IDE 以不同工作目录启动时找不到模块。
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR = os.path.dirname(_THIS_DIR)
for _subdir in ("turntable", "tilt_sensor"):
    _path = os.path.join(_PROJECT_DIR, _subdir)
    if _path not in sys.path:
        sys.path.append(_path)

from turntable_data_get import (
    turntableComm, turntableData, turntableState,
    turntable_feedback_queue_set, turntable_feedback_get_nowait,
    turntable_feedback_queue_drop_count_get
)
from turntable_2TD600_comm import (
    INNER_ROTATION_AXIS, OUTER_ROTATION_AXIS,
    twoTD600_SetAxisVelocity, twoTD600_SetAxisStop, twoTD600_SetAxisPosition,
    twoTD600_SetAxisFindZero,
    twoTD600_getAxisEnable, twoTD600_getAxisNormal,
    twoTD600_getAxisDriverFault, twoTD600_getAxisOverSpeed,
    twoTD600_getAxisOverDiff, twoTD600_getAxisOverVoltage,
    twoTD600_getAxisUpLimit, twoTD600_getAxisDownLimit,
)
from tilt_sensor_asm330_data_get import (
    tiltSensorRawData, tiltSensorComm,
    tilt_sensor_calibration_queue_set, tilt_sensor_calibration_frame_get_nowait,
    tilt_sensor_calibration_queue_drop_count_get
)
from tilt_sensor_asm330_csv import csv_is_enabled
from tilt_sensor_asm330_def import INC_SAMPLE_NUM
from calibration_model_compare import MODEL_NAMES, compare_models, score_model, serialize
from model_comparison_report import save_model_comparison, save_selected_model
from production_calibration import (
    load_profile, acc_fit_steps, acc_verify_steps, gyro_fit_steps, gyro_verify_steps,
    robust_segment, frame_average_sanitized, residual_statistics, evaluate, sensor_axis_invariants,
    verify_sensor_config, sensor_config_consistent, restrict_unverified_release,
)



def _rotation_x(angle_deg):
    """右手系绕 X 轴旋转矩阵。"""
    a = np.deg2rad(float(angle_deg))
    c, s = np.cos(a), np.sin(a)
    return np.array([[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]], dtype=float)


def _rotation_y(angle_deg):
    """右手系绕 Y 轴旋转矩阵。"""
    a = np.deg2rad(float(angle_deg))
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]], dtype=float)


def _rotation_z(angle_deg):
    a = np.deg2rad(float(angle_deg))
    c, sn = np.cos(a), np.sin(a)
    return np.array([[c, -sn, 0.0], [sn, c, 0.0], [0.0, 0.0, 1.0]], dtype=float)


# 已通过设备使用者确认：本转台的反馈角度按 360° 周期等价，0° 与 360° 为同一机械姿态。
# 只改变到位角度误差的计算，不取消机械找零、控制器到位标志、低速或超时检查。
POSITION_TOLERANCE_DEG = 0.2  # 试验初值，需根据设备计量能力确认
HOME_TIMEOUT_SECONDS = 180.0
POSITION_TIMEOUT_SECONDS = 240.0


def _wrapped_angle_error_deg(actual, target):
    """周期角度的最短有符号差，返回范围 [-180, 180) 度。"""
    return (float(actual) - float(target) + 180.0) % 360.0 - 180.0


def _feedback_at_target(inner_target, outer_target, tolerance=POSITION_TOLERANCE_DEG):
    inner = float(turntableData.inner_axis_position)
    outer = float(turntableData.outer_axis_position)
    targets = (float(inner_target), float(outer_target))
    if not np.all(np.isfinite((inner, outer, *targets))):
        return False
    return (abs(_wrapped_angle_error_deg(inner, targets[0])) <= tolerance and
            abs(_wrapped_angle_error_deg(outer, targets[1])) <= tolerance)


def _platform_rotation(inner_deg, outer_deg, axis_model):
    """
    默认按正交双轴框架计算平台姿态。
    axis_model='outer_x_inner_y': R = Rx(outer) @ Ry(inner)
    axis_model='outer_y_inner_x': R = Ry(outer) @ Rx(inner)
    R 将平台坐标向量变换到转台基座坐标。
    """
    if axis_model == "outer_x_inner_z":
        return _rotation_x(outer_deg) @ _rotation_z(inner_deg)
    if axis_model == "outer_y_inner_x":
        return _rotation_y(outer_deg) @ _rotation_x(inner_deg)
    if axis_model == "outer_x_inner_y":
        return _rotation_x(outer_deg) @ _rotation_y(inner_deg)
    raise ValueError(f"未知转台轴系模型：{axis_model}")


def _platform_gravity_vector(inner_deg, outer_deg, axis_model, gravity_sign=1):
    """按所选基座 Z 方向计算静止比力参考向量。"""
    R = _platform_rotation(inner_deg, outer_deg, axis_model)
    return R.T @ np.array([0.0, 0.0, float(gravity_sign)], dtype=float)


def _platform_angular_rate(inner_deg, outer_deg, inner_rate_dps, outer_rate_dps, axis_model):
    """把转台内/外轴实际角速度转换到当前平台坐标系。"""
    if axis_model == "outer_x_inner_z":
        R_outer = _rotation_x(outer_deg)
        e_outer = np.array([1.0, 0.0, 0.0])
        e_inner = np.array([0.0, 0.0, 1.0])
    elif axis_model == "outer_y_inner_x":
        R_outer = _rotation_y(outer_deg)
        e_outer = np.array([0.0, 1.0, 0.0])
        e_inner = np.array([1.0, 0.0, 0.0])
    elif axis_model == "outer_x_inner_y":
        R_outer = _rotation_x(outer_deg)
        e_outer = np.array([1.0, 0.0, 0.0])
        e_inner = np.array([0.0, 1.0, 0.0])
    else:
        raise ValueError(f"未知转台角速度轴系模型：{axis_model}")
    R = _platform_rotation(inner_deg, outer_deg, axis_model)
    omega_base = float(outer_rate_dps) * e_outer + float(inner_rate_dps) * (R_outer @ e_inner)
    return R.T @ omega_base


def _fit_affine_reference(reference_vectors, measured_vectors, input_unit, output_unit):
    """
    拟合 measured = A @ reference + bias，返回 inverse(A) 作为 measured -> reference 校正矩阵。
    reference/measured 均为 N×3；需要参考向量在三维空间有充分激励。
    """
    ref = np.asarray(reference_vectors, dtype=float)
    measured = np.asarray(measured_vectors, dtype=float)
    if ref.ndim != 2 or measured.ndim != 2 or ref.shape != measured.shape or ref.shape[1] != 3:
        raise ValueError("拟合数据必须是形状一致的 N×3 数组。")
    if len(ref) < 12:
        raise ValueError(f"有效拟合样本不足：{len(ref)}，至少需要 12 组。")
    if not np.all(np.isfinite(ref)) or not np.all(np.isfinite(measured)):
        raise ValueError("拟合数据包含 NaN 或无穷值。")
    design = np.column_stack([ref, np.ones(len(ref))])
    rank = int(np.linalg.matrix_rank(design))
    if rank < 4:
        raise ValueError(f"参考激励不满秩（rank={rank}/4），无法唯一估计三轴矩阵。请检查轴系模型和姿态覆盖。")
    beta, _, _, singular = np.linalg.lstsq(design, measured, rcond=None)
    forward = beta[:3, :].T
    bias = beta[3, :]
    cond = float(np.linalg.cond(forward))
    if not np.all(np.isfinite(forward)) or abs(float(np.linalg.det(forward))) < 1e-10 or cond > 1e5:
        raise ValueError(f"拟合矩阵不可逆或病态（condition={cond:.3g}）。")
    correction = np.linalg.inv(forward)
    corrected = (measured - bias) @ correction.T
    residual = corrected - ref
    norms = np.linalg.norm(residual, axis=1)
    return {
        "forward_matrix": forward,
        "bias": bias,
        "correction_matrix": correction,
        "condition_number": cond,
        "rank": rank,
        "rmse_vector": float(np.sqrt(np.mean(np.sum(residual * residual, axis=1)))),
        "max_vector_error": float(np.max(norms)),
        "residual_vectors": residual,
        "corrected_vectors": corrected,
    }


def _polar_rotation(matrix):
    """从校正矩阵提取最近的正交旋转分量（极分解/SVD）。"""
    m = np.asarray(matrix, dtype=float)
    u, _, vt = np.linalg.svd(m)
    r = u @ vt
    if np.linalg.det(r) < 0:
        u[:, -1] *= -1.0
        r = u @ vt
    return r


def _rotation_angle_deg(rotation):
    value = (float(np.trace(rotation)) - 1.0) / 2.0
    return float(np.rad2deg(np.arccos(np.clip(value, -1.0, 1.0))))



APP_REVISION = "imu-calibration-workbench-0.3-auto-calibration"
# 第一版仅开放低速单步运动，避免未实机验证前直接执行高转速工况。
# 后续应依据厂家手册、负载和风险评估再调整，不应仅为满足标定速率而随意放宽。
PROTOTYPE_MAX_ABS_SPEED_DPS = 10.0


def _now_iso():
    return datetime.datetime.now().astimezone().isoformat(timespec="milliseconds")


def _safe_float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class FormImuCalibration:
    """向主窗口动态增加“IMU标定”页。"""

    def __init__(self, main_window_ui, turntable_form):
        self.ui = main_window_ui
        self.turntable_form = turntable_form
        self.page = QWidget()
        self.page.setObjectName("page_ImuCalibration")
        self.recording = False
        self.run_dir = ""
        self.run_id = ""
        self.run_start_iso = ""
        self._imu_update_count_last = None
        self._turntable_update_count_last = None
        self._turntable_queue_active = False
        self._last_imu_queue_drops = 0
        self._last_turntable_queue_drops = 0
        self._imu_serial_was_open = bool(tiltSensorComm.is_serial_opened)
        self._last_flush_monotonic = time.monotonic()
        self._last_poll_error = ""
        self._auto_last_imu_count = None
        self._auto_last_imu_change_monotonic = time.monotonic()
        self._imu_rows = 0
        self._turntable_rows = 0
        self._marker_rows = 0
        self._event_rows = 0
        self._files = {}
        self._writers = {}
        self._manifest = {}
        self._auto_task = None
        self._axis_model_key = "outer_x_inner_z"
        self._last_accel_result = None
        self._last_gyro_result = None
        self._last_alignment_result = None
        self._last_model_comparison = None

        self._build_ui()
        self.ui.tabWidget_CalMain.addTab(self.page, "IMU 标定")
        self._update_live_status()

        self.display_timer = QTimer(self.page)
        self.display_timer.setInterval(250)
        self.display_timer.timeout.connect(self._update_live_status)
        self.display_timer.start()

        self.record_timer = QTimer(self.page)
        self.record_timer.setInterval(10)
        self.record_timer.timeout.connect(self._record_poll_tick)

        self.auto_timer = QTimer(self.page)
        self.auto_timer.setInterval(100)
        self.auto_timer.timeout.connect(self._auto_task_tick)

        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.shutdown)

        self._log_event("INFO", "PAGE_READY", "IMU自动标定页已初始化；转台运动通过原转台控制模块执行。", True)

    def _build_ui(self):
        """IMU页只负责自动标定任务与溯源；人工转台控制留在“转台”页。"""
        self.page.setStyleSheet("""
            QWidget#page_ImuCalibration { background: #eff2f3; color: #353d43; }
            QGroupBox { border: 1px solid #dce1e4; border-top: 1px solid #ffffff;
                border-radius: 13px; margin-top: 13px; padding-top: 8px; font-weight: 600;
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #ffffff,stop:1 #f9fafa); }
            QGroupBox::title { subcontrol-origin: margin; left: 13px; padding: 0 5px;
                color: #525d65; }
            QPushButton { min-height: 25px; padding: 3px 10px; border-radius: 9px;
                color: #424b53; border: 1px solid #cfd6da; border-top-color: #ffffff;
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #ffffff,stop:1 #ebeff1); }
            QPushButton:hover { background: #ffffff; border-color: #aeb9c1; }
            QPushButton:pressed { background: #e2e7e9; }
            QPushButton:disabled { color: #a4acb1; background: #eff1f2; border-color: #e2e6e8; }
            QPushButton#button_Plan { background: #e8ecee; font-weight: 600; }
            QPushButton#button_ImuRecordStart { color: white; font-weight: 600;
                border: 1px solid #313840; border-top-color: #78818a;
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #707a83,stop:1 #333b43); }
            QPushButton#button_ImuRecordStart[recording="true"] { color: #824c4c;
                border: 1px solid #e0bfbf; border-top-color: white; background: #f8eaea; }
            QLineEdit, QComboBox, QDoubleSpinBox, QSpinBox { min-height: 25px;
                border: 1px solid #d8dee2; border-radius: 7px; padding: 2px 6px; background: #ffffff; }
            QPlainTextEdit { border: 1px solid #d9e0e4; border-radius: 8px; background: #ffffff; }
            QLabel#label_ImuCalibrationSubtitle { color: #6d7880; }
        """)
        outer = QVBoxLayout(self.page)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)

        title = QLabel("IMU 自动标定")
        title.setStyleSheet("font-size: 16px; font-weight: 650; color: #353d44;")
        subtitle = QLabel("转台页面负责人工控制；本页负责自动驱动转台、同步采集 IMU 与转台反馈、拟合标定参数并保存全程记录。结果仍需独立工程验证后才能用于产品。")
        subtitle.setObjectName("label_ImuCalibrationSubtitle")
        subtitle.setWordWrap(True)
        outer.addWidget(title)
        outer.addWidget(subtitle)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(8)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        # 只显示共享设备状态，不在 IMU 页面提供转台连接/运动控件。
        status_box = QGroupBox("共享设备状态")
        status_layout = QGridLayout(status_box)
        self.label_turntable_status = QLabel("转台：读取原转台页面连接状态")
        self.label_imu_status = QLabel("IMU：请在左侧设备连接区打开串口")
        self.label_turntable_feedback = QLabel("内轴：位置 -- °，速率 -- °/s    外轴：位置 -- °，速率 -- °/s")
        self.label_turntable_feedback.setWordWrap(True)
        self.label_record_status = QLabel("实验：未开始")
        status_layout.addWidget(self.label_turntable_status, 0, 0)
        status_layout.addWidget(self.label_imu_status, 0, 1)
        status_layout.addWidget(self.label_turntable_feedback, 1, 0, 1, 2)
        status_layout.addWidget(self.label_record_status, 2, 0, 1, 2)
        layout.addWidget(status_box)

        # 自动标定任务区：IMU 页面不提供人工转台控制；任务通过共享的 2TD600 控制接口自动执行。
        task_box = QGroupBox("自动标定任务")
        task_grid = QGridLayout(task_box)
        task_grid.addWidget(QLabel("加速度计位置数"), 0, 0)
        self.spin_accel_positions = QSpinBox()
        self.spin_accel_positions.setRange(24, 24)
        self.spin_accel_positions.setValue(24)
        self.spin_accel_positions.setToolTip("常温试运行工艺：12 个拟合位置 + 12 个独立验证位置。")
        task_grid.addWidget(self.spin_accel_positions, 0, 1)

        task_grid.addWidget(QLabel("每个位置稳定等待（秒）"), 0, 2)
        self.spin_settle_seconds = QDoubleSpinBox()
        self.spin_settle_seconds.setRange(1.0, 120.0)
        self.spin_settle_seconds.setValue(3.0)
        self.spin_settle_seconds.setDecimals(1)
        task_grid.addWidget(self.spin_settle_seconds, 0, 3)

        task_grid.addWidget(QLabel("每个位置采样（秒）"), 1, 0)
        self.spin_sample_seconds = QDoubleSpinBox()
        self.spin_sample_seconds.setRange(2.0, 60.0)
        self.spin_sample_seconds.setValue(5.0)
        self.spin_sample_seconds.setDecimals(1)
        task_grid.addWidget(self.spin_sample_seconds, 1, 1)

        task_grid.addWidget(QLabel("位置运动速率（°/s）"), 1, 2)
        self.spin_position_speed = QDoubleSpinBox()
        self.spin_position_speed.setRange(0.1, 5.0)
        self.spin_position_speed.setValue(2.0)
        self.spin_position_speed.setDecimals(1)
        task_grid.addWidget(self.spin_position_speed, 1, 3)

        task_grid.addWidget(QLabel("参考轴系模型"), 2, 0)
        self.combo_axis_model = QComboBox()
        self.combo_axis_model.addItem("2TD600 已确认模型：外轴 X / 内轴 Z（零位、正向须实机核对）", "outer_x_inner_z")
        self.combo_axis_model.setToolTip(
            "自动标定固定使用外轴 X、内轴 Z。旧轴系仅用于解析历史资料，不能在本设备新任务中选择。"
        )
        task_grid.addWidget(self.combo_axis_model, 2, 1, 1, 3)

        task_grid.addWidget(QLabel("基座重力参考"), 3, 0)
        self.combo_gravity_sign = QComboBox()
        self.combo_gravity_sign.addItem("基座 +Z 向上（静止比力 +1 g）", 1)
        self.combo_gravity_sign.addItem("基座 +Z 向下（静止比力 -1 g）", -1)
        self.combo_gravity_sign.setToolTip("按转台基座坐标定义选择；不确定时不要运行自动标定。")
        task_grid.addWidget(self.combo_gravity_sign, 3, 1, 1, 3)

        # 不改变原转台工况：只在任务结束时选择不同数学模型求参。
        task_grid.addWidget(QLabel("标定数学方案"), 4, 0)
        self.combo_calibration_model = QComboBox()
        for model_id, model_name in MODEL_NAMES.items():
            self.combo_calibration_model.addItem(model_name, model_id)
        self.combo_calibration_model.setCurrentIndex(2)  # 原版完整3×3为默认，不改变既有行为
        self.combo_calibration_model.setToolTip(
            "A：ACC轴对齐椭球，仅重力模长确定零偏与比例；GYRO三轴独立线性拟合。\n"
            "B：零偏+三轴比例+SO(3)安装旋转。\n"
            "C：原版完整3×3标定。"
        )
        task_grid.addWidget(self.combo_calibration_model, 4, 1, 1, 3)

        self.button_accel_plan = QPushButton("开始 ACC 标定（12拟合+12验证）")
        self.button_accel_plan.setObjectName("button_Plan")
        self.button_accel_plan.clicked.connect(self._start_accel_auto)
        self.button_gyro_plan = QPushButton("开始陀螺仪自动标定")
        self.button_gyro_plan.setToolTip('实际执行保守速率 ±1、±2、±5°/s；±20、±60、±80°/s属于待转台认证候选，不会自动执行。')
        self.button_gyro_plan.clicked.connect(self._start_gyro_auto)
        self.button_alignment_check = QPushButton("开始六轴标定结果独立验证")
        self.button_alignment_check.clicked.connect(self._start_alignment_auto)
        task_grid.addWidget(self.button_accel_plan, 5, 0, 1, 2)
        task_grid.addWidget(self.button_gyro_plan, 5, 2, 1, 2)
        task_grid.addWidget(self.button_alignment_check, 7, 0, 1, 4)

        # 一次实际运动和采样，三种模型使用同一拟合集及独立验证集，禁止数据泄漏。
        self.button_compare_acc = QPushButton("自动采集 + ACC 三方案对比测试")
        self.button_compare_acc.setToolTip("自动完成12拟合+12独立验证；输出三方案参数及误差比较，不改变既有正式标定参数。")
        self.button_compare_acc.clicked.connect(self._start_acc_compare)
        self.button_compare_gyro = QPushButton("自动采集 + GYRO 三方案对比测试")
        self.button_compare_gyro.setToolTip("自动完成原工艺19拟合+13独立验证；同一采样数据比较三方案。")
        self.button_compare_gyro.clicked.connect(self._start_gyro_compare)
        task_grid.addWidget(self.button_compare_acc, 6, 0, 1, 2)
        task_grid.addWidget(self.button_compare_gyro, 6, 2, 1, 2)

        self.check_safety = QCheckBox(
            "已确认转台安装牢固、基座水平、轴系模型正确、线缆不缠绕、运动范围无障碍且硬件急停可用"
        )
        task_grid.addWidget(self.check_safety, 8, 0, 1, 4)

        self.label_auto_task = QLabel("自动标定：空闲")
        self.label_auto_task.setWordWrap(True)
        task_grid.addWidget(self.label_auto_task, 9, 0, 1, 4)
        self.progress_auto_task = QProgressBar()
        self.progress_auto_task.setRange(0, 100)
        self.progress_auto_task.setValue(0)
        task_grid.addWidget(self.progress_auto_task, 10, 0, 1, 3)
        self.button_abort_auto = QPushButton("中止自动标定")
        self.button_abort_auto.setEnabled(False)
        self.button_abort_auto.clicked.connect(self._abort_auto_button_clicked)
        task_grid.addWidget(self.button_abort_auto, 10, 3)

        warning = QLabel(
            "自动任务会实际驱动 2TD600。启动前必须在“转台”页面连接并使能转台，在左侧设备连接区打开 IMU 串口。"
            "当前为ASM330LHHX试运行：不强制ACC/GYRO候选量程；MCU未确认量程时允许开发标定，但不得正式出厂放行。"
            "转台未经高速认证，只运行≤10°/s的保守工况，拟合±1/±2/±5°/s；高速方案不自动执行。"
            "请核实机械零位、转台限位和反馈有效性。"
        )
        warning.setWordWrap(True)
        warning.setStyleSheet("color: #836e50; background: #f8f4e9; border: 1px solid #e9e0cf; border-radius: 8px; padding: 7px;")
        task_grid.addWidget(warning, 11, 0, 1, 4)
        self.table_model_comparison = QTableWidget(3, 6)
        self.table_model_comparison.setHorizontalHeaderLabels(
            ["方案", "质量结论", "验证矢量 RMSE", "最大矢量误差", "最大方向误差 °", "模长/交叉轴误差"]
        )
        self.table_model_comparison.verticalHeader().setVisible(False)
        self.table_model_comparison.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table_model_comparison.setAlternatingRowColors(True)
        self.table_model_comparison.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table_model_comparison.setMinimumHeight(145)
        self.table_model_comparison.setMaximumHeight(190)
        task_grid.addWidget(self.table_model_comparison, 12, 0, 1, 4)
        self.text_model_comparison = QPlainTextEdit()
        self.text_model_comparison.setReadOnly(True)
        self.text_model_comparison.setMinimumHeight(130)
        self.text_model_comparison.setMaximumHeight(230)
        self.text_model_comparison.setPlaceholderText(
            "运行 ACC/GYRO 自动对比后，将显示三模型独立验证RMSE、最大误差、质量结论及候选方案。"
        )
        task_grid.addWidget(self.text_model_comparison, 13, 0, 1, 4)
        layout.addWidget(task_box)

        # 实验目录与原始数据记录，继续复用已建立的记录器。
        record_box = QGroupBox("实验编号与原始数据记录")
        record_layout = QGridLayout(record_box)
        record_layout.addWidget(QLabel("实验编号"), 0, 0)
        self.line_run_id = QLineEdit("CAL_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
        record_layout.addWidget(self.line_run_id, 0, 1, 1, 2)
        record_layout.addWidget(QLabel("实验类型"), 1, 0)
        self.combo_experiment_type = QComboBox()
        self.combo_experiment_type.addItems(["加速度计内参", "陀螺仪内参", "六轴标定验证", "六轴综合数据", "摸底采集"])
        record_layout.addWidget(self.combo_experiment_type, 1, 1, 1, 2)
        record_layout.addWidget(QLabel("PCB唯一编号"), 5, 0)
        self.line_device_sn = QLineEdit()
        self.line_device_sn.setObjectName('line_ImuDeviceSerial')
        self.line_device_sn.setPlaceholderText('逐台标定必填；ACC、GYRO、六轴验证必须一致')
        record_layout.addWidget(self.line_device_sn, 5, 1, 1, 2)
        record_layout.addWidget(QLabel("保存根目录"), 2, 0)
        self.line_output_root = QLineEdit(os.path.join(os.path.expanduser("~"), "IMU_Calibration_Data"))
        record_layout.addWidget(self.line_output_root, 2, 1)
        self.button_browse_output = QPushButton("选择目录…")
        self.button_browse_output.clicked.connect(self._browse_output_root)
        record_layout.addWidget(self.button_browse_output, 2, 2)
        self.button_record_start = QPushButton("开始记录")
        self.button_record_start.setObjectName("button_ImuRecordStart")
        self.button_record_start.setProperty("recording", False)
        self.button_record_start.clicked.connect(self._toggle_recording)
        record_layout.addWidget(self.button_record_start, 3, 0, 1, 3)
        marker_layout = QHBoxLayout()
        marker_layout.addWidget(QLabel("工况编号"))
        self.line_step_id = QLineEdit("A_POSE_01")
        self.line_step_id.setPlaceholderText("例如 A_POSE_01 / G_OUTER_POS_01")
        marker_layout.addWidget(self.line_step_id, 1)
        marker_layout.addWidget(QLabel("备注"))
        self.line_step_note = QLineEdit()
        self.line_step_note.setPlaceholderText("姿态、方向、稳定情况等")
        marker_layout.addWidget(self.line_step_note, 2)
        self.button_mark_step = QPushButton("记录工况标记")
        self.button_mark_step.setEnabled(False)
        self.button_mark_step.clicked.connect(self._mark_step)
        marker_layout.addWidget(self.button_mark_step)
        record_layout.addLayout(marker_layout, 4, 0, 1, 3)
        layout.addWidget(record_box)

        log_box = QGroupBox("操作与异常日志")
        log_layout = QVBoxLayout(log_box)
        self.text_log = QPlainTextEdit()
        self.text_log.setReadOnly(True)
        self.text_log.setMaximumBlockCount(500)
        self.text_log.setMinimumHeight(120)
        self.text_log.setPlaceholderText("记录开始/停止、工况标记、计划生成和异常都会记录在这里；记录期间写入 events.csv。")
        log_layout.addWidget(self.text_log)
        layout.addWidget(log_box)

    def _write_plan_file(self, filename, payload):
        root = os.path.abspath(os.path.expanduser(self.line_output_root.text().strip()))
        if not root:
            QMessageBox.warning(self.page, "目录无效", "请先选择有效的保存根目录。")
            return None
        os.makedirs(root, exist_ok=True)
        path = os.path.join(root, filename)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.write("\n")
        self._log_event("INFO", "PLAN_FILE_CREATED", f"已生成工况计划：{path}；本操作不会驱动转台。", True)
        QMessageBox.information(self.page, "计划已生成", f"工况计划已保存：\n{path}\n\n注意：这是待核实的计划文件，不会自动控制转台，也不是标定结果。")
        return path


    def _current_axis_model(self):
        value = self.combo_axis_model.currentData() if hasattr(self, "combo_axis_model") else "outer_x_inner_z"
        return str(value or "outer_x_inner_z")

    @staticmethod
    def _sensor_reading_snapshot():
        # 避免量程字段、确认标志和ODR跨越MCU数据更新边界产生撕裂快照。
        with tiltSensorRawData.data_lock:
            return {'acc_fs':int(tiltSensorRawData.acc_fs),
                    'gyro_fs':int(tiltSensorRawData.gyro_fs),
                    'acc_fs_ever_valid':bool(tiltSensorRawData.acc_fs_ever_valid),
                    'gyro_fs_ever_valid':bool(tiltSensorRawData.gyro_fs_ever_valid),
                    'data_odr':int(tiltSensorRawData.data_odr)}

    def _auto_preflight(self, task_type):
        """自动任务启动前检查；不满足条件时绝不发送运动命令。"""
        if self._auto_task is not None:
            QMessageBox.warning(self.page, "任务正在运行", "请先完成或中止当前自动标定任务。")
            return False
        if self.recording:
            QMessageBox.warning(self.page, "已有记录正在进行", "请先停止手动记录，再启动自动标定，避免混合不同实验。")
            return False
        if not self._is_turntable_connected() or not turntableData.is_turntable_data_available:
            QMessageBox.warning(self.page, "转台未就绪", "请先在“转台”页面连接 2TD600，并确认状态反馈有效。")
            return False
        if not tiltSensorComm.is_serial_opened or not tiltSensorComm.is_data_available or tiltSensorRawData.data_update_count <= 0:
            QMessageBox.warning(self.page, "IMU 未就绪", "请先在左侧设备连接区打开 IMU 串口，并确认有效数据正在更新。")
            return False
        try:
            profile = load_profile(_PROJECT_DIR)
            current_sensor = self._sensor_reading_snapshot()
            verify_sensor_config(profile, current_sensor)
            if task_type == 'align':
                for label in ('accel_calibration.json','gyro_calibration.json'):
                    fpath = os.path.join(os.path.abspath(os.path.expanduser(self.line_output_root.text().strip())), label)
                    if os.path.isfile(fpath):
                        with open(fpath, encoding='utf-8') as fh:
                            previous = json.load(fh)
                        frozen = previous.get('sensor_configuration')
                        if not isinstance(frozen, dict) or not sensor_config_consistent(frozen, verify_sensor_config(profile, current_sensor)):
                            raise ValueError(f'{label} 的有效换算量程与当前不同或缺少记录，拒绝混用')
        except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
            QMessageBox.warning(self.page, '芯片配置核验失败', str(exc))
            return False
        if not self.check_safety.isChecked():
            QMessageBox.warning(self.page, "缺少安全确认", "请确认机械安装、轴系模型、线缆、运动范围和硬件急停后勾选安全确认。")
            return False
        if csv_is_enabled():
            QMessageBox.warning(
                self.page, "IMU 原有 CSV 记录仍在运行",
                "请先在左侧“数据记录”页停止原有 CSV 记录，避免数据来源混淆。"
            )
            return False
        # 两轴都必须处于可运行且已使能状态；状态未知按不安全处理。
        for axis, name in ((INNER_ROTATION_AXIS, "内轴"), (OUTER_ROTATION_AXIS, "外轴")):
            ok, reason = self._motion_precheck(axis)
            if not ok:
                QMessageBox.warning(self.page, f"{name}未通过安全检查", reason)
                return False
        if abs(float(turntableData.inner_axis_speed)) > 0.05 or abs(float(turntableData.outer_axis_speed)) > 0.05:
            QMessageBox.warning(self.page, "转台尚未停止", "请先确认内外轴实际速率均接近 0°/s，再启动自动标定。")
            return False
        if task_type == "align":
            root = os.path.abspath(os.path.expanduser(self.line_output_root.text().strip()))
            missing = [p for p in (os.path.join(root, "accel_calibration.json"),
                                   os.path.join(root, "gyro_calibration.json")) if not os.path.isfile(p)]
            if missing:
                QMessageBox.warning(self.page, "缺少前置标定结果",
                                    "六轴验证前必须先完成ACC和GYRO标定：\n" + "\n".join(missing))
                return False
            for path in (os.path.join(root, 'accel_calibration.json'), os.path.join(root,'gyro_calibration.json')):
                try:
                    with open(path, encoding='utf-8') as f:
                        previous = json.load(f)
                except (OSError, ValueError) as exc:
                    QMessageBox.warning(self.page, '无法读取标定参数', f'{path}\n{exc}')
                    return False
                if previous.get('quality_gate',{}).get('metric_pass') is not True:
                    QMessageBox.warning(self.page,'前置结果未通过', f'独立验证未通过，不能开始六轴验证：{path}')
                    return False
                if previous.get('device_serial') != self.line_device_sn.text().strip():
                    QMessageBox.warning(self.page,'PCB编号不匹配', f'标定结果属于其他PCB：{path}')
                    return False
        return True

    def _set_turntable_manual_controls_locked(self, locked):
        """自动任务运行期间锁住人工启动/回零/连接操作，但保留人工停车按钮。"""
        form = self.turntable_form
        if form is None:
            return
        lock_names = [
            "button_TurntableCommPortOpen", "comboBox_TurntableModelSelect",
            "pushButton_InnerReturnZero", "pushButton_OuterReturnZero", "pushButton_AllReturnZero",
            "pushButton_InnerRun", "pushButton_OuterRun", "pushButton_AllRun",
            "lineEdit_InnerRotationAngleSet", "lineEdit_InnerRotationSpeedSet",
            "lineEdit_outerRotationAngleSet", "lineEdit_outerRotationSpeedSet",
            "comboBox_InnerPositionMode", "comboBox_OuterPositionMode",
            "lineEdit_InnerRotationSpeedForSpeedMode", "lineEdit_InnerRotationAccelForSpeedMode",
            "lineEdit_OuterRotationSpeedForSpeedMode", "lineEdit_OuterRotationAccelForSpeedMode",
            "pushButton_InnerRunForSpeedMode", "pushButton_OuterRunForSpeedMode",
            "lineEdit_InnerSwayAmplForSwayMode", "lineEdit_InnerSwayFreqForSwayMode",
            "lineEdit_OuterSwayAmplForSwayMode", "lineEdit_OuterSwayFreqForSwayMode",
            "pushButton_InnerRunForSwayMode", "pushButton_OuterRunForSwayMode",
        ]
        if locked:
            if getattr(self, "_manual_controls_snapshot", None) is None:
                self._manual_controls_snapshot = {}
                for name in lock_names:
                    widget = getattr(form, name, None)
                    if widget is not None:
                        self._manual_controls_snapshot[name] = bool(widget.isEnabled())
            for name in lock_names:
                widget = getattr(form, name, None)
                if widget is not None:
                    widget.setEnabled(False)
        else:
            snapshot = getattr(self, "_manual_controls_snapshot", None)
            if snapshot is not None:
                for name, enabled in snapshot.items():
                    widget = getattr(form, name, None)
                    if widget is not None:
                        widget.setEnabled(bool(enabled))
            self._manual_controls_snapshot = None

    def _new_run_id(self, prefix):
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        candidate = f"{prefix}_{stamp}"
        root = os.path.abspath(os.path.expanduser(self.line_output_root.text().strip()))
        suffix = 1
        while os.path.exists(os.path.join(root, candidate)):
            suffix += 1
            candidate = f"{prefix}_{stamp}_{suffix:02d}"
        return candidate

    def _start_auto_task(self, task_type, steps, run_prefix, experiment_type, *, compare=False, model_id=None):
        if not self._auto_preflight(task_type):
            return
        axis_model = self._current_axis_model()
        # 2TD600 本机禁止把旧轴系选项当作现场可切换的标定模型。
        if axis_model != "outer_x_inner_z":
            QMessageBox.warning(self.page, '标定轴系错误',
                                '本机物理轴系必须为外 X / 内 Z；不允许用其他模型拟合。')
            return
        gravity_sign = int(self.combo_gravity_sign.currentData())
        device_sn = self.line_device_sn.text().strip()
        if not device_sn or not re.fullmatch(r'[A-Za-z0-9._-]{1,64}', device_sn):
            QMessageBox.warning(self.page, 'PCB编号缺失或非法',
                                '标定前必须填写1–64位的PCB唯一编号（字母、数字、点、下划线、短横线）。')
            return
        selected_model = model_id or self.combo_calibration_model.currentData()
        if selected_model not in MODEL_NAMES:
            QMessageBox.warning(self.page, "方案无效", "请先选择有效的标定方案")
            return
        # 强制在弹窗中再次确认本次任务会实际运动，避免把“开始”误当成计划生成。
        count = len(steps)
        answer = QMessageBox.question(
            self.page, "确认开始自动标定",
            f"任务：{experiment_type}\n模式：{'自动采集+三方案对比' if compare else MODEL_NAMES[selected_model]}\n"
            f"步骤数：{count}\n轴系模型：{self.combo_axis_model.currentText()}\n"
            f"重力参考：{self.combo_gravity_sign.currentText()}\n保存目录：{self.line_output_root.text().strip()}\n\n"
            "开始后检查机械找零状态；必要时执行机械找零，随后移动双轴至 0°。"
            "请确认机械运动安全、线缆有余量，并已核对设备零位定义。是否开始？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if answer != QMessageBox.Yes:
            return

        try:
            quality_profile = load_profile(_PROJECT_DIR)
        except Exception as exc:
            QMessageBox.critical(self.page, "生产工艺配置错误", str(exc))
            return
        self.line_run_id.setText(self._new_run_id(run_prefix))
        self.combo_experiment_type.setCurrentText(experiment_type)
        self._start_recording()
        if not self.recording:
            return

        self._auto_last_imu_count = int(tiltSensorRawData.data_update_count)
        self._auto_last_imu_change_monotonic = time.monotonic()
        try:
            frozen_sensor_config = verify_sensor_config(quality_profile, self._sensor_reading_snapshot())
        except ValueError as exc:
            self._stop_recording()
            QMessageBox.warning(self.page, '量程/ODR发生变化', str(exc))
            return
        if not frozen_sensor_config['verified_for_release']:
            self._log_event('WARN', 'SENSOR_FULL_SCALE_UNVERIFIED',
                            'MCU未明确确认实际量程/ODR；使用本次有效换算值进行试运行，结果禁止出厂放行。', True)
            QMessageBox.information(
                self.page, '量程未核验：允许试运行',
                f'本次IMU数据换算：ACC ±{frozen_sensor_config["acc_fs_g"]} g，'
                f'GYRO ±{frozen_sensor_config["gyro_fs_dps"]}°/s，'
                f'ODR {frozen_sensor_config["odr_hz"] or "未知"} Hz。\n'
                '这些数值可能来自底层默认回退，未被MCU确认。标定允许继续，但结果不能正式出厂放行。'
            )
        self._auto_task = {
            "type": task_type,
            "compare_models": bool(compare),
            "selected_model": selected_model,
            "sensor_configuration": frozen_sensor_config,
            "steps": steps,
            "index": 0,
            "phase": "home_check",
            "phase_started": time.monotonic(),
            "home_axis": None,
            "stable_since": None,
            "sample_started": None,
            "sample_frames": [],
            "static_retry_count": 0,
            "static_retry_history": [],
            "rate_retry_count": 0,
            "rate_retry_history": [],
            "last_rate_quality_error": "",
            "last_static_quality_error": "",
            "pose_measurements": [],
            "gyro_fit_samples": [],
            "gyro_validation_samples": [],
            "gyro_static_samples": [],
            "quality_profile": quality_profile,
            "device_serial": device_sn,
            "axis_model": axis_model,
            "gravity_sign": gravity_sign,
            "abort_reason": "",
            "abort_stop_sent": False,
            "result_paths": [],
        }
        self._log_event(
            "INFO", "AUTO_TASK_START",
            json.dumps({"type": task_type, "steps": count, "compare_models": bool(compare),
                        "selected_model": selected_model, "axis_model": axis_model, "gravity_sign": gravity_sign,
                        "settle_seconds": self.spin_settle_seconds.value(),
                        "sample_seconds": self.spin_sample_seconds.value(),
                        "position_speed_dps": self.spin_position_speed.value(),
                        "device_serial": device_sn,
                        "quality_profile": quality_profile['profile_id'],
                        "sensor_configuration": frozen_sensor_config,
                        "approved_for_production": quality_profile['approved_for_production']}, ensure_ascii=False),
            True
        )
        self.button_accel_plan.setEnabled(False)
        self.button_gyro_plan.setEnabled(False)
        self.button_alignment_check.setEnabled(False)
        self.button_compare_acc.setEnabled(False)
        self.button_compare_gyro.setEnabled(False)
        self.combo_calibration_model.setEnabled(False)
        self.button_record_start.setEnabled(False)
        self.button_abort_auto.setEnabled(True)
        self._set_turntable_manual_controls_locked(True)
        self.progress_auto_task.setValue(0)
        self.label_auto_task.setText(f"自动标定启动：{experiment_type}，共 {count} 步")
        self.auto_timer.start()

    def _start_accel_auto(self):
        # 6个正交基准 + 6个扩展点用于求参，12个不重复参考方向完全留作验证。
        steps = acc_fit_steps() + acc_verify_steps()
        self._start_auto_task("accel", steps, "ACCEL", "加速度计内参")

    def _start_gyro_auto(self):
        try:
            profile = load_profile(_PROJECT_DIR)
        except Exception as exc:
            QMessageBox.warning(self.page, "生产工艺配置错误", str(exc))
            return
        if not self._check_gyro_profile_rate_safety(profile):
            return
        steps = gyro_fit_steps(profile) + gyro_verify_steps(profile)
        self._start_auto_task("gyro", steps, "GYRO", "陀螺仪内参")

    def _start_acc_compare(self):
        steps = acc_fit_steps() + acc_verify_steps()
        self._start_auto_task("accel", steps, "ACC_COMPARE", "ACC 三方案自动标定与独立测试", compare=True)

    def _start_gyro_compare(self):
        try:
            profile = load_profile(_PROJECT_DIR)
        except Exception as exc:
            QMessageBox.warning(self.page, "生产工艺配置错误", str(exc))
            return
        if not self._check_gyro_profile_rate_safety(profile):
            return
        steps = gyro_fit_steps(profile) + gyro_verify_steps(profile)
        self._start_auto_task("gyro", steps, "GYRO_COMPARE", "GYRO 三方案自动标定与独立测试", compare=True)

    def _start_alignment_auto(self):
        # 独立复核，不再把极分解相对旋转再次乘到ACC/GYRO输出上。
        try:
            profile = load_profile(_PROJECT_DIR)
        except Exception as exc:
            QMessageBox.warning(self.page, "生产工艺配置错误", str(exc))
            return
        if not self._check_gyro_profile_rate_safety(profile):
            return
        steps = acc_verify_steps() + gyro_verify_steps(profile)
        self._start_auto_task("align", steps, "VERIFY", "六轴标定验证")

    def _check_gyro_profile_rate_safety(self, profile):
        """运动前验证工艺转速表；不能等转台归零后才检查超速。"""
        try:
            rates = profile['rates']
            fit = [float(x) for x in rates['fit_dps']]
            verify = [float(x) for x in rates['verify_dps']]
            all_rates = fit + verify
            if not fit or not verify or not all(np.isfinite(x) and x > 0 for x in all_rates):
                raise ValueError('拟合和验证必须包含正的有限角速度幅值。')
            if len(set(fit)) != len(fit) or len(set(verify)) != len(verify):
                raise ValueError('标定或验证中存在重复的角速度幅值。')
            if set(fit) & set(verify):
                raise ValueError('独立验证角速度必须与拟合速率不同。')
            limit = min(float(rates['maximum_command_rate_dps']), PROTOTYPE_MAX_ABS_SPEED_DPS)
            if not np.isfinite(limit) or limit <= 0 or max(all_rates) > limit:
                raise ValueError(f'速率计划最高 {max(all_rates):g}°/s，超过已允许的 ±{limit:g}°/s。'
                                 '请先核实转台限位、计量能力和稳定匀速区间，不得绕过限速。')
            return True
        except (ValueError, KeyError, TypeError) as exc:
            QMessageBox.warning(self.page, '陀螺仪速率工艺配置无效', str(exc))
            return False

    def _task_both_axes_safe(self):
        task = self._auto_task
        if task is not None:
            try:
                verified = verify_sensor_config(task['quality_profile'], self._sensor_reading_snapshot())
                if not sensor_config_consistent(task['sensor_configuration'], verified):
                    return False, 'IMU量程/ODR在标定任务中发生变化。'
            except (ValueError, TypeError, KeyError) as exc:
                return False, f'IMU量程/ODR核验失败：{exc}'
        if not self._is_turntable_connected() or not turntableData.is_turntable_data_available:
            return False, "转台通讯或反馈丢失。"
        # is_turntable_data_available 是历史有效标志；必须同时确认反馈仍在刷新，防止用旧位置/速率继续自动运动。
        feedback_ns = int(getattr(turntableData, "last_update_monotonic_ns", 0) or 0)
        if feedback_ns <= 0 or (time.perf_counter_ns() - feedback_ns) > 750_000_000:
            return False, "转台反馈超过 0.75 秒未更新，自动任务中止。"
        if not tiltSensorComm.is_serial_opened or not tiltSensorComm.is_data_available:
            return False, "IMU 串口或数据流中断。"
        imu_count = int(getattr(tiltSensorRawData, "data_update_count", 0))
        if imu_count != self._auto_last_imu_count:
            self._auto_last_imu_count = imu_count
            self._auto_last_imu_change_monotonic = time.monotonic()
        elif time.monotonic() - self._auto_last_imu_change_monotonic > 1.5:
            return False, "IMU 数据计数超过 1.5 秒未更新，自动任务中止。"
        for axis, name in ((INNER_ROTATION_AXIS, "内轴"), (OUTER_ROTATION_AXIS, "外轴")):
            ok, reason = self._motion_precheck(axis)
            if not ok:
                return False, f"{name}安全检查失败：{reason}"
        return True, "OK"

    def _send_position_pair(self, inner_deg, outer_deg):
        speed = float(self.spin_position_speed.value())
        with turntableComm.thread_lock:
            inner_ok = bool(twoTD600_SetAxisPosition(INNER_ROTATION_AXIS, float(inner_deg), speed))
            if not inner_ok:
                return False, "内轴位置指令失败。"
            time.sleep(0.03)
            outer_ok = bool(twoTD600_SetAxisPosition(OUTER_ROTATION_AXIS, float(outer_deg), speed))
        if not outer_ok:
            return False, "外轴位置指令失败。"
        return True, "OK"

    def _send_axis_velocity(self, axis, speed):
        # 速率模式加速度参数暂采用已在人工转台页面验证前的保守值；可后续加入自动任务专用参数。
        accel = 1.0
        with turntableComm.thread_lock:
            result = bool(twoTD600_SetAxisVelocity(int(axis), float(speed), accel))
        return result

    def _send_stop_axis(self, axis):
        with turntableComm.thread_lock:
            return bool(twoTD600_SetAxisStop(int(axis)))

    def _send_stop_all(self):
        results = []
        for axis in (INNER_ROTATION_AXIS, OUTER_ROTATION_AXIS):
            try:
                results.append(self._send_stop_axis(axis))
            except Exception:
                results.append(False)
        return all(results)

    def _current_step(self):
        if self._auto_task is None:
            return None
        steps = self._auto_task["steps"]
        idx = self._auto_task["index"]
        return steps[idx] if 0 <= idx < len(steps) else None

    def _auto_task_tick(self):
        task = self._auto_task
        if task is None:
            return
        now = time.monotonic()
        try:
            if task["phase"] == "aborting":
                if not task["abort_stop_sent"]:
                    self._send_stop_all()
                    task["abort_stop_sent"] = True
                    task["phase_started"] = now
                stopped = (abs(float(turntableData.inner_axis_speed)) < 0.05 and
                           abs(float(turntableData.outer_axis_speed)) < 0.05)
                if stopped or now - task["phase_started"] > 20.0:
                    reason = task["abort_reason"] or "用户中止"
                    if not stopped:
                        reason += "；20 秒内未能从反馈确认两轴停止，请立即检查硬件急停。"
                    self._finalize_auto_task(False, reason)
                return

            ok, reason = self._task_both_axes_safe()
            if not ok:
                self._request_auto_abort(f"运行期间安全检查失败：{reason}")
                return

            phase = task["phase"]
            if phase in ("home_check", "home_command", "home_wait", "zero_position_command", "zero_position_wait", "zero_settle"):
                names = {
                    "home_check": "核验机械零点",
                    "home_command": "下发机械找零命令",
                    "home_wait": "等待机械找零反馈",
                    "zero_position_command": "下发双轴 0° 位置指令",
                    "zero_position_wait": "等待双轴回到 0°",
                    "zero_settle": "双轴归零完成，等待静置",
                }
                elapsed = max(0.0, now - float(task["phase_started"]))
                self.label_auto_task.setText(
                    f"自动标定准备阶段：{names[phase]}（{elapsed:.0f}秒）\n"
                    f"内轴 {turntableData.inner_axis_position:.3f}°，"
                    f"外轴 {turntableData.outer_axis_position:.3f}°；"
                    f"速度 {turntableData.inner_axis_speed:.3f}/{turntableData.outer_axis_speed:.3f}°/s；"
                    f"到位标志 内={int(bool(turntableState.is_inner_axis_in_place))}、"
                    f"外={int(bool(turntableState.is_outer_axis_in_place))}。"
                )
            if phase == "home_check":
                # FindZero 标志表示机械参考已建立；位置仍须单独核验。
                if not turntableState.is_inner_axis_find_zero:
                    task["home_axis"] = "inner"
                    task["phase"] = "home_command"
                elif not turntableState.is_outer_axis_find_zero:
                    task["home_axis"] = "outer"
                    task["phase"] = "home_command"
                else:
                    task["phase"] = "zero_position_command"
                task["phase_started"] = now
                task["stable_since"] = None
                return

            if phase == "home_command":
                axis_name = task["home_axis"]
                axis = INNER_ROTATION_AXIS if axis_name == "inner" else OUTER_ROTATION_AXIS
                # 保守速率；硬件找零安全性及机械范围必须在首次实机使用前确认。
                with turntableComm.thread_lock:
                    sent = bool(twoTD600_SetAxisFindZero(axis, 2.0, 2.0))
                self._log_event("INFO" if sent else "ERROR", "AUTO_FIND_ZERO_COMMAND", f"axis={axis_name}; speed=2 deg/s; accel=2 deg/s²", sent)
                if not sent:
                    self._request_auto_abort(f"{axis_name} 机械找零命令失败")
                    return
                task["phase"] = "home_wait"
                task["phase_started"] = now
                task["stable_since"] = None
                return

            if phase == "home_wait":
                name = task["home_axis"]
                found = bool(turntableState.is_inner_axis_find_zero if name == "inner" else turntableState.is_outer_axis_find_zero)
                speed = float(turntableData.inner_axis_speed if name == "inner" else turntableData.outer_axis_speed)
                if found and abs(speed) < 0.05:
                    if task["stable_since"] is None:
                        task["stable_since"] = now
                    elif now - task["stable_since"] >= 0.5:
                        self._log_event("INFO", "AUTO_FIND_ZERO_DONE", f"axis={name}", True)
                        task["phase"] = "home_check"
                        task["phase_started"] = now
                        task["stable_since"] = None
                else:
                    task["stable_since"] = None
                if now - task["phase_started"] > HOME_TIMEOUT_SECONDS:
                    self._request_auto_abort(f"{name} 机械找零超时，未确认找零成功")
                return

            if phase == "zero_position_command":
                ok, reason = self._send_position_pair(0.0, 0.0)
                self._log_event("INFO" if ok else "ERROR", "AUTO_ZERO_POSITION_COMMAND", reason, ok)
                if not ok:
                    self._request_auto_abort(f"双轴回 0° 指令失败：{reason}")
                    return
                task["phase"] = "zero_position_wait"
                task["phase_started"] = now
                task["stable_since"] = None
                return

            if phase == "zero_position_wait":
                stopped = abs(float(turntableData.inner_axis_speed)) < 0.05 and abs(float(turntableData.outer_axis_speed)) < 0.05
                reached = _feedback_at_target(0.0, 0.0) and bool(turntableState.is_inner_axis_in_place and turntableState.is_outer_axis_in_place)
                if stopped and reached:
                    if task["stable_since"] is None:
                        task["stable_since"] = now
                    elif now - task["stable_since"] >= 0.5:
                        task["phase"] = "zero_settle"
                        task["phase_started"] = now
                        task["stable_since"] = None
                        self._log_event("INFO", "AUTO_ZERO_VERIFIED", "两轴反馈角度等效 0±0.2°（360°周期），停止且到位标志有效", True)
                else:
                    task["stable_since"] = None
                if now - task["phase_started"] > POSITION_TIMEOUT_SECONDS:
                    self._request_auto_abort("双轴回零后周期角度误差未到 0±0.2° 或到位标志无效，已拒绝开始标定")
                return

            if phase == "zero_settle":
                if not _feedback_at_target(0.0, 0.0):
                    self._request_auto_abort("回零静置期间角度反馈偏离零位")
                    return
                if now - task["phase_started"] >= float(self.spin_settle_seconds.value()):
                    task["phase"] = "position_command"
                    task["phase_started"] = now
                return

            step = self._current_step()
            if step is None:
                self._complete_auto_task()
                return
            phase = task["phase"]
            self.label_auto_task.setText(
                f'{task["type"]} 自动标定：第 {task["index"] + 1}/{len(task["steps"])} 步 '
                f'{step["step_id"]}；阶段={phase}'
                + (f'；已重试 {task.get("static_retry_count", 0)}/'
                   f'{int(task["quality_profile"]["quality"].get("static_sample_max_retries", 5))} 次'
                   if step['mode'] == 'static' and task.get('static_retry_count') else '')
            )

            if phase == "position_command":
                ok, reason = self._send_position_pair(step["inner_deg"], step["outer_deg"])
                self._log_event("INFO" if ok else "ERROR", "AUTO_POSITION_COMMAND",
                                f'{step["step_id"]}: inner={step["inner_deg"]}, outer={step["outer_deg"]}, '
                                f'speed={self.spin_position_speed.value()} deg/s; {reason}', ok)
                if not ok:
                    self._request_auto_abort(reason)
                    return
                task["phase"] = "wait_position"
                task["phase_started"] = now
                task["stable_since"] = None
                return

            if phase == "wait_position":
                speeds_zero = (abs(float(turntableData.inner_axis_speed)) < 0.05 and
                               abs(float(turntableData.outer_axis_speed)) < 0.05)
                in_place = bool(turntableState.is_inner_axis_in_place and turntableState.is_outer_axis_in_place)
                if speeds_zero and in_place and _feedback_at_target(step["inner_deg"], step["outer_deg"]):
                    if task["stable_since"] is None:
                        task["stable_since"] = now
                    elif now - task["stable_since"] >= 0.5:
                        task["phase"] = "settle"
                        task["phase_started"] = now
                        task["stable_since"] = None
                        self._log_event("INFO", "AUTO_POSITION_REACHED", step["step_id"], True)
                else:
                    task["stable_since"] = None
                if now - task["phase_started"] > POSITION_TIMEOUT_SECONDS:
                    self._request_auto_abort(f'{step["step_id"]} 等待转台到位超时。')
                return

            if phase == "settle":
                if not _feedback_at_target(step["inner_deg"], step["outer_deg"]):
                    self._request_auto_abort(f'{step["step_id"]} 静置期间实际角度偏离目标')
                    return
                if now - task["phase_started"] >= float(self.spin_settle_seconds.value()):
                    task["sample_frames"] = []
                    task["sample_started"] = now
                    mode = step["mode"]
                    task["phase"] = "command_rate" if mode == "rate" else "sample_static"
                    if mode != "rate":
                        task["sample_started"] = now
                    if mode != 'rate' and not self._auto_mark_step(step):
                        return
                    self._log_event("INFO", "AUTO_STEP_READY", step["step_id"], True)
                return

            if phase == "sample_static":
                if not _feedback_at_target(step["inner_deg"], step["outer_deg"]):
                    self._request_auto_abort(f'{step["step_id"]} 采样期间实际角度偏离目标')
                    return
                if now - task["sample_started"] >= float(step.get('sample_seconds', self.spin_sample_seconds.value())):
                    if not self._complete_static_sample(step):
                        self._retry_static_sample_or_abort(step, now)
                        return
                    self._advance_auto_step()
                return

            if phase == "command_rate":
                axis = INNER_ROTATION_AXIS if step["rotation_axis"] == "inner" else OUTER_ROTATION_AXIS
                speed = float(step["target_rate_dps"])
                if abs(speed) > PROTOTYPE_MAX_ABS_SPEED_DPS:
                    self._request_auto_abort("目标速率超过软件限幅。")
                    return
                result = self._send_axis_velocity(axis, speed)
                self._log_event("INFO" if result else "ERROR", "AUTO_RATE_COMMAND",
                                f'{step["step_id"]}: axis={step["rotation_axis"]}, target={speed} deg/s, accel=1 deg/s²',
                                result)
                if not result:
                    self._request_auto_abort(f'{step["step_id"]} 速率运动指令失败。')
                    return
                task["phase"] = "wait_rate"
                task["phase_started"] = now
                task["stable_since"] = None
                return

            if phase == "wait_rate":
                axis_speed = float(turntableData.inner_axis_speed if step["rotation_axis"] == "inner"
                                   else turntableData.outer_axis_speed)
                target = float(step["target_rate_dps"])
                tolerance = max(0.2, abs(target) * 0.15)
                if abs(axis_speed - target) <= tolerance:
                    if task["stable_since"] is None:
                        task["stable_since"] = now
                    elif now - task["stable_since"] >= 0.5:
                        task["phase"] = "sample_rate"
                        task["sample_started"] = now
                        task["sample_frames"] = []
                        if not self._auto_mark_step(step):
                            return
                        self._log_event("INFO", "AUTO_RATE_STABLE", f'{step["step_id"]}: actual={axis_speed:.4f} deg/s', True)
                else:
                    task["stable_since"] = None
                if now - task["phase_started"] > 30.0:
                    self._request_auto_abort(f'{step["step_id"]} 实际速率未能稳定到目标值；当前={axis_speed:.4f}°/s。')
                return

            if phase == "sample_rate":
                if now - task["sample_started"] >= float(step.get('sample_seconds', self.spin_sample_seconds.value())):
                    sample_count = len(task["sample_frames"])
                    if sample_count < task['quality_profile']['quality']['minimum_frames']:
                        task['last_rate_quality_error'] = (
                            f"有效帧不足 {sample_count}/{task['quality_profile']['quality']['minimum_frames']}；"
                            "请检查串口帧率、时间同步和采样时长")
                        self._retry_rate_sample_or_abort(step, now)
                        return
                    if not self._complete_rate_sample(step):
                        self._retry_rate_sample_or_abort(step, now)
                        return
                    axis = INNER_ROTATION_AXIS if step["rotation_axis"] == "inner" else OUTER_ROTATION_AXIS
                    stopped_ok = self._send_stop_axis(axis)
                    self._log_event("INFO" if stopped_ok else "ERROR", "AUTO_RATE_STOP",
                                    f'{step["step_id"]}: stop_axis={step["rotation_axis"]}', stopped_ok)
                    if not stopped_ok:
                        self._request_auto_abort(f'{step["step_id"]} 停车命令失败。')
                        return
                    task["phase"] = "wait_stop"
                    task["phase_started"] = now
                    task["stable_since"] = None
                return

            if phase in ("wait_stop", "wait_stop_retry"):
                speeds_zero = (abs(float(turntableData.inner_axis_speed)) < 0.05 and
                               abs(float(turntableData.outer_axis_speed)) < 0.05)
                if speeds_zero:
                    if task["stable_since"] is None:
                        task["stable_since"] = now
                    elif now - task["stable_since"] >= 0.5:
                        retrying = (phase == "wait_stop_retry")
                        task["phase"] = "position_command"
                        if not retrying:
                            task["index"] += 1
                            task["rate_retry_count"] = 0
                            task["last_rate_quality_error"] = ""
                        task["stable_since"] = None
                        self._update_auto_progress()
                else:
                    task["stable_since"] = None
                if now - task["phase_started"] > 20.0:
                    self._request_auto_abort(f'{step["step_id"]} 停车后实际速率未降到阈值。')
                return

        except Exception as exc:
            self._request_auto_abort(f"自动任务内部异常：{exc!r}")

    def _capture_auto_task_frame(self, frame):
        task = self._auto_task
        if task is None or task.get("phase") not in ("sample_static", "sample_rate"):
            return
        try:
            # 兼容稳定旧版IMU帧格式：旧采集队列不携带 ever_valid 标志。
            # 在标定页读取当前线程安全快照作为量程有效性依据，不修改串口采集模块。
            current = self._sensor_reading_snapshot()
            reading = {'acc_fs': frame.get('acc_fs', current['acc_fs']),
                       'gyro_fs': frame.get('gyro_fs', current['gyro_fs']),
                       'acc_fs_ever_valid': current['acc_fs_ever_valid'],
                       'gyro_fs_ever_valid': current['gyro_fs_ever_valid'],
                       'data_odr': frame.get('data_odr', current['data_odr'])}
            sensor = verify_sensor_config(task['quality_profile'], reading)
            if not sensor_config_consistent(task['sensor_configuration'], sensor):
                self._request_auto_abort('标定中途量程或ODR配置改变，数据不可用于拟合。')
                return
            acc_arr = np.asarray(frame.get("acc_g_arr", []), dtype=float)
            gyr_arr = np.asarray(frame.get("gyr_dps_arr", []), dtype=float)
            if acc_arr.ndim != 2 or acc_arr.shape[1] != 3 or len(acc_arr) == 0:
                return
            profile = task["quality_profile"]
            acc_mean, acc_count, acc_valid = frame_average_sanitized(
                acc_arr, profile['quality']['mad_sigma'], return_stats=True)
            gyr_mean, gyr_count, gyr_valid = (
                frame_average_sanitized(gyr_arr, profile['quality'].get('gyro_mad_sigma', profile['quality']['mad_sigma']), return_stats=True)
                if gyr_arr.ndim == 2 and gyr_arr.shape[1] == 3 and len(gyr_arr)
                else (None, 0, 0))
            # ACC 内参只依赖 ACC 与转台：GYRO 缺帧/离群也不剔除有效 ACC 帧。
            if acc_mean is None or (task['type'] != 'accel' and gyr_mean is None):
                return
            stamp_ns = int(frame.get('monotonic_time_ns', 0) or 0)
            feedback_ns = int(getattr(turntableData, 'last_update_monotonic_ns', 0) or 0)
            if not stamp_ns or not feedback_ns:
                return
            if stamp_ns / 1e9 < float(task.get('sample_started') or 0):
                return  # 上一个工况遗留在IMU队列里的帧，不能记入当前工况。
            age_ms = abs(stamp_ns - feedback_ns) / 1e6
            if age_ms > profile['quality']['feedback_age_max_ms']:
                return  # 无法证明参考反馈时间接近IMU帧时间，拒绝使用该帧。
            sample = {
                "acc": acc_mean.tolist(),
                "gyro": gyr_mean.tolist() if gyr_mean is not None else [None, None, None],
                "acc_raw_samples": acc_count,
                "acc_accepted_samples": acc_valid,
                "gyro_raw_samples": gyr_count,
                "gyro_accepted_samples": gyr_valid,
                "inner_deg": float(turntableData.inner_axis_position),
                "outer_deg": float(turntableData.outer_axis_position),
                "inner_rate_dps": float(turntableData.inner_axis_speed),
                "outer_rate_dps": float(turntableData.outer_axis_speed),
                "temp_c": float(frame.get('temp_c', float('nan'))),
                "feedback_delta_ms": age_ms,
                "time_iso": _now_iso(),
                "frame_update_count": int(frame.get('frame_update_count', 0)),
            }
            task['sample_frames'].append(sample)
        except ValueError as exc:
            self._request_auto_abort(f'IMU实时配置无效：{exc}')
        except Exception as exc:
            self._log_event("WARN", "AUTO_FRAME_CAPTURE_ERROR", repr(exc), False)

    def _complete_static_sample(self, step):
        task = self._auto_task
        sensor = {'accel': 'acc', 'gyro': 'gyro', 'align': 'both'}[task['type']]
        try:
            stats = robust_segment(task['sample_frames'], 'static', task['quality_profile'],
                                   static_sensor=sensor)
        except ValueError as exc:
            task['last_static_quality_error'] = str(exc)
            self._log_event('WARN', 'AUTO_STATIC_QUALITY_REJECTED',
                            f"{step['step_id']} 尝试 {task['static_retry_count'] + 1}/"
                            f"{int(task['quality_profile']['quality'].get('static_sample_max_retries', 5)) + 1}：{exc}", False)
            return False
        result = {'step_id': step['step_id'], 'split': step.get('split', 'validate'),
                  'inner_target_deg': step['inner_deg'], 'outer_target_deg': step['outer_deg'],
                  'attempts': task['static_retry_count'] + 1,
                  'retry_count': task['static_retry_count'], **stats}
        if task['type'] in ('accel', 'align'):
            task['pose_measurements'].append(result)
        else:
            result['reference'] = [0., 0., 0.]
            result['measured'] = stats['gyro_raw_mean_dps']
            task['gyro_static_samples'].append(result)
            if result['split'] == 'fit':
                task['gyro_fit_samples'].append(result)
            else:
                task['gyro_validation_samples'].append(result)
        self._log_event('INFO', 'AUTO_SAMPLE_COMPLETE',
                        f"{step['step_id']}: accepted={stats['accepted_frames']}/{stats['frame_count']} "
                        f"temp={stats['temperature_mean_c']:.2f}C; "
                        f"attempt={task['static_retry_count'] + 1}/"
                        f"{int(task['quality_profile']['quality'].get('static_sample_max_retries', 5)) + 1}", True)
        return True

    def _retry_static_sample_or_abort(self, step, now):
        """仅采样质量失败时重试。机械安全、通信、限位故障仍由状态机立即中止。"""
        task = self._auto_task
        if task is None:
            return
        previous_failures = int(task.get('static_retry_count', 0))
        max_retries = int(task['quality_profile']['quality'].get('static_sample_max_retries', 5))
        failed_attempt = previous_failures + 1
        detail = task.get('last_static_quality_error') or '静态采样质量未达标'
        task['static_retry_history'].append({
            'step_id': step['step_id'], 'attempt': failed_attempt,
            'reason': detail, 'timestamp': _now_iso(),
        })
        if previous_failures >= max_retries:
            self._log_event('ERROR', 'AUTO_STATIC_RETRIES_EXHAUSTED',
                            f"{step['step_id']} 共采样 {max_retries + 1} 次仍未通过；末次原因：{detail}", False)
            self._request_auto_abort(
                f"{step['step_id']} 共 {max_retries + 1} 次采样均不合格；末次原因：{detail}")
            return
        task['static_retry_count'] = failed_attempt
        task['sample_frames'] = []
        task['sample_started'] = None
        task['stable_since'] = None
        # 复用既有的到位标志、角度误差、低速稳定0.5s校验，然后再静置3秒。
        # 不重复发送任何运动指令，不推进姿态索引。
        task['phase'] = 'wait_position'
        task['phase_started'] = now
        self._log_event('WARN', 'AUTO_STATIC_RETRY',
                        f"{step['step_id']}：采样未通过（{detail}）；"
                        f"准备重试 {failed_attempt}/{max_retries}，先重新确认到位并静置。", False)
        self.label_auto_task.setText(
            f"{step['step_id']} 采样质量未通过：{detail}；"
            f"重试 {failed_attempt}/{max_retries}，正在重新确认位置与静置。"
        )

    def _retry_rate_sample_or_abort(self, step, now):
        """匀速段质控失败：先停车，反馈确认静止后重新定位并采样；不接受坏数据。

        机械/通信/急停类故障仍立即中止，不进入本重试通道。
        """
        task = self._auto_task
        if task is None:
            return
        failed = int(task.get('rate_retry_count', 0)) + 1
        limit = int(task['quality_profile']['quality'].get('rate_sample_max_retries', 3))
        detail = task.get('last_rate_quality_error') or '匀速段质量不合格'
        task['rate_retry_history'].append({
            'step_id': step['step_id'], 'attempt': failed,
            'reason': detail, 'timestamp': _now_iso(),
        })
        if failed > limit:
            self._request_auto_abort(
                f"{step['step_id']} 动态采样 {limit+1} 次不合格；末次原因：{detail}")
            return
        axis = INNER_ROTATION_AXIS if step['rotation_axis'] == 'inner' else OUTER_ROTATION_AXIS
        if not self._send_stop_axis(axis):
            self._request_auto_abort(f"{step['step_id']} 采样不合格且停止转轴指令失败：{detail}")
            return
        task['rate_retry_count'] = failed
        task['phase'] = 'wait_stop_retry'
        task['phase_started'] = now
        task['stable_since'] = None
        task['sample_started'] = None
        task['sample_frames'] = []
        self._log_event('WARN', 'AUTO_RATE_RETRY',
                        f"{step['step_id']}：{detail}；停车确认后重测 {failed}/{limit}", False)
        self.label_auto_task.setText(
            f"{step['step_id']} 匀速段质控失败：{detail}；安全停车后重测 {failed}/{limit}")

    def _complete_rate_sample(self, step):
        task = self._auto_task
        try:
            stats = robust_segment(task['sample_frames'], 'rate', task['quality_profile'],
                                   target_rate=step['target_rate_dps'], axis=step['rotation_axis'])
        except ValueError as exc:
            task['last_rate_quality_error'] = str(exc)
            self._log_event('WARN', 'AUTO_RATE_QUALITY_FAIL',
                            f"{step['step_id']} 第{task.get('rate_retry_count', 0)+1}次采样：{exc}", False)
            return False
        ref = _platform_angular_rate(stats['inner_actual_mean_deg'], stats['outer_actual_mean_deg'],
                                     stats['inner_rate_mean_dps'], stats['outer_rate_mean_dps'], task['axis_model'])
        result = {'step_id': step['step_id'], 'split': step.get('split','validate'),
                  'axis':step['rotation_axis'], 'target_rate_dps':step['target_rate_dps'],
                  'reference':ref.tolist(), 'measured':stats['gyro_raw_mean_dps'], **stats}
        if result['split'] == 'fit' and task['type'] == 'gyro':
            task['gyro_fit_samples'].append(result)
        else:
            task['gyro_validation_samples'].append(result)
        self._log_event('INFO', 'AUTO_RATE_SAMPLE_COMPLETE',
                        f"{step['step_id']}: ref={ref.tolist()}; accepted={stats['accepted_frames']}/{stats['frame_count']}", True)
        return True

    def _advance_auto_step(self):
        task = self._auto_task
        task["index"] += 1
        task["phase"] = "position_command"
        task["phase_started"] = time.monotonic()
        task["stable_since"] = None
        task["sample_started"] = None
        task["sample_frames"] = []
        task["static_retry_count"] = 0
        task["last_static_quality_error"] = ""
        self._update_auto_progress()
        if task["index"] >= len(task["steps"]):
            self._complete_auto_task()

    def _update_auto_progress(self):
        task = self._auto_task
        if task is None:
            return
        total = len(task["steps"])
        current = min(task["index"], total)
        percent = int(100 * current / max(total, 1))
        self.progress_auto_task.setValue(percent)
        step = self._current_step()
        if step:
            self.label_auto_task.setText(
                f'{task["type"]} 自动标定：第 {current + 1}/{total} 步 {step["step_id"]}；阶段={task["phase"]}'
            )
        else:
            self.label_auto_task.setText(f'{task["type"]} 自动标定：正在计算结果……')

    def _request_auto_abort(self, reason):
        task = self._auto_task
        if task is None:
            return
        if task["phase"] == "aborting":
            return
        task["abort_reason"] = str(reason)
        task["phase"] = "aborting"
        task["phase_started"] = time.monotonic()
        task["abort_stop_sent"] = False
        self.label_auto_task.setText("正在中止：发送停车命令并等待反馈……")
        self._log_event("ERROR", "AUTO_TASK_ABORT_REQUESTED", reason, False)

    def _abort_auto_button_clicked(self):
        self._request_auto_abort("用户点击中止自动标定。")

    def _model_rows(self, task):
        """统一原版采样统计与参考向量，拟合集和验证集严禁混用。"""
        if task['type'] == 'accel':
            rows = []
            for item in task['pose_measurements']:
                ref = _platform_gravity_vector(
                    item['inner_actual_mean_deg'], item['outer_actual_mean_deg'],
                    task['axis_model'], task['gravity_sign']).tolist()
                item['gravity_reference_platform_g'] = ref
                rows.append({'step_id':item['step_id'], 'split':item['split'],
                             'reference':ref, 'measured':item['acc_raw_mean_g'],
                             'temperature_mean_c':item['temperature_mean_c']})
            expected = (12, 12)
        elif task['type'] == 'gyro':
            rows = task['gyro_fit_samples'] + task['gyro_validation_samples']
            expected = (1+6*len(task['quality_profile']['rates']['fit_dps']),
                        1+6*len(task['quality_profile']['rates']['verify_dps']))
        else:
            raise ValueError('此任务不支持模型比较')
        fit_rows = [x for x in rows if x['split'] == 'fit']
        val_rows = [x for x in rows if x['split'] == 'validate']
        if (len(fit_rows), len(val_rows)) != expected:
            raise ValueError(f"独立工况不完整：得到 {len(fit_rows)}/{len(val_rows)}，要求 {expected}")
        return fit_rows, val_rows

    def _run_model_comparison(self, task):
        fit_rows, val_rows = self._model_rows(task)
        kind = 'acc' if task['type'] == 'accel' else 'gyro'
        report = compare_models(kind, fit_rows, val_rows, task['quality_profile'])
        report.update({'schema_version':1, 'calibration_type': 'ambient_model_comparison',
                       'created_at':_now_iso(), 'run_id':self.run_id,
                       'device_serial':task['device_serial'], 'axis_model':task['axis_model'],
                       'gravity_sign':task['gravity_sign'], 'fit_step_ids':[x['step_id'] for x in fit_rows],
                       'validation_step_ids':[x['step_id'] for x in val_rows],
                       'sensor_configuration':task['sensor_configuration'],
                       'quality_profile_snapshot':task['quality_profile'],
                       'approved_for_production':False,
                       'production_release':'PROHIBITED: 模型比较报告不自动更新原版生产标定参数'})
        paths = save_model_comparison(self.run_dir, kind, report)
        summary = ['三方案自动标定/独立测试：' + ('ACC' if kind=='acc' else 'GYRO'),
                   '同批转台拟合工况与独立验证工况；只产生候选报告，不覆盖原版标定文件。']
        for code in MODEL_NAMES:
            result = report['models'].get(code)
            if result is None:
                summary.append(f"{code}: 拟合失败：{report['errors'].get(code,'未知错误')}")
            else:
                val = result['independent_validation']; verdict=result['quality_gate']['verdict']
                summary.append(f"{code}: 矢量RMSE={val['rmse_vector']:.6g}，最大误差={val['max_vector_error']:.6g}，"
                               f"最大方向误差={val.get('max_direction_error_deg')!s}°，结论={verdict}")
        summary.append(f"按独立验证指标得到的候选方案：{report['candidate_model'] or '无合格候选'}（不代表正式放行）")
        for row_index, code in enumerate(MODEL_NAMES):
            info = report['models'].get(code)
            if info:
                val=info['independent_validation']
                values=[code, info['quality_gate']['verdict'],
                        f"{val['rmse_vector']:.6g}", f"{val['max_vector_error']:.6g}",
                        f"{val.get('max_direction_error_deg'):.4f}" if val.get('max_direction_error_deg') is not None else '—',
                        f"{val.get('max_norm_error_g'):.6g} g" if kind=='acc' else
                        f"{val.get('max_cross_axis_dps'):.6g} °/s" if val.get('max_cross_axis_dps') is not None else '—']
            else:
                values=[code, '拟合失败', '—','—','—','—']
            for column_index,value in enumerate(values):
                self.table_model_comparison.setItem(row_index,column_index,QTableWidgetItem(value))
        self.text_model_comparison.setPlainText('\n'.join(summary))
        self._last_model_comparison = serialize(report)
        for path in paths:
            self._log_event('INFO', 'MODEL_COMPARISON_REPORT_SAVED', path, True)
        self._manifest.setdefault('result_files', []).extend(os.path.basename(path) for path in paths)
        task['result_paths'].extend(paths)
        return report

    def _run_selected_model(self, task, model_id):
        """保留原版C方案完整输出；A/B单独生成候选文件，不覆盖原有生产文件。"""
        if model_id == 'C':
            return self._fit_accelerometer_result(task) if task['type']=='accel' else self._fit_gyroscope_result(task)
        fit_rows, val_rows = self._model_rows(task)
        kind='acc' if task['type']=='accel' else 'gyro'
        scored=score_model(kind,model_id,fit_rows,val_rows,task['quality_profile'])
        fitted=scored['fit']
        result={
            'schema_version':3,
            'calibration_type':f'{"accelerometer" if kind=="acc" else "gyroscope"}_ambient_candidate_model_{model_id}',
            'created_at':_now_iso(), 'run_id':self.run_id,
            'device_serial':task['device_serial'], 'axis_model':task['axis_model'],
            'gravity_sign':task['gravity_sign'], 'model_id':model_id,
            'model_name':MODEL_NAMES[model_id], 'model_note':fitted['model_note'],
            'coordinate_frame':'转台机械坐标系 P（A仅名义轴，未辨识安装旋转）',
            'raw_accel_bias_g' if kind=='acc' else 'raw_gyro_bias_dps':fitted['bias'].tolist(),
            'raw_to_platform_matrix':fitted['correction_matrix'].tolist(),
            'forward_platform_to_raw_matrix':fitted['forward_matrix'].tolist(),
            'axis_intrinsic_invariants':sensor_axis_invariants(fitted['forward_matrix']),
            'fit_quality':{'samples':len(fit_rows),'matrix_condition_number':fitted['condition_number'],
                           'rmse_vector':fitted['fit_vector_rmse'],
                           'max_vector_error':fitted['fit_vector_max']},
            'independent_validation':scored['independent_validation'],
            'quality_gate':scored['quality_gate'],
            'fit_measurements':fit_rows, 'validation_measurements':val_rows,
            'position_measurements':task['pose_measurements'] if kind=='acc' else [],
            'quality_profile_snapshot':task['quality_profile'],
            'production_release':'PROHIBITED: 新方案仅候选，不覆盖原版本正式参数',
            'status':scored['quality_gate']['verdict'],
        }
        if kind=='gyro':
            result['tested_rate_points_dps']=sorted({abs(float(x.get('target_rate_dps', 0)))
                                                 for x in fit_rows+val_rows if x.get('target_rate_dps')})
        return result

    def _complete_auto_task(self):
        task = self._auto_task
        if task is None:
            return
        try:
            if task['type'] == 'align':
                result = self._fit_alignment_result(task)
            elif task.get('compare_models'):
                report = self._run_model_comparison(task)
                candidate = report.get('candidate_model')
                if not report['models']:
                    self._finalize_auto_task(False, '三个方案全部拟合失败；原始数据与诊断已保存', show_dialog=True)
                else:
                    self._finalize_auto_task(bool(candidate),
                        f'三方案独立验证完成；候选方案：{candidate or "无合格候选"}；'
                        f'报告：{self.run_dir}（不覆盖原生产标定参数）',show_dialog=True)
                return
            else:
                result = self._run_selected_model(task,task.get('selected_model','C'))
            result['static_retry_history']=list(task.get('static_retry_history',[]))
            result['rate_retry_history']=list(task.get('rate_retry_history',[]))
            restrict_unverified_release(result,task['sensor_configuration'])
            result['sensor_configuration']=dict(task['sensor_configuration'])
            if task['type']=='align' and isinstance(result.get('combined_calibration'),dict):
                result['combined_calibration']['sensor_configuration']=dict(task['sensor_configuration'])
            # 只有原版C和六轴验证延续此前原位更新策略；新A/B作为候选写在运行目录。
            model_id=task.get('selected_model','C')
            if task['type'] != 'align' and model_id in ('A','B'):
                path=save_selected_model(self.run_dir,'acc' if task['type']=='accel' else 'gyro',model_id,result)
                self._manifest.setdefault('result_files',[]).append(os.path.basename(path))
            else:
                path=self._save_calibration_result(task,result)
            task['result_paths'].append(path)
            self._log_event('INFO','AUTO_TASK_RESULT_SAVED',f'结果文件={path}',True)
            verdict=result.get('quality_gate',{}).get('verdict','UNKNOWN')
            report_tip=''
            try:
                from calibration_excel_report import create_validation_workbook
                excel_path=create_validation_workbook(task['type'],result,self.run_dir)
                task['result_paths'].append(excel_path)
                self._manifest.setdefault('result_files',[]).append(os.path.basename(excel_path))
                self._log_event('INFO','CALIBRATION_EXCEL_SAVED',excel_path,True)
                report_tip=f'；Excel对比报告：{excel_path}'
                if model_id=='C' or task['type']=='align':
                    import shutil
                    latest=os.path.join(os.path.abspath(os.path.expanduser(self.line_output_root.text().strip())),
                                        f'validation_comparison_{task["type"]}_latest.xlsx')
                    try:
                        shutil.copy2(excel_path,latest)
                    except OSError as exc:
                        self._log_event('WARN','CALIBRATION_REPORT_LATEST_COPY_FAILED',repr(exc),False)
            except Exception as exc:
                self._log_event('ERROR','CALIBRATION_EXCEL_EXPORT_FAILED',repr(exc),False)
                report_tip=f'；Excel报告未生成：{exc}'
            if task['type'] != 'align' and model_id in ('A','B'):
                report_tip+='；新模型仅候选，不更新根目录原版参数'
            self._finalize_auto_task(verdict!='FAIL',f'流程完成；质量结论：{verdict}{report_tip}',show_dialog=True)
        except Exception as exc:
            self._log_event('ERROR','AUTO_TASK_FIT_FAILED',repr(exc),False)
            self._finalize_auto_task(False,f'拟合或验证失败：{exc}',show_dialog=True)

    def _fit_accelerometer_result(self, task):
        fit_rows = [x for x in task['pose_measurements'] if x['split'] == 'fit']
        val_rows = [x for x in task['pose_measurements'] if x['split'] == 'validate']
        if len(fit_rows) != 12 or len(val_rows) != 12:
            raise ValueError(f'ACC工况不完整：拟合 {len(fit_rows)}/12，验证 {len(val_rows)}/12')
        def vectors(rows):
            refs, raw = [], []
            for item in rows:
                ref = _platform_gravity_vector(item['inner_actual_mean_deg'],
                                               item['outer_actual_mean_deg'],
                                               task['axis_model'], task['gravity_sign']).tolist()
                item['gravity_reference_platform_g'] = ref
                refs.append(ref)
                raw.append(item['acc_raw_mean_g'])
            return refs, raw
        xfit,yfit = vectors(fit_rows)
        xval,yval = vectors(val_rows)
        fit = _fit_affine_reference(xfit, yfit, 'g','g')
        check = residual_statistics(xval,yval,fit['bias'],fit['correction_matrix'],'acc')
        design_cond = float(np.linalg.cond(np.column_stack([xfit, np.ones(len(xfit))])))
        temperatures = [x['temperature_mean_c'] for x in task['pose_measurements']]
        decision = evaluate(task['quality_profile'],'acc',check,fit['condition_number'],
                            design_cond, float(max(temperatures)-min(temperatures)))
        return {'schema_version':3,'calibration_type':'accelerometer_production_ambient',
                'created_at':_now_iso(),'run_id':self.run_id,'device_serial':task['device_serial'],'axis_model':task['axis_model'],
                'gravity_sign':task['gravity_sign'],
                'sampling_processing':'ACC每帧按3×1.4826×MAD三轴联合离群剔除后取帧均值；5秒内帧均值再次按3×稳健标准差MAD剔除后平均，每姿态仅一条均值参与拟合（sigma倍率以工艺快照为准）',
                'coordinate_frame':'转台圆盘公共机械坐标系 P；外X内Z模型需要轴符号和零位实机确认',
                'model':'raw = forward_matrix @ reference_P + bias',
                'raw_accel_bias_g':fit['bias'].tolist(),
                'raw_to_platform_matrix':fit['correction_matrix'].tolist(),
                'forward_platform_to_raw_matrix':fit['forward_matrix'].tolist(),
                'axis_intrinsic_invariants':sensor_axis_invariants(fit['forward_matrix']),
                'fit_quality':{'samples':len(fit_rows),'design_rank':fit['rank'],
                               'matrix_condition_number':fit['condition_number'],
                               'rmse_vector_g':fit['rmse_vector'], 'max_vector_error_g':fit['max_vector_error']},
                'independent_validation':check,'quality_gate':decision,
                'quality_profile_snapshot':task['quality_profile'],
                'position_measurements':task['pose_measurements'],
                'status':decision['verdict']}

    def _fit_gyroscope_result(self, task):
        fit_rows = task['gyro_fit_samples']
        val_rows = task['gyro_validation_samples']
        expected_fit = 1 + 6 * len(task['quality_profile']['rates']['fit_dps'])
        expected_val = 1 + 6 * len(task['quality_profile']['rates']['verify_dps'])
        if len(fit_rows) != expected_fit or len(val_rows) != expected_val:
            raise ValueError(f'GYRO工况不完整：拟合 {len(fit_rows)}/{expected_fit}，验证 {len(val_rows)}/{expected_val}')
        refs = [x['reference'] for x in fit_rows]
        measured = [x['measured'] for x in fit_rows]
        fit = _fit_affine_reference(refs, measured,'deg/s','deg/s')
        check = residual_statistics([x['reference'] for x in val_rows],
                                    [x['measured'] for x in val_rows],
                                    fit['bias'],fit['correction_matrix'],'gyro')
        design_cond = float(np.linalg.cond(np.column_stack([refs, np.ones(len(refs))])))
        temperatures = [x['temperature_mean_c'] for x in fit_rows+val_rows]
        decision = evaluate(task['quality_profile'],'gyro',check,fit['condition_number'],
                            design_cond,float(max(temperatures)-min(temperatures)))
        return {'schema_version':3,'calibration_type':'gyroscope_production_ambient',
                'created_at':_now_iso(),'run_id':self.run_id,'device_serial':task['device_serial'],'axis_model':task['axis_model'],
                'gravity_sign':task['gravity_sign'],
                'coordinate_frame':'转台圆盘公共机械坐标系 P',
                'model':'raw = forward_matrix @ angular_velocity_P + bias',
                'raw_gyro_bias_dps':fit['bias'].tolist(),
                'raw_to_platform_matrix':fit['correction_matrix'].tolist(),
                'forward_platform_to_raw_matrix':fit['forward_matrix'].tolist(),
                'axis_intrinsic_invariants':sensor_axis_invariants(fit['forward_matrix']),
                'fit_quality':{'samples':len(fit_rows),'design_rank':fit['rank'],
                               'matrix_condition_number':fit['condition_number'],
                               'rmse_vector_dps':fit['rmse_vector'],
                               'max_vector_error_dps':fit['max_vector_error']},
                'independent_validation':check, 'quality_gate':decision,
                'quality_profile_snapshot':task['quality_profile'],
                'fit_measurements':fit_rows, 'validation_measurements':val_rows,
                'tested_rate_points_dps':sorted({float(abs(x['target_rate_dps'])) for x in fit_rows + val_rows if 'target_rate_dps' in x}),
                'rate_scope_warning':'本次仅证明报告列出的离散角速度工况；不代表 20°/s、100°/s 或全量程精度。',
                'status':decision['verdict']}

    def _fit_alignment_result(self, task):
        root = os.path.abspath(os.path.expanduser(self.line_output_root.text().strip()))
        with open(os.path.join(root,'accel_calibration.json'),encoding='utf-8') as f:
            acc=json.load(f)
        with open(os.path.join(root,'gyro_calibration.json'),encoding='utf-8') as f:
            gyro=json.load(f)
        if acc.get('axis_model') != task['axis_model'] or gyro.get('axis_model') != task['axis_model']:
            raise ValueError('ACC/GYRO参考轴系与当前任务不同')
        if acc.get('device_serial') != task['device_serial'] or gyro.get('device_serial') != task['device_serial']:
            raise ValueError('两份标定文件不属于当前PCB唯一编号，拒绝跨设备混用')
        current_profile = task['quality_profile']['profile_id']
        if (acc.get('quality_gate',{}).get('profile_id') != current_profile or
                gyro.get('quality_gate',{}).get('profile_id') != current_profile):
            raise ValueError('前置标定使用的工艺版本与当前不同，拒绝混用')
        if acc.get('gravity_sign') != task['gravity_sign']:
            raise ValueError('ACC重力方向与当前任务不同')
        if acc.get('quality_gate',{}).get('metric_pass') is not True or gyro.get('quality_gate',{}).get('metric_pass') is not True:
            raise ValueError('ACC/GYRO前置标定的独立验证未通过；禁止合成六轴参数')
        if not acc.get('raw_accel_bias_g') or not gyro.get('raw_gyro_bias_dps'):
            raise ValueError('已有标定参数不完整')
        av = task['pose_measurements']; gv=task['gyro_validation_samples']
        expected_gv = 1 + 6 * len(task['quality_profile']['rates']['verify_dps'])
        if len(av)!=12 or len(gv)!=expected_gv:
            raise ValueError(f'六轴独立复核不完整：ACC {len(av)}/12、GYRO {len(gv)}/{expected_gv}')
        arefs=[]
        for item in av:
            ref = _platform_gravity_vector(item['inner_actual_mean_deg'],
                         item['outer_actual_mean_deg'],task['axis_model'],task['gravity_sign']).tolist()
            item['gravity_reference_platform_g'] = ref
            arefs.append(ref)
        acheck=residual_statistics(arefs,[x['acc_raw_mean_g'] for x in av],
              acc['raw_accel_bias_g'],acc['raw_to_platform_matrix'],'acc')
        gcheck=residual_statistics([x['reference'] for x in gv], [x['measured'] for x in gv],
              gyro['raw_gyro_bias_dps'],gyro['raw_to_platform_matrix'],'gyro')
        acond=float(np.linalg.cond(np.asarray(acc['raw_to_platform_matrix'])))
        gcond=float(np.linalg.cond(np.asarray(gyro['raw_to_platform_matrix'])))
        temps=[x['temperature_mean_c'] for x in av+gv]
        temp_span=float(max(temps)-min(temps))
        adecision=evaluate(task['quality_profile'],'acc',acheck,acond,1.0,temp_span)
        gdecision=evaluate(task['quality_profile'],'gyro',gcheck,gcond,1.0,temp_span)
        metric_pass=bool(adecision['metric_pass'] and gdecision['metric_pass'])
        # 六轴正式放行必须同时确认此前ACC、GYRO标定以及本次复核的量程/ODR来源。
        # 未确认的历史候选参数仍可进行试运行复核，但不可生成正式出厂PASS。
        approved=bool(task['quality_profile']['approved_for_production']
                      and acc.get('sensor_configuration', {}).get('verified_for_release') is True
                      and gyro.get('sensor_configuration', {}).get('verified_for_release') is True
                      and task.get('sensor_configuration', {}).get('verified_for_release') is True)
        verdict='FAIL' if not metric_pass else ('PASS' if approved else 'PILOT_PASS_NOT_RELEASED')
        return {'schema_version':3,'calibration_type':'six_axis_common_P_verification',
                'created_at':_now_iso(),'run_id':self.run_id,'device_serial':task['device_serial'],'axis_model':task['axis_model'],
                'coordinate_frame':'公共机械平台P；ACC、GYRO校正后均为P坐标表达，不额外乘旋转',
                'validation':{'acc':acheck,'gyro':gcheck,'acc_gates':adecision,'gyro_gates':gdecision,
                              'acc_static_poses':len(av),'gyro_rate_and_zero_segments':len(gv),
                              'warning':'使用共同转台参考校验两套映射；不等同于动态时间同步的ACC/GYRO互校'},
                'quality_profile_snapshot':task['quality_profile'],
                'validation_measurements':{'acc':av,'gyro':gv},
                'quality_gate':{'metric_pass':metric_pass, 'approved_for_production':approved,
                                'verdict':verdict,'profile_id':task['quality_profile']['profile_id']},
                'combined_calibration':{
                    'schema_version':3,'coordinate_frame':'P','device_serial':task['device_serial'],'axis_model':task['axis_model'],
                    'accelerometer':{'raw_bias_g':acc['raw_accel_bias_g'],
                                     'raw_to_platform_matrix':acc['raw_to_platform_matrix']},
                    'gyroscope':{'raw_bias_dps':gyro['raw_gyro_bias_dps'],
                                 'raw_to_platform_matrix':gyro['raw_to_platform_matrix']},
                    'release_verdict':verdict,
                    'warning':'未对传感器再做相对旋转；必须有正式批准的工艺阈值才能签发PASS'},
                'status':verdict}

    def _save_calibration_result(self, task, result):
        root = os.path.abspath(os.path.expanduser(self.line_output_root.text().strip()))
        os.makedirs(root, exist_ok=True)
        task_type = task["type"]
        if task_type == "accel":
            filename = "accel_calibration.json"
            self._last_accel_result = result
        elif task_type == "gyro":
            filename = "gyro_calibration.json"
            self._last_gyro_result = result
        else:
            filename = "alignment.json"
            self._last_alignment_result = result
        # 失败参数仅归档到本次run，不覆盖上次合格候选。
        root_path = os.path.join(root, filename)
        run_path = os.path.join(self.run_dir, filename)
        qualified = bool(result.get('quality_gate', {}).get('metric_pass'))
        result['result_file_latest'] = root_path if qualified else None
        result['result_file_run'] = run_path
        for path in ((root_path, run_path) if qualified else (run_path,)):
            with open(path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
                f.write("\n")
        if task_type == 'align' and qualified:
            final = result['combined_calibration']
            # 试运行指标未批准时只保存候选，不生成可供设备误用的正式final参数。
            name = 'imu_calibration_final.json' if result['quality_gate']['approved_for_production'] else 'imu_calibration_pilot_candidate.json'
            for path in (os.path.join(root,name), os.path.join(self.run_dir,name)):
                with open(path,'w',encoding='utf-8') as f:
                    json.dump(final,f,ensure_ascii=False,indent=2)
                    f.write('\n')
        self._manifest["result_files"] = ([os.path.basename(root_path)] if qualified else []) + [os.path.basename(run_path)]
        self._manifest["axis_model"] = task["axis_model"]
        self._manifest["fit_quality"] = result.get("fit_quality", result.get("validation", {}))
        return root_path if qualified else run_path

    def _finalize_auto_task(self, success, reason, show_dialog=False):
        task = self._auto_task
        if task is None:
            return
        task_type = task.get("type", "unknown")
        self.auto_timer.stop()
        self._auto_task = None
        self.button_accel_plan.setEnabled(True)
        self.button_gyro_plan.setEnabled(True)
        self.button_alignment_check.setEnabled(True)
        self.button_compare_acc.setEnabled(True)
        self.button_compare_gyro.setEnabled(True)
        self.combo_calibration_model.setEnabled(True)
        self.button_record_start.setEnabled(True)
        self.button_abort_auto.setEnabled(False)
        self._set_turntable_manual_controls_locked(False)
        if success:
            self.progress_auto_task.setValue(100)
            self.label_auto_task.setText(f"自动标定完成：{task_type}；{reason}")
            self._log_event("INFO", "AUTO_TASK_FINISHED", f"{task_type}: {reason}", True)
        else:
            self.label_auto_task.setText(f"自动标定未完成：{task_type}；{reason}")
            self._log_event("ERROR", "AUTO_TASK_FAILED", f"{task_type}: {reason}", False)
        if not success and task_type == 'gyro' and self.run_dir:
            # 发生在哪一项检查、使用何限值：即便未完成全部标定，也留独立诊断文件。
            current_index = int(task.get('index', 0))
            steps = task.get('steps', [])
            current = steps[current_index] if 0 <= current_index < len(steps) else None
            frames = task.get('sample_frames', [])
            diagnostic = {
                'type': 'GYRO_QUALITY_OR_ABORT_DIAGNOSTICS',
                'run_id': self.run_id, 'created_at': _now_iso(),
                'step': current, 'phase': task.get('phase'),
                'abort_reason': task.get('abort_reason') or str(reason),
                'last_static_quality_error': task.get('last_static_quality_error'),
                'last_rate_quality_error': task.get('last_rate_quality_error'),
                'static_retry_history': task.get('static_retry_history', []),
                'rate_retry_history': task.get('rate_retry_history', []),
                'last_segment_frame_count': len(frames),
                'last_segment_gyro_mean_dps': np.mean([f['gyro'] for f in frames], axis=0).tolist() if frames else None,
                'last_segment_gyro_std_dps': np.std([f['gyro'] for f in frames], axis=0).tolist() if frames else None,
                'quality_limits': task.get('quality_profile', {}).get('quality', {}),
                'acceptance_limits': task.get('quality_profile', {}).get('acceptance', {}),
                'sensor_configuration': task.get('sensor_configuration'),
            }
            try:
                diagnostic_path = os.path.join(self.run_dir, 'gyro_failure_diagnostics.json')
                with open(diagnostic_path, 'w', encoding='utf-8') as diagnostic_file:
                    json.dump(diagnostic, diagnostic_file, ensure_ascii=False, indent=2)
                self._log_event('WARN', 'GYRO_FAILURE_DIAGNOSTICS_SAVED', diagnostic_path, True)
            except OSError as exc:
                self._log_event('WARN', 'GYRO_FAILURE_DIAGNOSTICS_WRITE_FAILED', repr(exc), False)
        if self.recording:
            self._manifest["auto_task"] = {"type": task_type, "success": bool(success),
                                           "device_serial": task.get('device_serial'),
                                           "static_retry_history": list(task.get('static_retry_history', [])),
                                           "rate_retry_history": list(task.get('rate_retry_history', [])),
                                           "message": str(reason),
                                           "end_time_local": _now_iso()}
            self._stop_recording()
        self._update_live_status()
        if show_dialog:
            if success:
                QMessageBox.information(
                    self.page, "自动标定任务完成",
                    f"{task_type} 任务已执行并完成计算。\n\n数据目录：{self.run_dir}\n"
                    f"质量结论：{reason}\n试运行工艺尚未获批，不得作为正式出厂合格证明。"
                )
            else:
                QMessageBox.warning(
                    self.page, "自动标定未完成",
                    f"{reason}\n\n已尽可能发送两轴停车命令；请确认转台实际已停止。\n"
                    f"已采集的数据保存在：{self.run_dir}"
                )

    def _abort_auto_task(self, reason):
        self._request_auto_abort(reason)

    def _complete_auto_task_noop(self):
        return

    def _generate_accel_plan(self):
        """只生成与实际生产标定一致的12+12参考姿态列表，不驱动设备。"""
        steps = acc_fit_steps() + acc_verify_steps()
        payload = {'schema_version':3, 'plan_type':'accelerometer_pilot_12_fit_12_validate',
                   'created_at':_now_iso(), 'axis_model':self._current_axis_model(),
                   'position_speed_dps':self.spin_position_speed.value(),
                   'steps':steps, 'does_not_command_hardware':True}
        self._write_plan_file('accel_production_24_pose_plan.json', payload)

    def _generate_gyro_plan(self):
        """只生成与自动任务一致的低速工况，高速候选单独标注禁止执行。"""
        try:
            profile = load_profile(_PROJECT_DIR)
        except (ValueError, KeyError, OSError) as exc:
            QMessageBox.warning(self.page, '工艺配置不合法', str(exc))
            return
        steps = gyro_fit_steps(profile) + gyro_verify_steps(profile)
        payload = {'schema_version':3, 'plan_type':'gyroscope_pilot_fit_validate',
                   'created_at':_now_iso(), 'axis_model':self._current_axis_model(),
                   'active_fit_rates_dps':profile['rates']['fit_dps'],
                   'active_verify_rates_dps':profile['rates']['verify_dps'],
                   'proposed_after_turntable_approval':profile['rates'].get('proposed_after_turntable_approval'),
                   'software_max_abs_rate_dps':PROTOTYPE_MAX_ABS_SPEED_DPS,
                   'sensor_configuration':profile['sensor_config'],
                   'steps':steps, 'does_not_command_hardware':True,
                   'warning':'待核准的高速候选不参与自动执行，不能直接修改活动限速。'}
        self._write_plan_file('gyro_production_rate_plan.json', payload)

    def _check_alignment_inputs(self):
        self._start_alignment_auto()

    def _refresh_ports(self):
        previous = self.combo_port.currentData() if hasattr(self, "combo_port") else None
        if not previous and self.turntable_form is not None:
            previous = getattr(self.turntable_form, "turntable_2TD600_comm_port", "")
        self.combo_port.clear()
        ports = []
        try:
            ports = list(serial.tools.list_ports.comports())
        except Exception as exc:
            self._log_event("WARN", "PORT_ENUM_ERROR", str(exc), False)
        for port_info in ports:
            self.combo_port.addItem(f"{port_info.device} — {port_info.description}", port_info.device)
        known_port = getattr(self.turntable_form, "turntable_2TD600_comm_port", "") if self.turntable_form else ""
        if known_port and all(self.combo_port.itemData(i) != known_port for i in range(self.combo_port.count())):
            self.combo_port.addItem(f"{known_port}（配置值，当前未枚举到）", known_port)
        if self.combo_port.count() == 0:
            self.combo_port.addItem("未发现串口", "")
        target = previous or known_port
        index = self.combo_port.findData(target)
        if index >= 0:
            self.combo_port.setCurrentIndex(index)
        self._update_connection_ui()

    def _browse_output_root(self):
        current = self.line_output_root.text().strip()
        start_dir = current if os.path.isdir(current) else os.path.expanduser("~")
        path = QFileDialog.getExistingDirectory(self.page, "选择 IMU 标定数据保存根目录", start_dir)
        if path:
            self.line_output_root.setText(path)

    def _is_turntable_connected(self):
        return (
            self.turntable_form is not None
            and self.turntable_form.button_TurntableCommPortOpen.text() == "关闭转台"
            and turntableComm.turntable_model == "2TD600"
            and turntableComm.thread_instance is not None
        )

    def _toggle_turntable_connection(self):
        if self.turntable_form is None:
            QMessageBox.warning(self.page, "无法连接", "未找到现有转台控制模块。")
            return
        button_text = self.turntable_form.button_TurntableCommPortOpen.text()
        connected_model = turntableComm.turntable_model
        if button_text == "关闭转台":
            if connected_model != "2TD600":
                QMessageBox.warning(
                    self.page, "转台型号不匹配",
                    "当前已连接的不是 2TD600。请先在原“转台”页面按原流程断开连接，再从本页连接 2TD600。"
                )
                return
            if abs(float(turntableData.inner_axis_speed)) > 0.05 or abs(float(turntableData.outer_axis_speed)) > 0.05:
                self._stop_all_axes()
                QMessageBox.warning(
                    self.page, "等待转台停止",
                    "检测到转台仍在运动，已发送两轴停车命令。请确认两轴实际速率接近 0°/s 后，再次点击断开连接。"
                )
                return
            self._log_event("INFO", "TURNTABLE_DISCONNECT_REQUEST", "请求通过现有转台控制模块断开 2TD600。", True)
            self.turntable_form.button_TurntableCommPortOpen_Click()
            self._update_connection_ui()
            return

        port = self.combo_port.currentData()
        if not port:
            QMessageBox.warning(self.page, "没有可用串口", "请先刷新并选择 2TD600 所连接的 COM 端口。")
            return
        self.turntable_form.turntable_2TD600_comm_port = str(port)
        self.turntable_form.comboBox_TurntableModelSelect.setCurrentText("2TD600")
        self._log_event("INFO", "TURNTABLE_CONNECT_REQUEST", f"请求连接 2TD600，端口={port}，波特率=115200。", True)
        try:
            self.turntable_form.button_TurntableCommPortOpen_Click()
        except Exception as exc:
            self._log_event("ERROR", "TURNTABLE_CONNECT_EXCEPTION", repr(exc), False)
            QMessageBox.critical(self.page, "连接异常", f"连接转台时发生异常：\n{exc}")
        connected = self._is_turntable_connected()
        self._log_event(
            "INFO" if connected else "ERROR",
            "TURNTABLE_CONNECTED" if connected else "TURNTABLE_CONNECT_FAILED",
            f"端口={port}; 当前通讯线程={'已启动' if turntableComm.thread_instance is not None else '未启动'}",
            connected
        )
        self._update_connection_ui()

    def _update_connection_ui(self):
        connected = self._is_turntable_connected()
        if hasattr(self, "label_turntable_status"):
            if connected and turntableData.is_turntable_data_available:
                self.label_turntable_status.setText("转台：2TD600 已连接，反馈数据有效")
                self.label_turntable_status.setStyleSheet("color: #166534; font-weight: 600;")
            elif connected:
                self.label_turntable_status.setText("转台：已连接，等待反馈数据")
                self.label_turntable_status.setStyleSheet("color: #a16207; font-weight: 600;")
            else:
                self.label_turntable_status.setText("转台：未连接（请在“转台”页面连接）")
                self.label_turntable_status.setStyleSheet("color: #64748b;")
        if hasattr(self, "label_imu_status"):
            if not tiltSensorComm.is_serial_opened:
                self.label_imu_status.setText("IMU：未连接（请在倾角仪校准页打开串口）")
                self.label_imu_status.setStyleSheet("color: #64748b;")
            elif tiltSensorComm.is_data_available and tiltSensorRawData.data_update_count > 0:
                self.label_imu_status.setText(
                    f"IMU：已连接 / 数据更新 {tiltSensorRawData.data_update_count} 帧 / ODR {tiltSensorRawData.data_odr} Hz"
                )
                self.label_imu_status.setStyleSheet("color: #166534; font-weight: 600;")
            else:
                self.label_imu_status.setText("IMU：串口已打开，等待有效数据")
                self.label_imu_status.setStyleSheet("color: #a16207;")
        if hasattr(self, "label_turntable_feedback"):
            self.label_turntable_feedback.setText(
                f"内轴：位置 {turntableData.inner_axis_position:.4f}°，速率 {turntableData.inner_axis_speed:.4f}°/s"
                f"    外轴：位置 {turntableData.outer_axis_position:.4f}°，速率 {turntableData.outer_axis_speed:.4f}°/s"
            )
        if hasattr(self, "label_record_status"):
            if self.recording:
                self.label_record_status.setText(
                    f"记录中：{self.run_id} | IMU {self._imu_rows} 行 | 转台反馈 {self._turntable_rows} 行"
                )
                self.label_record_status.setStyleSheet("color: #166534; font-weight: 600;")
            else:
                self.label_record_status.setText("记录：未开始" if not self.run_dir else f"最近一次：{self.run_dir}")
                self.label_record_status.setStyleSheet("color: #64748b;")

    def _log_event(self, level, event_name, details, success):
        stamp = _now_iso()
        message = f"[{stamp}] {level:<5} {event_name}: {details}"
        if hasattr(self, "text_log"):
            self.text_log.appendPlainText(message)
        if self.recording and self._writers.get("events") is not None:
            try:
                self._writers["events"].writerow([
                    stamp, time.time_ns(), time.perf_counter_ns(), level, event_name,
                    str(details), bool(success)
                ])
                self._event_rows += 1
                self._files["events"].flush()
            except Exception as exc:
                self._last_poll_error = f"事件日志写入失败：{exc}"

    def _motion_precheck(self, axis):
        if not self._is_turntable_connected() or not turntableData.is_turntable_data_available:
            return False, "2TD600 未连接或尚未取得有效反馈。"
        if not self.check_safety.isChecked():
            return False, "请先勾选安全确认项。"
        # 直接读取安全相关状态；未知/读取失败按不安全处理。
        try:
            with turntableComm.thread_lock:
                enabled = twoTD600_getAxisEnable(axis)
                normal = twoTD600_getAxisNormal(axis)
                driver_fault = twoTD600_getAxisDriverFault(axis)
                over_speed = twoTD600_getAxisOverSpeed(axis)
                over_diff = twoTD600_getAxisOverDiff(axis)
                over_voltage = twoTD600_getAxisOverVoltage(axis)
                up_limit = twoTD600_getAxisUpLimit(axis)
                down_limit = twoTD600_getAxisDownLimit(axis)
        except Exception as exc:
            return False, f"读取转台安全状态失败：{exc}"
        if enabled is not True:
            return False, "所选轴未使能或使能状态未知。"
        if normal is not True:
            return False, "所选轴未处于正常状态或状态未知。"
        fault_values = {
            "驱动故障": driver_fault, "超速": over_speed, "超差": over_diff,
            "电压超限": over_voltage
        }
        active_faults = [name for name, value in fault_values.items() if value is not False]
        if active_faults:
            return False, "安全状态异常或无法确认：" + "、".join(active_faults)
        if up_limit is not False or down_limit is not False:
            return False, "所选轴触碰限位或限位状态未知，拒绝启动运动。"
        return True, "检查通过"

    def _start_velocity_motion(self):
        axis = int(self.combo_axis.currentData())
        speed = float(self.spin_speed.value())
        accel = float(self.spin_accel.value())
        if abs(speed) < 1e-9:
            QMessageBox.warning(self.page, "目标速率无效", "目标速率不能为 0；如需停止，请使用停车按钮。")
            return
        if abs(speed) > PROTOTYPE_MAX_ABS_SPEED_DPS:
            QMessageBox.warning(self.page, "超过第一版限幅", f"第一版软件限幅为 ±{PROTOTYPE_MAX_ABS_SPEED_DPS:g}°/s。")
            return
        if not self.recording:
            answer = QMessageBox.question(
                self.page, "当前未记录实验",
                "当前没有开始实验记录，本次运动命令只显示在界面日志，不会写入 events.csv。\n"
                "为保证实验可追溯，建议先开始实验记录。仍要发送运动指令吗？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if answer != QMessageBox.Yes:
                return
        ok, reason = self._motion_precheck(axis)
        if not ok:
            self._log_event("ERROR", "VELOCITY_COMMAND_REJECTED", reason, False)
            QMessageBox.warning(self.page, "未执行运动", reason)
            return
        try:
            with turntableComm.thread_lock:
                result = twoTD600_SetAxisVelocity(axis, speed, accel)
        except Exception as exc:
            result = False
            reason = repr(exc)
        else:
            reason = f"axis={axis}, target_speed_dps={speed:.6f}, target_accel_dps2={accel:.6f}"
        self._log_event("INFO" if result else "ERROR", "VELOCITY_COMMAND", reason, bool(result))
        if result:
            QMessageBox.information(
                self.page, "指令已发送",
                "转台已接受速率运动指令。请继续观察实际角速度和状态；这不代表实际速率已稳定到目标值。"
            )
        else:
            QMessageBox.critical(self.page, "运动指令失败", f"转台未确认接受运动指令。\n{reason}")
        self._update_live_status()

    def _stop_selected_axis(self):
        axis = int(self.combo_axis.currentData())
        if not self._is_turntable_connected():
            self._log_event("WARN", "STOP_SELECTED_REJECTED", "2TD600未连接，未发送停车命令。", False)
            QMessageBox.warning(self.page, "转台未连接", "当前没有已连接的 2TD600，无法发送软件停车命令。")
            return
        try:
            with turntableComm.thread_lock:
                result = twoTD600_SetAxisStop(axis)
        except Exception as exc:
            result = False
            details = repr(exc)
        else:
            details = f"axis={axis}; stop_command_accepted={bool(result)}"
        self._log_event("INFO" if result else "ERROR", "STOP_SELECTED_AXIS", details, bool(result))
        if not result:
            QMessageBox.warning(self.page, "停车指令失败", details)
        self._update_live_status()

    def _stop_all_axes(self):
        if not self._is_turntable_connected():
            self._log_event("WARN", "STOP_ALL_REJECTED", "2TD600 未连接，未发送停车命令。", False)
            QMessageBox.warning(self.page, "转台未连接", "当前没有已连接的 2TD600，无法发送软件停车命令。")
            return
        results = {}
        try:
            with turntableComm.thread_lock:
                results["inner"] = bool(twoTD600_SetAxisStop(INNER_ROTATION_AXIS))
                results["outer"] = bool(twoTD600_SetAxisStop(OUTER_ROTATION_AXIS))
        except Exception as exc:
            results["exception"] = repr(exc)
        success = results.get("inner") is True and results.get("outer") is True
        self._log_event("INFO" if success else "ERROR", "STOP_ALL_AXES", json.dumps(results, ensure_ascii=False), success)
        if not success:
            QMessageBox.warning(self.page, "停车结果需确认", f"停车命令返回：{results}\n请检查转台实际速度和硬件状态。")
        self._update_live_status()

    def _toggle_recording(self):
        """实验原始数据记录采用唯一按钮；自动任务期间不允许手动停止。"""
        if getattr(self, '_auto_task', None) is not None:
            QMessageBox.warning(self.page, "自动标定正在运行", "请使用‘中止自动标定’；不能手动停止自动任务的数据记录。")
            return
        if self.recording:
            self._stop_recording()
        else:
            self._start_recording()
        self._sync_imu_record_button()

    def _sync_imu_record_button(self):
        active = bool(self.recording)
        label = "停止记录" if active else "开始记录"
        if self.button_record_start.text() != label:
            self.button_record_start.setText(label)
        if self.button_record_start.property("recording") != active:
            self.button_record_start.setProperty("recording", active)
            style = self.button_record_start.style()
            style.unpolish(self.button_record_start)
            style.polish(self.button_record_start)
            self.button_record_start.update()

    def _start_recording(self):
        if self.recording:
            return
        if csv_is_enabled():
            QMessageBox.warning(
                self.page, "已有另一份 IMU 记录正在进行",
                "请先在左侧“数据记录”页点击“停止记录”。本页会生成包含 IMU 与转台反馈的完整实验包，"
                "同时启用两份记录容易混淆文件来源。"
            )
            return
        if not tiltSensorComm.is_serial_opened or tiltSensorRawData.data_update_count <= 0:
            QMessageBox.warning(
                self.page, "IMU 尚未就绪",
                "请先在“倾角仪校准”页面打开 IMU 串口，并确认已有有效数据，再开始实验记录。"
            )
            return
        if not self._is_turntable_connected():
            answer = QMessageBox.question(
                self.page, "转台尚未连接",
                "当前没有连接 2TD600。本次仍可记录 IMU 数据，但不会有有效的转台反馈文件内容。\n确定继续吗？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if answer != QMessageBox.Yes:
                return

        raw_root_dir = self.line_output_root.text().strip()
        raw_run_id = self.line_run_id.text().strip()
        root_dir = os.path.abspath(os.path.expanduser(raw_root_dir)) if raw_root_dir else ""
        safe_run_id = re.sub(r"[^A-Za-z0-9._-]+", "_", raw_run_id).strip("._-")
        if not root_dir or not safe_run_id:
            QMessageBox.warning(self.page, "信息不完整", "请填写有效的实验编号和保存根目录。")
            return
        run_dir = os.path.join(root_dir, safe_run_id)
        if os.path.exists(run_dir):
            QMessageBox.warning(
                self.page, "实验目录已存在",
                f"为避免覆盖原始数据，程序不会复用已有目录：\n{run_dir}\n请更换实验编号。"
            )
            return
        try:
            os.makedirs(root_dir, exist_ok=True)
            os.mkdir(run_dir)
            self.run_dir = run_dir
            self.run_id = safe_run_id
            self.run_start_iso = _now_iso()
            self._imu_rows = 0
            self._turntable_rows = 0
            self._marker_rows = 0
            self._event_rows = 0
            self._files = {}
            self._writers = {}

            self._files["imu"] = open(os.path.join(run_dir, "imu_raw.csv"), "w", encoding="utf-8-sig", newline="", buffering=1024 * 1024)
            self._writers["imu"] = csv.writer(self._files["imu"])
            self._writers["imu"].writerow([
                "sample_time_iso_est", "host_unix_ns_est", "host_monotonic_ns_est",
                "frame_update_count", "sample_index_in_batch", "mcu_tick_ms",
                "mcu_sample_ms_est", "frame_interval_ms", "data_unread", "data_odr_hz",
                "fifo_state", "acc_fs_g", "gyro_fs_dps",
                "acc_x_raw", "acc_y_raw", "acc_z_raw", "gyr_x_raw", "gyr_y_raw", "gyr_z_raw",
                "acc_x_g", "acc_y_g", "acc_z_g", "gyr_x_dps", "gyr_y_dps", "gyr_z_dps",
                "temp_raw", "temp_c"
            ])

            self._files["turntable"] = open(os.path.join(run_dir, "turntable_feedback.csv"), "w", encoding="utf-8-sig", newline="", buffering=256 * 1024)
            self._writers["turntable"] = csv.writer(self._files["turntable"])
            self._writers["turntable"].writerow([
                "feedback_time_iso", "host_unix_ns", "host_monotonic_ns",
                "feedback_update_count", "feedback_age_ms",
                "inner_position_deg", "inner_speed_dps", "outer_position_deg", "outer_speed_dps",
                "inner_run_mode", "outer_run_mode", "inner_enable", "outer_enable",
                "inner_normal", "outer_normal", "inner_find_zero", "outer_find_zero",
                "inner_up_limit", "inner_down_limit", "outer_up_limit", "outer_down_limit",
                "inner_over_speed", "outer_over_speed", "inner_over_diff", "outer_over_diff",
                "inner_driver_fault", "outer_driver_fault", "inner_over_voltage", "outer_over_voltage"
            ])

            self._files["events"] = open(os.path.join(run_dir, "events.csv"), "w", encoding="utf-8-sig", newline="", buffering=64 * 1024)
            self._writers["events"] = csv.writer(self._files["events"])
            self._writers["events"].writerow([
                "timestamp_iso", "host_unix_ns", "host_monotonic_ns", "level", "event", "details", "success"
            ])

            self._files["markers"] = open(os.path.join(run_dir, "step_markers.csv"), "w", encoding="utf-8-sig", newline="", buffering=64 * 1024)
            self._writers["markers"] = csv.writer(self._files["markers"])
            self._writers["markers"].writerow([
                "timestamp_iso", "host_unix_ns", "host_monotonic_ns",
                "step_id", "experiment_type", "notes",
                "inner_position_deg", "inner_speed_dps", "outer_position_deg", "outer_speed_dps",
                "imu_frame_update_count", "imu_mcu_tick_ms"
            ])

            self._manifest = {
                "schema_version": 1,
                "application_revision": APP_REVISION,
                "run_id": self.run_id,
                "experiment_type": self.combo_experiment_type.currentText(),
                "start_time_local": self.run_start_iso,
                "end_time_local": None,
                "status": "recording",
                "host_platform": platform.platform(),
                "python_version": platform.python_version(),
                "turntable": {
                    "model": turntableComm.turntable_model or None,
                    "port": getattr(self.turntable_form, "turntable_2TD600_comm_port", None),
                    "axis_mapping": {"inner": INNER_ROTATION_AXIS, "outer": OUTER_ROTATION_AXIS},
                    "feedback_polling": "使用现有转台轮询线程缓存值；记录主机时间戳和更新计数，不代表硬件时钟同步。"
                },
                "imu": {
                    "model": "ASM330 (项目当前数据模块)",
                    "serial_open": bool(tiltSensorComm.is_serial_opened),
                    "port": str(tiltSensorComm.comm_port),
                    "baudrate": int(tiltSensorComm.baudrate),
                    "acc_fs_g": int(tiltSensorRawData.acc_fs),
                    "gyro_fs_dps": int(tiltSensorRawData.gyro_fs),
                    "data_odr_hz": int(tiltSensorRawData.data_odr)
                },
                "coordinate_convention": "尚需在实验规程中明确转台内外轴正方向、安装坐标系P及IMU轴方向；本文件不自动推断坐标变换。",
                "timestamp_note": "imu_raw.csv 中样本级主机时间戳由帧接收时间和帧间隔估算；mcu_sample_ms_est 由帧tick和帧间隔估算。应结合设备时钟和通讯延迟评估同步不确定度。",
                "notes": self.line_step_note.text().strip(),
                "files": ["imu_raw.csv", "turntable_feedback.csv", "events.csv", "step_markers.csv", "manifest.json"]
            }
            self._write_manifest()
            self.recording = True
            self._imu_update_count_last = int(tiltSensorRawData.data_update_count)
            turntable_connected = self._is_turntable_connected()
            self._turntable_queue_active = bool(turntable_connected)
            self._turntable_update_count_last = int(turntableData.update_count) if turntable_connected else None
            self._last_imu_queue_drops = 0
            self._last_turntable_queue_drops = 0
            tilt_sensor_calibration_queue_set(True, clear=True)
            turntable_feedback_queue_set(turntable_connected, clear=True)
            self._last_flush_monotonic = time.monotonic()
            self.record_timer.start()
            self._sync_imu_record_button()
            self.button_mark_step.setEnabled(True)
            self.line_run_id.setReadOnly(True)
            self.line_device_sn.setReadOnly(True)
            self.line_output_root.setReadOnly(True)
            self.button_browse_output.setEnabled(False)
            self._log_event("INFO", "RECORD_START", f"实验记录开始；目录={run_dir}", True)
            self._update_live_status()
        except Exception as exc:
            self.recording = False
            self.record_timer.stop()
            try:
                tilt_sensor_calibration_queue_set(False, clear=False)
                turntable_feedback_queue_set(False, clear=False)
            except Exception:
                pass
            self._turntable_queue_active = False
            for handle in self._files.values():
                try:
                    handle.close()
                except Exception:
                    pass
            self._files = {}
            self._writers = {}
            self._log_event("ERROR", "RECORD_START_FAILED", repr(exc), False)
            QMessageBox.critical(self.page, "开始记录失败", f"创建实验记录文件失败：\n{exc}\n\n已创建的目录（如有）：\n{run_dir}")
            self._update_live_status()

    def _write_manifest(self):
        if not self.run_dir:
            return
        self._manifest["status"] = "recording" if self.recording else self._manifest.get("status", "stopped")
        self._manifest["row_counts"] = {
            "imu_raw.csv": self._imu_rows,
            "turntable_feedback.csv": self._turntable_rows,
            "events.csv": self._event_rows,
            "step_markers.csv": self._marker_rows
        }
        self._manifest["queue_drop_counts"] = {
            "imu_frame_queue_drops": tilt_sensor_calibration_queue_drop_count_get(),
            "turntable_feedback_queue_drops": turntable_feedback_queue_drop_count_get()
        }
        tmp_path = os.path.join(self.run_dir, "manifest.json.tmp")
        final_path = os.path.join(self.run_dir, "manifest.json")
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(self._manifest, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(tmp_path, final_path)

    def _record_poll_tick(self):
        if not self.recording:
            return
        try:
            # 如果记录开始时未连接转台，之后连接成功则开始记录反馈；断开时先停队列并排空缓存。
            turntable_connected = self._is_turntable_connected()
            if turntable_connected and not self._turntable_queue_active:
                self._turntable_update_count_last = int(turntableData.update_count)
                turntable_feedback_queue_set(True, clear=True)
                self._turntable_queue_active = True
                self._last_turntable_queue_drops = 0
                self._log_event("INFO", "TURNTABLE_FEEDBACK_CAPTURE_STARTED",
                                "检测到2TD600连接，开始记录转台反馈队列。", True)
            elif not turntable_connected and self._turntable_queue_active:
                turntable_feedback_queue_set(False, clear=False)
                self._drain_turntable_feedback_queue()
                self._turntable_queue_active = False
                self._log_event("WARN", "TURNTABLE_FEEDBACK_CAPTURE_STOPPED",
                                "检测到2TD600断开；后续IMU数据仍会记录，但转台反馈将缺失。", False)

            # IMU采集线程直接入队，GUI只负责排空队列；不会因GUI刷新慢而只拿到最新一帧。
            while True:
                try:
                    frame = tilt_sensor_calibration_frame_get_nowait()
                except queue.Empty:
                    break
                frame_count = int(frame["frame_update_count"])
                if self._imu_update_count_last is not None and frame_count - self._imu_update_count_last > 1:
                    self._log_event(
                        "WARN", "IMU_FRAME_GAP",
                        f"帧计数从 {self._imu_update_count_last} 跳到 {frame_count}；"
                        "请结合队列丢帧计数和通讯日志检查数据完整性。",
                        False
                    )
                self._write_imu_frame(frame)
                self._capture_auto_task_frame(frame)
                self._imu_update_count_last = frame_count

            self._drain_turntable_feedback_queue()

            imu_drops = tilt_sensor_calibration_queue_drop_count_get()
            if imu_drops > self._last_imu_queue_drops:
                self._log_event("ERROR", "IMU_QUEUE_OVERFLOW",
                                f"标定帧队列累计丢弃 {imu_drops} 帧。该次数据集需标记为不完整。", False)
                self._last_imu_queue_drops = imu_drops
            turntable_drops = turntable_feedback_queue_drop_count_get()
            if turntable_drops > self._last_turntable_queue_drops:
                self._log_event("ERROR", "TURNTABLE_QUEUE_OVERFLOW",
                                f"转台反馈队列累计丢弃 {turntable_drops} 条。该次数据集需标记为不完整。", False)
                self._last_turntable_queue_drops = turntable_drops

            imu_open_now = bool(tiltSensorComm.is_serial_opened)
            if imu_open_now != self._imu_serial_was_open:
                self._log_event("INFO" if imu_open_now else "WARN", "IMU_SERIAL_STATE_CHANGED",
                                "IMU串口已打开。" if imu_open_now else "IMU串口已关闭。",
                                imu_open_now)
                self._imu_serial_was_open = imu_open_now

            if time.monotonic() - self._last_flush_monotonic >= 1.0:
                self._flush_files()
                self._last_flush_monotonic = time.monotonic()
            self._update_live_status()
        except Exception as exc:
            text = repr(exc)
            if text != self._last_poll_error:
                self._last_poll_error = text
                self._log_event("ERROR", "RECORD_POLL_EXCEPTION", text, False)

    def _drain_turntable_feedback_queue(self):
        while True:
            try:
                item = turntable_feedback_get_nowait()
            except queue.Empty:
                break
            update_count = int(item["update_count"])
            if (self._turntable_update_count_last is not None and
                    update_count - self._turntable_update_count_last > 1):
                self._log_event(
                    "WARN", "TURNTABLE_FEEDBACK_GAP",
                    f"反馈计数从 {self._turntable_update_count_last} 跳到 {update_count}；"
                    "请检查转台轮询和反馈队列丢失计数。",
                    False
                )
            self._write_turntable_feedback(item)
            self._turntable_update_count_last = update_count

    def _write_imu_frame(self, frame):
        sample_num = min(
            INC_SAMPLE_NUM,
            len(frame["acc_x_raw_arr"]), len(frame["acc_y_raw_arr"]), len(frame["acc_z_raw_arr"]),
            len(frame["gyr_x_raw_arr"]), len(frame["gyr_y_raw_arr"]), len(frame["gyr_z_raw_arr"]),
            len(frame["acc_g_arr"]), len(frame["gyr_dps_arr"])
        )
        if sample_num <= 0:
            return
        frame_update_count = int(frame["frame_update_count"])
        frame_interval_ms = float(frame["frame_interval_ms"])
        wall_now_ns = int(frame["wall_time_ns"])
        mono_now_ns = int(frame["monotonic_time_ns"])
        dt_ms = min(max(frame_interval_ms, 0.0), 100.0)
        writer = self._writers["imu"]
        for i in range(sample_num):
            offset_ns = int(round((sample_num - 1 - i) * dt_ms / sample_num * 1_000_000.0))
            sample_wall_ns = wall_now_ns - offset_ns
            sample_mono_ns = mono_now_ns - offset_ns
            sample_iso = datetime.datetime.fromtimestamp(sample_wall_ns / 1e9).astimezone().isoformat(timespec="microseconds")
            mcu_sample_ms_est = int(frame["tick_ms"]) - (sample_num - 1 - i) * dt_ms / sample_num
            acc = frame["acc_g_arr"][i]
            gyr = frame["gyr_dps_arr"][i]
            writer.writerow([
                sample_iso, sample_wall_ns, sample_mono_ns, frame_update_count, i,
                frame["tick_ms"], f"{mcu_sample_ms_est:.6f}", f"{frame_interval_ms:.6f}",
                frame["data_unread"], frame["data_odr"], frame["fifo_state"],
                frame["acc_fs"], frame["gyro_fs"],
                frame["acc_x_raw_arr"][i], frame["acc_y_raw_arr"][i], frame["acc_z_raw_arr"][i],
                frame["gyr_x_raw_arr"][i], frame["gyr_y_raw_arr"][i], frame["gyr_z_raw_arr"][i],
                f"{acc[0]:.12g}", f"{acc[1]:.12g}", f"{acc[2]:.12g}",
                f"{gyr[0]:.12g}", f"{gyr[1]:.12g}", f"{gyr[2]:.12g}",
                frame["temp_raw"], f"{frame['temp_c']:.9g}"
            ])
            self._imu_rows += 1

    def _write_turntable_feedback(self, item):
        wall_sec = float(item["wall_time_sec"])
        age_ms = max(0.0, (time.time() - wall_sec) * 1000.0)
        writer = self._writers["turntable"]
        writer.writerow([
            datetime.datetime.fromtimestamp(wall_sec).astimezone().isoformat(timespec="microseconds"),
            item["wall_time_ns"], item["monotonic_time_ns"], item["update_count"], f"{age_ms:.3f}",
            f"{item['inner_position_deg']:.12g}", f"{item['inner_speed_dps']:.12g}",
            f"{item['outer_position_deg']:.12g}", f"{item['outer_speed_dps']:.12g}",
            item["inner_run_mode"], item["outer_run_mode"], item["inner_enable"], item["outer_enable"],
            item["inner_normal"], item["outer_normal"], item["inner_find_zero"], item["outer_find_zero"],
            item["inner_up_limit"], item["inner_down_limit"], item["outer_up_limit"], item["outer_down_limit"],
            item["inner_over_speed"], item["outer_over_speed"], item["inner_over_diff"], item["outer_over_diff"],
            item["inner_driver_fault"], item["outer_driver_fault"], item["inner_over_voltage"], item["outer_over_voltage"]
        ])
        self._turntable_rows += 1

    def _auto_mark_step(self, step):
        """自动任务实际采样起点写工况标记；拒绝手工输入覆盖自动工况编号。"""
        if not self.recording or 'markers' not in self._writers:
            self._request_auto_abort('自动记录器未就绪，无法保存工况采样标记')
            return False
        task=self._auto_task
        attempt=(int(task.get('rate_retry_count',0)) if step['mode']=='rate' else
                 int(task.get('static_retry_count',0))) + 1
        note=f"AUTO|{step['mode']}|{step.get('split','')}|attempt={attempt}"
        try:
            self._writers['markers'].writerow([
                _now_iso(),time.time_ns(),time.perf_counter_ns(),
                step['step_id'],self.combo_experiment_type.currentText(),note,
                f"{turntableData.inner_axis_position:.12g}",f"{turntableData.inner_axis_speed:.12g}",
                f"{turntableData.outer_axis_position:.12g}",f"{turntableData.outer_axis_speed:.12g}",
                int(tiltSensorRawData.data_update_count),int(tiltSensorRawData.tick_ms)
            ])
            self._marker_rows+=1
            self._files['markers'].flush()
            self._log_event('INFO','AUTO_SAMPLE_START_MARKER',
                            f"{step['step_id']} split={step.get('split')} attempt={attempt}",True)
            return True
        except Exception as exc:
            self._request_auto_abort(f"无法保存自动采样标记：{exc}")
            return False

    def _mark_step(self):
        if not self.recording:
            return
        step_id = self.line_step_id.text().strip()
        note = self.line_step_note.text().strip()
        if not step_id:
            QMessageBox.warning(self.page, "缺少工况编号", "请填写当前工况编号，例如 G_STATIC_01。")
            return
        stamp = _now_iso()
        try:
            self._writers["markers"].writerow([
                stamp, time.time_ns(), time.perf_counter_ns(),
                step_id, self.combo_experiment_type.currentText(), note,
                f"{turntableData.inner_axis_position:.12g}", f"{turntableData.inner_axis_speed:.12g}",
                f"{turntableData.outer_axis_position:.12g}", f"{turntableData.outer_axis_speed:.12g}",
                int(tiltSensorRawData.data_update_count), int(tiltSensorRawData.tick_ms)
            ])
            self._marker_rows += 1
            self._files["markers"].flush()
            self._log_event("INFO", "STEP_MARKER", f"step_id={step_id}; notes={note}", True)
            self.line_step_note.clear()
            self._write_manifest()
        except Exception as exc:
            self._log_event("ERROR", "STEP_MARKER_FAILED", repr(exc), False)
            QMessageBox.warning(self.page, "工况标记失败", str(exc))

    def _flush_files(self):
        for handle in self._files.values():
            try:
                handle.flush()
            except Exception:
                pass
        if self.run_dir:
            self._write_manifest()

    def _stop_recording(self):
        if not self.recording:
            return
        self.record_timer.stop()
        # 先停止生产者入队，再排空队列，避免关闭文件后仍有数据等待写入。
        tilt_sensor_calibration_queue_set(False, clear=False)
        turntable_feedback_queue_set(False, clear=False)
        self._drain_imu_queue_on_stop()
        self._drain_turntable_feedback_queue()
        self._log_event("INFO", "RECORD_STOP", "用户点击停止记录；队列已排空。此操作不会自动停止转台运动。", True)
        self.recording = False
        self._turntable_queue_active = False
        self._flush_files()
        for handle in self._files.values():
            try:
                handle.flush()
                handle.close()
            except Exception:
                pass
        self._files = {}
        self._writers = {}
        self._manifest["end_time_local"] = _now_iso()
        self._manifest["status"] = "stopped"
        self._manifest["row_counts"] = {
            "imu_raw.csv": self._imu_rows,
            "turntable_feedback.csv": self._turntable_rows,
            "events.csv": self._event_rows,
            "step_markers.csv": self._marker_rows
        }
        try:
            self._write_manifest()
        except Exception as exc:
            self._log_event("ERROR", "MANIFEST_FINALIZE_FAILED", repr(exc), False)
        self._sync_imu_record_button()
        self.button_mark_step.setEnabled(False)
        self.line_run_id.setReadOnly(False)
        self.line_device_sn.setReadOnly(False)
        self.line_output_root.setReadOnly(False)
        self.button_browse_output.setEnabled(True)
        self._log_event("INFO", "RECORD_CLOSED", f"数据目录={self.run_dir}; IMU样本行={self._imu_rows}; 转台反馈行={self._turntable_rows}", True)
        self._update_live_status()

    def _drain_imu_queue_on_stop(self):
        while True:
            try:
                frame = tilt_sensor_calibration_frame_get_nowait()
            except queue.Empty:
                break
            frame_count = int(frame["frame_update_count"])
            if self._imu_update_count_last is not None and frame_count - self._imu_update_count_last > 1:
                self._log_event("WARN", "IMU_FRAME_GAP_AT_STOP",
                                f"停止记录前帧计数从 {self._imu_update_count_last} 跳到 {frame_count}。", False)
            self._write_imu_frame(frame)
            self._imu_update_count_last = frame_count

    def shutdown(self):
        """应用退出时请求两轴停车并关闭记录；不代替硬件急停。"""
        try:
            if self._auto_task is not None:
                try:
                    self._send_stop_all()
                except Exception:
                    pass
                self._auto_task = None
                self.auto_timer.stop()
                self._set_turntable_manual_controls_locked(False)
            if self.recording:
                self._stop_recording()
        except Exception:
            pass

    def _update_live_status(self):
        self._update_connection_ui()
        if self.recording:
            self._sync_imu_record_button()
            self.button_mark_step.setEnabled(True)
        else:
            self._sync_imu_record_button()
            self.button_mark_step.setEnabled(False)
