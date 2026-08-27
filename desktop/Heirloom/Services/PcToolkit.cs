using System.Diagnostics;
using System.Net.Http;
using System.Text;
using System.Text.RegularExpressions;

namespace Heirloom.Services;

public sealed record ToolResult(bool Ok, string Detail);

public sealed class PcToolkit : IDisposable
{
    private static readonly HttpClient Web = new() { Timeout = TimeSpan.FromSeconds(12) };
    private readonly SettingsStore _settings;
    private readonly MixerSessionService _mixer;
    private readonly ScreenCaptureService _screen;
    private readonly VaultService _vault;
    private readonly OllamaService _ollama;
    private readonly WhisperService _whisper;
    private readonly BrowserSession _browser = new();

    public PcToolkit(
        SettingsStore settings,
        MixerSessionService mixer,
        ScreenCaptureService screen,
        VaultService vault,
        OllamaService ollama,
        WhisperService whisper)
    {
        _settings = settings;
        _mixer = mixer;
        _screen = screen;
        _vault = vault;
        _ollama = ollama;
        _whisper = whisper;
    }

    public bool AllowPc => _settings.Current.AllowPcControl
        && !string.Equals(_settings.Current.AppMode, "heir", StringComparison.OrdinalIgnoreCase);
    public bool AllowSee => _settings.Current.AllowSeeScreen
        && !string.Equals(_settings.Current.AppMode, "heir", StringComparison.OrdinalIgnoreCase);

    public bool AllowVaultWrite =>
        !string.Equals(_settings.Current.AppMode, "heir", StringComparison.OrdinalIgnoreCase);

    public static bool NeedsConfirm(string tool, IReadOnlyDictionary<string, string> args) =>
        AssistPlanner.NeedsConfirm(tool, args);

    public async Task<ToolResult> RunAsync(string tool, IReadOnlyDictionary<string, string> args, CancellationToken cancellationToken)
    {
        var a = (string key) => args.TryGetValue(key, out var v) ? v : "";
        try
        {
            return tool switch
            {
                "open_url" => Open(a("url").Length > 0 ? a("url") : a("target")),
                "open_app" => await Task.Run(() => Open(a("name").Length > 0 ? a("name") : a("target")), cancellationToken).ConfigureAwait(false),
                "set_volume" => SetVolume(a("level")),
                "media" => Media(a("action")),
                "clipboard_get" => await ClipboardGetAsync().ConfigureAwait(false),
                "clipboard_set" => ClipboardSet(a("text")),
                "type_text" => Type(a("text")),
                "find_file" => await Task.Run(() => FindFiles(a("query").Length > 0 ? a("query") : a("name"), cancellationToken), cancellationToken).ConfigureAwait(false),
                "list_dir" => await Task.Run(() => ListDir(a("path")), cancellationToken).ConfigureAwait(false),
                "read_file" => await Task.Run(() => ReadFile(a("path")), cancellationToken).ConfigureAwait(false),
                "write_note" => WriteNote(a("text")),
                "search_vault" => SearchVault(a("query")),
                "shell" => await ShellAsync(a("command"), cancellationToken).ConfigureAwait(false),
                "power" => Power(a("action")),
                "screenshot" => await SeeScreenAsync(cancellationToken).ConfigureAwait(false),
                "system_status" => await Task.Run(SystemStatus, cancellationToken).ConfigureAwait(false),
                "windows" => await Task.Run(Windows, cancellationToken).ConfigureAwait(false),
                "fetch_url" => await FetchAsync(a("url"), cancellationToken).ConfigureAwait(false),
                "run_skill" => await SkillAsync(a("name"), cancellationToken).ConfigureAwait(false),
                "browse" => await BrowseAsync(args, cancellationToken).ConfigureAwait(false),
                _ => new ToolResult(false, "Unknown tool " + tool),
            };
        }
        catch (OperationCanceledException)
        {
            return new ToolResult(false, "Stopped.");
        }
        catch (Exception ex)
        {
            return new ToolResult(false, ex.Message);
        }
    }

