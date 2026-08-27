using System.Diagnostics;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace Heirloom.Services;

public sealed record VideoEngineProbe(
    bool TalkingReady,
    bool FfmpegReady,
    bool ComfyUp,
    bool LtxReady,
    bool WanReady,
    bool HunyuanReady,
    string Line,
    string RecommendLine);

public sealed class VideoEngineService
{
    private static readonly JsonSerializerOptions JsonOptions = new() { PropertyNameCaseInsensitive = true };
    private readonly SettingsStore _settings;
    private readonly SpeakService _speak;
    private readonly AvatarEngineService _avatar;

    public VideoEngineService(SettingsStore settings, SpeakService speak, AvatarEngineService avatar)
    {
        _settings = settings;
        _speak = speak;
        _avatar = avatar;
    }

    public string ScriptPath
    {
        get
        {
            var bundled = Path.Combine(AppContext.BaseDirectory, "tools", "avatar_engine", "video_engine.py");
            return File.Exists(bundled) ? bundled : Path.Combine(AppContext.BaseDirectory, "video_engine.py");
        }
    }

    public VideoEngineProbe Probe()
    {
        var talking = _avatar.Probe();
        var ffmpeg = File.Exists(Path.Combine(_avatar.EngineRoot, "ffmpeg", "ffmpeg.exe"));
        var line = VideoCatalog.RecommendLine(talking.Ready, false, false, false, false);
        return new VideoEngineProbe(talking.Ready, ffmpeg, false, false, false, false, talking.Line, line);
    }

    public async Task<VideoEngineProbe> ProbeAsync(CancellationToken cancellationToken)
    {
        var talking = _avatar.Probe();
        VideoScriptResult? extra = null;
        try
        {
            extra = await RunVideo(["--probe"], TimeSpan.FromSeconds(8), null, cancellationToken).ConfigureAwait(false);
        }
        catch
        {
            extra = null;
        }

        var ffmpeg = extra?.FfmpegReady == true || File.Exists(Path.Combine(_avatar.EngineRoot, "ffmpeg", "ffmpeg.exe"));
        var comfy = extra?.ComfyOk == true;
        var ltx = extra?.Ltx == true;
        var wan = extra?.Wan == true;
        var hunyuan = extra?.Hunyuan == true;
        var line = VideoCatalog.RecommendLine(talking.Ready, ltx, wan, hunyuan, comfy);
        return new VideoEngineProbe(talking.Ready, ffmpeg, comfy, ltx, wan, hunyuan, talking.Line, line);
    }

    public async Task<string> RenderFilmAsync(
        IReadOnlyList<VideoShotPlan> shots,
        string sittingOrFace,
        IProgress<string>? progress,
        CancellationToken cancellationToken)
    {
        AppPaths.EnsureDirectories();
        var job = Path.Combine(AppPaths.VideoRoot, DateTime.Now.ToString("yyyyMMdd-HHmmss"));
        Directory.CreateDirectory(job);
        var clips = new List<string>();
        var probe = Probe();

        for (var i = 0; i < shots.Count; i++)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var shot = shots[i];
            progress?.Report("Shot " + (i + 1) + " of " + shots.Count + " — " + shot.Title + "…");
            var clip = Path.Combine(job, $"shot-{i + 1:00}.mp4");
            var made = await RenderShotAsync(shot, sittingOrFace, clip, probe, progress, cancellationToken).ConfigureAwait(false);
            if (!string.IsNullOrWhiteSpace(made) && File.Exists(made))
            {
                clips.Add(made);
            }
            else
            {
                progress?.Report("Skipped a beat: " + (shot.Title) + ".");
            }
        }

        if (clips.Count == 0)
        {
            throw new InvalidOperationException("No shots were ready. File a likeness or a photograph, then make the film again.");
        }

        var film = Path.Combine(job, "film.mp4");
        if (clips.Count == 1)
        {
            File.Copy(clips[0], film, overwrite: true);
        }
        else
        {
            var joined = await RunVideo(
                ["--concat", "--clips", string.Join("|", clips), "--out", film],
                TimeSpan.FromMinutes(20),
                progress,
                cancellationToken).ConfigureAwait(false);
            if (!joined.Ok || string.IsNullOrWhiteSpace(joined.Path) || !File.Exists(joined.Path))
            {
                throw new InvalidOperationException(joined.Error ?? "Could not join the shots into one film.");
            }

            film = joined.Path;
        }

