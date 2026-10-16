namespace Heirloom.Services;

public static class FaultLog
{
    public static string Path { get; } = System.IO.Path.Combine(AppPaths.Root, "faults.log");

    public static string FallbackPath { get; } = System.IO.Path.Combine(System.IO.Path.GetTempPath(), "Heirloom", "faults.log");

    public static void Write(string area, string detail)
    {
        var line = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") + "  " + area + "  " + (detail ?? "").Replace('\r', ' ').Replace('\n', ' ') + Environment.NewLine;
        if (TryAppend(Path, line))
        {
            return;
        }

        TryAppend(FallbackPath, line);
    }

    private static bool TryAppend(string path, string line)
    {
        try
        {
            var folder = System.IO.Path.GetDirectoryName(path);
            if (!string.IsNullOrEmpty(folder))
            {
                Directory.CreateDirectory(folder);
            }

            File.AppendAllText(path, line);
            return true;
        }
        catch
        {
            return false;
        }
    }
}
