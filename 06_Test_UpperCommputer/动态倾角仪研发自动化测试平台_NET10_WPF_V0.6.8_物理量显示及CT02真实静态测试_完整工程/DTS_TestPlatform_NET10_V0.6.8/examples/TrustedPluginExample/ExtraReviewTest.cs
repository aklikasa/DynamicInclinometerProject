using Dts.TestEngine;

namespace TrustedPluginExample;

// 示例展示外置 DLL 加载机制，本例不执行测试，也不生成任何虚假数据。
public sealed class ExtraReviewTest : TestModuleBase
{
    public override string TestId => "S1-EXAMPLE";
    public override string Stage => "S1";
    public override string Name => "插件机制演示（未实现）";
    public override string Purpose => "验证外置 DLL 模块可以被阶段按钮自动发现";
    public override string Procedure => "本模块不连接硬件，也不执行测试，仅显示安全占位";
    public override string ImplementationNote => "演示插件：尚未实现，禁止执行";
}
