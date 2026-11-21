"""UI实用工具"""
from PySide6.QtWidgets import *
from PySide6.QtCore import QTimer
import xml.etree.ElementTree as Et

class MyMessageBox:
    """具有指定文本、标题的消息框"""
    def __init__(self):
        self.message_box = QMessageBox()

    def show(self, text, caption):
        """显示具有指定文本、标题的消息框"""
        self.message_box.setText(text)
        self.message_box.setWindowTitle(caption)
        self.message_box.exec()


def xml_write(file_path, tag, text):
    """
    写xml文件

    Args:
        file_path (str): xml文件路径
        tag (str): 标签名字
        text (str): 写入的内容

    Returns:
        str: xml文件写入成功，返回True；写入失败，返回False

    """
    try:
        tree = Et.parse(file_path)
        root = tree.getroot()
        for iterator in root.iter(tag):
            iterator.text = text
        tree.write(file_path)
        return True
    except:
        return False


def xml_read(file_path, tag):
    """
    读xml文件

    Args:
        file_path (str): xml文件路径
        tag (str): 标签名字

    Returns:
        str: xml文件读取成功，返回标签对应的内容；读取失败，返回空字符。

    """
    try:
        tree = Et.parse(file_path)
        root = tree.getroot()
        for iterator in root.iter(tag):
            return iterator.text
    except:
        return ""


def remove_tab_by_name(tab_widget, name):
    """
    遍历所有选项卡，找到与name匹配的选项卡并移除

    Args:
        tab_widget (tab_widget): 选项卡
        name (str): tab的Text

    Returns:
        None

    """
    for i in range(tab_widget.count()):
        if tab_widget.tabText(i) == name:
            tab_widget.removeTab(i)
            break  # 只移除一个匹配的选项卡
