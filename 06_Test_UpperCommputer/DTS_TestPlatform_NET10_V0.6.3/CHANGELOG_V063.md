# V0.6.3 / 2026-11-03

- `MainWindow.xaml`: 全局目录区域缩短，旁边增加 IMU/2TD/2FDT 三张连接状态卡；测试按钮的 ItemsPanel 改为真正的两列 UniformGrid；2TD/2FDT 连接按钮标签简化；主 IMU 实时表格采用统一专业数据表样式。
- `App.xaml`: 新增三设备状态卡和统一 DataGrid 表格样式，卡片布局宽度不再使用可能引发换行的硬编码宽度。
- `ImuMonitorWindow.xaml`: 独立实时数据窗口同步应用同一表格样式。
- `MainWindow.xaml.cs`: 测试卡按实际可用宽度控制一/两列；实时反馈更新设备状态卡，2TD 仅有确认状态时亮绿灯，4 秒以上的过期反馈不再显示就绪。
- `scripts/check_sources.py`: 增加新版布局和表格资源的回归检查。

**本版仅修改界面/状态显示。不修改实际通讯/运动/使能/采集/标定算法。**
