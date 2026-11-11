namespace Heirloom.BoxCore;

/// <summary>
/// Rewrite card for the Companion hotkey. Paste-back returns text only after approval.
/// The passphrase-style rule is the same: the proposal is not a send.
/// </summary>
public sealed class WritingPaste
{
    public WritingPaste(string before, string after)
    {
        Before = before ?? "";
        After = after ?? "";
    }

    public string Before { get; }
    public string After { get; }
    public bool Approved { get; private set; }

    public static WritingPaste Propose(string selected, string mode = "shorter")
    {
        var text = selected ?? "";
        var after = mode switch
        {
            "formal" => text.Replace("don't", "do not", StringComparison.OrdinalIgnoreCase),
            "friendlier" => text.Replace("do not", "don't", StringComparison.OrdinalIgnoreCase),
            _ => text.Replace("very ", "", StringComparison.OrdinalIgnoreCase)
                .Replace("really ", "", StringComparison.OrdinalIgnoreCase),
        };
        return new WritingPaste(text.Trim(), after.Trim());
    }

    public void Approve() => Approved = true;

    public string? PasteBack() => Approved ? After : null;
}

/// <summary>
/// The hotkey copies the highlight first. A clipboard that did not change was not the selection.
/// </summary>
public static class SelectionCapture
{
    public static string AfterCopy(bool copySent, string? before, string? copied)
    {
        if (!copySent)
        {
            return "";
        }

        var next = copied ?? "";
        if (next == (before ?? ""))
        {
            return "";
        }

        return next;
    }
}

/// <summary>
/// Ctrl+Alt+H is still held when the hook runs. Release those keys before Ctrl+C.
/// </summary>
public static class CopyChord
{
    public const byte VkMenu = 0x12;
    public const byte VkControl = 0x11;
    public const byte VkH = 0x48;
    public const byte VkC = 0x43;

    public static IReadOnlyList<(byte Key, bool Down)> Sequence() =>
    [
        (VkH, false),
        (VkMenu, false),
        (VkControl, false),
        (VkControl, true),
        (VkC, true),
        (VkC, false),
        (VkControl, false),
    ];
}
