"""Offline tests; do not attempt to touch a physical COM/PLC/WK device."""
import threading
from pathlib import Path
import tempfile
import time
import types
import unittest
from unittest.mock import patch
from native_web import device_service as dev

class NativeWebTest(unittest.TestCase):
    def new_service(self):
        with patch.object(dev, 'SETTINGS_FILE', Path(tempfile.gettempdir()) / '__WK_web_test_no_existing_file_3272399.json'):
            return dev.DeviceService()

    def test_qt_independent_import(self):
        import sys
        self.assertNotIn('PySide6.QtCore', sys.modules)
        self.assertNotIn('PySide6.QtWidgets', sys.modules)

    def test_offline_is_not_made_up(self):
        obj = self.new_service().status()
        self.assertFalse(obj['simulation'])
        self.assertFalse(obj['imu']['reading'])
        self.assertIsNone(obj['imu']['values'])
        self.assertIsNone(obj['plc']['pv'])
        self.assertIsNone(obj['wk']['inner'])
        self.assertFalse(obj['capabilities']['thermal_auto'])

    def test_serial_scan_returns_actual_ports_not_saved_default(self):
        s=self.new_service()
        import sys
        fake_serial=types.ModuleType('serial')
        fake_tools=types.ModuleType('serial.tools')
        fake_list_ports=types.ModuleType('serial.tools.list_ports')
        fake_tools.list_ports=fake_list_ports
        fake_serial.tools=fake_tools
        fake=[types.SimpleNamespace(device='COM3', description='USB Serial Device'),
              types.SimpleNamespace(device='COM8', description='FTDI USB UART')]
        fake_list_ports.comports=lambda:fake
        with patch.dict(sys.modules, {'serial':fake_serial, 'serial.tools':fake_tools,
                                      'serial.tools.list_ports':fake_list_ports}):
            result=s.serial_ports()
            self.assertEqual([p['device'] for p in result], ['COM3','COM8'])
            self.assertNotIn('COM5', [p['device'] for p in result])
            fake_list_ports.comports=lambda:[]
            self.assertEqual(s.serial_ports(), [])

    def test_invalid_serial_port_rejected(self):
        s = self.new_service()
        for bad in ('/dev/ttyUSB0','COM0','COM1 && rm','COM9999'):
            with self.assertRaises(ValueError):s.update_settings({'port':bad})

    def test_invalid_plc_ip_rejected(self):
        s = self.new_service()
        for bad in ('http://192.168.1.1','255.1.1.900','not-an-ip'):
            with self.assertRaises(ValueError):s.update_settings({'plc_ip':bad})

    def test_wk_axis_port_collision_rejected(self):
        s=self.new_service()
        with self.assertRaises(ValueError):s.update_settings({'wk_inner':'COM8','wk_outer':'COM8'})

    def test_imu_reading_requires_recent_valid_frame(self):
        s=self.new_service()
        c=types.SimpleNamespace(is_serial_opened=True,is_data_available=True,
                                last_success_time_sec=time.time(),comm_port='COM5',baudrate=1500000,
                                device_sn='DTS123456',comm_rate=34.5,comm_success_count=100,
                                comm_total_count=101,last_success_time_text='2026-11-10 10:00:00',
                                frame_interval_ms=30.0)
        r=types.SimpleNamespace(data_lock=threading.Lock(),is_data_valid=True,
                                acc_g_arr=[(0.1,0.2,0.97)]*16,
                                gyr_dps_arr=[(1.2,0.1,-.5)]*16,
                                temp_c=28.4,tick_ms=12000,acc_fs=2,gyro_fs=250,
                                data_odr=833,fifo_state=0,data_update_count=100)
        s.imu_mod=types.SimpleNamespace(tiltSensorComm=c,tiltSensorRawData=r)
        s.csv_mod=types.SimpleNamespace(csv_is_enabled=lambda:False,csv_row_count=0,
                                        csv_drop_count=0,csv_file_path='',csv_write_error='')
        snap=s.status()['imu']
        self.assertTrue(snap['reading'])
        self.assertAlmostEqual(snap['values']['temperature'],28.4)
        self.assertEqual(snap['values']['acc'],[0.1,0.2,0.97])
        c.last_success_time_sec=time.time()-30
        self.assertIsNone(s.status()['imu']['values'])
        self.assertFalse(s.status()['imu']['reading'])
        c.last_success_time_sec=time.time()
        r.is_data_valid=False
        self.assertIsNone(s.status()['imu']['values'])

    def test_record_filename_whitelist(self):
        s=self.new_service()
        for bad in ('../config.xml','..\\config.xml','abc.csv','tilt_sensor_a.csv'):
            with self.assertRaises(ValueError):s.record_file(bad)
        with self.assertRaises(FileNotFoundError):s.record_file('tilt_sensor_20990101_101010_123456.csv')

    def test_plc_stale_reading_hidden(self):
        s=self.new_service()
        s.plc_connected=True
        s.plc_state.update(pv=24.3,sp=35,alarm=0,last_pv_monotonic=time.monotonic()-100)
        result=s.status()['plc']
        self.assertFalse(result['reading'])
        self.assertIsNone(result['pv'])
        self.assertIsNone(result['sp'])

    def test_wk_stale_reading_hidden(self):
        s=self.new_service()
        s.wk_ports_open=True
        s.wk_state.update(inner={'angle':12},outer={'angle':15},last_monotonic=time.monotonic()-90)
        result=s.status()['wk']
        self.assertFalse(result['reading'])
        self.assertIsNone(result['inner'])

if __name__=='__main__':unittest.main()
