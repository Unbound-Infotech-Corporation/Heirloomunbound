using System.Globalization;
using System.Text.Json;

namespace Heirloom.BoxCore;

/// <summary>
/// When a Twin Box owner session should be rotated. Access tokens stay at 7 days.
/// A stored refresh token is used only near expiry or after expiry. Web sessions
/// are not renewed here.
/// </summary>
public static class SessionClock
{
    public static readonly TimeSpan RenewWithin = TimeSpan.FromHours(36);

    public static readonly TimeSpan RetrySpacing = TimeSpan.FromMinutes(30);

    public static bool ShouldRenew(DateTimeOffset? expiresAt, DateTimeOffset now, bool hasRefresh, TimeSpan? window = null)
    {
        if (!hasRefresh)
        {
            return true;
        }

        if (expiresAt is null)
        {
            return false;
        }

        return expiresAt.Value - now <= (window ?? RenewWithin);
    }

    public static bool AttemptDue(DateTimeOffset? lastAttempt, DateTimeOffset now, TimeSpan? spacing = null)
    {
        if (lastAttempt is null)
        {
            return true;
        }

        return now - lastAttempt.Value >= (spacing ?? RetrySpacing);
    }

    public static DateTimeOffset? Parse(string? text)
    {
        if (string.IsNullOrWhiteSpace(text))
        {
            return null;
        }

        if (DateTimeOffset.TryParse(text, CultureInfo.InvariantCulture, DateTimeStyles.RoundtripKind, out var parsed))
        {
            return parsed;
        }

        return DateTimeOffset.TryParse(text, CultureInfo.InvariantCulture, DateTimeStyles.AssumeUniversal, out parsed)
            ? parsed
            : null;
    }

    public static DateTimeOffset? ReadExpiry(JsonElement body)
    {
        if (body.ValueKind != JsonValueKind.Object || !body.TryGetProperty("expires_at", out var expires))
        {
            return null;
        }

        return expires.ValueKind == JsonValueKind.String ? Parse(expires.GetString()) : null;
    }
}

/// <summary>
/// Cold qwen2.5:14b load measured 56.31s after Ollama was recreated (2026-11-11).
/// The server draft cap is 120s. The desktop wait must outlast that cap.
/// Warm replies are not delayed by these ceilings.
/// </summary>
public static class ChatWait
{
    public static readonly TimeSpan ColdLoadSeen = TimeSpan.FromSeconds(56.31);

    public static readonly TimeSpan LocalModel = TimeSpan.FromSeconds(120);

    public static readonly TimeSpan BoxReply = TimeSpan.FromSeconds(150);

    public static readonly TimeSpan HttpClient = TimeSpan.FromSeconds(160);

    public static readonly TimeSpan ShowLoadingAfter = TimeSpan.FromSeconds(3);
}

public static class ProductStamp
{
    public const string FallbackVersion = "0.5.1";

    public static string Display(string? informationalVersion, string? fallback = null)
    {
        var stamp = Clean(informationalVersion);
        if (stamp.Length == 0)
        {
            stamp = Clean(fallback);
        }

        return stamp.Length == 0 ? FallbackVersion : stamp;
    }

    public static string Title(string? informationalVersion, string? fallback = null) =>
        "Heirloom  " + Display(informationalVersion, fallback);

    private static string Clean(string? value)
    {
        var text = (value ?? "").Trim();
        var cut = text.IndexOf(' ');
        if (cut > 0)
        {
            text = text[..cut];
        }

        return text;
    }
}
