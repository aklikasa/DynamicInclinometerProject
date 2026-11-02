# 动态倾角仪研发自动化测试平台 V0.5.1 (.NET 10 / WPF / C#)

## V0.5.1 编译修复（针对 CT-05 窗口）

- 修复 `src/Dts.Wpf/TestWindows/CT05/CT05Window.xaml` 第20、33、39行三个 `CheckBox` 误用 `TextWrapping` 导致的 WPF XAML 编译失败。
- 保留复选框原来的 `x:Name`、勾选状态读取和安全确认逻辑；将长文案改为子 `TextBlock` 来实现换行。
- `scripts/check_sources.py` 新增检查：阻止 `CheckBox` 等不支持的控件直接使用 `TextWrapping`。
- 如果 Visual Studio 提示 `Dts.TestPlatform.exe` 不存在，请先清理并重新生成；这是前面 XAML 编译失败的连带结果。
- 本次修复未更改 IMU、2TD-600、2FDT600WK 协议和运动安全逻辑。Windows .NET 10 构建仍需要在本机完成。

## 本版定位

在 V0.4 84 个模块的基础上增加：**项目级报告根目录、每个测试按钮弹出独立测试子窗口、首个可运行的 CT-05 多点静态角度检测、独立轴相对运动控制**。

本工程使用真实厂家 DLL、真实 IMU Modbus，不生成模拟数据；但**本交付尚未在 Windows 下编译、也尚未接入你的真实机械设备完成联调**。它是需要现场构建和分步骤安全验收的开发版本，不能被称为已完成仪器验收。

### 一、现在是什么结构？

- `Dts.Wpf`：主界面，阶段按钮及独立测试窗口。
- `Dts.TestEngine`：`ITestModule` 接口、真实设备抽象、任务互斥和审计。
- `Dts.Tests`：84 项各有独立的 `*_Test.cs`；当前四项有真实执行入口：S0-04、CT-05、CT-09、CT-12，其中 S0-04/CT-09/CT-12 仅原始采集或诊断子项。
- `Dts.Devices`：IMU Modbus（UID/六轴）、2TD-600/2FDT600WK DLL、实际采样、转台状态与指令。
- `assets/tests.json`：阶段/编号/目的/步骤/优先级目录。
- `docs`：新增测试模块规则、测试窗体规则、安全、迁移说明。

### 二、使用方式

1. 安装 Windows x64、支持 .NET 10 的 Visual Studio 和 .NET 10 SDK。
2. 打开 `DTS.TestPlatform.sln`，把 `Dts.Wpf` 设为启动项目。
3. `scripts/build_windows.cmd` 执行实际编译与模块自检，先解决所有编译警告/错误。
4. 在主界面顶部选择报告根目录；以后默认记住上次的可用目录。
5. 自动扫描设备 COM，连接 IMU、读取真实 12 字节 UID；连接 2TD 双轴转台并观察实际反馈。
6. 点击 S1 的 `CT-05` 按钮：出现独立的 CT-05 窗口，导入当前设备的 ACC 标定 JSON，设定采样时间、速度、运动范围、姿态计划。
7. 先执行**静态只读状态和手动低速运动现场验证**（无需 CT-05 运动），核实编码器参考位置、X/Y 轴方向、物理急停、夹具、线缆、限位。
8. 等试验负责人批准轨迹后，勾选安全条件，双重确认启动。不可在无人监管或机械安全条件不明时运行。

### 三、相对运动语义

用户填写内轴 `+50°`、`10°/s`，即**先读取实际内轴反馈位置，再将 `当前位置 + 50°` 换算为绝对目标位置**，使用原厂 `SetAxisPosition` 发指令；不是把 `50°` 直接当绝对目标。

- 2TD 手动软件角速度范围 `(0,60]°/s`；CT-05 自动扫描限定 `(0,5]°/s`。
- 目前每次相对运动 `|Δθ|≤90°`，不允许在 0/360° 边界做未经厂家证明的绕圈或反向运动。
- `SetAxisPosition` 的“绝对位置模式”来自提供的原 Python 驱动和厂商接口。跨周边界的运动方向/机械绕转是否正确，必须实机确认。
- 两轴分别有使能、解除、运行、停止、实时位置、使能、到位状态。选择轴归零是**绝对零位 0°**，不是伺服系统找机械零点；2TD 双轴归零时先外轴后内轴并等待到位。2FDT 状态码含义不明确，暂不允许未验证到位的双轴连续自动归零。

