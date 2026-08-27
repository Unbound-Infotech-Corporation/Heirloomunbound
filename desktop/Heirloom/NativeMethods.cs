using System.Runtime.InteropServices;

namespace Heirloom;

internal static class NativeMethods
{
    public const string AppUserModelId = "UnboundInfotech.Heirloom";

    [DllImport("shell32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern int SetCurrentProcessExplicitAppUserModelID(string appID);

    public static void SetAppIdentity()
    {
        _ = SetCurrentProcessExplicitAppUserModelID(AppUserModelId);
    }

    [DllImport("user32.dll")]
    public static extern int GetSystemMetrics(int nIndex);

    public const int SmXVirtualScreen = 76;
    public const int SmYVirtualScreen = 77;
    public const int SmCxVirtualScreen = 78;
    public const int SmCyVirtualScreen = 79;

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool LockWorkStation();

    [DllImport("user32.dll")]
    private static extern void keybd_event(byte bVk, byte bScan, int dwFlags, int dwExtraInfo);

    public static void MediaKey(string action)
    {
        byte vk = action switch
        {
            "playpause" or "play" or "pause" => 0xB3,
            "next" => 0xB0,
            "previous" or "prev" => 0xB1,
            "mute" => 0xAD,
            "volume_up" => 0xAF,
            "volume_down" => 0xAE,
            _ => 0,
        };
        if (vk == 0)
        {
            return;
        }

        keybd_event(vk, 0, 0, 0);
        keybd_event(vk, 0, 2, 0);
    }

    public const uint InputKeyboard = 1;
    public const uint KeyeventfExtendedkey = 0x0001;
    public const uint KeyeventfKeyup = 0x0002;
    public const uint KeyeventfUnicode = 0x0004;

    [DllImport("user32.dll", SetLastError = true)]
    public static extern uint SendInput(uint nInputs, INPUT[] pInputs, int cbSize);

    [DllImport("user32.dll")]
    public static extern nint GetForegroundWindow();

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern int GetWindowText(nint hWnd, System.Text.StringBuilder text, int maxCount);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, nint lParam);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool IsWindowVisible(nint hWnd);

    [DllImport("user32.dll")]
    public static extern uint GetWindowThreadProcessId(nint hWnd, out uint processId);

    public delegate bool EnumWindowsProc(nint hWnd, nint lParam);

    [StructLayout(LayoutKind.Sequential)]
    public struct INPUT
    {
        public uint type;
        public InputUnion U;
    }

    [StructLayout(LayoutKind.Explicit)]
    public struct InputUnion
    {
        [FieldOffset(0)] public KEYBDINPUT ki;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct KEYBDINPUT
    {
        public ushort wVk;
        public ushort wScan;
        public uint dwFlags;
        public uint time;
        public nint dwExtraInfo;
    }

    public static void TypeText(string text)
    {
        if (string.IsNullOrEmpty(text))
        {
            return;
        }

        var inputs = new List<INPUT>(text.Length * 2);
        foreach (var ch in text)
        {
            inputs.Add(UnicodeKey(ch, up: false));
            inputs.Add(UnicodeKey(ch, up: true));
        }

        var arr = inputs.ToArray();
        _ = SendInput((uint)arr.Length, arr, Marshal.SizeOf<INPUT>());
    }

    private static INPUT UnicodeKey(char ch, bool up) => new()
    {
        type = InputKeyboard,
        U = new InputUnion
        {
            ki = new KEYBDINPUT
            {
                wVk = 0,
                wScan = ch,
                dwFlags = KeyeventfUnicode | (up ? KeyeventfKeyup : 0),
            },
        },
    };

    public static string ForegroundTitle()
    {
        var hwnd = GetForegroundWindow();
        return WindowTitle(hwnd);
    }

    public static string WindowTitle(nint hwnd)
    {
        var buffer = new System.Text.StringBuilder(512);
        _ = GetWindowText(hwnd, buffer, buffer.Capacity);
        return buffer.ToString();
    }

    public static IReadOnlyList<(string Title, string Process)> VisibleWindows(int limit = 24)
    {
        var list = new List<(string, string)>();
        EnumWindows((hwnd, _) =>
        {
            if (!IsWindowVisible(hwnd))
            {
                return true;
            }

            var title = WindowTitle(hwnd);
            if (string.IsNullOrWhiteSpace(title))
            {
                return true;
            }

            GetWindowThreadProcessId(hwnd, out var pid);
            var proc = "";
            try
            {
                proc = System.Diagnostics.Process.GetProcessById((int)pid).ProcessName;
            }
            catch
            {
                // Process may have exited.
            }

            list.Add((title, proc));
            return list.Count < limit;
        }, 0);
        return list;
    }
}
