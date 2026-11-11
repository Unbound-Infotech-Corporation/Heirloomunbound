namespace Heirloom.Services;

/// <summary>
/// Offline guards for Setup, Smart Home, Writing, and Code.
/// The full engines live in the local API (setup_center.py and the modules
/// beside it). These checks are what the Windows app must not skip when it
/// acts on this PC. Twin routing is not decided here.
/// </summary>
public static class StudioPolicy
{
    public const string LinuxLiveRoot = "/var/lib/heirloom";
    public const int HeatMinF = 60;
    public const int HeatMaxF = 74;
    public const int CoolMinF = 68;
    public const int CoolMaxF = 78;
    public const string PasteChord = "Ctrl+Alt+H";

    private static readonly string[] CriticalWords =
    [
        "fridge", "freezer", "sump", "oxygen", "medical", "furnace",
        "water heater", "water-heater", "well pump", "smoke",
        "carbon monoxide", "cpap",
    ];

    private static readonly string[] CloudKeyFlows =
    [
        "openai", "anthropic", "claude", "gemini", "google", "google_ai",
        "elevenlabs", "groq", "mistral", "openrouter", "azure_openai",
    ];

    private static readonly string[] CoderHints =
    [
        "qwen3-coder", "qwen2.5-coder", "deepseek-coder", "codellama", "starcoder",
    ];

    private static readonly string[] BlockedCommands =
    [
        "rm -rf /", "rm -rf /*", ":(){", "mkfs", "diskpart",
        "format c:", "format d:", "shutdown", "restart-computer", "stop-computer", "dd if=",
    ];

    public static string MaskSecret(string? value)
    {
        var raw = (value ?? "").Trim();
        if (raw.Length < 8)
        {
            return "••••";
        }

        return "••••" + raw[^4..];
    }

    public static string SecretForLog(string? value) => "[redacted]";

    public static bool CloudModelKey(string? flowId)
    {
        var key = new string((flowId ?? "").Trim().ToLowerInvariant().Where(char.IsLetterOrDigit).ToArray());
        if ((flowId ?? "").Contains('_'))
        {
            key = (flowId ?? "").Trim().ToLowerInvariant();
        }

        return CloudKeyFlows.Contains(key);
    }

    public static bool IsUnderLinuxLiveRoot(string? path)
    {
        var full = (path ?? "").Replace('\\', '/').TrimEnd('/');
        return full.Equals(LinuxLiveRoot, StringComparison.OrdinalIgnoreCase)
            || full.StartsWith(LinuxLiveRoot + "/", StringComparison.OrdinalIgnoreCase);
    }

    public static (double Applied, bool Limited, string Reason) ClampSetpoint(string mode, double value, string unit = "F")
    {
        var fahrenheit = unit.Equals("C", StringComparison.OrdinalIgnoreCase)
            ? value * 9.0 / 5.0 + 32.0
            : value;
        var heat = mode.Equals("heat", StringComparison.OrdinalIgnoreCase);
        var low = heat ? HeatMinF : CoolMinF;
        var high = heat ? HeatMaxF : CoolMaxF;
        var appliedF = Math.Min(high, Math.Max(low, fahrenheit));
        var limited = Math.Abs(appliedF - fahrenheit) > 0.05;
        double applied;
        double showLow;
        double showHigh;
        if (unit.Equals("C", StringComparison.OrdinalIgnoreCase))
        {
            applied = Math.Round((appliedF - 32.0) * 5.0 / 9.0, 1);
            showLow = Math.Round((low - 32.0) * 5.0 / 9.0, 1);
            showHigh = Math.Round((high - 32.0) * 5.0 / 9.0, 1);
        }
        else
        {
            applied = Math.Round(appliedF, 1);
            showLow = low;
            showHigh = high;
        }

        var reason = limited
            ? $"{(heat ? "Heat" : "Cooling")} stays between {showLow}° and {showHigh}° so the house is not pushed to an extreme."
            : "";
        return (applied, limited, reason);
    }

    public static bool IsCritical(string? name, string? role = null)
    {
        var blob = $"{name} {role}".ToLowerInvariant();
        return CriticalWords.Any(word => blob.Contains(word, StringComparison.Ordinal));
    }

    /// <summary>
    /// Always-allow never covers a critical off or a thermostat off.
    /// </summary>
    public static bool MayTurnOff(bool critical, bool approved, bool criticalConfirm, bool alwaysAllow, bool thermostat)
    {
        if (critical || thermostat)
        {
            return approved && criticalConfirm;
        }

        return alwaysAllow || approved;
    }

    public static bool MayPaste(bool approved) => approved;

    public static string? PickCoder(IEnumerable<string> tags)
    {
        var local = tags
            .Where(tag => !string.IsNullOrWhiteSpace(tag) && !IsHosted(tag))
            .Select(tag => tag.Trim())
            .ToList();
        foreach (var hint in CoderHints)
        {
            var hit = local.FirstOrDefault(tag => tag.Contains(hint, StringComparison.OrdinalIgnoreCase));
            if (hit is not null)
            {
                return hit;
            }
        }

        return null;
    }

    public static bool CommandBlocked(string? command)
    {
        var lowered = string.Join(' ', (command ?? "").ToLowerInvariant().Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries));
        if (BlockedCommands.Any(fragment => lowered.Contains(fragment, StringComparison.Ordinal)))
        {
            return true;
        }

        return lowered.Contains("remove-item", StringComparison.Ordinal)
            && lowered.Contains("-recurse", StringComparison.Ordinal)
            && lowered.Contains(":\\", StringComparison.Ordinal);
    }

    private static bool IsHosted(string tag)
    {
        var name = tag.Trim().ToLowerInvariant();
        if (name.StartsWith("gpt-oss", StringComparison.Ordinal))
        {
            return false;
        }

        return name.Contains("claude", StringComparison.Ordinal)
            || name.Contains("gpt-4", StringComparison.Ordinal)
            || name.Contains("gpt-3", StringComparison.Ordinal)
            || name.Contains("gemini", StringComparison.Ordinal)
            || name.Contains("openai/", StringComparison.Ordinal);
    }
}
