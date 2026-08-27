using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using Heirloom.Services;

using Microsoft.UI.Xaml;

namespace Heirloom.ViewModels;

public sealed class ChatLine
{
    public ChatLine(string role, string text, string citation = "")
    {
        Role = role;
        Text = text;
        Citation = citation;
        var you = role == "you";
        var meta = role is "now" or "work";
        YouVis = you ? Visibility.Visible : Visibility.Collapsed;
        MetaVis = meta ? Visibility.Visible : Visibility.Collapsed;
        OtherVis = !you && !meta ? Visibility.Visible : Visibility.Collapsed;
        CiteVis = string.IsNullOrWhiteSpace(citation) ? Visibility.Collapsed : Visibility.Visible;
    }

    public string Role { get; }
    public string Text { get; }
    public string Citation { get; }
    public string RoleLabel => Role switch
    {
        "you" => "You",
        "twin" => "Twin",
        "work" => "Did",
        "now" => "Now",
        _ => "Assist",
    };
    public bool IsYou => Role == "you";
    public bool IsMeta => Role is "now" or "work";
    public bool IsOther => !IsYou && !IsMeta;
    public bool HasCitation => !string.IsNullOrWhiteSpace(Citation);
    public Visibility YouVis { get; }
    public Visibility MetaVis { get; }
    public Visibility OtherVis { get; }
    public Visibility CiteVis { get; }
    public string Display =>
        RoleLabel + "  ·  " + Text
        + (HasCitation ? "\n" + Citation : "");
}

public partial class TwinViewModel : ObservableObject
{
    private readonly AppHost _host;

    public TwinViewModel(AppHost host, MixerViewModel mixer)
    {
        _host = host;
        Mixer = mixer;
        SpeakReplies = host.Settings.Current.SpeakReplies;
        Persona = host.Settings.Current.TwinPersona;
        GroundedOnly = host.CanEdit
            ? host.Settings.Current.GroundedOnly
            : true;
        ApplyAudience();
        NewConversation();
    }

    public MixerViewModel Mixer { get; }
    public PhoneViewModel? Phone { get; set; }
    public ObservableCollection<ChatLine> Lines { get; } = [];
    public IReadOnlyList<string> Personas { get; } = ["family", "formal", "full"];
    public bool CanEdit => _host.CanEdit;
    public event EventHandler? Filed;
    public event EventHandler<VideoJobIntent>? VideoStudioRequested;
    public string LastOfferScript => _lastTwinReply;

    public void ApplyAudience()
    {
        OnPropertyChanged(nameof(CanEdit));
        if (!CanEdit && !GroundedOnly)
        {
            GroundedOnly = true;
        }
    }

    [ObservableProperty] private string _draft = "";
    [ObservableProperty] private string _status = "Ready";
    [ObservableProperty] private bool _isRecording;
    [ObservableProperty] private double _level;
    [ObservableProperty] private string _avatarState = "listening";
    [ObservableProperty] private bool _groundedOnly;
    [ObservableProperty] private bool _speakReplies;
    [ObservableProperty] private string _persona = "family";
    [ObservableProperty] private string _lastCitation = "No memories cited yet.";
    [ObservableProperty] private bool _isBusy;
    [ObservableProperty] private bool _canOfferVideo;
    [ObservableProperty] private bool _hasPending;
    [ObservableProperty] private string _pendingSummary = "";
    private PhoneCallIntent? _pendingCall;
    private long _lastFiled;
    private string _lastTwinReply = "";
    private readonly object _jobGate = new();
    private readonly Queue<string> _jobs = new();
    private int _draining;
    private CancellationTokenSource? _jobCts;
    private int _sitting;
    private bool _pttOpen;

