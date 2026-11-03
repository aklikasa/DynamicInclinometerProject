# V0.5.8 构建状态

- 当前环境：Linux；未安装 dotnet 10 SDK，无法实际运行 Windows WPF 及实体设备。
- 已执行：`python scripts/check_sources.py`（PASS）。
- Windows 现场编译：在解压后的工程根目录执行 `scripts\build_windows.cmd`，随后运行 `Dts.SelfTest`，再启动 WPF。
- 需要现场验证：IMU UID、FS/ODR、SENSOR_OK 状态位、原始/常温/全温三模式表格与 CSV 一致性、转台按钮布局和机械安全。
- 不包含模拟硬件数据；原厂两套转台 DLL 完整保留。
