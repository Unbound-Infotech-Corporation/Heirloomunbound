using System.IO;
using NAudio.Wave;

namespace Heirloom.Companion;

/// <summary>
/// Plays one Chatterbox wav, then drops the bytes.
/// </summary>
internal sealed class CaptionPlayer : IDisposable
{
    private WaveOutEvent? _output;
    private WaveFileReader? _reader;
    private MemoryStream? _stream;

    public void Play(byte[] wav)
    {
        Stop();
        if (wav.Length < 12 || wav[0] != (byte)'R')
        {
            return;
        }

        _stream = new MemoryStream(wav, writable: false);
        _reader = new WaveFileReader(_stream);
        _output = new WaveOutEvent();
        _output.PlaybackStopped += (_, _) => Stop();
        _output.Init(_reader);
        _output.Play();
    }

    public void Stop()
    {
        if (_output is not null)
        {
            _output.PlaybackStopped -= (_, _) => Stop();
            try
            {
                _output.Stop();
            }
            catch (Exception)
            {
                // The device can already be gone.
            }

            _output.Dispose();
            _output = null;
        }

        _reader?.Dispose();
        _reader = null;
        _stream?.Dispose();
        _stream = null;
    }

    public void Dispose() => Stop();
}
