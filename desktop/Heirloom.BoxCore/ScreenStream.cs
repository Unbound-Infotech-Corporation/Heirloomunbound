namespace Heirloom.BoxCore;

/// <summary>
/// Companion screen send policy. The JPEG stays on the home LAN, on the Twin Box.
/// </summary>
public static class ScreenStream
{
    public const int TargetWidth = 1920;
    public const double DefaultFps = 2;
    public const long JpegQuality = 60;

    public static bool MaySend(bool observerPaused, bool enabled, bool reachable, string mode = "")
    {
        if (!enabled || !reachable || observerPaused)
        {
            return false;
        }

        return !string.Equals(mode, "capture", StringComparison.OrdinalIgnoreCase);
    }

    public static (int Width, int Height) ScaledSize(int width, int height, int maxWidth = TargetWidth)
    {
        if (width < 1)
        {
            width = 1;
        }

        if (height < 1)
        {
            height = 1;
        }

        if (width <= maxWidth)
        {
            return (width, height);
        }

        var scaledHeight = Math.Max(1, (int)((long)height * maxWidth / width));
        return (maxWidth, scaledHeight);
    }

    public static TimeSpan Interval(double fps)
    {
        var rate = fps > 0 ? fps : DefaultFps;
        return TimeSpan.FromSeconds(1.0 / rate);
    }

    /// <summary>
    /// A fresh network signal follows the reported sample rate, between 0.5 and 8.
    /// Any other signal uses <see cref="DefaultFps"/>.
    /// </summary>
    public static double SendFps(double reportedFps, string signal)
    {
        if (!string.Equals(signal, "ok", StringComparison.OrdinalIgnoreCase))
        {
            return DefaultFps;
        }

        if (reportedFps < 0.5 || reportedFps > 8)
        {
            return DefaultFps;
        }

        return reportedFps;
    }
}
