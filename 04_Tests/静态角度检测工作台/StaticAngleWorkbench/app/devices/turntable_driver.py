"""2TD600 厂商 DLL ctypes 适配层，独立加载，原项目调用约定 CDLL。
轴号与旧工程一致：内轴 0；外轴 2。Windows + 64位 Python。
"""
from __future__ import annotations
import ctypes
import os
import re
from pathlib import Path

INNER = 0
OUTER = 2
AXES = (INNER, OUTER)


class TurntableDriver:
    def __init__(self, dll_path: Path | None = None):
        if os.name != 'nt':
            raise OSError('2TD600.dll 仅支持 Windows 64 位运行')
        dll_path = dll_path or Path(__file__).resolve().parents[2] / 'vendor' / '2TD600.dll'
        if not dll_path.is_file():
            raise FileNotFoundError(f'找不到转台 DLL: {dll_path}')
        self._dll_folder = os.add_dll_directory(str(dll_path.parent)) if hasattr(os, 'add_dll_directory') else None
        self.lib = ctypes.CDLL(str(dll_path))
        self._bind('OpenPort', [ctypes.c_int, ctypes.c_int], ctypes.c_int)
        self._bind('ClosePort', [], None)
        for name in ('GetAxisEnable','GetAxisNormal','GetAxisMoveInPlace','GetAxisDriverFault',
                     'GetAxisUpLimit','GetAxisDownLimit','GetAxisOverSpeed','GetAxisOverDiff'):
            self._bind(name, [ctypes.c_int], ctypes.c_int)
        for name in ('GetPosition', 'GetSpeed'):
            self._bind(name, [ctypes.c_int], ctypes.c_double)
        for name in ('SetAxisEnable','SetAxisDisable','SetAxisStop'):
            self._bind(name, [ctypes.c_int], ctypes.c_int)
        self._bind('SetAxisPosition', [ctypes.c_int, ctypes.c_double, ctypes.c_double], ctypes.c_int)
        self.is_open = False

    def _bind(self, name, args, result):
        fn = getattr(self.lib, name)
        fn.argtypes = args
        fn.restype = result

    def open(self, com: str, baud: int = 115200):
        m = re.fullmatch(r'COM(\d+)', com.upper().strip())
        if not m:
            raise ValueError('转台串口格式必须为 COMn')
        if self.lib.OpenPort(int(m.group(1)), int(baud)) != 1:
            raise IOError(f'2TD600 OpenPort 失败：{com}/{baud}')
        self.is_open = True

    def close(self):
        if self.is_open:
            self.lib.ClosePort()
            self.is_open = False

    def _binary_feedback(self, name: str, axis: int) -> bool:
        code = int(getattr(self.lib, name)(axis))
        if code not in (0, 1):
            raise IOError(f'{name}(轴{axis}) 返回 {code}，不是有效的 0/1 状态；禁止运动')
        return code == 1

    def info(self):
        result = {}
        for axis, title in ((INNER, 'inner'), (OUTER, 'outer')):
            result[title] = {
                'position': float(self.lib.GetPosition(axis)),
                'speed': float(self.lib.GetSpeed(axis)),
                'enabled': self._binary_feedback('GetAxisEnable', axis),
                'normal': self._binary_feedback('GetAxisNormal', axis),
                'in_place': self._binary_feedback('GetAxisMoveInPlace', axis),
                'driver_fault': self._binary_feedback('GetAxisDriverFault', axis),
                'up_limit': self._binary_feedback('GetAxisUpLimit', axis),
                'down_limit': self._binary_feedback('GetAxisDownLimit', axis),
                'over_speed': self._binary_feedback('GetAxisOverSpeed', axis),
                'over_diff': self._binary_feedback('GetAxisOverDiff', axis),
            }
        return result

    def enable(self, axis: int, value: bool):
        fn = self.lib.SetAxisEnable if value else self.lib.SetAxisDisable
        if fn(axis) != 1:
            raise IOError(f'{"使能" if value else "解除使能"}命令失败：轴{axis}')

    def move(self, axis: int, angle: float, speed: float):
        if self.lib.SetAxisPosition(axis, float(angle), float(speed)) != 1:
            raise IOError(f'绝对位置命令失败：轴{axis}')

    def stop(self, axis: int):
        if self.lib.SetAxisStop(axis) != 1:
            raise IOError(f'停车命令失败：轴{axis}')
