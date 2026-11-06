# V0.6.7.1：VS 编译错误 CS0136 修复

针对 V0.6.7 的 `src/Dts.Devices/SelectedImuFrame.cs` 第 55 行变量重名错误：

- Raw 分支的 `string status` 更名为 `string rawStatus`，对应 `Make()` 参数同步更改。
- 局部函数 `Missing(string status)` 的形参更名为 `reason`，防止与方法内的 `status` 混淆。
- 未改动原始 int16 采集、标定矩阵、Gyro 2000 dps 历史换算系数、CT-05 或 2TD 运动逻辑。

## 使用

1. 已有 V0.6.7 时，把补丁中 `src/Dts.Devices/SelectedImuFrame.cs` 覆盖到工程相同相对路径。
2. Visual Studio：**生成 → 清理解决方案 → 重新生成解决方案**。
3. 检查 `Dts.Devices` 成功生成，再以 `Dts.Wpf` 为启动项目运行。
4. 如仍有编译错误，取**重新生成后第一条** `CS****`/`MC****` 错误；后续的 `CS0006` 和 EXE 不存在通常是级联错误。

## 检查状态

已执行源码级检查，但运行环境缺少 Windows/.NET 10 SDK，不能声明真正编译通过或实机验证。
