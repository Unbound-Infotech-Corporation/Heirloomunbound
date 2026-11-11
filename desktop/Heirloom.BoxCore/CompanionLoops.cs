namespace Heirloom.BoxCore;

/// <summary>
/// Companion poll loops must survive a hung socket after sleep. A pass that
/// never finishes is cancelled, and the loop starts again.
/// </summary>
public static class LoopGuard
{
    public static readonly TimeSpan StaleAfter = TimeSpan.FromMinutes(3);
    public static readonly TimeSpan InitialBackoff = TimeSpan.FromSeconds(2);
    public static readonly TimeSpan MaxBackoff = TimeSpan.FromSeconds(30);

    public static TimeSpan Backoff(int failures)
    {
        if (failures <= 0)
        {
            return TimeSpan.Zero;
        }

        var seconds = InitialBackoff.TotalSeconds * Math.Pow(2, failures - 1);
        return TimeSpan.FromSeconds(Math.Min(MaxBackoff.TotalSeconds, seconds));
    }

    public static bool IsStale(DateTimeOffset lastSuccessUtc, DateTimeOffset nowUtc, TimeSpan? staleAfter = null) =>
        nowUtc - lastSuccessUtc >= (staleAfter ?? StaleAfter);
}

public static class WakeReason
{
    public const string SleepResume = "sleep-resume";
    public const string Network = "network";
    public const string Watchdog = "watchdog";
}

public static class RequestDeadline
{
    public static readonly TimeSpan Connect = TimeSpan.FromSeconds(5);
    public static readonly TimeSpan Health = TimeSpan.FromSeconds(8);
    public static readonly TimeSpan Poll = TimeSpan.FromSeconds(12);
    public static readonly TimeSpan Upload = TimeSpan.FromSeconds(15);

    public static CancellationTokenSource Link(CancellationToken outer, TimeSpan timeout)
    {
        var linked = CancellationTokenSource.CreateLinkedTokenSource(outer);
        linked.CancelAfter(timeout);
        return linked;
    }
}

public sealed class WakeHub
{
    private readonly object _gate = new();
    private DateTimeOffset _lastNetwork = DateTimeOffset.MinValue;

    public event Action<string>? Raised;

    public bool Raise(string reason, DateTimeOffset now)
    {
        if (reason == WakeReason.Network)
        {
            lock (_gate)
            {
                if (now - _lastNetwork < TimeSpan.FromSeconds(5))
                {
                    return false;
                }

                _lastNetwork = now;
            }
        }

        Raised?.Invoke(reason);
        return true;
    }
}

public sealed class LoopHealth
{
    private DateTimeOffset _lastSuccess;
    private int _failures;

    public LoopHealth(DateTimeOffset startedUtc)
    {
        _lastSuccess = startedUtc;
    }

    public int Failures => _failures;

    public DateTimeOffset LastSuccessUtc => _lastSuccess;

    public void NoteSuccess(DateTimeOffset nowUtc)
    {
        _lastSuccess = nowUtc;
        _failures = 0;
    }

    public TimeSpan NoteFailure()
    {
        _failures++;
        return LoopGuard.Backoff(_failures);
    }

    public bool IsStale(DateTimeOffset nowUtc, TimeSpan? staleAfter = null) =>
        LoopGuard.IsStale(_lastSuccess, nowUtc, staleAfter);

    public void Kick(DateTimeOffset nowUtc)
    {
        _lastSuccess = nowUtc;
        _failures = 0;
    }
}

/// <summary>
/// Rolling text log. It only writes under its own directory and never touches settings.json.
/// </summary>
public sealed class CompanionLog
{
    public const long MaxBytes = 256 * 1024;
    public const int KeptFiles = 3;

    public CompanionLog(string directory)
    {
        DirectoryPath = directory;
    }

    public string DirectoryPath { get; }

    public static string DefaultDirectory()
    {
        var root = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        return Path.Combine(string.IsNullOrWhiteSpace(root) ? "." : root, "Heirloom", "logs");
    }

