using System.Windows.Input;
using H.NotifyIcon;
using H.NotifyIcon.Core;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using DrawingIcon = System.Drawing.Icon;

namespace Heirloom.Services;

public sealed class TrayService : IDisposable
{
    private TaskbarIcon? _icon;
    private DrawingIcon? _fileIcon;
    private readonly Window _window;
    private readonly ICommand _showCommand;

    public TrayService(Window window)
    {
        _window = window;
        _showCommand = new ShowCommand(ShowStudio);
    }

    public bool Attached { get; private set; }

    public void Attach()
    {
        try
        {
            _icon = new TaskbarIcon
            {
                ToolTipText = "Heirloom — click to show",
                ContextMenuMode = ContextMenuMode.PopupMenu,
                NoLeftClickDelay = true,
                LeftClickCommand = _showCommand,
                DoubleClickCommand = _showCommand,
            };

            var ico = Path.Combine(AppContext.BaseDirectory, "Assets", "AppIcon.ico");
            if (File.Exists(ico))
            {
                _fileIcon = new DrawingIcon(ico);
                _icon.Icon = _fileIcon;
            }

            var menu = new MenuFlyout();
            var show = new MenuFlyoutItem { Text = "Show Heirloom" };
            show.Click += (_, _) => ShowStudio();
            var quit = new MenuFlyoutItem { Text = "Quit" };
            quit.Click += (_, _) => Application.Current.Exit();
            menu.Items.Add(show);
            menu.Items.Add(quit);
            _icon.ContextFlyout = menu;
            Attached = true;
        }
        catch (Exception ex)
        {
            Attached = false;
            FaultLog.Write("tray", ex.Message);
        }
    }

    public void ShowStudio()
    {
        try
        {
            _window.AppWindow.Show();
            _window.Activate();
        }
        catch (Exception ex)
        {
            FaultLog.Write("tray-show", ex.Message);
        }
    }

    public void ShowNotice(string title, string message)
    {
        if (_icon is null || string.IsNullOrWhiteSpace(message))
        {
            return;
        }

        try
        {
            _icon.ShowNotification(
                string.IsNullOrWhiteSpace(title) ? "Heirloom" : title,
                message,
                NotificationIcon.None);
        }
        catch (Exception ex)
        {
            FaultLog.Write("tray-notice", ex.Message);
        }
    }

    public void Dispose()
    {
        _icon?.Dispose();
        _fileIcon?.Dispose();
        Attached = false;
    }

    private sealed class ShowCommand : ICommand
    {
        private readonly Action _run;

        public ShowCommand(Action run) => _run = run;

        public bool CanExecute(object? parameter) => true;

        public void Execute(object? parameter) => _run();

        public event EventHandler? CanExecuteChanged
        {
            add { }
            remove { }
        }
    }
}
