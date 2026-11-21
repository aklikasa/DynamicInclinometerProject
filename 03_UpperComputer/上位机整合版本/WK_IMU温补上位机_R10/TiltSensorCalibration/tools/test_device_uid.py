"""离线 UID 协议/哈希回归测试；不连接真实硬件，默认不使用 PySide6。"""
from pathlib import Path
import sys
import types
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
for name in ('tilt_sensor', 'debug'):
    sys.path.insert(0, str(ROOT / name))

# 测试环境无 pyserial 时注入最小 stub；用户电脑安装 pyserial 后仍使用正式模块。
try:
    import serial
except ImportError:
    serial = types.ModuleType('serial')
    tools = types.ModuleType('serial.tools')
    list_ports = types.ModuleType('serial.tools.list_ports')
    tools.list_ports = list_ports
    serial.tools = tools
    sys.modules.update({'serial': serial, 'serial.tools': tools, 'serial.tools.list_ports': list_ports})

import tilt_sensor_asm330_comm as comm


class FakeSerial:
    def __init__(self, response):
        self.is_open = True
        self.timeout = 1.0
        self.buffer = bytes(response)
        self.request = b''

    def reset_input_buffer(self):
        pass

    def write(self, data):
        self.request = data

    def read(self, size):
        result, self.buffer = self.buffer[:size], self.buffer[size:]
        return result


def crc_append(payload):
    crc = comm._mb_crc16(payload)
    return bytes(payload) + bytes([crc & 0xff, (crc >> 8) & 0xff])


def check(response, expected):
    fake = FakeSerial(response)
    comm.serial_instance = fake
    comm.mb_last_tx_hex = 'UNCHANGED'
    comm.mb_last_rx_hex = 'UNCHANGED'
    result = comm.mb_device_uid_read(1)
    assert result == expected, (result, expected)
    assert fake.request.hex().upper() == '01030BB8000647C9', fake.request.hex()
    assert fake.timeout == 1.0
    assert comm.mb_last_tx_hex == 'UNCHANGED'
    assert comm.mb_last_rx_hex == 'UNCHANGED'


uid = bytes.fromhex('002900593252501720323350')
assert comm.device_uid_to_sn(uid) == 'DTS672516'
assert comm.device_uid_to_sn(uid) == comm.device_uid_to_sn(uid)
assert comm.device_uid_to_sn(b'\x00' * 12) == ''
assert comm.device_uid_to_sn(b'\xff' * 12) == ''
assert comm.device_uid_to_sn(b'\x01') == ''
assert comm.device_uid_to_sn(None) == ''
check(crc_append(b'\x01\x03\x0C' + uid), uid)
check(crc_append(b'\x01\x83\x02'), None)  # 不支持寄存器的旧固件
check(b'', None)
check(b'\x01\x03\x0C\x00', None)
check(crc_append(b'\x02\x03\x0C' + uid), None)
check(crc_append(b'\x01\x03\x0C' + b'\x00' * 12), None)
bad_crc = bytearray(crc_append(b'\x01\x03\x0C' + uid))
bad_crc[-1] ^= 0xFF
check(bytes(bad_crc), None)

ui_root = ET.parse(ROOT / 'ui/mainWindow.ui').getroot()
assert ui_root.find(".//widget[@name='tabWidget_AccDataManual']") is not None
form = (ROOT / 'form/form_tilt_sensor_cal.py').read_text(encoding='utf-8')
assert 'ui.tabWidget_AccDataManual.addTab(self._device_uid_tab, "设备 UID")' in form
assert 'device_sn = tiltSensorComm.device_sn if tiltSensorComm.is_serial_opened else ""' in form
worker = (ROOT / 'tilt_sensor/tilt_sensor_asm330_data_get.py').read_text(encoding='utf-8')
assert 'if not tiltSensorComm.device_uid_checked:' in worker
assert 'with tiltSensorComm.thread_lock:' in worker
print('[PASS] Modbus UID 正常返回、异常、超时、CRC、DTS哈希、UI接线均通过')
