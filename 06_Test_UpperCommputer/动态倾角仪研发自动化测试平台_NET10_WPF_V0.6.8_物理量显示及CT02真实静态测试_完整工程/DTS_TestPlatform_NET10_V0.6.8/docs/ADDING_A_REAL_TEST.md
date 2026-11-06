> **V0.5 提示：本页为旧版资料；新增带独立 XAML、算法、结果、报告的测试，请优先阅读 `docs/ADDING_NEW_TEST_V05.md`。**

# 如何接入真实测试（V0.4）

本文件在 V0.4 已合并到 [NEW_TEST_GUIDE.md](NEW_TEST_GUIDE.md)，请以新文档为准。

特别注意：原 V0.3 中“手动扩充 RealStaticTests 白名单”的做法已经废弃。如今每个编号有对应的 `Dts.Tests/S*/xxx_Test.cs`，实现并设置 `IsExecutable` 后，由 `TestModuleRegistry` 自动发现，不再修改主窗口白名单。
