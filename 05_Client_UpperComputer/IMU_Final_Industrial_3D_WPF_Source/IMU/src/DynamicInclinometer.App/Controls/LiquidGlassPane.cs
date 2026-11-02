using System;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Shapes;
using DynamicInclinometer.App.Effects;

namespace DynamicInclinometer.App.Controls;

/// <summary>
/// Reusable native-WPF content control. IMPORTANT: ContentControl, not UserControl.
/// XAML elements placed in this Content (RollLabel, PitchLabel etc.) belong to the
/// hosting Window namescope and are accessible from MainWindow.xaml.cs.
/// The visual parts are independently defined in App.xaml ControlTemplate.
/// </summary>
public sealed class LiquidGlassPane : ContentControl
{
    public static readonly DependencyProperty BackgroundVisualProperty = DependencyProperty.Register(
        nameof(BackgroundVisual), typeof(Visual), typeof(LiquidGlassPane),
        new PropertyMetadata(null, (sender, _) => ((LiquidGlassPane)sender).RefreshSampling()));

    public Visual? BackgroundVisual
    {
        get => (Visual?)GetValue(BackgroundVisualProperty);
        set => SetValue(BackgroundVisualProperty, value);
    }

    private readonly VisualBrush _samplingBrush;
    private LiquidGlassEffect? _shader;
    public string ShaderDiagnostic { get; private set; } = "GPU 特效尚未初始化";
    public bool ShaderAvailable => _shader is not null;
    private Rectangle? _glassSurface;
    private bool _fallback;
    private Rect _lastViewbox = Rect.Empty;

    public bool UsingFallback => _fallback;

    public LiquidGlassPane()
    {
        _samplingBrush = new VisualBrush
        {
            Stretch = Stretch.Fill,
            ViewboxUnits = BrushMappingMode.Absolute,
            ViewportUnits = BrushMappingMode.RelativeToBoundingBox,
            Viewport = new Rect(0, 0, 1, 1),
            TileMode = TileMode.None
        };
        // Crucial: never call native graphics APIs during XAML InitializeComponent.
        // The window can load even if Direct3DCompiler is unavailable or broken.
        _fallback = true;
        Loaded += (_, _) => RefreshSampling();
        SizeChanged += (_, _) => RefreshSampling();
        MouseMove += HandleGlassMouseMove;
    }

    public override void OnApplyTemplate()
    {
        base.OnApplyTemplate();
        _glassSurface = GetTemplateChild("PART_GlassPixelSurface") as Rectangle;
        if (_glassSurface is null)
            throw new InvalidOperationException(
                "LiquidGlassPane 模板缺少 PART_GlassPixelSurface；请检查 App.xaml 中的隐式控件样式。");
        _glassSurface.Fill = _samplingBrush;
        _glassSurface.Effect = _fallback ? null : _shader;
        _glassSurface.Opacity = _fallback ? 0.68 : 0.95;
        RefreshSampling();
    }

    public void SetGlassActive(bool active)
    {
        if (active && _shader is null)
        {
            if (LiquidGlassEffect.TryCreate(out var shader, out string diagnostic))
                _shader = shader;
            ShaderDiagnostic = diagnostic;
        }
        _fallback = !active || _shader is null;
        if (_glassSurface is not null)
        {
            _glassSurface.Effect = _fallback ? null : _shader;
            _glassSurface.Opacity = _fallback ? 0.68 : 0.95;
        }
    }

    public void SetTime(double time)
    {
        if (!_fallback && _shader is not null) _shader.Time = time;
        RefreshSampling();
    }

    public void SetDistortion(double value)
    {
        if (_shader is not null) _shader.Distortion = value;
    }

    public void RefreshSampling()
    {
        if (!IsLoaded || BackgroundVisual is not FrameworkElement scene ||
            ActualWidth <= 0 || ActualHeight <= 0 || scene.ActualWidth <= 0 || scene.ActualHeight <= 0)
            return;
        try
        {
            var position = TranslatePoint(new Point(0, 0), scene);
            var newViewbox = new Rect(position.X, position.Y, ActualWidth, ActualHeight);
            if (_samplingBrush.Visual != scene) _samplingBrush.Visual = scene;
            if (_lastViewbox != newViewbox)
            {
                _samplingBrush.Viewbox = newViewbox;
                _lastViewbox = newViewbox;
            }
        }
        catch (InvalidOperationException) { /* visual may detach during shutdown */ }
    }

    private void HandleGlassMouseMove(object sender, MouseEventArgs e)
    {
        if (_fallback || ActualWidth <= 0 || ActualHeight <= 0) return;
        var at = e.GetPosition(this);
        if (_shader is null) return;
        _shader.Light = new Point(
            Math.Clamp(at.X / ActualWidth, 0, 1),
            Math.Clamp(at.Y / ActualHeight, 0, 1));
    }
}
