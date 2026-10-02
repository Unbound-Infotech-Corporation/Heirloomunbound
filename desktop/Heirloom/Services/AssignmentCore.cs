namespace Heirloom.Services;

/// <summary>
/// Assignments v1 shared with the web studio. Pure rules only.
/// The WinUI list document is a follow-up; the session client can already
/// list assignments and decide approvals.
/// </summary>
public static class AssignmentCore
{
    public const string ListPath = "/assignments";
    public const string ApprovalsPath = "/approvals?status=pending";

    public static readonly string[] Statuses =
    [
        "queued",
        "running",
        "needs_approval",
        "done",
        "failed",
        "cancelled",
    ];

    private static readonly Dictionary<string, string[]> Legal = new(StringComparer.Ordinal)
    {
        ["queued"] = ["running", "cancelled"],
        ["running"] = ["needs_approval", "done", "failed", "cancelled"],
        ["needs_approval"] = ["done", "cancelled", "failed"],
        ["done"] = [],
        ["failed"] = [],
        ["cancelled"] = [],
    };

    private static readonly HashSet<string> Outbound = new(StringComparer.Ordinal)
    {
        "send", "post", "delete", "spend",
    };

    private static readonly HashSet<string> Internal = new(StringComparer.Ordinal)
    {
        "read", "draft", "summarize", "summary", "write", "artifact",
    };

    public readonly record struct Preset(string Id, string Label, string Title, string Goal, string Scope, string Autonomy);

    public static bool CanTransition(string? from, string? to)
    {
        var src = (from ?? "").Trim().ToLowerInvariant();
        var dst = (to ?? "").Trim().ToLowerInvariant();
        return Legal.TryGetValue(src, out var next) && next.Contains(dst, StringComparer.Ordinal);
    }

    public static IReadOnlyList<string> NextStatuses(string? from)
    {
        var src = (from ?? "").Trim().ToLowerInvariant();
        return Legal.TryGetValue(src, out var next) ? next : [];
    }

    public static string StatusLabel(string? status) => (status ?? "").Trim().ToLowerInvariant() switch
    {
        "queued" => "Queued",
        "running" => "Running",
        "needs_approval" => "Needs approval",
        "done" => "Done",
        "failed" => "Failed",
        "cancelled" => "Cancelled",
        _ => "Unknown",
    };

    /// <summary>
    /// Send, post, delete, and spend always need an approval.
    /// Act does not bypass them. Read, draft, summarize, and write do not ask.
    /// </summary>
    public static bool EffectNeedsApproval(string? actionKind, string? cloneAutonomy)
    {
        var kind = NormalizeKind(actionKind);
        var autonomy = string.Equals(cloneAutonomy, "act", StringComparison.OrdinalIgnoreCase) ? "act" : "ask";
        if (Internal.Contains(kind))
        {
            return false;
        }

        if (Outbound.Contains(kind))
        {
            return true;
        }

        return autonomy is "ask" or "act";
    }

    public static Preset Prefill(string? presetId)
    {
        var key = (presetId ?? "").Trim().ToLowerInvariant().Replace(' ', '_').Replace('-', '_');
        key = key switch
        {
            "triage" or "email" => "triage_email",
            "summarize" or "summary" or "thread" => "summarize_thread",
            _ => key,
        };
        return key switch
        {
            "triage_email" => new Preset(
                "triage_email",
                "Triage email",
                "Triage email",
                "Read what the owner pointed at and draft a short triage: what needs a reply, what can wait, and what to leave alone.",
                "Heirloom only. Draft replies. Do not send email.",
                "draft"),
            "summarize_thread" => new Preset(
                "summarize_thread",
                "Summarize thread",
                "Summarize thread",
                "Summarize the thread into a short note the owner can act on.",
                "Read the thread. Write a summary artifact. Do not reply, post, or send.",
                "draft"),
            _ => new Preset("blank", "Blank", "", "", "", "draft"),
        };
    }

    public static string ApprovalPath(string approvalId, bool approve)
    {
        var id = (approvalId ?? "").Trim();
        return approve ? $"/approvals/{id}/approve" : $"/approvals/{id}/decline";
    }

    private static string NormalizeKind(string? kind)
    {
        var key = (kind ?? "").Trim().ToLowerInvariant().Replace('-', '_').Replace(' ', '_');
        return key switch
        {
            "send_email" or "send_message" or "email" or "message" => "send",
            "post_message" => "post",
            "spend_money" or "purchase" or "pay" => "spend",
            "remove" => "delete",
            _ => key,
        };
    }
}
