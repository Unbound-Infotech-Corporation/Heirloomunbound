using System.IO;
using System.Threading;
using System.Windows;

namespace Heirloom.Companion;

public partial class App : Application
{
    private TrayController? _tray;
    private Mutex? _instance;

    protected override void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);
        if (!AcquireInstance())
        {
            Shutdown();
            return;
        }

        _tray = new TrayController();
        _tray.Start();
    }

    private bool AcquireInstance()
    {
        try
        {
            _instance = new Mutex(false, @"Local\Heirloom.Companion");
            try
            {
                return _instance.WaitOne(0);
            }
            catch (AbandonedMutexException)
            {
                return true;
            }
        }
        catch (Exception ex) when (ex is UnauthorizedAccessException or IOException or WaitHandleCannotBeOpenedException)
        {
            return true;
        }
    }

    protected override void OnExit(ExitEventArgs e)
    {
        _tray?.Dispose();
        base.OnExit(e);
    }
}
