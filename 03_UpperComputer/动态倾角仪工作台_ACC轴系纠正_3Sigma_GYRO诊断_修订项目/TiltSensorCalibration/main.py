# ---------------------------------------------------------------------------
# 本机WMI异常保护：
# platform.system()/uname() 默认先走WMI查询(platform._wmi_query -> _wmi.exec_query)，
# 本机该查询会卡死(实测>15秒不返回)，凡是调用它的第三方库(如snap7)在导入时都会
# 一起卡住，导致主界面窗口出不来。这里把WMI查询置为"不支持"，等价于Python在
# 未安装_wmi模块时的行为，platform会自动回退到 sys.getwindowsversion()，
# 结果不变且不再依赖WMI。若本机WMI恢复正常，删掉这段保护也不影响功能。
# ---------------------------------------------------------------------------
import platform as _platform_guard
if hasattr(_platform_guard, '_wmi_query'):
    def _wmi_query_disabled(*args, **kwargs):
        raise OSError("not supported")
    _platform_guard._wmi_query = _wmi_query_disabled

from pathlib import Path
import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication
from PySide6.QtUiTools import QUiLoader

# 保持历史模块使用的相对配置与 DLL 路径，同时支持从 IDE / 任意目录启动。
PROJECT_DIR = Path(__file__).resolve().parent
os.chdir(PROJECT_DIR)
for subdir in ("form", "tilt_sensor", "turntable", "temperature_chamber", "tilt_sensor_calibration", "debug", "ellipsoid", "lm", "acc_tdc"):
    path = str(PROJECT_DIR / subdir)
    if path not in sys.path:
        sys.path.insert(0, path)

from form_turntable_ctrl import FormTurntableCtrl
from form_tc import FormTc
from form_tilt_sensor_cal import FormTiltSensorCal
from form_imu_calibration import FormImuCalibration


def _remove_page(tab_widget, page):
    """从导航中摘掉遗留页（不销毁 widget，旧模块仍可安全取到相应对象）。"""
    index = tab_widget.indexOf(page)
    if index >= 0:
        tab_widget.removeTab(index)


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei UI", 9))
    ui = QUiLoader().load(str(PROJECT_DIR / "ui" / "mainWindow.ui"))
    if ui is None:
        raise RuntimeError("无法加载 ui/mainWindow.ui")

    # 恢复原软件紧凑尺寸；不强制扩大为 1460x900。
    ui.setFixedSize(1144, 723)
    ui.setWindowFlags(ui.windowFlags() & ~Qt.WindowCloseButtonHint)

    # 初始化所有仍在使用的底层设备模块，保留原串口/转台/温箱通信能力。
    form_turntable_ctrl = FormTurntableCtrl(ui)
    form_tc = FormTc(ui)
    form_tilt_sensor_cal = FormTiltSensorCal(ui)
    form_imu_calibration = FormImuCalibration(ui, form_turntable_ctrl)

    # 六轴 IMU 工作区优先：不再向用户暴露柔性测斜仪阵列、FTP、温漂计算等历史入口。
    # 注意：旧控件并未销毁，避免历史业务代码访问已删除的 QObject。
    # 数据预览区只保留“实时数据”和“数据记录”两个页面；
    # 校准计算 / 温漂补偿 / FTP / 故障统计控件已从 .ui 中移除。
    _remove_page(ui.tabWidget_CalMain, ui.tab_18)  # 旧版柔性测斜仪自动校准入口

    tabbar = ui.tabWidget_CalMain.tabBar()
    imu_index = ui.tabWidget_CalMain.indexOf(form_imu_calibration.page)
    if imu_index >= 0:
        tabbar.moveTab(imu_index, 0)
    ui.tabWidget_CalMain.setCurrentWidget(form_imu_calibration.page)
    ui.tabWidget_AccDataManual.setCurrentWidget(ui.tab_AccData)

    # 正常退出时务必关闭实验 CSV / 释放记录队列。
    app.aboutToQuit.connect(form_imu_calibration.shutdown)
    ui.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
