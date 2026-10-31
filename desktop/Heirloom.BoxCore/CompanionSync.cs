using System.Text.Json;
using System.Text.RegularExpressions;

namespace Heirloom.BoxCore;

/// <summary>
/// When the Companion pushes assist settings, and the tray label for always-listening.
/// </summary>
public static class CompanionSync
{
    public static bool ShouldPush(bool signedIn, bool? wasReachable, bool reachable)
    {
        if (!signedIn || !reachable)
        {
            return false;
        }

        return wasReachable is null || wasReachable == false;
    }

    public static string AlwaysListeningLabel(bool on) =>
        on ? "Always listening: on" : "Always listening: off";

    public static string AssistSettingsBody(string twinName, string wakePhrase, bool proactive) =>
        JsonSerializer.Serialize(new
        {
            twin_name = twinName ?? "",
            wake_phrase = wakePhrase ?? "",
            proactive,
        });
}

/// <summary>
/// Local hard rules for the Caretaker window, plus the companion command flag.
/// </summary>
public static class CaretakerGuard
{
    public static string? Block(string? text)
    {
        var raw = text ?? "";
        if (raw.Length == 0)
        {
            return null;
        }

        if (raw.Contains("192.168.0.16", StringComparison.Ordinal) || raw.Contains("192.168.0.19", StringComparison.Ordinal))
        {
            return "Caretaker does not touch 192.168.0.16 or 192.168.0.19.";
        }

        if (Regex.IsMatch(raw, @"\b(format|mkfs|wipe)\b", RegexOptions.IgnoreCase))
        {
            return "Caretaker will not format or wipe a drive.";
        }

        if (Regex.IsMatch(raw, @"\breboot\b", RegexOptions.IgnoreCase) || raw.Contains("restart bigdeal", StringComparison.OrdinalIgnoreCase))
        {
            return "Caretaker will not reboot BIGDEAL.";
        }

        if (Regex.IsMatch(raw, @"\bpassword\b", RegexOptions.IgnoreCase))
        {
            return "Caretaker does not ask for or handle the owner password.";
        }

        if (Regex.IsMatch(raw, @"fan\s*curve", RegexOptions.IgnoreCase)
            || Regex.IsMatch(raw, @"\b(set|change)\b.{0,24}\bfan\b", RegexOptions.IgnoreCase))
        {
            return "Caretaker does not change fan curves.";
        }

        if (raw.Contains("power limit", StringComparison.OrdinalIgnoreCase))
        {
            return "Caretaker does not change power limits.";
        }

        return null;
    }

    public static bool WantsRestart(string? json) => Flag(json, "restart");

    public static bool WantsRepush(string? json) => Flag(json, "repush");

    private static bool Flag(string? json, string name)
    {
        if (string.IsNullOrWhiteSpace(json))
        {
            return false;
        }

        try
        {
            using var doc = JsonDocument.Parse(json);
            return doc.RootElement.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.True;
        }
        catch (JsonException)
        {
            return false;
        }
    }
}
