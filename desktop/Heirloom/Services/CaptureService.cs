using NAudio.Wave;

namespace Heirloom.Services;

public sealed class CaptureService : IDisposable
{
    private readonly SettingsStore _settings;
    private WaveInEvent? _capture;
    private WaveFileWriter? _writer;
    private MemoryStream? _buffer;
    private float _peak;
    private float _hpPrevIn;
    private float _hpPrevOut;

    public bool IsCapturing { get; private set; }
    public float Peak => _peak;
    public event EventHandler<float>? LevelChanged;

    public CaptureService(SettingsStore settings) => _settings = settings;

    public IReadOnlyList<string> ListWaveInDevices()
    {
        var names = new List<string>();
        for (var i = 0; i < WaveIn.DeviceCount; i++)
        {
            names.Add(WaveIn.GetCapabilities(i).ProductName);
        }

        return names;
    }

    public void StartPtt()
    {
        if (IsCapturing)
        {
            return;
        }

        _buffer = new MemoryStream();
        _hpPrevIn = 0;
        _hpPrevOut = 0;
        try
        {
            var device = Math.Clamp(_settings.Current.InputDeviceNumber, 0, Math.Max(0, WaveIn.DeviceCount - 1));
            _capture = new WaveInEvent
            {
                WaveFormat = new WaveFormat(16000, 1),
                DeviceNumber = WaveIn.DeviceCount == 0 ? 0 : device,
            };
            _writer = new WaveFileWriter(_buffer, _capture.WaveFormat);
            _capture.DataAvailable += OnData;
            _capture.StartRecording();
            IsCapturing = true;
        }
        catch
        {
            IsCapturing = false;
        }
    }

    public byte[] StopPtt()
    {
        IsCapturing = false;
        try { _capture?.StopRecording(); } catch { /* ignore */ }
        _writer?.Flush();
        var bytes = _buffer?.ToArray() ?? [];
        DisposeCapture();
        return bytes;
    }

    private void OnData(object? sender, WaveInEventArgs e)
    {
        if (_writer is null || e.BytesRecorded <= 0)
        {
            return;
        }

        ProcessBuffer(e.Buffer, e.BytesRecorded);
        _writer.Write(e.Buffer, 0, e.BytesRecorded);
        _peak = EstimatePeak(e.Buffer, e.BytesRecorded);
        LevelChanged?.Invoke(this, _peak);
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
            _capture.Dispose();
            _capture = null;
        }

        _writer?.Dispose();
        _writer = null;
        _buffer?.Dispose();
        _buffer = null;
    }

    public void Dispose() => DisposeCapture();
}