    public ToolResult Open(string target)
    {
        if (!AllowPc)
        {
            return new ToolResult(false, "Use this PC is off. Turn it on in Abilities.");
        }

        if (string.IsNullOrWhiteSpace(target))
        {
            return new ToolResult(false, "Nothing to open.");
        }

        var resolved = LaunchTarget.Resolve(target);
        if (string.IsNullOrWhiteSpace(resolved.Value))
        {
            return new ToolResult(false, "Nothing to open.");
        }

        try
        {
            Process.Start(new ProcessStartInfo(resolved.Value) { UseShellExecute = true });
            return new ToolResult(true, OpenedLine(target, resolved));
        }
        catch (Exception ex)
        {
            FaultLog.Write("open", resolved.Value + " · " + ex.Message);
        }

        if (resolved.Kind != LaunchTarget.Kind.Url)
        {
            var lnk = StartMenuHunt.FindShortcut(target, TimeSpan.FromSeconds(2));
            if (!string.IsNullOrWhiteSpace(lnk))
            {
                try
                {
                    Process.Start(new ProcessStartInfo(lnk) { UseShellExecute = true });
                    return new ToolResult(true, "Opened " + Path.GetFileNameWithoutExtension(lnk) + " from the Start menu.");
                }
                catch (Exception ex)
                {
                    FaultLog.Write("open-lnk", lnk + " · " + ex.Message);
                }
            }
        }

        return new ToolResult(false, resolved.Kind == LaunchTarget.Kind.Url
            ? WebIntent.FailOpenLine(WebIntent.TrySite(target, out _, out var failLabel) ? failLabel : "that site")
            : "Could not open " + resolved.Value + ". Name an installed app, a path, or a URL.");
    }

    public ToolResult SetVolume(string level)
    {
        if (!int.TryParse(Regex.Replace(level ?? "", @"[^\d]", ""), out var vol))
        {
            return new ToolResult(false, "Need a volume 0–100.");
        }

        vol = Math.Clamp(vol, 0, 100);
        _mixer.SessionVolume = vol;
        return new ToolResult(true, $"Heirloom session volume {vol}%.");
    }

    public ToolResult Media(string action)
    {
        if (!AllowPc)
        {
            return new ToolResult(false, "Use this PC is off.");
        }

        NativeMethods.MediaKey(string.IsNullOrWhiteSpace(action) ? "playpause" : action.Trim().ToLowerInvariant());
        return new ToolResult(true, "Media " + action);
    }

    public async Task<ToolResult> ClipboardGetAsync()
    {
        if (!AllowPc)
        {
            return new ToolResult(false, "Use this PC is off.");
        }

        var text = await ClipboardService.GetTextAsync().ConfigureAwait(false);
        return string.IsNullOrWhiteSpace(text)
            ? new ToolResult(true, "Clipboard is empty.")
            : new ToolResult(true, text.Length > 2000 ? text[..2000] + "…" : text);
    }

    public ToolResult ClipboardSet(string text)
    {
        if (!AllowPc)
        {
            return new ToolResult(false, "Use this PC is off.");
        }

        ClipboardService.CopyText(text ?? "");
        return new ToolResult(true, "Copied " + (text ?? "").Length + " characters.");
    }

    public ToolResult Type(string text)
    {
        if (!AllowPc)
        {
            return new ToolResult(false, "Use this PC is off.");
        }

        if (string.IsNullOrEmpty(text))
        {
            return new ToolResult(false, "Nothing to type.");
        }

        NativeMethods.TypeText(text);
        return new ToolResult(true, "Typed " + text.Length + " characters into the foreground window (" + NativeMethods.ForegroundTitle() + ").");
    }

