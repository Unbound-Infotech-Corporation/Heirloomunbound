using System.Collections.Specialized;
using Heirloom.Controls;
using Heirloom.Services;
using Heirloom.ViewModels;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;

namespace Heirloom;

public sealed partial class MainPage : Page
{
    private int _z = 8;

    public StudioShellViewModel ViewModel { get; }

    public MainPage()
    {
        ViewModel = new StudioShellViewModel(App.Host);
        InitializeComponent();
        ViewModel.PropertyChanged += (_, e) =>
        {
            if (e.PropertyName is nameof(StudioShellViewModel.ShowSplash)
                or nameof(StudioShellViewModel.ShowFirstRun)
                or nameof(StudioShellViewModel.CommandPaletteOpen)
                or nameof(StudioShellViewModel.ActiveDocumentId)
                or nameof(StudioShellViewModel.ShowCoach))
            {
                SyncChrome();
            }
        };
        ViewModel.Coach.PropertyChanged += (_, e) =>
        {
            if (e.PropertyName is nameof(VendorCoachViewModel.IsOpen))
            {
                SyncChrome();
            }
        };
        ViewModel.DocumentOpened += (_, id) => ShowDocument(id, focus: true);
        ViewModel.DocumentClosed += (_, id) => HideDocument(id);
        ViewModel.LayoutCascadeRequested += (_, _) => Cascade();
        ViewModel.LayoutTileRequested += (_, _) => Tile();
        ThemeService.Changed += () => DispatcherQueue.TryEnqueue(ApplyDockLayout);
        Loaded += OnLoaded;
    }

    private async void OnLoaded(object sender, RoutedEventArgs e)
    {
        ApplyDockLayout();
        SyncChrome();
        foreach (var window in Documents())
        {
            window.HelpRequested += OnDocHelp;
            window.Visibility = ViewModel.IsOpen(window.DocumentId) ? Visibility.Visible : Visibility.Collapsed;
        }

        ViewModel.Assistant.Lines.CollectionChanged += (_, e) => ScrollLatest(AssistChatList, e);
        ViewModel.Twin.Lines.CollectionChanged += (_, e) => ScrollLatest(TwinChatList, e);
        await Task.Delay(900);
        ViewModel.DismissSplash();
        AddAccelerator(Windows.System.VirtualKey.K, Windows.System.VirtualKeyModifiers.Control, () => ViewModel.TogglePalette());
        AddAccelerator(Windows.System.VirtualKey.W, Windows.System.VirtualKeyModifiers.Control, () => ViewModel.CloseDocument(ViewModel.ActiveDocumentId));
        AddAccelerator(Windows.System.VirtualKey.Tab, Windows.System.VirtualKeyModifiers.Control, () => ViewModel.CycleWindows());
        AddAccelerator(Windows.System.VirtualKey.F1, Windows.System.VirtualKeyModifiers.None, ToggleInspector);
    }

    private void AddAccelerator(Windows.System.VirtualKey key, Windows.System.VirtualKeyModifiers modifiers, Action action)
    {
        var accel = new KeyboardAccelerator { Key = key, Modifiers = modifiers };
        accel.Invoked += (_, args) =>
        {
            action();
            args.Handled = true;
        };
        KeyboardAccelerators.Add(accel);
    }

    private void SyncChrome()
    {
        Splash.Visibility = ViewModel.ShowSplash ? Visibility.Visible : Visibility.Collapsed;
        FirstRun.Visibility = ViewModel.ShowFirstRun ? Visibility.Visible : Visibility.Collapsed;
        Palette.Visibility = ViewModel.CommandPaletteOpen ? Visibility.Visible : Visibility.Collapsed;
        Coach.Visibility = ViewModel.ShowCoach && ViewModel.Coach.IsOpen ? Visibility.Visible : Visibility.Collapsed;
        foreach (var window in Documents())
        {
            if (window.DocumentId == ViewModel.ActiveDocumentId && window.Visibility == Visibility.Visible)
            {
                Canvas.SetZIndex(window, ++_z);
            }
        }
    }

