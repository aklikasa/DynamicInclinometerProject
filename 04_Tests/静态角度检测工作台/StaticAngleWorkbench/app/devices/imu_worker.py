"""IMU 后台读取线程，不在GUI线程上阻塞串口。"""
from __future__ import annotations
import time
import threading
from PySide6.QtCore import QThread, Signal
from .imu_protocol import decode, read_registers


class IMUWorker(QThread):
    sample = Signal(object)
    state = Signal(bool, str)
    notice = Signal(str)

    def __init__(self, port: str, baud: int = 1500000, addr: int = 1, parent=None):
        super().__init__(parent)
        self.port, self.baud, self.addr = port, baud, addr
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        device = None
        try:
            import serial
            device = serial.Serial(self.port, baudrate=self.baud, bytesize=8,
                                   parity='N', stopbits=1, timeout=0.65, write_timeout=0.65)
            self.state.emit(True, f'IMU 已打开 {self.port} · {self.baud}')
            last_acc, last_gyro = 2, 2000
            error_streak = 0
            last_tick = None
            warned_missing_range = False
            notified_recovered_range = False  # 每次连接最多记录一次缺失和一次恢复
            while not self._stop.is_set():
                start = time.monotonic()
                try:
                    data = decode(read_registers(device, self.addr), last_acc, last_gyro)
                    last_acc, last_gyro = data.acc_fs, data.gyro_fs
                    # 无新的数据或者设备时间戳未变化：不要画成有效新帧
                    data.valid = bool(data.valid and data.tick_ms != last_tick)
                    last_tick = data.tick_ms
                    self.sample.emit(data)
                    missing = (not data.acc_fs_reported, not data.gyro_fs_reported)
                    if any(missing) and not warned_missing_range:
                        names = '/'.join(name for name, absent in zip(('ACC', 'GYRO'), missing) if absent)
                        self.notice.emit(f'{names} 量程字段缺失：当前按旧工程回退比例换算，必须核对固件实际量程；本次连接只提示一次')
                        warned_missing_range = True
                    elif not any(missing) and warned_missing_range and not notified_recovered_range:
                        self.notice.emit('IMU 量程字段已恢复有效上报；本次连接后续不再重复提示')
                        notified_recovered_range = True
                    error_streak = 0
                except Exception as exc:
                    error_streak += 1
                    if error_streak in (1, 5) or error_streak % 50 == 0:
                        self.notice.emit(f'IMU 读取失败({error_streak})：{exc}')
                self._stop.wait(max(0.0, 0.020 - (time.monotonic() - start)))
        except Exception as exc:
            self.notice.emit(f'IMU 串口打开失败：{exc}')
        finally:
            if device is not None:
                try: device.close()
                except Exception: pass
            self.state.emit(False, f'IMU 已断开 {self.port}')
