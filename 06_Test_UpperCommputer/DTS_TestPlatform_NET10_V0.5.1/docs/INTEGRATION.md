> **V0.5 提示：本页为旧版资料；新增带独立 XAML、算法、结果、报告的测试，请优先阅读 `docs/ADDING_NEW_TEST_V05.md`。**

# 84 项测试集成接口（V0.4）

请参照 [ARCHITECTURE.md](ARCHITECTURE.md) 了解模块依赖，以及 [NEW_TEST_GUIDE.md](NEW_TEST_GUIDE.md) 查看如何用一个 `.cs` 文件接入测试。

已有 `Dts.Tests`、`Dts.TestEngine`、自动发现和安全占位；不是 V0.3 的待建设结构。

现有三项真实采集子功能：S0-04、CT-09、CT-12，属于诊断子项而非完整合格判定。

尚未完成：ACC/Gyro 全矩阵标定、两类转台自动化工况编排安全联锁、温箱 PLC 控制、全温补偿、Allan 专项、动态频响完整测试、产品级验收判据。新增相关测试时需先在共享硬件/算法服务中实现必要能力。