    partial void OnGroundedOnlyChanged(bool value)
    {
        if (!CanEdit && !value)
        {
            GroundedOnly = true;
            Status = "Heir sitting. Grounded only — the archive cannot infer.";
            return;
        }

        _host.Settings.Current.GroundedOnly = value;
        _host.Settings.Save();
        Status = value
            ? "Vault only. The twin will not invent."
            : "May infer. Do not leave this on for an heir.";
    }

    partial void OnSpeakRepliesChanged(bool value)
    {
        _host.Settings.Current.SpeakReplies = value;
        _host.Settings.Save();
    }

    partial void OnPersonaChanged(string value)
    {
        _host.Settings.Current.TwinPersona = value;
        _host.Settings.Save();
    }

    public Visibility BusyVis => IsBusy ? Visibility.Visible : Visibility.Collapsed;
    public Visibility OfferVideoVis => CanOfferVideo ? Visibility.Visible : Visibility.Collapsed;
    public Visibility PendingVis => HasPending ? Visibility.Visible : Visibility.Collapsed;

    partial void OnIsBusyChanged(bool value)
    {
        OnPropertyChanged(nameof(BusyVis));
        StopJobCommand.NotifyCanExecuteChanged();
    }

    partial void OnHasPendingChanged(bool value)
    {
        OnPropertyChanged(nameof(PendingVis));
        ConfirmCommand.NotifyCanExecuteChanged();
        CancelPendingCommand.NotifyCanExecuteChanged();
        StopJobCommand.NotifyCanExecuteChanged();
    }

    partial void OnCanOfferVideoChanged(bool value)
    {
        OnPropertyChanged(nameof(OfferVideoVis));
        MakeVideoOfLastCommand.NotifyCanExecuteChanged();
    }

    private bool CanStop() => IsBusy && !HasPending;

    [RelayCommand(CanExecute = nameof(HasPending))]
    public async Task ConfirmAsync()
    {
        if (_pendingCall is null || !_pendingCall.Resolved)
        {
            ClearPending();
            return;
        }

        var job = _pendingCall;
        ClearPending();
        if (!CanEdit)
        {
            var heir = "Heir sitting cannot place a call as the Twin.";
            Lines.Add(new ChatLine("work", heir));
            Status = heir;
            return;
        }

        if (Phone is null)
        {
            Status = "Open Phone, then confirm the call.";
            Lines.Add(new ChatLine("work", Status));
            return;
        }

        IsBusy = true;
        SetNow("Placing the call…");
        Status = "Placing the call…";
        try
        {
            var result = await Phone.DialAsync(job.ToE164, job.ContactName).ConfigureAwait(true);
            ClearNow();
            Lines.Add(new ChatLine("work", result));
            Status = result;
            AvatarState = "listening";
        }
        catch (Exception ex)
        {
            ClearNow();
            Status = ex.Message;
            Lines.Add(new ChatLine("work", "The call did not start: " + ex.Message));
            AvatarState = "listening";
        }
        finally
        {
            IsBusy = false;
        }

        await DrainAsync().ConfigureAwait(true);
    }

    [RelayCommand(CanExecute = nameof(HasPending))]
    public void CancelPending()
    {
        ClearPending();
        Status = "Cancelled. No call was placed.";
        ClearNow();
        Lines.Add(new ChatLine("work", "Cancelled. I did not place the call."));
        AvatarState = "listening";
        _ = DrainAsync();
    }

    private void ClearPending()
    {
        _pendingCall = null;
        HasPending = false;
        PendingSummary = "";
    }

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

        try { _jobCts?.Cancel(); } catch { /* disposed */ }
        _jobCts?.Dispose();
        _jobCts = null;
        lock (_jobGate)
        {
            _jobs.Clear();
        }

