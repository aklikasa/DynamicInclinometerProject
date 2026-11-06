# V0.5.5 使用说明

这版针对 Visual Studio 的 `集合表达式没有目标类型`（CS9176）错误。

## 只替换一个文件

将 `src/Dts.Devices/StaticDiagnostics.cs` 覆盖旧工程中相同路径的文件，然后清理/重新生成解决方案。

## 使用完整包

1. 解压 V0.5.5 到独立新目录，避免混用旧版 `obj`/`bin`。
2. 打开 `DTS.TestPlatform.sln`，将 `Dts.Wpf` 设为启动项目。
3. 在项目根目录运行 `scripts\build_windows.cmd`，确认生成 `src\Dts.Wpf\bin\Debug\net10.0-windows\Dts.TestPlatform.exe`。
4. 如果还有报错，先看 `build_logs\last_build_debug.log` 中第一条 `error CSxxxx`，不要只看 DLL 缺失报错。

此修复只改变匿名对象中 `physical_units` 的数组构造语法，不改变硬件操作。
