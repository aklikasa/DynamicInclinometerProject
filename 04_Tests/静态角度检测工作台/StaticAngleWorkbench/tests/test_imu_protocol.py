import unittest
from app.devices.imu_protocol import crc16, read_registers, decode, signed16, IMUProtocolError


class FakePort:
    def __init__(self, data):
        self.data = data
        self.pos = 0
        self.requests = []

    def reset_input_buffer(self):
        pass

    def write(self, msg):
        self.requests.append(msg)
        return len(msg)

    def read(self, n):
        part = self.data[self.pos:self.pos+n]
        self.pos += len(part)
        return part


def response_for(words, addr=1):
    data = b''.join(int(word).to_bytes(2, 'big') for word in words)
    header = bytes([addr, 3, len(data)]) + data
    return header + crc16(header).to_bytes(2,'little')


class IMUTests(unittest.TestCase):
    def make_sample(self):
        words = [0]*104
        words[0] = 0
        words[1:17] = [1000]*16
        words[17:33] = [(-1000) & 65535]*16
        words[33:49] = [16384]*16
        words[49:65] = [10]*16
        words[97] = 256
        words[98] = 0xDDCC; words[99] = 0xBBAA
        words[100] = 2; words[101] = 250; words[102] = 833
        return words

    def test_known_crc(self):
        self.assertEqual(crc16(bytes.fromhex('01 03 00 00 00 0A')), 0xCDC5)

    def test_modbus_payload(self):
        data = self.make_sample()
        wire = FakePort(response_for(data))
        actual = read_registers(wire,1)
        self.assertEqual(actual, data)
        self.assertEqual(wire.requests[0][:6],bytes.fromhex('01 03 03 E8 00 68'))
        self.assertEqual(len(wire.requests[0]),8)

    def test_bad_crc_and_exception(self):
        words = self.make_sample()
        bad = bytearray(response_for(words)); bad[-1] ^= 1
        with self.assertRaisesRegex(IMUProtocolError, 'CRC16'):
            read_registers(FakePort(bad))
        reply = bytes([1,0x83,2]); reply += crc16(reply).to_bytes(2,'little')
        with self.assertRaisesRegex(IMUProtocolError, '异常码'):
            read_registers(FakePort(reply))

    def test_decode_scaling_according_to_original(self):
        frame = decode(self.make_sample())
        self.assertTrue(frame.valid)  # 原始旧工程依赖六轴数组是否全零，不依赖 unread
        self.assertAlmostEqual(frame.accel_g[0], .061, places=7)
        self.assertAlmostEqual(frame.accel_g[1], -.061, places=7)
        self.assertAlmostEqual(frame.accel_g[2], 16384*.000061, places=7)
        self.assertAlmostEqual(frame.gyro_dps[0], .0875, places=7)
        self.assertEqual(frame.tick_ms, 0xBBAADDCC)
        self.assertEqual(frame.temp_c,26)
        self.assertEqual(signed16(65535),-1)

    def test_empty_frame_and_range_fallback(self):
        empty = [0]*104
        self.assertFalse(decode(empty).valid)
        data = self.make_sample(); data[100]=0; data[101]=0
        frame = decode(data, 8, 500)
        self.assertFalse(frame.acc_fs_reported)
        self.assertFalse(frame.gyro_fs_reported)
        self.assertEqual(frame.acc_fs,8)
        self.assertEqual(frame.gyro_fs,500)


if __name__ == '__main__': unittest.main()
