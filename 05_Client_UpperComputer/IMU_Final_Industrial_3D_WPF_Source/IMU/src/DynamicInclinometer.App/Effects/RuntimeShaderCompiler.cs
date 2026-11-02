using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;

namespace DynamicInclinometer.App.Effects;

/// <summary>
/// Compile embedded HLSL in-process, once per launch, rather than launching a second
/// dotnet project during MSBuild. On failure the app falls back to a readable glass pane.
/// No shader bytecode files or FXC installation are required at build time.
/// </summary>
internal static class RuntimeShaderCompiler
{
    private const string ShaderName = "DynamicInclinometer.App.Effects.LiquidGlass.hlsl";

    // d3dcompiler_47.dll is included in supported modern Windows releases.
    // Calls only the native D3DCompiler; does not require any EXE or nested .NET host.
    [DllImport("d3dcompiler_47.dll", EntryPoint = "D3DCompile", ExactSpelling = true,
        CallingConvention = CallingConvention.StdCall)]
    private static extern int D3DCompile(
        [In] byte[] source, UIntPtr sourceSize,
        [MarshalAs(UnmanagedType.LPStr)] string sourceName,
        IntPtr defines, IntPtr include,
        [MarshalAs(UnmanagedType.LPStr)] string entryPoint,
        [MarshalAs(UnmanagedType.LPStr)] string target,
        uint flags1, uint flags2, out IntPtr code, out IntPtr errors);

    [UnmanagedFunctionPointer(CallingConvention.StdCall)]
    private delegate IntPtr GetBufferPointer(IntPtr self);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)]
    private delegate UIntPtr GetBufferSize(IntPtr self);

    private static byte[] CopyBlob(IntPtr blob)
    {
        if (blob == IntPtr.Zero) return Array.Empty<byte>();
        // ID3DBlob vtable: IUnknown 0..2, GetBufferPointer=3, GetBufferSize=4.
        var vtable = Marshal.ReadIntPtr(blob);
        var getPtr = Marshal.GetDelegateForFunctionPointer<GetBufferPointer>(Marshal.ReadIntPtr(vtable, 3 * IntPtr.Size));
        var getSize = Marshal.GetDelegateForFunctionPointer<GetBufferSize>(Marshal.ReadIntPtr(vtable, 4 * IntPtr.Size));
        ulong bytes = getSize(blob).ToUInt64();
        if (bytes == 0 || bytes > 16_000_000) throw new IOException("GPU 编译返回异常大小的着色器数据");
        var buffer = new byte[(int)bytes];
        Marshal.Copy(getPtr(blob), buffer, 0, buffer.Length);
        return buffer;
    }

    public static (byte[]? Bytecode, string Message) Compile()
    {
        IntPtr code = IntPtr.Zero, errors = IntPtr.Zero;
        try
        {
            if (!OperatingSystem.IsWindows())
                return (null, "当前平台不支持 Direct3D9 WPF ShaderEffect");
            using var stream = Assembly.GetExecutingAssembly().GetManifestResourceStream(ShaderName);
            if (stream is null) return (null, "找不到嵌入 HLSL 资源：" + ShaderName);
            using var buffer = new MemoryStream();
            stream.CopyTo(buffer);
            var data = buffer.ToArray();
            if (data.Length == 0) return (null, "HLSL 资源内容为空");
            int hr = D3DCompile(data, new UIntPtr((uint)data.Length), "LiquidGlass.hlsl",
                IntPtr.Zero, IntPtr.Zero, "main", "ps_3_0", 0, 0, out code, out errors);
            if (hr < 0 || code == IntPtr.Zero)
            {
                string detail = errors == IntPtr.Zero ? "未知编译错误" : Encoding.UTF8.GetString(CopyBlob(errors));
                return (null, $"HLSL ps_3_0 编译失败 (0x{hr:X8})：{detail}");
            }
            var shader = CopyBlob(code);
            if (shader.Length < 4 || BitConverter.ToUInt32(shader, 0) != 0xFFFF0300u)
                return (null, "编译器没有返回 WPF 兼容的 ps_3_0 字节码");
            return (shader, "Direct3D9 ps_3_0 已成功编译（运行时）");
        }
        catch (Exception ex)
        {
            Trace.WriteLine("GPU 玻璃已回退：" + ex);
            return (null, ex.GetType().Name + ": " + ex.Message);
        }
        finally
        {
            // A failed COM cleanup must never turn a shader fallback into an app crash.
            if (errors != IntPtr.Zero)
            {
                try { Marshal.Release(errors); }
                catch (Exception ex) { Trace.WriteLine("Shader diagnostic buffer cleanup: " + ex.Message); }
            }
            if (code != IntPtr.Zero)
            {
                try { Marshal.Release(code); }
                catch (Exception ex) { Trace.WriteLine("Shader bytecode buffer cleanup: " + ex.Message); }
            }
        }
    }
}
