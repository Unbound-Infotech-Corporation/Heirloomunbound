using System.Runtime.InteropServices;
using System.Windows.Interop;

namespace Heirloom.Companion;

/// <summary>Ctrl+Alt+H opens the writing card. It does not paste.</summary>
internal sealed class WritingHotkey : IDisposable
{
    private const int HotkeyId = 0x4857;
    private const uint ModControl = 0x0002;
    private const uint ModAlt = 0x0001;
    private const uint VkH = 0x48;
    private const int WmHotkey = 0x0312;

    private HwndSource? _source;
    private bool _registered;

    public event Action? Pressed;

    public void Attach()
    {
        if (!OperatingSystem.IsWindows() || _source is not null)
        {
            return;
        }

        var parameters = new HwndSourceParameters("Heirloom.Companion.Writing")
        {
            Width = 0,
            Height = 0,
            WindowStyle = 0,
        };
        _source = new HwndSource(parameters);
        _source.AddHook(Hook);
        _registered = RegisterHotKey(_source.Handle, HotkeyId, ModControl | ModAlt, VkH);
    }

    public void Dispose()
    {
        if (_registered && _source is not null)
        {
            UnregisterHotKey(_source.Handle, HotkeyId);
        }

        _source?.RemoveHook(Hook);
        _source?.Dispose();
        _source = null;
        _registered = false;
    }

    private IntPtr Hook(IntPtr hwnd, int msg, IntPtr wParam, IntPtr lParam, ref bool handled)
    {
        if (msg == WmHotkey && wParam.ToInt32() == HotkeyId)
        {
            Pressed?.Invoke();
            handled = true;
        }

        return IntPtr.Zero;
    }

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool RegisterHotKey(IntPtr hWnd, int id, uint modifiers, uint key);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool UnregisterHotKey(IntPtr hWnd, int id);
}
