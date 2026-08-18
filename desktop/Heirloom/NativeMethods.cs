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
}
