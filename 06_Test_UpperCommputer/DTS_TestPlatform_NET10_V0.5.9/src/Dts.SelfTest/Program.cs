using Dts.Core;
using Dts.Devices;
using Dts.TestEngine;
using Dts.Tests.S0;
using Dts.Tests.S1.CT05;
using System.IO.Compression;
using System.Text.Json;
using System.Buffers.Binary;

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
// A real firmware may report zero FS/ODR while the signed int16 samples are authentic.
// In that situation we MUST preserve the raw sample instead of inventing physical units.
var regs = new byte[208];
void SetWord(int offset,ushort value) => BinaryPrimitives.WriteUInt16BigEndian(regs.AsSpan(offset*2,2),value);
SetWord(0,1);SetWord(1,16384);SetWord(17,0);SetWord(33,0);SetWord(49,100);
SetWord(100,0);SetWord(101,0);SetWord(102,0);SetWord(103,1);
var unknown = Asm330Codec.Parse(regs,DateTimeOffset.UtcNow);
Ensure(!unknown.AllUnitsValid && unknown.Samples[0].RawAx==16384 &&
    double.IsNaN(unknown.Samples[0].AxG),"零量程时应保留MCU真实计数，禁止默认伪换算");
SetWord(100,2);SetWord(101,2000);SetWord(102,104);
var known = Asm330Codec.Parse(regs,DateTimeOffset.UtcNow);
Ensure(known.AllUnitsValid && Math.Abs(known.Samples[0].AxG-.999424)<0.000001,
    "MCU报告 ±2g 时应正确换算为g");

string fixture=Path.Combine(Path.GetTempPath(),"dts_calibration_selftest_"+Guid.NewGuid().ToString("N"));
Directory.CreateDirectory(fixture);
try
{
    byte[] fakeUid=Enumerable.Range(0,12).Select(i=>(byte)(i+1)).ToArray();
    var hardware=DeviceId.FromUid(fakeUid);
    double[][] identityMatrix = [[1d,0,0],[0,1,0],[0,0,1]];
    var accJson=JsonSerializer.Serialize(new {
        schema_version=3, uid_raw_12_bytes=hardware.UidHex,
        raw_accel_bias_g=new[]{.01d,0,0},raw_to_platform_matrix=identityMatrix,
        sensor_configuration=new {acc_fs_g=2,acc_full_scale_mcu_verified=false}
    });
    var gyrJson=JsonSerializer.Serialize(new {
        schema_version=3, uid_raw_12_bytes=hardware.UidHex,
        raw_gyro_bias_dps=new[]{0d,.02d,0},raw_to_platform_matrix=identityMatrix,
        sensor_configuration=new {gyro_fs_dps=2000,gyro_full_scale_mcu_verified=false}
    });
    // The operator selects only fixture (the calibration root). The two files may be in
    // completely different nested subdirectories, with no fixed folder naming scheme.
    var accFolder=Path.Combine(fixture,hardware.DtsId,"常温标定","ACC");
    var gyroFolder=Path.Combine(fixture,"不同批次",hardware.DtsId,"Gyro");
    Directory.CreateDirectory(accFolder);Directory.CreateDirectory(gyroFolder);
    var accFile=Path.Combine(accFolder,hardware.DtsId+"_accel_calibration.json");
    var gyroFile=Path.Combine(gyroFolder,hardware.DtsId+"_gyro_calibration.json");
    File.WriteAllText(accFile,accJson);File.WriteAllText(gyroFile,gyrJson);
    var matched=CalibrationLibrary.Load(fixture,hardware);
    Ensure(matched.AllFullUidVerified && matched.Acc?.FsHint==2 && matched.Gyro?.FsHint==2000,
        "按当前UID匹配两份JSON并检查候选量程");
    Ensure(Math.Abs(matched.Acc!.Apply(1,0,0)[0]-.99)<1e-10,"ACC标定应先减零偏再乘矩阵");
    // The same formatter powers the live DataGrid and main imu_selected.csv.
    var rawFrame=SelectedImuFrame.FromSample(unknown,unknown.Samples[0],0,CalibrationRun.Raw);
    Ensure(rawFrame.Ax=="16384" && rawFrame.Gx=="100" && rawFrame.AccUnit=="count" &&
        rawFrame.ToSelectedCsvLine().Contains(",16384,0,0,100,",StringComparison.Ordinal),
        "原始模式须显示和记录同一组 int16 计数");
    var ambientRun=new CalibrationRun(CalibrationMode.Ambient,matched,false);
    ambientRun.Validate(hardware);
    var ambientFrame=SelectedImuFrame.FromSample(known,known.Samples[0],0,ambientRun);
    Ensure(ambientFrame.HasValidCalibration && ambientFrame.Ax=="0.989424" &&
        ambientFrame.AccUnit=="g" && ambientFrame.ToSelectedCsvLine().Contains(ambientFrame.Ax),
        "常温模式必须使用同一个补偿结果显示和记录（不许返回 raw 数值）");
    var unknownFrame=SelectedImuFrame.FromSample(unknown,unknown.Samples[0],0,ambientRun);
    Ensure(unknownFrame.Status=="MCU_FS_UNKNOWN" && unknownFrame.Ax=="--" &&
        unknownFrame.ToSelectedCsvLine().Contains(",--,--,--,--,--,--,",StringComparison.Ordinal),
        "未知量程不允许将原始数值伪装成标定值");
    var wrong=DeviceId.FromUid(Enumerable.Range(0,12).Select(i=>(byte)(50+i)).ToArray());
    Ensure(CalibrationLibrary.Find(fixture,wrong,"accel_calibration.json") is null,"禁止误选另一设备的文件");
    // Identical archived copies are harmless. Conflicting files with the same UID/type
    // must fail closed rather than auto-picking by date/path.
    var archiveFolder=Path.Combine(fixture,"历史归档",hardware.DtsId,"旧版");
    Directory.CreateDirectory(archiveFolder);
    var archivedAcc=Path.Combine(archiveFolder,Path.GetFileName(accFile));
    File.Copy(accFile,archivedAcc);
    Ensure(CalibrationLibrary.Find(fixture,hardware,"accel_calibration.json")==accFile,
        "同内容副本可去重，自动采用确定性的首选路径");
    File.WriteAllText(archivedAcc,accJson.Replace(".01", ".02"));
    bool conflictRejected=false;
    try{_ = CalibrationLibrary.Load(fixture,hardware);}catch(InvalidDataException){conflictRejected=true;}
    Ensure(conflictRejected,"不同版本的UID/类型标定文件必须阻止自动选择");
    File.Delete(archivedAcc);
    File.WriteAllText(accFile,accJson.Replace(hardware.UidHex,"000000000000000000000000"));
    bool mismatchedRejected=false;
    try{_ = CalibrationLibrary.Load(fixture,hardware);}catch(InvalidDataException){mismatchedRejected=true;}
    Ensure(mismatchedRejected,"文件内原始UID冲突必须拒绝应用");
}
finally{Directory.Delete(fixture,true);}
Console.WriteLine("PASS: 表格/主CSV 使用同一数据转换：原始、常温、量程未知三种情况");
Console.WriteLine("PASS: 0量程仍保留原始样本 / 有效MCU量程换算 / UID标定文件双重验证");
Console.WriteLine("PASS: 标定总目录递归匹配 / 同内容文件去重 / 冲突版本拒绝加载");
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
