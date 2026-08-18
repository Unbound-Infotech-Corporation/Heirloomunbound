using Heirloom.Controls;
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
        Loaded += OnLoaded;
    }

    private async void OnLoaded(object sender, RoutedEventArgs e)
    {
        SyncChrome();
        foreach (var window in Documents())
        {
            window.Visibility = ViewModel.IsOpen(window.DocumentId) ? Visibility.Visible : Visibility.Collapsed;
        }

        await Task.Delay(900);
        ViewModel.DismissSplash();
        AddAccelerator(Windows.System.VirtualKey.K, Windows.System.VirtualKeyModifiers.Control, () => ViewModel.TogglePalette());
        AddAccelerator(Windows.System.VirtualKey.W, Windows.System.VirtualKeyModifiers.Control, () => ViewModel.CloseDocument(ViewModel.ActiveDocumentId));
        AddAccelerator(Windows.System.VirtualKey.Tab, Windows.System.VirtualKeyModifiers.Control, () => ViewModel.CycleWindows());
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

    private void Dock_ItemClick(object sender, ItemClickEventArgs e)
    {
        if (e.ClickedItem is DockItem item)
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
        }
    }

    private void OnQuit(object sender, RoutedEventArgs e) => Application.Current.Exit();

    private void PttPressed(object sender, RoutedEventArgs e) => ViewModel.Twin.BeginPtt();

    private async void PttReleased(object sender, RoutedEventArgs e) => await ViewModel.Twin.EndPttAsync();

    private void SkipSetup(object sender, RoutedEventArgs e)
    {
        ViewModel.FirstRun.Skip();
        ViewModel.ShowFirstRun = false;
    }

    private async void FinishSetup(object sender, RoutedEventArgs e)
    {
        await ViewModel.FirstRun.FinishAsync();
        ViewModel.ShowFirstRun = false;
        ViewModel.StartCoach();
    }
}
