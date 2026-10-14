namespace Heirloom.BoxCore;

/// <summary>
/// Twin Box client mode. The Windows PC talks to the box API and keeps Assist on this PC.
/// </summary>
public static class BoxLink
{
    public const string Local = "local";
    public const string Box = "box";
    public const string DefaultBoxUrl = "https://192.168.0.111";

    public static bool IsBoxClient(string? runMode) =>
        string.Equals(runMode?.Trim(), Box, StringComparison.OrdinalIgnoreCase);

    public static bool StartsLocalModels(string? runMode) => !IsBoxClient(runMode);

    /// <summary>Twin chat, clones, assignments, approvals, presence, and observer use the box.</summary>
    public static bool TwinUsesRemoteApi(string? runMode) => IsBoxClient(runMode);

    /// <summary>Assist PC tools stay on the Windows PC. The box never receives mode=assistant.</summary>
    public static bool AssistCloudFallback(string? runMode) => !IsBoxClient(runMode);

    /// <summary>
    /// Box mode sends the owner session except on companion poll, which stays a device token.
    /// </summary>
    public static bool UsesOwnerSession(string? runMode, string? path)
    {
        if (!IsBoxClient(runMode))
        {
            return false;
        }

        return (path ?? "").Contains("/companion/", StringComparison.OrdinalIgnoreCase) is false;
    }

    public static string ApiBase(string? runMode, string? boxUrl, string? cloudUrl)
    {
        if (IsBoxClient(runMode))
        {
            return Normalize(string.IsNullOrWhiteSpace(boxUrl) ? DefaultBoxUrl : boxUrl);
        }

        return Normalize(string.IsNullOrWhiteSpace(cloudUrl) ? "https://voice-clone-hub-20.emergent.host" : cloudUrl);
    }

    public static string WebHome(string? boxUrl) => Normalize(string.IsNullOrWhiteSpace(boxUrl) ? DefaultBoxUrl : boxUrl) + "/";

    public static string Normalize(string url)
    {
        var text = (url ?? "").Trim();
        if (text.Length == 0)
        {
            return DefaultBoxUrl;
        }

        if (!text.Contains("://", StringComparison.Ordinal))
        {
            text = "https://" + text;
        }

        return text.TrimEnd('/');
    }
}
