using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Windows;
using System.Windows.Controls;
using H.NotifyIcon;
using Heirloom.BoxCore;

namespace Heirloom.Companion;

internal sealed class TrayController : IDisposable
{
    private readonly CompanionStore _store = new();
    private readonly CancellationTokenSource _stop = new();
    private readonly TaskbarIcon _icon = new();
    private readonly AudioPump _audio;
    private readonly ScreenPump _screen;
    private readonly CaptionWindow _caption = new();
    private readonly TwinLiveWindow _live;
    private readonly CaptionPlayer _player = new();
    private readonly CompanionHotkey _hotkey = new();
    private AssistLiveView _assist = AssistLiveView.Empty;
    private string _shownCaptionId = "";
    private string _playedAudioId = "";
    private BoxSnapshot _snapshot = TrayStatus.Describe(false, null, BoxLink.DefaultBoxUrl, null);
    private bool? _wasReachable;
    private string _authNotice = "";
    private string _micStatus = "";
    private bool _wasCertificate;
    private TimeSpan _delay = PollSchedule.Healthy;
    private Icon? _current;

    public TrayController()
    {
        _audio = new AudioPump(_store);
        _screen = new ScreenPump(_store);
        _live = new TwinLiveWindow(_store);
        _live.ConfirmRequested += id => _ = ConfirmAsync(id);
        _live.DeclineRequested += id => _ = DeclineAsync(id);
        BoxClient.Unauthorized += OnUnauthorized;
    }

    public void Start()
    {
        ApplyAutostart(_store.Autostart);
        _hotkey.Pressed += () => _ = ArmPushToTalkAsync();
        _hotkey.Attach();
        _icon.ToolTipText = "Heirloom Twin Box";
        Paint(BoxLamp.Red);
        RebuildMenu();
        _icon.ForceCreate();
        _ = PollAsync(_stop.Token);
    }

    private async Task PollAsync(CancellationToken cancellationToken)
    {
        while (!cancellationToken.IsCancellationRequested)
        {
            var url = _store.BoxUrl;
            var probe = await BoxClient.HealthAsync(url, _store.Pin, _store.CaPem, cancellationToken).ConfigureAwait(true);
            var next = TrayStatus.Describe(probe.Reachable, probe.LatencyMs, url, probe.Body, probe.Failure);
            var healthy = next.Lamp != BoxLamp.Red;
            _delay = PollSchedule.Next(_delay, healthy);
            MaybeToast(next);
            _snapshot = next;
            _audio.Note(next);
            _screen.Note(next);
            var signedIn = !string.IsNullOrWhiteSpace(_store.Session());
            if (CompanionSync.ShouldPush(signedIn, _wasReachable, next.Reachable))
            {
                await PushSettingsAsync(cancellationToken).ConfigureAwait(true);
            }

            if (signedIn && next.Reachable)
            {
                await PollCaretakerAsync(cancellationToken).ConfigureAwait(true);
            }

            await PollAssistAsync(cancellationToken).ConfigureAwait(true);
            _wasReachable = next.Reachable;
            _wasCertificate = next.CertificateFailed;
            _micStatus = _audio.MicFault;
            var tip = string.IsNullOrWhiteSpace(_micStatus) ? next.Tooltip : next.Tooltip + "\n" + _micStatus;
            await Application.Current.Dispatcher.InvokeAsync(() =>
            {
                _icon.ToolTipText = tip;
                Paint(next.Lamp);
                RebuildMenu();
            });
            try
            {
                await Task.Delay(_delay, cancellationToken).ConfigureAwait(true);
            }
            catch (OperationCanceledException)
            {
                return;
            }
        }
    }

    private void MaybeToast(BoxSnapshot next)
    {
        if (!_store.Toasts || _wasReachable is null)
        {
            return;
        }

        if (_wasReachable == next.Reachable && _wasCertificate == next.CertificateFailed)
        {
            return;
        }

        var title = next.Reachable
            ? "Twin Box is back"
            : next.CertificateFailed
                ? "Certificate check failed"
                : "Twin Box is offline";
        var body = next.Reachable
            ? "Observer status is updating again."
            : next.CertificateFailed
                ? CertificatePin.CheckFailed
                : "The box did not answer.";
        Application.Current.Dispatcher.Invoke(() => _icon.ShowNotification(title, body));
    }

