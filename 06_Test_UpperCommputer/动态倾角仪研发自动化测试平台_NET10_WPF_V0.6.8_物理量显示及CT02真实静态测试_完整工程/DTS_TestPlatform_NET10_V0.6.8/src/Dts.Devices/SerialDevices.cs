using System.IO.Ports;
using Dts.Core;

namespace Dts.Devices;

public static class ComPorts
{
    public static string[] Available() => SerialPort.GetPortNames()
        .OrderBy(p=>int.TryParse(p.Replace("COM", "", StringComparison.OrdinalIgnoreCase),out int n)?n:9999)
        .ToArray();
    public static int Number(string port)
    {
        if(!port.StartsWith("COM",StringComparison.OrdinalIgnoreCase) ||
           !int.TryParse(port.AsSpan(3),out int number) || number<1)
            throw new ArgumentException($"串口名称无效：{port}");
        return number;
    }
}

/// <summary>
/// Physical ASM330/MCU Modbus RTU serial communication, no fake or generated readings.
/// Shared lock serializes UID reads and the 104-register FIFO polls.
/// </summary>
public sealed class RealImu : IDisposable
{
    private readonly SemaphoreSlim _io=new(1,1);
    private SerialPort? _serial;
    private byte _slave=1;
    public string PortName => _serial?.PortName ?? "";
    public bool Connected => _serial?.IsOpen==true;
    public DeviceIdentity? Identity {get; private set;}

    public async Task ConnectAsync(string name,int baud,byte slave,CancellationToken ct)
    {
        if(Connected) throw new InvalidOperationException("已有 IMU 连接，请先断开");
        _slave=slave;
        var port=new SerialPort(name,baud,Parity.None,8,StopBits.One)
        {
            ReadTimeout=500,WriteTimeout=500,Handshake=Handshake.None,DtrEnable=false,RtsEnable=false
        };
        try
        {
            port.Open(); _serial=port;
            var data=await ReadAsync(3000,6,ct);
            Identity=DeviceId.FromUid(data);
        }
        catch
        {
            port.Dispose();_serial=null;Identity=null;throw;
        }
    }

    public async Task<ImuBatch> ReadBatchAsync(CancellationToken ct,bool requireSensorOk=true)
    {
        byte[] payload=await ReadAsync(1000,104,ct);
        var batch=Asm330Codec.Parse(payload,DateTimeOffset.UtcNow);
        if((batch.FifoFlags&0x0002)!=0)
            throw new InvalidDataException("MCU FIFO 标志表明传感器处于模拟模式：拒绝记录为真实测量");
        if(requireSensorOk && (batch.FifoFlags&0x0001)==0)
            throw new InvalidDataException("MCU 未报告 SENSOR_OK：拒绝记录");
        return batch;
    }

    private async Task<byte[]> ReadAsync(ushort start,ushort count,CancellationToken ct)
    {
        await _io.WaitAsync(ct);
        try
        {
            if(_serial?.IsOpen!=true) throw new IOException("IMU 串口未打开");
            SerialPort sp=_serial;
            return await Task.Run(()=>
            {
                ct.ThrowIfCancellationRequested();
                sp.DiscardInBuffer();
                byte[] request=ModbusRtu.BuildRead(_slave,start,count);
                sp.Write(request,0,request.Length);
                byte[] header=ReadExact(sp,3,ct);
                if(header[0]!=_slave)throw new InvalidDataException("IMU 从机地址不匹配");
                if(header[1]==0x83)
                {
                    byte[] crc=ReadExact(sp,2,ct);
                    byte[] error=[..header,..crc];
                    if(ModbusRtu.Crc(error.AsSpan(0,3))!=(ushort)(error[3]|error[4]<<8))
                        throw new InvalidDataException("Modbus 异常帧 CRC 错误");
                    throw new InvalidDataException($"IMU Modbus 异常 0x{header[2]:X2}");
                }
                if(header[1]!=0x03 || header[2]!=count*2)
                    throw new InvalidDataException("IMU 应答长度/功能码错误");
                byte[] tail=ReadExact(sp,count*2+2,ct);
                return ModbusRtu.Payload([..header,..tail],_slave,count);
            },ct);
        }
        finally{_io.Release();}
    }
    private static byte[] ReadExact(SerialPort p,int count,CancellationToken ct)
    {
        byte[] data=new byte[count];int offset=0;
        while(offset<count)
        {
            ct.ThrowIfCancellationRequested();
            int got=p.Read(data,offset,count-offset);
            if(got==0) throw new TimeoutException("串口读取超时");
            offset+=got;
        }
        return data;
    }
    public void Dispose(){_serial?.Dispose();_serial=null;Identity=null;_io.Dispose();}
}

