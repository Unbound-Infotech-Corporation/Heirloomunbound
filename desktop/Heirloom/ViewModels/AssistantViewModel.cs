using System.Collections.ObjectModel;
using System.Text.Json;
using System.Text.RegularExpressions;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using Heirloom.Services;
using Microsoft.UI.Xaml;

namespace Heirloom.ViewModels;

public partial class AssistantViewModel : ObservableObject
{
    private const string EmptyDid = "Nothing run this sitting.";

    private readonly AppHost _host;
    private readonly MixerViewModel _mixer;
    private readonly object _jobGate = new();
    private readonly Queue<string> _jobs = new();
    private int _draining;
    private PendingJob? _pending;
    private double _lastLevel;
    private CancellationTokenSource? _jobCts;
    private int _sitting;
    private bool _pttOpen;

    public AssistantViewModel(AppHost host, MixerViewModel mixer)
    {
        _host = host;
        _mixer = mixer;
        SpeakReplies = host.Settings.Current.SpeakReplies;
        NewConversation();
    }

    public MixerViewModel Mixer => _mixer;
    public ObservableCollection<ChatLine> Lines { get; } = [];
    public ObservableCollection<string> Work { get; } = [];
    public event EventHandler<VideoJobIntent>? VideoStudioRequested;
    public Visibility PendingVis => HasPending ? Visibility.Visible : Visibility.Collapsed;
    public Visibility BusyVis => IsBusy ? Visibility.Visible : Visibility.Collapsed;

    [ObservableProperty] private string _draft = "";
    [ObservableProperty] private string _status = "Ready to work on this PC.";
    [ObservableProperty] private bool _isRecording;
    [ObservableProperty] private double _level;
    [ObservableProperty] private bool _speakReplies;
    [ObservableProperty] private bool _isBusy;
    [ObservableProperty] private bool _hasPending;
    [ObservableProperty] private string _pendingSummary = "";

    partial void OnSpeakRepliesChanged(bool value)
    {
        _host.Settings.Current.SpeakReplies = value;
        _host.Settings.Save();
    }

    partial void OnHasPendingChanged(bool value)
    {
        OnPropertyChanged(nameof(PendingVis));
        ConfirmCommand.NotifyCanExecuteChanged();
        CancelPendingCommand.NotifyCanExecuteChanged();
        StopJobCommand.NotifyCanExecuteChanged();
    }

    partial void OnIsBusyChanged(bool value)
    {
        OnPropertyChanged(nameof(BusyVis));
        StopJobCommand.NotifyCanExecuteChanged();
    }

    private bool CanStop() => IsBusy && !HasPending;

    [RelayCommand]
    public void NewConversation()
    {
        Interlocked.Increment(ref _sitting);
        if (_pttOpen)
        {
            _pttOpen = false;
            _host.Capture.LevelChanged -= OnLevel;
            _ = _host.Capture.StopPtt();
            IsRecording = false;
            Level = 0;
        }

        CancelJobToken();
        lock (_jobGate)
        {
            _jobs.Clear();
        }

        Lines.Clear();
        Work.Clear();
        Work.Add(EmptyDid);
        HasPending = false;
        PendingSummary = "";
        _pending = null;
        Lines.Add(new ChatLine(
            "assist",
            "I work on this PC. I am not the Twin — I do not speak as you. I open apps, read files in your profile, search the vault, see the screen if you allow it, and run skills you listed. Destructive shell and power wait for Confirm."));
        Status = "New job. Tell me what to do.";
    }

    [RelayCommand]
    public async Task SendAsync()
    {
        var text = Draft.Trim();
        if (text.Length == 0)
        {
            Status = "Type a job, or hold to speak.";
            return;
        }

        Draft = "";
        await TalkAsync(text).ConfigureAwait(true);
    }

    [RelayCommand]
    public void BeginPtt()
    {
        if (_pttOpen)
        {
            return;
        }

        _pttOpen = true;
        IsRecording = true;
        Status = "Recording…";
        _host.Capture.LevelChanged += OnLevel;
        _host.Capture.StartPtt();
        if (!_host.Capture.IsCapturing)
        {
            _host.Capture.LevelChanged -= OnLevel;
            _pttOpen = false;
            IsRecording = false;
            Status = string.IsNullOrWhiteSpace(_host.Capture.LastError)
                ? "Microphone did not open. Open Mixer and pick Chat Mic."
                : _host.Capture.LastError;
        }
    }