    private void Paint(BoxLamp lamp)
    {
        var next = LampIcon.Create(lamp);
        _icon.Icon = next;
        _current?.Dispose();
        _current = next;
    }

    private void RebuildMenu()
    {
        var menu = new ContextMenu();
        foreach (var line in _snapshot.Tooltip.Split('\n'))
        {
            menu.Items.Add(new MenuItem { Header = line, IsEnabled = false });
        }

        if (!string.IsNullOrWhiteSpace(_micStatus))
        {
            menu.Items.Add(new MenuItem { Header = _micStatus, IsEnabled = false });
        }

        menu.Items.Add(new Separator());
        var pause = new MenuItem { Header = TrayStatus.PauseVerb(_snapshot.ObserverPaused) };
        pause.IsEnabled = _snapshot.Reachable && !string.IsNullOrWhiteSpace(_store.Session());
        pause.Click += async (_, _) => await TogglePauseAsync().ConfigureAwait(true);
        menu.Items.Add(pause);
        menu.Items.Add(StreamItem("system", _snapshot.SystemAudio, _store.SystemAudio));
        menu.Items.Add(StreamItem("mic", _snapshot.MicAudio, _store.MicAudio));
        menu.Items.Add(ScreenItem());
        var mute = new MenuItem { Header = _assist.Muted ? "Let the twin speak" : "Mute the twin" };
        mute.IsEnabled = _snapshot.Reachable && !string.IsNullOrWhiteSpace(_store.Session());
        mute.Click += async (_, _) => await SetMutedAsync(!_assist.Muted).ConfigureAwait(true);
        menu.Items.Add(mute);
        var listen = new MenuItem { Header = CompanionSync.AlwaysListeningLabel(_store.Proactive) };
        listen.Click += async (_, _) =>
        {
            _store.Proactive = !_store.Proactive;
            await PushSettingsAsync().ConfigureAwait(true);
            RebuildMenu();
        };
        menu.Items.Add(listen);
        var yes = new MenuItem
        {
            Header = string.IsNullOrWhiteSpace(_assist.PendingLabel) ? "Yes, do that" : "Yes — " + _assist.PendingLabel,
            IsEnabled = _assist.PendingId.Length > 0 && _snapshot.Reachable,
        };
        yes.Click += async (_, _) => await ConfirmAsync(_assist.PendingId).ConfigureAwait(true);
        menu.Items.Add(yes);
        if (string.IsNullOrWhiteSpace(_store.Session()))
        {
            if (!string.IsNullOrWhiteSpace(_authNotice))
            {
                menu.Items.Add(new MenuItem { Header = _authNotice, IsEnabled = false });
            }

            menu.Items.Add(new MenuItem { Header = "Sign in from Settings", IsEnabled = false });
        }
        else
        {
            _authNotice = "";
            menu.Items.Add(new MenuItem { Header = "Signed in", IsEnabled = false });
            var signOut = new MenuItem { Header = "Sign out" };
            signOut.Click += async (_, _) =>
            {
                var pending = CompanionSession.SignOutAsync(_store);
                RebuildMenu();
                await pending.ConfigureAwait(true);
            };
            menu.Items.Add(signOut);
        }

        var live = new MenuItem { Header = "Twin Live" };
        live.Click += (_, _) => _live.Reveal();
        menu.Items.Add(live);
        var open = new MenuItem { Header = "Open Twin" };
        open.Click += (_, _) => OpenTwin();
        menu.Items.Add(open);
        var settings = new MenuItem { Header = "Settings" };
        settings.Click += (_, _) => new SettingsWindow(_store).Show();
        menu.Items.Add(settings);
        var quit = new MenuItem { Header = "Quit" };
        quit.Click += (_, _) => Application.Current.Shutdown();
        menu.Items.Add(quit);
        _icon.ContextMenu = menu;
    }

    private MenuItem StreamItem(string source, AudioStreamView reported, bool localOn)
    {
        var on = _snapshot.Reachable ? reported.Enabled : localOn;
        var label = source == "mic" ? "Microphone" : "System audio";
        var item = new MenuItem
        {
            Header = on ? "Turn " + label.ToLowerInvariant() + " off" : "Turn " + label.ToLowerInvariant() + " on",
            IsEnabled = _snapshot.Reachable && !string.IsNullOrWhiteSpace(_store.Session()),
        };
        item.Click += async (_, _) => await ToggleStreamAsync(source, !on).ConfigureAwait(true);
        return item;
    }

