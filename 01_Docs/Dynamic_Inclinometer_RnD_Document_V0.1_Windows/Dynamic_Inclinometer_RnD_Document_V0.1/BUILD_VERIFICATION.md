# 构建验证记录

- 编译器：当前 Linux 环境 TeX Live / XeLaTeX。
- 执行：`xelatex -interaction=nonstopmode -halt-on-error -file-line-error main.tex`，连续多遍直到目录与交叉引用稳定。
- 验证结果：XeLaTeX 返回码 0；已生成 PDF（36 页）；最后一遍编译记录中 0 处 `Overfull/Underfull`、0 处 `Infinite glue shrinkage`、0 处 `undefined references`。
- 已渲染检查封面、目录、设备照片和表格页面。
- **限制**：未在用户 Windows / MiKTeX 环境做编译测试。用户机器中 `requested release 2026/06/01` 仍可能存在，需更新本机宏包/内核版本以消除。
- 设备与工艺：文档反映研发代码和手册，并不声明完成转台/温箱实机验收。