    [RelayCommand]
    public async Task EndPttAsync()
    {
        if (!_pttOpen)
        {
            return;
        }

        _pttOpen = false;
        _host.Capture.LevelChanged -= OnLevel;
        IsRecording = false;
        Level = 0;
        var wav = _host.Capture.StopPtt();
        if (wav.Length < 2048)
        {
            Status = string.IsNullOrWhiteSpace(_host.Capture.LastError)
                ? "No audio captured."
                : _host.Capture.LastError;
            return;
        }

        Status = "Transcribing…";
        SetNow("Transcribing the hold.");
        await _host.Whisper.EnsureAsync().ConfigureAwait(true);
        string? text = null;
        var whisperMiss = "";
        if (_host.Whisper.IsReady)
        {
            text = await _host.Whisper.TranscribeAsync(wav).ConfigureAwait(true);
        }
        else
        {
            whisperMiss = string.IsNullOrWhiteSpace(_host.Whisper.LastError)
                ? _host.Whisper.Status
                : _host.Whisper.LastError;
        }

        if (string.IsNullOrWhiteSpace(text))
        {
            using var stt = new CancellationTokenSource(TimeSpan.FromSeconds(20));
            var cloud = await _host.Api.PostMultipartAsync("/companion/voice", "ptt.wav", wav, cancellationToken: stt.Token).ConfigureAwait(true);
            if (cloud is { } json && json.TryGetProperty("transcript", out var t))
            {
                text = t.GetString();
            }
        }

        if (string.IsNullOrWhiteSpace(text))
        {
            var fact = VoiceMiss(whisperMiss);
            ClearNow();
            Lines.Add(new ChatLine("assist", fact));
            Status = fact;
            return;
        }

        ClearNow();
        await TalkAsync(text).ConfigureAwait(true);
    }

    [RelayCommand(CanExecute = nameof(HasPending))]
    public async Task ConfirmAsync()
    {
        if (_pending is null)
        {
            return;
        }

        var job = _pending;
        _pending = null;
        HasPending = false;
        PendingSummary = "";
        Status = "Confirmed. Working…";
        var sitting = _sitting;
        var token = ResetJobToken();
        Interlocked.Exchange(ref _draining, 1);
        IsBusy = true;
        SetNow("Running " + job.Tool + " after Confirm.");
        try
        {
            var result = await _host.Pc.RunAsync(job.Tool, job.Args, token).ConfigureAwait(true);
            if (sitting != _sitting)
            {
                return;
            }

            Note(job.Tool, result);
            job.Observations.Add(job.Tool + ": " + Trim(result.Detail, 1200));
            if (token.IsCancellationRequested)
            {
                SpeakStopped();
                return;
            }

            if (job.ContinueThink)
            {
                await ThinkAsync(job.UserText, job.Observations, token).ConfigureAwait(true);
            }
            else
            {
                var reply = result.Ok
                    ? "Done. " + Trim(result.Detail, 800)
                    : "That did not run: " + result.Detail;
                ClearNow();
                Lines.Add(new ChatLine("assist", reply));
                Status = result.Ok ? "Did the confirmed step." : "Confirmed step failed.";
                await MaybeSpeakAsync(reply).ConfigureAwait(true);
            }
        }
        catch (OperationCanceledException)
        {
            if (sitting == _sitting)
            {
                SpeakStopped();
            }
        }
        catch (Exception ex)
        {
            if (sitting != _sitting)
            {
                return;
            }

            ClearNow();
            Status = ex.Message;
            Lines.Add(new ChatLine("assist", "I hit a fault: " + ex.Message));
            FaultLog.Write("assist-confirm", ex.Message);
        }
        finally
        {
            IsBusy = false;
            Interlocked.Exchange(ref _draining, 0);
        }

        if (sitting == _sitting)
        {
            await DrainAsync().ConfigureAwait(true);
        }
    }

    [RelayCommand(CanExecute = nameof(HasPending))]
    public void CancelPending()
    {
        _pending = null;
        HasPending = false;
        PendingSummary = "";
        Status = "Cancelled. Nothing ran.";
        ClearNow();
        Lines.Add(new ChatLine("assist", "Cancelled. I did not run it."));
        _ = DrainAsync();
    }

    [RelayCommand(CanExecute = nameof(CanStop))]
    public void StopJob()
    {
        _jobCts?.Cancel();
        Status = "Stopping this job.";
        SetNow("Stopping this job.");
    }

