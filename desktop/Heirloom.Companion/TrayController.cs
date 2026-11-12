using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Text.Json;
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
    private readonly WritingHotkey _writingHotkey = new();
    private AssistLiveView _assist = AssistLiveView.Empty;
    private string _shownCaptionId = "";
    private string _playedAudioId = "";
    private BoxSnapshot _snapshot = TrayStatus.Describe(false, null, BoxLink.DefaultBoxUrl, null);
    private bool? _wasReachable;
    private string _authNotice = "";
    private string _micStatus = "";
    private bool _wasCertificate;
    private TimeSpan _delay = PollSchedule.Healthy;
    private DateTimeOffset? _lastHealthLog;
    private string _lastHealthKey = "";
    private DateTimeOffset? _lastRenewAttempt;
    private readonly Func<CancellationToken, Task<bool>> _recover;
    private Icon? _current;
    private readonly CompanionLog _log = new(CompanionLog.DefaultDirectory());
    private readonly WakeHub _wake = new();
    private readonly SupervisedLoop _poll;
    private IDisposable? _signals;

    public TrayController()
    {
        _poll = new SupervisedLoop("health", _log, _wake);
        _audio = new AudioPump(_store, _log, _wake);
        _screen = new ScreenPump(_store, _log, _wake);
        _live = new TwinLiveWindow(_store);
        _live.ConfirmRequested += id => _ = ConfirmAsync(id);
        _live.DeclineRequested += id => _ = DeclineAsync(id);
        _live.TypedRequested += text => _ = SendTypedAsync(text);
        BoxClient.Unauthorized += OnUnauthorized;
        _recover = TryRecoverAsync;
        BoxClient.Recover = _recover;
    }

    public void Start()
    {
        ApplyAutostart(_store.Autostart);
        _hotkey.Pressed += () => _ = ArmPushToTalkAsync();
        _hotkey.Attach();
        _writingHotkey.Pressed += ShowWritingCard;
        _writingHotkey.Attach();
        _icon.ToolTipText = "Heirloom Twin Box";
        Paint(BoxLamp.Red);
        RebuildMenu();
        _icon.ForceCreate();
        _signals = MachineSignals.Attach(_wake);
        _ = _poll.RunAsync(PollOnceAsync, _stop.Token);
    }

    private async Task PollOnceAsync(CancellationToken cancellationToken)
    {
        HealthFrame? frame = null;
        await CompanionHealthPass.RunAsync(
            async ct => frame = await CollectAsync(ct).ConfigureAwait(false),
            () =>
            {
                if (frame is not null)
                {
                    ApplyFrame(frame);
                }
            },
            () => Application.Current?.Dispatcher.CheckAccess() == true,
            action =>
            {
                var dispatcher = Application.Current?.Dispatcher;
                if (dispatcher is null)
                {
                    return;
                }

                if (dispatcher.CheckAccess())
                {
                    action();
                    return;
                }

                dispatcher.Invoke(action);
            },
            cancellationToken).ConfigureAwait(false);
        if (frame is null)
        {
            return;
        }

        NoteHealth(frame);
        _wasReachable = frame.Snapshot.Reachable;
        _wasCertificate = frame.Snapshot.CertificateFailed;
        await Task.Delay(_delay, cancellationToken).ConfigureAwait(false);
    }

    private async Task<HealthFrame> CollectAsync(CancellationToken cancellationToken)
    {
        var url = _store.BoxUrl;
        var probe = await BoxClient.HealthAsync(url, _store.Pin, _store.CaPem, cancellationToken).ConfigureAwait(false);
        var next = TrayStatus.Describe(probe.Reachable, probe.LatencyMs, url, probe.Body, probe.Failure);
        var healthy = next.Lamp != BoxLamp.Red;
        _delay = PollSchedule.Next(_delay, healthy);
        _snapshot = next;
        _audio.Note(next);
        _screen.Note(next);
        await MaybeRenewAsync(cancellationToken).ConfigureAwait(false);
        var signedIn = !string.IsNullOrWhiteSpace(_store.Session());
        if (CompanionSync.ShouldPush(signedIn, _wasReachable, next.Reachable))
        {
            await PushSettingsAsync(cancellationToken).ConfigureAwait(false);
        }

        var restart = false;
        if (signedIn && next.Reachable)
        {
            restart = await PollCaretakerAsync(cancellationToken).ConfigureAwait(false);
        }

        var assist = await FetchAssistAsync(cancellationToken).ConfigureAwait(false);
        _micStatus = _audio.MicFault;
        var tip = string.IsNullOrWhiteSpace(_micStatus) ? next.Tooltip : next.Tooltip + "\n" + _micStatus;
        var toast = TakeToast(next);
        return new HealthFrame(next, tip, signedIn, toast, assist, restart);
    }

    private void ApplyFrame(HealthFrame frame)
    {
        if (frame.Toast is { } toast)
        {
            _icon.ShowNotification(toast.Title, toast.Body);
        }

        _icon.ToolTipText = frame.Tip;
        Paint(frame.Snapshot.Lamp);
        RebuildMenu();
        if (frame.Assist is { } assist)
        {
            ApplyAssist(assist);
        }

        if (frame.Restart)
        {
            CompanionProcess.Restart();
        }
    }

    private void NoteHealth(HealthFrame frame)
    {
        var key = frame.Snapshot.Reachable + "|" + frame.SignedIn + "|" + frame.Snapshot.Lamp;
        var now = DateTimeOffset.UtcNow;
        var changed = !string.Equals(key, _lastHealthKey, StringComparison.Ordinal);
        if (!HealthLog.ShouldWrite(_lastHealthLog, now, changed))
        {
            return;
        }

        _lastHealthKey = key;
        _lastHealthLog = now;
        _log.Write("health", HealthLog.Line(frame.Snapshot.Reachable, frame.SignedIn, frame.Snapshot.Lamp));
    }

    private async Task MaybeRenewAsync(CancellationToken cancellationToken)
    {
        var bundle = _store.Bundle();
        if (bundle is null || string.IsNullOrWhiteSpace(bundle.Session))
        {
            return;
        }

        var now = DateTimeOffset.UtcNow;
        var expires = SessionClock.Parse(bundle.ExpiresAt);
        if (!SessionClock.ShouldRenew(expires, now, bundle.HasRefresh))
        {
            return;
        }

        if (!SessionClock.AttemptDue(_lastRenewAttempt, now))
        {
            return;
        }

        _lastRenewAttempt = now;
        var next = await BoxClient.RefreshAsync(
            _store.BoxUrl,
            _store.Pin,
            _store.CaPem,
            bundle.Session,
            bundle.Refresh,
            cancellationToken).ConfigureAwait(false);
        if (next is not null)
        {
            _store.SaveBundle(next);
        }
    }

    private async Task<bool> TryRecoverAsync(CancellationToken cancellationToken)
    {
        var bundle = _store.Bundle();
        if (bundle is null)
        {
            return false;
        }

        var next = await BoxClient.RefreshAsync(
            _store.BoxUrl,
            _store.Pin,
            _store.CaPem,
            bundle.Session,
            bundle.Refresh,
            cancellationToken).ConfigureAwait(false);
        if (next is null)
        {
            var newer = _store.Bundle();
            return newer is not null
                && !string.IsNullOrWhiteSpace(newer.Session)
                && !string.Equals(newer.Session, bundle.Session, StringComparison.Ordinal);
        }

        _store.SaveBundle(next);
        _authNotice = "";
        return true;
    }

    private TrayToast? TakeToast(BoxSnapshot next)
    {
        if (!_store.Toasts || _wasReachable is null)
        {
            return null;
        }

        if (_wasReachable == next.Reachable && _wasCertificate == next.CertificateFailed)
        {
            return null;
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
        return new TrayToast(title, body);
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

    private async Task<bool> PollCaretakerAsync(CancellationToken cancellationToken)
    {
        var token = _store.Session();
        if (string.IsNullOrWhiteSpace(token))
        {
            return false;
        }

        var json = await BoxClient.GetCaretakerCompanionAsync(_store.BoxUrl, _store.Pin, _store.CaPem, token, cancellationToken).ConfigureAwait(true);
        if (!CaretakerGuard.WantsRepush(json) && !CaretakerGuard.WantsRestart(json))
        {
            return false;
        }

        if (CaretakerGuard.WantsRepush(json))
        {
            await PushSettingsAsync(cancellationToken).ConfigureAwait(true);
        }

        await BoxClient.AckCaretakerCompanionAsync(_store.BoxUrl, _store.Pin, _store.CaPem, token, cancellationToken).ConfigureAwait(true);
        return CaretakerGuard.WantsRestart(json);
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

    private async Task<AssistFetch?> FetchAssistAsync(CancellationToken cancellationToken)
    {
        var token = _store.Session();
        if (string.IsNullOrWhiteSpace(token) || !_snapshot.Reachable)
        {
            return null;
        }

        var json = await BoxClient.GetAssistLiveAsync(_store.BoxUrl, _store.Pin, _store.CaPem, token, cancellationToken).ConfigureAwait(false);
        var micJson = await BoxClient.GetAssistMicAsync(_store.BoxUrl, _store.Pin, _store.CaPem, token, cancellationToken).ConfigureAwait(false);
        if (json is null && micJson is null)
        {
            return null;
        }

        var view = json is null ? _assist : AssistLive.Parse(json);
        byte[]? wav = null;
        if (view.HasAudio && view.AudioId.Length > 0 && view.AudioId != _playedAudioId)
        {
            wav = await BoxClient.GetAssistAudioAsync(_store.BoxUrl, _store.Pin, _store.CaPem, token, view.AudioId, cancellationToken).ConfigureAwait(false);
        }

        return new AssistFetch(view, json is not null, MicTranscript.Parse(micJson), wav);
    }

    private void ApplyAssist(AssistFetch fetch)
    {
        if (fetch.ReplaceView)
        {
            _assist = fetch.View;
        }

        _live.Apply(fetch.View, fetch.Mic);
        if (fetch.View.CaptionId != _shownCaptionId)
        {
            _shownCaptionId = fetch.View.CaptionId;
            _caption.ShowCaption(fetch.View.Caption);
        }

        if (fetch.Wav is { Length: > 12 })
        {
            _playedAudioId = fetch.View.AudioId;
            _player.Play(fetch.Wav);
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

    private async Task SendTypedAsync(string text)
    {
        var words = (text ?? "").Trim();
        if (words.Length == 0)
        {
            return;
        }

        var token = _store.Session();
        if (string.IsNullOrWhiteSpace(token))
        {
            return;
        }

        var json = JsonSerializer.Serialize(new { text = words });
        await BoxClient.PostAssistAsync(
            _store.BoxUrl,
            _store.Pin,
            _store.CaPem,
            token,
            "/api/assist/live/say",
            json).ConfigureAwait(true);
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

        var plan = CompanionAutostart.Build(enabled, Environment.ProcessPath);
        try
        {
            using var key = Microsoft.Win32.Registry.CurrentUser.OpenSubKey(
                @"Software\Microsoft\Windows\CurrentVersion\Run", writable: true);
            if (key is null)
            {
                return;
            }

            foreach (var name in plan.Delete)
            {
                key.DeleteValue(name, throwOnMissingValue: false);
            }

            if (plan.WriteName is not null && plan.WriteValue is not null)
            {
                key.SetValue(plan.WriteName, plan.WriteValue);
            }
        }
        catch (Exception ex) when (ex is UnauthorizedAccessException or IOException or System.Security.SecurityException)
        {
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

    private void ShowWritingCard()
    {
        var dispatcher = Application.Current?.Dispatcher;
        if (dispatcher is not null && !dispatcher.CheckAccess())
        {
            dispatcher.Invoke(ShowWritingCard);
            return;
        }

        var selected = CaptureSelection();
        var card = new WritingCardWindow(selected);
        card.Show();
    }

    private static string CaptureSelection()
    {
        var before = "";
        try
        {
            if (Clipboard.ContainsText())
            {
                before = Clipboard.GetText();
            }
        }
        catch (System.Runtime.InteropServices.COMException)
        {
            return SelectionCapture.AfterCopy(false, "", "");
        }

        try
        {
            SendCopy();
            System.Threading.Thread.Sleep(80);
            var copied = Clipboard.ContainsText() ? Clipboard.GetText() : "";
            return SelectionCapture.AfterCopy(true, before, copied);
        }
        catch (System.Runtime.InteropServices.COMException)
        {
            return SelectionCapture.AfterCopy(false, before, "");
        }
    }

    private static void SendCopy()
    {
        const uint keyUp = 2;
        foreach (var (key, down) in CopyChord.Sequence())
        {
            keybd_event(key, 0, down ? 0 : keyUp, UIntPtr.Zero);
        }
    }

    [System.Runtime.InteropServices.DllImport("user32.dll")]
    private static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, UIntPtr dwExtraInfo);

    public void Dispose()
    {
        if (BoxClient.Recover == _recover)
        {
            BoxClient.Recover = null;
        }

        BoxClient.Unauthorized -= OnUnauthorized;
        _signals?.Dispose();
        _stop.Cancel();
        _hotkey.Dispose();
        _writingHotkey.Dispose();
        _player.Dispose();
        _live.Shutdown();
        _caption.Close();
        _audio.Dispose();
        _screen.Dispose();
        _current?.Dispose();
        _icon.Dispose();
        _stop.Dispose();
    }

    private sealed record TrayToast(string Title, string Body);

    private sealed record AssistFetch(AssistLiveView View, bool ReplaceView, MicTranscript? Mic, byte[]? Wav);

    private sealed record HealthFrame(
        BoxSnapshot Snapshot,
        string Tip,
        bool SignedIn,
        TrayToast? Toast,
        AssistFetch? Assist,
        bool Restart);
}
