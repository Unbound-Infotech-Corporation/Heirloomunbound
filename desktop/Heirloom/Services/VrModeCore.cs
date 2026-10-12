namespace Heirloom.Services;

/// <summary>
/// Owner VR preference for the Room. The saved switch is not a session.
/// Launch stays on the normal screen even when a headset is connected.
/// </summary>
public enum VrSurface
{
    Room,
    Settings,
}

public sealed record VrPrefs(bool Enabled, bool GazeEnabled)
{
    public static VrPrefs Default { get; } = new(false, false);
}

public sealed record VrLaunch(VrPrefs Prefs, bool SessionActive, bool AutoEnter);

public sealed record VrToggleDecision(VrPrefs Prefs, bool StartSession, bool EndSession, string Reason);

public static class VrModeCore
{
    public const string GazeExtension = "XR_EXT_eye_gaze_interaction";
    public const int MinDwellMs = 400;

    public static bool Allowed(string? audience, bool heirSurface)
    {
        if (heirSurface)
        {
            return false;
        }

        return string.Equals(audience ?? "owner", "owner", StringComparison.OrdinalIgnoreCase);
    }

    public static VrPrefs Clamp(bool enabled, bool gazeEnabled) => new(enabled, gazeEnabled);

    public static bool ShouldAutoEnter(bool headsetConnected, bool enabled)
    {
        _ = headsetConnected;
        _ = enabled;
        return false;
    }

    public static VrLaunch Launch(bool enabled, bool gazeEnabled, bool headsetConnected = false)
    {
        var prefs = Clamp(enabled, gazeEnabled);
        return new VrLaunch(prefs, SessionActive: false, AutoEnter: ShouldAutoEnter(headsetConnected, prefs.Enabled));
    }

    /// <summary>
    /// Account payloads may echo a session flag. It is ignored on launch.
    /// </summary>
    public static VrLaunch FromAccount(bool? enabled, bool? gazeEnabled, bool? sessionActive, bool headsetConnected = false)
    {
        _ = sessionActive;
        return Launch(enabled ?? false, gazeEnabled ?? false, headsetConnected);
    }

    public static VrToggleDecision Toggle(VrPrefs current, bool nextEnabled, bool gesture, VrSurface surface, bool sessionActive)
    {
        current ??= VrPrefs.Default;
        if (!gesture)
        {
            return new VrToggleDecision(current, false, false, "no-gesture");
        }

        if (!nextEnabled)
        {
            return new VrToggleDecision(new VrPrefs(false, current.GazeEnabled), false, true, "toggled-off");
        }

        var next = new VrPrefs(true, current.GazeEnabled);
        if (surface != VrSurface.Room)
        {
            return new VrToggleDecision(next, false, false, "settings");
        }

        return new VrToggleDecision(next, !sessionActive, false, "user-gesture");
    }

    public static VrToggleDecision Enter(VrPrefs current, bool gesture, bool sessionActive)
    {
        current ??= VrPrefs.Default;
        if (!gesture)
        {
            return new VrToggleDecision(current, false, false, "no-gesture");
        }

        if (!current.Enabled)
        {
            return new VrToggleDecision(current, false, false, "off");
        }

        if (sessionActive)
        {
            return new VrToggleDecision(current, false, false, "already");
        }

        return new VrToggleDecision(current, true, false, "user-gesture");
    }

    public static VrToggleDecision Gaze(VrPrefs current, bool nextGaze, bool gesture)
    {
        current ??= VrPrefs.Default;
        if (!gesture)
        {
            return new VrToggleDecision(current, false, false, "no-gesture");
        }

        return new VrToggleDecision(new VrPrefs(current.Enabled, nextGaze), false, false, "gaze");
    }

    public static string GazeDecision(bool gazeEnabled, bool paused, string? audience, bool heirSurface, bool available, int summaryCount)
    {
        if (!Allowed(audience, heirSurface))
        {
            return "heir";
        }

        if (!gazeEnabled)
        {
            return "opt-in-off";
        }

        if (paused)
        {
            return "paused";
        }

        if (!available)
        {
            return "unavailable";
        }

        if (summaryCount <= 0)
        {
            return "empty";
        }

        return "ok";
    }

    public static IReadOnlyList<(string Area, int DwellMs)> AggregateGaze(IEnumerable<(string Area, int DwellMs)> samples)
    {
        var allowed = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            "twin", "seat", "room", "floor", "elsewhere",
        };
        var totals = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
        var order = new List<string>();
        foreach (var (area, dwell) in samples)
        {
            var key = (area ?? "").Trim().ToLowerInvariant();
            if (!allowed.Contains(key) || dwell <= 0)
            {
                continue;
            }

            if (!totals.ContainsKey(key))
            {
                order.Add(key);
                totals[key] = 0;
            }

            totals[key] += dwell;
        }

        return order
            .Where(area => totals[area] >= MinDwellMs)
            .Select(area => (area, totals[area]))
            .ToList();
    }
}
