# 转台回零弹窗兼容与自动归零状态提示修复

## 本次问题

在 PySide6 上位机中，旧 `form/form_turntable_ctrl.py` 使用 `tkinter.messagebox.showinfo()` 提示“内轴、外轴回零中”，某些虚拟环境无法找到 `init.tcl`，导致 `_tkinter.TclError`。这是 GUI 弹窗库混用问题，**不能据此判断转台回零指令是否执行成功**。

## 修改范围（在“稳定底座_量程不阻断标定”项目基础上）

- 新增 `qt_dialogs.py`，为旧 `messagebox`（`showinfo/showwarning/showerror`）及 `filedialog.askdirectory` 提供 PySide6 映射，无 Tcl/Tk 依赖。
- 对原来使用 `from tkinter import filedialog, messagebox` 的五个 Python 文件，只替换导入语句，不修改这些文件中的数据采集、通信及标定算法。
- `form/form_turntable_ctrl.py` 中仅重写三个手动回零按钮的提示逻辑：仍使用原有两种厂商 DLL 的回零指令及原始指令参数；确保通信锁释放之后才提示错误；下发成功时仅在底部状态栏与控制台非阻塞显示“回零命令已发送”，不再弹出阻塞对话框。
- `form/form_imu_calibration.py` 增加自动标定归零阶段的可见进度，包括阶段、耗时、两轴角度和速度。**没有修改双轴归零、角度判定、加速度/陀螺仪拟合或采样算法**。

## 边界与操作注意

- 转台控制器反馈 `360°` 与位置指令 `0°` 是否机械等价，尚需根据厂家编码器/机械限位定义确认。本版不会自动把 `360°` 当成 `0°`，也不会为绕过超时放松到位判定。
- 状态栏显示“回零命令已发送”**不代表回零已完成**。须通过轴找零/到位状态和位置反馈验证。
- 厂商 DLL 仍在已有调用线程中运行，若 DLL 自身阻塞或崩溃，单纯更换 Qt 弹窗不能保证软件绝不卡死；没有修改这些通信模块以避免再次引入读数/退出回归。
- 没有修改 `main.py`、`ui/mainWindow.ui`、IMU 串口采样、转台厂商 DLL、数据记录及退出逻辑。

## 验证

运行无硬件检查：

```powershell
python tools/test_qt_homing_patch.py
```

该脚本验证 Qt 弹窗接口、单轴/双轴回零命令调用路径、失败/异常时的锁释放以及自动归零阶段显示。另已完成全部 Python 源码语法检查和 UI XML 解析。**尚未完成 Windows/PySide6/真实转台实机联调**。

第一次测试建议先在机械安全范围和线缆安全条件下测试手动回零，并确认底部状态栏及反馈；之后再进行 ACC 自动标定。