    public ToolResult FindFiles(string query, CancellationToken cancellationToken = default)
    {
        if (string.IsNullOrWhiteSpace(query))
        {
            return new ToolResult(false, "Need a file name or fragment.");
        }

        var roots = new List<string> { _vault.RootPath };
        if (AllowPc)
        {
            roots.Add(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory));
            roots.Add(Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments));
            roots.Add(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "Downloads"));
        }

        var globHits = FileHunt.Search(roots, query, TimeSpan.FromSeconds(5), 20, cancellationToken);
        if (globHits.Hits.Count == 0)
        {
            return new ToolResult(true, AllowPc
                ? (globHits.TimedOut
                    ? "Search stopped after 5 seconds with no match in Desktop, Documents, Downloads, or the vault."
                    : "No files matched in Desktop, Documents, Downloads, or the vault.")
                : "No files matched in the vault. Profile search is off (Heir mode or Use this PC).");
        }

        var body = string.Join("\n", globHits.Hits);
        if (globHits.TimedOut)
        {
            body += "\n(Stopped after 5 seconds so the studio stays responsive.)";
        }

        return new ToolResult(true, body);
    }

    public ToolResult ListDir(string path)
    {
        var dir = string.IsNullOrWhiteSpace(path) ? _vault.RootPath : path.Trim().Trim('"');
        if (!Directory.Exists(dir))
        {
            return new ToolResult(false, "Folder not found: " + dir);
        }

        if (!IsSafePath(dir))
        {
            return new ToolResult(false, DenyPath(dir));
        }

        var names = Directory.EnumerateFileSystemEntries(dir).Take(40).Select(Path.GetFileName);
        return new ToolResult(true, dir + "\n" + string.Join("\n", names));
    }

    public ToolResult ReadFile(string path)
    {
        var full = string.IsNullOrWhiteSpace(path) ? "" : Path.GetFullPath(path.Trim().Trim('"'));
        if (!File.Exists(full))
        {
            return new ToolResult(false, "File not found.");
        }

        if (!IsSafePath(full))
        {
            return new ToolResult(false, DenyPath(full));
        }

        var info = new FileInfo(full);
        if (info.Length > 120_000)
        {
            return new ToolResult(false, "File is " + info.Length + " bytes. Ask for a smaller file.");
        }

        var text = File.ReadAllText(full);
        return new ToolResult(true, text.Length > 6000 ? text[..6000] + "\n…" : text);
    }

    public ToolResult WriteNote(string text)
    {
        if (!AllowVaultWrite)
        {
            return new ToolResult(false, "Heir mode. The vault is locked.");
        }

        if (string.IsNullOrWhiteSpace(text))
        {
            return new ToolResult(false, "Nothing to file.");
        }

        _vault.AddCapture("note", text.Trim(), "assistant");
        return new ToolResult(true, "Filed a note in the vault.");
    }

    public ToolResult SearchVault(string query)
    {
        if (string.IsNullOrWhiteSpace(query))
        {
            return new ToolResult(false, "Need a search.");
        }

        var rows = _vault.Search(query, null, 8);
        if (rows.Count == 0)
        {
            return new ToolResult(true, "Vault had no match for " + query + ".");
        }

        var body = string.Join("\n", rows.Select(r => $"[{r.Kind}] {Trim(r.Text, 240)}"));
        return new ToolResult(true, body);
    }

    public async Task<ToolResult> ShellAsync(string command, CancellationToken cancellationToken)
    {
        if (!AllowPc)
        {
            return new ToolResult(false, "Use this PC is off.");
        }

        if (string.IsNullOrWhiteSpace(command))
        {
            return new ToolResult(false, "No command.");
        }

        var start = new ProcessStartInfo("cmd.exe", "/d /c " + command)
        {
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };
        using var process = Process.Start(start);
        if (process is null)
        {
            return new ToolResult(false, "Could not start the shell.");
        }

        var stdout = process.StandardOutput.ReadToEndAsync(cancellationToken);
        var stderr = process.StandardError.ReadToEndAsync(cancellationToken);
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        timeout.CancelAfter(TimeSpan.FromSeconds(20));
        try
        {
            await process.WaitForExitAsync(timeout.Token).ConfigureAwait(false);
        }
        catch (OperationCanceledException)
        {
            TryKill(process);
            return new ToolResult(false, "Command ran longer than 20 seconds and was stopped.");
        }

        var text = ((await stdout.ConfigureAwait(false) + "\n" + await stderr.ConfigureAwait(false)).Trim());
        if (text.Length > 4000)
        {
            text = text[..4000] + "…";
        }

        return new ToolResult(process.ExitCode == 0, string.IsNullOrWhiteSpace(text) ? "exit " + process.ExitCode : text);
    }

    public ToolResult Power(string action)
    {
        if (!AllowPc)
        {
            return new ToolResult(false, "Use this PC is off.");
        }

        return action.Trim().ToLowerInvariant() switch
        {
            "lock" => new ToolResult(NativeMethods.LockWorkStation(), "Locked the workstation."),
            "sleep" => Run("rundll32.exe", "powrprof.dll,SetSuspendState 0,1,0", "Sleeping."),
            "shutdown" => Run("shutdown", "/s /t 8", "Shutdown in 8 seconds. Open a command prompt and run shutdown /a to abort."),
            "restart" => Run("shutdown", "/r /t 8", "Restart in 8 seconds. Run shutdown /a to abort."),
            _ => new ToolResult(false, "Power action must be lock, sleep, shutdown, or restart."),
        };
    }

    public async Task<ToolResult> SeeScreenAsync(CancellationToken cancellationToken)
    {
        if (!AllowSee)
        {
            return new ToolResult(false, "See the screen is off. Turn it on in Abilities.");
        }

        var jpeg = _screen.CaptureJpeg(1280, 60);
        if (jpeg.Length == 0)
        {
            return new ToolResult(false, "Screen capture failed.");
        }

        var windows = FormatWindows();
        await _ollama.ProbeAsync(cancellationToken).ConfigureAwait(false);
        var vision = _ollama.Models.FirstOrDefault(m =>
            m.Contains("llava", StringComparison.OrdinalIgnoreCase)
            || m.Contains("vision", StringComparison.OrdinalIgnoreCase)
            || m.Contains("moondream", StringComparison.OrdinalIgnoreCase)
            || m.Contains("minicpm-v", StringComparison.OrdinalIgnoreCase)
            || m.Contains("qwen2.5vl", StringComparison.OrdinalIgnoreCase)
            || m.Contains("gemma3", StringComparison.OrdinalIgnoreCase));
        if (!string.IsNullOrWhiteSpace(vision))
        {
            var described = await _ollama.CompleteVisionAsync(
                vision,
                "Describe this Windows desktop for an assistant that must act. Name the active app, readable text, and what a human is looking at. Be literal.",
                jpeg,
                cancellationToken).ConfigureAwait(false);
            if (!string.IsNullOrWhiteSpace(described))
            {
                return new ToolResult(true, described.Trim() + "\n\nWindows:\n" + windows);
            }
        }

        return new ToolResult(true, "Captured the screen (" + jpeg.Length / 1024 + " KB). No vision model is installed, so here are the window titles:\n" + windows);
    }

    public ToolResult SystemStatus()
    {
        var drive = DriveInfo.GetDrives().FirstOrDefault(d => d.IsReady && d.Name.StartsWith("C", StringComparison.OrdinalIgnoreCase));
        var f = DriveInfo.GetDrives().FirstOrDefault(d => d.IsReady && d.Name.StartsWith("F", StringComparison.OrdinalIgnoreCase));
        var bits = new List<string>
        {
            Environment.MachineName,
            Environment.OSVersion.ToString(),
            Environment.ProcessorCount + " logical processors",
            "working set " + (Environment.WorkingSet / (1024 * 1024)) + " MB",
            _whisper.Status,
            _ollama.Status,
            "Heirloom session " + _mixer.SessionVolume + "%",
        };
        if (drive is not null)
        {
            bits.Add($"C: {drive.AvailableFreeSpace / (1024 * 1024 * 1024)} GB free");
        }

        if (f is not null)
        {
            bits.Add($"F: {f.AvailableFreeSpace / (1024 * 1024 * 1024)} GB free");
        }

        var gpu = ProbeGpu();
        if (!string.IsNullOrWhiteSpace(gpu))
        {
            bits.Add("GPU " + gpu);
        }

        return new ToolResult(true, string.Join(" · ", bits));
    }

    public static string? ProbeGpu()
    {
        try
        {
            using var smi = Process.Start(new ProcessStartInfo("nvidia-smi.exe", "--query-gpu=name,memory.used,memory.total,utilization.gpu --format=csv,noheader")
            {
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
            });
            if (smi is null)
            {
                return null;
            }

            if (!smi.WaitForExit(2000))
            {
                TryKill(smi);
                return null;
            }

            var line = smi.StandardOutput.ReadToEnd().Trim();
            if (string.IsNullOrWhiteSpace(line))
            {
                return null;
            }

            var first = line.Split(['\r', '\n'], StringSplitOptions.RemoveEmptyEntries)[0].Trim();
            return first.Length > 180 ? first[..180] : first;
        }
        catch
        {
            return null;
        }
    }

    public ToolResult Windows()
    {
        if (!AllowPc)
        {
            return new ToolResult(false, "Use this PC is off.");
        }

        var text = FormatWindows();
        return new ToolResult(true, text);
    }

    private static string FormatWindows()
    {
        var rows = NativeMethods.VisibleWindows();
        if (rows.Count == 0)
        {
            return "No visible windows.";
        }

        return string.Join("\n", rows.Select(r =>
            (string.IsNullOrWhiteSpace(r.Process) ? "" : r.Process + " — ") + r.Title));
    }

    public async Task<ToolResult> BrowseAsync(IReadOnlyDictionary<string, string> args, CancellationToken cancellationToken)
    {
        if (!AllowPc)
        {
            return new ToolResult(false, "Use this PC is off. Turn it on in Abilities.");
        }

        var action = (args.TryGetValue("action", out var rawAction) ? rawAction : "").Trim().ToLowerInvariant();
        var url = FirstArg(args, "url", "href");
        var query = FirstArg(args, "query", "q");
        var target = FirstArg(args, "target", "name", "selector");
        var text = FirstArg(args, "text", "value", "then_text");
        var amount = FirstArg(args, "amount", "delta");
        var label = FirstArg(args, "label");
        var thenAction = FirstArg(args, "then_action", "follow");
        var thenTarget = FirstArg(args, "then_target");
        var thenText = FirstArg(args, "then_text");
        if (thenText.Length == 0)
        {
            thenText = text;
        }

        if (action.Length == 0)
        {
            action = query.Length > 0 ? "search" : "open";
        }

        if (action is "open" or "search" or "launch")
        {
            if (query.Length > 0 && (url.Length == 0 || action == "search"))
            {
                var engine = FirstArg(args, "engine");
                if (engine.Length == 0)
                {
                    engine = "google";
                }

                var intent = WebIntent.TryParse("search " + query + " on " + engine, out var parsed)
                    ? parsed
                    : null;
                url = intent?.Url ?? ("https://www.google.com/search?q=" + Uri.EscapeDataString(query));
                if (string.IsNullOrWhiteSpace(label))
                {
                    label = intent?.Label ?? "Google";
                }
            }

            if (url.Length == 0)
            {
                url = target;
            }

            if (url.Length == 0)
            {
                return new ToolResult(false, "Need a site, a search, or a web address.");
            }

            if (thenAction.Length > 0)
            {
                var driven = await DriveThenAsync(url, thenAction, thenTarget, thenText, amount, cancellationToken).ConfigureAwait(false);
                if (driven.Ok)
                {
                    return new ToolResult(true, string.IsNullOrWhiteSpace(label)
                        ? driven.Detail
                        : WebIntent.DoneOpenLine(label).TrimEnd('.') + " " + driven.Detail);
                }

                var fallback = Open(url);
                if (fallback.Ok)
                {
                    return new ToolResult(false, WebIntent.DoneOpenLine(string.IsNullOrWhiteSpace(label) ? HostHint(url) : label).TrimEnd('.')
                        + " I could not click or type on that page from here. " + driven.Detail);
                }

                return FailBrowse(action, label, query, driven.Detail);
            }

            var opened = Open(url);
            if (!opened.Ok)
            {
                return FailBrowse(action, label, query, opened.Detail);
            }

            if (action == "search" && query.Length > 0)
            {
                return new ToolResult(true, WebIntent.DoneSearchLine(string.IsNullOrWhiteSpace(label) ? "Google" : label, query));
            }

            return new ToolResult(true, WebIntent.DoneOpenLine(string.IsNullOrWhiteSpace(label) ? HostHint(url) : label));
        }

        if (action is "goto" or "navigate" or "newtab" or "new_tab")
        {
            if (url.Length == 0)
            {
                url = target;
            }

            var driven = await _browser.RunAsync(action is "newtab" or "new_tab" ? "newtab" : "goto", url, "", "", "", cancellationToken).ConfigureAwait(false);
            if (driven.Ok)
            {
                return new ToolResult(true, WebIntent.DoneOpenLine(string.IsNullOrWhiteSpace(label) ? HostHint(url) : label));
            }

            var fallback = Open(url);
            if (fallback.Ok)
            {
                return new ToolResult(true, WebIntent.DoneOpenLine(string.IsNullOrWhiteSpace(label) ? HostHint(url) : label)
                    + " (Your usual browser. In-page clicks need a Heirloom window.)");
            }

            return FailBrowse("open", label, query, driven.Detail);
        }

        return await _browser.RunAsync(action, url, target.Length > 0 ? target : thenTarget, thenText.Length > 0 ? thenText : text, amount, cancellationToken).ConfigureAwait(false);
    }

    private async Task<ToolResult> DriveThenAsync(
        string url,
        string thenAction,
        string thenTarget,
        string thenText,
        string amount,
        CancellationToken cancellationToken)
    {
        var arrived = await _browser.RunAsync("goto", url, "", "", "", cancellationToken).ConfigureAwait(false);
        if (!arrived.Ok)
        {
            return arrived;
        }

        return thenAction.Trim().ToLowerInvariant() switch
        {
            "click" or "tap" => await _browser.RunAsync("click", url, thenTarget, "", "", cancellationToken).ConfigureAwait(false),
            "type" or "fill" => await _browser.RunAsync("type", url, thenTarget, thenText, "", cancellationToken).ConfigureAwait(false),
            "scroll" => await _browser.RunAsync("scroll", url, "", "", thenTarget.Length > 0 ? thenTarget : amount, cancellationToken).ConfigureAwait(false),
            _ => arrived,
        };
    }

    private static ToolResult FailBrowse(string action, string label, string query, string detail)
    {
        if (detail.Contains("Use this PC is off", StringComparison.OrdinalIgnoreCase))
        {
            return new ToolResult(false, detail);
        }

        if (action == "search" && query.Length > 0)
        {
            return new ToolResult(false, WebIntent.FailSearchLine(string.IsNullOrWhiteSpace(label) ? "Google" : label, query));
        }

        if (!string.IsNullOrWhiteSpace(label) && !label.StartsWith("http", StringComparison.OrdinalIgnoreCase))
        {
            return new ToolResult(false, WebIntent.FailOpenLine(label));
        }

        return new ToolResult(false, string.IsNullOrWhiteSpace(detail)
            ? "Could not open the browser. Check that this computer allows Heirloom to start one."
            : detail);
    }

    private static string HostHint(string url)
    {
        try
        {
            var host = new Uri(url).Host;
            return host.StartsWith("www.", StringComparison.OrdinalIgnoreCase) ? host[4..] : host;
        }
        catch
        {
            return "the page";
        }
    }

    public void Dispose() => _browser.Dispose();

    private static string FirstArg(IReadOnlyDictionary<string, string> args, params string[] keys)
    {
        foreach (var key in keys)
        {
            if (args.TryGetValue(key, out var value) && !string.IsNullOrWhiteSpace(value))
            {
                return value.Trim();
            }
        }

        return "";
    }

    private static string OpenedLine(string requested, LaunchTarget.Resolved resolved)
    {
        if (resolved.Kind == LaunchTarget.Kind.Url)
        {
            if (WebIntent.TrySite(requested, out _, out var site))
            {
                return WebIntent.DoneOpenLine(site);
            }

            return WebIntent.DoneOpenLine(resolved.Value);
        }

        return "Opened " + resolved.Value;
    }

    public async Task<ToolResult> FetchAsync(string url, CancellationToken cancellationToken)
    {
        if (string.IsNullOrWhiteSpace(url) || !Uri.TryCreate(url, UriKind.Absolute, out var uri) || uri.Scheme is not ("http" or "https"))
        {
            return new ToolResult(false, "Need an http(s) URL.");
        }

        using var response = await Web.GetAsync(uri, cancellationToken).ConfigureAwait(false);
        var raw = await response.Content.ReadAsStringAsync(cancellationToken).ConfigureAwait(false);
        var text = Regex.Replace(raw, "<script[\\s\\S]*?</script>", " ", RegexOptions.IgnoreCase);
        text = Regex.Replace(text, "<style[\\s\\S]*?</style>", " ", RegexOptions.IgnoreCase);
        text = Regex.Replace(text, "<[^>]+>", " ");
        text = Regex.Replace(text, "\\s+", " ").Trim();
        if (text.Length > 4000)
        {
            text = text[..4000] + "…";
        }

        return new ToolResult(response.IsSuccessStatusCode, $"HTTP {(int)response.StatusCode} {uri}\n" + text);
    }

    public async Task<ToolResult> SkillAsync(string name, CancellationToken cancellationToken)
    {
        if (!AllowVaultWrite)
        {
            return new ToolResult(false, "Heir mode. Skills stay off.");
        }

        var skill = _vault.Skills().FirstOrDefault(s =>
            s.Enabled && (
                s.Name.Contains(name, StringComparison.OrdinalIgnoreCase)
                || name.Contains(s.Name, StringComparison.OrdinalIgnoreCase)
                || s.Triggers.Contains(name, StringComparison.OrdinalIgnoreCase)));
        if (skill.Id == 0 || string.IsNullOrWhiteSpace(skill.Url))
        {
            return new ToolResult(false, "No skill matched " + name + ".");
        }

        try
        {
            using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(15) };
            using var response = await client.PostAsync(skill.Url, new StringContent("{}", Encoding.UTF8, "application/json"), cancellationToken).ConfigureAwait(false);
            return new ToolResult(response.IsSuccessStatusCode, "Skill " + skill.Name + " HTTP " + (int)response.StatusCode);
        }
        catch (Exception ex)
        {
            return new ToolResult(false, ex.Message);
        }
    }

    private bool IsSafePath(string path)
    {
        var full = Path.GetFullPath(path);
        if (PathGuard.IsUnder(full, _vault.RootPath))
        {
            return true;
        }

        if (!AllowPc)
        {
            return false;
        }

        var home = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
        return PathGuard.IsUnder(full, home);
    }

    private string DenyPath(string path) =>
        AllowPc
            ? "That path is outside the vault and your user profile."
            : "That path is outside the vault. Profile files need Use this PC in Abilities.";

    private static ToolResult Run(string file, string args, string ok)
    {
        Process.Start(new ProcessStartInfo(file, args) { UseShellExecute = false, CreateNoWindow = true });
        return new ToolResult(true, ok);
    }

    private static void TryKill(Process process)
    {
        try
        {
            if (!process.HasExited)
            {
                process.Kill(entireProcessTree: true);
            }
        }
        catch
        {
            // Best-effort.
        }
    }

    private static string Trim(string text, int max) =>
        string.IsNullOrEmpty(text) ? "" : text.Length <= max ? text : text[..max] + "…";
}
