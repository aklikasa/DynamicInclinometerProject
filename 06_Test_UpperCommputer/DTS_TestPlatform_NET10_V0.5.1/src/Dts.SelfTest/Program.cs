using Dts.Core;
using Dts.TestEngine;
using Dts.Tests.S0;
using Dts.Tests.S1.CT05;
using System.IO.Compression;

static void Ensure(bool condition, string message)
{
    if (!condition) throw new Exception("自检失败：" + message);
}

var registry = TestModuleRegistry.Discover(typeof(S0_04_Test).Assembly);
var defined = TestCatalog.Load(Path.Combine(AppContext.BaseDirectory, "assets", "tests.json"));
Ensure(defined.Count == 84, "原始目录需要有 84 项");
Ensure(registry.Modules.Count == 84, "每一项必须有独立 .cs 测试类");
Ensure(registry.Modules.Count(m => m.IsExecutable) == 4, "三项真实静态采集子项与CT-05逐点扫描共四项允许执行");
Ensure(defined.All(x => registry.Find(x.Id) is not null), "JSON 有找不到测试类的编号");
Ensure(defined.Count(x => x.Stage == "S0") == 10, "S0 数量");
Ensure(defined.Count(x => x.Stage == "S1") == 30, "S1 数量");
Ensure(defined.Count(x => x.Stage == "S2") == 16, "S2 数量");
Ensure(defined.Count(x => x.Stage == "S3") == 16, "S3 数量");
Ensure(defined.Count(x => x.Stage == "S4") == 12, "S4 数量");
Ensure(registry.Warnings.Count == 0, "内置测试模块注册不应有冲突");
Ensure(registry.Find("CT-12")?.IsExecutable == true, "CT-12 自动注册失败");
Ensure(registry.Find("S3-01")?.IsExecutable == false, "未实现测试不应该可执行");
var all = registry.MergeDefinitions(defined);
Ensure(all.Count == 84, "原 84 项不应改变");
var extras = TestModuleRegistry.Discover(typeof(DynamicExtraTest).Assembly);
Ensure(extras.Find("S1-EXAMPLE") is not null, "新测试类必须能被自动注册");
Ensure(extras.MergeDefinitions(defined).Count == 85, "新增编号应该自动生成目录元数据");
Ensure(registry.Find("CT-05")?.IsExecutable==true,"CT-05真实测试模块未注册");
Ensure(Ct05Algorithm.BuildPlan("小角度").Count==8,"小角度点数应为8");
Ensure(Ct05Algorithm.BuildPlan("对称小角度").Count==14,"对称小角度点数应为14");
Ensure(Ct05Algorithm.BuildPlan("全圈74点").Count==74,"Python V1.4 全圈扫描点数应为74");
try
{
    Ct05Algorithm.ValidatePlan(new Ct05Settings(Path.GetTempPath(),"",3,5,1,.1,0,30,"对称小角度",false,false),Ct05Algorithm.BuildPlan("对称小角度"));
    throw new Exception("负角度计划未经现场方向确认，必须拒绝");
}
catch(InvalidOperationException){}
var tempDir=Path.Combine(Path.GetTempPath(),"dts_ct05_selftest_"+Guid.NewGuid().ToString("N"));
Directory.CreateDirectory(tempDir);
try
{
    var opts=new Ct05Settings(tempDir,"example.json",3,5,1,.1,0,30,"小角度",false,false);
    var item=new Ct05PointResult(1,"Y",0,5,0,5,5,5.012,.012,1.0001,
        new[]{0d,.09d,.99d},new[]{0d,.09d,.99d},new[]{.001d,.001d,.001d},
        125,124,.008,DateTimeOffset.UtcNow,DateTimeOffset.UtcNow,"real_point.csv",25);
    var report=new Ct05Summary("CT-05","00112233445566778899AABB","DTS123456","example.json","SHA",DateTimeOffset.UtcNow.ToString("O"),
        DateTimeOffset.UtcNow.ToString("O"),"测试数据结构自检","",opts,new[]{item},.012,.012,.012);
    var reportFiles=Ct05Report.ExportAsync(tempDir,report,CancellationToken.None).GetAwaiter().GetResult();
    Ensure(reportFiles.All(File.Exists),"CT-05报告应输出 JSON CSV HTML XLSX");
    using var archive=ZipFile.OpenRead(Path.Combine(tempDir,"CT-05_report.xlsx"));
    Ensure(archive.Entries.Any(x=>x.FullName=="xl/worksheets/sheet2.xml"),"Excel报告缺少逐点工作表");
}
finally{Directory.Delete(tempDir,true);}
Console.WriteLine("PASS: 84/84 测试模块发现；4项有真实执行入口，80项安全占位");
Console.WriteLine("PASS: CT-05 8/14/74点计划、方向安全门禁、CSV/JSON/HTML/XLSX生成自检");
Console.WriteLine("PASS: 新增测试类无需修改主界面，可自动合并为新按钮");
Console.WriteLine("PASS: 编号、阶段数量、唯一性、不可误执行检查通过");
Console.WriteLine("注意：此自检不连接实体硬件，不代表 Windows GUI 或现场控制验收通过");

// 在自检程序中模拟新增加一个源码模块的元数据发现，不接触真实设备。
public sealed class DynamicExtraTest : TestModuleBase
{
    public override string TestId => "S1-EXAMPLE";
    public override string Stage => "S1";
    public override string Name => "模块动态发现自检（未实现）";
}