    public async Task TalkAsync(string text)
    {
        Lines.Add(new ChatLine("you", text));
        lock (_jobGate)
        {
            _jobs.Enqueue(text);
        }

        if (HasPending)
        {
            Status = "Queued. Confirm or Cancel the waiting step first.";
            SetNow("Queued behind Confirm.");
            return;
        }

        await DrainAsync().ConfigureAwait(true);
    }

    private async Task DrainAsync()
    {
        if (HasPending)
        {
            return;
        }

        if (Interlocked.CompareExchange(ref _draining, 1, 0) != 0)
        {
            Status = "Queued behind the current job.";
            SetNow("Queued behind the current job.");
            return;
        }

        var sitting = _sitting;
        var token = ResetJobToken();
        IsBusy = true;
        try
        {
            while (!HasPending && !token.IsCancellationRequested && sitting == _sitting)
            {
                string job;
                lock (_jobGate)
                {
                    if (_jobs.Count == 0)
                    {
                        break;
                    }

                    job = _jobs.Dequeue();
                }

                Status = "Working…";
                SetNow("Working on this job.");
                try
                {
                    if (await TryDirectAsync(job, token).ConfigureAwait(true))
                    {
                        continue;
                    }

                    await ThinkAsync(job, null, token).ConfigureAwait(true);
                }
                catch (OperationCanceledException)
                {
                    if (sitting == _sitting)
                    {
                        SpeakStopped();
                    }

                    break;
                }
                catch (Exception ex)
                {
                    if (sitting != _sitting)
                    {
                        break;
                    }

                    ClearNow();
                    Status = ex.Message;
                    Lines.Add(new ChatLine("assist", "I hit a fault: " + ex.Message));
                    FaultLog.Write("assist-job", ex.Message);
                }
            }
        }
        finally
        {
            IsBusy = false;
            Interlocked.Exchange(ref _draining, 0);
        }

        if (token.IsCancellationRequested || sitting != _sitting)
        {
            return;
        }

        bool more;
        lock (_jobGate)
        {
            more = _jobs.Count > 0 && !HasPending;
        }

        if (more)
        {
            await DrainAsync().ConfigureAwait(true);
        }
    }

