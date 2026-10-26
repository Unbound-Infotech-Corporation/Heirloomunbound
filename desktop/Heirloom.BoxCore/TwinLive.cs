namespace Heirloom.BoxCore;

public sealed record MicTranscriptLine(string Id, string Text);

public sealed record MicTranscript(bool Listening, bool Paused, IReadOnlyList<MicTranscriptLine> Lines)
{
    public static MicTranscript? Parse(string? json)
    {
        if (string.IsNullOrWhiteSpace(json))
        {
            return null;
        }

        try
        {
            using var doc = System.Text.Json.JsonDocument.Parse(json);
            var root = doc.RootElement;
            var listening = root.TryGetProperty("listening", out var hear) &&
                            (hear.ValueKind == System.Text.Json.JsonValueKind.True ||
                             (hear.ValueKind == System.Text.Json.JsonValueKind.String &&
                              string.Equals(hear.GetString(), "true", StringComparison.OrdinalIgnoreCase)));
            var paused = root.TryGetProperty("paused", out var hold) &&
                         (hold.ValueKind == System.Text.Json.JsonValueKind.True ||
                          (hold.ValueKind == System.Text.Json.JsonValueKind.String &&
                           string.Equals(hold.GetString(), "true", StringComparison.OrdinalIgnoreCase)));
            if (!listening)
            {
                paused = true;
            }

            var lines = new List<MicTranscriptLine>();
            if (root.TryGetProperty("lines", out var list) && list.ValueKind == System.Text.Json.JsonValueKind.Array)
            {
                foreach (var row in list.EnumerateArray())
                {
                    if (row.ValueKind != System.Text.Json.JsonValueKind.Object)
                    {
                        continue;
                    }

                    var text = row.TryGetProperty("text", out var words) && words.ValueKind == System.Text.Json.JsonValueKind.String
                        ? (words.GetString() ?? "").Trim()
                        : "";
                    if (text.Length == 0)
                    {
                        continue;
                    }

                    var id = row.TryGetProperty("id", out var key) && key.ValueKind == System.Text.Json.JsonValueKind.String
                        ? (key.GetString() ?? "")
                        : "";
                    if (id.Length == 0)
                    {
                        var ts = row.TryGetProperty("ts", out var stamp) && stamp.ValueKind == System.Text.Json.JsonValueKind.String
                            ? stamp.GetString() ?? ""
                            : "";
                        id = ts + "|" + text;
                    }

                    lines.Add(new MicTranscriptLine(id, text));
                }
            }

            return new MicTranscript(listening && !paused, paused || !listening, lines);
        }
        catch (System.Text.Json.JsonException)
        {
            return null;
        }
    }
}

public sealed record TwinLiveLine(string Who, string Text);

public sealed record TwinLiveFrame(
    string Status,
    bool CanAnswer,
    IReadOnlyList<TwinLiveLine> Lines,
    string CaptionId,
    IReadOnlyList<string> SeenMicIds)
{
    public static TwinLiveFrame Empty { get; } = new("Paused", false, Array.Empty<TwinLiveLine>(), "", Array.Empty<string>());
}

/// <summary>
/// Folds observer microphone words and twin captions into one board.
/// A paused poll keeps lines already shown. Confirm stays off while paused.
/// </summary>
public static class TwinLiveBoard
{
    public const string You = "You";
    public const string Twin = "Twin";

    public static TwinLiveFrame Next(
        TwinLiveFrame prior,
        bool listening,
        IReadOnlyList<MicTranscriptLine>? mic,
        string caption,
        string captionId,
        string pendingId)
    {
        var lines = new List<TwinLiveLine>(prior.Lines);
        var seen = new HashSet<string>(prior.SeenMicIds, StringComparer.Ordinal);
        if (mic is not null)
        {
            foreach (var row in mic)
            {
                if (row.Id.Length == 0 || !seen.Add(row.Id))
                {
                    continue;
                }

                lines.Add(new TwinLiveLine(You, row.Text));
            }
        }

        var shown = prior.CaptionId;
        var reply = (caption ?? "").Trim();
        if (captionId.Length > 0 && captionId != shown && reply.Length > 0)
        {
            lines.Add(new TwinLiveLine(Twin, reply));
            shown = captionId;
        }

        if (lines.Count > 80)
        {
            lines = lines.GetRange(lines.Count - 80, 80);
        }

        if (seen.Count > 200)
        {
            seen = new HashSet<string>(seen.Skip(seen.Count - 200), StringComparer.Ordinal);
        }

        return new TwinLiveFrame(
            listening ? "Listening" : "Paused",
            listening && pendingId.Length > 0,
            lines,
            shown,
            seen.ToArray());
    }
}
