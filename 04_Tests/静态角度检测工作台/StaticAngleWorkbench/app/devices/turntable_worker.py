"""2TD600 单线程命令调度与受控停车。

安全边界：厂商DLL可能阻塞/底层故障；软件不能替代硬件急停或独立安全回路。
断开只有在两轴新鲜静止反馈、解除使能反馈均确认后才执行 ClosePort。
"""
from __future__ import annotations

import collections
import math
import threading
import time
from PySide6.QtCore import QThread, Signal
from .turntable_driver import TurntableDriver, INNER, OUTER

AXIS_MAP = ((INNER, 'inner', '内轴0'), (OUTER, 'outer', '外轴2'))
SPEED_LIMIT = 0.05


class TurntableWorker(QThread):
    state = Signal(bool, str)
    feedback = Signal(object)
    result = Signal(str, bool, str)
    notice = Signal(str)
    safety_alarm = Signal(str)

    def __init__(self, port, parent=None, driver_factory=TurntableDriver):
        super().__init__(parent)
        self.port, self.driver_factory = port, driver_factory
        self._queue = collections.deque()
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._ending = False
        self._disconnect_requested = False
        self.connected = False
        self.last_feedback = None

    def submit(self, cmd, *args):
        """停车和断开优先于队列中的任何尚未发送的运动/使能命令。"""
        with self._lock:
            if cmd == 'disconnect':
                self._disconnect_requested = True
                self._queue.clear()
                self._queue.appendleft((cmd, args))
            elif cmd == 'stop_all':
                if not self._disconnect_requested:
                    self._queue.clear()
                    self._queue.appendleft((cmd, args))
            elif not self._disconnect_requested:
                self._queue.append((cmd, args))
            else:
                return False
        self._wake.set()
        return True

    def _next(self):
        with self._lock:
            return self._queue.popleft() if self._queue else None

    @staticmethod
    def _axis_reason(info):
        flags = ('enabled', 'normal', 'driver_fault', 'up_limit', 'down_limit', 'over_speed', 'over_diff')
        return ', '.join(f'{key}={int(bool(info.get(key)))}' for key in flags)

    def _read(self, driver):
        data = driver.info()  # 每次从 DLL 读取，禁止用UI缓存做静止确认
        for _, key, name in AXIS_MAP:
            if key not in data:
                raise RuntimeError(f'{name}状态缺失；无法确认安全')
            for field in ('speed', 'position'):
                value = float(data[key][field])
                if not math.isfinite(value):
                    raise RuntimeError(f'{name}反馈{field}无效：{value}；无法确认安全')
        self.last_feedback = data
        self.feedback.emit(data)
        return data

    def _wait_for_still(self, driver, timeout=6.0, consecutive=3):
        deadline = time.monotonic() + timeout
        good = 0
        previous = None
        while time.monotonic() < deadline:
            data = self._read(driver)
            stopped = all(abs(data[key]['speed']) <= SPEED_LIMIT for _, key, _ in AXIS_MAP)
            # 即便设备报告零速，也使用连续新反馈确认；编码器静止性额外校验。
            if previous is not None:
                for _, key, _ in AXIS_MAP:
                    diff = (data[key]['position'] - previous[key]['position'] + 180.0) % 360.0 - 180.0
                    if abs(diff) > 0.08:
                        stopped = False
            good = (good + 1) if stopped else 0
            if good >= consecutive:
                return data
            previous = data
            time.sleep(.18)
        raise RuntimeError('停车超时：未获得连续3次双轴零速且编码器稳定的反馈；保持端口打开。请确认机械状态，必要时使用实体急停')

    def _stop_verified(self, driver):
        initial = self._read(driver)
        errors, warnings = [], []
        # 某轴未使能且静止时不向其发送可能返回0的停车指令；该轴仍需通过零速反馈。
        # 两轴分别尝试，不允许轴0命令失败时跳过轴2的停车。
        for axis, key, title in AXIS_MAP:
            fb = initial[key]
            if not fb['enabled'] and abs(fb['speed']) <= SPEED_LIMIT:
                self.notice.emit(f'{title}未使能且反馈零速，跳过无意义的停车命令（仍将核实新反馈）')
                continue
            try:
                driver.stop(axis)
                self.notice.emit(f'{title}停车指令已被DLL接受，等待实际反馈')
            except Exception as exc:
                reason = f'{title}停车指令返回失败：{exc}'
                if abs(fb['speed']) > SPEED_LIMIT:
                    errors.append(reason)
                else:
                    warnings.append(reason + '；该轴先前已经零速，仍将核对反馈')
        # 即使命令返回0仍要读取真实速度；不能把返回0解释为已停车。
        final = self._wait_for_still(driver)
        if errors:
            raise RuntimeError('；'.join(errors) + '；虽检测到当前零速，但无法确认运动中的停车命令有效，拒绝自动解除使能/断开')
        if warnings:
            self.notice.emit('停车告警：' + '；'.join(warnings))
        return final

    def _disable_confirmed(self, driver, axis, key, name):
        current = self._read(driver)[key]
        if not current['enabled']:
            self.notice.emit(f'{name}本来已解除使能，跳过解除指令')
            return
        if abs(current['speed']) > SPEED_LIMIT:
            raise RuntimeError(f'{name}仍有速度，拒绝解除使能')
        driver.enable(axis, False)
        deadline = time.monotonic() + 3.5
        good = 0
        while time.monotonic() < deadline:
            fb = self._read(driver)[key]
            if abs(fb['speed']) > SPEED_LIMIT:
                raise RuntimeError(f'{name}解除使能过程中出现运动反馈，拒绝继续断开')
            good = good + 1 if not fb['enabled'] else 0
            if good >= 2:
                self.notice.emit(f'{name}解除使能已核实：enabled=0')
                return
            time.sleep(.2)
        raise RuntimeError(f'{name}已发送解除使能，但未收到连续2次 enabled=0 的确认；保持端口打开')

    def _safe_disconnect(self, driver):
        self.notice.emit('安全断开步骤1/3：取消尚未执行的运动指令，分别停车并验证双轴静止')
        self._stop_verified(driver)
        self.notice.emit('安全断开步骤2/3：分别解除使能，回读驱动状态')
        failures = []
        for axis, key, name in AXIS_MAP:
            try:
                self._disable_confirmed(driver, axis, key, name)
            except Exception as exc:
                failures.append(str(exc))
        if failures:
            raise RuntimeError('；'.join(failures) + '；为避免不确定状态，不关闭转台串口')
        final = self._wait_for_still(driver, timeout=3.0)
        if any(final[key]['enabled'] for _, key, _ in AXIS_MAP):
            raise RuntimeError('有轴仍处于使能状态，不关闭通讯')
        self.notice.emit('安全断开步骤3/3：双轴已反馈静止且解除使能，关闭DLL通信端口')
        driver.close()
        self.connected = False
        self._ending = True
        self.state.emit(False, '已核对双轴静止及解除使能；转台端口已关闭')
        return '双轴静止已确认，enabled均为0，已关闭转台通信端口'

    def _enable_one(self, driver, axis):
        axis_name = '内轴' if axis == INNER else '外轴'
        key = 'inner' if axis == INNER else 'outer'
        before = self._read(driver)[key]
        self.notice.emit(f'{axis_name}使能前状态：{self._axis_reason(before)}')
        alarms = ('driver_fault', 'up_limit', 'down_limit', 'over_speed', 'over_diff')
        bad = [k for k in alarms if before.get(k)]
        if bad:
            raise RuntimeError(f'{axis_name}存在故障/限位信号 {bad}，拒绝使能；{self._axis_reason(before)}')
        if not before['enabled']:
            self.notice.emit(f'正在调用 2TD600.dll SetAxisEnable({axis})：{axis_name}（不发送运动指令）')
            driver.enable(axis, True)
            self.notice.emit(f'SetAxisEnable({axis}) 返回 1，继续核对实际反馈')
        time.sleep(.55)
        feedback = None
        for _ in range(12):
            feedback = self._read(driver)[key]
            detected = [k for k in alarms if feedback.get(k)]
            if detected:
                raise RuntimeError(f'{axis_name}使能后出现告警 {detected}，禁止运动')
            if feedback['enabled'] and feedback['normal']:
                break
            time.sleep(.25)
        if not feedback['enabled']:
            raise RuntimeError(f'{axis_name}(轴{axis}) 已调用 SetAxisEnable，但 GetAxisEnable仍为0。'
                               f'normal={int(feedback["normal"])} 不代表使能。反馈：{self._axis_reason(feedback)}')
        if not feedback['normal']:
            raise RuntimeError(f'{axis_name}(轴{axis}) enabled=1但normal=0，驱动未就绪')
        return f'{axis_name}(轴{axis})使能成功：enabled=1 normal=1'

    def _do(self, driver, cmd, args):
        if cmd == 'stop_all':
            self._stop_verified(driver)
            return '停车已确认：两轴速度连续3次≤0.05°/s且编码器反馈稳定（软件停车，不替代实体急停）'
        if cmd == 'disconnect':
            return self._safe_disconnect(driver)
        if cmd in ('refresh', 'diagnose'):
            data = self._read(driver)
            if cmd == 'diagnose':
                hint = '；提示：外轴2 normal=1但enabled=0，尚未使能' if not data['outer']['enabled'] and data['outer']['normal'] else ''
                return f'转台诊断：内轴[{self._axis_reason(data["inner"])}]；外轴[{self._axis_reason(data["outer"])}]' + hint
            return '状态已刷新'
        if cmd == 'enable_both':
            first = self._enable_one(driver, INNER)
            try:
                second = self._enable_one(driver, OUTER)
            except Exception as exc:
                raise RuntimeError(f'{exc}；注意内轴可能仍处于使能状态') from exc
            return first + '；' + second
        if not args or args[0] not in (INNER, OUTER):
            raise ValueError('轴号无效')
        axis = args[0]
        key = 'inner' if axis == INNER else 'outer'
        v = self._read(driver)[key]
        if cmd == 'enable':
            return self._enable_one(driver, axis)
        if cmd == 'disable':
            self._wait_for_still(driver, timeout=2.0)
            self._disable_confirmed(driver, axis, key, '内轴0' if axis == INNER else '外轴2')
            return f'{key}解除使能反馈已确认'
        if cmd == 'move':
            _, angle, speed = args
            if not (0 <= angle <= 360 and 0 < speed <= 5):
                raise ValueError('位置需在0–360°，速度需在(0,5]°/s')
            if not v['enabled'] or not v['normal'] or any(v[k] for k in ('driver_fault','over_speed','over_diff','up_limit','down_limit')):
                raise RuntimeError('未使能、故障或限位状态，不允许运动')
            driver.move(axis, angle, speed)
            return f'{"内轴" if axis == INNER else "外轴"}绝对位置命令：{angle:.3f}° / {speed:.2f}°/s'
        raise ValueError(f'未知指令 {cmd}')

    def run(self):
        driver = None
        abnormal = False
        try:
            driver = self.driver_factory()
            driver.open(self.port, 115200)
            self.connected = True
            self.state.emit(True, f'2TD600 转台已打开 {self.port} / 115200')
            first = self._read(driver)
            self.notice.emit('转台初始反馈：内轴[' + self._axis_reason(first['inner']) +
                             ']；外轴[' + self._axis_reason(first['outer']) + ']')
            next_poll = time.monotonic() + .35
            while not self._ending:
                job = self._next()
                if job is not None:
                    name, args = job
                    try:
                        message = self._do(driver, name, args)
                        self.result.emit(name, True, message)
                    except Exception as exc:
                        if name == 'disconnect':
                            with self._lock: self._disconnect_requested = False
                        self.result.emit(name, False, str(exc))
                        if name in ('disconnect', 'stop_all'):
                            self.safety_alarm.emit(f'{name}未能确认安全：{exc}。请现场查看状态，必要时使用实体急停。')
                    next_poll = time.monotonic() + .35
                    continue
                if time.monotonic() >= next_poll:
                    try:
                        self._read(driver)
                    except Exception as exc:
                        self.notice.emit(f'转台状态查询异常：{exc}')
                    next_poll = time.monotonic() + .4
                self._wake.wait(.05)
                self._wake.clear()
        except Exception as exc:
            abnormal = True
            self.notice.emit(f'转台通信线程异常：{exc}')
        finally:
            if self.connected or (driver is not None and getattr(driver, 'is_open', False)):
                # 禁止在无法证实停车/解除使能的情况下，自动关闭端口并假装安全。
                self.safety_alarm.emit('转台控制线程意外退出或端口状态不明，无法确认机械停止。请立即现场核实，必要时实体急停。')
            if abnormal and driver is not None and not getattr(driver, 'is_open', False):
                self.notice.emit('转台端口未成功打开；未执行任何运动')
            self.connected = False
            self.state.emit(False, '转台控制线程已退出' if not self._ending else '转台控制线程正常退出')
