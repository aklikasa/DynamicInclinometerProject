"""静态角度检测工作台：串口联调、双轴状态/使能与静态自动检测。"""
from __future__ import annotations
from datetime import datetime
import time
from pathlib import Path
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QFrame, QLabel, QPushButton, QHBoxLayout, QVBoxLayout,
    QGridLayout, QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit, QTextEdit,
    QScrollArea, QFileDialog, QMessageBox, QDialog, QDialogButtonBox, QFormLayout,
    QSizePolicy, QCheckBox, QProgressBar
)
from app.core.calibration import Calibration
from app.core.auto_scan import AutoScan
from app.core.report import export_report, save_checkpoint, checkpoint_path, export_from_checkpoint
from app.devices.imu_worker import IMUWorker
from app.devices.turntable_worker import TurntableWorker
from app.devices.turntable_driver import INNER, OUTER
from .theme import STYLESHEET, AuroraBackground, shadow

ROOT = Path(__file__).resolve().parents[2]


def label(text, kind='small', word_wrap=False):
    w = QLabel(text)
    w.setObjectName(kind)
    w.setWordWrap(word_wrap)
    return w


def button(text, variant='secondary', callback=None):
    w = QPushButton(text)
    w.setObjectName(variant)
    w.setCursor(Qt.PointingHandCursor)
    if callback: w.clicked.connect(callback)
    return w


def panel(style='glass'):
    f = QFrame()
    f.setObjectName(style)
    return f


def vbox(widget, margin=19, spacing=12):
    l = QVBoxLayout(widget)
    l.setContentsMargins(margin, margin, margin, margin)
    l.setSpacing(spacing)
    return l


def badge(text):
    return label(text, 'stat')


class SettingsDialog(QDialog):
    def __init__(self, still, sample, parent=None):
        super().__init__(parent)
        self.setWindowTitle('检测参数 · 预设')
        self.setMinimumWidth(365)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(25,25,25,20)
        layout.setSpacing(17)
        layout.addWidget(label('检测时序预设', 'sectionTitle'))
        layout.addWidget(label('参数用于自动静态扫描；先完成实机零位及符号验证。'))
        form = QFormLayout()
        self.still = QDoubleSpinBox(); self.still.setRange(0,600); self.still.setDecimals(1); self.still.setSuffix(' s'); self.still.setValue(still)
        self.sample = QDoubleSpinBox(); self.sample.setRange(.1,600); self.sample.setDecimals(1); self.sample.setSuffix(' s'); self.sample.setValue(sample)
        form.addRow('静止时间', self.still)
        form.addRow('采样时间', self.sample)
        layout.addLayout(form)
        actions = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        actions.accepted.connect(self.accept); actions.rejected.connect(self.reject)
        layout.addWidget(actions)


class Metric(QWidget):
    def __init__(self, tag, unit='g'):
        super().__init__()
        outer = vbox(self, 0, 4)
        outer.addWidget(label(tag, 'small'))
        line = QHBoxLayout(); line.setSpacing(6)
        self.number = label('—', 'number')
        self.number.setTextInteractionFlags(Qt.TextSelectableByMouse)
        line.addWidget(self.number)
        line.addWidget(label(unit, 'small'), alignment=Qt.AlignBottom)
        line.addStretch()
        outer.addLayout(line)

    def set(self, value, decimals=5):
        self.number.setText(f'{value:+.{decimals}f}')


