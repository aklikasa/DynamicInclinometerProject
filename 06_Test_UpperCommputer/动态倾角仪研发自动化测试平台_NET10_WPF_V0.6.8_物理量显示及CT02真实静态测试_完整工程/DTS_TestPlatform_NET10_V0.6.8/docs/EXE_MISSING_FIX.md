# Visual Studio 提示 Dts.TestPlatform.exe 不存在：快速排查

这个提示只是 **程序文件尚未生成**，并不提供真正的编译错误。不要手动复制别的 DLL 或改成启动 `Dts.Core`。

## 最可靠的做法

1. 将本压缩包解压到**短、无空格**路径，例如 `D:\DTS\TestPlatform`。不要把多个版本压缩包叠加在旧工程中。
2. 先确认 Visual Studio 已安装 **.NET 10 SDK**、**.NET 桌面开发工作负载**，而不是只有 Runtime。
3. 双击 `scripts\build_windows.cmd`；它实际执行 restore/build，再**检查 EXE 确实存在**，然后运行 84 项模块自检。
4. 如果失败，打开 `build_logs\last_build_debug.log`，找**第一条 error** 或 `CS****` / `MC****` / `NU****`；不要只发“exe 不存在”。
5. 如果成功，打开 `DTS.TestPlatform.sln`，在解决方案资源管理器右键 `Dts.Wpf` → 设置为启动项目。配置 Debug、启动配置 `Dts.TestPlatform (Project)`，按 F5。
6. 如果 VS 保留旧启动路径：退出 VS，删除本工程的 `.vs` 目录、`src\Dts.Wpf\bin`、`src\Dts.Wpf\obj`（可由 `dotnet clean` 代替），重开 `.sln`。

标准输出路径：`src\Dts.Wpf\bin\Debug\net10.0-windows\Dts.TestPlatform.exe`。

**重要：** 本源码当前只经过静态校验；我们无法在此 Linux 环境运行 Windows WPF。`build_windows.cmd` 在你的 Windows 电脑上才是实际编译验收。
