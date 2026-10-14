using System.Windows;

namespace Heirloom.Companion;

public partial class App : Application
{
    private TrayController? _tray;

    protected override void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);
        _tray = new TrayController();
        _tray.Start();
    }

    protected override void OnExit(ExitEventArgs e)
    {
        _tray?.Dispose();
        base.OnExit(e);
    }
}
