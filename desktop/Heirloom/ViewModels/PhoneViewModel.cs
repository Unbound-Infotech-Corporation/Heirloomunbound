using System.Collections.ObjectModel;
using System.Text.Json;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using Heirloom.Services;
using Microsoft.UI.Xaml;

namespace Heirloom.ViewModels;

public partial class PhoneViewModel : ObservableObject
{
    private readonly AppHost _host;
    private readonly Dictionary<string, string> _transcripts = new(StringComparer.Ordinal);
    private readonly Task _load;
    private bool _loading;

    public PhoneViewModel(AppHost host)
    {
        _host = host;
        WhoChoice = WhoChoices[0];
        UnknownChoice = UnknownChoices[0];
        DisclosureChoice = DisclosureChoices[0];
        HoursSpan = HoursSpans[0];
        _load = ReloadInnerAsync();
    }

    public ObservableCollection<ArchiveEntry> Allowlist { get; } = [];
    public ObservableCollection<ArchiveEntry> Calls { get; } = [];
    public IReadOnlyList<string> WhoChoices { get; } = ["People on this list", "Anyone"];
    public IReadOnlyList<string> UnknownChoices { get; } = ["Hang up", "Take a message"];
    public IReadOnlyList<string> DisclosureChoices { get; } = ["Unknown callers", "Always", "Never"];
    public IReadOnlyList<string> HoursSpans { get; } = ["Weekdays", "Every day"];

    public bool CanEdit => _host.CanEdit;

    public IReadOnlyList<PhoneContact> Contacts =>
        Allowlist.Select(row => new PhoneContact(row.Title, row.Tag, row.Kind)).ToList();

    [ObservableProperty] private string _status = "Family line. The Twin answers from the vault when this PC is off.";
    [ObservableProperty] private bool _busy;
    [ObservableProperty] private bool _hasLine;
    [ObservableProperty] private string _numberLine = "No number yet.";
    [ObservableProperty] private string _voiceLine = "";
    [ObservableProperty] private bool _answering;
    [ObservableProperty] private string _whoChoice;
    [ObservableProperty] private string _unknownChoice;
    [ObservableProperty] private string _disclosureChoice;
    [ObservableProperty] private string _ownerE164 = "";
    [ObservableProperty] private bool _hoursEnabled;
    [ObservableProperty] private string _hoursSpan;
    [ObservableProperty] private string _hoursStart = "09:00";
    [ObservableProperty] private string _hoursEnd = "17:00";
    [ObservableProperty] private string _timezone = "America/Los_Angeles";
    [ObservableProperty] private bool _handoffEnabled;
    [ObservableProperty] private string _handoffE164 = "";
    [ObservableProperty] private bool _record = true;
    [ObservableProperty] private string _newName = "";
    [ObservableProperty] private string _newE164 = "";
    [ObservableProperty] private ArchiveEntry? _selectedAllow;
    [ObservableProperty] private ArchiveEntry? _selectedCall;
    [ObservableProperty] private string _transcript = "";
    [ObservableProperty] private string _outboundName = "";

    public Visibility BusyVis => Busy ? Visibility.Visible : Visibility.Collapsed;
    public Visibility EditVis => CanEdit ? Visibility.Visible : Visibility.Collapsed;
    public Visibility GetLineVis => CanEdit && !HasLine ? Visibility.Visible : Visibility.Collapsed;
    public Visibility ReleaseVis => CanEdit && HasLine ? Visibility.Visible : Visibility.Collapsed;
    public Visibility TranscriptVis =>
        string.IsNullOrWhiteSpace(Transcript) ? Visibility.Collapsed : Visibility.Visible;

    public void ApplyAudience()
    {
        OnPropertyChanged(nameof(CanEdit));
        OnPropertyChanged(nameof(EditVis));
        OnPropertyChanged(nameof(GetLineVis));
        OnPropertyChanged(nameof(ReleaseVis));
        GetLineCommand.NotifyCanExecuteChanged();
        ReleaseLineCommand.NotifyCanExecuteChanged();
        SaveCommand.NotifyCanExecuteChanged();
        AddAllowCommand.NotifyCanExecuteChanged();
        RemoveAllowCommand.NotifyCanExecuteChanged();
        PlaceCallCommand.NotifyCanExecuteChanged();
    }

    partial void OnBusyChanged(bool value)
    {
        OnPropertyChanged(nameof(BusyVis));
        GetLineCommand.NotifyCanExecuteChanged();
        ReleaseLineCommand.NotifyCanExecuteChanged();
        SaveCommand.NotifyCanExecuteChanged();
        PlaceCallCommand.NotifyCanExecuteChanged();
    }

