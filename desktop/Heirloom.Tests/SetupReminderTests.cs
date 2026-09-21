using Heirloom.Services;
using Xunit;

namespace Heirloom.Tests;

public class SetupReminderTests
{
    [Fact]
    public void Incomplete_account_shows_critical_coach()
    {
        var snap = TwinSetupProgress.Build(false, 0, false, dismissed: false, heirMode: false);
        Assert.True(snap.Visible);
        Assert.False(snap.YoureSet);
        Assert.Equal(2, snap.RemainingCritical);
        Assert.Contains(snap.Steps, s => s.Id == "voice" && !s.Done && s.Critical);
        Assert.Contains(snap.Steps, s => s.Id == "likeness" && !s.Done && s.Critical);
        Assert.Equal(3, snap.Steps.First(s => s.Id == "voice").Examples.Count);
        Assert.Equal(3, snap.Steps.First(s => s.Id == "likeness").Need);
    }

    [Fact]
    public void Voice_and_three_photos_clears_coach()
    {
        var snap = TwinSetupProgress.Build(true, 3, true, dismissed: false, heirMode: false);
        Assert.False(snap.Visible);
        Assert.True(snap.AllCriticalDone);
        Assert.True(snap.YoureSet);
        Assert.Equal(0, snap.RemainingCritical);
    }

    [Fact]
    public void Dismissed_hides_until_reopened()
    {
        var hidden = TwinSetupProgress.Build(false, 1, false, dismissed: true, heirMode: false);
        Assert.False(hidden.Visible);
        Assert.True(hidden.Dismissed);
        Assert.Equal(2, hidden.RemainingCritical);

        var open = TwinSetupProgress.Build(false, 1, false, dismissed: false, heirMode: false);
        Assert.True(open.Visible);
    }

    [Fact]
    public void Heir_mode_never_shows_the_coach()
    {
        var snap = TwinSetupProgress.Build(false, 0, false, dismissed: false, heirMode: true);
        Assert.False(snap.Visible);
        Assert.False(snap.YoureSet);
    }

    [Fact]
    public void Partial_photos_keep_likeness_open()
    {
        var snap = TwinSetupProgress.Build(true, 1, false, dismissed: false, heirMode: false);
        Assert.True(snap.Visible);
        Assert.Equal(1, snap.RemainingCritical);
        var likeness = snap.Steps.First(s => s.Id == "likeness");
        Assert.Equal(1, likeness.Have);
        Assert.False(likeness.Done);
    }
}
