using Heirloom.Services;
using Microsoft.UI.Xaml;

namespace Heirloom;

public sealed partial class MainWindow : Window
{
    private readonly TrayService _tray;

    public MainWindow()
    {
        InitializeComponent();
        ExtendsContentIntoTitleBar = true;
        SetTitleBar(AppTitleBar);
        AppWindow.SetIcon("Assets/AppIcon.ico");
        AppWindow.Resize(new Windows.Graphics.SizeInt32(1440, 900));
        AppTitleBar.Title = $"Heirloom  {App.Host.Version}  ·  {App.Host.BuildId}";
        Closed += OnClosed;
        _tray = new TrayService(this);
        _tray.Attach();
        RootFrame.Navigate(typeof(MainPage));
    }

    private void OnClosed(object sender, WindowEventArgs args)
    {
        args.Handled = true;
        AppWindow.Hide();
    }
}
