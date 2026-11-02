# Dynamic Inclinometer | 原生 WPF GPU 液态玻璃监测版

这是基于用户上传的 `IMU_2TD600_FINAL_ABS_REL_Full_Source.zip` **直接修改、保留原项目名称**的完整工程，不是液态玻璃演示，也不是网页。

## 这次有什么变化

- 主窗口和转台手动控制的主要卡片换为 `LiquidGlassPane : ContentControl`，由 WPF/Direct3D9 PixelShader `ps_3_0` 对背景 `LiquidScene` 做实时扭曲采样、边缘色散和鼠标高光。
- 背景只保留深蓝渐变、光晕、轻微细线，不含任何 `LIQUID GLASS` 巨型背景文字。
- 顶部加入**关闭 GPU 折射 / 开启 GPU 折射**和**折射强度**，更新频率限制为 20 FPS。关闭时保留透光玻璃边框、半透明背景，但关闭 HLSL 动画。
- 主导航只留下**实时监测**、**转台手动控制**。**自动测试的标签页、参数面板、执行按钮、报告入口都从 XAML 删除**。
- **保留**原先 ACC/GYRO 校准导入、设备号、1500000 baud Modbus IMU 采集、ESKF、ABS/REL 参考零点、Roll/Pitch 曲线、三维姿态和手动 2TD-600 两轴控制。
- 为减少原自动测试代码牵连引发的编译风险，旧的自动测试辅助算法源码暂留（不在 UI 出现），自动测试入口另有硬禁用。后续如需彻底删除底层模块须另做单元测试/实机验收。
- 设备层、ESKF 数值实现和 2TD600.dll **未做修改**，不改变真实运动速率/方向/联动安全约束。

## Windows 编译与启动

前提：Windows + Visual Studio 的 .NET 桌面开发工作负载 + .NET 10 SDK。

1. 把本工程解压到新的、自己信任的本地目录，**不要覆盖之前可运行的原工程**。
2. 打开 `DynamicInclinometer.slnx`，将 `DynamicInclinometer.App` 设为启动项目。
3. 选择 Debug / x64 或 AnyCPU，点击“重新生成解决方案”。HLSL 已作为 `EmbeddedResource` 嵌入 EXE，不再在编译期调用第二个项目。启动后才使用 Windows 自带的 `d3dcompiler_47.dll` 在内存里生成 `ps_3_0`；如果运行环境不支持，软件自动显示不带 GPU 折射的普通玻璃。
4. 若显卡不支持 ps_3_0 或动画性能不足，启动后点击 **关闭 GPU 折射**。
5. 先只验证界面、ABS/REL 和采集，不要立即执行真实转台运动。

也可以在工程根目录的 PowerShell 执行 `构建并启动_GPU版.ps1`。

## 重要说明

本环境只能做 XAML/源码/资源映射静态检查与 ZIP CRC 检查，**无法在 Windows 上编译**，也没有真机验证 GPU、IMU 和转台的实际运行。静态检查不是已编译、已测试、已认证的软件。

实际使用若出现 `0x800711C7`，是 Windows 拒绝加载 DLL 的安全策略异常；不要绕过 Windows 安全策略。参考原来的 CodeIntegrity 诊断记录，旧版请保留。

## 模式说明

- ABS：重力水平参考 Roll/Pitch，ESKF 原始输出保持不变。
- REL：点击“设置当前姿态为相对零点”后，显示相对参考四元数计算的 Roll/Pitch；切换会同步作用于实时读数、曲线与三维模型。
- 采集会继续生成 `raw_processed.csv` 和 `display_processed.csv`，分别保存 ABS 原始融合输出和当时用户看到的 ABS/REL 显示；**不包含自动测试按钮**。

## 技术结构

- `src/DynamicInclinometer.App/Controls/LiquidGlassPane.cs`
- `src/DynamicInclinometer.App/Effects/LiquidGlassEffect.cs`
- `src/DynamicInclinometer.App/Effects/LiquidGlass.hlsl`
- `src/DynamicInclinometer.App/Effects/RuntimeShaderCompiler.cs`：在主进程里调用 `D3DCompile`，生成内存着色器并支持安全回退（Windows 专用）
- `src/DynamicInclinometer.App/App.xaml`：`LiquidGlassCard` ContentControl 模板，避免 `x:Name` 作用域冲突