    private MenuItem ScreenItem()
    {
        var on = _store.Screen;
        var item = new MenuItem
        {
            Header = on ? "Turn screen off" : "Turn screen on",
        };
        item.Click += (_, _) => { _store.Screen = !on; };
        return item;
    }

    private async Task PushSettingsAsync(CancellationToken cancellationToken = default)
    {
        var token = _store.Session();
        if (string.IsNullOrWhiteSpace(token))
        {
            return;
        }

        await BoxClient.SetAudioStreamAsync(_store.BoxUrl, _store.Pin, _store.CaPem, token, "system", _store.SystemAudio, cancellationToken).ConfigureAwait(true);
        await BoxClient.SetAudioStreamAsync(_store.BoxUrl, _store.Pin, _store.CaPem, token, "mic", _store.MicAudio, cancellationToken).ConfigureAwait(true);
        var settings = CompanionSync.AssistSettingsBody(_store.TwinName, _store.WakePhrase, _store.Proactive);
        await BoxClient.PutAssistSettingsAsync(_store.BoxUrl, _store.Pin, _store.CaPem, token, settings, cancellationToken).ConfigureAwait(true);
    }

    private async Task PollCaretakerAsync(CancellationToken cancellationToken)
    {
        var token = _store.Session();
        if (string.IsNullOrWhiteSpace(token))
        {
            return;
        }

        var json = await BoxClient.GetCaretakerCompanionAsync(_store.BoxUrl, _store.Pin, _store.CaPem, token, cancellationToken).ConfigureAwait(true);
        if (!CaretakerGuard.WantsRepush(json) && !CaretakerGuard.WantsRestart(json))
        {
            return;
        }

        if (CaretakerGuard.WantsRepush(json))
        {
            await PushSettingsAsync(cancellationToken).ConfigureAwait(true);
        }

        await BoxClient.AckCaretakerCompanionAsync(_store.BoxUrl, _store.Pin, _store.CaPem, token, cancellationToken).ConfigureAwait(true);
        if (CaretakerGuard.WantsRestart(json))
        {
            CompanionProcess.Restart();
        }
    }

    private async Task ToggleStreamAsync(string source, bool enabled)
    {
        if (source == "mic")
        {
            _store.MicAudio = enabled;
        }
        else
        {
            _store.SystemAudio = enabled;
        }

        var token = _store.Session();
        if (!string.IsNullOrWhiteSpace(token))
        {
            await BoxClient.SetAudioStreamAsync(_store.BoxUrl, _store.Pin, _store.CaPem, token, source, enabled).ConfigureAwait(true);
        }
    }

    private async Task PollAssistAsync(CancellationToken cancellationToken)
    {
        var token = _store.Session();
        if (string.IsNullOrWhiteSpace(token) || !_snapshot.Reachable)
        {
            return;
        }

        var json = await BoxClient.GetAssistLiveAsync(_store.BoxUrl, _store.Pin, _store.CaPem, token, cancellationToken).ConfigureAwait(true);
        var micJson = await BoxClient.GetAssistMicAsync(_store.BoxUrl, _store.Pin, _store.CaPem, token, cancellationToken).ConfigureAwait(true);
        if (json is null && micJson is null)
        {
            return;
        }

        var view = json is null ? _assist : AssistLive.Parse(json);
        if (json is not null)
        {
            _assist = view;
        }

        _live.Apply(view, MicTranscript.Parse(micJson));
        if (view.CaptionId != _shownCaptionId)
        {
            _shownCaptionId = view.CaptionId;
            _caption.ShowCaption(view.Caption);
        }

        if (!view.HasAudio || view.AudioId.Length == 0 || view.AudioId == _playedAudioId)
        {
            return;
        }

        var wav = await BoxClient.GetAssistAudioAsync(_store.BoxUrl, _store.Pin, _store.CaPem, token, view.AudioId, cancellationToken).ConfigureAwait(true);
        if (wav is { Length: > 12 })
        {
            _playedAudioId = view.AudioId;
            _player.Play(wav);
        }
    }