### 四、CT-05 真正实现了哪些工作？

参考用户上传的 PySide6 `静态角度检测工作台 V1.4`：

- ACC JSON 的 `raw_accel_bias_g` 与 `raw_to_platform_matrix` 解析、校验与快照，SHA256 保存。
- 生成 8 点正角小幅、14 点对称小幅或 Python 同型 74 点全圈计划（Y 内轴 0°、X 内轴 90°；外轴从 -180° 到 +180°，步长 10°），计划可预览。
- 逐点单轴定位、编码器实际位置回读、连续到位判断；内轴变动前让外轴先回到 0°。
- 稳定等待、逐点真实 Modbus 数据采集，原始点 CSV、MAD 异常值剔除、ACC 校准与 `atan2` 角度，逐点参考/测量/误差/模长。
- 逐点 JSON 检查点；完成/取消/异常时输出**汇总 JSON、逐点 CSV、Excel `.xlsx`、HTML 报告**；每项都包含 UID、校准文件 SHA256 和可追溯的逐点 CSV 路径。
- 报告有整体和 X/Y 两轴 Bias、RMSE、最大误差与实测趋势，不在没有参考不确定度/产品判据时虚报 PASS。
- 取消或异常时尝试两个轴的软件停车并核实连续实际速度反馈；失败则报警要求人工物理急停。**软件停车不替代硬件急停**。

默认行程 **[0°,30°]**，所以全圈以及存在负角（映射到 350°等）的计划都不能直接运行；必须由现场负责人批准机械行程、实测旋转方向和电缆条件之后才允许修改参数。此限制是安全设计，不是遗漏功能。

### 五、CT-05 文件结构

```text
src/Dts.Tests/S1/CT_05_Test.cs             // 真正执行流程
src/Dts.Tests/S1/CT05/CT_05_Algorithm.cs  // 计划、MAD、校准角度、统计
src/Dts.Tests/S1/CT05/CT_05_Result.cs     // 设置和结果模型、标定参数加载
src/Dts.Tests/S1/CT05/CT_05_Report.cs     // JSON/CSV/HTML/XLSX
src/Dts.Wpf/TestWindows/CT05/CT05Window.xaml
src/Dts.Wpf/TestWindows/CT05/CT05Window.xaml.cs
```

不同编号可复用公共设备驱动和数学服务，因此不一定**每项都强制**拆四个文件，但建议按这套模板写。新增独立窗口通过 `[TestWindowFor("编号")]` 属性自动识别；没有专用 XAML 的测试会打开标准设置子窗口。

### 六、报告保存目录

由主界面按钮选择，保存路径写到本地用户配置 `%LOCALAPPDATA%/DTS_TestPlatform/output_root.txt`。每次运行写：

```text
<选定根目录>/DTSxxxxxx_<原始12字节UID>/yyyyMMdd_HHmmss_fff_CT-05/
    calibration_used.json
    point_001_Y.csv ...
    checkpoint.json
    CT-05_result.json
    CT-05_points.csv
    CT-05_report.html
    CT-05_report.xlsx
```

HTML 可通过系统浏览器“打印为 PDF”，但本版**没有内置可靠的 PDF 生成器**。Excel 是独立 C# OOXML 输出，无须 Python / Excel 进程 / NuGet 大型库。

### 七、已知限制 / 待现场处理

- 本环境无法执行 .NET 10 Windows WPF 编译和现场联调；**请先运行 `scripts/build_windows.cmd`**。
- 2TD 厂商说明书未给出速率计量精度，不能用其指令转速直接宣称 Gyro 绝对准确度。
- 2FDT `GetStateInfo.state` 的各位含义未由供应商证明；不能据此假称“已到位/已使能”。该机型真实状态/控制接入，但本版 CT-05 只针对 2TD。
- WPF 不是安全控制器，任何软件动作都依赖现场硬件限位、物理急停和操作规程。
- CT-05 在硬件读数链/坐标系和安装方向完成对齐确认前，只可做有人员监管的研发试验。
- 84 项中其余 80 项仍是安全占位模块，不能产生任何模拟的 PASS。