    private async Task<bool> TryDirectAsync(string text, CancellationToken cancellationToken)
    {
        var t = text.Trim();
        var lower = t.ToLowerInvariant();

        if (VideoIntent.TryParse(t, out var video))
        {
            SetNow(video.OpeningLine);
            Status = video.OpeningLine;
            try
            {
                await Task.Delay(280, cancellationToken).ConfigureAwait(true);
            }
            catch (OperationCanceledException)
            {
                ClearNow();
                Status = "Stopped.";
                return true;
            }

            VideoStudioRequested?.Invoke(this, video);
            ClearNow();
            Lines.Add(new ChatLine("work", video.DoneLine));
            Status = video.DoneLine;
            return true;
        }

        if (Regex.IsMatch(lower, @"^(what('?s| is) on (the |my )?clipboard|clipboard|paste that)$"))
        {
            return await ExecAsync("clipboard_get", [], t, continueThink: false, cancellationToken).ConfigureAwait(true);
        }

        var vol = Regex.Match(lower, @"(?:volume|set volume|session)\s*(?:to\s*)?(\d{1,3})");
        if (vol.Success)
        {
            return await ExecAsync("set_volume", Dict("level", vol.Groups[1].Value), t, continueThink: false, cancellationToken).ConfigureAwait(true);
        }

        if (lower is "play" or "pause" or "playpause"
            || (lower.Contains("music") && Regex.IsMatch(lower, @"\b(play|pause)\b")))
        {
            return await ExecAsync("media", Dict("action", "playpause"), t, continueThink: false, cancellationToken).ConfigureAwait(true);
        }

        if (lower.Contains("next track") || lower is "next")
        {
            return await ExecAsync("media", Dict("action", "next"), t, continueThink: false, cancellationToken).ConfigureAwait(true);
        }

        if (lower.Contains("previous") || lower is "prev")
        {
            return await ExecAsync("media", Dict("action", "previous"), t, continueThink: false, cancellationToken).ConfigureAwait(true);
        }

        if (Regex.IsMatch(lower, @"\bmute\b") && !lower.Contains("unmute"))
        {
            return await ExecAsync("media", Dict("action", "mute"), t, continueThink: false, cancellationToken).ConfigureAwait(true);
        }

        if (Regex.IsMatch(lower, @"lock (the )?(pc|computer|workstation|machine)"))
        {
            return await ExecAsync("power", Dict("action", "lock"), t, continueThink: false, cancellationToken).ConfigureAwait(true);
        }

        if (Regex.IsMatch(lower, @"(put (the )?(pc|computer|machine) to sleep|sleep (the )?(pc|computer|machine))"))
        {
            return await ExecAsync("power", Dict("action", "sleep"), t, continueThink: false, cancellationToken).ConfigureAwait(true);
        }

        if (Regex.IsMatch(lower, @"shut\s*down (the )?(pc|computer|machine)"))
        {
            return await ExecAsync("power", Dict("action", "shutdown"), t, continueThink: false, cancellationToken).ConfigureAwait(true);
        }

        if (Regex.IsMatch(lower, @"restart (the )?(pc|computer|machine)"))
        {
            return await ExecAsync("power", Dict("action", "restart"), t, continueThink: false, cancellationToken).ConfigureAwait(true);
        }

        if (Regex.IsMatch(lower, @"(see|look at|what.?s on) (the |my )?screen") || lower is "see screen")
        {
            return await ExecAsync("screenshot", [], t, continueThink: false, cancellationToken).ConfigureAwait(true);
        }

        if (Regex.IsMatch(lower, @"(what('?s| is) open|list windows|open windows)"))
        {
            return await ExecAsync("windows", [], t, continueThink: false, cancellationToken).ConfigureAwait(true);
        }

        if (Regex.IsMatch(lower, @"(system status|pc status|how is this (pc|machine)|machine status)"))
        {
            return await ExecAsync("system_status", [], t, continueThink: false, cancellationToken).ConfigureAwait(true);
        }

        if (WebIntent.TryParse(t, out var web))
        {
            return await ExecBrowseAsync(web, t, cancellationToken).ConfigureAwait(true);
        }

        var find = Regex.Match(t, @"(?:find|locate|search for) (?:the )?(?:file )?(.+)$", RegexOptions.IgnoreCase);
        if (find.Success && !lower.Contains("vault") && !lower.Contains("archive"))
        {
            return await ExecAsync("find_file", Dict("query", find.Groups[1].Value.Trim()), t, continueThink: false, cancellationToken).ConfigureAwait(true);
        }

        var vault = Regex.Match(t, @"(?:search|ask) (?:the )?(?:vault|archive)(?: for)? (.+)$", RegexOptions.IgnoreCase);
        if (vault.Success)
        {
            return await ExecAsync("search_vault", Dict("query", vault.Groups[1].Value.Trim()), t, continueThink: false, cancellationToken).ConfigureAwait(true);
        }

        var remember = Regex.Match(t, @"^(?:remember|file(?: this)?|note)[:\s]+(.+)$", RegexOptions.IgnoreCase);
        if (remember.Success)
        {
            return await ExecAsync("write_note", Dict("text", remember.Groups[1].Value.Trim()), t, continueThink: false, cancellationToken).ConfigureAwait(true);
        }

        var open = Regex.Match(t, @"^(?:open|launch|go to|browse|start)\s+(.+)$", RegexOptions.IgnoreCase);
        if (open.Success)
        {
            var target = open.Groups[1].Value.Trim();
            var resolved = LaunchTarget.Resolve(target);
            var tool = resolved.Kind == LaunchTarget.Kind.Url ? "open_url" : "open_app";
            var key = tool == "open_url" ? "url" : "name";
            return await ExecAsync(tool, Dict(key, target), t, continueThink: false, cancellationToken).ConfigureAwait(true);
        }

        var fetch = Regex.Match(t, @"^(?:fetch|read url|get)\s+(https?://\S+)$", RegexOptions.IgnoreCase);
        if (fetch.Success)
        {
            return await ExecAsync("fetch_url", Dict("url", fetch.Groups[1].Value), t, continueThink: false, cancellationToken).ConfigureAwait(true);
        }

        var read = Regex.Match(t, @"^(?:read(?: the)? file|open file|show file)\s+(.+)$", RegexOptions.IgnoreCase);
        if (read.Success)
        {
            return await ExecAsync("read_file", Dict("path", read.Groups[1].Value.Trim().Trim('"')), t, continueThink: false, cancellationToken).ConfigureAwait(true);
        }

        var list = Regex.Match(t, @"^(?:list(?: the)?(?: files in)?|ls|dir)\s+(.+)$", RegexOptions.IgnoreCase);
        if (list.Success)
        {
            return await ExecAsync("list_dir", Dict("path", list.Groups[1].Value.Trim().Trim('"')), t, continueThink: false, cancellationToken).ConfigureAwait(true);
        }

        var skill = Regex.Match(t, @"^(?:run skill|fire|trigger)\s+(.+)$", RegexOptions.IgnoreCase);
        if (skill.Success)
        {
            return await ExecAsync("run_skill", Dict("name", skill.Groups[1].Value.Trim()), t, continueThink: false, cancellationToken).ConfigureAwait(true);
        }

        return false;
    }

