using System.Diagnostics;
using NAudio.CoreAudioApi;
using NAudio.Wave;

namespace Heirloom.Services;

public sealed class AudioDeviceInfo
{
    public required string Id { get; init; }
    public required string Name { get; init; }
    public required string Kind { get; init; }
    public bool IsDefault { get; init; }
}

/// <summary>
/// Keeps a named WASAPI render session so Heirloom appears as its own
/// Windows Volume Mixer slider (never the system master).
/// </summary>
public sealed class MixerSessionService : IDisposable
{
    private readonly SettingsStore _settings;
    private WasapiOut? _keepalive;
    private BufferedWaveProvider? _silence;
    private MMDeviceEnumerator? _enumerator;

    public MixerSessionService(SettingsStore settings)
    {
        _settings = settings;
    }

    public IReadOnlyList<AudioDeviceInfo> Inputs { get; private set; } = [];
    public IReadOnlyList<AudioDeviceInfo> Outputs { get; private set; } = [];
    public int SessionVolume
    {
        get => _settings.Current.SessionVolume;
        set
        {
            _settings.Current.SessionVolume = Math.Clamp(value, 0, 100);
            ApplySessionVolume();
            _settings.Save();
        }
    }

    public void Start()
    {
        RefreshDevices();
        try
        {
            var format = WaveFormat.CreateIeeeFloatWaveFormat(48000, 2);
            _silence = new BufferedWaveProvider(format)
            {
                DiscardOnBufferOverflow = true,
                BufferDuration = TimeSpan.FromMilliseconds(200),
            };
            _silence.AddSamples(new byte[format.AverageBytesPerSecond / 10], 0, format.AverageBytesPerSecond / 10);

            var device = ResolveOutput(_settings.Current.OutputDeviceId);
            _keepalive = device is null
                ? new WasapiOut(AudioClientShareMode.Shared, 50)
                : new WasapiOut(device, AudioClientShareMode.Shared, true, 50);
            _keepalive.Init(_silence);
            _keepalive.Play();
            ApplySessionVolume();
        }
        catch
        {
            // No audio endpoint — UI still works.
        }
    }

    public void RefreshDevices()
    {
        _enumerator ??= new MMDeviceEnumerator();
        var defaultIn = _enumerator.GetDefaultAudioEndpoint(DataFlow.Capture, Role.Multimedia);
        var defaultOut = _enumerator.GetDefaultAudioEndpoint(DataFlow.Render, Role.Multimedia);

        Inputs = Enumerate(DataFlow.Capture, defaultIn.ID);
        Outputs = Enumerate(DataFlow.Render, defaultOut.ID);
    }

    public void SetMuted(bool muted)
    {
        _settings.Current.SessionMuted = muted;
        _settings.Save();
        ApplySessionVolume();
    }

    public void SetOutputDevice(string id)
    {
        _settings.Current.OutputDeviceId = id;
        _settings.Save();
        DisposeKeepalive();
        Start();
    }

    private IReadOnlyList<AudioDeviceInfo> Enumerate(DataFlow flow, string defaultId)
    {
        _enumerator ??= new MMDeviceEnumerator();
        var list = new List<AudioDeviceInfo>();
        foreach (var device in _enumerator.EnumerateAudioEndPoints(flow, DeviceState.Active))
        {
            list.Add(new AudioDeviceInfo
            {
                Id = device.ID,
                Name = device.FriendlyName,
                Kind = flow == DataFlow.Capture ? "input" : "output",
                IsDefault = device.ID == defaultId,
            });
        }

        return list;
    }

    private MMDevice? ResolveOutput(string id)
    {
        try
        {
            _enumerator ??= new MMDeviceEnumerator();
            if (string.IsNullOrWhiteSpace(id) || id == "default")
            {
                return _enumerator.GetDefaultAudioEndpoint(DataFlow.Render, Role.Multimedia);
            }

            return _enumerator.GetDevice(id);
        }
        catch
        {
            return null;
        }
    }

    private void ApplySessionVolume()
    {
        try
        {
            _enumerator ??= new MMDeviceEnumerator();
            var device = _enumerator.GetDefaultAudioEndpoint(DataFlow.Render, Role.Multimedia);
            var pid = (uint)Process.GetCurrentProcess().Id;
            var sessions = device.AudioSessionManager.Sessions;
            for (var i = 0; i < sessions.Count; i++)
            {
                var session = sessions[i];
                if (session.GetProcessID == pid)
                {
                    session.SimpleAudioVolume.Mute = _settings.Current.SessionMuted;
                    session.SimpleAudioVolume.Volume = _settings.Current.SessionMuted
                        ? 0
                        : _settings.Current.SessionVolume / 100f;
                    return;
                }
            }
        }
        catch
        {
            // Session may not exist until keepalive is playing.
        }
    }

    private void DisposeKeepalive()
    {
        _keepalive?.Stop();
        _keepalive?.Dispose();
        _keepalive = null;
        _silence = null;
    }

    public void Dispose()
    {
        DisposeKeepalive();
        _enumerator?.Dispose();
    }
}
