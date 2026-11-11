"""Hardware-free regression tests for COM diagnostics; no pyserial required on test host."""
import sys
import types
import unittest
from unittest.mock import patch
from native_web import device_service

class SerialDiagnosticsTest(unittest.TestCase):
    def test_open_error_is_preserved(self):
        d = str(device_service.ROOT / 'tilt_sensor')
        if d not in sys.path: sys.path.insert(0, d)
        fake_serial = types.ModuleType('serial')
        fake_tools = types.ModuleType('serial.tools')
        fake_list_ports = types.ModuleType('serial.tools.list_ports')
        fake_tools.list_ports = fake_list_ports
        fake_serial.tools = fake_tools
        fake_serial.Serial = lambda **kwargs: (_ for _ in ()).throw(PermissionError(13, 'Access is denied'))
        with patch.dict(sys.modules, {'serial':fake_serial, 'serial.tools':fake_tools,
                                      'serial.tools.list_ports':fake_list_ports}):
            import tilt_sensor_asm330_comm as comm
            with patch.object(comm, 'OFFLINE_DEBUG', False):
                self.assertFalse(comm.mb_serial_open('COM5', 1500000))
                self.assertIn('PermissionError', comm.mb_last_serial_error)
                self.assertIn('Access is denied', comm.mb_last_serial_error)
                with patch.object(fake_serial, 'Serial', side_effect=FileNotFoundError(2, 'Port not found')):
                    self.assertFalse(comm.mb_serial_open('COM5', 1500000))
                    self.assertIn('FileNotFoundError', comm.mb_last_serial_error)

if __name__ == '__main__': unittest.main()
