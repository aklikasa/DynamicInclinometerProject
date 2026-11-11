"""Hardware-free tests for R7 UID retry and six-axis live traces."""
import threading
import time
import types
import unittest
from unittest.mock import patch
from pathlib import Path
from native_web import device_service as dev


class UidTraceTest(unittest.TestCase):
    def service(self):
        with patch.object(dev, 'SETTINGS_FILE', Path('/tmp/__wk_trace_test_missing__.json')):
            return dev.DeviceService()

    def device(self):
        c = types.SimpleNamespace(
            is_serial_opened=True, is_data_available=True,
            last_success_time_sec=time.time(), device_uid_checked=True,
            device_uid_raw='AABBCCDDEEFF001122334455', device_sn='DTS321000',
            thread_lock=threading.Lock(), comm_port='COM3', baudrate=1500000,
            comm_rate=30.0, comm_success_count=100, comm_total_count=100,
            last_success_time_text='2026-11-10 10:10:10', frame_interval_ms=30,
            thread_instance=None)
        r = types.SimpleNamespace(data_lock=threading.Lock(),is_data_valid=True,
            acc_g_arr=[(0.1,0.2,0.95)]*16, gyr_dps_arr=[(1,2,3)]*16,
            temp_c=25,tick_ms=123,acc_fs=2,gyro_fs=250,data_odr=833,
            fifo_state=0,data_update_count=100)
        s = self.service()
        s.imu_mod = types.SimpleNamespace(tiltSensorComm=c, tiltSensorRawData=r)
        s.imu_comm_mod = types.SimpleNamespace(mb_last_serial_error='')
        s.csv_mod = types.SimpleNamespace(csv_is_enabled=lambda:False,csv_row_count=0,
            csv_drop_count=0,csv_file_path='',csv_write_error='')
        return s,c,r

    def test_trace_contains_only_real_callback_frames(self):
        s,c,r=self.device()
        self.assertEqual(s.imu_trace()['samples'], [])
        s._trace_frame_from_original_worker(1234.5, r)
        rows=s.imu_trace(0)['samples']
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['acc'], [0.1,0.2,0.95])
        self.assertEqual(rows[0]['gyro'], [1.0,2.0,3.0])
        self.assertEqual(s.imu_trace(rows[-1]['seq'])['samples'], [])
        r.is_data_valid=False
        s._trace_frame_from_original_worker(1235.5, r)
        self.assertEqual(len(s.imu_trace()['samples']),1)
        c.last_success_time_sec=time.time()-20
        self.assertFalse(s.imu_trace()['online'])
        self.assertEqual(s.imu_trace()['samples'],[])

    def test_uid_status_and_manual_retry_in_single_thread(self):
        s,c,r=self.device()
        data=s.status()['imu']
        self.assertEqual(data['device_uid_raw'],'AABBCCDDEEFF001122334455')
        self.assertEqual(data['serial_number'],'DTS321000')
        reply=s.imu_uid_retry()
        self.assertIn('UID', reply)
        self.assertFalse(c.device_uid_checked)
        self.assertEqual(c.device_uid_raw,'')
        with self.assertRaises(ValueError):s.imu_uid_retry()
        c.is_serial_opened=False
        s.uid_last_retry=0
        with self.assertRaises(ValueError):s.imu_uid_retry()

    def test_nonnegative_and_limited_trace(self):
        s,c,r=self.device()
        for i in range(2005):s._trace_frame_from_original_worker(i, r)
        self.assertEqual(len(s.trace_rows),1800)
        self.assertEqual(len(s.imu_trace()['samples']),240)
        for bad in (-1,'abc', True):
            with self.assertRaises(ValueError):s.imu_trace(bad)

if __name__=='__main__':unittest.main()
