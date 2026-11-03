using Dts.TestEngine;

namespace Dts.Tests.S3;

/// <summary>
/// S3-13 - 丢帧/采样率变化的鲁棒性
/// 当前为安全占位；实现时仅修改本文件。不得在尚未校验实测结果时返回 PASS。
/// </summary>
public sealed class S3_13_Test : TestModuleBase
{
    public override string TestId => "S3-13";
}
