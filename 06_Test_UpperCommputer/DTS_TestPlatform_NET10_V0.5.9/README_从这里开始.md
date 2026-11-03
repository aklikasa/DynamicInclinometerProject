> **当前版本 V0.5.6：** 请先阅读 `README_V056_从这里开始.md` 与 `docs/标定总目录与子文件夹规则.md`。标定文件支持**总目录递归搜索**；`CHANGELOG_V056.md` 记录最新改动。

# 动态倾角仪研发自动化测试平台 V0.5.4 —— 重建版

这是从此前 V0.5.3 完整工程中恢复并重新整理的 **.NET 10 / WPF / 纯 C# 源码**，不是可直接运行的 EXE 安装包。请**先编译，再启动**。

## 第一步：Windows 上验证

1. 解压到 `D:\DTS\TestPlatform`，不要直接在压缩包内打开工程。
2. 双击 `scripts\build_windows.cmd`。该脚本检查 .NET 10 SDK、还原依赖、编译 WPF、核实 EXE 路径并运行模块自检。详见 `docs\EXE_MISSING_FIX.md`。
3. 编译成功后打开 `DTS.TestPlatform.sln`，把 `Dts.Wpf` 设为启动项目，按 F5。
4. 如继续提示 EXE 不存在，直接将 `build_logs\last_build_debug.log` 第一条错误发回来；**不要发“EXE 不存在”作为唯一错误**。

## 保留的功能

- S0～S4 共 84 个编号；每编号独立测试模块 `.cs`；未实现的测试明确禁止执行。
- CT-05 独立 XAML 设置窗口、实际采样、结果和 Excel/HTML/JSON 报告逻辑。
- IMU：Modbus 实机 UID、六轴 FIFO、原始 int16 CSV、定时/手动停止。
- 2TD-600 和 2FDT600WK 原厂 x64 DLL 驱动；内/外轴独立操作、安全检查。
- 按 DTS 编号关联 ACC/Gyro 标定 JSON；原始 UID / 量程不明数据来源和标定文件哈希可追踪。
- 输出根目录、标定目录分别选择；UID 写入文件记录。

## 安全边界

源码调用真实设备，不生成假测量数据。但此版本**未在当前环境中完成 Windows .NET 10 编译、实体硬件联调或运动安全验收**。真实转台必须先人工检查机械限位、夹具、线缆、物理急停，不能让尚未验证的命令自动执行。

当固件返回 `ACC_FS=0 / GYRO_FS=0` 时，仅能确认原始计数，不能伪造 g/°/s；试算模式不能用于验收。

## 这一版相对于 V0.5.3 的构建修订

- 明确 WPF `UseAppHost=true`，Windows Debug 应生成 `Dts.TestPlatform.exe`。
- .NET 10 `System.IO.Ports` 的依赖锁定在稳定基线 `10.0.0`。
- 加入 Windows 编译日志收集、EXE 实际存在性校验和自检，一次定位真正的构建错误。
- 加入 `Properties/launchSettings.json` 项目启动配置。
- 保留之前的 UID / 设备通信 / 测试模块 / UI 代码，并未声称在此完成真实编译和设备调试。
