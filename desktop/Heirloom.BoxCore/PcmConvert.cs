namespace Heirloom.BoxCore;

/// <summary>
/// Turns a WASAPI buffer into 16 kHz mono s16le. The companion posts that form and keeps no file.
/// </summary>
public static class PcmConvert
{
    public const int TargetRate = 16000;

    public static byte[] ToS16Mono16k(ReadOnlySpan<byte> interleaved, int channels, int sampleRate, bool ieeeFloat)
    {
        if (channels < 1 || sampleRate < 8000 || interleaved.IsEmpty)
        {
            return [];
        }

        var frames = ieeeFloat ? ReadFloat(interleaved, channels) : ReadS16(interleaved, channels);
        if (frames.Length == 0)
        {
            return [];
        }

        var mono = Downmix(frames, channels);
        var resampled = Resample(mono, sampleRate, TargetRate);
        var bytes = new byte[resampled.Length * 2];
        for (var i = 0; i < resampled.Length; i++)
        {
            var clamped = Math.Clamp(resampled[i], -1f, 1f);
            var sample = (short)Math.Round(clamped * 32767f);
            bytes[i * 2] = (byte)(sample & 0xff);
            bytes[(i * 2) + 1] = (byte)((sample >> 8) & 0xff);
        }

        return bytes;
    }

    private static float[] ReadFloat(ReadOnlySpan<byte> interleaved, int channels)
    {
        var width = channels * 4;
        var frames = interleaved.Length / width;
        var samples = new float[frames * channels];
        for (var i = 0; i < samples.Length; i++)
        {
            samples[i] = BitConverter.ToSingle(interleaved.Slice(i * 4, 4));
        }

        return samples;
    }

    private static float[] ReadS16(ReadOnlySpan<byte> interleaved, int channels)
    {
        var width = channels * 2;
        var frames = interleaved.Length / width;
        var samples = new float[frames * channels];
        for (var i = 0; i < samples.Length; i++)
        {
            var sample = BitConverter.ToInt16(interleaved.Slice(i * 2, 2));
            samples[i] = sample / 32768f;
        }

        return samples;
    }

    private static float[] Downmix(float[] interleaved, int channels)
    {
        if (channels == 1)
        {
            return interleaved;
        }

        var frames = interleaved.Length / channels;
        var mono = new float[frames];
        for (var frame = 0; frame < frames; frame++)
        {
            float sum = 0;
            for (var channel = 0; channel < channels; channel++)
            {
                sum += interleaved[(frame * channels) + channel];
            }

            mono[frame] = sum / channels;
        }

        return mono;
    }

    private static float[] Resample(float[] mono, int fromRate, int toRate)
    {
        if (fromRate == toRate || mono.Length == 0)
        {
            return mono;
        }

        var frames = Math.Max(1, (int)Math.Round(mono.Length * (toRate / (double)fromRate)));
        var output = new float[frames];
        var scale = (mono.Length - 1) / (double)Math.Max(1, frames - 1);
        for (var i = 0; i < frames; i++)
        {
            var position = i * scale;
            var left = (int)Math.Floor(position);
            var right = Math.Min(left + 1, mono.Length - 1);
            var mix = (float)(position - left);
            output[i] = (mono[left] * (1f - mix)) + (mono[right] * mix);
        }

        return output;
    }
}
