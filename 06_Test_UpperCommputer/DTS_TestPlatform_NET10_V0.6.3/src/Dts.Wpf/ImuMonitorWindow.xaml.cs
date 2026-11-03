using System.Collections;
using System.Collections.Specialized;
using System.Windows;
using System.Windows.Threading;

namespace Dts.Wpf;

/// <summary>Read-only live view. Uses the same collection and values as the recorder UI.</summary>
public partial class ImuMonitorWindow : Window
{
    private readonly INotifyCollectionChanged? _observable;

    public ImuMonitorWindow(IEnumerable frames)
    {
        InitializeComponent();
        SamplesGrid.ItemsSource = frames;
        _observable = frames as INotifyCollectionChanged;
        if (_observable != null) _observable.CollectionChanged += FramesChanged;
        Closed += (_, _) =>
        {
            if (_observable != null) _observable.CollectionChanged -= FramesChanged;
        };
    }

    private void FramesChanged(object? sender, NotifyCollectionChangedEventArgs e)
    {
        if (FollowLatest.IsChecked != true || SamplesGrid.Items.Count == 0) return;
        Dispatcher.BeginInvoke((Action)(() =>
        {
            if (SamplesGrid.Items.Count > 0)
                SamplesGrid.ScrollIntoView(SamplesGrid.Items[SamplesGrid.Items.Count - 1]);
        }), DispatcherPriority.Background);
    }
}
