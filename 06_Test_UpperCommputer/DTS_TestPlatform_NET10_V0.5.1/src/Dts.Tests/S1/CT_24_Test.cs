using Dts.TestEngine;

namespace Dts.Tests.S1;

/// <summary>
/// CT-24 - Gyro 旧 C / 补偿 C / 新 C 同批独立对比
/// 当前为安全占位；实现时仅修改本文件。不得在尚未校验实测结果时返回 PASS。
/// </summary>
public sealed class CT_24_Test : TestModuleBase
{
    public override string TestId => "CT-24";
}