        ClearPending();
        Lines.Clear();
        Lines.Add(new ChatLine(
            "twin",
            !CanEdit
                ? "This is the archive speaking. I will only use what was filed. I cannot add to it. If I don't remember, I'll say so."
                : "I'm here. Hold to talk, or type. I only remember what you file — a fluent answer is not a memory. If I don't know, I'll say so."));
        LastCitation = "New conversation. Ask does not file. Use File this sitting to keep a turn.";
        Status = CanEdit
            ? "New sitting. Ask retrieves. File this sitting keeps a turn."
            : "Heir sitting. Read-only archive.";
        AvatarState = "listening";
        _lastTwinReply = "";
        CanOfferVideo = false;
    }

    [RelayCommand]
    public async Task SendAsync()
    {
        var text = Draft.Trim();
        if (text.Length == 0)
        {
            Status = "Type a sentence or hold to speak.";
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
        AvatarState = "listening";
        Status = "Recording…";
        _host.Capture.LevelChanged += OnLevel;
        _host.Capture.StartPtt();
        if (!_host.Capture.IsCapturing)
        {
            _host.Capture.LevelChanged -= OnLevel;
            _pttOpen = false;
            IsRecording = false;
            Status = string.IsNullOrWhiteSpace(_host.Capture.LastError)
                ? "Microphone did not open."
                : _host.Capture.LastError;
            AvatarState = "listening";
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
                ? "No audio captured. Open Mixer, pick Chat Mic, hold longer, and watch the level move."
                : _host.Capture.LastError;
            AvatarState = "listening";
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
            Lines.Add(new ChatLine("twin", fact));
            Status = fact;
            AvatarState = "listening";
            return;
        }

        ClearNow();
        await TalkAsync(text).ConfigureAwait(true);
    }

    public async Task SpeakAsync(string text) => await _host.Speak.SpeakAsync(text).ConfigureAwait(true);

    [RelayCommand(CanExecute = nameof(CanStop))]
    public void StopJob()
    {
        _jobCts?.Cancel();
        Status = "Stopping this sitting.";
        SetNow("Stopping this sitting.");
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
            Status = "Queued. Confirm or Do not run the waiting call first.";
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
            Status = "Queued behind the current sitting.";
            SetNow("Queued behind the current sitting.");
            return;
        }

        var sitting = _sitting;
        _jobCts?.Dispose();
        _jobCts = new CancellationTokenSource();
        var token = _jobCts.Token;
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

                await AnswerAsync(job, token).ConfigureAwait(true);
            }
        }
        catch (OperationCanceledException)
        {
            if (sitting == _sitting)
            {
                ClearNow();
                Status = "Stopped.";
                Lines.Add(new ChatLine("twin", "Stopped. I did not finish that answer."));
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

    private async Task AnswerAsync(string text, CancellationToken cancellationToken)
    {
        if (await TryPhoneAsync(text).ConfigureAwait(true))
        {
            return;
        }

        if (await TryVideoStudioAsync(text, cancellationToken).ConfigureAwait(true))
        {
            return;
        }

        Status = "Thinking…";
        AvatarState = "thinking";
        SetNow("Thinking from what you filed.");

        if (await TryOwnerBrowseAsync(text, cancellationToken).ConfigureAwait(true))
        {
            return;
        }

        var grounded = GroundedOnly || !CanEdit;
        var audience = CanEdit ? "owner" : "heir";
        var core = TwinPrompt.CoreFrom(
            Persona,
            _host.Settings.Current.PersonalityNotes,
            _host.Settings.Current.ValuesNotes);
        var pack = _host.Vault.BuildPack(text, core, grounded, audience);
        LastCitation = pack.CitationLine;

        await FireMatchingSkillsAsync(text).ConfigureAwait(true);
        cancellationToken.ThrowIfCancellationRequested();

        var system = TwinPrompt.System(pack, "");
        var prompt = "THEY SAID:\n" + text;

        string? reply = null;
        if (grounded && !pack.HasPassages)
        {
            reply = TwinPrompt.MissReply(grounded);
        }

        if (string.IsNullOrWhiteSpace(reply))
        {
            await _host.Ollama.ProbeAsync(cancellationToken).ConfigureAwait(true);
            var model = _host.Ollama.ChatModel;
            if (_host.Ollama.IsReachable && !string.IsNullOrWhiteSpace(model))
            {
                using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
                timeout.CancelAfter(TimeSpan.FromSeconds(50));
                var local = await _host.Ollama.CompleteDetailedAsync(model, prompt, system, timeout.Token).ConfigureAwait(true);
                reply = local.Text;
            }
        }

        if (string.IsNullOrWhiteSpace(reply) && (!grounded || pack.HasPassages))
        {
            using var cloudTimeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
            cloudTimeout.CancelAfter(TimeSpan.FromSeconds(25));
            var cloud = await _host.Api.PostAsync(
                "/desktop/chat",
                new { text, mode = "twin", grounded, persona = Persona, twin_pack = pack.ToWire() },
                cloudTimeout.Token).ConfigureAwait(true);
            if (cloud is { } json && json.TryGetProperty("reply", out var r))
            {
                reply = r.GetString();
            }
        }

        if (string.IsNullOrWhiteSpace(reply) && pack.HasPassages)
        {
            reply = QuoteFiled(pack.Passages);
        }

        if (string.IsNullOrWhiteSpace(reply) && grounded)
        {
            reply = TwinPrompt.MissReply(true);
        }

        reply ??= TwinSilence();
        var citation = pack.HasPassages ? "Grounded in: " + LastCitation : LastCitation;
        ClearNow();
        Lines.Add(new ChatLine("twin", reply, citation));
        _lastTwinReply = reply.Trim();
        CanOfferVideo = CanEdit
            && _lastTwinReply.Length >= 40
            && !_lastTwinReply.Contains("don't remember", StringComparison.OrdinalIgnoreCase);
        Status = pack.HasPassages
            ? "Answered from " + LastCitation
            : grounded
                ? "Nothing matched. I did not treat a guess as a memory."
                : "May infer. Vault had no match. Do not leave this on for an heir.";
        if (CanOfferVideo)
        {
            Status += " I can make a video of that.";
        }
        AvatarState = "speaking";
        Filed?.Invoke(this, EventArgs.Empty);
        if (SpeakReplies && _host.Settings.Current.AllowSpeak)
        {
            await _host.Speak.SpeakAsync(reply).ConfigureAwait(true);
        }

        AvatarState = "listening";
    }

    private bool CanMakeVideoOfLast() => CanEdit && !string.IsNullOrWhiteSpace(_lastTwinReply);

    [RelayCommand(CanExecute = nameof(CanMakeVideoOfLast))]
    public void MakeVideoOfLast()
    {
        if (!CanEdit)
        {
            Status = "Heir sitting cannot make a new video.";
            return;
        }

        if (string.IsNullOrWhiteSpace(_lastTwinReply))
        {
            Status = "Ask something first, then make a video of the answer.";
            return;
        }

        if (!VideoIntent.TryParse("make a video of that", out var intent))
        {
            return;
        }

        Lines.Add(new ChatLine("work", "Opening Video studio with that answer. This does not file a memory."));
        Status = intent.DoneLine;
        VideoStudioRequested?.Invoke(this, intent);
    }

    private async Task<bool> TryPhoneAsync(string text)
    {
        if (Phone is not null)
        {
            await Phone.EnsureLoadedAsync().ConfigureAwait(true);
        }

        var contacts = Phone?.Contacts;
        if (!PhoneIntent.TryParse(text, contacts, out var intent))
        {
            return false;
        }

        if (!CanEdit)
        {
            ClearNow();
            var heir = "Heir sitting cannot place a call as the Twin.";
            Lines.Add(new ChatLine("work", heir));
            Status = heir;
            AvatarState = "listening";
            return true;
        }

        if (!intent.Resolved)
        {
            ClearNow();
            Lines.Add(new ChatLine("work", intent.Summary));
            Status = intent.Summary;
            AvatarState = "listening";
            return true;
        }

        _pendingCall = intent;
        HasPending = true;
        PendingSummary = intent.Summary;
        ClearNow();
        SetNow("Waiting for Confirm: " + intent.Summary);
        Lines.Add(new ChatLine(
            "work",
            "I need Confirm before I place this call: " + intent.Summary
                + " Confirm is in this document. Do not run leaves it unplaced."));
        Status = "Waiting for Confirm in this document.";
        AvatarState = "listening";
        return true;
    }

    private async Task<bool> TryVideoStudioAsync(string text, CancellationToken cancellationToken)
    {
        if (!VideoIntent.TryParse(text, out var intent))
        {
            return false;
        }

        if (!CanEdit && intent.Action == "film")
        {
            ClearNow();
            var heir = "Heir sitting cannot make a new video. Play what was already filed in Video studio.";
            Lines.Add(new ChatLine("work", heir));
            Status = heir;
            AvatarState = "listening";
            VideoStudioRequested?.Invoke(this, VideoIntent.TryParse("open video studio", out var open) ? open : intent);
            return true;
        }

        if (intent.UseLastReply && string.IsNullOrWhiteSpace(_lastTwinReply))
        {
            ClearNow();
            var miss = "Ask something first, then say make a video of that.";
            Lines.Add(new ChatLine("work", miss));
            Status = miss;
            AvatarState = "listening";
            return true;
        }

        SetNow(intent.OpeningLine);
        Status = intent.OpeningLine;
        try
        {
            await Task.Delay(280, cancellationToken).ConfigureAwait(true);
        }
        catch (OperationCanceledException)
        {
            ClearNow();
            Status = "Stopped.";
            AvatarState = "listening";
            return true;
        }

        ClearNow();
        Lines.Add(new ChatLine("work", intent.DoneLine + " This does not file a memory."));
        Status = intent.DoneLine;
        AvatarState = "listening";
        VideoStudioRequested?.Invoke(this, intent);
        return true;
    }

    private async Task<bool> TryOwnerBrowseAsync(string text, CancellationToken cancellationToken)
    {
        if (!WebIntent.TryParse(text, out var intent) || WebIntent.NeedsPageControl(text))
        {
            return false;
        }

        if (!CanEdit)
        {
            ClearNow();
            var heir = "Heir mode. This sitting cannot open the browser. That stays with Assist on the owner’s PC.";
            Lines.Add(new ChatLine("work", heir));
            Status = heir;
            AvatarState = "listening";
            return true;
        }

        if (!_host.Settings.Current.AllowPcControl)
        {
            ClearNow();
            var off = "Opening the browser is Assist’s job, and Use this PC is off. Turn it on in Abilities.";
            Lines.Add(new ChatLine("work", off));
            Status = off;
            AvatarState = "listening";
            return true;
        }

        var showOpening = !string.Equals(intent.OpeningLine, intent.WorkingLine, StringComparison.Ordinal);
        if (showOpening)
        {
            SetNow(intent.OpeningLine);
            Status = intent.OpeningLine;
            try
            {
                await Task.Delay(400, cancellationToken).ConfigureAwait(true);
            }
            catch (OperationCanceledException)
            {
                ClearNow();
                Status = "Stopped.";
                AvatarState = "listening";
                return true;
            }
        }

        SetNow(intent.WorkingLine);
        Status = intent.WorkingLine;
        var args = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
        {
            ["action"] = intent.Action,
            ["url"] = intent.Url,
            ["label"] = intent.Label,
        };
        if (!string.IsNullOrWhiteSpace(intent.Query))
        {
            args["query"] = intent.Query;
        }

        var result = await _host.Pc.RunAsync("browse", args, cancellationToken).ConfigureAwait(true);
        ClearNow();
        var fact = result.Ok ? intent.DoneLine : PolishedTwinFail(intent.FailLine, result.Detail);
        Lines.Add(new ChatLine("work", fact));
        Status = result.Ok ? intent.DoneLine : fact;
        AvatarState = "listening";
        if (SpeakReplies && _host.Settings.Current.AllowSpeak)
        {
            await _host.Speak.SpeakAsync(fact).ConfigureAwait(true);
        }

        return true;
    }

    private static string PolishedTwinFail(string failLine, string detail)
    {
        if (detail.Contains("Use this PC is off", StringComparison.OrdinalIgnoreCase)
            || detail.Contains("Heir mode", StringComparison.OrdinalIgnoreCase))
        {
            return detail;
        }

        return string.IsNullOrWhiteSpace(failLine) ? detail : failLine;
    }

    private static string QuoteFiled(IReadOnlyList<TwinPassage> cites) =>
        "From what you filed:\n\n" + string.Join("\n\n", cites.Select(c => c.Text.Trim()));

    [RelayCommand]
    public void FileSitting()
    {
        if (!CanEdit)
        {
            Status = "Heir mode. The vault is locked.";
            return;
        }

        var turns = Lines.Where(l => l.Role == "you").Select(l => l.Text.Trim()).Where(t => t.Length > 0).ToList();
        if (turns.Count == 0)
        {
            Status = "Nothing in this sitting to file.";
            return;
        }

        _lastFiled = _host.Vault.AddCapture("journal", string.Join("\n\n", turns), "sitting");
        Status = _lastFiled > 0
            ? "Filed this sitting as a journal. Undo file takes it back."
            : "The vault did not take that file.";
        Filed?.Invoke(this, EventArgs.Empty);
    }

    private async Task FireMatchingSkillsAsync(string text)
    {
        if (!CanEdit)
        {
            return;
        }

        foreach (var skill in _host.Vault.Skills())
        {
            if (!skill.Enabled || string.IsNullOrWhiteSpace(skill.Triggers) || string.IsNullOrWhiteSpace(skill.Url))
            {
                continue;
            }

            var hit = skill.Triggers
                .Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
                .Any(trigger => trigger.Length > 0 && text.Contains(trigger, StringComparison.OrdinalIgnoreCase));
            if (!hit)
            {
                continue;
            }

            try
            {
                using var http = new HttpClient { Timeout = TimeSpan.FromSeconds(12) };
                await http.PostAsync(skill.Url, new StringContent("{\"source\":\"heirloom\",\"text\":" + System.Text.Json.JsonSerializer.Serialize(text) + "}")).ConfigureAwait(true);
            }
            catch
            {
                // Skill miss is not a vault miss — keep talking.
            }
        }
    }

    [RelayCommand]
    public void UndoLastFile()
    {
        if (!_host.CanEdit)
        {
            Status = "Heir mode. The vault is locked.";
            return;
        }

        if (_lastFiled <= 0 || !_host.Vault.DeleteCapture(_lastFiled))
        {
            Status = "Nothing to take back.";
            return;
        }

        _lastFiled = 0;
        Status = "Took back the last filed sentence. Say New if the chat should forget it too.";
        Filed?.Invoke(this, EventArgs.Empty);
    }

    private string TwinSilence()
    {
        var local = _host.Ollama.LastError;
        var cloud = _host.Api.LastFailure;
        if (!string.IsNullOrWhiteSpace(local) && !string.IsNullOrWhiteSpace(cloud))
        {
            return local + " Cloud: " + cloud + " File the fact, or provision Models on this PC.";
        }

        if (!string.IsNullOrWhiteSpace(local))
        {
            return local + " File the fact, or provision Models on this PC.";
        }

        if (!string.IsNullOrWhiteSpace(cloud))
        {
            return cloud + " File the fact, or provision Models on this PC.";
        }

        return "No local model and no cloud reply. File the fact, or provision Models on this PC.";
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

        return "No speech in that hold. Watch the gold bar move, then release.";
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

    private void OnLevel(object? sender, float peak) => UiDispatch.Post(() => Level = peak);
}
