# -*- coding: utf-8 -*-
"""
test_asm330_modbus.py —— asm330_modbus.py 的离线自测（不需要任何硬件/从机）

覆盖内容
    1. 换算函数：加速度/角速度/温度 -> double，符号保持不变，边界与全部量程
    2. 寄存器映射：ASM330_DATA 各成员偏移解析是否正确（含 Time 低 16 位在前）
    3. 量程判定：寄存器上报量程 / 非法或 0 时回退默认 ±2G、±2000dps / force_fs 强制
    4. CRC16：标准 Modbus 向量（与固件 crc16_lrc.c 算法一致）
    5. 主站客户端：open()/close()/reopen()/is_open 状态机、幂等性、错误路径
       （用假 client 工厂模拟，不占用真实串口）

运行：python test_asm330_modbus.py
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import asm330_modbus as m    # noqa: E402

EPS = 1e-9


def approx(a: float, b: float, tol: float = EPS) -> bool:
    return math.isclose(a, b, rel_tol=0.0, abs_tol=tol)


# ===========================================================================
# 1. 换算函数
# ===========================================================================

def test_crc16_standard_vector() -> None:
    """CRC 与固件一致：标准 Modbus CRC 值 0xCDC5，线上按低字节在前发 C5 CD。

    说明：固件 crc16_lrc.c 的 crc16() 内部把两个字节做了交换后返回 0xC5CD，
          再以“高字节先发”写入帧尾，两个操作合起来正好等价于标准 Modbus
          （标准值 0xCDC5，低字节先发）。本函数实现的是标准算法。
    """
    frame = bytes([0x01, 0x03, 0x00, 0x00, 0x00, 0x0A])
    crc = m.crc16_modbus(frame)
    assert crc == 0xCDC5, "标准 Modbus CRC 应为 0xCDC5，实际 0x%04X" % crc
    wire = [crc & 0xFF, (crc >> 8) & 0xFF]          # 线上低字节在前
    assert wire == [0xC5, 0xCD], "帧尾字节应为 C5 CD，实际 %s" % wire
    # 官方校验值：CRC-16/MODBUS("123456789") = 0x4B37，线上低字节在前 -> 37 4B
    crc2 = m.crc16_modbus(b"123456789")
    assert crc2 == 0x4B37, "CRC-16/MODBUS 校验值应为 0x4B37，实际 0x%04X" % crc2
    assert (crc2 & 0xFF, crc2 >> 8) == (0x37, 0x4B)


def test_to_int16() -> None:
    assert m.to_int16(0x0000) == 0
    assert m.to_int16(0x7FFF) == 32767
    assert m.to_int16(0xFFFF) == -1
    assert m.to_int16(0x8000) == -32768
    assert m.to_int16(-100) == -100          # 已是负数时保持原值


def test_conversion_sign_preserved() -> None:
    """符号必须保持不变：正原始值 -> 正值，负原始值 -> 负值。"""
    assert m.accel_raw_to_g(100) > 0.0
    assert m.accel_raw_to_g(0xFF9C) < 0.0                    # 0xFF9C = -100
    assert approx(m.accel_raw_to_g(100), -m.accel_raw_to_g(0xFF9C))
    assert approx(m.accel_raw_to_g(100), 0.0061)
    assert approx(m.accel_raw_to_g(-100), -0.0061)
    assert approx(m.accel_raw_to_g(0x8000), -1.998848)

    assert m.gyro_raw_to_dps(100) > 0.0
    assert m.gyro_raw_to_dps(0xFF9C) < 0.0
    assert approx(m.gyro_raw_to_dps(100), 7.0)
    assert approx(m.gyro_raw_to_dps(-100), -7.0)
    assert approx(m.gyro_raw_to_dps(0x8000), -2293.76)


def test_conversion_all_ranges() -> None:
    """逐个量程核对 mg/LSB、mdps/LSB。"""
    acc_expected = {2: 0.061, 4: 0.122, 8: 0.244, 16: 0.488}
    for fs, sens in acc_expected.items():
        assert approx(m.accel_raw_to_mg(1000, fs), 1000 * sens), "acc fs=%d" % fs
        assert approx(m.accel_raw_to_g(1000, fs), 1000 * sens / 1000.0)

    gyro_expected = {125: 4.37, 250: 8.75, 500: 17.5,
                     1000: 35.0, 2000: 70.0, 4000: 140.0}
    for fs, sens in gyro_expected.items():
        assert approx(m.gyro_raw_to_mdps(1000, fs), 1000 * sens), "gyro fs=%d" % fs
        assert approx(m.gyro_raw_to_dps(1000, fs), 1000 * sens / 1000.0)


def test_conversion_returns_double() -> None:
    """换算结果必须是 double（Python float），不是 int。"""
    for value in (m.accel_raw_to_g(0x8000), m.accel_raw_to_mg(1),
                  m.gyro_raw_to_dps(0xFF9C), m.gyro_raw_to_mdps(1),
                  m.temp_raw_to_celsius(0)):
        assert isinstance(value, float), "%r 不是 float" % (value,)
    assert isinstance(m.accel_raw_to_g(0), float)


def test_conversion_invalid_range() -> None:
    for bad in (3, 32, 0):
        for func in (m.accel_raw_to_g, m.accel_raw_to_mg):
            try:
                func(100, bad)
            except ValueError:
                pass
            else:
                raise AssertionError("加速度量程 %r 应抛 ValueError" % (bad,))
    try:
        m.gyro_raw_to_dps(100, 300)
    except ValueError:
        pass
    else:
        raise AssertionError("陀螺仪量程 300 应抛 ValueError")


def test_temperature_conversion() -> None:
    assert approx(m.temp_raw_to_celsius(0), 25.0)
    assert approx(m.temp_raw_to_celsius(-256), 24.0)
    assert approx(m.temp_raw_to_celsius(6400), 50.0)
    assert approx(m.temp_raw_to_celsius(0xFF00), 24.0)      # -256

# ===========================================================================
# 2. 寄存器映射与解析
# ===========================================================================

def make_words(acc_level=2, gyro_level=2000, odr=833, unread=1,
               tick=0x12345678, temp=0, fifo_state=0x0001):
    """构造一组 104 个寄存器的默认数据（模拟从机共享结构体）。"""
    words = [0] * m.ASM330_DATA_WORDS
    words[m.REG_OFF_DATA_UNREAD] = unread
    words[m.REG_OFF_TEMP] = temp & 0xFFFF
    words[m.REG_OFF_TIME_LOW] = tick & 0xFFFF
    words[m.REG_OFF_TIME_HIGH] = (tick >> 16) & 0xFFFF
    words[m.REG_OFF_ACC_LEVEL] = acc_level
    words[m.REG_OFF_GYRO_LEVEL] = gyro_level
    words[m.REG_OFF_DATA_ODR] = odr
    words[m.REG_OFF_FIFO_STATE] = fifo_state
    return words


def test_struct_words_and_offsets() -> None:
    """结构体长度与各成员偏移必须与固件一致。"""
    assert m.ASM330_DATA_WORDS == 104
    assert m.SAMPLES_PER_BLOCK == 16
    assert m.REG_OFF_DATA_UNREAD == 0
    assert m.REG_OFF_ACC_X == 1 and m.REG_OFF_ACC_Y == 17 and m.REG_OFF_ACC_Z == 33
    assert m.REG_OFF_GYR_X == 49 and m.REG_OFF_GYR_Y == 65 and m.REG_OFF_GYR_Z == 81
    assert m.REG_OFF_TEMP == 97
    assert m.REG_OFF_TIME_LOW == 98 and m.REG_OFF_TIME_HIGH == 99
    assert m.REG_OFF_ACC_LEVEL == 100 and m.REG_OFF_GYRO_LEVEL == 101
    assert m.REG_OFF_DATA_ODR == 102 and m.REG_OFF_FIFO_STATE == 103
    assert m.MB_REG_ASM330_BASE_HR == 1000 and m.MB_REG_ASM330_BASE_IR == 5000
    assert m.MB_MAX_READ_REGISTERS == 0x7E


def test_parse_register_mapping() -> None:
    """各轴样本按偏移正确解析，且换算为 double。"""
    words = make_words()
    words[m.REG_OFF_ACC_X + 0] = 100                  # AccX[0] = +100
    words[m.REG_OFF_ACC_X + 15] = 0xFF9C              # AccX[15] = -100
    words[m.REG_OFF_ACC_Y + 2] = 0x0010               # AccY[2] = +16
    words[m.REG_OFF_GYR_X + 0] = 100                  # GyrX[0] = +100
    words[m.REG_OFF_GYR_Z + 15] = 0x8000              # GyrZ[15] = -32768
    words[m.REG_OFF_TEMP] = 256                       # +1 ℃ -> 26 ℃
    words[m.REG_OFF_DATA_ODR] = 833
    words[m.REG_OFF_FIFO_STATE] = m.FIFO_STATE_SENSOR_OK | m.FIFO_STATE_FIFO_WTM

    blk = m.parse_asm330_block(words, pc_time=123.0)

    assert len(blk.acc_g) == 16 and len(blk.gyro_dps) == 16
    assert approx(blk.acc_g[0][0], 0.0061)            # 100 * 0.061 mg / 1000
    assert approx(blk.acc_g[15][0], -0.0061)          # 符号保持
    assert approx(blk.acc_g[2][1], 16 * 0.061 / 1000.0)
    assert approx(blk.gyro_dps[0][0], 7.0)            # 100 * 70 mdps / 1000
    assert approx(blk.gyro_dps[15][2], -2293.76)      # -32768 * 70 / 1000
    assert approx(blk.acc_g[1][0], 0.0)
    assert blk.acc_raw[15][0] == -100 and blk.gyro_raw[15][2] == -32768
    assert approx(blk.temp_c, 26.0)
    assert blk.data_odr_hz == 833
    assert blk.fifo_flags == ["SENSOR_OK", "FIFO_WTM"]
    assert blk.pc_time == 123.0

    # Time[0] 为低 16 位、Time[1] 为高 16 位
    words[m.REG_OFF_TIME_LOW] = 0xBEEF
    words[m.REG_OFF_TIME_HIGH] = 0x0001
    assert m.parse_asm330_block(words).tick_ms == 0x0001BEEF


def test_parse_level_from_register() -> None:
    words = make_words(acc_level=16, gyro_level=125)
    words[m.REG_OFF_ACC_X] = 100
    words[m.REG_OFF_GYR_X] = 100
    blk = m.parse_asm330_block(words)
    assert blk.acc_fs_g == 16 and blk.acc_fs_from_reg is True
    assert blk.gyro_fs_dps == 125 and blk.gyro_fs_from_reg is True
    assert approx(blk.acc_g[0][0], 100 * 0.488 / 1000.0)
    assert approx(blk.gyro_dps[0][0], 100 * 4.37 / 1000.0)


def test_parse_level_fallback_default() -> None:
    """寄存器量程为 0/非法时回退默认 ±2G、±2000dps（当前固件 FifoRefresh 被注释即此情况）。"""
    words = make_words(acc_level=0, gyro_level=0)
    blk = m.parse_asm330_block(words)
    assert blk.acc_fs_g == m.DEFAULT_ACC_FS_G == 2
    assert blk.gyro_fs_dps == m.DEFAULT_GYRO_FS_DPS == 2000
    assert blk.acc_fs_from_reg is False and blk.gyro_fs_from_reg is False

    words = make_words(acc_level=7, gyro_level=333)      # 非法值同样回退
    blk = m.parse_asm330_block(words, acc_fs_g=4, gyro_fs_dps=500)
    assert blk.acc_fs_g == 4 and blk.gyro_fs_dps == 500
    assert blk.acc_fs_from_reg is False


def test_parse_force_fs() -> None:
    words = make_words(acc_level=2, gyro_level=2000)
    words[m.REG_OFF_ACC_X] = 100
    blk = m.parse_asm330_block(words, acc_fs_g=8, gyro_fs_dps=500, force_fs=True)
    assert blk.acc_fs_g == 8 and blk.gyro_fs_dps == 500
    assert blk.acc_fs_from_reg is False and blk.gyro_fs_from_reg is False
    assert approx(blk.acc_g[0][0], 100 * 0.244 / 1000.0)


def test_parse_short_words_raises() -> None:
    try:
        m.parse_asm330_block([0] * 10)
    except ValueError:
        return
    raise AssertionError("寄存器数量不足时应抛 ValueError")


def test_block_rows_and_meta() -> None:
    blk = m.parse_asm330_block(make_words(), pc_time=1.0)
    rows = list(blk.sample_rows())
    assert len(rows) == 16
    assert rows[3]["sample_idx"] == 3 and "acc_x_g" in rows[0] and "temp_c" in rows[0]
    assert isinstance(rows[0]["acc_x_g"], float)
    assert "acc_fs=+-2g" in blk.meta_text()

# ===========================================================================
# 3. 主站客户端：open() / close() / reopen() 状态机与错误路径（假 client，不占用真实串口）
# ===========================================================================

class FakeSocket:
    """模拟 pyserial 的 Serial 对象。"""

    def __init__(self):
        self.is_open = True
        self.flush_calls = 0

    def reset_input_buffer(self):
        self.flush_calls += 1

    def reset_output_buffer(self):
        self.flush_calls += 1

    def close(self):
        self.is_open = False


class FakeResp:
    """模拟 pymodbus 响应对象。"""

    def __init__(self, registers=None, exception_code=None):
        self.registers = registers
        self.exception_code = exception_code

    def isError(self):
        return self.exception_code is not None


class FakeSerialClient:
    """模拟 pymodbus ModbusSerialClient（只实现主站用到的接口）。

    fail_connect / raise_on_connect 为**类属性**，用于让之后 new 出来的实例
    也走“连接失败”路径（工厂每次 open() 都会新建实例）。
    """

    last = None
    fail_connect = False
    raise_on_connect = None

    def __init__(self, port, **kwargs):
        self.port = port
        self.kwargs = kwargs
        self.socket = None
        self.connect_calls = 0
        self.close_calls = 0
        self.calls = []
        self.queue = []
        FakeSerialClient.last = self

    @property
    def connected(self):
        return self.socket is not None

    def connect(self):
        self.connect_calls += 1
        if FakeSerialClient.raise_on_connect is not None:
            raise FakeSerialClient.raise_on_connect
        if FakeSerialClient.fail_connect:
            return False
        self.socket = FakeSocket()
        return True

    def close(self):
        self.close_calls += 1
        if self.socket is not None:
            self.socket.close()
        self.socket = None

    def _read(self, address, count=1, device_id=1, **kwargs):
        self.calls.append((address, count, device_id))
        if not self.queue:
            raise m.ModbusIOException("no response")
        item = self.queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    read_holding_registers = _read
    read_input_registers = _read


def make_fake_client(port="loop://", **kwargs):
    """用假 client 工厂创建主站客户端（不会占用真实串口）。"""
    kwargs.setdefault("reconnect_delay", 0)
    return m.Asm330ModbusClient(port=port, client_factory=FakeSerialClient, **kwargs)


def test_client_starts_closed() -> None:
    """构造对象时不得自动打开串口（auto_open 默认 False）。"""
    cli = make_fake_client()
    assert cli.is_open is False
    assert cli.open_count == 0 and cli.close_count == 0


def test_client_open_close_reopen_state_machine() -> None:
    cli = make_fake_client()
    assert cli.open() is True                    # 打开
    assert cli.is_open is True
    assert cli.open_count == 1
    assert FakeSerialClient.last.connect_calls == 1
    assert FakeSerialClient.last.socket.flush_calls == 2      # 打开后清过收发缓冲

    assert cli.open() is True                    # 已打开：直接返回，不重复 connect
    assert FakeSerialClient.last.connect_calls == 1

    cli.close()                                  # 关闭
    assert cli.is_open is False
    assert cli.close_count == 1
    assert FakeSerialClient.last.socket is None

    cli.close()                                  # 幂等：再关一次不报错
    assert cli.close_count == 2 and cli.is_open is False

    assert cli.reopen() is True                  # 关 -> 开
    assert cli.is_open is True and cli.open_count == 2
    cli.close()


def test_client_context_manager_closes() -> None:
    cli = make_fake_client()
    with cli as handle:
        assert handle is cli and cli.is_open is True
    assert cli.is_open is False


def test_client_open_failure_raises_port_error() -> None:
    """connect() 返回 False 时应抛 Asm330PortError，且不留悬挂句柄。"""
    cli = m.Asm330ModbusClient(port="loop://", client_factory=FakeSerialClient,
                               reconnect_delay=0)
    FakeSerialClient.fail_connect = True
    try:
        try:
            cli.open()
        except m.Asm330PortError as exc:
            assert "loop://" in str(exc)
        else:
            raise AssertionError("connect() 失败时应抛 Asm330PortError")
    finally:
        FakeSerialClient.fail_connect = False      # 复位，避免影响后续用例
    assert cli.is_open is False


def test_client_open_exception_raises_port_error() -> None:
    """connect() 抛异常（如 PermissionError）时应转成 Asm330PortError。"""
    cli = m.Asm330ModbusClient(port="loop://", client_factory=FakeSerialClient,
                               reconnect_delay=0)
    FakeSerialClient.raise_on_connect = PermissionError("Access is denied")
    try:
        try:
            cli.open()
        except m.Asm330PortError as exc:
            assert "打开串口失败" in str(exc)
        else:
            raise AssertionError("connect() 抛异常时应抛 Asm330PortError")
    finally:
        FakeSerialClient.raise_on_connect = None
    assert cli.is_open is False


def test_client_real_port_not_exist_raises() -> None:
    """真实 factory：端口不存在时应给出中文提示。"""
    cli = m.Asm330ModbusClient(port="COM199")
    try:
        cli.open()
    except m.Asm330PortError as exc:
        assert "COM199" in str(exc), str(exc)
    else:
        raise AssertionError("不存在的串口应抛 Asm330PortError")
    assert cli.is_open is False


def test_client_count_limit() -> None:
    """固件限制单次读取 1..126 个寄存器。"""
    for bad in (0, 127, 200):
        try:
            m.Asm330ModbusClient(port="COM5", count=bad)
        except ValueError:
            continue
        raise AssertionError("count=%r 应抛 ValueError" % (bad,))

def test_read_requires_open() -> None:
    cli = make_fake_client()
    try:
        cli.read_raw_words()
    except m.Asm330ModbusError as exc:
        assert "串口未打开" in str(exc)
    else:
        raise AssertionError("未打开串口时应抛 Asm330ModbusError")


def test_read_block_and_request_parameters() -> None:
    cli = make_fake_client()
    cli.open()
    words = make_words()
    words[m.REG_OFF_ACC_X] = 100
    words[m.REG_OFF_GYR_X] = 0xFF9C                # -100
    FakeSerialClient.last.queue.append(FakeResp(registers=words))

    blk = cli.read_block()
    assert approx(blk.acc_g[0][0], 0.0061)
    assert approx(blk.gyro_dps[0][0], -7.0)        # 负号保持
    addr, count, unit = FakeSerialClient.last.calls[0]
    assert (addr, count) == (1000, 104)            # 保持寄存器基址 + 104 个寄存器
    assert unit == 1                               # 默认从机地址 0x01
    cli.close()


def test_read_input_registers_mode() -> None:
    cli = make_fake_client(func_code=m.MB_FUNC_READ_INPUT_REGISTERS)
    assert cli.start_addr == 5000                  # 0x04 模式基址自动为 5000
    cli.open()
    FakeSerialClient.last.queue.append(FakeResp(registers=make_words()))
    cli.read_block()
    assert FakeSerialClient.last.calls[0][0] == 5000
    cli.close()


def test_read_translates_exception_code() -> None:
    """从机异常帧（如 0x02 数量非法）应翻译成中文可读提示。"""
    cli = make_fake_client(retries=1)
    cli.open()
    FakeSerialClient.last.queue.append(FakeResp(exception_code=2))
    try:
        cli.read_raw_words()
    except m.Asm330ModbusError as exc:
        assert "0x02" in str(exc) or "非法数据地址" in str(exc), str(exc)
    else:
        raise AssertionError("异常帧应抛 Asm330ModbusError")
    cli.close()


def test_read_timeout_after_retries() -> None:
    """超时重试耗尽后抛错，错误信息含重试次数。"""
    cli = make_fake_client(retries=2)
    cli.open()
    FakeSerialClient.last.queue = []               # 空队列 -> 每次读取都“无响应”
    try:
        cli.read_raw_words()
    except m.Asm330ModbusError as exc:
        assert "重试 2 次" in str(exc), str(exc)
    else:
        raise AssertionError("超时应抛 Asm330ModbusError")
    cli.close()


def test_read_returns_uint16_words() -> None:
    cli = make_fake_client()
    cli.open()
    FakeSerialClient.last.queue.append(FakeResp(registers=[0, 0x7FFF, 0x8000, 0xFFFF]))
    words = cli.read_raw_words(count=4)
    assert words == [0, 32767, 32768, 65535]       # 原样 16 位无符号，符号由换算函数处理
    cli.close()


# ===========================================================================
# 运行器
# ===========================================================================

def main() -> int:
    tests = [(name, obj) for name, obj in globals().items()
             if name.startswith("test_") and callable(obj)]
    tests.sort(key=lambda item: item[1].__code__.co_firstlineno)
    passed, failed = 0, []
    for name, func in tests:
        try:
            func()
        except Exception as exc:                    # noqa: BLE001
            failed.append((name, exc))
            print("FAIL  %-46s %s: %s" % (name, type(exc).__name__, exc))
        else:
            passed += 1
            print("PASS  %s" % name)
    print("-" * 78)
    print("总计 %d 项，通过 %d 项，失败 %d 项" % (len(tests), passed, len(failed)))
    if failed:
        print("失败列表：%s" % ", ".join(name for name, _ in failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())