    private IEnumerable<StudioDocumentWindow> Documents() =>
        Workspace.Children.OfType<StudioDocumentWindow>();

    private StudioDocumentWindow? FindDoc(string id) =>
        Documents().FirstOrDefault(d => d.DocumentId == id);

    private void ShowDocument(string id, bool focus)
    {
        var window = FindDoc(id);
        if (window is null)
        {
            return;
        }

        window.Visibility = Visibility.Visible;
        window.RestoreFromMin();
        if (focus)
        {
            Canvas.SetZIndex(window, ++_z);
            foreach (var doc in Documents())
            {
                doc.IsActive = doc == window;
            }
        }
    }

    private void HideDocument(string id)
    {
        var window = FindDoc(id);
        if (window is not null)
        {
            window.Visibility = Visibility.Collapsed;
        }
    }

    private void Cascade()
    {
        var i = 0;
        foreach (var window in Documents().Where(w => w.Visibility == Visibility.Visible))
        {
            window.RestoreFromMin();
            Canvas.SetLeft(window, 24 + (i * 28));
            Canvas.SetTop(window, 16 + (i * 28));
            window.Width = Math.Min(920, Math.Max(560, Workspace.ActualWidth - 80 - (i * 12)));
            window.Height = Math.Min(620, Math.Max(380, Workspace.ActualHeight - 60 - (i * 12)));
            Canvas.SetZIndex(window, ++_z);
            i++;
        }
    }

    private void Tile()
    {
        var open = Documents().Where(w => w.Visibility == Visibility.Visible).ToList();
        if (open.Count == 0)
        {
            return;
        }

        var cols = open.Count == 1 ? 1 : 2;
        var rows = (int)Math.Ceiling(open.Count / (double)cols);
        var width = Math.Max(480, (Workspace.ActualWidth - 16) / cols);
        var height = Math.Max(320, (Workspace.ActualHeight - 16) / rows);
        for (var i = 0; i < open.Count; i++)
        {
            var window = open[i];
            window.RestoreFromMin();
            Canvas.SetLeft(window, 8 + (i % cols) * width);
            Canvas.SetTop(window, 8 + (i / cols) * height);
            window.Width = width - 10;
            window.Height = height - 10;
        }
    }

    private void OnDockDocument(object sender, DockItem item)
    {
        if (!item.IsHeader)
        {
            ViewModel.OpenDocument(item.Id);
        }
    }

    private void OnDockEdgeDropped(object sender, string edge) => ViewModel.Settings.SetDockEdge(edge);

    private void OnDockSizeChanged(object sender, double size) => ViewModel.Settings.SetDockSize(size);

    private void ApplyDockLayout()
    {
        var edge = ThemeService.DockEdge;
        var size = ThemeService.DockSize;
        var left = edge == "left";
        var right = edge == "right";
        var top = edge == "top";
        LeftRail.Visibility = left ? Visibility.Visible : Visibility.Collapsed;
        RightRail.Visibility = right ? Visibility.Visible : Visibility.Collapsed;
        TopRail.Visibility = top ? Visibility.Visible : Visibility.Collapsed;
        LeftDockCol.Width = new GridLength(left ? size : 0);
        RightDockCol.Width = new GridLength(right ? size : 0);
        TopDockRow.Height = top ? new GridLength(size) : new GridLength(0);
        LeftRail.Edge = "left";
        RightRail.Edge = "right";
        TopRail.Edge = "top";

        var inspector = ThemeService.InspectorOpen;
        var inspectorWidth = ThemeService.InspectorWidth;
        Inspector.Visibility = inspector ? Visibility.Visible : Visibility.Collapsed;
        InspectorSplit.Visibility = inspector ? Visibility.Visible : Visibility.Collapsed;
        InspectorSplitCol.Width = inspector ? new GridLength(6) : new GridLength(0);
        InspectorCol.Width = inspector ? new GridLength(inspectorWidth) : new GridLength(0);
    }

    private bool _inspectorSplitting;
    private double _inspectorSplitStart;
    private double _inspectorSplitWidth;

