# -*- coding: utf-8 -*-
"""Read-only Windows serial enumeration; never opens or changes a COM port."""
import sys

def main():
    print('='*60)
    print('WK IMU R7 - Windows COM port discovery (read-only)')
    print('Python:', sys.executable)
    try:
        from serial.tools import list_ports
        ports = sorted(list_ports.comports(), key=lambda p: str(p.device))
    except Exception as exc:
        print('SCAN ERROR:', type(exc).__name__, str(exc))
        return 1
    print('Found:', len(ports))
    if not ports:
        print('No serial ports detected. Check Windows Device Manager > Ports (COM & LPT).')
    for p in ports:
        print(f'  {p.device} | {p.description} | {p.hwid}')
    print('No COM port was opened. If COM5 is not listed, the saved config is stale.')
    print('='*60)
    return 0

if __name__=='__main__':
    raise SystemExit(main())
