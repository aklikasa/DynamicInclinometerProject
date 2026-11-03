# 构建状态 — V0.6.0

- [x] XAML/XML 解析
- [x] 原有 84 测试模块静态回归检查
- [x] 新实时数据窗口事件检查与资源验证
- [x] DPI manifest XML 解析与项目文件引用检查
- [ ] Windows .NET 10 实际编译（需用户现场执行）
- [ ] 1366×768/1920×1080 和 100/125/150% 缩放可见性实测
- [ ] IMU/2TD/2FDT 实机验证

Windows执行：`scripts\build_windows.cmd`。若失败请提供 `build_logs\last_build_debug.log` 第一条错误。
