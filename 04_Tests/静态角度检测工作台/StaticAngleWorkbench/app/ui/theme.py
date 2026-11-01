"""UI 视觉系统：深色液态玻璃 / 柔和动态光晕 / 微发光组件。"""
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QPainter, QRadialGradient, QLinearGradient
from PySide6.QtWidgets import QWidget, QGraphicsDropShadowEffect

STYLESHEET = r'''
* { font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Noto Sans CJK SC", "Segoe UI"; font-size: 11px; color: #DAE5F7; }
QMainWindow { background: #080F20; }
QWidget#appRoot { background: transparent; }
QFrame#glass { background-color: rgba(22,36,61,235); border: 1px solid #2A405C; border-radius: 12px; }
QFrame#glassSoft { background-color: rgba(20,33,57,218); border: 1px solid #2A3D58; border-radius: 12px; }
QFrame#metric { background-color: #142640; border: 1px solid #2C4665; border-radius: 14px; }
QFrame#header { background: transparent; border: none; }
QFrame#divider { background: #2A3C55; border: none; min-height:1px; max-height:1px; }
QLabel#hero { font-size: 19px; font-weight: 750; color: #F3F7FF; }
QLabel#subhead { font-size: 12px; color: #91A4C0; }
QLabel#sectionTitle { font-size: 13px; font-weight: 700; color: #EFF6FF; }
QLabel#small { font-size: 11px; color: #8CA4C2; }
QLabel#number { font-family: "Segoe UI", "Consolas", "Microsoft YaHei UI"; font-size: 18px; font-weight: 650; color: #F7FBFF; }
QLabel#stat { background: #142B44; color: #76D9E4; border: 1px solid #2A6178; border-radius: 11px; padding: 4px 8px; font-size: 11px; }
QPushButton { border-radius: 11px; padding: 6px 10px; font-size: 11px; font-weight: 650; }
QPushButton#primary { color: #07182B; background: #72DFEC; border:1px solid #B1F4FC; }
QPushButton#primary:hover { background: #9AF0FA; }
QPushButton#primary:pressed { background: #54C2D0; }
QPushButton#secondary { color: #DBEBFC; background: #253A57; border:1px solid #395475; }
QPushButton#secondary:hover { background: #345172; border-color:#4E7197; }
QPushButton#ghost { color: #B9CEE8; background: transparent; border:1px solid #3A5271; }
QPushButton#ghost:hover { background: #263D5B; }
QPushButton#danger { color: #FFC5CC; background: #4D2639; border: 1px solid #8C4057; }
QPushButton#danger:hover { background: #68364A; }
QPushButton:disabled { background: #182638; color: #536B85; border: 1px solid #2A3A4C; }
QLineEdit, QComboBox, QDoubleSpinBox, QSpinBox { background: #101D32; color:#E3EEFF; border:1px solid #35506D; border-radius: 9px; padding:5px 8px; selection-background-color: #4CBBCF; min-height: 16px; }
QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus, QSpinBox:focus { border-color:#68CEDC; }
QLineEdit:read-only { color: #ADC1D9; }
QComboBox::drop-down { border:0; width:22px; }
QComboBox QAbstractItemView { background: #1C2D48; color: #E1EAFA; selection-background-color: #315E78; border:1px solid #47617C; }
QTextEdit { background: #101C30; color:#B7D9ED; border:1px solid #29435F; border-radius:12px; padding:11px; font: 11px Consolas, "Microsoft YaHei UI"; }
QScrollArea { background: transparent; border:0; }
QScrollBar:vertical { background:#12223A; width:8px; margin:3px; }
QScrollBar::handle:vertical { background:#36506B; border-radius:4px; min-height:25px; }
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical { height:0px; }
QDialog { background: #101C30; }
QMessageBox { background:#13233B; }
QToolTip { background:#1F344F; color:white; border:1px solid #5A7897; padding:7px; }
'''


class AuroraBackground(QWidget):
    """纯 Qt 绘制的多层玻璃光晕背景，无外部贴图依赖。"""
    def paintEvent(self, _):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect())
        grad = QLinearGradient(0, 0, self.width(), self.height())
        grad.setColorAt(0, QColor('#080E1D'))
        grad.setColorAt(.52, QColor('#0B172A'))
        grad.setColorAt(1, QColor('#0A1021'))
        painter.fillRect(rect, grad)
        for x, y, radius, rgb in [(self.width()*.18, -90, 460, (30,125,172)),
                                   (self.width()*.82, self.height()*.1, 460, (68,83,177)),
                                   (self.width()*.73, self.height()*1.15, 510, (20,103,132))]:
            glow = QRadialGradient(x,y,radius)
            glow.setColorAt(0, QColor(*rgb, 45))
            glow.setColorAt(1, QColor(*rgb, 0))
            painter.fillRect(rect, glow)
        painter.end()


def shadow(widget, blur=32, opacity=45):
    fx = QGraphicsDropShadowEffect(widget)
    fx.setBlurRadius(blur)
    fx.setOffset(0, 9)
    fx.setColor(QColor(0, 0, 0, opacity))
    widget.setGraphicsEffect(fx)
