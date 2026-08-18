using System.Drawing;
using System.Drawing.Imaging;

namespace Heirloom.Services;

public sealed class ScreenCaptureService
{
    public byte[] CaptureJpeg(int maxWidth = 1280, long quality = 55L)
    {
        try
        {
            var x = NativeMethods.GetSystemMetrics(NativeMethods.SmXVirtualScreen);
            var y = NativeMethods.GetSystemMetrics(NativeMethods.SmYVirtualScreen);
            var width = Math.Max(1, NativeMethods.GetSystemMetrics(NativeMethods.SmCxVirtualScreen));
            var height = Math.Max(1, NativeMethods.GetSystemMetrics(NativeMethods.SmCyVirtualScreen));
            using var bmp = new Bitmap(width, height);
            using (var g = Graphics.FromImage(bmp))
            {
                g.CopyFromScreen(x, y, 0, 0, bmp.Size);
            }

            using var sized = Scale(bmp, maxWidth);
            using var stream = new MemoryStream();
            using var encoderParams = new EncoderParameters(1);
            encoderParams.Param[0] = new EncoderParameter(Encoder.Quality, quality);
            var codec = ImageCodecInfo.GetImageEncoders().First(c => c.FormatID == ImageFormat.Jpeg.Guid);
            sized.Save(stream, codec, encoderParams);
            return stream.ToArray();
        }
        catch
        {
            return [];
        }
    }

    public string CaptureJpegBase64(int maxWidth = 1280)
    {
        var bytes = CaptureJpeg(maxWidth);
        return bytes.Length == 0 ? "" : Convert.ToBase64String(bytes);
    }

    private static Bitmap Scale(Bitmap source, int maxWidth)
    {
        if (source.Width <= maxWidth)
        {
            return (Bitmap)source.Clone();
        }

        var height = Math.Max(1, source.Height * maxWidth / source.Width);
        var dest = new Bitmap(maxWidth, height);
        using var g = Graphics.FromImage(dest);
        g.DrawImage(source, 0, 0, maxWidth, height);
        return dest;
    }
}
