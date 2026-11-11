using System.IO;
using System.Threading;
using System.Windows;

namespace Heirloom.Companion;

public partial class App : Application
{
    private TrayController? _tray;
    private Mutex? _instance;
    private bool _ownsInstance;

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
                _ownsInstance = _instance.WaitOne(0);
                return _ownsInstance;
            }
            catch (AbandonedMutexException)
            {
                _ownsInstance = true;
                return true;
            }
        }
        catch (Exception ex) when (ex is UnauthorizedAccessException or IOException or WaitHandleCannotBeOpenedException)
        {
            return true;
        }
    }

    internal void ReleaseInstance()
    {
        if (!_ownsInstance || _instance is null)
        {
            return;
        }

        _ownsInstance = false;
        try
        {
            _instance.ReleaseMutex();
        }
        catch (ApplicationException)
        {
            // This thread does not own the mutex. The process exit still drops it.
        }

        _instance.Dispose();
        _instance = null;
    }

    protected override void OnExit(ExitEventArgs e)
    {
        _tray?.Dispose();
        ReleaseInstance();
        base.OnExit(e);
    }
}