        _settings.Current.VideoFilmPath = film;
        _settings.Save();
        return film;
    }

    private async Task<string?> RenderShotAsync(
        VideoShotPlan shot,
        string sittingOrFace,
        string clip,
        VideoEngineProbe probe,
        IProgress<string>? progress,
        CancellationToken cancellationToken)
    {
        if (shot.Kind == VideoShotKind.TalkingHead)
        {
            if (string.IsNullOrWhiteSpace(sittingOrFace) || !File.Exists(sittingOrFace))
            {
                throw new InvalidOperationException("File a sitting or a face-on original first. Video studio will not invent a mouth on a group shot.");
            }

            var generated = await _avatar.GenerateAsync(sittingOrFace, shot.Script, progress, cancellationToken).ConfigureAwait(false);
            if (!string.IsNullOrWhiteSpace(generated) && File.Exists(generated))
            {
                File.Copy(generated, clip, overwrite: true);
                return clip;
            }

            return generated;
        }

        var image = shot.ImagePath;
        if (string.IsNullOrWhiteSpace(image) || !File.Exists(image))
        {
            if (shot.Kind == VideoShotKind.TextToVideo)
            {
                progress?.Report("Text-to-video needs Wan or LTX on this PC. This beat was skipped.");
                return null;
            }

            return null;
        }

        if (shot.Kind == VideoShotKind.ImageToVideo && (probe.WanReady || probe.LtxReady))
        {
            progress?.Report("Wan/LTX is on this PC, but this studio still holds the photograph until a family-safe graph is filed. Using a living still with your voice.");
        }
        else if (shot.Kind == VideoShotKind.ImageToVideo)
        {
            progress?.Report("No Wan or LTX weights on this PC. Holding the photograph with your voice — the film still exports.");
        }

        string? audio = null;
        if (!string.IsNullOrWhiteSpace(shot.Script))
        {
            progress?.Report("Synthesizing the twin’s voice for this beat…");
            audio = await _speak.SynthesizeToFileAsync(shot.Script, Path.Combine(Path.GetDirectoryName(clip)!, "speech-" + shot.Id), cancellationToken).ConfigureAwait(false);
        }

        var args = new List<string> { "--hold", "--image", image, "--seconds", shot.Seconds.ToString(), "--out", clip };
        if (!string.IsNullOrWhiteSpace(audio))
        {
            args.Add("--audio");
            args.Add(audio);
        }

        var result = await RunVideo(args, TimeSpan.FromMinutes(8), progress, cancellationToken).ConfigureAwait(false);
        if (!result.Ok)
        {
            throw new InvalidOperationException(result.Error ?? "Could not hold that photograph as a shot.");
        }

        return result.Path;
    }

    private async Task<VideoScriptResult> RunVideo(
        IReadOnlyList<string> extra,
        TimeSpan timeout,
        IProgress<string>? progress,
        CancellationToken cancellationToken)
    {
        var script = ScriptPath;
        if (!File.Exists(script))
        {
            throw new InvalidOperationException("video_engine.py is missing from this install.");
        }

        var python = ResolvePython();
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
        start.ArgumentList.Add("-u");
        start.ArgumentList.Add(script);
        start.ArgumentList.Add("--root");
        start.ArgumentList.Add(_avatar.EngineRoot);
        start.ArgumentList.Add("--comfy");
        start.ArgumentList.Add(_settings.Current.ComfyUrl ?? "");
        foreach (var arg in extra)
        {
            start.ArgumentList.Add(arg);
        }

        start.Environment["HEIRLOOM_AVATAR_ENGINE"] = _avatar.EngineRoot;
        start.Environment["HEIRLOOM_COMFY_URL"] = _settings.Current.ComfyUrl ?? "";
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
            throw new InvalidOperationException("Could not start the video engine.");
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

            throw new TimeoutException("The video engine ran longer than expected and was stopped.");
        }

        var json = LastJson(stdout.ToString());
        if (json is not null)
        {
            var parsed = JsonSerializer.Deserialize<VideoScriptResult>(json, JsonOptions);
            if (parsed is not null)
            {
                return parsed with
                {
                    Error = string.IsNullOrWhiteSpace(parsed.Error) ? Tail(stderr.ToString()) : parsed.Error,
                    FfmpegReady = parsed.FfmpegReady || !string.IsNullOrWhiteSpace(parsed.Ffmpeg),
                };
            }
        }

        throw new InvalidOperationException(string.IsNullOrWhiteSpace(stderr.ToString())
            ? "Video engine returned no result."
            : Tail(stderr.ToString()));
    }

    private string ResolvePython()
    {
        var venv = Path.Combine(_avatar.EngineRoot, ".venv", "Scripts", "python.exe");
        if (File.Exists(venv))
        {
            return venv;
        }

        var py = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "Programs", "Python", "Python314", "python.exe");
        if (File.Exists(py))
        {
            return py;
        }

        return "python";
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

    private static string Tail(string text) =>
        string.IsNullOrWhiteSpace(text) ? "" : (text.Trim().Length <= 800 ? text.Trim() : text.Trim()[^800..]);

    private sealed record VideoScriptResult(
        bool Ok,
        string? Path,
        string? Error,
        string? Ffmpeg,
        [property: JsonPropertyName("comfy_ok")] bool ComfyOk = false,
        [property: JsonPropertyName("ltx")] bool Ltx = false,
        [property: JsonPropertyName("wan")] bool Wan = false,
        [property: JsonPropertyName("hunyuan")] bool Hunyuan = false)
    {
        public bool FfmpegReady { get; init; }
    }
}
