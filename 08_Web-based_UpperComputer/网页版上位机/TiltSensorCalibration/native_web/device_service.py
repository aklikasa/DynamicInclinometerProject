# -*- coding: utf-8 -*-
"""PySide6-free adapter for the original R7 physical device drivers.

Hardware policy: a *single* Web process owns each serial/PLC/DLL connection.
The original desktop application MUST remain closed. This module never sends
PLC setpoint, WK enable, motion, homing or experimental temperature commands.
"""
from __future__ import annotations

import importlib
from collections import deque
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import sys
import threading
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / 'native_web_data'
RECORDS_DIR = DATA_DIR / 'records'
DATA_DIR.mkdir(exist_ok=True)
RECORDS_DIR.mkdir(exist_ok=True)
SETTINGS_FILE = DATA_DIR / 'settings.json'
TD_BINDING_FILE = DATA_DIR / 'td_usb_binding.json'

for part in ('tilt_sensor', 'debug', 'temperature_chamber', 'turntable'):
    directory = str(ROOT / part)
    if directory not in sys.path:
        sys.path.insert(0, directory)

from motion_speed_guard import MAX_ABS_SPEED_DPS  # 原 R7 的 10°/s 软件限速，非厂家 60°/s 额定极限


def _default_settings():
    result = dict(port='COM5', baud=1500000, slave=1, poll_ms=20,
                  plc_ip='', wk_inner='COM8', wk_outer='COM9', td_port='COM4')
    try:
        root = ET.parse(ROOT / 'config.xml').getroot()
        keys = dict(IncCommPort='port', IncBaudrate='baud',
                    Turntable2TD600CommPort='td_port',
                    Turntable2FDT600WKInnerAxisCommPort='wk_inner',
                    Turntable2FDT600WKOuterAxisCommPort='wk_outer')
        for xml_name, setting in keys.items():
            node = root.find(xml_name)
            if node is not None and (node.text or '').strip():
                val = node.text.strip()
                result[setting] = int(val) if setting == 'baud' else val
    except (OSError, ValueError, ET.ParseError):
        pass
    try:
        saved = json.loads(SETTINGS_FILE.read_text(encoding='utf-8'))
        for key in result:
            if key in saved:
                result[key] = saved[key]
    except (OSError, ValueError, TypeError):
        pass
    return result


