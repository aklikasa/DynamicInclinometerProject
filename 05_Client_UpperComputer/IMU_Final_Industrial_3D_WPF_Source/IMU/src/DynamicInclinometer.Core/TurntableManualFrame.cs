using System;
using System.Buffers.Binary;
using System.IO;

namespace DynamicInclinometer.Core;

/// <summary>
/// PREVIEW ONLY: packet layout from 2TD-600 manual appendix A.5.5 (A2/D3).
/// Never send frames to the physical table without validating frame byte order,
/// axis mapping, center-angle semantics, bounds and physical E-stop onsite.
/// </summary>
public static class TurntableManualFrame
{
    // Byte order shown as sample assumption; to be confirmed with original controller's captures.
    public static byte[] PreviewSwayFrame(bool outerAxis, float amplitudeDeg, float frequencyHz)
    {
        if (!float.IsFinite(amplitudeDeg) || !float.IsFinite(frequencyHz) ||
            amplitudeDeg<=0 || amplitudeDeg>180 || frequencyHz<=0 || frequencyHz>10)
            throw new ArgumentOutOfRangeException(nameof(amplitudeDeg),"Check amplitude and frequency");
        var packet=new byte[46];
        packet[0]=0xAA;packet[1]=0x55;packet[2]=0x2E;
        packet[3]=0x01;packet[4]=0xA2;
        int o=outerAxis?31:5;
        packet[o]=0xD3;
        BinaryPrimitives.WriteSingleLittleEndian(packet.AsSpan(o+1,4),amplitudeDeg);
        BinaryPrimitives.WriteSingleLittleEndian(packet.AsSpan(o+5,4),frequencyHz);
        int sum=0;for(int i=2;i<=43;i++)sum+=packet[i];
        packet[44]=(byte)(sum&0xff);packet[45]=0xFE;
        return packet;
    }
}