    private void OnInspectorSplitPressed(object sender, PointerRoutedEventArgs e)
    {
        _inspectorSplitting = true;
        _inspectorSplitStart = e.GetCurrentPoint(StudioBody).Position.X;
        _inspectorSplitWidth = ThemeService.InspectorWidth;
        InspectorSplit.CapturePointer(e.Pointer);
        e.Handled = true;
    }

    private void OnInspectorSplitMoved(object sender, PointerRoutedEventArgs e)
    {
        if (!_inspectorSplitting)
        {
            return;
        }

        var x = e.GetCurrentPoint(StudioBody).Position.X;
        ViewModel.Settings.SetInspectorWidth(_inspectorSplitWidth + (_inspectorSplitStart - x));
        e.Handled = true;
    }

    private void OnInspectorSplitReleased(object sender, PointerRoutedEventArgs e)
    {
        _inspectorSplitting = false;
        InspectorSplit.ReleasePointerCapture(e.Pointer);
        e.Handled = true;
    }

    private void OnToggleInspector(object sender, RoutedEventArgs e) => ToggleInspector();

    private void ToggleInspector() =>
        ViewModel.Settings.SetInspectorOpen(!ViewModel.Settings.InspectorOpen);

    private void OnExplainActive(object sender, RoutedEventArgs e)
    {
        ViewModel.Settings.SetInspectorOpen(true);
        StudioHelp.Pin(ViewModel.ActiveDocumentId);
    }

    private void OnDocHelp(object sender, RoutedEventArgs e)
    {
        if (sender is StudioDocumentWindow window)
        {
            ViewModel.Settings.SetInspectorOpen(true);
            StudioHelp.Pin(window.DocumentId);
        }
    }

    private void OnInspectorGlossary(object sender, EventArgs e)
    {
        ViewModel.OpenDocument("glossary");
        StudioHelp.Pin("glossary");
    }

    private void OnInspectorHide(object sender, EventArgs e) =>
        ViewModel.Settings.SetInspectorOpen(false);

    private void OnInspectorTopic(object sender, string id)
    {
        if (ViewModel.Dock.Any(d => d.Id == id && !d.IsHeader))
        {
            ViewModel.OpenDocument(id);
        }
    }

    private void Dock_ItemClick(object sender, ItemClickEventArgs e)
    {
        if (e.ClickedItem is DockItem item && !item.IsHeader)
        {
            ViewModel.OpenDocument(item.Id);
        }
    }

    private void OnMenuOpen(object sender, RoutedEventArgs e)
    {
        if (sender is FrameworkElement item && item.Tag is string id)
        {
            ViewModel.OpenDocument(id);
        }
    }

    private void OnDocClose(object sender, RoutedEventArgs e)
    {
        if (sender is StudioDocumentWindow window)
        {
            ViewModel.CloseDocument(window.DocumentId);
        }
    }

    private void OnDocActivated(object sender, RoutedEventArgs e)
    {
        if (sender is StudioDocumentWindow window)
        {
            Canvas.SetZIndex(window, ++_z);
            ViewModel.ActiveDocumentId = window.DocumentId;
            StudioHelp.SetDocument(window.DocumentId);
            foreach (var doc in Documents())
            {
                doc.IsActive = doc == window;
            }
        }
    }

    private void OnQuit(object sender, RoutedEventArgs e) => Application.Current.Exit();

    private void TwinPttPressed(object sender, RoutedEventArgs e) => ViewModel.Twin.BeginPtt();

    private async void TwinPttReleased(object sender, RoutedEventArgs e) => await ViewModel.Twin.EndPttAsync();

    private void AssistPttPressed(object sender, RoutedEventArgs e) => ViewModel.Assistant.BeginPtt();

    private async void AssistPttReleased(object sender, RoutedEventArgs e) => await ViewModel.Assistant.EndPttAsync();

    private static void ScrollLatest(ListView list, NotifyCollectionChangedEventArgs e)
    {
        if (list.Items.Count == 0)
        {
            return;
        }

        var item = e.NewItems is { Count: > 0 } ? e.NewItems[^1] : list.Items[^1];
        list.ScrollIntoView(item);
    }

}
