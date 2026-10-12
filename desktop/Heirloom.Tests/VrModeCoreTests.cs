using Heirloom.Services;
using Xunit;

namespace Heirloom.Tests;

public class VrModeCoreTests
{
    [Fact]
    public void Launch_stays_on_the_normal_screen()
    {
        var fresh = VrModeCore.Launch(false, false, headsetConnected: true);
        Assert.False(fresh.Prefs.Enabled);
        Assert.False(fresh.Prefs.GazeEnabled);
        Assert.False(fresh.SessionActive);
        Assert.False(fresh.AutoEnter);

        var saved = VrModeCore.FromAccount(true, true, sessionActive: true, headsetConnected: true);
        Assert.True(saved.Prefs.Enabled);
        Assert.True(saved.Prefs.GazeEnabled);
        Assert.False(saved.SessionActive);
        Assert.False(saved.AutoEnter);
        Assert.False(VrModeCore.ShouldAutoEnter(headsetConnected: true, enabled: true));
    }

    [Fact]
    public void Toggle_starts_only_from_a_room_gesture()
    {
        var off = VrPrefs.Default;
        var silent = VrModeCore.Toggle(off, nextEnabled: true, gesture: false, VrSurface.Room, sessionActive: false);
        Assert.False(silent.StartSession);
        Assert.Equal("no-gesture", silent.Reason);

        var settings = VrModeCore.Toggle(off, nextEnabled: true, gesture: true, VrSurface.Settings, sessionActive: false);
        Assert.False(settings.StartSession);
        Assert.True(settings.Prefs.Enabled);
        Assert.Equal("settings", settings.Reason);

        var room = VrModeCore.Toggle(off, nextEnabled: true, gesture: true, VrSurface.Room, sessionActive: false);
        Assert.True(room.StartSession);
        Assert.Equal("user-gesture", room.Reason);

        var leave = VrModeCore.Toggle(room.Prefs, nextEnabled: false, gesture: true, VrSurface.Room, sessionActive: true);
        Assert.True(leave.EndSession);
        Assert.False(leave.Prefs.Enabled);
        Assert.False(leave.StartSession);
    }

    [Fact]
    public void Saved_on_still_needs_a_click()
    {
        var launched = VrModeCore.Launch(true, false, headsetConnected: true);
        Assert.False(launched.SessionActive);
        var blocked = VrModeCore.Enter(launched.Prefs, gesture: false, sessionActive: false);
        Assert.False(blocked.StartSession);
        var entered = VrModeCore.Enter(launched.Prefs, gesture: true, sessionActive: false);
        Assert.True(entered.StartSession);
        Assert.Equal("user-gesture", entered.Reason);
    }

    [Fact]
    public void Gaze_is_opt_in_and_heirs_are_fenced()
    {
        var gaze = VrModeCore.Gaze(VrPrefs.Default, nextGaze: true, gesture: true);
        Assert.False(gaze.StartSession);
        Assert.True(gaze.Prefs.GazeEnabled);
        Assert.False(gaze.Prefs.Enabled);
        Assert.Equal("no-gesture", VrModeCore.Gaze(VrPrefs.Default, true, gesture: false).Reason);

        var summaries = VrModeCore.AggregateGaze(
        [
            ("twin", 200),
            ("twin", 900),
            ("floor", 1200),
            ("nope", 5000),
        ]);
        Assert.Equal([("twin", 1100), ("floor", 1200)], summaries);

        Assert.Equal("opt-in-off", VrModeCore.GazeDecision(false, false, "owner", false, true, 1));
        Assert.Equal("paused", VrModeCore.GazeDecision(true, true, "owner", false, true, 1));
        Assert.Equal("unavailable", VrModeCore.GazeDecision(true, false, "owner", false, false, 1));
        Assert.Equal("heir", VrModeCore.GazeDecision(true, false, "heir", false, true, 1));
        Assert.Equal("heir", VrModeCore.GazeDecision(true, false, "owner", true, true, 1));
        Assert.False(VrModeCore.Allowed("caller", false));
        Assert.True(VrModeCore.Allowed("owner", false));
        Assert.Equal(VrModeCore.GazeExtension, "XR_EXT_eye_gaze_interaction");
    }
}
