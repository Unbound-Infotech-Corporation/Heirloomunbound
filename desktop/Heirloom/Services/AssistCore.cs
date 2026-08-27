using System.Diagnostics;
using System.Text.Json;

namespace Heirloom.Services;

public static class PathGuard
{
    public static bool IsUnder(string path, string root)
    {
        if (string.IsNullOrWhiteSpace(path) || string.IsNullOrWhiteSpace(root))
        {
            return false;
        }

        string full;
        string prefix;
        try
        {
            full = Path.GetFullPath(path);
            prefix = Path.GetFullPath(root);
        }
        catch
        {
            return false;
        }

        var fullNorm = TrimSlash(full);
        var rootNorm = TrimSlash(prefix);
        if (fullNorm.Equals(rootNorm, StringComparison.OrdinalIgnoreCase))
        {
            return true;
        }

        var withSep = rootNorm + Path.DirectorySeparatorChar;
        return fullNorm.StartsWith(withSep, StringComparison.OrdinalIgnoreCase);
    }

    private static string TrimSlash(string path) =>
        path.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
}

public static class LaunchTarget
{
    public enum Kind
    {
        App,
        Url,
        Path,
    }

    public readonly record struct Resolved(Kind Kind, string Value);

    private static readonly Dictionary<string, string> Known = new(StringComparer.OrdinalIgnoreCase)
    {
        ["notepad"] = "notepad",
        ["notepad.exe"] = "notepad",
        ["calc"] = "calc",
        ["calculator"] = "calc",
        ["explorer"] = "explorer",
        ["files"] = "explorer",
        ["file explorer"] = "explorer",
        ["cmd"] = "cmd",
        ["command prompt"] = "cmd",
        ["powershell"] = "powershell",
        ["pwsh"] = "pwsh",
        ["terminal"] = "wt",
        ["windows terminal"] = "wt",
        ["code"] = "code",
        ["vscode"] = "code",
        ["vs code"] = "code",
        ["visual studio code"] = "code",
        ["chrome"] = "chrome",
        ["google chrome"] = "chrome",
        ["edge"] = "msedge",
        ["msedge"] = "msedge",
        ["microsoft edge"] = "msedge",
        ["firefox"] = "firefox",
        ["paint"] = "mspaint",
        ["mspaint"] = "mspaint",
        ["snipping tool"] = "snippingtool",
        ["snippingtool"] = "snippingtool",
        ["task manager"] = "taskmgr",
        ["taskmgr"] = "taskmgr",
        ["control"] = "control",
        ["settings"] = "ms-settings:",
        ["word"] = "winword",
        ["excel"] = "excel",
        ["powerpoint"] = "powerpnt",
        ["outlook"] = "outlook",
        ["spotify"] = "spotify",
        ["discord"] = "discord",
        ["steam"] = "steam",
        ["photos"] = "ms-photos:",
    };

    public static Resolved Resolve(string target)
    {
        var value = (target ?? "").Trim().Trim('"');
        if (value.Length == 0)
        {
            return new Resolved(Kind.App, "");
        }

        if (value.StartsWith("http://", StringComparison.OrdinalIgnoreCase)
            || value.StartsWith("https://", StringComparison.OrdinalIgnoreCase)
            || value.StartsWith("ms-settings:", StringComparison.OrdinalIgnoreCase)
            || value.StartsWith("ms-photos:", StringComparison.OrdinalIgnoreCase))
        {
            return new Resolved(Kind.Url, value);
        }

        if (TryKnown(value, out var mapped))
        {
            return mapped.StartsWith("ms-", StringComparison.OrdinalIgnoreCase)
                ? new Resolved(Kind.Url, mapped)
                : new Resolved(Kind.App, mapped);
        }

        if (WebIntent.TrySite(value, out var siteUrl, out _))
        {
            return new Resolved(Kind.Url, siteUrl);
        }

        if (LooksLikeHost(value))
        {
            return new Resolved(Kind.Url, "https://" + value);
        }

        if (value.Contains('\\') || value.Contains('/') || File.Exists(value) || Directory.Exists(value))
        {
            return new Resolved(Kind.Path, value);
        }

        return new Resolved(Kind.App, value);
    }

    public static bool TryKnown(string name, out string mapped)
    {
        var key = Collapse(name);
        return Known.TryGetValue(key, out mapped!);
    }