    private async Task ArmPushToTalkAsync()
    {
        var token = _store.Session();
        if (string.IsNullOrWhiteSpace(token))
        {
            return;
        }

        await BoxClient.PostAssistAsync(
            _store.BoxUrl,
            _store.Pin,
            _store.CaPem,
            token,
            "/api/assist/live/ptt",
            "{\"held\":true}").ConfigureAwait(true);
    }

    private async Task SetMutedAsync(bool muted)
    {
        var token = _store.Session();
        if (string.IsNullOrWhiteSpace(token))
        {
            return;
        }

        var json = muted ? "{\"muted\":true}" : "{\"muted\":false}";
        await BoxClient.PostAssistAsync(_store.BoxUrl, _store.Pin, _store.CaPem, token, "/api/assist/live/mute", json).ConfigureAwait(true);
    }

    private async Task ConfirmAsync(string id)
    {
        if (string.IsNullOrWhiteSpace(id))
        {
            return;
        }

        var token = _store.Session();
        if (string.IsNullOrWhiteSpace(token))
        {
            return;
        }

        var json = "{\"id\":\"" + id.Replace("\"", "", StringComparison.Ordinal) + "\"}";
        await BoxClient.PostAssistAsync(_store.BoxUrl, _store.Pin, _store.CaPem, token, "/api/assist/live/confirm", json).ConfigureAwait(true);
    }

    private async Task DeclineAsync(string id)
    {
        if (string.IsNullOrWhiteSpace(id))
        {
            return;
        }

        var token = _store.Session();
        if (string.IsNullOrWhiteSpace(token))
        {
            return;
        }

        var json = "{\"id\":\"" + id.Replace("\"", "", StringComparison.Ordinal) + "\"}";
        await BoxClient.PostAssistAsync(_store.BoxUrl, _store.Pin, _store.CaPem, token, "/api/assist/live/decline", json).ConfigureAwait(true);
    }

    private async Task TogglePauseAsync()
    {
        var token = _store.Session();
        if (string.IsNullOrWhiteSpace(token))
        {
            return;
        }

        var pause = !_snapshot.ObserverPaused;
        await BoxClient.SetObserverPausedAsync(_store.BoxUrl, _store.Pin, _store.CaPem, token, pause).ConfigureAwait(true);
    }

    private void OpenTwin()
    {
        var studio = ResolveStudio();
        if (studio is not null)
        {
            Process.Start(new ProcessStartInfo(studio) { UseShellExecute = true });
            return;
        }

        Process.Start(new ProcessStartInfo(BoxLink.WebHome(_store.BoxUrl)) { UseShellExecute = true });
    }

    private static string? ResolveStudio()
    {
        var beside = Path.Combine(AppContext.BaseDirectory, "Heirloom.exe");
        if (File.Exists(beside))
        {
            return beside;
        }

        var sibling = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "..", "Heirloom", "Heirloom.exe"));
        return File.Exists(sibling) ? sibling : null;
    }

    internal static void ApplyAutostart(bool enabled)
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        const string name = "Heirloom Companion";
        using var key = Microsoft.Win32.Registry.CurrentUser.OpenSubKey(
            @"Software\Microsoft\Windows\CurrentVersion\Run", writable: true);
        if (key is null)
        {
            return;
        }

        if (!enabled)
        {
            key.DeleteValue(name, throwOnMissingValue: false);
            return;
        }

        var exe = Environment.ProcessPath;
        if (!string.IsNullOrWhiteSpace(exe))
        {
            key.SetValue(name, "\"" + exe + "\"");
        }
    }

    private void OnUnauthorized()
    {
        _store.ClearSession();
        _authNotice = OwnerSession.SignedOutSignInAgain;
        try
        {
            var dispatcher = Application.Current?.Dispatcher;
            if (dispatcher is null || dispatcher.CheckAccess())
            {
                RebuildMenu();
                return;
            }

            dispatcher.Invoke(RebuildMenu);
        }
        catch (InvalidOperationException)
        {
        }
    }

    public void Dispose()
    {
        BoxClient.Unauthorized -= OnUnauthorized;
        _stop.Cancel();
        _hotkey.Dispose();
        _player.Dispose();
        _live.Shutdown();
        _caption.Close();
        _audio.Dispose();
        _screen.Dispose();
        _current?.Dispose();
        _icon.Dispose();
        _stop.Dispose();
    }
}
