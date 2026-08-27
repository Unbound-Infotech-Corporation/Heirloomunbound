namespace Heirloom.Services;

public static class FaultLog
{
    public static string Path { get; } = System.IO.Path.Combine(AppPaths.Root, "faults.log");

    public static void Write(string area, string detail)
    {
        try
        {
            AppPaths.EnsureDirectories();
            var line = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") + "  " + area + "  " + (detail ?? "").Replace('\r', ' ').Replace('\n', ' ') + Environment.NewLine;
            File.AppendAllText(Path, line);
        }
        catch
        {
            // Logging must never throw into the studio.
        }
    }
}