    partial void OnHasLineChanged(bool value)
    {
        OnPropertyChanged(nameof(GetLineVis));
        OnPropertyChanged(nameof(ReleaseVis));
        GetLineCommand.NotifyCanExecuteChanged();
        ReleaseLineCommand.NotifyCanExecuteChanged();
        PlaceCallCommand.NotifyCanExecuteChanged();
    }

    partial void OnSelectedCallChanged(ArchiveEntry? value)
    {
        Transcript = value is null ? "" : _transcripts.GetValueOrDefault(value.Tag, "");
        OnPropertyChanged(nameof(TranscriptVis));
    }

    partial void OnTranscriptChanged(string value) => OnPropertyChanged(nameof(TranscriptVis));

    private bool CanMutate() => CanEdit && !Busy;

    [RelayCommand]
    public async Task ReloadAsync()
    {
        await ReloadInnerAsync().ConfigureAwait(true);
    }

    public Task EnsureLoadedAsync() => _load;

    private async Task ReloadInnerAsync()
    {
        Busy = true;
        try
        {
            await LoadCoreAsync().ConfigureAwait(true);
        }
        finally
        {
            Busy = false;
        }
    }

    private async Task LoadCoreAsync()
    {
        var json = await _host.Api.GetAsync("/phone/settings").ConfigureAwait(true);
        if (json is null)
        {
            Status = string.IsNullOrWhiteSpace(_host.Api.LastFailure)
                ? "Could not load the Phone line. Pair this PC in Settings."
                : _host.Api.LastFailure;
            return;
        }

        ApplySettings(json.Value);
        await LoadCallsAsync().ConfigureAwait(true);
        Status = HasLine
            ? (Answering ? "Answering  ·  " + NumberLine : "Line is quiet  ·  " + NumberLine)
            : "No number yet. Get a line when this Twin should answer the phone.";
    }

    private async Task LoadCallsAsync()
    {
        var json = await _host.Api.GetAsync("/phone/calls").ConfigureAwait(true);
        Calls.Clear();
        _transcripts.Clear();
        if (json is null || !json.Value.TryGetProperty("calls", out var list) || list.ValueKind != JsonValueKind.Array)
        {
            return;
        }

        foreach (var row in list.EnumerateArray())
        {
            var callId = Str(row, "call_id");
            if (callId.Length == 0)
            {
                continue;
            }

            var direction = Str(row, "direction");
            var inbound = !string.Equals(direction, "outbound", StringComparison.OrdinalIgnoreCase);
            var who = Str(row, "contact_name");
            if (who.Length == 0)
            {
                who = inbound ? Str(row, "from_e164") : Str(row, "to_e164");
            }

            var title = (inbound ? "In" : "Out") + "  ·  " + (string.IsNullOrWhiteSpace(who) ? "unknown" : who);
            var transcript = Str(row, "transcript");
            var left = Str(row, "message_left");
            var status = Str(row, "status");
            var body = string.IsNullOrWhiteSpace(transcript) ? status : Trim(transcript, 160);
            if (left.Length > 0)
            {
                body = "Message  ·  " + Trim(left, 140);
            }

            var meta = CallWhen(row);
            Calls.Add(new ArchiveEntry(title, body, meta, "call", callId));
            if (transcript.Length > 0 || left.Length > 0)
            {
                _transcripts[callId] = string.IsNullOrWhiteSpace(transcript)
                    ? left
                    : (left.Length == 0 ? transcript : transcript + "\n\nMessage kept:\n" + left);
            }
        }
    }

