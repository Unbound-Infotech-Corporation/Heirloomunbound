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
