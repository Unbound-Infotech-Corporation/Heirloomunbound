using System.Diagnostics;
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
    private readonly CancellationTokenSource _cts = new();
    private Task? _loop;
    private int _polls;

    public string LastStatus { get; private set; } = "Poller idle";
    public event EventHandler<string>? CommandExecuted;

    public CommandPoller(
        HeirloomApiClient api,
        MixerSessionService mixer,
        SpeakService speak,
        ScreenCaptureService screen,
        SettingsStore settings,
        WhisperService whisper,
        OllamaService ollama,
        ProvisionService provision)
    {
        _api = api;
        _mixer = mixer;
        _speak = speak;
        _screen = screen;
        _settings = settings;
        _whisper = whisper;
        _ollama = ollama;
        _provision = provision;
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
            if (kind is "shell" or "open_app" or "open_url" or "type_text" or "find_file" or "power" or "media_key"
                && !_settings.Current.AllowPcControl)
            {
                return (false, "PC control is off");
            }

            if (kind == "screenshot" && !_settings.Current.AllowSeeScreen)
            {
                return (false, "Screen vision is off");
            }

            if (kind is "say" or "speak" && !_settings.Current.AllowSpeak)
            {
                return (false, "Speak is off");
            }

            switch (kind)
            {
                case "open_url":
                    OpenUrl(PayloadString(command, "url") ?? PayloadString(command, "text"));
                    return (true, "opened");
                case "open_app":
                    OpenUrl(PayloadString(command, "name") ?? PayloadString(command, "text"));
                    return (true, "opened");
                case "set_volume":
                    if (int.TryParse(PayloadString(command, "level") ?? PayloadString(command, "text"), out var vol))
                    {
                        _mixer.SessionVolume = vol;
                        return (true, $"Heirloom session volume {vol}%");
                    }

                    return (false, "bad volume");
                case "notify":
                    CommandExecuted?.Invoke(this, PayloadString(command, "message") ?? PayloadString(command, "text") ?? "");
                    return (true, "notified");
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
                    NativeMethods.MediaKey(PayloadString(command, "action") ?? "");
                    return (true, "media");
                case "power":
                    return RunPower(PayloadString(command, "action") ?? "");
                case "clipboard_set":
                    ClipboardService.CopyText(PayloadString(command, "text") ?? "");
                    return (true, "clipboard");
                case "provision_models":
                    var profile = DiskProfiles.All.FirstOrDefault(p => p.Id == (_settings.Current.DiskProfile ?? "full"))
                        ?? DiskProfiles.All[1];
                    await _provision.ProvisionAsync(profile, new Progress<string>(_ => { }), cancellationToken).ConfigureAwait(false);
                    return (true, "provisioned");
                case "shell":
                    var cmd = PayloadString(command, "command") ?? PayloadString(command, "text") ?? "";
                    Process.Start(new ProcessStartInfo("cmd.exe", "/c " + cmd)
                    {
                        UseShellExecute = false,
                        CreateNoWindow = true,
                    });
                    return (true, "shell");
                case "system_status":
                    return (true, $"{Environment.MachineName} · {Environment.OSVersion} · {_whisper.Status} · {_ollama.Status}");
                default:
                    return (false, "unknown " + kind);
            }
        }
        catch (Exception ex)
        {
            return (false, ex.Message);
        }
    }

    private static (bool Ok, string Detail) RunPower(string action) =>
        action switch
        {
            "lock" => (NativeMethods.LockWorkStation(), "lock"),
            "sleep" => Run("rundll32.exe", "powrprof.dll,SetSuspendState 0,1,0"),
            "shutdown" => Run("shutdown", "/s /t 5"),
            "restart" => Run("shutdown", "/r /t 5"),
            _ => (false, "unknown power"),
        };

    private static (bool Ok, string Detail) Run(string file, string args)
    {
        Process.Start(new ProcessStartInfo(file, args) { UseShellExecute = false, CreateNoWindow = true });
        return (true, file);
    }

    private static void OpenUrl(string? target)
    {
        if (string.IsNullOrWhiteSpace(target))
        {
            return;
        }

        Process.Start(new ProcessStartInfo(target) { UseShellExecute = true });
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

        return ReadString(command, name) ?? ReadString(command, "text");
    }

    public async Task ReportRuntimeAsync(CancellationToken cancellationToken = default)
    {
        await _ollama.ProbeAsync(cancellationToken).ConfigureAwait(false);
        await _api.PostAsync("/companion/runtime", new
        {
            ollama = new { status = _ollama.Status, reachable = _ollama.IsReachable, models = _ollama.Models },
            whisper = new { status = _whisper.Status, ready = _whisper.IsReady },
            gpu = new { name = "local" },
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
