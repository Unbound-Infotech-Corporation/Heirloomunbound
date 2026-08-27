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
        App.Host.Poller.NoticeRequested += OnPhoneNotice;
        RootFrame.Navigate(typeof(MainPage));
    }

    private void OnPhoneNotice(object? sender, DesktopNotice notice)
    {
        DispatcherQueue.TryEnqueue(() => _tray.ShowNotice(notice.Title, notice.Message));
    }

    private void OnClosed(object sender, WindowEventArgs args)
    {
        if (!_tray.Attached)
        {
            FaultLog.Write("window", "Close with no tray — exiting so the studio cannot vanish.");
            Application.Current.Exit();
            return;
        }

        args.Handled = true;
        AppWindow.Hide();
    }
}