    public void Write(string loop, string message)
    {
        Directory.CreateDirectory(DirectoryPath);
        var path = Path.Combine(DirectoryPath, "companion.log");
        if (string.Equals(Path.GetFileName(path), "settings.json", StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidOperationException("refusing to write settings.json");
        }

        Rotate(path);
        var line = DateTimeOffset.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ", System.Globalization.CultureInfo.InvariantCulture)
            + " "
            + loop
            + " "
            + (message ?? "").Replace('\r', ' ').Replace('\n', ' ')
            + Environment.NewLine;
        File.AppendAllText(path, line);
    }

    private static void Rotate(string path)
    {
        var info = new FileInfo(path);
        if (!info.Exists || info.Length < MaxBytes)
        {
            return;
        }

        var oldest = path + "." + (KeptFiles - 1);
        if (File.Exists(oldest))
        {
            File.Delete(oldest);
        }

        for (var index = KeptFiles - 2; index >= 1; index--)
        {
            var source = path + "." + index;
            var dest = path + "." + (index + 1);
            if (File.Exists(source))
            {
                File.Move(source, dest, overwrite: true);
            }
        }

        File.Move(path, path + ".1", overwrite: true);
    }
}

public sealed class SupervisedLoop
{
    private readonly string _name;
    private readonly CompanionLog _log;
    private readonly LoopHealth _health;
    private readonly object _gate = new();
    private CancellationTokenSource? _pass;

    public SupervisedLoop(string name, CompanionLog log, WakeHub? wake = null, DateTimeOffset? startedUtc = null)
    {
        _name = name;
        _log = log;
        _health = new LoopHealth(startedUtc ?? DateTimeOffset.UtcNow);
        if (wake is not null)
        {
            wake.Raised += OnWake;
        }
    }

    public TimeSpan StaleAfter { get; init; } = LoopGuard.StaleAfter;

    public TimeSpan WatchPeriod { get; init; } = TimeSpan.FromSeconds(20);

    public Func<DateTimeOffset> Clock { get; init; } = () => DateTimeOffset.UtcNow;

    public LoopHealth Health => _health;

    public async Task RunAsync(Func<CancellationToken, Task> iteration, CancellationToken appStop)
    {
        using var watchStop = CancellationTokenSource.CreateLinkedTokenSource(appStop);
        var watch = WatchAsync(watchStop.Token);
        try
        {
            while (!appStop.IsCancellationRequested)
            {
                using var pass = CancellationTokenSource.CreateLinkedTokenSource(appStop);
                lock (_gate)
                {
                    _pass = pass;
                }

                try
                {
                    await iteration(pass.Token).ConfigureAwait(false);
                    _health.NoteSuccess(Clock());
                }
                catch (OperationCanceledException) when (appStop.IsCancellationRequested)
                {
                    return;
                }
                catch (OperationCanceledException)
                {
                    _log.Write(_name, "pass cancelled");
                    await SafeDelay(TimeSpan.FromMilliseconds(200), appStop).ConfigureAwait(false);
                }
                catch (Exception ex)
                {
                    var wait = _health.NoteFailure();
                    _log.Write(_name, ex.GetType().Name + ": " + ex.Message);
                    await SafeDelay(wait, appStop).ConfigureAwait(false);
                }
            }
        }
        finally
        {
            watchStop.Cancel();
            try
            {
                await watch.ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
            }
        }
    }

    private void OnWake(string reason)
    {
        _log.Write(_name, "resume after " + reason);
        _health.Kick(Clock());
        CancelPass();
    }

    public void CancelPass()
    {
        CancellationTokenSource? pass;
        lock (_gate)
        {
            pass = _pass;
        }

        try
        {
            pass?.Cancel();
        }
        catch (ObjectDisposedException)
        {
        }
    }

    private async Task WatchAsync(CancellationToken token)
    {
        while (!token.IsCancellationRequested)
        {
            try
            {
                await Task.Delay(WatchPeriod, token).ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
                return;
            }

            if (_health.IsStale(Clock(), StaleAfter))
            {
                _log.Write(_name, "watchdog restart");
                _health.Kick(Clock());
                CancelPass();
            }
        }
    }

    private static async Task SafeDelay(TimeSpan wait, CancellationToken token)
    {
        if (wait <= TimeSpan.Zero)
        {
            return;
        }

        try
        {
            await Task.Delay(wait, token).ConfigureAwait(false);
        }
        catch (OperationCanceledException) when (token.IsCancellationRequested)
        {
        }
    }
}
