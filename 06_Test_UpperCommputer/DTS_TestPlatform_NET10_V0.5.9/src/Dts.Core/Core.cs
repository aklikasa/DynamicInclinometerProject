using System.Security.Cryptography;
using System.Buffers.Binary;
using System.Text.Json;

namespace Dts.Core;

public sealed class TestDefinition
{
    public string Stage { get; set; } = "";
    public string Id { get; set; } = "";
    public string Name { get; set; } = "";
    public string Category { get; set; } = "";
    public string Purpose { get; set; } = "";
    public string Procedure { get; set; } = "";
    public string Priority { get; set; } = "";
    public string Equipment { get; set; } = "";
    public string Metrics { get; set; } = "";
}

public record DeviceIdentity(string UidHex, string DtsId);

public static class DeviceId
{
    public static DeviceIdentity FromUid(ReadOnlySpan<byte> uid)
    {
        if(uid.Length!=12 || uid.ToArray().All(b=>b==0) || uid.ToArray().All(b=>b==255))
            throw new InvalidDataException("无效的 12 字节 MCU UID");
        byte[] hash = SHA256.HashData(uid);
        ulong num = BinaryPrimitives.ReadUInt64BigEndian(hash.AsSpan(0,8));
        return new DeviceIdentity(Convert.ToHexString(uid), $"DTS{num%1_000_000:D6}");
    }
}

public static class TestCatalog
{
    public static IReadOnlyList<TestDefinition> Load(string path)
    {
        var data=JsonSerializer.Deserialize<List<TestDefinition>>(File.ReadAllText(path),
            new JsonSerializerOptions{PropertyNameCaseInsensitive=true}) ?? [];
        if(data.Count==0 || data.GroupBy(x=>x.Id).Any(x=>x.Count()>1))
            throw new InvalidDataException("测试清单为空或存在重复测试编号");
        return data;
    }
}

public static class ModbusRtu
{
    public static ushort Crc(ReadOnlySpan<byte> data)
    {
        ushort crc=0xFFFF;
        foreach(byte b in data)
        {
            crc^=b;
            for(int i=0;i<8;i++) crc=(ushort)(((crc&1)==0)?(crc>>1):((crc>>1)^0xA001));
        }
        return crc;
    }
    public static byte[] BuildRead(byte slave, ushort address, ushort count, byte function=3)
    {
        if(slave is <1 or >247 || count is <1 or >126 || function is not (3 or 4)) throw new ArgumentOutOfRangeException();
        byte[] result=[slave,function,(byte)(address>>8),(byte)address,(byte)(count>>8),(byte)count,0,0];
        ushort crc=Crc(result.AsSpan(0,6)); result[6]=(byte)crc; result[7]=(byte)(crc>>8);
        return result;
    }
    public static byte[] Payload(ReadOnlySpan<byte> response, byte slave, ushort count, byte function=3)
    {
        int byteCount=count*2;
        if(response.Length!=byteCount+5 || response[0]!=slave || response[1]!=function || response[2]!=byteCount)
            throw new InvalidDataException("Modbus 应答长度/地址/功能码错误");
        if(Crc(response[..^2])!=(ushort)(response[^2]|response[^1]<<8))
            throw new InvalidDataException("Modbus CRC 校验失败");
        return response.Slice(3,byteCount).ToArray();
    }
}

public sealed record ImuBatch(DateTimeOffset HostTimeUtc, uint McuTickMs, ushort FifoUnread,
    ushort AccFsG, ushort GyroFsDps, ushort OdrHz, ushort FifoFlags, double TemperatureC,
    IReadOnlyList<ImuSample> Samples)
{
    public bool AccUnitsValid => Asm330Codec.TryAccMg(AccFsG, out _);
    public bool GyroUnitsValid => Asm330Codec.TryGyroMdps(GyroFsDps, out _);
    public bool AllUnitsValid => AccUnitsValid && GyroUnitsValid;
}
public sealed record ImuSample(double AxG,double AyG,double AzG,double GxDps,double GyDps,double GzDps,
    short RawAx,short RawAy,short RawAz,short RawGx,short RawGy,short RawGz);

public static class Asm330Codec
{
    private static readonly Dictionary<int,double> AccMg=new(){{2,0.061},{4,0.122},{8,0.244},{16,0.488}};
    private static readonly Dictionary<int,double> GyrMdps=new(){{125,4.37},{250,8.75},{500,17.5},{1000,35},{2000,70},{4000,140}};
    public static bool TryAccMg(int fullScaleG, out double mgPerLsb) => AccMg.TryGetValue(fullScaleG, out mgPerLsb);
    public static bool TryGyroMdps(int fullScaleDps, out double mdpsPerLsb) => GyrMdps.TryGetValue(fullScaleDps, out mdpsPerLsb);
    public static ImuBatch Parse(ReadOnlySpan<byte> registers,DateTimeOffset host)
    {
        if(registers.Length!=208) throw new InvalidDataException("IMU 请求应返回 104 个寄存器");
        ushort[] words=new ushort[104];
        for(int j=0;j<words.Length;j++) words[j]=BinaryPrimitives.ReadUInt16BigEndian(registers.Slice(j*2,2));
        ushort W(int i)=>words[i];
        short S(int i)=>unchecked((short)words[i]);
        ushort accfs=W(100), gyrfs=W(101), odr=W(102), flags=W(103);
        // Missing FS/ODR must NEVER prevent archiving actual signed int16 MCU samples.
        // Unknown units are represented by NaN in memory and empty cells in exported CSV;
        // never silently replace the firmware's 0 with a default physical scale.
        bool hasAcc=TryAccMg(accfs,out double a);
        bool hasGyro=TryGyroMdps(gyrfs,out double g);
        if(odr>10000) throw new InvalidDataException("IMU ODR 字段异常，疑似响应格式错误");
        var list=new List<ImuSample>(16);
        for(int i=0;i<16;i++)
        {
            short ax=S(1+i),ay=S(17+i),az=S(33+i),gx=S(49+i),gy=S(65+i),gz=S(81+i);
            list.Add(new(hasAcc?ax*a/1000:double.NaN,hasAcc?ay*a/1000:double.NaN,hasAcc?az*a/1000:double.NaN,
                hasGyro?gx*g/1000:double.NaN,hasGyro?gy*g/1000:double.NaN,hasGyro?gz*g/1000:double.NaN,
                ax,ay,az,gx,gy,gz));
        }
        return new ImuBatch(host,(uint)(W(98)|(uint)W(99)<<16),W(0),accfs,gyrfs,odr,flags,S(97)/256.0+25.0,list);
    }
}
