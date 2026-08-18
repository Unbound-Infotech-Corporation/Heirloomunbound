using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using Heirloom.Services;

namespace Heirloom.ViewModels;

public sealed class ChatLine
{
    public ChatLine(string role, string text, string citation = "")
    {
        Role = role;
        Text = text;
        Citation = citation;
    }

    public string Role { get; }
    public string Text { get; }
    public string Citation { get; }
    public string Display =>
        (Role == "you" ? "You  ·  " : "Twin  ·  ")
        + Text
        + (string.IsNullOrWhiteSpace(Citation) ? "" : "\n" + Citation);
}

public partial class TwinViewModel : ObservableObject
{
    private readonly AppHost _host;

    public TwinViewModel(AppHost host, MixerViewModel mixer)
    {
        _host = host;
        Mixer = mixer;
        GroundedOnly = host.Settings.Current.GroundedOnly;
        SpeakReplies = host.Settings.Current.SpeakReplies;
        Persona = host.Settings.Current.TwinPersona;
        NewConversation();
    }

    public MixerViewModel Mixer { get; }
    public ObservableCollection<ChatLine> Lines { get; } = [];
    public IReadOnlyList<string> Personas { get; } = ["family", "formal", "full"];

    [ObservableProperty] private string _draft = "";
    [ObservableProperty] private string _status = "Ready";
    [ObservableProperty] private bool _isRecording;
    [ObservableProperty] private double _level;
    [ObservableProperty] private string _avatarState = "listening";
    [ObservableProperty] private bool _groundedOnly;
    [ObservableProperty] private bool _speakReplies;
    [ObservableProperty] private string _persona = "family";
    [ObservableProperty] private string _lastCitation = "No memories cited yet.";

    partial void OnGroundedOnlyChanged(bool value)
    {
        _host.Settings.Current.GroundedOnly = value;
        _host.Settings.Save();
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

    [RelayCommand]
    public void NewConversation()
    {
        Lines.Clear();
        Lines.Add(new ChatLine(
            "twin",
            GroundedOnly
                ? "I'm here, and I'll only speak from what you've filed. If I don't know, I'll say so."
                : "I'm here. Hold push-to-talk, or type — this is your archive speaking."));
        LastCitation = "New conversation. Memories stay in the vault.";
        Status = "Ready";
        AvatarState = "listening";
    }

    [RelayCommand]
    public async Task SendAsync()
    {
        var text = Draft.Trim();
        if (text.Length == 0)
        {
            return;
        }

        Draft = "";
        await TalkAsync(text).ConfigureAwait(true);
    }

    [RelayCommand]
    public void BeginPtt()
    {
        IsRecording = true;
        AvatarState = "listening";
        Status = "Recording…";
        _host.Capture.LevelChanged += OnLevel;
        _host.Capture.StartPtt();
    }

    [RelayCommand]
    public async Task EndPttAsync()
    {
        _host.Capture.LevelChanged -= OnLevel;
        IsRecording = false;
        Level = 0;
        var wav = _host.Capture.StopPtt();
        Status = "Transcribing…";
        var text = await _host.Whisper.TranscribeAsync(wav).ConfigureAwait(true);
        if (string.IsNullOrWhiteSpace(text))
        {
            var cloud = await _host.Api.PostMultipartAsync("/companion/voice", "ptt.wav", wav).ConfigureAwait(true);
            if (cloud is { } json && json.TryGetProperty("transcript", out var t))
            {
                text = t.GetString();
            }
        }

        if (string.IsNullOrWhiteSpace(text))
        {
            Status = "No speech heard";
            return;
        }

        await TalkAsync(text).ConfigureAwait(true);
    }

    public async Task SpeakAsync(string text) => await _host.Speak.SpeakAsync(text).ConfigureAwait(true);

    private async Task TalkAsync(string text)
    {
        Lines.Add(new ChatLine("you", text));
        _host.Vault.AddCapture("speech", text);
        Status = "Thinking…";
        AvatarState = "thinking";

        var memories = _host.Vault.GroundedContext();
        var cites = _host.Vault.CitationsFor(text);
        LastCitation = cites.Count == 0
            ? "Nothing in the vault matched this yet."
            : string.Join(" · ", cites.Select(c => c.Kind + (string.IsNullOrWhiteSpace(c.Tag) ? "" : "/" + c.Tag)));

        var personaLine = Persona switch
        {
            "formal" => "Speak as a composed, precise representative. Short sentences. No slang.",
            "full" => "Speak as the whole person: warmth, humor, and the hard years, if those memories exist.",
            _ => "Speak as family would remember them: warm, plain, and close.",
        };
        var system = GroundedOnly
            ? "You are this person's digital twin. Answer ONLY from MEMORIES. If the answer is not there, say you don't remember that yet. Never invent biography, dates, names, or advice they did not leave."
            : "You are this person's digital twin. Prefer MEMORIES. Be warm. Do not invent facts about their life.";
        var prompt = $"PERSONA: {personaLine}\n\nMEMORIES:\n{(string.IsNullOrWhiteSpace(memories) ? "(empty vault)" : memories)}\n\nTHEY SAID:\n{text}";

        string? reply = null;
        await _host.Ollama.ProbeAsync().ConfigureAwait(true);
        if (_host.Ollama.IsReachable && _host.Ollama.Models.Count > 0)
        {
            reply = await _host.Ollama.CompleteAsync(_host.Ollama.Models[0], prompt, system).ConfigureAwait(true);
        }

        if (string.IsNullOrWhiteSpace(reply))
        {
            var cloud = await _host.Api.PostAsync("/desktop/chat", new { text, grounded = GroundedOnly, persona = Persona }).ConfigureAwait(true);
            if (cloud is { } json && json.TryGetProperty("reply", out var r))
            {
                reply = r.GetString();
            }
        }

        if (string.IsNullOrWhiteSpace(reply) && GroundedOnly && string.IsNullOrWhiteSpace(memories))
        {
            reply = "I don't remember that yet. File a journal, interview, or photo story and I'll speak from it.";
        }

        reply ??= "I'm with you. When local models finish downloading, I'll answer from this machine.";
        var citation = cites.Count == 0 ? "" : "Grounded in: " + LastCitation;
        Lines.Add(new ChatLine("twin", reply, citation));
        Status = "Ready";
        AvatarState = "speaking";
        if (SpeakReplies)
        {
            await _host.Speak.SpeakAsync(reply).ConfigureAwait(true);
        }

        AvatarState = "listening";
    }

    private void OnLevel(object? sender, float peak) => UiDispatch.Post(() => Level = peak);
}
