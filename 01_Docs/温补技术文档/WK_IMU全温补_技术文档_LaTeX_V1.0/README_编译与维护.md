# WK 双轴转台六轴IMU全温度补偿技术文档（LaTeX项目）

本文档基于用户提供的 **R10完整工程** 源码及 **2026-11-10的原始实验运行日志**，采用中文 XeLaTeX / `ctexbook` 排版，数学公式用 amsmath，示意图使用可编辑的 TikZ / PGFPlots（**没有依赖外部的图片文件**）。

## 如何编译

1. 推荐使用 **TeX Live 2024及以上**，包含 `ctex`、`fontspec`、`tikz`、`pgfplots`、`tcolorbox` 等宏包。
2. 字体：`Noto Serif CJK SC`、`Noto Sans CJK SC`、`Noto Sans Mono CJK SC`、`Liberation Serif`、`Liberation Sans`、`DejaVu Sans Mono`。如Windows电脑没有这些字体，请自行把 `main.tex` 头部的 `setmainfont / setCJKmainfont` 替换成现有字体。**无需从此压缩包下载字体。**
3. 进入此文件夹，在终端执行：

   ```bash
   xelatex -interaction=nonstopmode -halt-on-error main.tex
   xelatex -interaction=nonstopmode -halt-on-error main.tex
   ```

   Windows可双击 `编译文档_Windows.bat`；macOS / Linux可运行 `bash build.sh`。

## 工程结构

- `main.tex` — 完整正文、公式、表格、参考文献及维护规则。
- `figures/*.tex` — **10张可编辑示意图的源代码**。
- `evidence/2026-11-10_实验原始运行日志.md` — 用户提供的原始实验日志，用作技术证据保留；并非实验已完成的证明。
- `main.pdf` — 本次XeLaTeX编译出的便于审阅的PDF。
- `SHA256SUMS.txt` — 出版时的源文件校验摘要。

## 内容重要限制

- 设备接口是 **2FDT600WK**，当前没有这台设备对应的独立机械计量证书。因此M0~M3只能叫 **等效几何辨识**，不可写成“已经校正真实机械误差”。
- 本项目采用温箱PV准入、热浸以及**每工况有效帧的芯片均温**；不是逐帧直接入温度最小二乘。
- 所有两次升降温完整时，四趟联合训练，而不是四组系数平均；目前没有自动实现“第一循环训练，第二循环完全不参与选型的最终独立检验”。
- 2026-11-10的低温实验因PLC状态异常中止，未形成完整的2次循环产品可放行结果。
- 产品级六轴轴向/固件一致性/融合动态倾角与对标精度，尚需实机独立验收。

## 版本维护建议

将这份文档放入你们自己的代码版本库；每次更新转台几何定义、温度自变量、拟合候选、温控状态机和固件变换顺序时，同步修订正文、维护记录、源码SHA与实机测试结论。建议把研究系数和获批准的生产系数分开管理。
