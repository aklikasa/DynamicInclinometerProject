"""使用Snap7读写西门子S7系列PLC"""

# 本机WMI异常保护(同main.py)：platform.system() 走WMI查询在本机会卡死，
# snap7导入时会调用它。这里置为"不支持"让platform回退到 getwindowsversion()。
import platform as _platform_guard
if hasattr(_platform_guard, '_wmi_query'):
    def _wmi_query_disabled(*args, **kwargs):
        raise OSError("not supported")
    _platform_guard._wmi_query = _wmi_query_disabled

from snap7 import client, util
from snap7.types import Areas


def plc_connect(ip: str, plc_model=3, rack=0, slot=1):
    """
    连接PLC

    Args:
        ip (str): PLC的IPV4地址
        plc_model (int): 连接类型：1用于PG，2用于OP，3至10用于S7基本
        rack (int): 服务器上的机架
        slot (int): 服务器上的插槽

    Returns:
        Client: 连接PLC成功，返回Client对象实例。连接PLC失败，返回None。

    """
    # 初始化一个客户端
    my_plc = client.Client()
    # 设置连接资源类型，即客户端,连接到PLC(注意：连接西门子s7-200SMART系列PLC一定要调用此函数！其他型号PLC不一定要调用此函数)
    my_plc.set_connection_type(plc_model)
    # 连接到S7服务器
    try:
        my_plc.connect(ip, rack, slot)
    except:
        return None
    return my_plc


def plc_disconnect(client_instance):
    """
    断开PLC的连接

    Args:
        client_instance: Client对象实例

    Returns:
        None

    """
    client_instance.disconnect()
    client_instance.destroy()  # 不用了一定要销毁客户端


def plc_connect_state_get(client_instance):
    """
    获取PLC的连接状态

    Args:
        client_instance: Client对象实例

    Returns:
        bool: 已连接，返回True; 未连接，返回False。

    """
    return client_instance.get_connected()


def plc_v_read(client_instance, addr, bit_index):
    """
    读取V区指定地址的第几位数据

    Args:
        client_instance (Client类): Client对象实例
        addr (int): 要读取数据的字节起始地址
        bit_index (int): 位(bit)索引(0~7)

    Returns:
        bool: 读取成功，返回位值(True或False)；读取失败，返回None。

    """
    try:
        byte_array = client_instance.read_area(Areas.DB, 1, addr, 1)
        value = util.get_bool(byte_array, 0, bit_index)
        return value
    except:
        return None


def plc_vw_read(client_instance, addr):
    """
    读取V区指定地址的2字节长度数据

    Args:
        client_instance (Client类): Client对象实例
        addr (int): 要读取数据的字节起始地址

    Returns:
        int: 读取成功，返回值；读取失败，返回None。

    """
    try:
        byte_array = client_instance.read_area(Areas.DB, 1, addr, 2)
        value = util.get_int(byte_array, 0)
        return value
    except:
        return None


def plc_m_read(client_instance, addr, bit_index):
    """
    读取M区指定地址的第几位数据

    Args:
        client_instance (Client类): Client对象实例
        addr (int): 要读取数据的字节起始地址
        bit_index (int): 位(bit)索引(0~7)

    Returns:
        bool: 读取成功，返回位值(True或False)；读取失败，返回None。

    """
    try:
        byte_array = client_instance.read_area(Areas.MK, 0, addr, 1)
        value = util.get_bool(byte_array, 0, bit_index)
        return value
    except:
        return None


def plc_v_write(client_instance, addr, bit_index, value):
    """
    向V区指定地址的指定位写入值

    Args:
        client_instance (Client类): Client对象实例
        addr (int): 要写入数据的字节起始地址
        bit_index (int): 位(bit)索引(0~7)
        value (bool): 写入值，True或False

    Returns:
        bool: 写入成功，返回True；写入失败，返回False。

    """
    try:
        byte_array = client_instance.read_area(Areas.DB, 1, addr, 1)
        util.set_bool(byte_array, 0, bit_index, value)
        client_instance.write_area(Areas.DB, 1, addr, byte_array)
        return True
    except:
        return False


def plc_vw_write(client_instance, addr, value):
    """
    向V区指定地址写入2字节值

    Args:
        client_instance (Client类): Client对象实例
        addr (int): 要写入数据的字节起始地址
        value (int): 写入值

    Returns:
        bool: 写入成功，返回True；写入失败，返回False。

    """
    try:
        byte_array = client_instance.read_area(Areas.DB, 1, addr, 2)
        byte_array = util.set_int(byte_array, 0, value)
        client_instance.write_area(Areas.DB, 1, addr, byte_array)
        return True
    except:
        return False


def plc_m_write(client_instance, addr, bit_index, value):
    """
    向M区指定地址的指定位写入值

    Args:
        client_instance (Client类): Client对象实例
        addr (int): 要写入数据的字节起始地址
        bit_index (int): 位(bit)索引(0~7)
        value (bool): 写入值，True或False

    Returns:
        bool: 写入成功，返回True；写入失败，返回False。

    """
    try:
        byte_array = client_instance.read_area(Areas.MK, 0, addr, 1)
        util.set_bool(byte_array, 0, bit_index, value)
        client_instance.write_area(Areas.MK, 0, addr, byte_array)
        return True
    except:
        return False


def plc_comm_test():
    ip = '192.168.0.10'
    client_instance = plc_connect(ip)

    v_value = plc_v_read(client_instance, 504, 0)
    vw_value = plc_vw_read(client_instance, 2100)
    m_value = plc_m_read(client_instance, 3, 6)

    plc_disconnect(client_instance)


def main():
    plc_comm_test()


if __name__ == '__main__':
    main()
