using H.NotifyIcon;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using DrawingIcon = System.Drawing.Icon;

namespace Heirloom.Services;

public sealed class TrayService : IDisposable
{
    private TaskbarIcon? _icon;
    private DrawingIcon? _fileIcon;
    private readonly Window _window;

    public TrayService(Window window) => _window = window;

    public void Attach()
    {
        try
        {
            _icon = new TaskbarIcon
            {
                ToolTipText = "Heirloom",
                ContextMenuMode = ContextMenuMode.PopupMenu,
            };

            var ico = Path.Combine(AppContext.BaseDirectory, "Assets", "AppIcon.ico");
            if (File.Exists(ico))
            {
                _fileIcon = new DrawingIcon(ico);
                _icon.Icon = _fileIcon;
            }

            var menu = new MenuFlyout();
            var show = new MenuFlyoutItem { Text = "Show Heirloom" };
            show.Click += (_, _) =>
            {
                _window.AppWindow.Show();
                _window.Activate();
            };
            var quit = new MenuFlyoutItem { Text = "Quit" };
            quit.Click += (_, _) => Application.Current.Exit();
            menu.Items.Add(show);
            menu.Items.Add(quit);
            _icon.ContextFlyout = menu;
        }
        catch
        {
            // Tray is optional on machines without a notify icon surface.
        }
    }

    public void Dispose()
    {
        _icon?.Dispose();
        _fileIcon?.Dispose();
    }
}
