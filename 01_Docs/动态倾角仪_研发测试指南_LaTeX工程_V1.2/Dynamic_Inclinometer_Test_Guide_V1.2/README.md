# 动态倾角仪研发测试指南 — LaTeX 工程 V1.2

**总标题（长期不变）**：动态倾角仪研发测试指南。**副标题**：分阶段测试项目总表与实施方案。

## 你要的使用方式

打开 `main.pdf`，从可点击目录找到当前研发阶段，先查看阶段总表，再按照测试编号阅读对应方案。后续阶段的测试编号与总表已经预留，具体操作步骤在设备条件和产品指标明确后补充。

| 阶段 | 当前文档深度 | 主要源文件 |
|---|---|---|
| S0 常温内参标定 | 工艺与检查总表、执行要点 | `sections/phase_S0_calibration.tex` |
| **S1 常温标定后验证** | **20 项详细方案（CT-00--CT-18 + CT-12A）** | `sections/05_overview.tex`、`sections/06_detailed_protocols.tex` |
| S2 全温及温补 | 全部候选项目总表、条件提示 | `sections/phase_S2_temperature.tex` |
| S3 动态及抗干扰 | 全部候选项目总表、条件提示 | `sections/phase_S3_dynamic.tex` |
| S4 环境、可靠性与批量 | 全部候选项目总表、条件提示 | `sections/phase_S4_reliability.tex` |

**Allan 方差在哪里？**：位于 **S1 测试总表 CT-12A** 和 **S1 逐项详细方案 CT-12A**，计算原理另见附录 A。CT-12 是短期静态噪声，CT-12A 是长时间 Allan 方差/偏差，适合估计 ARW、零偏不稳定性等随机噪声指标。S2、S4 可复用该测试方法做跨温度/跨时间对比。

## 编译

- 推荐 XeLaTeX，执行 **两遍**： `xelatex -interaction=nonstopmode -halt-on-error main.tex`。
- Windows / TeXstudio：主文件 `main.tex`，默认编译器 XeLaTeX；可运行 `build.bat`。
- macOS/Linux： `bash build.sh`。
- `xurl.sty` **不是强制依赖**。`sections/00_preamble.tex` 在缺少 `xurl` 时自动退回标准 `url`。此前 ctex/xeCJK 内核 release 版本差异通常是警告，不能直接编辑系统宏包解决。
- `templates/stage_master_test_register.csv` 是跨阶段总测试台账；`templates/CT12A_allan_record.csv` 是 Allan 专项模板。

## 质量与执行限制

- 本指南的 **S2--S4 是候选测试目录**，不意味着详细方案已经审批或现场执行。S0 是既有工艺归纳，不构成软件所有功能都已经现场验证的声明。
- 2TD-600 手册给出的角速率范围是运动能力，不是角速率计量精度保证；陀螺仪比例因子精度需要有溯源的速率基准。
- 当前使用单块 IMU PCB，不等于已经完成整机调平、全温、纯线性加速度、冲击和量产一致性检验。
- 已有软件阈值是试运行筛查，不等于最终产品精度验收限值。
- S1 的 Allan 方差测试需要连续长时间原始数据，温度、采样率、数据连续性和滤波链必须记录；不能直接拿短时平均数据估计长时间零偏不稳定性。

## 版本变化

- V1.0：S1 常温标定后测试规范初稿。
- V1.1：`xurl` 缺失时自动回退，增强兼容性。
- **V1.2：升级为跨阶段研发测试指南，S0--S4 各自独立章节；S1 保留原 CT 编号并新增 CT-12A Allan 专项；增加 S2--S4 测试总表及统一跨阶段 CSV 台账。**
