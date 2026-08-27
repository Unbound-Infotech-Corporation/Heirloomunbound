using System.Text.Json;

namespace Heirloom.Services;

public sealed class CommandPoller : IDisposable
{
    private readonly HeirloomApiClient _api;
    private readonly MixerSessionService _mixer;
    private readonly SpeakService _speak;
    private readonly ScreenCaptureService _screen;
    private readonly SettingsStore _settings;
    private readonly WhisperService _whisper;
    private readonly OllamaService _ollama;
    private readonly ProvisionService _provision;
    private readonly PcToolkit _pc;
    private readonly CancellationTokenSource _cts = new();
    private Task? _loop;
    private int _polls;

    public string LastStatus { get; private set; } = "Poller idle";
    public event EventHandler<string>? CommandExecuted;
    public event EventHandler<DesktopNotice>? NoticeRequested;

    public CommandPoller(
        HeirloomApiClient api,
        MixerSessionService mixer,
        SpeakService speak,
        ScreenCaptureService screen,
        SettingsStore settings,
        WhisperService whisper,
        OllamaService ollama,
        ProvisionService provision,
        PcToolkit pc)
    {
        _api = api;
        _mixer = mixer;
        _speak = speak;
        _screen = screen;
        _settings = settings;
        _whisper = whisper;
        _ollama = ollama;
        _provision = provision;
        _pc = pc;
    }

    public void Start()
    {
        _loop ??= Task.Run(() => LoopAsync(_cts.Token));
    }

    private async Task LoopAsync(CancellationToken cancellationToken)
    {
        while (!cancellationToken.IsCancellationRequested)
        {
            try
            {
                if (!_api.HasDeviceToken)
                {
                    LastStatus = "Waiting for device token";
                    await Task.Delay(4000, cancellationToken).ConfigureAwait(false);
                    continue;
                }

                var payload = await _api.GetAsync("/companion/poll", cancellationToken).ConfigureAwait(false);
                if (payload is { } json)
                {
                    ApplyStudio(json);
                    await ExecuteCommandsAsync(json, cancellationToken).ConfigureAwait(false);
                    _polls++;
                    if (_polls == 1 || _polls % 10 == 0)
                    {
                        await ReportRuntimeAsync(cancellationToken).ConfigureAwait(false);
                    }

                    LastStatus = "Polled " + DateTime.Now.ToString("HH:mm:ss");
                }
                else
                {
                    LastStatus = "Poll empty";
                }
            }
            catch (OperationCanceledException)
            {
                return;
            }
            catch (Exception ex)
            {
                LastStatus = "Poll error: " + ex.Message;
            }

            await Task.Delay(3000, cancellationToken).ConfigureAwait(false);
        }
    }

    private void ApplyStudio(JsonElement json)
    {
        if (json.TryGetProperty("audio_settings", out var audio) &&
            audio.TryGetProperty("session_volume", out var vol) &&
            vol.TryGetInt32(out var volume))
        {
            _mixer.SessionVolume = volume;
        }
    }

    private async Task ExecuteCommandsAsync(JsonElement json, CancellationToken cancellationToken)
    {
        if (!json.TryGetProperty("commands", out var commands) || commands.ValueKind != JsonValueKind.Array)
        {
            return;
        }

        foreach (var command in commands.EnumerateArray())
        {
            var id = ReadString(command, "cmd_id") ?? ReadString(command, "id");
            var kind = ReadString(command, "kind") ?? "";
            var (ok, detail) = await ExecuteAsync(kind, command, cancellationToken).ConfigureAwait(false);
            if (!string.IsNullOrWhiteSpace(id))
            {
                await _api.PostAsync("/companion/result", new
                {
                    cmd_id = id,
                    status = ok ? "ok" : "error",
                    output = detail,
                }, cancellationToken).ConfigureAwait(false);
            }

            CommandExecuted?.Invoke(this, $"{kind}: {detail}");
        }
    }

