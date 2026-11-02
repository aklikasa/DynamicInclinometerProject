# Windows 首次启动与现场检查单

## 编译

1. 确认安装 .NET 10 SDK、Visual Studio 的「.NET 桌面开发」工作负载。
2. 打开 `DTS.TestPlatform.sln`，右键 `Dts.Wpf` → 设为启动项目。
3. 在工程根目录执行 `scripts/build_windows.ps1`，检查第一条实际编译错误而非后续缺 DLL 错误。
4. F5 启动，确认没有 `XamlParseException`、`FileNotFoundException`。
5. 在不接设备的情况下逐阶段点击 84 个按钮：未开发的条目只应显示方案，不得产生 CSV 或 PASS。

## 真实硬件

1. 关闭旧 Python 上位机和串口调试助手，单独扫描 COM。发现端口与通过设备身份/状态核验是两个不同步骤。
2. 只连接 IMU，核对 12 字节 UID 和 PCB/DTS 短号；拔掉硬件后重测，应报告真实异常。
3. 静置固定，选 S0-04，10 秒先采集烟雾测试（调整采样秒数）。确认 `imu_raw.csv` 含真实量程、ODR 与非模拟标志。
4. 再对 CT-09、CT-12 做现场人工监督采样：有 `static_diagnostics.json`，它的 `evaluation` 必须是 `NO_PRODUCT_PASS_FAIL`。
5. 仅连接一台转台，核对实测内/外轴角度和厂家原上位机一致。扫描过程中不可产生使能/运动指令。
6. 不要在未经现场限位、硬件急停、夹具与安全操作审核前开启转台运动。

## 常见启动错误

- 报错 `不能启动具有类库输出类型的项目`：应将 `Dts.Wpf` 设为启动项目。
- 报错 `XamlParseException`：截取完整内部异常与行号。静态 XML 成功不代表 WPF 类型转换完全成功。
- 报错 `找不到 2TD600.dll`：检查构建输出目录下 x64 厂家 DLL 和程序位数。
- 报错无法识别串口：先确认真实端口和主动状态协议，不允许未经验证盲发运动指令。