public record DetectedPort(string Device,string Port,string Proof,string Axis="");

public static class SerialDiscovery
{
    public static async Task<IReadOnlyList<DetectedPort>> FindImuAsync(
        IEnumerable<string> ports,int baud,byte slave,IProgress<string>? progress,CancellationToken ct)
    {
        var results=new List<DetectedPort>();
        foreach(var port in ports)
        {
            ct.ThrowIfCancellationRequested();
            progress?.Report($"尝试 IMU {port} @ {baud}");
            using var probe=new RealImu();
            try
            {
                await probe.ConnectAsync(port,baud,slave,ct);
                if(probe.Identity is { } id)
                    results.Add(new DetectedPort("IMU",port,$"UID={id.UidHex}, DTS={id.DtsId}"));
            }
            catch(Exception e) when(e is IOException or TimeoutException or UnauthorizedAccessException or
                InvalidDataException or System.ComponentModel.Win32Exception or ArgumentException or InvalidOperationException)
            { /* only a valid CRC-checked UID counts as detected */ }
        }
        return results;
    }
    /// <summary>
    /// Passive 2TD600 identification: listens for documented 55-byte 0xA0 status frames.
    /// No motor control command is sent during discovery. Supports both byte orders for frame header.
    /// </summary>
    public static async Task<IReadOnlyList<DetectedPort>> Find2TdAsync(
        IEnumerable<string> ports,IProgress<string>? progress,CancellationToken ct)
    {
        var found=new List<DetectedPort>();
        foreach(string com in ports)
        foreach(int baud in new[]{115200,921600})
        {
            ct.ThrowIfCancellationRequested();
            progress?.Report($"监听 2TD-600 {com} @ {baud}（只读）");
            try
            {
                using var port=new SerialPort(com,baud,Parity.None,8,StopBits.One){ReadTimeout=150,Handshake=Handshake.None};
                port.Open();
                bool valid=await Task.Run(()=>Read2TdFrames(port,ct),ct);
                if(valid){found.Add(new DetectedPort("2TD-600",com,$"收到 CRC/和校验正确的 0xA0 状态帧，{baud}bps"));break;}
            }
            catch(Exception e) when(e is IOException or TimeoutException or UnauthorizedAccessException or
                System.ComponentModel.Win32Exception or InvalidOperationException or ArgumentException)
            { }
        }
        return found;
    }
    private static bool Read2TdFrames(SerialPort sp,CancellationToken ct)
    {
        var buffer=new List<byte>(512);
        var timer=System.Diagnostics.Stopwatch.StartNew();
        while(timer.ElapsedMilliseconds<750)
        {
            ct.ThrowIfCancellationRequested();
            try
            {
                int b=sp.ReadByte(); if(b<0)continue;buffer.Add((byte)b);
                if(buffer.Count>512)buffer.RemoveRange(0,buffer.Count-256);
                for(int i=0;i+55<=buffer.Count;i++)
                {
                    if(!((buffer[i]==0xAA && buffer[i+1]==0x55)||(buffer[i]==0x55 && buffer[i+1]==0xAA))) continue;
                    if(buffer[i+2]!=55 || buffer[i+4]!=0xA0 || buffer[i+54]!=0xFE)continue;
                    int sum=0;for(int j=2;j<=52;j++)sum+=buffer[i+j];
                    if((byte)sum==buffer[i+53]) return true;
                }
            }
            catch(TimeoutException){}
        }
        return false;
    }
}
