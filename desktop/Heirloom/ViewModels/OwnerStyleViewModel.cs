using System.Text.Json;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using Heirloom.Services;

namespace Heirloom.ViewModels;

public partial class OwnerStyleViewModel : ObservableObject
{
    private readonly AppHost _host;

    public OwnerStyleViewModel(AppHost host)
    {
        _host = host;
    }

    [ObservableProperty] private string _status = "How you talk. Heirs never see this page.";
    [ObservableProperty] private string _wordChoice = "";
    [ObservableProperty] private string _sentenceLength = "";
    [ObservableProperty] private string _punctuation = "";
    [ObservableProperty] private string _casing = "";
    [ObservableProperty] private string _deliberateTypos = "";
    [ObservableProperty] private string _humor = "";
    [ObservableProperty] private string _opens = "";
    [ObservableProperty] private string _closes = "";
    [ObservableProperty] private string _skips = "";
    [ObservableProperty] private string _topics = "";
    [ObservableProperty] private string _sampleLine = "";

    [RelayCommand]
    public async Task LoadAsync()
    {
        if (!_host.CanEdit)
        {
            Status = "Heir mode. The style profile stays with the owner.";
            return;
        }

        var result = await _host.Api.GetSessionAsync("/owner/style").ConfigureAwait(true);
        if (result is null || !result.Value.TryGetProperty("profile", out var profile))
        {
            Status = string.IsNullOrWhiteSpace(_host.Api.LastFailure) ? "The box did not answer." : _host.Api.LastFailure;
            return;
        }

        Apply(profile);
        Status = "Loaded from this box. Local Ollama updates it from your sittings.";
    }

    [RelayCommand]
    private async Task SaveAsync()
    {
        if (!_host.CanEdit)
        {
            Status = "Heir mode. The style profile stays with the owner.";
            return;
        }

        var body = Body();
        var result = await _host.Api.PutSessionAsync("/owner/style", body).ConfigureAwait(true);
        if (result is null || !result.Value.TryGetProperty("profile", out var profile))
        {
            Status = string.IsNullOrWhiteSpace(_host.Api.LastFailure) ? "Save did not land." : _host.Api.LastFailure;
            return;
        }

        Apply(profile);
        Status = "Saved. The twin uses this when it sits with you.";
    }

    [RelayCommand]
    private async Task ResetAsync()
    {
        if (!_host.CanEdit)
        {
            Status = "Heir mode. The style profile stays with the owner.";
            return;
        }

        var result = await _host.Api.PostSessionAsync("/owner/style/reset", new { }).ConfigureAwait(true);
        if (result is null || !result.Value.TryGetProperty("profile", out var profile))
        {
            Status = string.IsNullOrWhiteSpace(_host.Api.LastFailure) ? "Reset did not land." : _host.Api.LastFailure;
            return;
        }

        Apply(profile);
        Status = "Cleared. The next sittings can teach it again.";
    }

    private object Body() => new
    {
        word_choice = WordChoice,
        sentence_length = SentenceLength,
        punctuation = Punctuation,
        casing = Casing,
        deliberate_typos = DeliberateTypos,
        humor = Humor,
        opens = Opens,
        closes = Closes,
        skips = Skips,
        topics = Topics,
    };

    private void Apply(JsonElement profile)
    {
        WordChoice = Text(profile, "word_choice");
        SentenceLength = Text(profile, "sentence_length");
        Punctuation = Text(profile, "punctuation");
        Casing = Text(profile, "casing");
        DeliberateTypos = Text(profile, "deliberate_typos");
        Humor = Text(profile, "humor");
        Opens = Text(profile, "opens");
        Closes = Text(profile, "closes");
        Skips = Text(profile, "skips");
        Topics = Text(profile, "topics");
        var count = profile.TryGetProperty("sample_count", out var samples) && samples.TryGetInt32(out var number) ? number : 0;
        SampleLine = count == 0 ? "No owner lines folded in yet." : count + " owner lines folded in.";
    }

    private static string Text(JsonElement profile, string name) =>
        profile.TryGetProperty(name, out var node) ? node.GetString() ?? "" : "";
}
