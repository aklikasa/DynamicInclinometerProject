using System;
using System.IO;
using System.Windows;
using System.Windows.Media;
using System.Windows.Media.Effects;

namespace DynamicInclinometer.App.Effects;

/// <summary>
/// WPF-native Direct3D9 GPU refraction; ps_3_0 compiled in memory from embedded HLSL.
/// When unavailable, callers MUST use an ordinary transparent glass surface fallback.
/// </summary>
public sealed class LiquidGlassEffect : ShaderEffect
{
    public static readonly DependencyProperty InputProperty =
        RegisterPixelShaderSamplerProperty(nameof(Input), typeof(LiquidGlassEffect), 0);
    public static readonly DependencyProperty TimeProperty = DependencyProperty.Register(
        nameof(Time), typeof(double), typeof(LiquidGlassEffect),
        new UIPropertyMetadata(0.0, PixelShaderConstantCallback(0)));
    public static readonly DependencyProperty DistortionProperty = DependencyProperty.Register(
        nameof(Distortion), typeof(double), typeof(LiquidGlassEffect),
        new UIPropertyMetadata(0.72, PixelShaderConstantCallback(1)));
    public static readonly DependencyProperty LightProperty = DependencyProperty.Register(
        nameof(Light), typeof(Point), typeof(LiquidGlassEffect),
        new UIPropertyMetadata(new Point(0.28, 0.12), PixelShaderConstantCallback(2)));

    public Brush Input
    {
        get => (Brush)GetValue(InputProperty);
        set => SetValue(InputProperty, value);
    }
    public double Time
    {
        get => (double)GetValue(TimeProperty);
        set => SetValue(TimeProperty, value);
    }
    public double Distortion
    {
        get => (double)GetValue(DistortionProperty);
        set => SetValue(DistortionProperty, Math.Clamp(value, 0, 1));
    }
    public Point Light
    {
        get => (Point)GetValue(LightProperty);
        set => SetValue(LightProperty, value);
    }
    private static readonly Lazy<(byte[]? Bytecode, string Message)> Compiled =
        new(RuntimeShaderCompiler.Compile, isThreadSafe: true);

    public static bool TryCreate(out LiquidGlassEffect? effect, out string diagnostic)
    {
        effect = null;
        try
        {
            var result = Compiled.Value;
            diagnostic = result.Message;
            if (result.Bytecode is null) return false;
            var pixelShader = new PixelShader();
            using (var bytes = new MemoryStream(result.Bytecode, writable: false))
                pixelShader.SetStreamSource(bytes);
            effect = new LiquidGlassEffect(pixelShader);
            return true;
        }
        catch (Exception ex)
        {
            diagnostic = ex.GetType().Name + ": " + ex.Message;
            return false;
        }
    }

    private LiquidGlassEffect(PixelShader compiled)
    {
        PixelShader = compiled;
        UpdateShaderValue(InputProperty);
        UpdateShaderValue(TimeProperty);
        UpdateShaderValue(DistortionProperty);
        UpdateShaderValue(LightProperty);
    }
}
