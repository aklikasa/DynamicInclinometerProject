# CT-05 从静态角度检测工作台 V1.4 Python 的迁移核对

| Python V1.4 | C# V0.5 | 备注 |
|---|---|---|
| `app/core/scan_plan.py` | `CT_05_Algorithm.cs` | 74 点/小角度计划；可预览 |
| `app/core/calibration.py` | `CT_05_Result.cs` 中 `Ct05Calibration` | 校准文件校验、3×3矩阵校正、快照和SHA-256 |
| `app/core/measurement.py` | `CT_05_Algorithm.cs` | 3轴MAD筛选+均值、`atan2`、角差wrap；当前是对全部MCU样本聚合，Python采用两级帧均值，统计口径并非逐项完全相同 |
| `app/core/auto_scan.py` | `CT_05_Test.cs` | 外轴归零→内轴切换→外轴定位→稳态采集→逐点检查点 |
| `app/devices/turntable_driver.py` | `Dts.Devices/Turntables.cs` | P/Invoke 原厂DLL、内轴0/外轴2；软件限幅与状态检查 |
| `app/devices/turntable_worker.py` | `LiveTestHardware.cs` + `TestRunner` | 公共设备互斥、取消后软停车、连续读取反馈；原 Python 更完善的“安全断开/解除使能”状态机尚未完整迁移 |
| `app/devices/imu_protocol.py` | `Dts.Devices/SerialDevices.cs` | 实际Modbus读取；保留原始12字节UID |
| `app/core/report.py` | `CT_05_Report.cs` | JSON / CSV / HTML / XLSX；Excel字段样式与 Python 工作簿并非完全一致 |
| `app/ui/main_window.py` | `TestWindows/CT05/CT05Window.xaml` | 独立操作窗口，不阻塞主界面；安全条件双确认 |

源 Python V1.4 的完整外轴 -180 到 +180 计划会命令 180...350° 等真实位置。2TD 厂商绝对位置接口的跨周旋转方向与线缆运动必须完成实物验证。因此 C# 默认采用仅正角小幅、允许行程 0~30°，完整74点需现场手动批准后才能执行，**不能把原 Python 试验方案的可运行性等同于不同设备装夹状态下的机械安全**。

如需实现与 Python 结果严格一致的质控，应以同一批可追溯原始采样进行两端离线复算，对照 MAD剔除率、参考角单位、ACC符号及最终误差；未经对照不宣称数值完全相同。
