# 工程模块与依赖关系

```text
                     Dts.Wpf (Windows/.NET 10)
                       │             │
                Dts.TestEngine    Dts.Tests (84 个 .cs)
                       │             │
                       └──── Dts.Core ────┐
                                          │
               Dts.Devices (真实串口、原厂转台 DLL)
                   + LiveTestHardware 适配层
```

依赖为：`Dts.Tests → Dts.TestEngine → Dts.Core`，`Dts.Devices → Dts.TestEngine / Dts.Core`，`Dts.Wpf → Dts.Tests / Dts.TestEngine / Dts.Devices / Dts.Core`。

`MainWindow` 只负责设备 UI 和启动 `TestRunner`，不再维护 `RealStaticTests` 的硬编码集合。`TestModuleRegistry` 会反射发现每个实现 `ITestModule` 的公开、可无参构造类。原有 84 项测试信息仍由 `assets/tests.json` 定义。对于新的测试编号，如果代码中提供元数据，界面会自动增加按钮。

`TestRunner` 实施单任务互斥、编号匹配、取消传递、异常处理、采集证据完整性检查，并在采集目录输出 `test_execution.json`。原始 UID 必须是 24 位 hex 对应 12 字节硬件 UID。

**边界**：现有真实串口/双转台 DLL 代码沿用 V0.3，未在本交付环境完成实机联调；模块化改造不扩大自动运动权限。当前仅静态采集三个子功能接入真实测试模块，其余安全占位。真实转台运动仍需在独立设备操作页二次确认。
