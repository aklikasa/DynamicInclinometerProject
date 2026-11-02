# 动态倾角仪研发技术文档 V0.1（模块化 LaTeX）

这是整个动态倾角仪项目的**长期研发文档母版**。当前正文仅详细覆盖常温 ACC/GYRO 内参标定（A/B/C）和 2FDT600WK + PLC 自动温补。噪声分析、姿态融合、固件和整机、量产、塔筒现场只保留研发路线，不写成已经完成。

## 文件结构

- `main.tex`：唯一编译入口，只有 `\input` 章节组织。
- `config/preamble.tex`：跨 Windows/Linux 字体回退、公式、图表、版式配置。
- `frontmatter/`：封面、文档控制、项目总论与研发路线。
- `chapters/01_ambient/`：常温标定 5 个独立章节。
- `chapters/02_thermal/`：自动温补 5 个独立章节。
- `tables/`：可编辑的工况和参数表。
- `figures/`：可编辑 TikZ 流程图/架构图。
- `assets/`：设备厂家说明书配图；不分发字体文件。
- `appendices/`：来源、缩写、技术接口约束。
- `main.pdf`：编译好的 PDF。

## Windows 编译（TeXstudio / MiKTeX / TeX Live）

1. 解压到纯英文目录，例如 `C:\IMU_Doc\`。
2. 使用 XeLaTeX 打开并编译唯一主文件 `main.tex`。
3. 或运行 `build_windows.bat`，会连编两遍并保存 `build_pass*.log`。
4. 禁止使用 pdfLaTeX；不要将 `config/preamble.tex` 当作主文件编译。
5. `requested release 2026/06/01 ... only release 2025-11-01` 来自**本机 LaTeX 内核与 ctex/xeCJK 安装版本不一致**，并非本文档编译配置造成；需要更新/统一 MiKTeX 或 TeX Live 发行版。新项目源码无法替用户更新系统宏包。

## 编写/验收原则

- 必须区别“源码工况”“设备手册标称”“研发建议”“未经核准实测示例”。
- 自动温补代码仍需真实 PLC、2FDT 双轴、IMU 实机联动验收。
- 正式生产门限、整机动态倾角精度和温补固件接口尚未完成审定。
- 新阶段完成后再增设独立目录并引用实验报告，而非提前填写结论。

## 文件名规范

ZIP、LaTeX 相对路径使用英文，正文使用中文。建议长期固定文档编号 `DI-RND-TECH-001`。
