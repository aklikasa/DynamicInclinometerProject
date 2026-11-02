using System.IO;
using System.Numerics;
using DynamicInclinometer.Core;
namespace DynamicInclinometer.Devices;
public sealed record DecodedFrame(uint TickMs, ushort Unread, int AccFs, int GyroFs, bool AccFsVerified, bool GyroFsVerified, int Odr, int Fifo, double TempC, IReadOnlyList<(Vector3 acc,Vector3 gyro)> Samples)
{
    public bool ConfigurationVerified => AccFsVerified && GyroFsVerified && Odr>0;
}
public static class ImuProtocol
{
    public const int RegisterCount=104;
    private static readonly Dictionary<int,double> AccScale=new(){{2,.061},{4,.122},{8,.244},{16,.488}};
    private static readonly Dictionary<int,double> GyroScale=new(){{125,4.37},{250,8.75},{500,17.5},{1000,35},{2000,70},{4000,140}};
    public static ushort Crc(ReadOnlySpan<byte> b)
    {
        ushort crc=0xffff;
        foreach(var v in b){crc^=v;for(var i=0;i<8;i++)crc=(ushort)(((crc&1)!=0)?(crc>>1)^0xA001:crc>>1);}
        return crc;
    }
    private static short S(ushort v)=>unchecked((short)v);
    public static DecodedFrame Decode(ushort[] words,int fallbackAccFs=2,int fallbackGyroFs=2000)
    {
        if(words.Length!=104)throw new InvalidDataException("寄存器应为 104 个");
        var av=AccScale.ContainsKey(words[100]);var gv=GyroScale.ContainsKey(words[101]);
        int af=av?words[100]:fallbackAccFs, gf=gv?words[101]:fallbackGyroFs;
        if(!AccScale.ContainsKey(af)||!GyroScale.ContainsKey(gf))throw new InvalidDataException("量程未确定，不允许猜测数据比例");
        var samples=new List<(Vector3,Vector3)>(16);
        for(int i=0;i<16;i++)
        {
            var a=new Vector3((float)(S(words[1+i])*AccScale[af]/1000),(float)(S(words[17+i])*AccScale[af]/1000),(float)(S(words[33+i])*AccScale[af]/1000));
            var g=new Vector3((float)(S(words[49+i])*GyroScale[gf]/1000),(float)(S(words[65+i])*GyroScale[gf]/1000),(float)(S(words[81+i])*GyroScale[gf]/1000));
            samples.Add((a,g));
        }
        return new((uint)(words[98]|((uint)words[99]<<16)),words[0],af,gf,av,gv,words[102],words[103],25+S(words[97])/256.0,samples);
    }
    public static byte[] Request(byte slave)
    {
        byte[] req={slave,3,3,232,0,104,0,0};var c=Crc(req.AsSpan(0,6));req[6]=(byte)c;req[7]=(byte)(c>>8);return req;
    }
    public static ushort[] ParseReply(byte[] packet, byte slave)
    {
        if(packet.Length!=213 || packet[0]!=slave || packet[1]!=3 || packet[2]!=208)throw new InvalidDataException("Modbus 帧头或长度异常");
        var crc=Crc(packet.AsSpan(0,211));
        if(packet[211]!=(byte)crc||packet[212]!=(byte)(crc>>8))throw new InvalidDataException("Modbus CRC 错误");
        var words=new ushort[104];for(int i=0;i<104;i++)words[i]=(ushort)((packet[3+i*2]<<8)|packet[4+i*2]);return words;
    }
}
