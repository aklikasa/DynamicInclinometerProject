【双转台补全】已恢复独立 2TD600 常温标定转台的单 COM 只读连接与状态反馈页面；2FDT600WK 温补转台仍在原入口。两者互不混用。2TD600 厂家 DLL 读取不能验证设备身份；请现场核对，自动动作和标定执行仍未开放。详细见 DUAL_TURNTABLE_README_先读我.txt。

【2026-11-11 补充】PCB/IMU 页面新增原始 UID / DTS 编号、UID 重读及 ACC/GYRO 六轴趋势。详见 TiltSensorCalibration\R7_UID与六轴曲线更新说明.txt。完整 2TD600 常温自动标定仍未迁移，禁止视为可用。

WK IMU R7 白色原生网页版（Win11）
================================
这是实际 R7 工程 + 独立 Web 前后端，不是旧 R6，也不需要启动 PySide6。
不要覆盖原 R7 工作目录。第一次使用先解压到 D:\WK_R7_WEB 等较短目录。

一、首次安装：双击 Install_Web_Win11.cmd，安装独立 Python 环境。
二、启动：双击 Start_R7_Web_Win11.cmd（保留命令窗口）。浏览器打开 http://127.0.0.1:8765/
三、PCB：先关闭原桌面 R7 或串口助手，在网页 IMU 页选真实 COM、波特率、从机地址，保存并连接。
四、PLC：如果需要状态读取，先运行 Install_PLC_Optional.cmd，按原本 R7 的 PLC IP 填写并连接。
五、WK：Windows 环境及厂家DLL位数正确后，连接双轴读取真实状态。
六、R7方案：网页可按 R7 原始函数验证温度/速率、保存草稿；不发温箱和电机控制指令。
七、离线模型：将原 R7 完整实验目录复制到 TiltSensorCalibration\native_web_data\imported_R7_experiments\ 下。
  网页可检查完整工况并调用原 R7 的 28 候选研发报告函数进行复算。
八、启动故障：看 TiltSensorCalibration\web_startup.log；双击 Check_R7_Web_Win11.cmd 检查环境。

版本边界（非常重要）：
已接入：真实 PCB / IMU 串口采集、16点/帧均值与原始CSV、UID、错误诊断；PLC PV/SP读取、WK真实状态读取；R7方案草稿与原版校验；12+12姿态清单；完成实验的离线28模型报告。
尚未接入网页控制：PLC 设温/SP写入、WK运动/回零/使能、ACC/GYRO自动标定的执行、R7自动温补/中止/恢复、自动斜坡控制。
因此该版本不等于原R7全部功能已经可由网页执行，也没有通过真实设备联合验收。项目内保留原R7桌面源码供参照，但Web运行不调用main.py。

安全：任何需要真实运动与温控的测试都必须现场有人值守且急停可用。关网页不是急停。
绝不要让两套上位机同时操作相同COM/PLC/WK。禁止R6旧检查点直接交给R7续做。

技术架构：HTML/CSS/JavaScript 前端 + Python标准库HTTP后端；无Node、无PySide6 Web运行依赖。
网页默认只绑定127.0.0.1。所有写操作必须在本机，并经过同源和会话令牌检查。
