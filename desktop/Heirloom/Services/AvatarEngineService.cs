using System.Diagnostics;
using System.Text;
using System.Text.Json;

namespace Heirloom.Services;

public sealed record AvatarEngineProbe(
    bool Ready,
    string Engine,
    string Line,
    string ComfyLine,
    string Root);

public sealed record AvatarVisualCheck(bool Ok, string Line, int Width, int Height, int Faces);

public sealed class AvatarEngineService
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNameCaseInsensitive = true,
    };

    private readonly SettingsStore _settings;
    private readonly SpeakService _speak;

    public AvatarEngineService(SettingsStore settings, SpeakService speak)
    {
        _settings = settings;
        _speak = speak;
    }

    public string EngineRoot
    {
        get
        {
            var configured = _settings.Current.AvatarEngineRoot?.Trim();
            if (!string.IsNullOrWhiteSpace(configured))
            {
                return configured;
            }

            return AppPaths.AvatarEngineRoot;
        }
    }

    public string ScriptPath
    {
        get
        {
            var bundled = Path.Combine(AppContext.BaseDirectory, "tools", "avatar_engine", "lipsync.py");
            if (File.Exists(bundled))
            {
                return bundled;
            }

            return Path.Combine(AppContext.BaseDirectory, "lipsync.py");
        }
    }

    public AvatarEngineProbe Probe()
    {
        var root = EngineRoot;
        var unet = Path.Combine(root, "LatentSync", "checkpoints", "latentsync_unet.pt");
        var whisper = Path.Combine(root, "LatentSync", "checkpoints", "whisper", "tiny.pt");
        var venv = Path.Combine(root, ".venv", "Scripts", "python.exe");
        var ready = File.Exists(unet) && File.Exists(whisper) && File.Exists(venv);
        if (ready && string.IsNullOrWhiteSpace(_settings.Current.AvatarEngineRoot))
        {
            _settings.Current.AvatarEngineRoot = root;
            _settings.Save();
        }

        var engine = ready ? "LatentSync 1.6 on this PC" : "LatentSync 1.6 not installed yet";
        var line = ready
            ? "Engine ready. File a face-on original of you alone, write a line, Make live version."
            : "The likeness engine is not on this PC yet. Fetch engine once (about 8–12 GB on F:\\HeirloomModels). RTX-class GPU required.";
        var comfy = string.IsNullOrWhiteSpace(_settings.Current.ComfyUrl)
            ? "ComfyUI URL not set."
            : "ComfyUI optional at " + _settings.Current.ComfyUrl.Trim() + " when you start it.";
        return new AvatarEngineProbe(ready, engine, line, comfy, root);
    }

    public async Task<AvatarEngineProbe> EnsureAsync(IProgress<string>? progress, CancellationToken cancellationToken)
    {
        progress?.Report("Installing LatentSync 1.6 onto this PC…");
        var result = await RunScriptAsync(["--ensure"], TimeSpan.FromHours(3), progress, cancellationToken).ConfigureAwait(false);
        if (!result.Ok)
        {
            throw new InvalidOperationException(result.Error ?? "LatentSync did not install.");
        }

        return Probe();
    }

    public async Task<AvatarVisualCheck> CheckAsync(string visualPath, IProgress<string>? progress, CancellationToken cancellationToken)
    {
        if (!File.Exists(visualPath))
        {
            return new AvatarVisualCheck(false, "That file is gone.", 0, 0, 0);
        }

        progress?.Report("Checking whether this picture has a usable face…");
        var result = await RunScriptAsync(["--check", visualPath], TimeSpan.FromMinutes(4), progress, cancellationToken).ConfigureAwait(false);
        var line = string.IsNullOrWhiteSpace(result.Error)
            ? (result.Ok ? "This picture has a usable face." : "This picture is not usable yet.")
            : result.Error;
        return new AvatarVisualCheck(result.Ok, line, result.Width ?? 0, result.Height ?? 0, result.Faces ?? 0);
    }

    public async Task<string> GenerateAsync(string sittingPath, string line, IProgress<string>? progress, CancellationToken cancellationToken)
    {
        if (!File.Exists(sittingPath))
        {
            throw new InvalidOperationException("Add a face-on original of you alone first — head and shoulders filling the frame.");
        }

        if (string.IsNullOrWhiteSpace(line))
        {
            throw new InvalidOperationException("Write the line the twin should speak.");
        }

        var probe = Probe();
        if (!probe.Ready)
        {
            progress?.Report("Engine missing. Fetching LatentSync 1.6…");
            await EnsureAsync(progress, cancellationToken).ConfigureAwait(false);
            probe = Probe();
            if (!probe.Ready)
            {
                throw new InvalidOperationException("LatentSync did not finish installing. " + probe.Line);
            }
        }

        AppPaths.EnsureDirectories();
        progress?.Report("Synthesizing the twin’s voice…");
        var speechStem = Path.Combine(AppPaths.AvatarRoot, "speech");
        var audioPath = await _speak.SynthesizeToFileAsync(line.Trim(), speechStem, cancellationToken).ConfigureAwait(false);
        var outPath = Path.Combine(AppPaths.AvatarRoot, "generated.mp4");
        if (File.Exists(outPath))
        {
            File.Delete(outPath);
        }

        progress?.Report("Making the live likeness from what you filed…");
        var result = await RunScriptAsync(
            ["--sitting", sittingPath, "--audio", audioPath, "--out", outPath],
            TimeSpan.FromHours(2),
            progress,
            cancellationToken).ConfigureAwait(false);
        if (!result.Ok || string.IsNullOrWhiteSpace(result.Path) || !File.Exists(result.Path))
        {
            throw new InvalidOperationException(string.IsNullOrWhiteSpace(result.Error)
                ? "LatentSync did not write a video. File a face-on original of you alone — head and shoulders filling the frame."
                : result.Error);
        }

        _settings.Current.AvatarGeneratedPath = result.Path;
        _settings.Save();
        return result.Path;
    }

    private async Task<ScriptResult> RunScriptAsync(
        IReadOnlyList<string> extra,
        TimeSpan timeout,
        IProgress<string>? progress,
        CancellationToken cancellationToken)
    {
        var script = ScriptPath;
        if (!File.Exists(script))
        {
            throw new InvalidOperationException("lipsync.py is missing from this install.");
        }

        var python = ResolvePython(preferEngine: extra.Count == 0 || extra[0] != "--ensure");
        var args = new List<string> { "-u", script, "--root", EngineRoot, "--comfy", _settings.Current.ComfyUrl };
        args.AddRange(extra);
        var start = new ProcessStartInfo
        {
            FileName = python,
            WorkingDirectory = Path.GetDirectoryName(script) ?? AppContext.BaseDirectory,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            StandardOutputEncoding = Encoding.UTF8,
            StandardErrorEncoding = Encoding.UTF8,
        };
        start.ArgumentList.Clear();
        foreach (var arg in args)
        {
            start.ArgumentList.Add(arg);
        }

        start.Environment["HEIRLOOM_AVATAR_ENGINE"] = EngineRoot;
        start.Environment["HEIRLOOM_COMFY_URL"] = _settings.Current.ComfyUrl;
        var models = Path.GetDirectoryName(EngineRoot) ?? EngineRoot;
        start.Environment["UV_PYTHON_INSTALL_DIR"] = Path.Combine(models, "python");
        start.Environment["UV_CACHE_DIR"] = Path.Combine(models, "uv-cache");
        start.Environment["HF_HOME"] = Path.Combine(models, "hf");
        start.Environment["PIP_CACHE_DIR"] = Path.Combine(models, "pip-cache");
        start.Environment["PYTHONUTF8"] = "1";

        using var process = new Process { StartInfo = start, EnableRaisingEvents = true };
        var stdout = new StringBuilder();
        var stderr = new StringBuilder();
        process.OutputDataReceived += (_, e) =>
        {
            if (e.Data is null)
            {
                return;
            }

            stdout.AppendLine(e.Data);
            if (e.Data.StartsWith("STATUS:", StringComparison.Ordinal))
            {
                progress?.Report(e.Data["STATUS:".Length..].Trim());
            }
        };
        process.ErrorDataReceived += (_, e) =>
        {
            if (e.Data is not null)
            {
                stderr.AppendLine(e.Data);
            }
        };

        if (!process.Start())
        {
            throw new InvalidOperationException("Could not start the avatar engine.");
        }

        process.BeginOutputReadLine();
        process.BeginErrorReadLine();
        using var timeoutCts = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        timeoutCts.CancelAfter(timeout);
        try
        {
            await process.WaitForExitAsync(timeoutCts.Token).ConfigureAwait(false);
        }
        catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
        {
            TryKill(process);
            throw new TimeoutException("LatentSync ran longer than expected and was stopped.");
        }

        var json = LastJson(stdout.ToString());
        if (json is not null)
        {
            var parsed = JsonSerializer.Deserialize<ScriptResult>(json, JsonOptions);
            if (parsed is not null)
            {
                if (!parsed.Ok && string.IsNullOrWhiteSpace(parsed.Error))
                {
                    parsed = parsed with { Error = Tail(stderr.ToString(), 800) };
                }

                return parsed;
            }
        }

        var err = Tail(stderr.ToString(), 800);
        throw new InvalidOperationException(string.IsNullOrWhiteSpace(err)
            ? "Avatar engine returned no result."
            : err);
    }

    private string ResolvePython(bool preferEngine)
    {
        if (preferEngine)
        {
            var venv = Path.Combine(EngineRoot, ".venv", "Scripts", "python.exe");
            if (File.Exists(venv))
            {
                return venv;
            }
        }

        return ResolveBootstrapPython();
    }

    private static string ResolveBootstrapPython()
    {
        var py = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "Programs", "Python", "Python314", "python.exe");
        if (File.Exists(py))
        {
            return py;
        }

        var found = Where("python.exe");
        return string.IsNullOrWhiteSpace(found) ? "python" : found;
    }

    private static string Where(string name)
    {
        try
        {
            var start = new ProcessStartInfo
            {
                FileName = "where.exe",
                Arguments = name,
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = true,
            };
            using var process = Process.Start(start);
            var line = process?.StandardOutput.ReadLine();
            process?.WaitForExit(4000);
            return line?.Trim() ?? "";
        }
        catch
        {
            return "";
        }
    }

    private static string? LastJson(string text)
    {
        foreach (var line in text.Split('\n', StringSplitOptions.RemoveEmptyEntries).Reverse())
        {
            var trimmed = line.Trim();
            if (trimmed.StartsWith('{') && trimmed.EndsWith('}'))
            {
                return trimmed;
            }
        }

        return null;
    }

    private static string Tail(string text, int max)
    {
        if (string.IsNullOrWhiteSpace(text))
        {
            return "";
        }

        text = text.Trim();
        return text.Length <= max ? text : text[^max..];
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
            // Best-effort stop; do not surface a second fault.
        }
    }

    private sealed record ScriptResult(
        bool Ok,
        string? Engine,
        string? Path,
        string? Error,
        int? Width,
        int? Height,
        int? Faces);
}
