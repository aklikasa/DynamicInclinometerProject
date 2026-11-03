# V0.5.5 — Dts.Devices 编译错误修复

- 修复 `src/Dts.Devices/StaticDiagnostics.cs` 第 73 行匿名对象成员使用集合表达式 `physical_units=[...]` 时的 CS9176 错误。
- 该处现使用显式 `new string[] { ... }`，不影响统计逻辑或 JSON 输出数据。
- 给 `scripts/check_sources.py` 添加回归检测。
- 不修改 IMU、2TD-600、2FDT600WK 的通信协议和运动指令。
- 注意：此环境缺少 Windows/.NET 10 SDK；静态检查通过**不等于** Windows 完整编译通过。