    private async Task ThinkAsync(string text, List<string>? seed, CancellationToken cancellationToken)
    {
        var observations = seed ?? [];
        for (var step = 0; step < 8; step++)
        {
            cancellationToken.ThrowIfCancellationRequested();
            Status = step == 0 && observations.Count == 0 ? "Thinking…" : "Step " + (step + 1) + "…";
            SetNow(Status);
            var plan = await PlanAsync(text, observations, cancellationToken).ConfigureAwait(true);
            if (plan is null)
            {
                if (observations.Count > 0)
                {
                    var summary = PlannerMiss(observations[^1]);
                    ClearNow();
                    Lines.Add(new ChatLine("assist", summary));
                    Status = "Stopped after tools.";
                    await MaybeSpeakAsync(summary).ConfigureAwait(true);
                    return;
                }

                await CloudFallbackAsync(text, observations, cancellationToken).ConfigureAwait(true);
                return;
            }

            if (!string.IsNullOrWhiteSpace(plan.Reply))
            {
                ClearNow();
                Lines.Add(new ChatLine("assist", plan.Reply.Trim()));
                Status = "Done.";
                await MaybeSpeakAsync(plan.Reply).ConfigureAwait(true);
                return;
            }

            if (string.IsNullOrWhiteSpace(plan.Tool))
            {
                continue;
            }

            if (AssistPlanner.NeedsConfirm(plan.Tool, plan.Args))
            {
                Hold(plan.Tool, plan.Args, text, observations, continueThink: true);
                return;
            }

            if (plan.Tool is "browse")
            {
                var label = plan.Arg("label");
                var query = plan.Arg("query");
                var action = plan.Arg("action");
                var working = action is "search" && query.Length > 0
                    ? WebIntent.SearchingLine(string.IsNullOrWhiteSpace(label) ? "Google" : label, query)
                    : string.IsNullOrWhiteSpace(label)
                        ? "Working in the browser…"
                        : WebIntent.NavigatingLine(label);
                if (!await PulseBrowseAsync(WebIntent.OpeningBrowser, working, cancellationToken).ConfigureAwait(true))
                {
                    SpeakStopped();
                    return;
                }
            }
            else
            {
                SetNow("Running " + plan.Tool + ".");
            }
            var result = await _host.Pc.RunAsync(plan.Tool, plan.Args, cancellationToken).ConfigureAwait(true);
            Note(plan.Tool, result);
            observations.Add(plan.Tool + ": " + Trim(result.Detail, 1200));
        }

        var last = observations.Count == 0
            ? "I could not finish that job with the tools on this PC."
            : "I stopped after several steps. Last: " + observations[^1];
        ClearNow();
        Lines.Add(new ChatLine("assist", last));
        Status = "Stopped at the step cap.";
    }

    private async Task<bool> ExecBrowseAsync(WebBrowseIntent web, string userText, CancellationToken cancellationToken)
    {
        var args = BrowseArgs(web);
        if (AssistPlanner.NeedsConfirm("browse", args))
        {
            Hold("browse", args, userText, [], continueThink: false);
            return true;
        }

        if (!await PulseBrowseAsync(web.OpeningLine, web.WorkingLine, cancellationToken).ConfigureAwait(true))
        {
            SpeakStopped();
            return true;
        }
        var result = await _host.Pc.RunAsync("browse", args, cancellationToken).ConfigureAwait(true);
        RememberDid(DateTime.Now.ToString("HH:mm:ss") + "  browse" + (result.Ok ? "  ok  " : "  fail  ") + Trim(result.Detail.Replace('\n', ' '), 80));
        var reply = result.Ok
            ? (string.IsNullOrWhiteSpace(web.DoneLine) ? result.Detail : web.DoneLine)
            : PolishedFail(web.FailLine, result.Detail);
        if (!result.Ok)
        {
            Lines.Add(new ChatLine("work", "browse failed — " + Trim(reply.Replace('\n', ' '), 160)));
        }

        ClearNow();
        Lines.Add(new ChatLine("assist", reply));
        Status = result.Ok ? web.DoneLine : reply;
        await MaybeSpeakAsync(reply).ConfigureAwait(true);
        return true;
    }

