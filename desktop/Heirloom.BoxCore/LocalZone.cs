using System.Collections.Generic;

namespace Heirloom.BoxCore;

/// <summary>
/// The PC's time zone as an IANA name ("America/Los_Angeles"), for every twin or room
/// chat turn. The box runs on UTC, so without it "tomorrow at 9am" is 9am UTC.
/// Windows reports ids like "Pacific Standard Time"; .NET converts them with ICU.
/// </summary>
public static class LocalZone
{
    // Used only when ICU is not available to convert a Windows id.
    private static readonly Dictionary<string, string> Fallback = new(StringComparer.OrdinalIgnoreCase)
    {
        ["Pacific Standard Time"] = "America/Los_Angeles",
        ["Mountain Standard Time"] = "America/Denver",
        ["US Mountain Standard Time"] = "America/Phoenix",
        ["Central Standard Time"] = "America/Chicago",
        ["Eastern Standard Time"] = "America/New_York",
        ["Alaskan Standard Time"] = "America/Anchorage",
        ["Hawaiian Standard Time"] = "Pacific/Honolulu",
        ["Atlantic Standard Time"] = "America/Halifax",
        ["GMT Standard Time"] = "Europe/London",
        ["W. Europe Standard Time"] = "Europe/Berlin",
        ["Romance Standard Time"] = "Europe/Paris",
        ["Central Europe Standard Time"] = "Europe/Budapest",
        ["AUS Eastern Standard Time"] = "Australia/Sydney",
        ["India Standard Time"] = "Asia/Kolkata",
        ["Tokyo Standard Time"] = "Asia/Tokyo",
        ["China Standard Time"] = "Asia/Shanghai",
        ["UTC"] = "Etc/UTC",
        ["Coordinated Universal Time"] = "Etc/UTC",
    };

    /// <summary>The local zone as IANA, or null when it cannot be named.</summary>
    public static string? Iana()
    {
        try
        {
            return Iana(TimeZoneInfo.Local.Id);
        }
        catch (Exception)
        {
            return null;
        }
    }

    /// <summary>A Windows or IANA zone id as IANA. Null for an empty or unknown id.</summary>
    public static string? Iana(string? id)
    {
        var raw = (id ?? string.Empty).Trim();
        if (raw.Length == 0)
        {
            return null;
        }

        if (raw.Contains('/'))
        {
            return raw; // Already IANA (Linux, macOS, or a converted id).
        }

        try
        {
            if (TimeZoneInfo.TryConvertWindowsIdToIanaId(raw, out var iana) && !string.IsNullOrWhiteSpace(iana))
            {
                return iana;
            }
        }
        catch (Exception)
        {
            /* No ICU. Use the short table below. */
        }

        return Fallback.TryGetValue(raw, out var known) ? known : null;
    }
}

/// <summary>Twin Live request bodies. Each turn tells the box the PC's zone.</summary>
public static class AssistLiveBodies
{
    public static string Ptt(bool held) =>
        System.Text.Json.JsonSerializer.Serialize(new { held, timezone = LocalZone.Iana() });

    public static string Say(string words) =>
        System.Text.Json.JsonSerializer.Serialize(new { text = words, timezone = LocalZone.Iana() });
}
