using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.IO;
using System.Runtime.InteropServices;
using Heirloom.BoxCore;

namespace Heirloom.Companion;

/// <summary>
/// Sends the primary display to the Twin Box as a JPEG, on the same session as the microphone.
/// Capture runs at the Observer sample rate and stops while Observer is paused.
/// </summary>
internal sealed class ScreenPump : IDisposable
{
    private readonly CompanionStore _store;
    private readonly object _gate = new();
    private readonly CancellationTokenSource _stop = new();
    private BoxSnapshot _snapshot = TrayStatus.Describe(false, null, BoxLink.DefaultBoxUrl, null);

    public ScreenPump(CompanionStore store)
    {
        _store = store;
        _ = RunAsync(_stop.Token);
    }

    public void Note(BoxSnapshot snapshot)
    {
        lock (_gate)
        {
            _snapshot = snapshot;
        }
    }

    private BoxSnapshot Current()
    {
        lock (_gate)
        {
            return _snapshot;
        }
    }

    private async Task RunAsync(CancellationToken cancellationToken)
    {
        while (!cancellationToken.IsCancellationRequested)
        {
            var snapshot = Current();
            var fps = ScreenStream.SendFps(snapshot.ObserverFps, snapshot.ObserverSignal);
            try
            {
                if (ScreenStream.MaySend(snapshot.ObserverPaused, _store.Screen, snapshot.Reachable, snapshot.ObserverMode))
                {
                    var jpeg = PrimaryScreen.CaptureJpeg(ScreenStream.TargetWidth, ScreenStream.JpegQuality);
                    snapshot = Current();
                    if (jpeg.Length > 0 && ScreenStream.MaySend(snapshot.ObserverPaused, _store.Screen, snapshot.Reachable, snapshot.ObserverMode))
                    {
                        var token = _store.Session();
                        if (!string.IsNullOrWhiteSpace(token))
                        {
                            await BoxClient.PostScreenAsync(
                                _store.BoxUrl,
                                _store.Pin,
                                _store.CaPem,
                                token,
                                jpeg,
                                cancellationToken).ConfigureAwait(false);
                        }
                    }
                }

                await Task.Delay(ScreenStream.Interval(fps), cancellationToken).ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
                return;
            }
            catch (Exception)
            {
                try
                {
                    await Task.Delay(TimeSpan.FromSeconds(2), cancellationToken).ConfigureAwait(false);
                }
                catch (OperationCanceledException)
                {
                    return;
                }
            }
        }
    }

    public void Dispose()
    {
        _stop.Cancel();
        _stop.Dispose();
    }
}

internal static class PrimaryScreen
{
    public static byte[] CaptureJpeg(int maxWidth, long quality)
    {
        try
        {
            var width = Math.Max(1, Native.GetSystemMetrics(Native.SmCxScreen));
            var height = Math.Max(1, Native.GetSystemMetrics(Native.SmCyScreen));
            using var bmp = new Bitmap(width, height);
            using (var g = Graphics.FromImage(bmp))
            {
                g.CopyFromScreen(0, 0, 0, 0, bmp.Size, CopyPixelOperation.SourceCopy);
            }

            using var sized = Scale(bmp, maxWidth);
            using var stream = new MemoryStream();
            using var encoderParams = new EncoderParameters(1);
            encoderParams.Param[0] = new EncoderParameter(Encoder.Quality, quality);
            var codec = ImageCodecInfo.GetImageEncoders().First(item => item.FormatID == ImageFormat.Jpeg.Guid);
            sized.Save(stream, codec, encoderParams);
            return stream.ToArray();
        }
        catch (Exception)
        {
            return [];
        }
    }

    private static Bitmap Scale(Bitmap source, int maxWidth)
    {
        var (width, height) = ScreenStream.ScaledSize(source.Width, source.Height, maxWidth);
        if (width == source.Width && height == source.Height)
        {
            return (Bitmap)source.Clone();
        }

        var dest = new Bitmap(width, height);
        using var g = Graphics.FromImage(dest);
        g.InterpolationMode = InterpolationMode.Bilinear;
        g.CompositingQuality = CompositingQuality.HighSpeed;
        g.SmoothingMode = SmoothingMode.HighSpeed;
        g.PixelOffsetMode = PixelOffsetMode.HighSpeed;
        g.DrawImage(source, 0, 0, width, height);
        return dest;
    }

    private static class Native
    {
        public const int SmCxScreen = 0;
        public const int SmCyScreen = 1;

        [DllImport("user32.dll")]
        public static extern int GetSystemMetrics(int index);
    }
}