    private static Dictionary<string, string> BrowseArgs(WebBrowseIntent web)
    {
        var args = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
        {
            ["action"] = web.Action,
            ["url"] = web.Url,
            ["label"] = web.Label,
        };
        if (!string.IsNullOrWhiteSpace(web.Query))
        {
            args["query"] = web.Query;
        }

        if (!string.IsNullOrWhiteSpace(web.Engine))
        {
            args["engine"] = web.Engine;
        }

        if (!string.IsNullOrWhiteSpace(web.ThenAction))
        {
            args["then_action"] = web.ThenAction;
        }

        if (!string.IsNullOrWhiteSpace(web.ThenTarget))
        {
            args["then_target"] = web.ThenTarget;
            args["target"] = web.ThenTarget;
        }

        if (!string.IsNullOrWhiteSpace(web.ThenText))
        {
            args["then_text"] = web.ThenText;
            args["text"] = web.ThenText;
        }

        return args;
    }

    private static string PolishedFail(string failLine, string detail)
    {
        if (detail.Contains("Use this PC is off", StringComparison.OrdinalIgnoreCase)
            || detail.Contains("Heir mode", StringComparison.OrdinalIgnoreCase))
        {
            return detail;
        }

        if (LooksLikeHumanBrowseFail(detail))
        {
            return detail;
        }

        if (string.IsNullOrWhiteSpace(failLine))
        {
            return "Could not: " + detail;
        }

        return failLine;
    }

    private static bool LooksLikeHumanBrowseFail(string detail)
    {
        if (string.IsNullOrWhiteSpace(detail) || detail.Contains("Exception", StringComparison.Ordinal))
        {
            return false;
        }

        return detail.StartsWith("I could not", StringComparison.OrdinalIgnoreCase)
            || detail.StartsWith("No Heirloom", StringComparison.OrdinalIgnoreCase)
            || detail.StartsWith("Could not", StringComparison.OrdinalIgnoreCase)
            || detail.StartsWith("The page", StringComparison.OrdinalIgnoreCase)
            || detail.StartsWith("Microsoft Edge", StringComparison.OrdinalIgnoreCase)
            || detail.StartsWith("This PC blocked", StringComparison.OrdinalIgnoreCase)
            || detail.StartsWith("Need a", StringComparison.OrdinalIgnoreCase)
            || detail.StartsWith("Stopped", StringComparison.OrdinalIgnoreCase)
            || detail.StartsWith("Say what", StringComparison.OrdinalIgnoreCase)
            || detail.StartsWith("Nothing to", StringComparison.OrdinalIgnoreCase)
            || detail.StartsWith("Use this PC is off", StringComparison.OrdinalIgnoreCase);
    }

    private async Task<bool> PulseBrowseAsync(string opening, string working, CancellationToken cancellationToken)
    {
        var showOpening = !string.IsNullOrWhiteSpace(opening) && !string.Equals(opening, working, StringComparison.Ordinal);
        if (showOpening)
        {
            SetNow(opening);
            Status = opening;
            try
            {
                await Task.Delay(400, cancellationToken).ConfigureAwait(true);
            }
            catch (OperationCanceledException)
            {
                return false;
            }
        }

        SetNow(working);
        Status = working;
        return true;
    }

    private async Task<bool> ExecAsync(
        string tool,
        Dictionary<string, string> args,
        string userText,
        bool continueThink,
        CancellationToken cancellationToken,
        string? now = null)
    {
        if (AssistPlanner.NeedsConfirm(tool, args))
        {
            Hold(tool, args, userText, [], continueThink);
            return true;
        }

        SetNow(string.IsNullOrWhiteSpace(now) ? "Running " + tool + "." : now);
        var result = await _host.Pc.RunAsync(tool, args, cancellationToken).ConfigureAwait(true);
        Note(tool, result);
        var reply = result.Ok ? Trim(result.Detail, 1200) : "Could not: " + result.Detail;
        ClearNow();
        Lines.Add(new ChatLine("assist", reply));
        Status = result.Ok ? "Did " + tool + "." : tool + " failed.";
        await MaybeSpeakAsync(reply).ConfigureAwait(true);
        return true;
    }

