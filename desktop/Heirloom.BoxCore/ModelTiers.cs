using System.Diagnostics;
using System.Globalization;

namespace Heirloom.BoxCore;

/// <summary>
/// The local model for this PC's graphics card. Mirrors backend/model_tiers.py
/// (docs/MODEL-TIERS.md); tests/test_local_box.py fails if the two tables drift.
/// </summary>
public static class ModelTiers
{
    public sealed record Tier(string Name, int MinVramMib, string Model, string Fallback, int NumCtx, int LoadedMib, bool VoiceOnGpu);

    public sealed record Hardware(string Vendor, string Gpu, int VramMib, int RamMib);

    public sealed record Pick(string Tier, string Model, int NumCtx, bool VoiceOnGpu, string Reason);

    public const int VoiceReserveMib = 5248;
    public const int BaseReserveMib = 512;
    public const string EmbedModel = "nomic-embed-text";

    // Biggest first, same order and numbers as model_tiers.TIERS.
    public static readonly IReadOnlyList<Tier> Tiers =
    [
        new("xl", 30720, "gemma4:26b", "gemma4:12b", 16384, 18008, true),
        new("large", 22528, "gemma4:12b", "gemma4:e4b", 16384, 8398, true),
        new("medium", 15360, "gemma4:12b", "qwen3.5:4b", 16384, 8398, true),
        new("small", 11264, "qwen3.5:4b", "gemma4:e2b", 16384, 4628, true),
        new("compact", 7168, "qwen3.5:4b", "gemma4:e2b", 8192, 4358, false),
        new("cpu", 0, "gemma4:e4b", "gemma4:e2b", 8192, 0, false),
    ];

    public static IEnumerable<string> AllModels =>
        Tiers.SelectMany(t => new[] { t.Model, t.Fallback }).Distinct(StringComparer.OrdinalIgnoreCase);

    public static Pick Choose(Hardware hw, bool voiceOnGpu = true)
    {
        var cpu = Tiers[^1];
        var cpuModel = hw.RamMib == 0 || hw.RamMib >= 16384 ? cpu.Model : cpu.Fallback;
        var usable = hw.Vendor is "nvidia" or "amd" && hw.VramMib >= 4096;
        if (!usable)
        {
            return new Pick(cpu.Name, cpuModel, cpu.NumCtx, false, $"{(hw.Gpu.Length > 0 ? hw.Gpu : "no GPU")} -> cpu");
        }

        foreach (var tier in Tiers.Take(Tiers.Count - 1))
        {
            if (hw.VramMib < tier.MinVramMib)
            {
                continue;
            }

            var reserve = BaseReserveMib + (voiceOnGpu && tier.VoiceOnGpu ? VoiceReserveMib : 0);
            var model = tier.LoadedMib > 0 && tier.LoadedMib + reserve > hw.VramMib ? tier.Fallback : tier.Model;
            return new Pick(tier.Name, model, tier.NumCtx, tier.VoiceOnGpu, $"{hw.Gpu} {hw.VramMib} MiB -> {tier.Name}");
        }

        return new Pick(cpu.Name, cpuModel, cpu.NumCtx, false, $"{hw.Gpu} {hw.VramMib} MiB -> cpu");
    }

    /// <summary>"NVIDIA GeForce RTX 5090, 32607" from nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits.</summary>
    public static (string Name, int Mib) ParseNvidiaSmi(string? text)
    {
        var best = ("", 0);
        foreach (var line in (text ?? "").Split('\n', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
        {
            var cut = line.LastIndexOf(',');
            if (cut <= 0)
            {
                continue;
            }

            var digits = new string(line[(cut + 1)..].Where(char.IsDigit).ToArray());
            if (int.TryParse(digits, NumberStyles.Integer, CultureInfo.InvariantCulture, out var mib) && mib > best.Item2)
            {
                best = (line[..cut].Trim(), mib);
            }
        }

        return best;
    }

    /// <summary>NVIDIA through nvidia-smi; anything else is treated as the CPU tier (the installer's Python check also reads AMD).</summary>
    public static Hardware Detect()
    {
        var ram = 0;
        try
        {
            ram = (int)(GC.GetGCMemoryInfo().TotalAvailableMemoryBytes / (1024 * 1024));
        }
        catch
        {
            ram = 0;
        }

        try
        {
            var start = new ProcessStartInfo("nvidia-smi", "--query-gpu=name,memory.total --format=csv,noheader,nounits")
            {
                RedirectStandardOutput = true,
                UseShellExecute = false,
                CreateNoWindow = true,
            };
            using var proc = Process.Start(start);
            if (proc is not null)
            {
                var text = proc.StandardOutput.ReadToEnd();
                proc.WaitForExit(8000);
                var (name, mib) = ParseNvidiaSmi(text);
                if (mib > 0)
                {
                    return new Hardware("nvidia", name, mib, ram);
                }
            }
        }
        catch
        {
            // No NVIDIA driver on this PC.
        }

        return new Hardware("none", "", 0, ram);
    }
}

/// <summary>A Heirloom "local box" installed on this PC by Install-HeirloomLocal.ps1.</summary>
public static class LocalBox
{
    public const string DefaultUrl = "http://127.0.0.1:8001";

    public static string DefaultInstallDir =>
        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "HeirloomUnbound");

    /// <summary>The API url from data\heirloom.env, or null when Heirloom is not installed on this PC.</summary>
    public static string? FindUrl(string? installDir = null)
    {
        var env = Path.Combine(installDir ?? DefaultInstallDir, "data", "heirloom.env");
        if (!File.Exists(env))
        {
            return null;
        }

        foreach (var line in File.ReadLines(env))
        {
            if (line.StartsWith("HEIRLOOM_API_PORT=", StringComparison.Ordinal) && int.TryParse(line[18..].Trim(), out var port))
            {
                return $"http://127.0.0.1:{port}";
            }
        }

        return DefaultUrl;
    }
}