    private async Task<(bool Ok, string Detail)> ExecuteAsync(string kind, JsonElement command, CancellationToken cancellationToken)
    {
        try
        {
                if (kind is "shell" or "open_app" or "open_url" or "browse" or "type_text" or "find_file" or "power" or "media_key"
                    or "clipboard_get" or "clipboard_set" or "windows" or "list_dir" or "read_file")
            {
                if (string.Equals(_settings.Current.AppMode, "heir", StringComparison.OrdinalIgnoreCase))
                {
                    return (false, "Heir mode. This PC cannot be driven.");
                }

                if (!_settings.Current.AllowPcControl)
                {
                    return (false, "PC control is off");
                }
            }

            if (kind == "screenshot")
            {
                if (string.Equals(_settings.Current.AppMode, "heir", StringComparison.OrdinalIgnoreCase))
                {
                    return (false, "Heir mode. The screen stays private.");
                }

                if (!_settings.Current.AllowSeeScreen)
                {
                    return (false, "Screen vision is off");
                }
            }

            if (kind is "say" or "speak" && !_settings.Current.AllowSpeak)
            {
                return (false, "Speak is off");
            }

            switch (kind)
            {
                case "open_url":
                    return await ToolAsync("open_url", command, cancellationToken).ConfigureAwait(false);
                case "browse":
                    return await ToolAsync("browse", command, cancellationToken).ConfigureAwait(false);
                case "open_app":
                    return await ToolAsync("open_app", command, cancellationToken).ConfigureAwait(false);
                case "set_volume":
                    return await ToolAsync("set_volume", command, cancellationToken).ConfigureAwait(false);
                case "notify":
                {
                    var title = PayloadString(command, "title") ?? "Heirloom";
                    var message = PayloadString(command, "message") ?? PayloadString(command, "text") ?? "";
                    NoticeRequested?.Invoke(this, new DesktopNotice(title, message));
                    return (true, string.IsNullOrWhiteSpace(message) ? "notified" : message);
                }
                case "say":
                case "speak":
                    await _speak.SpeakAsync(PayloadString(command, "text") ?? "", cancellationToken).ConfigureAwait(false);
                    return (true, "spoken");
                case "screenshot":
                    var jpeg = _screen.CaptureJpeg(1600, 75);
                    if (jpeg.Length == 0)
                    {
                        return (false, "capture failed");
                    }

                    var cmdId = ReadString(command, "cmd_id") ?? "";
                    await _api.PostScreenshotAsync(cmdId, jpeg, cancellationToken).ConfigureAwait(false);
                    return (true, "captured");
                case "media_key":
                    return await ToolAsync("media", command, cancellationToken).ConfigureAwait(false);
                case "power":
                    return await ToolAsync("power", command, cancellationToken).ConfigureAwait(false);
                case "clipboard_set":
                    return await ToolAsync("clipboard_set", command, cancellationToken).ConfigureAwait(false);
                case "clipboard_get":
                    return await ToolAsync("clipboard_get", command, cancellationToken).ConfigureAwait(false);
                case "type_text":
                    return await ToolAsync("type_text", command, cancellationToken).ConfigureAwait(false);
                case "find_file":
                    return await ToolAsync("find_file", command, cancellationToken).ConfigureAwait(false);
                case "windows":
                    return await ToolAsync("windows", command, cancellationToken).ConfigureAwait(false);
                case "provision_models":
                    var profile = DiskProfiles.All.FirstOrDefault(p => p.Id == (_settings.Current.DiskProfile ?? "full"))
                        ?? DiskProfiles.All[1];
                    await _provision.ProvisionAsync(profile, new Progress<string>(_ => { }), cancellationToken).ConfigureAwait(false);
                    return (true, "provisioned");
                case "shell":
                    return await ToolAsync("shell", command, cancellationToken).ConfigureAwait(false);
                case "system_status":
                    return await ToolAsync("system_status", command, cancellationToken).ConfigureAwait(false);
                default:
                    return (false, "unknown " + kind);
            }
        }
        catch (Exception ex)
        {
            return (false, ex.Message);
        }
    }

    private async Task<(bool Ok, string Detail)> ToolAsync(string tool, JsonElement command, CancellationToken cancellationToken)
    {
        var args = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        foreach (var name in new[] { "url", "name", "text", "level", "action", "query", "path", "command", "target", "mode", "amount", "label", "engine" })
        {
            var value = PayloadString(command, name);
            if (!string.IsNullOrEmpty(value))
            {
                args[name] = value;
            }
        }

        var result = await _pc.RunAsync(tool, args, cancellationToken).ConfigureAwait(false);
        return (result.Ok, result.Detail);
    }

    private static string? ReadString(JsonElement el, string name)
    {
        if (!el.TryGetProperty(name, out var value))
        {
            return null;
        }

        return value.ValueKind switch
        {
            JsonValueKind.String => value.GetString(),
            JsonValueKind.Number => value.ToString(),
            JsonValueKind.True => "true",
            JsonValueKind.False => "false",
            _ => null,
        };
    }

    private static string? PayloadString(JsonElement command, string name)
    {
        if (command.TryGetProperty("payload", out var payload) && payload.ValueKind == JsonValueKind.Object)
        {
            var inner = ReadString(payload, name);
            if (!string.IsNullOrEmpty(inner))
            {
                return inner;
            }

            if (payload.TryGetProperty(name, out var num) && num.ValueKind == JsonValueKind.Number)
            {
                return num.ToString();
            }
        }

        return ReadString(command, name);
    }

    public async Task ReportRuntimeAsync(CancellationToken cancellationToken = default)
    {
        await _ollama.ProbeAsync(cancellationToken).ConfigureAwait(false);
        await _api.PostAsync("/companion/runtime", new
        {
            ollama = new { status = _ollama.Status, reachable = _ollama.IsReachable, models = _ollama.Models },
            whisper = new { status = _whisper.Status, ready = _whisper.IsReady },
            gpu = new { name = PcToolkit.ProbeGpu() ?? "local" },
            audio_devices = _mixer.Inputs.Select(d => d.Name).Concat(_mixer.Outputs.Select(d => d.Name)).ToArray(),
            detail = LastStatus,
        }, cancellationToken).ConfigureAwait(false);
    }

    public void Dispose()
    {
        _cts.Cancel();
        _cts.Dispose();
    }
}

public readonly record struct DesktopNotice(string Title, string Message);