    private static string Collapse(string name) =>
        string.Join(' ', name.Trim().Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries));

    private static bool LooksLikeHost(string value)
    {
        if (value.Contains(' ') || value.Contains('\\') || value.Contains('/'))
        {
            return false;
        }

        if (!value.Contains('.'))
        {
            return false;
        }

        if (value.EndsWith(".exe", StringComparison.OrdinalIgnoreCase)
            || value.EndsWith(".lnk", StringComparison.OrdinalIgnoreCase)
            || value.EndsWith(".bat", StringComparison.OrdinalIgnoreCase)
            || value.EndsWith(".cmd", StringComparison.OrdinalIgnoreCase)
            || value.EndsWith(".msi", StringComparison.OrdinalIgnoreCase))
        {
            return false;
        }

        return Uri.CheckHostName(value) != UriHostNameType.Unknown
            || value.Contains(".com", StringComparison.OrdinalIgnoreCase)
            || value.Contains(".org", StringComparison.OrdinalIgnoreCase)
            || value.Contains(".net", StringComparison.OrdinalIgnoreCase)
            || value.Contains(".io", StringComparison.OrdinalIgnoreCase);
    }
}

public static class ModelPicker
{
    private static readonly string[] Prefer =
        ["llama3.1", "llama3", "qwen2.5", "qwen", "mistral", "phi4", "phi3", "phi", "gemma", "deepseek", "command", "llama"];

    public static string? PickGenerate(IEnumerable<string> models)
    {
        var list = models.Where(m => !string.IsNullOrWhiteSpace(m)).Select(m => m.Trim()).ToList();
        if (list.Count == 0)
        {
            return null;
        }

        var chat = list.Where(m => !IsNonChat(m)).ToList();
        var pool = chat.Count > 0 ? chat : list;
        foreach (var hint in Prefer)
        {
            var hit = pool.FirstOrDefault(m => m.Contains(hint, StringComparison.OrdinalIgnoreCase));
            if (hit is not null)
            {
                return hit;
            }
        }

        return pool[0];
    }

    public static bool IsNonChat(string name)
    {
        var n = name.ToLowerInvariant();
        return n.Contains("embed")
            || n.Contains("nomic")
            || n.Contains("minilm")
            || n.Contains("bge-")
            || n.Contains("e5-")
            || n.Contains("mxbai")
            || n.Contains("clip")
            || n.Contains("whisper")
            || n.Contains("rerank")
            || n.Contains("llava");
    }
}

public static class FileSearchPattern
{
    public static string Glob(string query)
    {
        var cleaned = (query ?? "").Trim().Trim('*');
        if (cleaned.Length == 0)
        {
            return "*";
        }

        var chars = cleaned.Select(c => c is '*' or '?' or '[' or ']' ? '_' : c).ToArray();
        var tokens = new string(chars).Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries);
        if (tokens.Length == 0)
        {
            return "*";
        }

        return "*" + string.Join("*", tokens) + "*";
    }
}

public sealed record AssistPlan(string Tool, Dictionary<string, string> Args, string? Reply)
{
    public string Arg(string key) => Args.TryGetValue(key, out var v) ? v : "";
}

public static class AssistPlanner
{
    public static bool NeedsConfirm(string tool, IReadOnlyDictionary<string, string> args)
    {
        if (tool is "shell" or "type_text")
        {
            return true;
        }

        if (tool == "browse")
        {
            var action = args.TryGetValue("action", out var browseAction)
                ? browseAction.Trim().ToLowerInvariant()
                : "";
            var then = args.TryGetValue("then_action", out var thenAction)
                ? thenAction.Trim().ToLowerInvariant()
                : "";
            var target = (args.TryGetValue("target", out var t) ? t : "")
                + " "
                + (args.TryGetValue("then_target", out var tt) ? tt : "")
                + " "
                + (args.TryGetValue("text", out var text) ? text : "")
                + " "
                + (args.TryGetValue("url", out var url) ? url : "");
            if (action is "click" or "type" or "fill" || then is "click" or "type" or "fill")
            {
                return WebIntent.LooksDestructive(target) || WebIntent.LooksSecretField(target);
            }

            return false;
        }

        if (tool != "power")
        {
            return false;
        }

        var power = args.TryGetValue("action", out var a) ? a.Trim().ToLowerInvariant() : "";
        return power is "shutdown" or "restart" or "sleep";
    }

