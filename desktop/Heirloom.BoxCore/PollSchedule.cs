namespace Heirloom.BoxCore;

public static class PollSchedule
{
    public static readonly TimeSpan Healthy = TimeSpan.FromSeconds(5);
    public static readonly TimeSpan Max = TimeSpan.FromSeconds(60);

    public static TimeSpan Next(TimeSpan current, bool ok)
    {
        if (ok)
        {
            return Healthy;
        }

        var start = current <= TimeSpan.Zero ? Healthy : current;
        var doubled = TimeSpan.FromMilliseconds(start.TotalMilliseconds * 2);
        return doubled > Max ? Max : doubled;
    }
}