    private void Hold(string tool, Dictionary<string, string> args, string userText, List<string> observations, bool continueThink)
    {
        _pending = new PendingJob(tool, args, userText, observations, continueThink);
        HasPending = true;
        PendingSummary = tool + " — " + string.Join(" ", args.Select(kv => kv.Key + "=" + Trim(kv.Value, 80)));
        Status = "Confirm to run this. It will not run until you press Confirm.";
        SetNow("Waiting for Confirm: " + PendingSummary);
        Lines.Add(new ChatLine("assist", "I need Confirm before I run: " + PendingSummary + ". Confirm is in this document. Cancel leaves it unrun."));
    }

    private async Task<AssistPlan?> PlanAsync(string user, List<string> observations, CancellationToken cancellationToken)
    {
        var system = """
You are the Heirloom Assistant on this Windows PC. You work FOR the owner. You are not their digital twin and you never speak in their first person.

Return ONLY one JSON object.
To act: {"tool":"name","url":"...","name":"...","level":"50","action":"...","text":"...","query":"...","path":"...","command":"...","target":"...","amount":"..."}
When finished: {"reply":"short fact of what you did or found"}
If you must both act and talk, put the tool in and omit reply until the tool has run.

Tools: browse, open_url, open_app, set_volume, media, clipboard_get, clipboard_set, type_text, find_file, list_dir, read_file, write_note, search_vault, shell, power, screenshot, system_status, windows, fetch_url, run_skill.
browse actions: open (owner's default browser — Gmail/YouTube stay signed in), search, goto (separate Heirloom Edge window), click, type, scroll, snapshot, close.
For “open YouTube / Gmail / a site” or “search Google for …”, use browse action=open or search. That uses the owner's usual browser.
click/type/scroll/goto use a separate Heirloom Edge window that may not be signed in. Prefer open/search for Gmail, YouTube, and Google search.
Confirm is required for buying, paying, deleting, or typing a password.
Prefer tools over guessing. Do not invent files or biography. Keep replies to a few sentences.
""";
        var prompt = "OWNER ASKED:\n" + user + "\n\nALREADY DONE:\n" +
                     (observations.Count == 0 ? "(nothing yet)" : string.Join("\n", observations));
        await _host.Ollama.ProbeAsync(cancellationToken).ConfigureAwait(true);
        var model = _host.Ollama.ChatModel;
        if (_host.Ollama.IsReachable && !string.IsNullOrWhiteSpace(model))
        {
            using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
            timeout.CancelAfter(TimeSpan.FromSeconds(45));
            var first = await _host.Ollama.CompleteDetailedAsync(model, prompt, system, timeout.Token).ConfigureAwait(true);
            var plan = AssistPlanner.Parse(first.Text);
            if (plan is not null)
            {
                return plan;
            }

            var second = await _host.Ollama.CompleteDetailedAsync(model, prompt + "\n\nReturn JSON only.", system, timeout.Token).ConfigureAwait(true);
            plan = AssistPlanner.Parse(second.Text);
            if (plan is not null)
            {
                return plan;
            }
        }

        return null;
    }

    private async Task CloudFallbackAsync(string text, List<string> observations, CancellationToken cancellationToken)
    {
        var payload = text;
        if (observations.Count > 0)
        {
            payload = text + "\n\nAlready on this PC:\n" + string.Join("\n", observations);
        }

        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        timeout.CancelAfter(TimeSpan.FromSeconds(25));
        var cloud = await _host.Api.PostAsync("/desktop/chat", new { text = payload, mode = "assistant" }, timeout.Token).ConfigureAwait(true);
        string? reply = null;
        if (cloud is { } json)
        {
            if (json.TryGetProperty("reply", out var r))
            {
                reply = r.GetString();
            }

            if (json.TryGetProperty("tool_trace", out var trace) && trace.ValueKind == JsonValueKind.Array)
            {
                foreach (var item in trace.EnumerateArray())
                {
                    var name = item.TryGetProperty("name", out var n) ? n.GetString() : "tool";
                    RememberDid(DateTime.Now.ToString("HH:mm:ss") + "  " + name);
                }
            }
        }

        reply ??= SilenceCopy(observations);
        ClearNow();
        Lines.Add(new ChatLine("assist", reply));
        Status = "Answered.";
        await MaybeSpeakAsync(reply).ConfigureAwait(true);
    }

