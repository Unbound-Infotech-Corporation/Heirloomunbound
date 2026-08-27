using NAudio.CoreAudioApi;
using NAudio.Wave;

namespace Heirloom.Services;

public sealed class CaptureService : IDisposable
{
    private readonly SettingsStore _settings;
    private readonly MMDeviceEnumerator _enumerator = new();
    private WasapiCapture? _capture;
    private WaveFileWriter? _writer;
    private MemoryStream? _buffer;
    private WaveFormat? _nativeFormat;
    private float _peak;
    private float _hpPrevIn;
    private float _hpPrevOut;
    private float _sessionPeak;
    private readonly object _gate = new();

    public CaptureService(SettingsStore settings) => _settings = settings;

    public bool IsCapturing { get; private set; }
    public string LastError { get; private set; } = "";
    public float Peak => _peak;
    public float SessionPeak => _sessionPeak;
    public event EventHandler<float>? LevelChanged;

    public IReadOnlyList<string> ListWaveInDevices()
    {
        var names = new List<string>();
        try
        {
            for (var i = 0; i < WaveInEvent.DeviceCount; i++)
            {
                names.Add(WaveInEvent.GetCapabilities(i).ProductName);
            }
        }
        catch
        {
            // WinMM list is diagnostic only; WASAPI is the capture path.
        }

        return names;
    }

    public void StartPtt()
    {
        lock (_gate)
        {
            if (IsCapturing)
            {
                LastError = "Microphone is already in use.";
                return;
            }

            LastError = "";
            _buffer = new MemoryStream();
            _hpPrevIn = 0;
            _hpPrevOut = 0;
            _peak = 0;
            _sessionPeak = 0;
            try
            {
                var device = ResolveCapture(_settings.Current.InputDeviceId);
                _capture = new WasapiCapture(device, useEventSync: true)
                {
                    ShareMode = AudioClientShareMode.Shared,
                };
                _nativeFormat = _capture.WaveFormat;
                _writer = new WaveFileWriter(_buffer, new WaveFormat(16000, 1));
                _capture.DataAvailable += OnData;
            }
            catch (Exception ex)
            {
                LastError = "Microphone did not open: " + ex.Message;
                DisposeCapture();
                return;
            }
        }

        try
        {
            _capture!.StartRecording();
            IsCapturing = true;
        }
        catch (Exception ex)
        {
            lock (_gate)
            {
                IsCapturing = false;
                LastError = "Microphone did not open: " + ex.Message;
                DisposeCapture();
            }
        }
    }

    public byte[] StopPtt()
    {
        WasapiCapture? capture;
        lock (_gate)
        {
            IsCapturing = false;
            capture = _capture;
        }

        if (capture is not null)
        {
            using var done = new ManualResetEventSlim(false);
            EventHandler<StoppedEventArgs>? stopped = null;
            stopped = (_, _) =>
            {
                capture.RecordingStopped -= stopped;
                done.Set();
            };
            capture.RecordingStopped += stopped;
            try
            {
                capture.StopRecording();
            }
            catch
            {
                done.Set();
            }

            done.Wait(TimeSpan.FromMilliseconds(1500));
        }

        lock (_gate)
        {
            try { _writer?.Flush(); } catch { /* ignore */ }
            var bytes = _buffer?.ToArray() ?? [];
            if (bytes.Length >= 2048 && _sessionPeak < 0.008f)
            {
                LastError = "Microphone opened but stayed silent. Open Mixer, pick Chat Mic, and watch the gold bar move.";
            }

            DisposeCapture();
            return bytes;
        }
    }

    private MMDevice ResolveCapture(string id)
    {
        if (string.IsNullOrWhiteSpace(id) || string.Equals(id, "default", StringComparison.OrdinalIgnoreCase))
        {
            return _enumerator.GetDefaultAudioEndpoint(DataFlow.Capture, Role.Multimedia);
        }

        try
        {
            return _enumerator.GetDevice(id);
        }
        catch
        {
            return _enumerator.GetDefaultAudioEndpoint(DataFlow.Capture, Role.Multimedia);
        }
    }

    private void OnData(object? sender, WaveInEventArgs e)
    {
        byte[] pcm;
        float peak;
        lock (_gate)
        {
            if (_writer is null || _nativeFormat is null || e.BytesRecorded <= 0)
            {
                return;
            }

            pcm = ConvertTo16kMono(_nativeFormat, e.Buffer, e.BytesRecorded);
            if (pcm.Length < 2)
            {
                return;
            }

            ProcessBuffer(pcm, pcm.Length);
            _writer.Write(pcm, 0, pcm.Length);
            peak = EstimatePeak(pcm, pcm.Length);
            _peak = peak;
            if (peak > _sessionPeak)
            {
                _sessionPeak = peak;
            }
        }

        LevelChanged?.Invoke(this, peak);
    }

