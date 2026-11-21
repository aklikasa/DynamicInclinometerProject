"""2FDT600WK RS-422 passive-only axis discovery.

The manufacturer DLL expects $1 frames for axis 0 and $2 frames for axis 2.
This module NEVER writes any bytes to a serial port.
"""
import re
import time

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    serial = None
    list_ports = None

# One frame: '$1' / '$2' + alarm + state + 2-digit sequence + 8-character angle + CRLF
FRAME = re.compile(rb'\$([12])([0-9])([0-9])([0-9]{2})([0-9]{3}\.[0-9]{4})\r\n')


def parse_frames(buffer):
    """Return (axis_id, alarm, mode, angle) for plausible complete frames."""
    frames = []
    for match in FRAME.finditer(buffer):
        axis = int(match.group(1))
        alarm = int(match.group(2))
        state = int(match.group(3))
        angle = float(match.group(5))
        if state <= 9 and angle <= 360.0:
            frames.append((axis, alarm, state, angle))
    return frames


def probe_port(port, duration=0.8):
    """Open temporarily, passively read, close. Never send commands."""
    if serial is None:
        return {}, 'pyserial 未安装'
    raw = bytearray()
    try:
        with serial.Serial(port=port, baudrate=115200, bytesize=8,
                           parity='N', stopbits=1, timeout=0.12,
                           write_timeout=0.2) as ser:
            end = time.monotonic() + duration
            while time.monotonic() < end:
                piece = ser.read(min(512, max(1, ser.in_waiting)))
                if piece:
                    raw.extend(piece)
                    if len(raw) > 4096:
                        del raw[:-2048]
    except Exception as exc:
        return {}, str(exc)
    found = {}
    for axis, alarm, mode, angle in parse_frames(bytes(raw)):
        entry = found.setdefault(axis, {'count': 0, 'alarm': alarm,
                                        'state': mode, 'angle': angle})
        entry['count'] += 1
        entry.update(alarm=alarm, state=mode, angle=angle)
    return found, f'接收 {len(raw)} 字节'


def scan_axes(preferred=(), progress=None, duration=0.8):
    """Read all available serial ports safely. Require >=2 valid frames per axis.

    Returns mapping {1: 'COMn', 2: 'COMm'} only when unambiguous, and a log.
    If a live port reports both axes or >1 port has one axis, no automatic choice.
    """
    if list_ports is None:
        return {}, ['pyserial 未安装，无法执行串口检测']
    ports = [info.device for info in list_ports.comports()]
    priorities = {str(p).upper(): i for i, p in enumerate(preferred)}
    ports.sort(key=lambda name: (priorities.get(name.upper(), 999),
                                 int(re.search(r'(\d+)$', name).group(1)) if re.search(r'(\d+)$',name) else 999))
    detected = {1: [], 2: []}
    log = []
    if not ports:
        return {}, ['Windows 未检测到任何串口']
    for port in ports:
        if progress:
            progress(f'正在只读检测 {port} ...')
        result, detail = probe_port(port, duration=duration)
        good = {axis: d for axis,d in result.items() if d['count'] >= 2}
        if good:
            descriptors = ', '.join(f'${axis}: {d["count"]} 帧, 状态 {d["state"]}, 报警 {d["alarm"]}'
                                    for axis,d in sorted(good.items()))
            log.append(f'{port}: {descriptors}; {detail}')
            for axis in good:
                detected[axis].append(port)
        else:
            log.append(f'{port}: 未验证到有效转台帧 ({detail})')
    mapping = {}
    if len(detected[1]) == 1 and len(detected[2]) == 1 and detected[1][0] != detected[2][0]:
        mapping = {1: detected[1][0], 2: detected[2][0]}
        log.append(f'识别成功：内轴 $1={mapping[1]}，外轴 $2={mapping[2]}')
    else:
        log.append('未识别到唯一的内、外轴端口；不执行任何使能或运动指令。')
        log.append(f'内轴 $1 候选: {detected[1] or "无"}，外轴 $2 候选: {detected[2] or "无"}')
    return mapping, log
