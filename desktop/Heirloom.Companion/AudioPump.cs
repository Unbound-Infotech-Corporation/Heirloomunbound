using Heirloom.BoxCore;
using NAudio.CoreAudioApi;
using NAudio.Wave;

namespace Heirloom.Companion;

/// <summary>
/// Streams the default microphone, and loopback of the default speakers, as two PCM posts.
/// The box uses these only when it does not already hear the capture card or a C920.
/// </summary>
internal sealed class AudioPump : IDisposable
{
    private readonly CompanionStore _store;
    private readonly object _gate = new();
    private readonly List<byte> _system = new();
    private readonly List<byte> _mic = new();
    private readonly CancellationTokenSource _stop = new();
    private BoxSnapshot _snapshot = TrayStatus.Describe(false, null, BoxLink.DefaultBoxUrl, null);
    private WasapiLoopbackCapture? _loopback;
    private WasapiCapture? _microphone;
    private string _systemFault = "";
    private string _micFault = "";

    public AudioPump(CompanionStore store)
    {
        _store = store;
        _ = RunAsync(_stop.Token);
    }

    public string SystemFault
    {
        get { lock (_gate) return _systemFault; }
    }

    public string MicFault
    {
        get { lock (_gate) return _micFault; }
    }

    public void Note(BoxSnapshot snapshot)
    {
        lock (_gate)
        {
            _snapshot = snapshot;
        }
    }

    private async Task RunAsync(CancellationToken cancellationToken)
    {
        while (!cancellationToken.IsCancellationRequested)
        {
            try
            {
                var snapshot = Current();
                SyncDevices(snapshot);
                await FlushAsync(snapshot, cancellationToken).ConfigureAwait(false);
                await Task.Delay(TimeSpan.FromSeconds(1), cancellationToken).ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
                return;
            }
            catch (Exception)
            {
                await Task.Delay(TimeSpan.FromSeconds(2), cancellationToken).ConfigureAwait(false);
            }
        }
    }

    private BoxSnapshot Current()
    {
        lock (_gate)
        {
            return _snapshot;
        }
    }

    private void SyncDevices(BoxSnapshot snapshot)
    {
        var sendSystem = _store.SystemAudio && AssistLive.MaySend(snapshot.ObserverPaused, snapshot.SystemAudio);
        var sendMic = _store.MicAudio && AssistLive.MaySend(snapshot.ObserverPaused, snapshot.MicAudio);
        if (sendSystem)
        {
            StartLoopback();
        }
        else
        {
            StopLoopback();
        }

        if (sendMic)
        {
            StartMicrophone();
        }
        else
        {
            StopMicrophone();
        }
    }

    private void StartLoopback()
    {
        if (_loopback is not null)
        {
            return;
        }

        try
        {
            var capture = new WasapiLoopbackCapture();
            capture.DataAvailable += (_, args) => Append(_system, capture.WaveFormat, args.Buffer, args.BytesRecorded);
            capture.StartRecording();
            _loopback = capture;
            lock (_gate) _systemFault = "";
        }
        catch (Exception)
        {
            lock (_gate) _systemFault = "no loopback";
        }
    }

    private void StartMicrophone()
    {
        if (_microphone is not null)
        {
            return;
        }

        try
        {
            var capture = new WasapiCapture();
            capture.DataAvailable += (_, args) => Append(_mic, capture.WaveFormat, args.Buffer, args.BytesRecorded);
            capture.StartRecording();
            _microphone = capture;
            lock (_gate) _micFault = "";
        }
        catch (Exception)
        {
            lock (_gate) _micFault = "no microphone";
        }
    }

    private void StopLoopback()
    {
        _loopback?.StopRecording();
        _loopback?.Dispose();
        _loopback = null;
        lock (_gate) _system.Clear();
    }

    private void StopMicrophone()
    {
        _microphone?.StopRecording();
        _microphone?.Dispose();
        _microphone = null;
        lock (_gate) _mic.Clear();
    }

    private static void Append(List<byte> sink, WaveFormat format, byte[] buffer, int count)
    {
        var ieee = format.Encoding == WaveFormatEncoding.IeeeFloat;
        var pcm = PcmConvert.ToS16Mono16k(buffer.AsSpan(0, Math.Max(0, count)), format.Channels, format.SampleRate, ieee);
        if (pcm.Length == 0)
        {
            return;
        }

        lock (sink)
        {
            sink.AddRange(pcm);
            var cap = 16000 * 2 * 8;
            if (sink.Count > cap)
            {
                sink.RemoveRange(0, sink.Count - cap);
            }
        }
    }

    private async Task FlushAsync(BoxSnapshot snapshot, CancellationToken cancellationToken)
    {
        var token = _store.Session();
        if (string.IsNullOrWhiteSpace(token))
        {
            return;
        }

        if (AssistLive.MaySend(snapshot.ObserverPaused, snapshot.SystemAudio))
        {
            var system = Take(_system);
            if (system.Length > 0)
            {
                await BoxClient.PostAudioAsync(_store.BoxUrl, _store.Pin, _store.CaPem, token, "system", system, cancellationToken).ConfigureAwait(false);
            }
        }

        if (AssistLive.MaySend(snapshot.ObserverPaused, snapshot.MicAudio))
        {
            var mic = Take(_mic);
            if (mic.Length > 0)
            {
                await BoxClient.PostAudioAsync(_store.BoxUrl, _store.Pin, _store.CaPem, token, "mic", mic, cancellationToken).ConfigureAwait(false);
            }
        }
    }

    private static byte[] Take(List<byte> sink)
    {
        lock (sink)
        {
            if (sink.Count < 16000 * 2)
            {
                return [];
            }

            var length = Math.Min(sink.Count - (sink.Count % 2), 16000 * 2 * 2);
            var copy = sink.GetRange(0, length).ToArray();
            sink.RemoveRange(0, length);
            return copy;
        }
    }

    public void Dispose()
    {
        _stop.Cancel();
        StopLoopback();
        StopMicrophone();
        _stop.Dispose();
    }
}
