# -*- coding: utf-8 -*-
"""Read-only diagnostics: never contacts a physical device."""
from pathlib import Path
import importlib.util
import platform
import struct
import sys
from native_web.device_service import ROOT, _default_settings

def main():
    print('='*62)
    print('WK IMU R7 — 原生网页环境检查 (No Qt / No hardware I/O)')
    print('Python:',sys.version.split()[0], sys.executable)
    print('Platform:',platform.platform())
    print('Python bits:',struct.calcsize('P')*8)
    print('Base folder:',ROOT)
    for module in ('serial','snap7','numpy'):
        found=importlib.util.find_spec(module)
        print(module+':', '可找到' if found else '未安装', '(此项不等于通信已验证)')
    print('Qt/PySide6:', '原生网页启动完全不需要')
    print('2TD600 DLL:', '存在' if (ROOT/'2TD600.dll').exists() else '缺失')
    print('2TD600 config:',_default_settings()['td_port'])
    print('WK DLL:', '存在' if (ROOT/'2FDT600WK.dll').exists() else '缺失')
    settings=_default_settings()
    print('IMU config:',settings['port'], settings['baud'])
    print('WK config:',settings['wk_inner'],settings['wk_outer'])
    if importlib.util.find_spec('serial'):
        try:
            from serial.tools import list_ports
            print('COM ports:', ', '.join(str(p.device) for p in list_ports.comports()) or '(没有检测到)')
        except Exception as exc:
            print('COM port detection error:',exc)
    print('说明: 本测试不打开 COM、不连接 PLC、不调用 WK DLL。')
    print('='*62)

if __name__=='__main__':main()
