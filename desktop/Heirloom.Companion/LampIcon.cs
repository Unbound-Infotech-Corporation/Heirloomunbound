using System.Drawing;
using System.Drawing.Drawing2D;
using System.Runtime.InteropServices;
using Heirloom.BoxCore;

namespace Heirloom.Companion;

internal static class LampIcon
{
    public static Icon Create(BoxLamp lamp)
    {
        using var bitmap = new Bitmap(32, 32);
        using (var graphics = Graphics.FromImage(bitmap))
        {
            graphics.SmoothingMode = SmoothingMode.AntiAlias;
            graphics.Clear(Color.Transparent);
            var color = lamp switch
            {
                BoxLamp.Green => Color.FromArgb(46, 160, 67),
                BoxLamp.Amber => Color.FromArgb(210, 153, 34),
                _ => Color.FromArgb(196, 48, 43),
            };
            using var brush = new SolidBrush(color);
            graphics.FillEllipse(brush, 2, 2, 28, 28);
        }

        var handle = bitmap.GetHicon();
        try
        {
            using var temp = Icon.FromHandle(handle);
            return (Icon)temp.Clone();
        }
        finally
        {
            _ = DestroyIcon(handle);
        }
    }

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool DestroyIcon(IntPtr handle);
}
