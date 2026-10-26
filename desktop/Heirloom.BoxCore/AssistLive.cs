using System.Text.Json;

namespace Heirloom.BoxCore;

public sealed record AssistLiveView(
    bool Listening,
    string Caption,
    string CaptionId,
    string PendingId,
    string PendingLabel,
    bool ExplicitConfirm,
    bool Muted,
    bool Proactive,
    string WakePhrase,
    bool HasAudio,
    string AudioId,
    string ReceiptSummary)
{
    public static AssistLiveView Empty { get; } = new(false, "", "", "", "", false, false, false, "", false, "", "");
}

/// <summary>
/// Assist on BIGDEAL. The microphone leaves this PC only while Observer is listening.
/// </summary>
public static class AssistLive
{
    public const int PttWindowSeconds = 8;
    public const string DefaultChord = "Ctrl+Shift+Space";

    public static bool MaySend(bool observerPaused, AudioStreamView stream)
    {
        if (observerPaused)
        {
            return false;
        }

        return TrayStatus.CompanionShouldSend(stream);
    }

    public static AssistLiveView Parse(string? json)
    {
        if (string.IsNullOrWhiteSpace(json))
        {
            return AssistLiveView.Empty;
        }

        try
        {
            using var doc = JsonDocument.Parse(json);
            var root = doc.RootElement;
            var pendingId = "";
            var pendingLabel = "";
            var explicitConfirm = false;
            if (root.TryGetProperty("pending", out var pending) && pending.ValueKind == JsonValueKind.Object)
            {
                pendingId = Text(pending, "id");
                pendingLabel = Text(pending, "label");
                explicitConfirm = Flag(pending, "explicit");
            }

            var receipt = "";
            if (root.TryGetProperty("receipt", out var card) && card.ValueKind == JsonValueKind.Object)
            {
                receipt = Text(card, "summary");
            }

            return new AssistLiveView(
                Flag(root, "listening"),
                Text(root, "caption"),
                Text(root, "caption_id"),
                pendingId,
                pendingLabel,
                explicitConfirm,
                Flag(root, "muted"),
                Flag(root, "proactive"),
                Text(root, "wake_phrase"),
                Flag(root, "has_audio"),
                Text(root, "audio_id"),
                receipt);
        }
        catch (JsonException)
        {
            return AssistLiveView.Empty;
        }
    }

    private static bool Flag(JsonElement obj, string name) =>
        obj.TryGetProperty(name, out var value) &&
        (value.ValueKind == JsonValueKind.True ||
         (value.ValueKind == JsonValueKind.String && string.Equals(value.GetString(), "true", StringComparison.OrdinalIgnoreCase)));

    private static string Text(JsonElement obj, string name)
    {
        if (!obj.TryGetProperty(name, out var value) || value.ValueKind != JsonValueKind.String)
        {
            return "";
        }

        return value.GetString() ?? "";
    }
}
