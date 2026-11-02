# Visual Studio 报错：GeneratedMSBuildEditorConfig.editorconfig 路径不存在

**根本原因：原目录层级过深，自动生成文件路径达 264 字符。** 由于 Windows/MSBuild 某些操作仍受到约 260 字符限制，导致 Infrastructure 项目编译失败。`DynamicInclinometer.Infrastructure.dll` 缺失只是连锁错误，并非 DLL 源码丢失。

## 最简单解决办法（推荐）

1. 备份你之前能够运行的旧版本，关闭 Visual Studio 当前解决方案。
2. 将本 ZIP 直接解压到 **`D:\` 根目录**，应该得到 **`D:\IMU\DynamicInclinometer.slnx`**（文件夹只有一层、名字为 IMU）。不建议在原来的 `动态倾角仪研发\...` 目录里再套一个长文件夹。
3. 在 `D:\IMU` 中双击 `DynamicInclinometer.slnx`，确认 Visual Studio 的路径指向新目录。
4. 选 Debug / Any CPU，然后 **生成 → 重新生成解决方案**。不要在编译成功前按 F5。
5. 如果已经在深目录生成过 `bin` / `obj`，在 **新解压目录** 运行 `dotnet clean DynamicInclinometer.slnx` 再 `dotnet build DynamicInclinometer.slnx -c Debug`。本 ZIP 本身不包含旧的 bin / obj。

本版全部源码仍与上一版连接即监测 / 手动开始停止采集 / ODR 显示版本一致；只缩短解压后的根目录名称并增加路径预检。**没有擅自修改 IMU 协议、ESKF、转台驱动、标定参数、运动控制。**

## 验证路径长度

Windows PowerShell 在工程根目录执行：

```powershell
.\tools\检查路径长度.ps1
.\Windows_只编译验证_不启动转台.ps1
```

第一个脚本只计算路径，不修改文件或系统设置；第二个脚本仅编译，不启动串口/转台。

## 如果短目录仍然编译失败

请从 VS “输出 → 生成”复制**第一条 error**（而不是下游缺少元数据 DLL 的错误），并同时提供：

```powershell
dotnet --info
dotnet build .\src\DynamicInclinometer.Infrastructure\DynamicInclinometer.Infrastructure.csproj -c Debug -v:minimal
```

**本环境没有 Windows WPF 编译器，未在 Windows 上实际完成编译测试。**