    private string SilenceCopy(List<string> observations)
    {
        var local = _host.Ollama.LastError;
        var cloud = _host.Api.LastFailure;
        if (observations.Count > 0)
        {
            var why = FirstFact(local, cloud, "The planner stopped.");
            return why + " I still did: " + observations[^1];
        }

        var miss = FirstFact(local, cloud, "No local model and no cloud reply.");
        return miss + " Direct orders still run without a model: open YouTube, open Gmail, search Google for weather, open notepad, find a file, system status.";
    }

    private string PlannerMiss(string lastObservation)
    {
        var why = FirstFact(_host.Ollama.LastError, _host.Api.LastFailure, "Local planner stopped.");
        return why + " I still did: " + lastObservation;
    }

    private string VoiceMiss(string whisperMiss)
    {
        if (!string.IsNullOrWhiteSpace(whisperMiss) && string.IsNullOrWhiteSpace(_host.Api.LastFailure))
        {
            return whisperMiss + " Cloud speech-to-text also returned nothing.";
        }

        if (!string.IsNullOrWhiteSpace(whisperMiss))
        {
            return whisperMiss + " Cloud: " + _host.Api.LastFailure;
        }

        if (!string.IsNullOrWhiteSpace(_host.Api.LastFailure))
        {
            return "Local speech-to-text heard nothing. Cloud: " + _host.Api.LastFailure;
        }

        if (!string.IsNullOrWhiteSpace(_host.Whisper.LastError) && !_host.Whisper.IsReady)
        {
            return _host.Whisper.LastError;
        }

        return "No speech in that hold. Watch the gold bar move, then release.";
    }

    private void Note(string tool, ToolResult result)
    {
        var line = DateTime.Now.ToString("HH:mm:ss") + "  " + tool + (result.Ok ? "  ok" : "  fail") + "  " + Trim(result.Detail.Replace('\n', ' '), 80);
        RememberDid(line);
        Lines.Add(new ChatLine("work", tool + (result.Ok ? "" : " failed") + " — " + Trim(result.Detail.Replace('\n', ' '), 160)));
    }

    private void RememberDid(string line)
    {
        if (Work.Count == 1 && Work[0] == EmptyDid)
        {
            Work.Clear();
        }

        Work.Insert(0, line);
        while (Work.Count > 40)
        {
            Work.RemoveAt(Work.Count - 1);
        }
    }

    private void SetNow(string text)
    {
        for (var i = Lines.Count - 1; i >= 0; i--)
        {
            if (Lines[i].Role == "now")
            {
                Lines.RemoveAt(i);
                break;
            }
        }

        Lines.Add(new ChatLine("now", text));
    }

    private void ClearNow()
    {
        for (var i = Lines.Count - 1; i >= 0; i--)
        {
            if (Lines[i].Role == "now")
            {
                Lines.RemoveAt(i);
                break;
            }
        }
    }

    private void SpeakStopped()
    {
        ClearNow();
        Status = "Stopped.";
        Lines.Add(new ChatLine("assist", "Stopped. Nothing further ran on this job."));
    }

    private CancellationToken ResetJobToken()
    {
        _jobCts?.Dispose();
        _jobCts = new CancellationTokenSource();
        return _jobCts.Token;
    }

    private void CancelJobToken()
    {
        try
        {
            _jobCts?.Cancel();
        }
        catch
        {
            // Token already disposed.
        }

        _jobCts?.Dispose();
        _jobCts = null;
    }

    private async Task MaybeSpeakAsync(string reply)
    {
        if (SpeakReplies && _host.Settings.Current.AllowSpeak && !string.IsNullOrWhiteSpace(reply))
        {
            await _host.Speak.SpeakAsync(Trim(reply, 400)).ConfigureAwait(true);
        }
    }

    private void OnLevel(object? sender, float value)
    {
        if (Math.Abs(value - _lastLevel) < 0.03)
        {
            return;
        }

        _lastLevel = value;
        UiDispatch.Post(() => Level = value);
    }

    private static string FirstFact(string first, string second, string fallback)
    {
        if (!string.IsNullOrWhiteSpace(first))
        {
            return first;
        }

        if (!string.IsNullOrWhiteSpace(second))
        {
            return second;
        }

        return fallback;
    }

    private static Dictionary<string, string> Dict(string key, string value) =>
        new(StringComparer.OrdinalIgnoreCase) { [key] = value };

    private static string Trim(string text, int max) =>
        string.IsNullOrEmpty(text) ? "" : text.Length <= max ? text : text[..max] + "…";

    private sealed record PendingJob(
        string Tool,
        Dictionary<string, string> Args,
        string UserText,
        List<string> Observations,
        bool ContinueThink);
}