    private void ApplySettings(JsonElement root)
    {
        _loading = true;
        var line = Obj(root, "line");
        var e164 = Str(line, "e164");
        HasLine = e164.Length > 0 && !string.Equals(Str(line, "status"), "none", StringComparison.OrdinalIgnoreCase);
        NumberLine = HasLine ? e164 : "No number yet.";
        var voiceKind = Str(line, "voice_kind");
        var cloned = Flag(root, "cloned_voice_ready");
        VoiceLine = voiceKind == "cloned" || cloned
            ? "Cloned voice is on this line."
            : "Talk / cloned voice is not set. This line can still answer, but it will not sound like them.";

        var settings = Obj(root, "settings");
        Answering = Flag(settings, "answering");
        WhoChoice = Str(settings, "who_can_call") == "anyone" ? WhoChoices[1] : WhoChoices[0];
        UnknownChoice = Str(settings, "unknown_policy") == "message" ? UnknownChoices[1] : UnknownChoices[0];
        DisclosureChoice = Str(settings, "disclosure") switch
        {
            "always" => DisclosureChoices[1],
            "never" => DisclosureChoices[2],
            _ => DisclosureChoices[0],
        };
        OwnerE164 = Str(settings, "owner_e164");
        HoursEnabled = Flag(settings, "hours_enabled");
        Timezone = Str(settings, "timezone");
        if (Timezone.Length == 0)
        {
            Timezone = "America/Los_Angeles";
        }

        HoursStart = "09:00";
        HoursEnd = "17:00";
        HoursSpan = HoursSpans[0];
        if (settings.TryGetProperty("hours_windows", out var windows) && windows.ValueKind == JsonValueKind.Array
            && windows.GetArrayLength() > 0)
        {
            var first = windows[0];
            HoursStart = Str(first, "start");
            HoursEnd = Str(first, "end");
            if (first.TryGetProperty("days", out var days) && days.ValueKind == JsonValueKind.Array)
            {
                HoursSpan = days.GetArrayLength() >= 7 ? HoursSpans[1] : HoursSpans[0];
            }
        }

        HandoffEnabled = Flag(settings, "handoff_enabled");
        HandoffE164 = Str(settings, "handoff_e164");
        Record = settings.TryGetProperty("record", out var rec) ? rec.ValueKind != JsonValueKind.False : true;

        Allowlist.Clear();
        if (settings.TryGetProperty("allowlist", out var allow) && allow.ValueKind == JsonValueKind.Array)
        {
            foreach (var item in allow.EnumerateArray())
            {
                var number = PhoneIntent.NormalizeE164(Str(item, "e164"));
                if (number.Length == 0)
                {
                    continue;
                }

                var name = Str(item, "name");
                var heirId = Str(item, "heir_id");
                Allowlist.Add(new ArchiveEntry(
                    string.IsNullOrWhiteSpace(name) ? number : name,
                    number,
                    string.IsNullOrWhiteSpace(heirId) ? "family" : "heir",
                    heirId,
                    number));
            }
        }

        _loading = false;
        if (!Flag(root, "configured"))
        {
            Status = "The API does not have a Retell key yet. Add RETELL_API_KEY, then Get a line.";
        }
        else if (!Flag(root, "public_url_ready") && !HasLine)
        {
            Status = "PUBLIC_BACKEND_URL is not set, so a purchased number cannot reach this Twin.";
        }
    }

    [RelayCommand(CanExecute = nameof(CanMutate))]
    public async Task GetLineAsync()
    {
        if (!CanEdit)
        {
            Status = "Heir sitting cannot get a line.";
            return;
        }

        Busy = true;
        try
        {
            var json = await _host.Api.PostAsync("/phone/number", new { }).ConfigureAwait(true);
            if (json is null)
            {
                Status = string.IsNullOrWhiteSpace(_host.Api.LastFailure)
                    ? "Could not get a line."
                    : _host.Api.LastFailure;
                return;
            }

            ApplySettings(json.Value);
            Status = HasLine ? "Number is " + NumberLine + "." : "Retell did not return a number.";
        }
        finally
        {
            Busy = false;
        }
    }

    [RelayCommand(CanExecute = nameof(CanMutate))]
    public async Task ReleaseLineAsync()
    {
        if (!CanEdit)
        {
            Status = "Heir sitting cannot release the line.";
            return;
        }

        Busy = true;
        try
        {
            var json = await _host.Api.DeleteAsync("/phone/number").ConfigureAwait(true);
            if (json is null)
            {
                Status = string.IsNullOrWhiteSpace(_host.Api.LastFailure)
                    ? "Could not release the line."
                    : _host.Api.LastFailure;
                return;
            }

            ApplySettings(json.Value);
            Status = "Line released. The Twin will not answer the phone.";
        }
        finally
        {
            Busy = false;
        }
    }

    [RelayCommand(CanExecute = nameof(CanMutate))]
    public async Task SaveAsync()
    {
        if (!CanEdit)
        {
            Status = "Heir sitting cannot change the Phone line.";
            return;
        }

        if (_loading)
        {
            return;
        }

        Busy = true;
        try
        {
            var json = await _host.Api.PutAsync("/phone/settings", BuildPatch()).ConfigureAwait(true);
            if (json is null)
            {
                Status = string.IsNullOrWhiteSpace(_host.Api.LastFailure)
                    ? "Could not save Phone."
                    : _host.Api.LastFailure;
                return;
            }

            ApplySettings(json.Value);
            Status = "Saved.";
        }
        finally
        {
            Busy = false;
        }
    }

    [RelayCommand(CanExecute = nameof(CanMutate))]
    public async Task AddAllowAsync()
    {
        if (!CanEdit)
        {
            Status = "Heir sitting cannot change Who may call.";
            return;
        }

        var e164 = PhoneIntent.NormalizeE164(NewE164);
        if (e164.Length == 0)
        {
            Status = "Paste a phone number, then Add.";
            return;
        }

        if (Allowlist.Any(row => row.Tag == e164))
        {
            Status = e164 + " is already on Who may call.";
            return;
        }

        var name = NewName.Trim();
        Allowlist.Add(new ArchiveEntry(
            string.IsNullOrWhiteSpace(name) ? e164 : name,
            e164,
            "family",
            "",
            e164));
        NewName = "";
        NewE164 = "";
        await SaveAsync().ConfigureAwait(true);
        Status = "Added " + e164 + ".";
    }

