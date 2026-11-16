# 修订说明：旧版稳定底座 + 仅标定升级 + 退出问题修复

## 原因定位

1. 用户截图中的 **“上位机操作异常 / 具体原因已写入 logs/app.log”** 弹窗，来自此前 ASM330LHHX 新版 `main.py` 所安装的 `sys.excepthook`；用户最新上传的 `紧凑玻璃版_修复启动导入(3).zip` 和前一版“旧版通信保留”**都没有这段弹窗代码**。这说明截图时实际运行入口可能指向其他版本或混用文件。仅凭截屏无法确认最初异常发生在哪一行，需查看相应运行目录的 logs/app.log 完整 traceback。
2. 两个提供的旧底座工程里的 `form/form_turntable_ctrl.py` 存在一个真实的退出缺陷：关闭时不判断是否连接便访问转台 DLL、使用 `while True` 等待转台线程，以及温箱线程结束调用中的无限等待。这些都有界面假死风险。以前能退出不代表该分支可靠。
3. 上述函数原来调用依赖 `from ui_utils import *` 带入的 `QApplication.quit()`；本修订使用显式 `QCoreApplication.quit()`，避免名称查找受其他版本导入变化影响。截图中的 UnboundLocalError 的具体原始调用栈未提供，因此不能断言此项完全解释该异常。

## 本次范围（只改一份已有 Python 文件）

- 基于“旧版通信保留_仅ACC_GYRO标定升级_完整项目.zip”重新解压，保持其完整 ACC/GYRO 生产工艺与 Excel 报告。
- 仅修改 `form/form_turntable_ctrl.py`：退出前检查转台已安全断开，未连接时不调用厂商 DLL，温箱线程退出限时 2 秒，使用显式 `QCoreApplication.quit()`；温箱在线时保持安全停止定值检查。若设备仍连接，则温和提示先断开，不强行断电。
- `main.py` 与用户上传的“紧凑玻璃版_修复启动导入(3).zip”逐字节相同；没有自定义 `sys.excepthook`，PyCharm 下未处理异常由控制台正常打印，不自动弹“上位机操作异常”窗口。
- IMU 串口、转台通信 DLL、温箱底层模块、`ui/mainWindow.ui`、标定算法全部保持不变。

## 使用方式

**解压到全新目录，PyCharm 的 Script path 必须指向此次新目录下的 `TiltSensorCalibration/main.py`，Working directory 为这个 `TiltSensorCalibration` 目录**。不要只复制部分文件混到之前的工程。可先执行 `python tools/check_version_and_exit.py` 检查是否为正确版本。

## 限制与安全

- 此次没有 Windows/硬件联调，不能保证第三方 DLL 不会卡在内部或异常进程级崩溃。
- 转台处于连接/运动状态时，关闭窗口会提示**先在转台页面完成停车及断开**，这是防止在状态未知时直接对实体设备断电的设计。不得用强杀进程代替硬件急停。
- 如果弹窗仍然出现“具体原因已写入 logs/app.log”，优先检查 PyCharm 是否仍运行了以前的入口，并保留 `logs/app.log` 中完整 traceback。