class DeviceService:
    def __init__(self):
        self.settings = _default_settings()
        self.lock = threading.RLock()
        self.events = []
        # Real PCB data only: bounded live per-frame means for the browser plots.
        # Never consume R7's calibration frame queue or open a second COM port.
        self.trace_lock = threading.Lock()
        self.trace_rows = deque(maxlen=1800)
        self.trace_seq = 0
        self.trace_session = 0
        self.uid_last_retry = 0.0
        self.imu_mod = None
        self.imu_comm_mod = None
        self.csv_mod = None
        self.plc_mod = None
        self.plc_connected = False
        self.plc_stop = threading.Event()
        self.plc_thread = None
        self.plc_state = dict(pv=None, sp=None, alarm=None, fault=None,
                              running=None, last_pv_monotonic=0.0, error='')
        self.td_mod = None
        self.td_connected = False
        self.td_stop = threading.Event()
        self.td_thread = None
        self.td_io_lock = threading.RLock()
        self.td_connection_lock = threading.Lock()
        self.td_disconnecting = False  # blocks new movement/enable during deliberate port close
        self.td_state = dict(inner=None, outer=None, last_monotonic=0.0, error='', identity_verified=False)
        self.wk_mod = None
        self.wk_ports_open = False
        self.wk_stop = threading.Event()
        self.wk_thread = None
        self.wk_state = dict(inner=None, outer=None, last_monotonic=0.0, error='')
        self.td_auto_stop = threading.Event()
        self.td_auto_thread = None
        self.td_auto_suspended = False
        self.td_auto_last_error = ''
        self.td_auto_last_match = ''
        # Historical automatic USB binding is intentionally unused.
        # A serial port is never opened until a person clicks Connect.
        self.td_usb_binding = None
        self.td_motion = dict(state='idle', axis=None, target=None, started=None, message='')
        self.td_motion_lock = threading.RLock()
        self.ambient_capture = None
        self.ambient_auto = None
        self.log('Web 后端启动。所有设备保持断开；2TD600 仅在点击按钮后扫描、连接或执行经确认的手动动作。')

    def log(self, message, level='info'):
        with self.lock:
            self.events.append(dict(time=time.strftime('%Y-%m-%d %H:%M:%S'),
                                    text=str(message)[:250], level=level))
            del self.events[:-150]

    def _persist(self):
        path = SETTINGS_FILE.with_suffix('.new')
        path.write_text(json.dumps(self.settings, ensure_ascii=False, indent=2), encoding='utf-8')
        path.replace(SETTINGS_FILE)

    def update_settings(self, payload):
        with self.lock:
            if not isinstance(payload, dict):
                raise ValueError('无效的设置数据')
            incoming = {k: payload[k] for k in self.settings
                        if k in payload and payload[k] != self.settings[k]}
            if self.imu_mod is not None and self.imu_mod.tiltSensorComm.thread_instance is not None:
                if any(k in incoming for k in ('port', 'baud', 'slave', 'poll_ms')):
                    raise ValueError('先断开 PCB 才能修改串口参数')
            if self.plc_connected and 'plc_ip' in incoming:
                raise ValueError('先断开 PLC 才能修改 IP')
            if self.wk_ports_open and any(k in incoming for k in ('wk_inner', 'wk_outer')):
                raise ValueError('先断开 WK 转台才能修改 COM 口')
            if (self.td_connected or self.td_connection_lock.locked()) and 'td_port' in incoming:
                raise ValueError('先检查并断开 2TD600 才能修改其 COM 口')
            candidate = dict(self.settings, **incoming)
            for k in ('port', 'wk_inner', 'wk_outer', 'td_port'):
                if not isinstance(candidate[k], str) or not re.fullmatch(r'COM[1-9][0-9]{0,2}', candidate[k].upper()):
                    raise ValueError(k + ' 必须是 COMn 格式')
                candidate[k] = candidate[k].upper()
            if candidate['wk_inner'] == candidate['wk_outer']:
                raise ValueError('WK 内外轴不能使用同一个串口')
            for k, lo, hi in [('baud', 9600, 3000000), ('slave', 1, 247), ('poll_ms', 0, 1000)]:
                if isinstance(candidate[k], bool) or not isinstance(candidate[k], int) or not lo <= candidate[k] <= hi:
                    raise ValueError(f'{k} 必须是 {lo}～{hi} 的整数')
            if candidate['plc_ip']:
                try:
                    candidate['plc_ip'] = str(ipaddress.IPv4Address(candidate['plc_ip']))
                except ipaddress.AddressValueError as exc:
                    raise ValueError('PLC IP 请输入有效 IPv4 地址') from exc
            self.settings = candidate
            self._persist()
            self.log('已保存设备连接参数（不会自动连接或执行设备动作）')
            return dict(self.settings)

    def serial_ports(self):
        # This enumerates Windows device ports; the saved COM5 is never injected.
        # Enumeration is read-only and does not open or reserve a serial port.
        try:
            from serial.tools import list_ports
        except ImportError as exc:
            raise RuntimeError('未安装 pyserial。请先运行 Install_Web_Win11.cmd。') from exc
        try:
            result = []
            for p in list_ports.comports():
                result.append(dict(device=str(p.device).upper(), description=str(p.description or '串口设备'),
                    vid=getattr(p, 'vid', None), pid=getattr(p, 'pid', None),
                    serial_number=str(getattr(p, 'serial_number', None) or ''),
                    manufacturer=str(getattr(p, 'manufacturer', None) or '')))
            return result
        except Exception as exc:
            raise RuntimeError(f'Windows 串口枚举失败：{type(exc).__name__}: {exc}') from exc

    # USB descriptor binding is deliberately NOT an assertion that the physical
    # 2TD600 controller has been authenticated. A COM name or VID/PID alone is
    # insufficient: only a previously manually selected adapter with a unique
    # USB serial number may be auto-selected and opened read-only.
    def _read_td_usb_binding(self):
        try:
            data = json.loads(TD_BINDING_FILE.read_text(encoding='utf-8'))
            if (isinstance(data, dict) and isinstance(data.get('enabled'), bool)
                    and isinstance(data.get('serial_number'), str) and data['serial_number']
                    and type(data.get('vid')) is int and type(data.get('pid')) is int):
                return {k:data[k] for k in ('enabled','serial_number','vid','pid')}
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return None

    def _td_matching_ports(self, ports):
        binding = self.td_usb_binding
        if not binding:
            return []
        return [p for p in ports if p.get('serial_number') == binding['serial_number']
                and p.get('vid') == binding['vid'] and p.get('pid') == binding['pid']]

    def td_auto_status(self):
        with self.lock:
            binding = self.td_usb_binding
            return dict(enabled=bool(binding and binding['enabled']),
                        bound=bool(binding), suspended=self.td_auto_suspended,
                        matched_port=self.td_auto_last_match,
                        error=self.td_auto_last_error,
                        mechanism='USB VID/PID + 唯一序列号（非 2TD600 硬件身份）')

    def td_auto_configure(self, payload):
        enabled = payload.get('enabled')
        if type(enabled) is not bool:
            raise ValueError('enabled 必须为 true 或 false')
        if enabled:
            with self.lock:
                if not self.td_connected or time.monotonic()-self.td_state['last_monotonic'] > 4:
                    raise ValueError('请先人工确认 2TD600 COM 并建立有效的只读连接，然后才能绑定')
                selected = self.settings['td_port']
            ports = self.serial_ports()
            candidates = [p for p in ports if p['device'] == selected]
            if len(candidates) != 1:
                raise ValueError('当前转台串口已不在 Windows 的唯一 COM 列表中')
            p = candidates[0]
            if type(p.get('vid')) is not int or type(p.get('pid')) is not int or not p.get('serial_number'):
                raise ValueError('该 USB 串口适配器没有可用的 VID/PID + USB 序列号，无法安全自动识别；请继续手动选端口')
            duplicates = [x for x in ports if x.get('vid') == p['vid'] and
                          x.get('pid') == p['pid'] and x.get('serial_number') == p['serial_number']]
            if len(duplicates) != 1:
                raise ValueError('检测到多个相同 USB 身份的端口，无法唯一识别，禁止自动连接')
            new_binding = dict(enabled=True, vid=p['vid'], pid=p['pid'], serial_number=p['serial_number'])
        else:
            if not self.td_usb_binding:
                return self.td_auto_status()
            new_binding = dict(self.td_usb_binding, enabled=False)
        path = TD_BINDING_FILE.with_suffix('.new')
        path.write_text(json.dumps(new_binding,ensure_ascii=False,indent=2),encoding='utf-8')
        path.replace(TD_BINDING_FILE)
        with self.lock:
            self.td_usb_binding = new_binding
            self.td_auto_last_match = selected if enabled else ''
            self.td_auto_suspended = not enabled
            self.td_auto_last_error = ''
            self.log('2TD600 USB 串口自动匹配已'+('启用（仅只读通讯）' if enabled else '关闭'))
        return self.td_auto_status()

    def td_manual_disconnect(self):
        result = self.td_disconnect()
        with self.lock:
            self.td_auto_suspended = True
        return result

    def td_autoconnect_tick(self):
        # This method runs in the worker, never on the browser status thread.
        with self.lock:
            binding = self.td_usb_binding
            if not binding or not binding['enabled'] or self.td_auto_suspended or self.td_connected:
                return False
        ports = self.serial_ports()  # pure enumeration; does not open or probe ports
        matched = self._td_matching_ports(ports)
        with self.lock:
            self.td_auto_last_match = matched[0]['device'] if len(matched)==1 else ''
            if len(matched)>1:
                self.td_auto_last_error = '匹配到多个相同 USB 身份的端口；拒绝自动连接'
                return False
            if not matched:
                return False
            port = matched[0]['device']
            # Even when another device is offline, never guess that its
            # configured COM may safely be borrowed by the 2TD600.
            occupied = {self.settings['port'],self.settings['wk_inner'],self.settings['wk_outer']}
            if port in occupied:
                self.td_auto_last_error = '自动匹配的 COM 与 PCB/WK 配置冲突，拒绝连接'
                return False
        try:
            self.update_settings({'td_port':port})
            self.td_connect()  # original validated read-only path, no motion
        except (ValueError, RuntimeError, OSError) as exc:
            with self.lock:
                self.td_auto_last_error = str(exc)[:170]
            return False
        with self.lock:
            self.td_auto_last_error = ''
            self.log('2TD600 已按绑定的 USB 串口身份自动接入只读状态：'+port)
        return True

    def start_td_auto_scan(self):
        if self.td_auto_thread is not None:
            return
        self.td_auto_stop.clear()
        def worker():
            while not self.td_auto_stop.is_set():
                try:
                    self.td_autoconnect_tick()
                except Exception as exc:
                    with self.lock:
                        self.td_auto_last_error = str(exc)[:170]
                self.td_auto_stop.wait(5.0)
        self.td_auto_thread = threading.Thread(target=worker,daemon=True,name='2TD600-usb-auto-read-only')
        self.td_auto_thread.start()

    def _imu_modules(self):
        if self.imu_mod is None:
            try:
                self.imu_mod = importlib.import_module('tilt_sensor_asm330_data_get')
                self.imu_comm_mod = importlib.import_module('tilt_sensor_asm330_comm')
                self.csv_mod = importlib.import_module('tilt_sensor_asm330_csv')
            except ImportError as exc:
                self.imu_mod = None
                raise RuntimeError(f'PCB 串口驱动依赖缺失：{exc}。请执行安装依赖脚本。') from exc
        return self.imu_mod, self.csv_mod

    def _trace_frame_from_original_worker(self, wall_seconds, raw_snapshot):
        """Runs on the one existing R7 serial poll thread, after a valid frame.

        Copy only six means and a timestamp; CSV and calibration queues stay intact.
        A failed chart callback must never stop the original serial acquisition.
        """
        with raw_snapshot.data_lock:
            if not raw_snapshot.is_data_valid:
                return
            acc = raw_snapshot.acc_g_arr
            gyro = raw_snapshot.gyr_dps_arr
            n = min(len(acc), len(gyro))
            if n < 1:
                return
            a = [round(sum(x[k] for x in acc[:n]) / n, 7) for k in range(3)]
            g = [round(sum(x[k] for x in gyro[:n]) / n, 7) for k in range(3)]
        with self.trace_lock:
            self.trace_seq += 1
            self.trace_rows.append(dict(seq=self.trace_seq, t=round(float(wall_seconds), 3), acc=a, gyro=g))
        # Same ORIGINAL serial thread, no extra COM reader. Reject any failed
        # ambient callback without interrupting the PCB sampling driver.
        if self.ambient_capture is not None:
            try: self.ambient_capture.on_frame(wall_seconds,raw_snapshot)
            except Exception as exc: self.log('常温工况采样回调异常：'+str(exc),'error')

    def imu_trace(self, since=0):
        """A limited, read-only, incremental stream of measured frame means."""
        if isinstance(since, bool) or not isinstance(since, int) or since < 0:
            raise ValueError('since 必须是非负整数')
        with self.trace_lock:
            session = self.trace_session
            rows = [dict(r) for r in self.trace_rows if r['seq'] > since][-240:]
            latest = self.trace_seq
        c = getattr(self.imu_mod, 'tiltSensorComm', None) if self.imu_mod else None
        live = bool(c and c.is_serial_opened and c.is_data_available and
                    c.last_success_time_sec and time.time() - c.last_success_time_sec <= 3.0)
        return dict(session=session, online=live, latest=latest, samples=rows if live else [])

    def imu_uid_retry(self):
        """Ask the EXISTING serial poll thread to retry the UID register once.

        No direct serial reads here and no second serial port handle is created.
        """
        if self.imu_mod is None:
            raise ValueError('请先连接 PCB')
        c = self.imu_mod.tiltSensorComm
        if not (c.is_serial_opened and c.is_data_available and
                c.last_success_time_sec and time.time() - c.last_success_time_sec < 3.0):
            raise ValueError('请等待 PCB 有效数据后再读取 UID')
        now = time.monotonic()
        with self.lock:
            if now - self.uid_last_retry < 5.0:
                raise ValueError('UID 查询冷却中，请 5 秒后重试')
            self.uid_last_retry = now
            # Reset only the one-shot read flag. Original worker owns the
            # Modbus serial operation and the physical port at all times.
            with c.thread_lock:
                c.device_uid_checked = False
                c.device_uid_raw = ''
                c.device_sn = ''
            self.log('已请求原 PCB 采集线程重新读取 UID（不改变普通采集参数）')
        return '已提交 UID 读取请求；稍后查看 12 字节 UID 和 DTS 设备编号'

    def imu_connect(self):
        with self.lock:
            imu, csv = self._imu_modules()
            c = imu.tiltSensorComm
            if self.td_connected and self.settings['port'] == self.settings['td_port']:
                raise ValueError('PCB 与 2TD600 正使用同一 COM 口；拒绝重复占用')
            if c.thread_instance is not None:
                raise ValueError('PCB 采集线程已运行；无需重复连接')
            c.comm_port = self.settings['port']
            c.baudrate = self.settings['baud']
            c.comm_addr = self.settings['slave']
            c.poll_interval_ms = self.settings['poll_ms']
            c.terminate_thread_requst = False
            csv.csv_pause_set(True)
            # In the original R7 this starts one physical serial poll thread,
            # with auto-reconnect for USB unplug/replug. Never open a second port.
            with self.trace_lock:
                self.trace_session += 1
                self.trace_rows.clear()
            c.web_telemetry_hook = self._trace_frame_from_original_worker
            imu.thread_of_tilt_sensor_data_get_create_and_start()
            if not c.is_serial_opened:
                detail = getattr(self.imu_comm_mod, 'mb_last_serial_error', '') or '未知原因'
                self.log(f"{c.comm_port} 串口打开失败：{detail}；后台将每秒重试", 'warning')
                return f'{c.comm_port} 串口未打开：{detail}。后台正在重试；请检查端口是否存在或被占用。'
            self.log(f"已打开真实 PCB 串口 {c.comm_port} / {c.baudrate}，等待有效 Modbus 帧")
            return f'已打开 {c.comm_port}，正在等待 PCB 有效 Modbus 帧。'

    def imu_disconnect(self):
        if self.ambient_auto is not None and self.ambient_auto.is_active():
            raise RuntimeError('自动常温标定正在运行，请先请求停止并确认双轴静止')
        if self.ambient_capture is not None and self.ambient_capture.is_collecting():
            raise RuntimeError('常温工况正在采样，禁止改变电机/串口/CSV状态；先完成或取消采样')
        with self.lock:
            if self.imu_mod is None:
                return 'PCB 尚未连接'
            imu, csv = self.imu_mod, self.csv_mod
            c = imu.tiltSensorComm
            csv.csv_pause_set(True)
            csv.csv_close()
            if c.thread_instance is not None:
                c.terminate_thread_requst = True
                thread = c.thread_instance
                thread.join(timeout=5.0)
                if thread.is_alive():
                    raise RuntimeError('采集线程仍在结束中，请稍后重试；未强制关闭被占用的串口')
            if c.is_serial_opened:
                imu.tilt_sensor_comm_close()
            c.web_telemetry_hook = None
            with self.trace_lock:
                self.trace_session += 1
                self.trace_rows.clear()
            self.log('PCB 串口已断开，CSV 文件已收尾')
            return '已断开 PCB'

    def imu_record_start(self):
        if self.ambient_auto is not None and self.ambient_auto.is_active():
            raise RuntimeError('自动常温标定正在运行，请先请求停止并确认双轴静止')
        if self.ambient_capture is not None and self.ambient_capture.is_collecting():
            raise RuntimeError('常温工况正在采样，禁止改变电机/串口/CSV状态；先完成或取消采样')
        with self.lock:
            imu, csv = self._imu_modules()
            c = imu.tiltSensorComm
            if not (c.is_data_available and c.last_success_time_sec and time.time() - c.last_success_time_sec < 3.0):
                raise ValueError('没有新鲜的 PCB 有效数据，不能开始记录')
            if csv.csv_is_enabled():
                return 'CSV 已在记录'
            csv.csv_dir_set(str(RECORDS_DIR))
            csv.csv_pause_set(False)
            if not csv.csv_open():
                csv.csv_pause_set(True)
                raise RuntimeError('CSV 打开失败：' + csv.csv_write_error)
            self.log('开始记录 PCB 六轴原始数据到 native_web_data/records')
            return '已开始记录真实采集数据'

    def imu_record_stop(self):
        with self.lock:
            if self.csv_mod is None:
                return '未启动记录'
            self.csv_mod.csv_pause_set(True)
            self.csv_mod.csv_close()
            self.log('CSV 记录停止并已写盘')
            return 'CSV 记录已保存'

    def _imu_snapshot(self):
        if self.imu_mod is None:
            return dict(connected=False, reading=False, recording=False, values=None,
                        port=self.settings['port'], device_uid_raw='', serial_number='', uid_checked=False, reason='尚未启动 PCB 采集')
        imu, csv = self.imu_mod, self.csv_mod
        c = imu.tiltSensorComm
        fresh = (c.is_serial_opened and c.is_data_available and c.last_success_time_sec > 0 and
                 time.time() - c.last_success_time_sec <= 3.0)
        data = None
        if fresh:
            r = imu.tiltSensorRawData
            with r.data_lock:
                if r.is_data_valid:
                    n = len(r.acc_g_arr)
                    if n:
                        data = dict(acc=[round(sum(row[i] for row in r.acc_g_arr)/n, 6) for i in range(3)],
                                    gyro=[round(sum(row[i] for row in r.gyr_dps_arr)/n, 6) for i in range(3)],
                                    temperature=round(r.temp_c, 3), tick_ms=r.tick_ms,
                                    acc_fs=r.acc_fs, gyro_fs=r.gyro_fs,
                                    odr=r.data_odr, fifo_state=r.fifo_state,
                                    frame_number=r.data_update_count)
        thread = getattr(c, 'thread_instance', None)
        thread_running = bool(thread is not None and thread.is_alive())
        open_error = getattr(self.imu_comm_mod, 'mb_last_serial_error', '') or ''
        if data is not None:
            reason = '实时 PCB 有效帧'
        elif not thread_running and not c.is_serial_opened:
            reason = 'PCB 已断开' if c.comm_total_count else '尚未连接 PCB'
        elif not c.is_serial_opened:
            reason = f'串口打开失败：{open_error}' if open_error else '串口未打开，正在重试'
        elif c.comm_total_count:
            reason = f"串口已打开但没有有效 Modbus 数据：{getattr(imu, 'tilt_sensor_comm_error_text_get', lambda: '等待有效帧')()}（成功 {c.comm_success_count}/{c.comm_total_count}）"
        else:
            reason = '串口已打开，等待 PCB 首帧数据'
        return dict(connected=bool(c.is_serial_opened), reading=data is not None,
                    thread_running=thread_running, open_error=open_error[:300],
                    recording=bool(csv.csv_is_enabled()), values=data,
                    port=c.comm_port, baud=c.baudrate, serial_number=c.device_sn,
                    device_uid_raw=getattr(c, 'device_uid_raw', ''),
                    uid_checked=bool(getattr(c, 'device_uid_checked', False)),
                    comm_rate=c.comm_rate if data else None,
                    success_count=c.comm_success_count, total_count=c.comm_total_count,
                    last_success=c.last_success_time_text or None,
                    frame_interval_ms=c.frame_interval_ms if data else None,
                    record_rows=csv.csv_row_count, record_drop=csv.csv_drop_count,
                    record_path=Path(csv.csv_file_path).name if csv.csv_file_path else None,
                    error=csv.csv_write_error or '',
                    reason=reason)

    def _plc_driver(self):
        if self.plc_mod is None:
            try:
                self.plc_mod = importlib.import_module('temperature_chamber_comm')
            except ImportError as exc:
                raise RuntimeError(f'PLC 依赖不可用：{exc}。请安装 python-snap7。') from exc
        return self.plc_mod

    def plc_connect(self):
        with self.lock:
            if self.plc_connected:
                raise ValueError('PLC 已连接')
            if not self.settings['plc_ip']:
                raise ValueError('请先保存 PLC IPv4 地址')
            tc = self._plc_driver()
            if not tc.tc_connect(self.settings['plc_ip']):
                raise RuntimeError('真实 PLC 连接失败，请检查 IP、PLC 供电和网络')
            self.plc_connected = True
            self.plc_state = dict(pv=None, sp=None, alarm=None, fault=None,
                                  running=None, last_pv_monotonic=0.0, error='')
            self.plc_stop.clear()
            self.plc_thread = threading.Thread(target=self._poll_plc, daemon=True, name='PLC-read-only')
            self.plc_thread.start()
            self.log('PLC 已连接：只读 PV/SP/报警/运行状态，不写设定温度')
            return 'PLC 连接成功，开始读取真实温箱状态'

    def _poll_plc(self):
        while not self.plc_stop.is_set():
            try:
                with self.lock:
                    if not self.plc_connected:
                        break
                    tc = self.plc_mod
                    if not tc.tc_connect_state_get():
                        self.plc_state['error'] = 'PLC 通信已断开'
                    else:
                        # The original PLC register mapping and parsing remain untouched.
                        pv = tc.tc_pv_get()
                        sp = tc.tc_sp_get()
                        alarm = tc.tc_alarm_value_get()
                        fault = tc.tc_device_fault_state_get()
                        running = tc.tc_run_state_get()
                        if pv is not None:
                            self.plc_state.update(pv=pv, last_pv_monotonic=time.monotonic(), error='')
                        else:
                            self.plc_state['error'] = 'PLC PV 读数失败'
                        if sp is not None: self.plc_state['sp'] = sp
                        if alarm is not None: self.plc_state['alarm'] = alarm
                        if fault is not None: self.plc_state['fault'] = fault
                        if running is not None: self.plc_state['running'] = running
            except Exception as exc:
                with self.lock:
                    self.plc_state['error'] = str(exc)[:180]
            self.plc_stop.wait(1.5)

    def plc_disconnect(self):
        self.plc_stop.set()
        if self.plc_thread and threading.current_thread() is not self.plc_thread:
            self.plc_thread.join(timeout=6.0)
            if self.plc_thread.is_alive():
                raise RuntimeError('PLC 读数尚未结束，请稍后重试')
        with self.lock:
            if self.plc_connected:
                self.plc_mod.tc_disconnect()
            self.plc_connected = False
            self.plc_state['last_pv_monotonic'] = 0.0
            self.log('PLC 已断开')
        return 'PLC 已断开'

    def _wk_driver(self):
        if os.name != 'nt':
            raise RuntimeError('WK 厂商 DLL 只能在 Windows 64/32 位匹配的环境加载')
        if self.wk_mod is None:
            try:
                self.wk_mod = importlib.import_module('turntable_2FDT600WK_comm')
            except Exception as exc:
                raise RuntimeError('WK 厂家 DLL 加载失败，请核对 Windows、Python 和 DLL 位数：' + str(exc)) from exc
        return self.wk_mod

    def _wk_read_axis(self, axis):
        alarm, mode, angle, err = [0], [0], [0.0], [0]
        ok = self.wk_mod.twoFDT600WK_getAxisStateInfo(axis, alarm, mode, angle, err)
        if not ok:
            raise RuntimeError(f'轴 {axis} 未收到有效状态帧，DLL错误码 {err[0]}')
        return dict(alarm=alarm[0], state=mode[0], angle=round(angle[0], 5), error=err[0])

    def wk_connect(self):
        with self.lock:
            if self.wk_ports_open:
                raise ValueError('WK 已连接')
            wk = self._wk_driver()
            if self.td_connected and self.settings['td_port'] in (self.settings['wk_inner'], self.settings['wk_outer']):
                raise ValueError('2TD600 已占用 WK 配置的串口；拒绝重复连接')
            opened = []
            try:
                # COM axes are explicit; never autodetect by trying to move motors.
                for axis, name in ((wk.INNER_ROTATION_AXIS, 'wk_inner'),
                                   (wk.OUTER_ROTATION_AXIS, 'wk_outer')):
                    port_num = int(self.settings[name][3:])
                    e = [0]
                    if not wk.twoFDT600WK_openAxisPort(axis, port_num, 115200, e):
                        raise RuntimeError(f'{name} COM{port_num} 打开失败，厂家错误码 {e[0]}')
                    opened.append(axis)
                # The original DLL OpenPort resets timeouts, set both after BOTH ports open.
                for axis in opened:
                    e = [0]
                    if not wk.twoFDT600WK_setAxisTimeout(axis, 1000, e):
                        raise RuntimeError(f'WK 设置超时失败：{e[0]}')
                last_error = None
                for attempt in range(4):
                    try:
                        inner = self._wk_read_axis(wk.INNER_ROTATION_AXIS)
                        outer = self._wk_read_axis(wk.OUTER_ROTATION_AXIS)
                        last_error = None
                        break
                    except RuntimeError as exc:
                        last_error = exc
                        time.sleep(0.2)
                if last_error:
                    raise last_error
            except Exception:
                for axis in reversed(opened):
                    try: wk.twoFDT600WK_closeAxisPort(axis, [0])
                    except Exception: pass
                raise
            self.wk_ports_open = True
            self.wk_state = dict(inner=inner, outer=outer, last_monotonic=time.monotonic(), error='')
            self.wk_stop.clear()
            self.wk_thread = threading.Thread(target=self._poll_wk, daemon=True, name='WK-read-only')
            self.wk_thread.start()
            self.log('WK 双轴真实状态读取已连接；没有发送使能、回零或运动命令')
            return 'WK 状态通讯已建立（只读，不会自动使能）'

    def _poll_wk(self):
        while not self.wk_stop.is_set():
            try:
                with self.lock:
                    if not self.wk_ports_open: break
                    wk = self.wk_mod
                    i = self._wk_read_axis(wk.INNER_ROTATION_AXIS)
                    o = self._wk_read_axis(wk.OUTER_ROTATION_AXIS)
                    self.wk_state.update(inner=i, outer=o, last_monotonic=time.monotonic(), error='')
            except Exception as exc:
                with self.lock:
                    self.wk_state['error'] = str(exc)[:180]
            self.wk_stop.wait(0.6)

    def wk_disconnect(self):
        self.wk_stop.set()
        if self.wk_thread and threading.current_thread() is not self.wk_thread:
            self.wk_thread.join(timeout=4.0)
            if self.wk_thread.is_alive():
                raise RuntimeError('WK 状态读取尚未结束；未强制断开通讯')
        with self.lock:
            if not self.wk_ports_open:
                return 'WK 尚未连接'
            # A browser must never unilaterally sever communication during motion.
            wk = self.wk_mod
            try:
                i = self._wk_read_axis(wk.INNER_ROTATION_AXIS)
                o = self._wk_read_axis(wk.OUTER_ROTATION_AXIS)
            except Exception as exc:
                self.wk_stop.clear()
                self.wk_thread = threading.Thread(target=self._poll_wk, daemon=True)
                self.wk_thread.start()
                raise RuntimeError('未确认双轴静止，拒绝断开 WK 通讯：' + str(exc)) from exc
            if any(s['state'] not in (0, 1) for s in (i, o)):
                self.wk_stop.clear()
                self.wk_thread = threading.Thread(target=self._poll_wk, daemon=True)
                self.wk_thread.start()
                raise ValueError('WK 双轴未确认处于空闲/伺服静止状态，拒绝断开')
            for axis in (wk.INNER_ROTATION_AXIS, wk.OUTER_ROTATION_AXIS):
                e = [0]
                if not wk.twoFDT600WK_closeAxisPort(axis, e):
                    raise RuntimeError(f'WK 端口关闭未完成：轴{axis}，错误码{e[0]}')
            self.wk_ports_open = False
            self.wk_state['last_monotonic'] = 0.0
            self.log('WK 双轴通讯已断开')
        return 'WK 已断开'

    # 2TD600 is the separate ambient IMU calibration turntable, NOT 2FDT600WK.
    # This R7 vendor DLL does not expose a validated passive device-identity
    # signature. Therefore DLL readback values NEVER imply authenticated hardware.
    # No enabling, homing, positional or velocity commands are registered here.
    # 2TD600 connection is deliberately click-driven, never scheduled on boot.
    # Without a vendor device identifier, only one unoccupied COM candidate may
    # be auto-selected. When ambiguous, the user must explicitly choose a port.
    def td_scan_connect(self):
        if self.td_connected:
            return f'2TD600 已连接 {self.settings["td_port"]}，无需重新打开'
        ports = self.serial_ports()
        with self.lock:
            # A configured PCB/WK port remains reserved even if disconnected;
            # a one-click scan must not claim an unrelated instrument port.
            occupied = {self.settings['port'], self.settings['wk_inner'], self.settings['wk_outer']}
            if self.imu_mod is not None:
                c = self.imu_mod.tiltSensorComm
                if getattr(c, 'thread_instance', None) is not None:
                    occupied.add(str(c.comm_port).upper())
            if self.wk_ports_open:
                occupied.update([self.settings['wk_inner'], self.settings['wk_outer']])
        candidates = sorted({p['device'].upper() for p in ports
                            if re.fullmatch(r'COM[1-9][0-9]{0,2}', p['device'].upper())
                            and p['device'].upper() not in occupied},
                            key=lambda port:int(port[3:]))
        if not candidates:
            raise ValueError('没有可用的 Windows COM 口；检查转台电源、USB 驱动和设备管理器')
        if len(candidates) != 1:
            raise ValueError('检测到多个可用串口：'+', '.join(candidates)+'。厂家 DLL 不提供设备识别码；请在下拉框选择转台 COM 后点击“连接选中串口”，不会逐口试探其他设备。')
        selected = candidates[0]
        with self.lock:
            if self.td_connected:
                return '2TD600 已连接'
            self.settings['td_port'] = selected
            self._persist()
        self.td_connect()
        self.log('按钮触发了 Windows COM 扫描，唯一空闲端口 '+selected+' 已建立 2TD600 通讯。')
        return '已扫描并连接 '+selected+'（只有一个可用的空闲 COM 口，仍须现场确认接线）'

    @staticmethod
    def _td_angle_diff(actual, target):
        return (float(actual)-float(target)+180.0)%360.0-180.0

    def _td_safety_snapshot(self, require_enabled=True):
        # Read every interlock from original driver; fail closed.
        td=self._td_driver()
        axes={}
        for label,axis in (('inner',td.INNER_ROTATION_AXIS),('outer',td.OUTER_ROTATION_AXIS)):
            flags={
                'enabled':td.twoTD600_getAxisEnable(axis),
                'normal':td.twoTD600_getAxisNormal(axis),
                'zero':td.twoTD600_getAxisFindZero(axis),
                'driver_fault':td.twoTD600_getAxisDriverFault(axis),
                'overspeed':td.twoTD600_getAxisOverSpeed(axis),
                'following_error':td.twoTD600_getAxisOverDiff(axis),
                'overvoltage':td.twoTD600_getAxisOverVoltage(axis),
                'up_limit':td.twoTD600_getAxisUpLimit(axis),
                'down_limit':td.twoTD600_getAxisDownLimit(axis),
            }
            if any(type(val) is not bool for val in flags.values()):
                raise RuntimeError(label+' 轴安全状态返回未知值，拒绝运动')
            required = ('enabled','normal','zero') if require_enabled else ('normal','zero')
            if not all(flags[k] for k in required):
                raise RuntimeError(label+' 轴未使能、非正常或未机械找零；请在现场使用原控制台确认')
            if any(flags[k] for k in ('driver_fault','overspeed','following_error','overvoltage','up_limit','down_limit')):
                raise RuntimeError(label+' 轴存在驱动故障、超差、超速、电压或限位报警；拒绝运动')
            position=float(td.twoTD600_getPositionRaw(axis))
            speed=float(td.twoTD600_getSpeedRaw(axis))
            mode=str(td.twoTD600_getRunMode(axis))
            if not math.isfinite(position) or not math.isfinite(speed):
                raise RuntimeError(label+' 轴反馈包含非有限值')
            axes[label]=dict(position=position,speed=speed,mode=mode)
        return axes

    def td_enable_axes(self, payload):
        if self.ambient_auto is not None and self.ambient_auto.is_active():
            raise RuntimeError('自动常温标定正在运行，请先请求停止并确认双轴静止')
        if self.ambient_capture is not None and self.ambient_capture.is_collecting():
            raise RuntimeError('常温工况正在采样，禁止改变电机/串口/CSV状态；先完成或取消采样')
        # Explicit action separate from COM connect; powering motors can change
        # holding torque. Never perform this silently during COM discovery.
        if payload.get('safety_ack')!='PHYSICAL_ESTOP_READY':
            raise ValueError('请先在现场检查机械结构、转台供电、线缆与独立硬件急停')
        with self.td_motion_lock:
            if self.td_disconnecting:
                raise RuntimeError('2TD600 正在断开串口，禁止使能')
            with self.lock:
                if not self.td_connected or time.monotonic()-self.td_state['last_monotonic']>1.75:
                    raise RuntimeError('没有新鲜的转台反馈，不能使能电机')
                if self.td_motion.get('state') not in ('idle','complete','stopped'):
                    raise RuntimeError('转台仍在运动或停车检查中，不能再次使能')
            with self.td_io_lock:
                states=self._td_safety_snapshot(require_enabled=False)
                if any(abs(x['speed'])>0.05 or x['mode'] not in ('空闲','静止','停止') for x in states.values()):
                    raise RuntimeError('转台未确认双轴静止，不能使能')
                td=self._td_driver()
                for label,axis in (('inner',td.INNER_ROTATION_AXIS),('outer',td.OUTER_ROTATION_AXIS)):
                    if td.twoTD600_getAxisEnable(axis) is not True:
                        if not td.twoTD600_SetAxisEnable(axis):
                            raise RuntimeError(label+' 轴使能命令被厂家 DLL 拒绝，请检查现场转台')
                time.sleep(0.25)
                for axis in (td.INNER_ROTATION_AXIS,td.OUTER_ROTATION_AXIS):
                    if td.twoTD600_getAxisEnable(axis) is not True:
                        raise RuntimeError('厂家 DLL 未确认双轴均使能，请停止操作并检查现场')
        self.log('2TD600 用户主动确认后使能双轴电机','warning')
        return '厂家 DLL 已确认双轴使能；使能不等于允许无监护运动'

    @staticmethod
    def _td_position_speed(speed):
        if isinstance(speed, bool) or not isinstance(speed, (int, float)) or not math.isfinite(speed):
            raise ValueError('运动速度必须是数字')
        if not (0.01 <= float(speed) <= MAX_ABS_SPEED_DPS):
            raise ValueError(f'运动速度要求 0.01～{MAX_ABS_SPEED_DPS:g}°/s。厂家额定最高 60°/s，原 R7 软件限速仍为 {MAX_ABS_SPEED_DPS:g}°/s')
        return float(speed)

    @staticmethod
    def _td_motion_deadline(delta_deg, speed):
        return time.monotonic() + max(15.0, abs(float(delta_deg)) / float(speed) * 3.0 + 10.0)

    def _td_ready_to_move(self):
        if self.td_disconnecting:
            raise RuntimeError('2TD600 正在断开串口，禁止下发新运动指令')
        with self.lock:
            if not self.td_connected or time.monotonic()-self.td_state['last_monotonic'] >= 1.75:
                raise RuntimeError('2TD600 未连接或反馈过期超过 1.75 秒，禁止运动')
            if self.td_motion['state'] not in ('idle', 'complete', 'stopped'):
                raise RuntimeError('转台处于运动、停车或故障未确认状态，请先检查实际反馈及硬件安全')
        states = self._td_safety_snapshot()
        if any(abs(item['speed']) > 0.05 or item['mode'] not in ('空闲', '静止', '停止') for item in states.values()):
            raise RuntimeError('双轴未确认静止，禁止发送新的位置指令')
        return states

    def td_jog(self, payload):
        if self.ambient_auto is not None and self.ambient_auto.is_active():
            raise RuntimeError('自动常温标定正在运行，请先请求停止并确认双轴静止')
        if self.ambient_capture is not None and self.ambient_capture.is_collecting():
            raise RuntimeError('常温工况正在采样，禁止改变电机/串口/CSV状态；先完成或取消采样')
        # No invented 0.5..5 degree test range. Preserve real R7 protection and device flags.
        if not isinstance(payload, dict):
            raise ValueError('参数不是对象')
        if payload.get('safety_ack') != 'PHYSICAL_ESTOP_READY':
            raise ValueError('请先在现场确认机械安装、线缆和硬件急停，并勾选操作确认')
        axis_name = payload.get('axis')
        if axis_name not in ('inner', 'outer'):
            raise ValueError('轴必须选择内轴或外轴')
        step = payload.get('step_deg')
        if isinstance(step, bool) or not isinstance(step, (int, float)) or not math.isfinite(step) or abs(step) < 0.000001:
            raise ValueError('相对转角必须是非零的有限数值，可自由输入任意小数')
        speed = self._td_position_speed(payload.get('speed_dps'))
        with self.td_motion_lock:
            with self.td_io_lock:
                state = self._td_ready_to_move()
                # The UI asks for an INCREMENT, not an absolute encoder coordinate.
                # 2TD-600 manual appendix A.5 lists D6 for relative positioning;
                # R7's vendor wrapper exposes D6 as SetAxisOpposition.
                # Never calculate current+increment then constrain it to +/-360 deg.
                # Nor use modulo on the requested increment: +720 means TWO turns.
                if axis_name == 'inner' and abs(self._td_angle_diff(state['outer']['position'], 0.0)) > 0.2:
                    raise RuntimeError('按 2TD-600 说明书，内轴旋转前须确认外轴位于零位且静止；当前外轴非零位')
                td = self._td_driver()
                axis = td.INNER_ROTATION_AXIS if axis_name == 'inner' else td.OUTER_ROTATION_AXIS
                if not callable(getattr(td, 'twoTD600_SetAxisOpposition', None)):
                    raise RuntimeError('2TD600 厂家驱动缺少相对位置函数，拒绝退回绝对位置指令')
                ok = td.twoTD600_SetAxisOpposition(axis, float(step), speed) is True
                initial = float(state[axis_name]['position'])
            if not ok:
                raise RuntimeError('厂家 DLL 拒绝相对位置指令；未确认转台发生运动')
            start = time.monotonic()
            self.td_motion = dict(state='moving', job='manual', mode='relative', axis=axis_name,
                requested_step_deg=float(step), travelled_deg=0.0,
                last_angle=initial, last_update=start, target=None,
                command_speed=speed, started=start, deadline=self._td_motion_deadline(step, speed),
                message=f'{axis_name} 相对转动 {float(step):+g}°，速度 {speed:g}°/s；等待累计转角、到位与停稳反馈')
            self.log('2TD600 用户手动增量运动（厂家 D6 指令）：' + self.td_motion['message'], 'warning')
        return dict(self.td_motion)

    def td_return_zero(self, payload):
        if self.ambient_auto is not None and self.ambient_auto.is_active():
            raise RuntimeError('自动常温标定正在运行，请先请求停止并确认双轴静止')
        if self.ambient_capture is not None and self.ambient_capture.is_collecting():
            raise RuntimeError('常温工况正在采样，禁止改变电机/串口/CSV状态；先完成或取消采样')
        """Dual *position* return (not mechanical homing): outer 0 then inner 0.

        Execute one axis at a time in the backend feedback monitor, not in a browser
        promise chain. Browser closure does not stop a running motion; operators
        must use software stop or the physical emergency stop when necessary.
        """
        if not isinstance(payload, dict) or payload.get('safety_ack') != 'PHYSICAL_ESTOP_READY':
            raise ValueError('双轴回到 0° 前必须现场确认工装、硬件急停、机械找零及线缆空间')
        outer_speed = self._td_position_speed(payload.get('outer_speed_dps'))
        inner_speed = self._td_position_speed(payload.get('inner_speed_dps'))
        speeds = dict(outer=outer_speed, inner=inner_speed)
        with self.td_motion_lock:
            with self.td_io_lock:
                state = self._td_ready_to_move()
                remaining = [axis for axis in ('outer', 'inner') if abs(self._td_angle_diff(state[axis]['position'], 0.)) > 0.2]
                if not remaining:
                    self.td_motion = dict(state='complete', job='dual_zero', axis=None, target=0., started=None,
                                          message='双轴当前位置已在 0° 附近，未发送运动指令')
                    return dict(self.td_motion)
                first = remaining[0]
                td = self._td_driver()
                axis = td.OUTER_ROTATION_AXIS if first == 'outer' else td.INNER_ROTATION_AXIS
                if not td.twoTD600_SetAxisPosition(axis, 0.0, speeds[first]):
                    raise RuntimeError('厂家 DLL 拒绝 ' + first + ' 轴位置归零指令')
            self.td_motion = dict(state='moving', job='dual_zero', axis=first, target=0.0,
                remaining=remaining[1:], speeds=speeds, command_speed=speeds[first],
                started=time.monotonic(), stable_since=None, deadline=self._td_motion_deadline(state[first]['position'], speeds[first]),
                message=('双轴位置回零第 1 段：' + first + ' 轴前往 0°；下一轴将在确认到位停稳后执行'))
            self.log('2TD600 用户主动启动顺序双轴位置回零：外轴优先、内轴后续', 'warning')
        return dict(self.td_motion)

    def td_stop_all(self):
        # Operator software stop cancels the background sequencer before writing stop.
        if self.ambient_auto is not None and self.ambient_auto.is_active():
            self.ambient_auto.request_abort()
        # Software stop is best effort; not E-STOP.
        with self.td_motion_lock:
            with self.lock:
                if not self.td_connected: raise RuntimeError('2TD600 尚未连接；软件停车无法发出，请使用硬件急停')
            with self.td_io_lock:
                td=self._td_driver()
                result={label:bool(td.twoTD600_SetAxisStop(axis))
                        for label,axis in (('inner',td.INNER_ROTATION_AXIS),('outer',td.OUTER_ROTATION_AXIS))}
            self.td_motion=dict(state='stopping',axis=None,target=None,started=time.monotonic(),
                                deadline=time.monotonic()+20.0,
                                message='双轴停车命令已发送，必须观察现场转台是否确实停稳')
            self.log('2TD600 双轴停车命令：'+str(result),'warning')
            if not all(result.values()):
                raise RuntimeError('双轴停车指令未全部被 DLL 接受，请立即使用现场硬件急停并检查设备')
        return '已发送双轴停车命令，必须确认真实角速度下降至零；软件停车不是急停'

    def _td_monitor_motion(self, state):
        # Backend-only movement sequencer: fail closed on stale/unknown motor state.
        with self.td_motion_lock:
            motion = self.td_motion
            if motion['state'] not in ('moving', 'stopping'):
                return
            now = time.monotonic()
            try:
                with self.td_io_lock:
                    safe = self._td_safety_snapshot()
                command_speed = float(motion.get('command_speed') or MAX_ABS_SPEED_DPS)
                # Keep original R7 absolute speed guard while allowing transient tolerance.
                if any(abs(x['speed']) > MAX_ABS_SPEED_DPS + 0.5 or
                       (motion['state'] == 'moving' and abs(x['speed']) > command_speed * 1.5 + 0.5)
                       for x in safe.values()):
                    raise RuntimeError('实际反馈速度超过所下发指令或原 R7 软件限速')
                if motion['state'] == 'moving':
                    axis = motion['axis']
                    info = safe[axis]
                    if now > motion['deadline']:
                        raise RuntimeError('位置运动超过预计最长用时')
                    td = self._td_driver()
                    idx = td.INNER_ROTATION_AXIS if axis == 'inner' else td.OUTER_ROTATION_AXIS
                    with self.td_io_lock:
                        in_place = td.twoTD600_getAxisMoveInPlace(idx)
                    if type(in_place) is not bool:
                        raise RuntimeError('厂家 DLL 到位状态不明确')
                    if motion.get('mode') == 'relative':
                        # Position feedback may wrap at +/-180 or 0..360, and 360n
                        # is the same orientation but NOT the same travel distance.
                        # Accumulate each fresh short-interval delta, never use
                        # (current-target) % 360 to declare a multirevolution move done.
                        elapsed = now - float(motion['last_update'])
                        if elapsed < 0 or elapsed > 1.75:
                            raise RuntimeError('相对运动角度反馈间隔过长，累计圈数不可确认，必须停车')
                        delta = self._td_angle_diff(info['position'], motion['last_angle'])
                        # At <=R7 10 deg/s, enormous sample-to-sample jumps are
                        # implausible: fail closed rather than losing turns.
                        max_plausible = (command_speed + 0.5) * max(elapsed, 0.05) * 2.5 + 2.5
                        if abs(delta) > max_plausible:
                            raise RuntimeError('相对运动角度反馈跳变过大，无法安全累计实际圈数')
                        other = 'outer' if axis == 'inner' else 'inner'
                        if abs(safe[other]['speed']) >= 0.05:
                            raise RuntimeError('相对位置运动中另一轴出现非预期旋转')
                        motion['travelled_deg'] += delta
                        motion['last_angle'] = info['position']
                        motion['last_update'] = now
                        requested = float(motion['requested_step_deg'])
                        arrived = (in_place and abs(info['speed']) < 0.05
                                   and abs(motion['travelled_deg'] - requested) <= 0.2)
                    else:
                        arrived = in_place and abs(info['speed']) < 0.05 and abs(self._td_angle_diff(info['position'], motion['target'])) <= 0.2
                    if motion.get('job') == 'dual_zero':
                        if not arrived:
                            motion['stable_since'] = None
                        elif motion.get('stable_since') is None:
                            motion['stable_since'] = now
                            return
                        elif now - motion['stable_since'] < 0.5:
                            return
                    if arrived:
                        if motion.get('job') == 'dual_zero' and motion.get('remaining'):
                            next_axis = motion['remaining'][0]
                            # Never issue next command while another axis has residual motion.
                            if any(abs(item['speed']) >= 0.05 or (name != axis and item['mode'] not in ('空闲', '静止', '停止'))
                                   for name, item in safe.items()):
                                return
                            next_speed = motion['speeds'][next_axis]
                            next_idx = td.INNER_ROTATION_AXIS if next_axis == 'inner' else td.OUTER_ROTATION_AXIS
                            with self.td_io_lock:
                                confirmed = self._td_safety_snapshot()
                                if any(abs(x['speed']) >= 0.05 for x in confirmed.values()):
                                    return
                                ok = td.twoTD600_SetAxisPosition(next_idx, 0.0, next_speed)
                            if not ok:
                                raise RuntimeError('第二轴回到 0° 指令被厂家 DLL 拒绝')
                            self.td_motion = dict(state='moving', job='dual_zero', axis=next_axis, target=0.0,
                                remaining=motion['remaining'][1:], speeds=motion['speeds'], command_speed=next_speed,
                                started=now, stable_since=None, deadline=self._td_motion_deadline(confirmed[next_axis]['position'], next_speed),
                                message='第一轴已确认回 0° 并停稳；正在执行 ' + next_axis + ' 轴回 0°')
                            self.log(self.td_motion['message'], 'warning')
                        else:
                            self.td_motion = dict(state='complete', job=motion.get('job', 'manual'),
                                axis=axis, target=motion['target'], started=None,
                                travelled_deg=motion.get('travelled_deg'), requested_step_deg=motion.get('requested_step_deg'),
                                message='已核对实际反馈速度和到位标志；' + ('双轴位置归零完成' if motion.get('job') == 'dual_zero' else f'相对转角累计 {motion.get("travelled_deg", 0.):+.3f}°，目标 {motion.get("requested_step_deg", 0.):+.3f}°，单轴增量运动完成'))
                            self.log('2TD600 反馈到位：' + self.td_motion['message'])
                elif all(abs(x['speed']) < 0.05 for x in safe.values()):
                    self.td_motion = dict(state='stopped', axis=None, target=None, started=None, message='反馈显示双轴静止')
                elif now > motion['deadline']:
                    raise RuntimeError('20 秒后仍未确认双轴停车，必须使用硬件急停')
            except Exception as exc:
                self.td_motion = dict(state='fault', axis=None, target=None, started=None,
                                      message='运动监控异常：' + str(exc)[:190])
                try:
                    with self.td_io_lock:
                        td = self._td_driver()
                        td.twoTD600_SetAxisStop(td.INNER_ROTATION_AXIS)
                        td.twoTD600_SetAxisStop(td.OUTER_ROTATION_AXIS)
                except Exception as stop_error:
                    self.log('2TD600 监控停车命令亦失败：' + str(stop_error), 'error')
                self.log('2TD600 异常请求软件停车：' + str(exc) + '；必须现场核对硬件急停', 'error')

    def _td_driver(self):
        if os.name != 'nt':
            raise RuntimeError('2TD600 厂家 DLL 只能在匹配位数的 Windows 环境加载')
        if self.td_mod is None:
            try:
                self.td_mod = importlib.import_module('turntable_2TD600_comm')
            except Exception as exc:
                raise RuntimeError('2TD600.dll 加载失败；检查文件存在、运行库及 Python/DLL 位数：' + str(exc)) from exc
        return self.td_mod

    def _td_read_axes(self):
        td = self._td_driver()
        result = {}
        for label, axis in (('inner', td.INNER_ROTATION_AXIS), ('outer', td.OUTER_ROTATION_AXIS)):
            angle = float(td.twoTD600_getPositionRaw(axis))
            speed = float(td.twoTD600_getSpeedRaw(axis))
            if not (math.isfinite(angle) and math.isfinite(speed)) or abs(angle) > 1_000_000 or abs(speed) > 100_000:
                raise RuntimeError('2TD600 DLL 返回非正常数值；不能当作有效位置反馈')
            result[label] = dict(angle=round(angle, 5), speed=round(speed, 5),
                                 mode=str(td.twoTD600_getRunMode(axis)),
                                 enabled=bool(td.twoTD600_getAxisEnable(axis)),
                                 zero=bool(td.twoTD600_getAxisFindZero(axis)),
                                 normal=bool(td.twoTD600_getAxisNormal(axis)))
        return result

    def td_connect(self):
        if not self.td_connection_lock.acquire(blocking=False):
            raise RuntimeError('2TD600 正在进行其他连接操作，请勿重复提交')
        try:
            return self._td_connect_inner()
        finally:
            self.td_connection_lock.release()

    def _td_connect_inner(self):
        with self.lock:
            if self.td_connected:
                raise ValueError('2TD600 串口已打开')
            port = self.settings['td_port']
            if self.imu_mod is not None and getattr(self.imu_mod.tiltSensorComm, 'thread_instance', None) is not None and port == self.settings['port']:
                raise ValueError('2TD600 与正在轮询的 PCB 共用串口；拒绝重复占用')
            if self.wk_ports_open and port in (self.settings['wk_inner'], self.settings['wk_outer']):
                raise ValueError('2TD600 与已连接 WK 共用串口；拒绝重复占用')
        td = self._td_driver()
        with self.td_io_lock:
            opened = bool(td.twoTD600_openPort(int(port[3:]), 115200))
            if not opened:
                raise RuntimeError('2TD600 厂家 DLL 未能打开 ' + port + '；检查实际串口和占用状态')
            try:
                values = self._td_read_axes()
            except Exception:
                td.twoTD600_closePort()
                raise
        with self.lock:
            self.td_connected = True
            self.td_state = dict(**values, last_monotonic=time.monotonic(), error='', identity_verified=False)
            self.td_stop.clear()
            self.td_thread = threading.Thread(target=self._poll_td, daemon=True, name='2TD600-read-only')
            self.td_thread.start()
            self.log(f'2TD600 {port} 已打开且 DLL 返回状态；未做设备身份认证，未发送任何运动指令', 'warning')
        return '2TD600 串口已打开，已读取厂家 DLL 返回值；不能仅凭这些返回值确认物理设备身份，请现场核对。'

    def _poll_td(self):
        while not self.td_stop.is_set():
            try:
                with self.td_io_lock:
                    values = self._td_read_axes()
                with self.lock:
                    self.td_state.update(**values, last_monotonic=time.monotonic(), error='')
                if self.ambient_capture is not None:
                    try:self.ambient_capture.on_turntable_poll(values,time.monotonic())
                    except Exception as exc:self.log('转台独立反馈采集异常：'+str(exc),'error')
                self._td_monitor_motion(values)
            except Exception as exc:
                with self.lock:
                    self.td_state['error'] = str(exc)[:180]
                if self.td_motion.get('state') in ('moving','stopping'):
                    with self.td_motion_lock:
                        try:
                            td=self._td_driver()
                            with self.td_io_lock:
                                td.twoTD600_SetAxisStop(td.INNER_ROTATION_AXIS)
                                td.twoTD600_SetAxisStop(td.OUTER_ROTATION_AXIS)
                        except Exception as stop_error:
                            self.log('反馈失联后的软件停车也失败：'+str(stop_error),'error')
                        self.td_motion=dict(state='fault',axis=None,target=None,started=None,
                            message='实际运动中反馈失败，已请求双轴停车；需现场核实：'+str(exc)[:120])
                        self.log('运动中 DLL 反馈丢失，已请求停车；软件停车不能替代硬件急停','error')
            self.td_stop.wait(0.12 if ((self.ambient_capture is not None and self.ambient_capture.is_collecting()) or (self.ambient_auto is not None and self.ambient_auto.is_active())) else 0.5)

    def td_disconnect(self):
        if self.ambient_auto is not None and self.ambient_auto.is_active():
            raise RuntimeError('自动常温标定正在运行，请先请求停止并确认双轴静止')
        if self.ambient_capture is not None and self.ambient_capture.is_collecting():
            raise RuntimeError('常温工况正在采样，禁止改变电机/串口/CSV状态；先完成或取消采样')
        if not self.td_connection_lock.acquire(blocking=False):
            raise RuntimeError('2TD600 正在进行其他连接操作，请勿重复提交')
        try:
            return self._td_disconnect_inner()
        finally:
            self.td_connection_lock.release()

    def _td_disconnect_inner(self):
        # Set a guard while holding the motion lock, then release it before
        # joining the polling thread (which can itself need that lock).
        with self.td_motion_lock:
            if self.td_motion.get('state') in ('moving', 'stopping'):
                raise RuntimeError('有正在执行或尚未完成确认的转台动作；先软件停车并核实双轴静止，不能直接断开通讯')
            self.td_disconnecting = True
        try:
            self.td_stop.set()
            if self.td_thread and threading.current_thread() is not self.td_thread:
                self.td_thread.join(timeout=4.0)
                if self.td_thread.is_alive():
                    self.td_stop.clear()
                    raise RuntimeError('2TD600 DLL 状态读取未结束，拒绝强行关闭端口')
            with self.lock:
                if not self.td_connected:
                    return '2TD600 尚未连接'
            try:
                with self.td_io_lock:
                    state = self._td_read_axes()
                    # Fail closed if the vendor returns unknown/invalid motion mode.
                    for item in state.values():
                        if item['mode'] not in ('空闲', '静止', '停止') or abs(item['speed']) > 0.05 or not item['normal']:
                            raise RuntimeError('未确认双轴静止且正常，拒绝断开通讯；请使用现场控制器及硬件急停保护')
                    self._td_driver().twoTD600_closePort()
            except Exception:
                self.td_stop.clear()
                self.td_thread = threading.Thread(target=self._poll_td, daemon=True, name='2TD600-read-only')
                self.td_thread.start()
                raise
            with self.lock:
                self.td_connected = False
                self.td_motion = dict(state='idle',axis=None,target=None,started=None,message='')
                self.td_state = dict(inner=None, outer=None, last_monotonic=0., error='', identity_verified=False)
                self.log('2TD600 DLL 串口连接已关闭')
            return '2TD600 串口已关闭'
        finally:
            with self.td_motion_lock:
                self.td_disconnecting = False

    def status(self):
        with self.lock:
            imu = self._imu_snapshot()
            plc_fresh = (self.plc_connected and self.plc_state['pv'] is not None and
                         time.monotonic() - self.plc_state['last_pv_monotonic'] < 7.0)
            wk_fresh = (self.wk_ports_open and self.wk_state['inner'] is not None and
                        self.wk_state['outer'] is not None and
                        time.monotonic() - self.wk_state['last_monotonic'] < 4.0)
            td_fresh = (self.td_connected and self.td_state['inner'] is not None and
                        self.td_state['outer'] is not None and
                        time.monotonic() - self.td_state['last_monotonic'] < 4.0)
            return dict(server='真实硬件后端（无 PySide6）', simulation=False,
                        imu=imu,
                        plc=dict(connected=self.plc_connected, reading=plc_fresh,
                                 ip=self.settings['plc_ip'], pv=self.plc_state['pv'] if plc_fresh else None,
                                 sp=self.plc_state['sp'] if plc_fresh else None,
                                 alarm=self.plc_state['alarm'] if plc_fresh else None,
                                 fault=self.plc_state['fault'] if plc_fresh else None,
                                 running=self.plc_state['running'] if plc_fresh else None,
                                 error=self.plc_state['error']),
                        td=dict(connected=self.td_connected, reading=td_fresh,
                                feedback_age_ms=round((time.monotonic()-self.td_state['last_monotonic'])*1000) if td_fresh else None,
                                port=self.settings['td_port'], identity_verified=False,
                                motion=dict(self.td_motion),
                                inner=self.td_state['inner'] if td_fresh else None,
                                outer=self.td_state['outer'] if td_fresh else None,
                                error=self.td_state['error']),
                        wk=dict(connected=self.wk_ports_open, reading=wk_fresh,
                                inner=self.wk_state['inner'] if wk_fresh else None,
                                outer=self.wk_state['outer'] if wk_fresh else None,
                                error=self.wk_state['error']),
                        settings=dict(self.settings), events=list(reversed(self.events[-35:])),
                        capabilities=dict(imu_live=True, imu_csv=True, plc_read=True,
                                          wk_read=True, td_read_unverified=True, offline_reports=True,
                                          thermal_auto=False, plc_write=False,
                                          wk_motion=False, td_manual_jog=True, imu_calibration=False,
                                          ambient_auto_supervised=True))

    def records(self):
        files = []
        for p in RECORDS_DIR.iterdir():
            if p.is_file() and p.suffix.lower() == '.csv':
                s = p.stat()
                files.append(dict(name=p.name, bytes=s.st_size,
                                  updated=time.strftime('%Y-%m-%d %H:%M', time.localtime(s.st_mtime))))
        return sorted(files, key=lambda x: x['updated'], reverse=True)[:100]

    def record_file(self, name):
        # Whitelist by basename, extension, and resolved directory.
        if not isinstance(name, str) or not re.fullmatch(r'tilt_sensor_[0-9_]+\.csv', name):
            raise ValueError('文件名不合法')
        p = (RECORDS_DIR / name).resolve()
        if p.parent != RECORDS_DIR.resolve() or not p.is_file():
            raise FileNotFoundError('记录不存在')
        return p

    def shutdown(self):
        if self.ambient_auto is not None and self.ambient_auto.is_active():
            try:
                self.ambient_auto.request_abort()
                # Must not close the COM while the worker is still stopping.
                if self.ambient_auto.worker is not None:
                    self.ambient_auto.worker.join(timeout=15.0)
                if self.ambient_auto.is_active():
                    self.log('自动任务无法在退出期间确认停止；请立即使用硬件急停', 'error')
                    return
            except Exception as exc:self.log('自动标定退出停车失败：'+str(exc),'error')
        if self.ambient_auto is not None and self.ambient_auto.is_active():
            raise RuntimeError('自动常温标定正在运行，请先请求停止并确认双轴静止')
        if self.ambient_capture is not None and self.ambient_capture.is_collecting():
            try: self.ambient_capture.cancel()
            except Exception as exc: self.log('标定会话关闭警告：'+str(exc),'error')
        if self.td_connected and self.td_motion.get('state') in ('moving','stopping'):
            try: self.td_stop_all()
            except Exception as exc: self.log('进程关闭时 2TD600 软件停车失败，必须使用硬件急停：'+str(exc),'error')
        self.td_auto_stop.set()
        if self.td_auto_thread and self.td_auto_thread.is_alive():
            self.td_auto_thread.join(timeout=3.0)
        try: self.imu_disconnect()
        except Exception as exc: self.log('PCB 关闭警告：' + str(exc), 'warning')
        # Do not silently disconnect the 2TD600 while physical motion might be active.
        try: self.plc_disconnect()
        except Exception as exc: self.log('PLC 关闭警告：' + str(exc), 'warning')
        # Deliberately do not send untested actuator commands on server exit.
        # WK may be moving; safety is always under the physical controller/E-STOP.
