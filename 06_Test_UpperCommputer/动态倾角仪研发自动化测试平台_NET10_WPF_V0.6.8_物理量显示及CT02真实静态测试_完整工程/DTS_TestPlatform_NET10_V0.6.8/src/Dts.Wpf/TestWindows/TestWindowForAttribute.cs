namespace Dts.Wpf.TestWindows;

/// <summary>Marks a WPF test-specific subwindow. Newly compiled XAML windows can register without editing MainWindow.</summary>
[AttributeUsage(AttributeTargets.Class,AllowMultiple=false)]
public sealed class TestWindowForAttribute(string testId) : Attribute
{
    public string TestId {get;}=testId;
}
