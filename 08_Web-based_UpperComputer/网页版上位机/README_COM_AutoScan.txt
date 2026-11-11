WK IMU R7 白色网页版 - Win11 COM 自动扫描修复
===========================================
问题根因：上一版将 config.xml 中保存的 COM5 填入网页输入框，启动时没有自动请求 /api/ports，
而输入框的 datalist 也不是真正的下拉选择框，因此 COM5 容易被误认为扫描结果。

本版修复：
1. 页面打开时由 Python 后端自动扫描 Windows 真实 COM 口；进入 PCB 页面也会刷新。
2. PCB 串口改成真正的下拉框，列出端口号及 Windows 设备描述。
3. 原保存端口如果不存在，将显示黄色警告，不再当成真实检测结果。
4. 未检测到 COM 口时不允许选择旧的 COM5 去连接。
5. 额外提供 Scan_COM_Win11.cmd（只读扫描，不会打开/占用串口）。
6. 保留原 R7 硬件驱动、算法与其余 Web 功能。没有增加任何 PLC 写温或 WK 运动控制。

使用：
- 关闭原版 R7 桌面程序和其他串口工具；不要让两个程序同时打开 PCB COM 口。
- 解压新工程到新的文件夹（不要覆盖正在运行的旧工程）。
- 首次安装运行 Install_Web_Win11.cmd；再运行 Start_R7_Web_Win11.cmd。
- 浏览器按 Ctrl+F5 强制刷新，进入“PCB / IMU 实时采集”，查看实际扫描到的端口。
- 若为空，双击 Scan_COM_Win11.cmd，核对 Windows 设备管理器 > 端口（COM 和 LPT）。
- 若能扫描到 COM，但连接仍失败，查看网页诊断和 web_startup.log 的具体错误。

可在浏览器打开 http://127.0.0.1:8765/api/ports 检查后端真实扫描结果。
例：{"ok":true,"data":[{"device":"COM3","description":"USB Serial Device (COM3)"}]}
这里的示例不是你电脑上的实际扫描结果。

安全：串口枚举不连接 PCB，不发送任何硬件指令；现场运动与温控控制仍保持禁用。
