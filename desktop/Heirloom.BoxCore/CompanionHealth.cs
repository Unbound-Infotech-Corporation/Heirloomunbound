namespace Heirloom.BoxCore;

/// <summary>
/// The supervised health loop resumes on the thread pool after its first await.
/// Tray icons, menus, and WPF windows are STA objects and throw
/// "The calling thread cannot access this object because a different thread owns it"
/// if the poll touches them on that pool thread.
/// </summary>
public static class CompanionHealthPass
{
    public static async Task RunAsync(
        Func<CancellationToken, Task> work,
        Action applyUi,
        Func<bool> onOwnerThread,
        Action<Action> postToOwner,
        CancellationToken cancellationToken)
    {
        await work(cancellationToken).ConfigureAwait(false);
        if (onOwnerThread())
        {
            applyUi();
            return;
        }

        postToOwner(applyUi);
    }
}

/// <summary>
/// Test double for a tray icon created on one thread. Touching it elsewhere throws
/// the same exception WPF raises for a DispatcherObject.
/// </summary>
public sealed class StaAffinity
{
    private readonly int _owner = Environment.CurrentManagedThreadId;

    public int Touches { get; private set; }

    public bool OnOwnerThread => Environment.CurrentManagedThreadId == _owner;

    public void Touch()
    {
        if (!OnOwnerThread)
        {
            throw new InvalidOperationException(
                "The calling thread cannot access this object because a different thread owns it.");
        }

        Touches++;
    }
}

public static class HealthLog
{
    public static readonly TimeSpan Heartbeat = TimeSpan.FromMinutes(5);

    public static string Line(bool reachable, bool signedIn, BoxLamp lamp) =>
        "ok reachable=" + (reachable ? "yes" : "no")
        + " signed-in=" + (signedIn ? "yes" : "no")
        + " lamp=" + lamp.ToString().ToLowerInvariant();

    public static bool ShouldWrite(DateTimeOffset? lastWrite, DateTimeOffset now, bool changed, TimeSpan? heartbeat = null)
    {
        if (lastWrite is null || changed)
        {
            return true;
        }

        return now - lastWrite.Value >= (heartbeat ?? Heartbeat);
    }
}

/// <summary>
/// One HKCU Run value for the Companion. The legacy unspaced name is removed
/// so a reboot cannot start a second copy of the same executable.
/// </summary>
/// <summary>
/// Caretaker restart starts the replacement process and then shuts this one down.
/// The single-instance mutex must be released first, or the child WaitOne(0) fails and exits.
/// </summary>
public static class InstanceHandoff
{
    public static void Restart(Action release, Action start, Action shutdown)
    {
        release();
        start();
        shutdown();
    }
}

public static class CompanionAutostart
{
    public const string ValueName = "Heirloom Companion";

    public static readonly string[] LegacyNames = ["HeirloomCompanion"];

    public readonly record struct Plan(IReadOnlyList<string> Delete, string? WriteName, string? WriteValue);

    public static Plan Build(bool enabled, string? exePath)
    {
        var delete = new List<string>();
        if (!enabled)
        {
            delete.Add(ValueName);
        }

        delete.AddRange(LegacyNames);
        if (!enabled || string.IsNullOrWhiteSpace(exePath))
        {
            return new Plan(delete, null, null);
        }

        var exe = exePath.Trim().Trim('"');
        return new Plan(delete, ValueName, "\"" + exe + "\"");
    }
}
