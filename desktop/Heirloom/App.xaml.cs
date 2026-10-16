using Heirloom.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace Heirloom;

public partial class App : Application
{
    private static int _startupFailureShown;

    public static Window Window { get; private set; } = null!;
    public static Microsoft.UI.Dispatching.DispatcherQueue DispatcherQueue { get; private set; } = null!;
    public static nint WindowHandle => WinRT.Interop.WindowNative.GetWindowHandle(Window);
    public static AppHost Host { get; private set; } = null!;
    public static bool HasMainWindow { get; private set; }

    public App()
    {
        NativeMethods.SetAppIdentity();
        InitializeComponent();
        UnhandledException += (_, e) =>
        {
            FaultLog.Write("unhandled", e.Exception.ToString());
            if (!HasMainWindow)
            {
                ShowStartupFailure(e.Exception);
            }

            e.Handled = true;
        };
    }

    protected override async void OnLaunched(LaunchActivatedEventArgs args)
    {
        try
        {
            DispatcherQueue = Microsoft.UI.Dispatching.DispatcherQueue.GetForCurrentThread();
            Host = new AppHost();
            await Host.StartAsync();
            ThemeService.Apply(Host.Settings.Current);

            Window = new MainWindow();
            HasMainWindow = true;
            Window.Activate();
        }
        catch (Exception ex)
        {
            FaultLog.Write("launch", ex.ToString());
            ShowStartupFailure(ex);
        }
    }

    private static void ShowStartupFailure(Exception ex)
    {
        if (Interlocked.Exchange(ref _startupFailureShown, 1) == 1)
        {
            return;
        }

        try
        {
            var text = new TextBlock
            {
                Text = "Heirloom could not open." + Environment.NewLine + Environment.NewLine + ex.Message,
                TextWrapping = TextWrapping.Wrap,
                Margin = new Thickness(24),
            };
            var window = new Window
            {
                Title = "Heirloom could not open",
                Content = text,
            };
            window.Closed += (_, _) => Environment.Exit(1);
            Window = window;
            window.Activate();
        }
        catch (Exception showEx)
        {
            FaultLog.Write("launch-dialog", showEx.ToString());
            Environment.Exit(1);
        }
    }
}
