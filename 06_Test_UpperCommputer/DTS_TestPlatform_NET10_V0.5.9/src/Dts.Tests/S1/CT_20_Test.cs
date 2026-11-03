using Dts.TestEngine;

namespace Dts.Tests.S1;

/// <summary>
/// CT-20 - Gyro 冷启动预热零偏曲线
/// 当前为安全占位；实现时仅修改本文件。不得在尚未校验实测结果时返回 PASS。
/// </summary>
public sealed class CT_20_Test : TestModuleBase
{
    public override string TestId => "CT-20";
}