class AxisBox(QFrame):
    def __init__(self, title, axis, parent):
        super().__init__()
        self.setObjectName('glassSoft')
        self.axis = axis
        lay = vbox(self, 13, 9)
        header = QHBoxLayout()
        header.addWidget(label(title, 'sectionTitle'))
        header.addStretch()
        self.status = badge('未连接')
        header.addWidget(self.status)
        lay.addLayout(header)
        stats = QHBoxLayout(); stats.setSpacing(8)
        self.position = Metric('当前位置', '°'); self.speed = Metric('反馈速度', '°/s')
        stats.addWidget(self.position); stats.addWidget(self.speed)
        lay.addLayout(stats)
        cmdline = QHBoxLayout(); cmdline.setSpacing(7)
        self.enable_btn = button('使能', 'secondary', lambda: parent.axis_enable(axis, True))
        self.disable_btn = button('解除', 'ghost', lambda: parent.axis_enable(axis, False))
        self.enable_btn.setEnabled(False); self.disable_btn.setEnabled(False)
        cmdline.addWidget(self.enable_btn); cmdline.addWidget(self.disable_btn)
        cmdline.addStretch()
        lay.addLayout(cmdline)

    def update_info(self, d, connected=True):
        if not connected or d is None:
            self.status.setText('未连接')
            self.position.number.setText('—'); self.speed.number.setText('—')
            self.enable_btn.setEnabled(False); self.disable_btn.setEnabled(False)
            return
        enabled = bool(d.get('enabled', False))
        alarm_flags = ('driver_fault', 'up_limit', 'down_limit', 'over_speed', 'over_diff')
        explicit_alarm = any(d.get(flag) for flag in alarm_flags)
        normal = bool(d.get('normal', False))
        if explicit_alarm:
            self.status.setText('故障/限位')
        elif enabled and not normal:
            self.status.setText('已使能/未就绪')
        elif enabled:
            self.status.setText('已使能')
        elif not normal:
            self.status.setText('待使能')
        else:
            self.status.setText('未使能')
        # 编码器角度可能报负值或超过一圈，界面按 0~360° 显示；原始反馈不改写。
        pos = float(d['position'])
        shown = pos % 360.0
        if 0.0 < pos <= 360.0 and abs(pos - 360.0) < 0.00005:
            shown = 360.0
        self.position.number.setText(f'{shown:.4f}')
        self.position.setToolTip(f'DLL原始读数：{pos:.6f}°；界面显示在0~360°，不修改反馈数据')
        self.speed.set(d['speed'], 4)
        self.enable_btn.setEnabled(not enabled and not explicit_alarm)
        self.disable_btn.setEnabled(enabled)
        summary = ', '.join(f'{k}={int(bool(d.get(k)))}' for k in ('enabled','normal',*alarm_flags))
        self.status.setToolTip(summary)
        self.enable_btn.setToolTip('发送厂商 SetAxisEnable 命令并等待0.5秒读取使能反馈；无运动动作。' + summary)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('静态角度检测工作台 V1.4 · Static Angle Lab')
        self.setMinimumSize(890, 600)
        self.resize(1060, 690)
        self.setStyleSheet(STYLESHEET)
        self.imu_worker: IMUWorker | None = None
        self.turn_worker: TurntableWorker | None = None
        self.imu_connected = False
        self.turn_connected = False
        self.latest_table = None
        self.calibration: Calibration | None = None
        self.still_seconds = 3.0
        self.sample_seconds = 5.0
        self.valid_frame_count = 0
        self.scan = AutoScan(self)
        self.scan.notice.connect(self.write_log)
        self.scan.progress.connect(self._scan_progress)
        self.scan.finished.connect(self._scan_finished)
        self.report_path = ''
        self.last_fb_monotonic = 0
        self._last_axis_states = None
        self._closed_by_user = False
        self._disconnect_after_abort = False
        self._turn_fault_latched = False
        self._feedback_alerted = False
        self._make_ui()
        self.refresh_ports()
        self.write_log('自动检测可用：需要双设备、校准文件、报告路径以及实机安全确认。')
        self.write_log('传感器：Modbus RTU 1000 / 104 寄存器；转台：2TD600.dll（内轴0、外轴2）。')
        self.cleanup_timer = QTimer(self)
        self.cleanup_timer.timeout.connect(self._cleanup_workers)
        self.cleanup_timer.start(400)

    def _make_ui(self):
        bg = AuroraBackground()
        self.setCentralWidget(bg)
        root = QHBoxLayout(bg)
        root.setContentsMargins(13, 12, 13, 12)
        root.setSpacing(9)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        root.addWidget(scroll, 1)
        main = QWidget(); main.setObjectName('appRoot'); scroll.setWidget(main)
        layout = QVBoxLayout(main); layout.setContentsMargins(3, 2, 3, 4); layout.setSpacing(9)

        head = QHBoxLayout(); head.setSpacing(7)
        brand = QVBoxLayout(); brand.setSpacing(1)
        brand.addWidget(label('STATIC ANGLE  /  LAB', 'small'))
        brand.addWidget(label('静态角度检测', 'hero'))
        head.addLayout(brand, 1)
        self.overview = badge('设备待连接'); head.addWidget(self.overview)
        head.addWidget(button('设置', 'ghost', self.open_settings))
        self.log_btn = button('日志 ›', 'secondary', self.toggle_log); head.addWidget(self.log_btn)
        layout.addLayout(head)
        self.safety_banner = label('!', 'small', True)
        self.safety_banner.setStyleSheet('background:#632333; color:#fff; padding:10px; border:1px solid #ff6f80; border-radius:9px; font-weight:600;')
        self.safety_banner.hide()
        layout.addWidget(self.safety_banner)

        cal = panel(); c = QHBoxLayout(cal); c.setContentsMargins(12,9,12,9); c.setSpacing(8)
        c.addWidget(label('校准', 'sectionTitle'))
        self.file_path = QLineEdit(); self.file_path.setReadOnly(True)
        self.file_path.setPlaceholderText('选择 accel_calibration.json')
        c.addWidget(self.file_path, 1)
        c.addWidget(button('导入 JSON', 'primary', self.open_calibration))
        self.cal_status = badge('未加载'); c.addWidget(self.cal_status)
        layout.addWidget(cal)
        self.cal_details = label('原始 IMU 数据可独立验证；未导入校准文件时不计算校正量。')
        layout.addWidget(self.cal_details)

        connections = QHBoxLayout(); connections.setSpacing(9)
        imu = panel(); il = vbox(imu, 12, 7)
        ih = QHBoxLayout(); ih.addWidget(label('IMU  /  数据串口', 'sectionTitle')); ih.addStretch()
        self.imu_status = badge('未连接'); ih.addWidget(self.imu_status); il.addLayout(ih)
        ic = QHBoxLayout(); ic.setSpacing(6)
        self.imu_port = QComboBox(); self.imu_port.setEditable(False)
        self.imu_baud = QComboBox(); self.imu_baud.setEditable(True)
        self.imu_baud.addItems(['1500000','921600','460800','115200'])
        self.imu_addr = QSpinBox(); self.imu_addr.setRange(1,247); self.imu_addr.setValue(1)
        ic.addWidget(self.imu_port, 2); ic.addWidget(self.imu_baud, 2); ic.addWidget(self.imu_addr, 1)
        il.addLayout(ic)
        self.imu_connect_btn = button('连接传感器', 'primary', self.toggle_imu)
        il.addWidget(self.imu_connect_btn)
        mr = QHBoxLayout(); mr.setSpacing(9)
        self.ax = Metric('ACC X'); self.ay = Metric('ACC Y'); self.az = Metric('ACC Z')
        for m in (self.ax,self.ay,self.az): mr.addWidget(m,1)
        il.addLayout(mr)
        self.raw_label = label('原始值：—'); self.corr_label = label('校正值：—')
        self.gyro_label = label('陀螺仪：— °/s')
        self.meta_label = label('温度 —   |   ACC FS —   |   GYRO FS —')
        self.tick_label = label('有效帧 0   |   MCU tick —   |   ODR —')
        for w in (self.raw_label,self.corr_label,self.gyro_label,self.meta_label,self.tick_label): il.addWidget(w)
        il.addStretch(1); connections.addWidget(imu, 1)

        turn = panel(); tl = vbox(turn, 12, 7)
        th = QHBoxLayout(); th.addWidget(label('2TD600  /  转台串口', 'sectionTitle')); th.addStretch()
        self.turn_status = badge('未连接'); th.addWidget(self.turn_status); tl.addLayout(th)
        tp = QHBoxLayout(); tp.setSpacing(6)
        self.turn_port = QComboBox(); self.turn_port.setEditable(False)
        tp.addWidget(self.turn_port,1)
        self.turn_connect_btn = button('连接转台', 'primary', self.toggle_turn); tp.addWidget(self.turn_connect_btn)
        tl.addLayout(tp)
        self.both_enable_btn = button('使能双轴', 'secondary', self.enable_both)
        self.both_enable_btn.setEnabled(False)
        self.outer_enable_btn = button('使能外轴 2', 'secondary', lambda: self.axis_enable(OUTER, True))
        self.outer_enable_btn.setEnabled(False)
        self.diagnose_btn = button('诊断状态', 'ghost', self.diagnose_table)
        self.diagnose_btn.setEnabled(False)
        shortcuts = QHBoxLayout(); shortcuts.setSpacing(6)
        for b in (self.both_enable_btn, self.outer_enable_btn, self.diagnose_btn):
            shortcuts.addWidget(b,1)
        tl.addLayout(shortcuts)
        self.table_hint = label('使能检查：内轴 0 与外轴 2 必须分别反馈 enabled=1；normal=1 不等于使能。', 'small', True)
        tl.addWidget(self.table_hint)
        self.inner_axis = AxisBox('内轴  ·  0', INNER, self)
        self.outer_axis = AxisBox('外轴  ·  2', OUTER, self)
        tl.addWidget(self.inner_axis); tl.addWidget(self.outer_axis)
        mv = QHBoxLayout(); mv.setSpacing(6)
        self.move_axis = QComboBox(); self.move_axis.addItems(['内轴','外轴'])
        self.move_deg = QDoubleSpinBox(); self.move_deg.setRange(0,360); self.move_deg.setDecimals(2); self.move_deg.setSuffix(' °')
        self.move_speed = QDoubleSpinBox(); self.move_speed.setRange(.1,5); self.move_speed.setDecimals(1); self.move_speed.setValue(1); self.move_speed.setSuffix(' °/s')
        mv.addWidget(self.move_axis,2); mv.addWidget(self.move_deg,2); mv.addWidget(self.move_speed,2)
        tl.addLayout(mv)
        ctr = QHBoxLayout(); ctr.setSpacing(6)
        self.move_btn = button('手动定位', 'secondary', self.position_test); self.move_btn.setEnabled(False)
        self.stop_btn = button('双轴停止', 'danger', self.stop_all); self.stop_btn.setEnabled(False)
        ctr.addWidget(self.move_btn,1); ctr.addWidget(self.stop_btn,1); tl.addLayout(ctr)
        connections.addWidget(turn,1); layout.addLayout(connections)

        test = panel(); ts = vbox(test, 11, 7)
        row = QHBoxLayout(); row.addWidget(label('静态绝对倾角  /  自动扫描', 'sectionTitle')); row.addStretch()
        self.scan_status=badge('待开始'); row.addWidget(self.scan_status); ts.addLayout(row)
        ts.addWidget(label('Y：内轴0° → 外轴−180°~+180°；X：内轴90° → 同范围。每10°一点；帧内/窗口两级MAD异常值处理。', 'small', True))
        pathrow=QHBoxLayout(); pathrow.addWidget(label('报告保存到'))
        self.report_edit=QLineEdit(); self.report_edit.setReadOnly(True); self.report_edit.setPlaceholderText('开始前选择 Excel 报告路径')
        pathrow.addWidget(self.report_edit,1)
        pathrow.addWidget(button('选择路径', 'secondary', self.choose_report))
        pathrow.addWidget(button('恢复备份', 'ghost', self.recover_backup))
        ts.addLayout(pathrow)
        opts=QHBoxLayout(); opts.addWidget(label('步进10°  /  74点'))
        opts.addWidget(label('定位速度'))
        self.scan_speed=QDoubleSpinBox(); self.scan_speed.setRange(.1,5); self.scan_speed.setSingleStep(.5); self.scan_speed.setValue(2); self.scan_speed.setSuffix(' °/s')
        opts.addWidget(self.scan_speed); opts.addStretch()
        ts.addLayout(opts)
        self.safety_check=QCheckBox('已实机确认编码器零位、轴方向、限位、线缆空间和跨0°/360°运动路径；两轴已确认使能')
        ts.addWidget(self.safety_check)
        self.progress=QProgressBar(); self.progress.setRange(0,74); self.progress.setValue(0); ts.addWidget(self.progress)
        act=QHBoxLayout(); act.setSpacing(7)
        self.detect_btn=button('开始自动检测', 'primary', self.start_scan)
        self.abort_btn=button('终止检测 / 停车', 'danger', self.abort_scan); self.abort_btn.setEnabled(False)
        act.addWidget(self.detect_btn); act.addWidget(self.abort_btn)
        ts.addLayout(act); layout.addWidget(test)
        foot = QHBoxLayout(); foot.addWidget(label('V1.3  /  0~360°  /  Excel直接导出 + 逐点备份'))
        foot.addStretch(); foot.addWidget(button('刷新串口', 'ghost', self.refresh_ports))
        layout.addLayout(foot)

        self.log_panel = panel(); self.log_panel.setFixedWidth(280)
        ll = vbox(self.log_panel, 12, 8)
        lh = QHBoxLayout(); lh.addWidget(label('操作日志','sectionTitle')); lh.addStretch()
        lh.addWidget(button('×', 'ghost', self.toggle_log)); ll.addLayout(lh)
        self.log_text = QTextEdit(); self.log_text.setReadOnly(True); ll.addWidget(self.log_text,1)
        lr = QHBoxLayout(); lr.addWidget(button('清空','ghost',self.log_text.clear))
        lr.addWidget(button('保存','secondary',self.save_log)); ll.addLayout(lr)
        root.addWidget(self.log_panel, 0); self.log_panel.hide()

    def choose_report(self):
        suggested=str(ROOT / 'reports' / ('静态角度精度检测_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'.xlsx'))
        path,_=QFileDialog.getSaveFileName(self,'选择检测报告保存位置',suggested,'Excel 工作簿 (*.xlsx)')
        if path:
            if not path.lower().endswith('.xlsx'): path+='.xlsx'
            self.report_path=path
            self.report_edit.setText(path)

    def recover_backup(self):
        """设备不连接时也能将上次的逐点备份重新导出为 Excel。"""
        folder = str(Path(self.report_path).parent) if self.report_path else str(ROOT / 'reports')
        source, _ = QFileDialog.getOpenFileName(self, '选择逐点备份文件', folder,
                                                '检测备份 (*.checkpoint.json);;JSON 文件 (*.json)')
        if not source:
            return
        proposed = str(Path(source).with_name(Path(source).name.replace('.checkpoint.json', '_恢复.xlsx')))
        if not proposed.lower().endswith('.xlsx'):
            proposed = str(Path(source).with_suffix('.xlsx'))
        path, _ = QFileDialog.getSaveFileName(self, '将备份恢复到 Excel', proposed, 'Excel 文件 (*.xlsx)')
        if not path:
            return
        if not path.lower().endswith('.xlsx'):
            path += '.xlsx'
        try:
            dest = export_from_checkpoint(source, path)
            self.write_log(f'成功：备份已恢复成 Excel：{dest}')
            QMessageBox.information(self, 'Excel 恢复成功', f'报告已生成：\n{dest}')
        except Exception as exc:
            self.show_error('备份恢复失败', exc)

    def _save_point_checkpoint(self, status='采集中', reason=''):
        if not self.report_path or not self.calibration:
            return None
        return save_checkpoint(self.report_path, self.scan.rows,
                               self.calibration, self._report_settings(), status, reason)

    def start_scan(self):
        if self.scan.active: return
        if self._turn_fault_latched:
            self.show_error('转台安全状态不明', '发生过停车/连接异常，须确认现场安全，重新建立并验证转台反馈后才能检测。'); return
        if not self.imu_connected or not self.turn_connected or not self.turn_worker:
            self.show_error('启动条件不足','必须先连接 IMU 和双轴转台。'); return
        if not self.calibration:
            self.show_error('启动条件不足','先导入有效的加速度校准 JSON。'); return
        if not self.report_path:
            self.show_error('启动条件不足','请在检测开始前选择 Excel 报告路径。'); return
        if not self.safety_check.isChecked():
            self.show_error('安全确认','须先实机确认零位、轴符号、限位和运动路径，勾选安全确认。'); return
        if not self.latest_table or time.monotonic() - self.last_fb_monotonic > 2.0:
            if self.turn_worker: self.turn_worker.submit('diagnose')
            self.show_error('转台反馈超时', '转台双轴状态超过 2 秒没有更新，已请求重新诊断。\n'
                            '为安全起见暂不启动自动运动，请检查 COM 口和实时状态。')
            return
        not_ready = []
        for key, title in (('inner', '内轴 0'), ('outer', '外轴 2')):
            axis = self.latest_table[key]
            if not axis['enabled']:
                not_ready.append(f'{title}：未使能（enabled=0，normal={int(axis["normal"])}）')
            elif not axis['normal']:
                not_ready.append(f'{title}：使能后未就绪（normal=0）')
            alarms = [k for k in ('driver_fault', 'up_limit', 'down_limit', 'over_speed', 'over_diff') if axis.get(k)]
            if alarms: not_ready.append(f'{title}：存在告警 {", ".join(alarms)}')
        if not_ready:
            reason = '\n'.join(not_ready)
            self.write_log('自动检测被阻止：' + '；'.join(not_ready))
            self.show_error('双轴使能/状态检查未通过', reason + '\n\n'
                            '可点击转台区域的「使能外轴 2」或「使能双轴」，确认现场安全后尝试使能。\n'
                            '使能操作本身不会运动；只有回读 enabled=1 且 normal=1 时才能继续。')
            return
        if not self.valid_frame_count:
            self.show_error('没有有效数据','IMU 尚未收到有效新帧。'); return
        if not self.calibration.approved:
            result=QMessageBox.question(self,'校准文件未正式放行',
                '当前校准文件标注为试运行，不可用于正式出厂判定。\n是否仅以工程试验身份继续？',
                QMessageBox.Yes|QMessageBox.No,QMessageBox.No)
            if result != QMessageBox.Yes:return
        decision=QMessageBox.question(self,'确认开始真实自动运动',
            '将执行双轴真实机械动作，共74个采样姿态。\n'
            '所谓“回零”仅为编码器绝对位置0°定位，不是硬件机械寻零。\n'
            '已知0°/360°路径、绝对角度符号及线缆绕转安全？\n'
            '现场必须有人看守，并能操作硬件急停。\n\n确认开始？',
            QMessageBox.Yes|QMessageBox.No,QMessageBox.No)
        if decision!=QMessageBox.Yes:return
        existing = checkpoint_path(self.report_path)
        if existing.exists():
            overwrite = QMessageBox.question(
                self, '报告路径存在检测备份',
                f'发现同名检测备份：\n{existing}\n\n'
                '继续将覆盖这份备份。建议先选择新的报告文件名。确定覆盖吗？',
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if overwrite != QMessageBox.Yes:
                return
        try:
            # 在电机开始运动之前验证：所选目录可写、备份文件可生成。
            save_checkpoint(self.report_path, [], self.calibration,
                            self._report_settings(), '准备检测')
        except Exception as exc:
            self.show_error('无法创建结果备份', f'报告目录不可写，未启动转台：{exc}')
            return
        self.write_log(f'逐点备份已建立：{checkpoint_path(self.report_path)}')
        self.progress.setValue(0); self.scan_status.setText('检测中')
        self.detect_btn.setEnabled(False); self.abort_btn.setEnabled(True)
        self.safety_check.setEnabled(False)
        try:self.scan.start(self.turn_worker,self.calibration,self.still_seconds,self.sample_seconds,self.scan_speed.value())
        except Exception as exc:self._scan_finished('失败',str(exc))

    def _scan_progress(self,done,total,desc):
        self.progress.setRange(0,total); self.progress.setValue(done)
        self.scan_status.setText(f'{done}/{total} · {desc}')
        self.write_log(f'采点 {done}/{total}：{desc}')
        try:
            self._save_point_checkpoint()
        except Exception as exc:
            self.write_log(f'严重：逐点备份写入失败：{exc}')
            if self.scan.active:
                self.scan.abort('采点备份写入失败，为避免数据丢失已停车')

    def abort_scan(self):
        if self.scan.active: self.scan.abort('操作员手动终止')

    def _report_settings(self):
        return dict(静止时间秒=self.still_seconds,采样时间秒=self.sample_seconds,
                    步进角度='10°',定位速度=self.scan_speed.value(),
                    IMU串口=self.imu_port.currentData() or '',转台串口=self.turn_port.currentData() or '',
                    备注='零位及旋转符号需要使用已知角实机确认；未确认不得作为出厂判定')

    def _save_excel(self,status,reason=''):
        if not self.report_path or not self.calibration: return
        try:
            path=export_report(self.report_path,self.scan.rows,self.calibration,self._report_settings(),status,reason)
            self.write_log(f'Excel 报告已写入：{path}（{len(self.scan.rows)}点）')
        except Exception as exc:
            self.show_error('Excel 报告保存失败',
                            f'{exc}\n\n检测备份仍保存在：\n{checkpoint_path(self.report_path)}\n'
                            '可关闭占用该 Excel 的程序后，点击「恢复备份」重新导出。')

    def _scan_finished(self,status,reason=''):
        self.detect_btn.setEnabled(True); self.abort_btn.setEnabled(False)
        self.safety_check.setEnabled(True)
        self.scan_status.setText(status + (' · '+reason[:35] if reason else ''))
        self.write_log(f'自动检测结束：{status} {reason}')
        if status.startswith('危险'):
            self._on_safety_alarm('自动检测未能确认停车：' + reason + '。请现场核实转台状态，必要时使用实体急停。')
        try:
            dest = self._save_point_checkpoint(status, reason)
            if dest:
                self.write_log(f'最终检测备份已保存：{dest}')
        except Exception as exc:
            self.write_log(f'错误：最终备份保存失败：{exc}；先前逐点备份通常仍可恢复。')
        self._save_excel(status,reason)
        if self._disconnect_after_abort:
            self._disconnect_after_abort = False
            if status.startswith('危险'):
                self.write_log('安全断开未继续：停车确认失败。保持转台连接并要求现场检查。')
                self.turn_connect_btn.setEnabled(True)
            elif self.turn_worker and self.turn_connected:
                self.write_log('自动检测中止并确认停车后，继续受控解除使能与断开')
                self.turn_worker.submit('disconnect')

    def export_scan_plan(self):
        from app.core.scan_plan import make_scan_plan, save_scan_plan
        path, _ = QFileDialog.getSaveFileName(self, '导出静态扫描方案', str(ROOT / 'static_scan_plan.csv'), 'CSV 文件 (*.csv)')
        if not path: return
        try:
            save_scan_plan(make_scan_plan(sample_seconds=self.sample_seconds, settle_seconds=self.still_seconds), path)
            self.write_log('已导出 74 点静态扫描方案（方案文件不会使转台运动）：' + path)
            QMessageBox.information(self, '扫描方案已导出', '已生成 74 个采点位置和时序。\n自动运行仍需要实机确认机械零位、转向和跨0°/360°路径。')
        except Exception as exc:
            self.show_error('导出失败', exc)

    def write_log(self, msg):
        stamp = datetime.now().strftime('%H:%M:%S')
        self.log_text.append(f'[{stamp}] {msg}')

    def show_error(self, title, details):
        self.write_log(f'错误：{details}')
        QMessageBox.warning(self, title, str(details))

    def refresh_ports(self):
        """只列出系统真实识别的COM端口；显示USB设备描述并保存真实端口名。"""
        import re
        try:
            from serial.tools import list_ports
            ports = sorted((p for p in list_ports.comports()
                            if re.fullmatch(r'COM[0-9]+', p.device.upper())),
                           key=lambda p: int(p.device[3:]))
        except Exception as exc:
            ports = []
            self.write_log(f'串口扫描不可用：{exc}')
        names = [p.device.upper() for p in ports]
        for combo, hint, busy in ((self.imu_port, '请选择 IMU 串口', self.imu_connected),
                                  (self.turn_port, '请选择转台串口', self.turn_connected)):
            if busy or not combo.isEnabled():
                continue  # 不改变已连接/正在连接的设备对应选择
            selected = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(hint, None)
            for p in ports:
                port = p.device.upper()
                desc = (p.description or '').strip()
                shown = f'{port}  ·  {desc}' if desc and desc != 'n/a' else port
                combo.addItem(shown, port)
                combo.setItemData(combo.count()-1, f'{port}\n{desc}\n{p.hwid}', Qt.ToolTipRole)
            chosen = combo.findData(selected) if selected else -1
            combo.setCurrentIndex(chosen if chosen >= 0 else 0)
            combo.blockSignals(False)
            combo.setToolTip('请展开列表选择实际连接的COM端口；本列表不包含虚构的默认端口。')
        self.write_log(f'系统发现 {len(ports)} 个串口：{", ".join(names) if names else "无（请检查USB连接、设备管理器与驱动）"}')

    def ports_distinct(self):
        a = self.imu_port.currentData()
        b = self.turn_port.currentData()
        if a and b and a.upper() == b.upper():
            self.show_error('串口冲突', 'IMU 和2TD600不能使用同一个COM口，请从下拉框重新选择。')
            return False
        return True

    def open_calibration(self):
        path, _ = QFileDialog.getOpenFileName(self, '加载加速度计校准结果', str(ROOT / 'examples'), 'JSON 文件 (*.json)')
        if not path: return
        try:
            cal = Calibration.load(path)
        except Exception as exc:
            self.show_error('校准文件无效', exc)
            return
        self.calibration = cal
        self.file_path.setText(str(cal.path))
        self.file_path.setToolTip(str(cal.path))
        self.cal_status.setText('✓ 已读取')
        self.cal_details.setText(f'设备 SN：{cal.device_serial}    ·    批次：{cal.run_id}    ·    {cal.verdict}    ·    3维零偏 + 3×3校正矩阵')
        self.write_log(f'校准文件已载入：{cal.path.name}；质量标记：{cal.verdict}')
        if not cal.approved:
            self.write_log('提醒：该校准报告未批准正式出厂，仅用于当前联调展示。')

    def open_settings(self):
        dlg = SettingsDialog(self.still_seconds,self.sample_seconds,self)
        if dlg.exec() == QDialog.Accepted:
            self.still_seconds = dlg.still.value()
            self.sample_seconds = dlg.sample.value()
            self.write_log(f'保存时序：静止 {self.still_seconds:.1f}s / 采样 {self.sample_seconds:.1f}s')

    def toggle_log(self):
        show = not self.log_panel.isVisible()
        self.log_panel.setVisible(show)
        self.log_btn.setText('收起日志  ‹' if show else '日志  ›')

    def toggle_imu(self):
        if self.scan.active:
            self.show_error('检测运行中','请先终止检测，才能断开传感器'); return
        if self.imu_worker and self.imu_worker.isRunning():
            self.imu_worker.stop()
            self.imu_connect_btn.setEnabled(False)
            self.write_log('请求停止 IMU 读取线程')
            return
        if not self.ports_distinct(): return
        port = self.imu_port.currentData()
        try:
            baud = int(self.imu_baud.currentText())
            if not (baud > 0 and port): raise ValueError
        except ValueError:
            self.show_error('连接参数错误', '请先在 IMU 下拉框选择真实COM端口并设置正确波特率。')
            return
        worker = IMUWorker(port,baud,self.imu_addr.value(),self)
        self.imu_worker = worker
        worker.state.connect(self._imu_state)
        worker.notice.connect(self.write_log)
        worker.sample.connect(self._imu_sample)
        self.imu_connect_btn.setEnabled(False)
        self.imu_status.setText('◌ 正在连接')
        self.imu_port.setEnabled(False); self.imu_baud.setEnabled(False); self.imu_addr.setEnabled(False)
        worker.start()

    def _imu_state(self, ok, msg):
        self.imu_connected = ok
        self.write_log(msg)
        self.imu_status.setText('● 正在采集' if ok else '○ 未连接')
        self.imu_connect_btn.setText('断开传感器' if ok else '连接传感器')
        if ok:
            self.imu_connect_btn.setEnabled(True)
        self._update_overview()

    def _imu_sample(self, frame):
        self.scan.feed(frame)
        if not frame.valid:
            self.imu_status.setText('◌ 已连接 / 等待新帧')
            return
        self.valid_frame_count += 1
        self.imu_status.setText('● 正在采集')
        for widget, val in zip((self.ax,self.ay,self.az),frame.accel_g): widget.set(val)
        self.raw_label.setText('原始均值  ' + '   /   '.join(f'{x:+.6f}' for x in frame.accel_g) + ' g')
        if self.calibration:
            corrected = self.calibration.correct(frame.accel_g)
            self.corr_label.setText('校正均值  ' + '   /   '.join(f'{x:+.6f}' for x in corrected) + ' g')
        self.gyro_label.setText('角速度均值  ' + '   /   '.join(f'{x:+.3f}' for x in frame.gyro_dps) + ' °/s')
        acc_hint = '' if frame.acc_fs_reported else '（回退，未上报）'
        gyro_hint = '' if frame.gyro_fs_reported else '（回退，未上报）'
        self.meta_label.setText(f'温度 {frame.temp_c:.2f} °C  |  ACC ±{frame.acc_fs}g{acc_hint}  |  GYRO ±{frame.gyro_fs}°/s{gyro_hint}')
        self.tick_label.setText(f'有效帧 {self.valid_frame_count}    |    MCU tick {frame.tick_ms} ms    |    ODR {frame.odr} Hz')

    def toggle_turn(self):
        if self.scan.active:
            self._disconnect_after_abort = True
            self.turn_connect_btn.setEnabled(False)
            self.write_log('操作员要求安全断开：正在终止扫描，并优先确认停车')
            self.scan.abort('操作员点击安全断开')
            return
        if self.turn_worker and self.turn_worker.isRunning():
            if self.turn_connected:
                self.turn_connect_btn.setEnabled(False)
                self.write_log('请求安全断开：丢弃待执行运动→停车核实→解除使能核实→关闭端口')
                if not self.turn_worker.submit('disconnect'):
                    self.turn_connect_btn.setEnabled(True)
                    self.write_log('断开指令未进入控制线程，请立即检查通讯')
            return
        if not self.ports_distinct(): return
        port = self.turn_port.currentData()
        if not port:
            self.show_error('端口错误', '请先在转台下拉框选择系统识别到的COM端口。'); return
        self.turn_worker = TurntableWorker(port, self)
        w = self.turn_worker
        w.state.connect(self._turn_state)
        w.feedback.connect(self._turn_feedback)
        w.result.connect(self._turn_result)
        w.notice.connect(self.write_log)
        w.safety_alarm.connect(self._on_safety_alarm)
        self.turn_connect_btn.setEnabled(False)
        self.turn_status.setText('◌ 正在连接')
        self.turn_port.setEnabled(False)
        w.start()

    def _turn_state(self, ok, msg):
        self.turn_connected = ok
        self.turn_status.setText('● 端口已打开' if ok else '○ 未连接')
        self.turn_connect_btn.setText('安全断开' if ok else '连接转台')
        if ok:
            self.turn_connect_btn.setEnabled(True)
            self.stop_btn.setEnabled(True)
            self._feedback_alerted = False
            # 一次全新重连不自动消除危险提示；需要看到稳定的有效反馈。
        else:
            self.inner_axis.update_info(None,False)
            self.outer_axis.update_info(None,False)
            self._last_axis_states = None
            self.last_fb_monotonic = 0
            self.outer_enable_btn.setEnabled(False)
            self.move_btn.setEnabled(False)
            self.stop_btn.setEnabled(False)
            self.latest_table = None
        self.both_enable_btn.setEnabled(ok)
        self.outer_enable_btn.setEnabled(False)  # 等待外轴实际状态反馈后才允许使能
        self.diagnose_btn.setEnabled(ok)
        self._update_overview()
        self.write_log(msg)

    def _turn_feedback(self, data):
        self.scan.feedback(data)
        self.latest_table = data
        self.last_fb_monotonic = time.monotonic()
        self._feedback_alerted = False
        states = tuple((key, int(bool(data[key]['enabled'])), int(bool(data[key]['normal'])))
                       for key in ('inner', 'outer'))
        if self._last_axis_states is not None and states != self._last_axis_states:
            self.write_log('双轴状态变化：' + ' / '.join(f'{key} enabled={enabled} normal={normal}'
                                                        for key, enabled, normal in states))
        self._last_axis_states = states
        self.inner_axis.update_info(data['inner'])
        self.outer_axis.update_info(data['outer'])
        selected = data['inner' if self.move_axis.currentIndex() == 0 else 'outer']
        self.move_btn.setEnabled(self.turn_connected and not self._turn_fault_latched and selected['enabled'] and selected['normal']
                                and not any(selected.get(k) for k in ('driver_fault','up_limit','down_limit','over_speed','over_diff')))
        alarms = ('driver_fault', 'up_limit', 'down_limit', 'over_speed', 'over_diff')
        fault = any(any(v.get(k) for k in alarms) for v in data.values())
        if fault:
            self.turn_status.setText('! 有故障/限位')
        elif any(v['enabled'] and not v['normal'] for v in data.values()):
            self.turn_status.setText('! 使能后状态未就绪')
        elif not data['outer']['enabled']:
            self.turn_status.setText('! 外轴 2 未使能')
        elif not data['inner']['enabled']:
            self.turn_status.setText('! 内轴 0 未使能')
        else:
            self.turn_status.setText('● 双轴已使能')
        self.table_hint.setText('内轴 使能={} 正常={}   |   外轴 使能={} 正常={}'.format(
            int(bool(data['inner']['enabled'])),int(bool(data['inner']['normal'])),
            int(bool(data['outer']['enabled'])),int(bool(data['outer']['normal']))))
        self.both_enable_btn.setEnabled(self.turn_connected and not self._turn_fault_latched and
                not all(v['enabled'] and v['normal'] for v in data.values()) and not fault)
        self.outer_enable_btn.setEnabled(self.turn_connected and not self._turn_fault_latched and not data['outer']['enabled'] and not fault)
        if self._turn_fault_latched:
            self.inner_axis.enable_btn.setEnabled(False)
            self.outer_axis.enable_btn.setEnabled(False)

    def _on_safety_alarm(self, message):
        self._turn_fault_latched = True
        self.safety_banner.setText('⚠ 安全状态未确认：' + str(message))
        self.safety_banner.show()
        self.write_log('严重安全告警：' + str(message))
        self.detect_btn.setEnabled(False)

    def _turn_result(self, name, ok, message):
        self.scan.command_result(name,ok,message)
        self.write_log(('成功：' if ok else '失败：') + message)
        if name in ('enable', 'enable_both') and not ok:
            self.write_log('使能故障排查：先看驱动供电、现场急停/外部互锁、轴号与设备状态；'
                           'normal=1 并不意味着 enabled=1。请对比原上位机外轴2使能结果。')
        if name == 'disconnect' and not ok:
            self.turn_connect_btn.setEnabled(True)
        if not ok:
            if name not in ('disconnect', 'stop_all'):
                self.show_error('转台命令失败：' + name, message)
            else:
                self.write_log('危险：' + name + '失败，保持连接；详细原因：' + message)
        if name == 'disconnect' and ok:
            self.write_log('断开完成：停车和解除使能均已经读取反馈确认。')
        if ok and name in ('enable','enable_both','disable','move') and self.turn_worker:
            self.turn_worker.submit('refresh')

    def diagnose_table(self):
        if self.turn_connected and self.turn_worker:
            if self._turn_fault_latched and self.latest_table and time.monotonic() - self.last_fb_monotonic < 2.0:
                # 清除告警不意味着机械已停稳，只允许对比反馈；人工确认后方可恢复测试。
                decision=QMessageBox.question(self, '清除软件联锁前确认',
                    '曾发生停车/通信安全异常。请确认现场已安全、实体急停可用，且两轴已核实状态。\n'
                    '只解除软件测试锁定，不会自动使能或运动。确认？',
                    QMessageBox.Yes|QMessageBox.No, QMessageBox.No)
                if decision == QMessageBox.Yes:
                    self._turn_fault_latched = False
                    self.safety_banner.hide()
                    self.detect_btn.setEnabled(True)
                    self.write_log('操作员现场确认后解除了软件联锁；不代表硬件安全认证')
            self.turn_worker.submit('diagnose')
            self.write_log('请求双轴详细诊断：enabled/normal/驱动故障/限位/超速/超差')
            if not self.log_panel.isVisible(): self.toggle_log()

    def enable_both(self):
        if self._turn_fault_latched: return
        if self.scan.active or not self.turn_connected or not self.turn_worker: return
        if not self.latest_table: return
        if all(self.latest_table[k]['enabled'] and self.latest_table[k]['normal'] for k in ('inner','outer')):
            self.write_log('两轴已经使能且状态正常，不重复使能。'); return
        decision=QMessageBox.question(self,'确认使能双轴',
            '将依次向内轴0、外轴2发送驱动器使能指令，并等待状态反馈；不会执行机械运动。\n'
            '若有故障、限位或急停状态，请先排查。确认现场安全后执行？',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if decision == QMessageBox.Yes:
            self.turn_worker.submit('enable_both')
            self.write_log('操作员确认：依次执行内轴0、外轴2使能及反馈核验')

    def axis_enable(self, axis, enable):
        if self._turn_fault_latched and enable: return
        if self.scan.active: return
        if not self.turn_connected or not self.turn_worker: return
        name = '内轴' if axis == INNER else '外轴'
        if enable:
            ret = QMessageBox.question(self, '确认电机上电', f'确认{name}使能？\n请确保转台附近无人且设备准备就绪。',
                                       QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if ret != QMessageBox.Yes: return
        else:
            ret = QMessageBox.question(self,'解除使能',f'确认解除{name}使能？\n确保运动已停止，注意机械保持方式。',
                                       QMessageBox.Yes | QMessageBox.No,QMessageBox.No)
            if ret != QMessageBox.Yes: return
        self.turn_worker.submit('enable' if enable else 'disable',axis)

    def position_test(self):
        if self._turn_fault_latched: return
        if self.scan.active: return
        if not self.turn_connected or not self.turn_worker: return
        axis = INNER if self.move_axis.currentIndex()==0 else OUTER
        key = 'inner' if axis==INNER else 'outer'
        d = (self.latest_table or {}).get(key, {})
        if not d.get('enabled') or not d.get('normal') or any(d.get(k) for k in ('driver_fault','up_limit','down_limit','over_speed','over_diff')):
            self.show_error('无法定位','所选轴未使能或反馈状态异常，请先使能并检查状态。'); return
        angle = self.move_deg.value(); speed = self.move_speed.value()
        ret = QMessageBox.question(self,'确认真实机械运动',
                f'即将控制{self.move_axis.currentText()}执行绝对定位：\n\n目标角度：{angle:.2f}°\n运行速度：{speed:.2f}°/s\n\n确认设备机械范围、零位和线缆安全？',
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ret == QMessageBox.Yes:
            self.turn_worker.submit('move',axis,angle,speed)

    def stop_all(self):
        if self.scan.active:
            self.scan.abort('操作员点击双轴停止')
            return
        if self.turn_worker and self.turn_connected:
            self.turn_worker.submit('stop_all')
            self.write_log('手动请求：已取消待执行运动并优先停车；正在等待双轴静止反馈。')

    def _update_overview(self):
        count = int(self.imu_connected) + int(self.turn_connected)
        self.overview.setText(['● 设备待连接','◐ 已连接 1 / 2','● 双设备已连接'][count])

    def save_log(self):
        file, _ = QFileDialog.getSaveFileName(self,'导出联调日志',str(ROOT / 'bringup_log.txt'),'日志 (*.txt)')
        if file:
            try:
                Path(file).write_text(self.log_text.toPlainText(),encoding='utf-8-sig')
                self.write_log('日志已保存至 ' + file)
            except Exception as exc:
                self.show_error('保存失败',exc)

    def _cleanup_workers(self):
        if self.turn_connected and self.last_fb_monotonic and time.monotonic() - self.last_fb_monotonic > 5.0 and not self._feedback_alerted:
            self._feedback_alerted = True
            self._on_safety_alarm('转台状态反馈超过5秒未刷新；不再允许新的运动/自动检测。请核实现场设备与实体急停。')
        if self.imu_worker and not self.imu_worker.isRunning():
            self.imu_worker = None
            self.imu_connected = False
            self.imu_connect_btn.setEnabled(True)
            self.imu_port.setEnabled(True); self.imu_baud.setEnabled(True); self.imu_addr.setEnabled(True)
            self.imu_connect_btn.setText('连接传感器')
            self.imu_status.setText('○ 未连接')
            self._update_overview()
        if self.turn_worker and not self.turn_worker.isRunning():
            self.turn_worker = None
            self.turn_connected = False
            self.turn_connect_btn.setEnabled(True)
            self.turn_port.setEnabled(True)
            self.turn_connect_btn.setText('连接转台')
            self.turn_status.setText('○ 未连接')
            self.inner_axis.update_info(None,False); self.outer_axis.update_info(None,False)
            self.stop_btn.setEnabled(False); self.move_btn.setEnabled(False)
            self.both_enable_btn.setEnabled(False); self.outer_enable_btn.setEnabled(False); self.diagnose_btn.setEnabled(False)
            self._update_overview()

    def closeEvent(self, event):
        if self.scan.active:
            event.ignore()
            self.show_error('检测进行中','请先点击终止检测/停车，然后再安全断开设备。')
            return
        if self.turn_worker and self.turn_worker.isRunning():
            event.ignore()
            QMessageBox.warning(self,'请先确认转台停车并安全断开',
                '转台控制仍在运行。请点击「安全断开」，完成受控停车和解除使能后再退出。\n'
                '如果转台未能反馈静止状态，软件将拒绝自动关闭端口，请先检查设备。')
            return
        if self.imu_worker and self.imu_worker.isRunning():
            self.imu_worker.stop()
            if not self.imu_worker.wait(2500):
                event.ignore()
                self.show_error('正在停止采集','IMU 读取线程尚未结束，请断开后再退出。')
                return
        event.accept()
