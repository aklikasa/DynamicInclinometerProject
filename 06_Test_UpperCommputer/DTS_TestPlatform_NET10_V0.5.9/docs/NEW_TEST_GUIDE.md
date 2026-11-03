> **V0.5 提示：本页为旧版资料；新增带独立 XAML、算法、结果、报告的测试，请优先阅读 `docs/ADDING_NEW_TEST_V05.md`。**

# 新增/完善测试：操作指南（V0.4）

## 先看结论

- **已有编号（84 项中的一项）**：打开 `src/Dts.Tests/S*/<编号>_Test.cs`，实现该类，改成 `IsExecutable => true`，**重新生成解决方案**，启动后原按钮自动可用；不需要在 `MainWindow.xaml.cs` 注册，也不需要新建按钮。
- **新测试编号**：把 `docs/templates/NewTestModule.cs.txt` 复制到对应 `S0`～`S4` 目录并改名 `.cs`，实现唯一 `TestId`、`Stage`、`Name`、`Purpose`、`Procedure`；重新生成解决方案，新按钮自动出现在该阶段，即使未修改 `assets/tests.json`。建议同时把编号写进 JSON/测试规范以便长期追溯。
- **不想重新编译主 WPF**：单独创建一个引用 `Dts.TestEngine` 的 C# 类库，将经过审核的 `*.dll` 放到应用输出目录的 `plugins/` 再重启，程序会自动发现。`.cs` 原始源码**不能**像脚本一样直接拖入后运行。

## 目录设计

```text
src/
  Dts.Wpf/           主界面和动态按钮生成（不写单项测试逻辑）
  Dts.Core/          UID / 原始 IMU 数据模型 / 测试元数据
  Dts.Devices/       串口、厂家 DLL、原始数据采集、硬件服务适配
  Dts.TestEngine/    ITestModule、执行上下文、注册表、互斥、审计
  Dts.Tests/         84 个独立测试 .cs（按 S0～S4 分类）
  Dts.SelfTest/      模块发现、编号、状态自动自检
```

## 开发一个真实测试的必要步骤

1. 确定 **测试编号与科学评价指标**，在对应 `.cs` 文件内实现 `ExecuteAsync`。
2. 通过 `context.Hardware` 获取已审核的硬件操作服务。现在的接口提供真实 IMU 静态采集；**多位置转台自动运动、温箱控制、标定矩阵求解还没有完整测试级服务**。这些新能力必须先在 `Dts.Devices` + `ITestHardware` 中安全实现/验证，不能仅补一个测试文件就直接进行危险运动。
3. 对会运动的测试，必须接入独立的安全调度器，执行权限、机械限位、到位反馈、超时和急停策略检查。禁止绕过公共设备驱动直接 P/Invoke 厂家 DLL。
4. 测试结束保存原始 UID（12 字节）、显示 DTS 编号、测试编号、采样条件、参考量、版本、原始 CSV、分析 JSON 和日志。
5. 没有完整验收判据/不确定度时，返回 `TestOutcome.DiagnosticOnly` 或 `PendingAcceptance`，禁止填造 `Passed`。
6. 运行 `scripts/build_windows.ps1` 的构建和自检，再在现场人工监督下验证。

## 参考实现

- `src/Dts.Tests/S0/S0_04_Test.cs`：真实 Gyro 原始零速采集。
- `src/Dts.Tests/S1/CT_09_Test.cs`：真实 Gyro 单姿态原始零速诊断子项。
- `src/Dts.Tests/S1/CT_12_Test.cs`：真实六轴短期噪声统计子项。

它们均**不**是完整的标定后精度验收，返回 `DiagnosticOnly`。

## 插件与安全

`TestModuleRegistry` 先加载内置 `Dts.Tests`，再加载 `plugins/*.dll`。若插件模块编号与占位类相同，**只有插件声明可执行而占位类不可执行时**才可替换；如果已有可执行模块，遇到同编号插件会保留现有模块并记录警告。

插件与主程序运行在同一个进程中，**不是沙箱**。只使用内部经过代码审查和签名/校验的 DLL。若插件需要额外依赖，须同时设计依赖解析和版本匹配，当前示例主要面向无额外依赖的模块。

## 常见误区

- `IsExecutable = true` 仅表明代码允许调用，不代表测试已实机验收。
- JSON 元数据不代表已经实现自动测试；没有执行类时只能查看方案。
- 直接复制 `.cs` 文件并不自动变成可执行程序集；必须**编译**。复制编译好的 DLL 并重启才支持免重编译扩展。
- 新硬件协议、新分析算子、全自动转台动作可能需要在共享服务层增补代码，不保证所有测试都能只改一个文件。
