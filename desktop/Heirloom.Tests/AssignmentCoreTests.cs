using Heirloom.Services;
using Xunit;

namespace Heirloom.Tests;

public class AssignmentCoreTests
{
    [Fact]
    public void Legal_transitions_match_the_server_table()
    {
        Assert.True(AssignmentCore.CanTransition("queued", "running"));
        Assert.True(AssignmentCore.CanTransition("queued", "cancelled"));
        Assert.True(AssignmentCore.CanTransition("running", "needs_approval"));
        Assert.True(AssignmentCore.CanTransition("needs_approval", "done"));
        Assert.False(AssignmentCore.CanTransition("done", "running"));
        Assert.False(AssignmentCore.CanTransition("cancelled", "queued"));
        Assert.False(AssignmentCore.CanTransition("queued", "done"));
        Assert.Equal("Needs approval", AssignmentCore.StatusLabel("needs_approval"));
        Assert.Empty(AssignmentCore.NextStatuses("done"));
    }

    [Fact]
    public void Act_does_not_bypass_outbound_approval()
    {
        Assert.True(AssignmentCore.EffectNeedsApproval("send", "act"));
        Assert.True(AssignmentCore.EffectNeedsApproval("send_email", "act"));
        Assert.True(AssignmentCore.EffectNeedsApproval("post", "ask"));
        Assert.True(AssignmentCore.EffectNeedsApproval("delete", "act"));
        Assert.True(AssignmentCore.EffectNeedsApproval("spend", "act"));
        Assert.False(AssignmentCore.EffectNeedsApproval("summarize", "ask"));
        Assert.False(AssignmentCore.EffectNeedsApproval("read", "act"));
    }

    [Fact]
    public void Presets_prefill_draft_only()
    {
        var triage = AssignmentCore.Prefill("triage_email");
        Assert.Equal("Triage email", triage.Title);
        Assert.Equal("draft", triage.Autonomy);
        Assert.Contains("Do not send", triage.Scope, StringComparison.Ordinal);

        var thread = AssignmentCore.Prefill("summarize");
        Assert.Equal("summarize_thread", thread.Id);
        Assert.Equal("draft", thread.Autonomy);

        var blank = AssignmentCore.Prefill("blank");
        Assert.Equal("", blank.Title);
        Assert.Equal("", blank.Goal);
    }

    [Fact]
    public void Approval_paths_are_owner_session_routes()
    {
        Assert.Equal("/assignments", AssignmentCore.ListPath);
        Assert.Equal("/approvals/apr_abc/approve", AssignmentCore.ApprovalPath("apr_abc", true));
        Assert.Equal("/approvals/apr_abc/decline", AssignmentCore.ApprovalPath("apr_abc", false));
    }
}
