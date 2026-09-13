namespace Heirloom.Services;

public sealed record DiskProfile(
    string Id,
    string Label,
    int GbMin,
    int GbMax,
    string Summary,
    IReadOnlyList<string> Includes,
    IReadOnlyList<string> ProvisionFeatures,
    string Whisper = "base",
    string VaultTier = "lite",
    bool GpuRequired = false,
    bool MachineRole = false);

public static class DiskProfiles
{
    public static IReadOnlyDictionary<string, string> Aliases { get; } =
        new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
        {
            ["lite"] = "small",
            ["full"] = "medium",
            ["max"] = "large",
            ["studio"] = "large",
        };

    public static IReadOnlyList<DiskProfile> All { get; } =
    [
        new(
            "small",
            "Small",
            5,
            12,
            "App, Whisper, Piper, lite vault. Twin, TTS, and avatar stay cloud Auto. No GPU.",
            ["Heirloom Unbound app", "Whisper base/tiny — CPU is enough", "Piper if installable", "Vault: daily summaries only", "No Ollama / Voicebox / LatentSync required"],
            ["stt", "tts"],
            "base",
            "lite"),
        new(
            "medium",
            "Medium",
            40,
            70,
            "Small plus Ollama llama3.1, Whisper small, and one voice-clone path.",
            ["Everything in Small", "Ollama + llama3.1 (~5–8 GB)", "Whisper small", "Qwen3-TTS 0.6B or Voicebox (coach if not listening)", "Waveform", "Vault: transcripts forever, audio 30 days"],
            ["stt", "tts", "twin", "voice_clone"],
            "small",
            "partial"),
        new(
            "large",
            "Large",
            100,
            160,
            "Whisper large-v3, stronger twin + vision, Voicebox and Qwen3-TTS 1.7B, LatentSync.",
            ["Whisper large-v3", "llama3.1 + llava", "Voicebox AND Qwen3-TTS 1.7B — never Pinokio", "LatentSync (+ MuseTalk if license OK)", "Vault: keep every recording"],
            ["stt", "tts", "twin", "vision", "voicebox", "qwen3_tts", "latentsync", "avatar"],
            "large-v3",
            "full",
            GpuRequired: true),
        new(
            "dedicated",
            "Dedicated PC",
            200,
            0,
            "Everything in Large plus a machine that exists for Heirloom Unbound.",
            ["Everything in Large", "Start with Windows", "Vault / data drive", "Warm engine probes", "Standing routines + live listen toward on", "Overnight maintenance hook"],
            ["stt", "tts", "twin", "vision", "voicebox", "qwen3_tts", "latentsync", "avatar", "machine_role"],
            "large-v3",
            "full",
            GpuRequired: true,
            MachineRole: true),
    ];

    public static DiskProfile Resolve(string? id)
    {
        var key = string.IsNullOrWhiteSpace(id) ? "medium" : id.Trim();
        if (Aliases.TryGetValue(key, out var mapped))
        {
            key = mapped;
        }

        return All.FirstOrDefault(p => p.Id.Equals(key, StringComparison.OrdinalIgnoreCase))
            ?? All.First(p => p.Id == "medium");
    }
}