    [RelayCommand(CanExecute = nameof(CanMutate))]
    public async Task RemoveAllowAsync()
    {
        if (SelectedAllow is null)
        {
            Status = "Select someone on Who may call, then remove.";
            return;
        }

        Allowlist.Remove(SelectedAllow);
        SelectedAllow = null;
        await SaveAsync().ConfigureAwait(true);
        Status = "Removed from Who may call.";
    }

    [RelayCommand(CanExecute = nameof(CanPlace))]
    public async Task PlaceCallAsync()
    {
        if (!CanEdit)
        {
            Status = "Heir sitting cannot place a call as the Twin.";
            return;
        }

        var target = SelectedAllow;
        var e164 = target?.Tag ?? PhoneIntent.NormalizeE164(OutboundName);
        var name = target?.Title ?? OutboundName.Trim();
        if (string.IsNullOrWhiteSpace(e164))
        {
            Status = "Pick someone on Who may call, then Place a call.";
            return;
        }

        await DialAsync(e164, name).ConfigureAwait(true);
    }

    private bool CanPlace() => CanEdit && !Busy && HasLine;

    public async Task<string> DialAsync(string e164, string contactName)
    {
        if (!CanEdit)
        {
            return "Heir sitting cannot place a call as the Twin.";
        }

        if (!HasLine)
        {
            await EnsureLoadedAsync().ConfigureAwait(true);
        }

        if (!HasLine)
        {
            return "Get a phone line first.";
        }

        Busy = true;
        try
        {
            var json = await _host.Api.PostAsync(
                "/phone/outbound",
                new { to_e164 = e164, contact_name = contactName }).ConfigureAwait(true);
            if (json is null)
            {
                var fail = string.IsNullOrWhiteSpace(_host.Api.LastFailure)
                    ? "Could not place the call."
                    : _host.Api.LastFailure;
                Status = fail;
                return fail;
            }

            var dest = Str(json.Value, "to_e164");
            Status = "Calling " + (string.IsNullOrWhiteSpace(contactName) ? dest : contactName) + "…";
            await LoadCallsAsync().ConfigureAwait(true);
            return Status;
        }
        finally
        {
            Busy = false;
        }
    }

    private object BuildPatch()
    {
        var days = HoursSpan == HoursSpans[1]
            ? new[] { 0, 1, 2, 3, 4, 5, 6 }
            : new[] { 0, 1, 2, 3, 4 };
        return new
        {
            answering = Answering,
            who_can_call = WhoChoice == WhoChoices[1] ? "anyone" : "allowlist",
            unknown_policy = UnknownChoice == UnknownChoices[1] ? "message" : "decline",
            disclosure = DisclosureChoice switch
            {
                "Always" => "always",
                "Never" => "never",
                _ => "unknown",
            },
            owner_e164 = OwnerE164,
            hours_enabled = HoursEnabled,
            timezone = Timezone,
            hours_windows = new[]
            {
                new { days, start = HoursStart, end = HoursEnd },
            },
            handoff_enabled = HandoffEnabled,
            handoff_e164 = HandoffE164,
            record = Record,
            allowlist = Allowlist.Select(row => new
            {
                e164 = row.Tag,
                name = row.Title,
                heir_id = row.Kind,
            }).ToArray(),
        };
    }

    private static JsonElement Obj(JsonElement json, string name) =>
        json.TryGetProperty(name, out var p) && p.ValueKind == JsonValueKind.Object ? p : default;

    private static string Str(JsonElement json, string name)
    {
        if (json.ValueKind != JsonValueKind.Object || !json.TryGetProperty(name, out var p))
        {
            return "";
        }

        return p.ValueKind switch
        {
            JsonValueKind.String => p.GetString() ?? "",
            JsonValueKind.Number => p.ToString(),
            _ => "",
        };
    }

    private static bool Flag(JsonElement json, string name) =>
        json.ValueKind == JsonValueKind.Object
        && json.TryGetProperty(name, out var p)
        && p.ValueKind == JsonValueKind.True;

    private static string CallWhen(JsonElement row)
    {
        var started = Str(row, "started_at");
        var ended = Str(row, "ended_at");
        if (started.Length >= 16)
        {
            var stamp = started[..16].Replace('T', ' ');
            return string.IsNullOrWhiteSpace(ended) ? stamp : stamp + "  ·  ended";
        }

        return Str(row, "status");
    }

    private static string Trim(string text, int max) =>
        text.Length <= max ? text : text[..max] + "…";
}