    public static AssistPlan? Parse(string? raw)
    {
        if (string.IsNullOrWhiteSpace(raw))
        {
            return null;
        }

        var start = raw.IndexOf('{');
        var end = raw.LastIndexOf('}');
        var json = start >= 0 && end > start ? raw[start..(end + 1)] : raw.Trim();
        try
        {
            using var doc = JsonDocument.Parse(json);
            var root = doc.RootElement;
            var tool = root.TryGetProperty("tool", out var t) && t.ValueKind == JsonValueKind.String
                ? t.GetString() ?? ""
                : "";
            if (!string.IsNullOrWhiteSpace(tool))
            {
                var args = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
                foreach (var p in root.EnumerateObject())
                {
                    if (p.NameEquals("tool") || p.NameEquals("reply"))
                    {
                        continue;
                    }

                    args[p.Name] = p.Value.ValueKind == JsonValueKind.String
                        ? p.Value.GetString() ?? ""
                        : p.Value.ToString();
                }

                return new AssistPlan(tool.Trim(), args, null);
            }

            if (root.TryGetProperty("reply", out var reply) && reply.ValueKind == JsonValueKind.String)
            {
                var text = reply.GetString();
                if (!string.IsNullOrWhiteSpace(text))
                {
                    return new AssistPlan("", new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase), text);
                }
            }

            return null;
        }
        catch
        {
            return null;
        }
    }
}

public sealed record FileHuntResult(IReadOnlyList<string> Hits, bool TimedOut);

public static class FileHunt
{
    public static FileHuntResult Search(
        IEnumerable<string> roots,
        string query,
        TimeSpan limit,
        int maxHits,
        CancellationToken cancellationToken = default)
    {
        var hits = new List<string>();
        var glob = FileSearchPattern.Glob(query);
        var options = new EnumerationOptions
        {
            RecurseSubdirectories = true,
            IgnoreInaccessible = true,
            MaxRecursionDepth = 6,
            ReturnSpecialDirectories = false,
            AttributesToSkip = FileAttributes.ReparsePoint | FileAttributes.System,
            MatchCasing = MatchCasing.CaseInsensitive,
        };
        var clock = Stopwatch.StartNew();
        var timedOut = false;

        foreach (var root in roots.Where(Directory.Exists).Distinct(StringComparer.OrdinalIgnoreCase))
        {
            try
            {
                foreach (var file in Directory.EnumerateFiles(root, glob, options))
                {
                    if (cancellationToken.IsCancellationRequested || clock.Elapsed > limit)
                    {
                        timedOut = true;
                        break;
                    }

                    hits.Add(file);
                    if (hits.Count >= maxHits)
                    {
                        break;
                    }
                }
            }
            catch
            {
                // Skip roots this process cannot open.
            }

            if (hits.Count >= maxHits || timedOut)
            {
                break;
            }
        }

        return new FileHuntResult(hits, timedOut);
    }
}

public static class StartMenuHunt
{
    public static string? FindShortcut(string query, TimeSpan budget, IEnumerable<string>? roots = null)
    {
        var tokens = (query ?? "")
            .Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries)
            .Select(t => t.Trim().Trim('"'))
            .Where(t => t.Length > 0)
            .ToArray();
        if (tokens.Length == 0)
        {
            return null;
        }

        var searchRoots = (roots ?? DefaultRoots()).Where(Directory.Exists).ToArray();
        if (searchRoots.Length == 0)
        {
            return null;
        }

        var options = new EnumerationOptions
        {
            RecurseSubdirectories = true,
            IgnoreInaccessible = true,
            MaxRecursionDepth = 5,
            ReturnSpecialDirectories = false,
            AttributesToSkip = FileAttributes.ReparsePoint,
            MatchCasing = MatchCasing.CaseInsensitive,
        };
        var clock = Stopwatch.StartNew();
        string? fallback = null;
        foreach (var root in searchRoots)
        {
            try
            {
                foreach (var lnk in Directory.EnumerateFiles(root, "*.lnk", options))
                {
                    if (clock.Elapsed > budget)
                    {
                        return fallback;
                    }

                    var name = Path.GetFileNameWithoutExtension(lnk);
                    if (tokens.All(t => name.Contains(t, StringComparison.OrdinalIgnoreCase)))
                    {
                        if (tokens.Length == 1 || name.StartsWith(tokens[0], StringComparison.OrdinalIgnoreCase))
                        {
                            return lnk;
                        }

                        fallback ??= lnk;
                    }
                }
            }
            catch
            {
                // Skip locked start-menu folders.
            }
        }

        return fallback;
    }

    private static IEnumerable<string> DefaultRoots()
    {
        yield return Environment.GetFolderPath(Environment.SpecialFolder.StartMenu);
        yield return Environment.GetFolderPath(Environment.SpecialFolder.CommonStartMenu);
        var programs = Environment.GetFolderPath(Environment.SpecialFolder.Programs);
        if (!string.IsNullOrWhiteSpace(programs))
        {
            yield return programs;
        }
    }
}
