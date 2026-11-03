# V0.5.4 重新交付与构建诊断

- 基于用户前次 V0.5.3 源码重建全部项目。
- WPF 主程序明确 UseAppHost=true。
- System.IO.Ports 改用 .NET10 稳定初版依赖 10.0.0。
- 脚本编译、强制检查预期 EXE 是否存在，日志保存至 build_logs。
- 加入 Visual Studio 的 Project 启动配置和 EXE 缺失排查说明。
- UID 采集、转台驱动、84 项模块、CT-05 及报告逻辑保持。
- 当前环境无法运行 Windows .NET10 编译，Windows 生成结果需用户本机核对。
