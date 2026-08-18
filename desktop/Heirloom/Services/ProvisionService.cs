namespace Heirloom.Services;

public sealed record DiskProfile(
    string Id,
    string Label,
    int GbMin,
    int GbMax,
    string Summary,
    IReadOnlyList<string> Includes,
    IReadOnlyList<string> ProvisionFeatures);

public static class DiskProfiles
{
    public static IReadOnlyList<DiskProfile> All { get; } =
    [
        new(
            "lite",
            "Lite",
            3,
            8,
            "Local Whisper for journals. Twin and voice can use cloud fallbacks.",
            ["faster-whisper / Whisper.net base", "Vault: daily summaries only", "Cloud twin/TTS if you add keys"],
            ["stt"]),
        new(
            "full",
            "Full local",
            20,
            35,
            "Whisper + Ollama + local speech on this PC. Cloud keys are optional extras.",
            ["Whisper.net base", "Ollama + llama3.1 (~5–8 GB)", "Vault: transcripts forever, audio 30 days"],
            ["stt", "tts", "twin"]),
        new(
            "studio",
            "Studio (recommended serious)",
            40,
            80,
            "50 GB is the serious floor: twin, speech, vault headroom. Not the ceiling.",
            ["Whisper + Ollama llama3.1 + vision optional", "Keep recordings", "Headroom for a larger instruct model"],
            ["stt", "tts", "twin", "vision"]),
        new(
            "dedicated",
            "Dedicated / custom",
            50,
            0,
            "No 50 GB cap. Point Heirloom at a drive and pull whatever this machine can hold.",
            ["User-chosen Ollama models", "Keep every recording", "Meant for a second PC that only runs Heirloom"],
            ["stt", "tts", "twin", "vision"]),
    ];
}

public sealed class ProvisionService
{
    private readonly OllamaService _ollama;
    private readonly WhisperService _whisper;

    public ProvisionService(OllamaService ollama, WhisperService whisper)
    {
        _ollama = ollama;
        _whisper = whisper;
    }

    public string LastMessage { get; private set; } = "";

    public async Task ProvisionAsync(DiskProfile profile, IProgress<string> progress, CancellationToken cancellationToken = default)
    {
        progress.Report("Preparing local brain · " + profile.Label);
        Directory.CreateDirectory(AppPaths.ModelsRoot);
        await _whisper.EnsureAsync(cancellationToken).ConfigureAwait(false);
        progress.Report(_whisper.Status);

        if (profile.ProvisionFeatures.Contains("twin"))
        {
            await _ollama.ProbeAsync(cancellationToken).ConfigureAwait(false);
            if (_ollama.IsReachable && !_ollama.Models.Any(m => m.Contains("llama3.1", StringComparison.OrdinalIgnoreCase)))
            {
                LastMessage = await _ollama.PullAsync("llama3.1", progress, cancellationToken).ConfigureAwait(false);
            }
            else if (!_ollama.IsReachable)
            {
                LastMessage = "Install Ollama, then provision again.";
                progress.Report(LastMessage);
            }
        }

        if (profile.ProvisionFeatures.Contains("vision") && _ollama.IsReachable)
        {
            LastMessage = await _ollama.PullAsync("llava", progress, cancellationToken).ConfigureAwait(false);
        }

        progress.Report("Provision finished");
    }
}
