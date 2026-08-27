using Heirloom.Services;
using Microsoft.UI.Xaml;

namespace Heirloom;

public partial class App : Application
{
    public static Window Window { get; private set; } = null!;
    public static Microsoft.UI.Dispatching.DispatcherQueue DispatcherQueue { get; private set; } = null!;
    public static nint WindowHandle => WinRT.Interop.WindowNative.GetWindowHandle(Window);
    public static AppHost Host { get; private set; } = null!;

    public App()
    {
        NativeMethods.SetAppIdentity();
        InitializeComponent();
        UnhandledException += (_, e) =>
        {
            FaultLog.Write("unhandled", e.Exception.GetType().Name + ": " + e.Exception.Message);
            e.Handled = true;
        };
    }

    protected override async void OnLaunched(LaunchActivatedEventArgs args)
    {
        Host = new AppHost();
        await Host.StartAsync();
        ThemeService.Apply(Host.Settings.Current);

        Window = new MainWindow();
        DispatcherQueue = Microsoft.UI.Dispatching.DispatcherQueue.GetForCurrentThread();
        Window.Activate();
    }
}