    private static byte[] ConvertTo16kMono(WaveFormat format, byte[] buffer, int bytes)
    {
        var samples = ExtractMono(format, buffer, bytes);
        if (samples.Length == 0)
        {
            return [];
        }

        var ratio = format.SampleRate / 16000.0;
        if (ratio < 0.01)
        {
            return FloatsToPcm16(samples);
        }

        if (Math.Abs(ratio - 1) < 0.001)
        {
            return FloatsToPcm16(samples);
        }

        var outLen = Math.Max(1, (int)(samples.Length / ratio));
        var resampled = new float[outLen];
        for (var i = 0; i < outLen; i++)
        {
            var src = i * ratio;
            var i0 = Math.Min((int)src, samples.Length - 1);
            var i1 = Math.Min(i0 + 1, samples.Length - 1);
            var t = (float)(src - i0);
            resampled[i] = samples[i0] * (1 - t) + samples[i1] * t;
        }

        return FloatsToPcm16(resampled);
    }

    private static float[] ExtractMono(WaveFormat format, byte[] buffer, int bytes)
    {
        var channels = Math.Max(1, format.Channels);
        var frame = format.BlockAlign > 0 ? format.BlockAlign : channels * Math.Max(1, format.BitsPerSample / 8);
        if (frame <= 0 || bytes < frame)
        {
            return [];
        }

        var bytesPerSample = Math.Max(1, frame / channels);
        var isFloat = format.Encoding == WaveFormatEncoding.IeeeFloat
            || (format.BitsPerSample == 32 && format.Encoding != WaveFormatEncoding.Pcm && bytesPerSample == 4);
        if (format is WaveFormatExtensible extensible)
        {
            var ieee = new Guid("00000003-0000-0010-8000-00aa00389b71");
            var pcm = new Guid("00000001-0000-0010-8000-00aa00389b71");
            if (extensible.SubFormat == ieee)
            {
                isFloat = true;
            }
            else if (extensible.SubFormat == pcm)
            {
                isFloat = false;
            }
        }

        var n = bytes / frame;
        var mono = new float[n];
        for (var i = 0; i < n; i++)
        {
            var sum = 0f;
            for (var c = 0; c < channels; c++)
            {
                sum += ReadSample(buffer, i * frame + c * bytesPerSample, bytesPerSample, isFloat);
            }

            mono[i] = sum / channels;
        }

        return mono;
    }

    private static float ReadSample(byte[] buffer, int offset, int bytesPerSample, bool isFloat)
    {
        if (offset + bytesPerSample > buffer.Length)
        {
            return 0f;
        }

        if (isFloat && bytesPerSample >= 4)
        {
            return BitConverter.ToSingle(buffer, offset);
        }

        return bytesPerSample switch
        {
            1 => (buffer[offset] - 128) / 128f,
            2 => BitConverter.ToInt16(buffer, offset) / 32768f,
            3 => ReadInt24(buffer, offset) / 8388608f,
            4 => BitConverter.ToInt32(buffer, offset) / 2147483648f,
            _ => 0f,
        };
    }

    private static int ReadInt24(byte[] buffer, int offset)
    {
        var value = buffer[offset] | (buffer[offset + 1] << 8) | (buffer[offset + 2] << 16);
        if ((value & 0x800000) != 0)
        {
            value |= unchecked((int)0xFF000000);
        }

        return value;
    }

    private static byte[] FloatsToPcm16(float[] samples)
    {
        var pcm = new byte[samples.Length * 2];
        for (var i = 0; i < samples.Length; i++)
        {
            var clipped = Math.Clamp(samples[i], -1f, 1f);
            var value = (short)Math.Clamp((int)(clipped * 32767f), short.MinValue, short.MaxValue);
            pcm[i * 2] = (byte)(value & 0xFF);
            pcm[i * 2 + 1] = (byte)((value >> 8) & 0xFF);
        }

        return pcm;
    }

    private void ProcessBuffer(byte[] buffer, int count)
    {
        var gain = (float)_settings.Current.InputGain;
        var gate = (float)_settings.Current.NoiseGate;
        var highPass = _settings.Current.HighPass;
        const float rc = 0.002f;
        const float alpha = rc / (rc + (1f / 16000f));
        for (var i = 0; i + 2 <= count; i += 2)
        {
            var sample = BitConverter.ToInt16(buffer, i) / 32768f * gain;
            if (highPass)
            {
                var hp = alpha * (_hpPrevOut + sample - _hpPrevIn);
                _hpPrevIn = sample;
                _hpPrevOut = hp;
                sample = hp;
            }

            if (Math.Abs(sample) < gate)
            {
                sample = 0;
            }

            var pcm = (short)Math.Clamp((int)(sample * 32767f), short.MinValue, short.MaxValue);
            buffer[i] = (byte)(pcm & 0xFF);
            buffer[i + 1] = (byte)((pcm >> 8) & 0xFF);
        }
    }

    private static float EstimatePeak(byte[] buffer, int count)
    {
        var peak = 0f;
        for (var i = 0; i + 2 <= count; i += 2)
        {
            peak = Math.Max(peak, Math.Abs(BitConverter.ToInt16(buffer, i) / 32768f));
        }

        return peak;
    }

    private void DisposeCapture()
    {
        if (_capture is not null)
        {
            _capture.DataAvailable -= OnData;
            try { _capture.Dispose(); } catch { /* ignore */ }
            _capture = null;
        }

        try { _writer?.Dispose(); } catch { /* ignore */ }
        _writer = null;
        _buffer?.Dispose();
        _buffer = null;
        _nativeFormat = null;
    }

    public void Dispose()
    {
        DisposeCapture();
        _enumerator.Dispose();
    }
}
