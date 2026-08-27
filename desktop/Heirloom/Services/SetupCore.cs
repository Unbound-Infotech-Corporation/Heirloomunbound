using System.Net;
using System.Net.Http.Headers;
using System.Net.Sockets;
using System.Text.Json;

namespace Heirloom.Services;

public sealed record SetupDiskPlan(
    bool CanHear,
    bool CanThink,
    bool CanPicture,
    string ProfileId,
    string DiskLine,
    long FreeBytes);

public sealed record SetupProgress(string TaskId, string State, string Detail);

public sealed record SetupReport(
    bool VaultOk,
    bool HearingOk,
    bool MindOk,
    bool PictureOk,
    string Headline,
    string Body);

public static class SetupTasks
{
    public const string Vault = "vault";
    public const string Hearing = "hearing";
    public const string Mind = "mind";
    public const string Picture = "picture";
}

public static class SetupCopy
{
    public const string WhisperUrl = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin";
    public const string OllamaSetupUrl = "https://ollama.com/download/OllamaSetup.exe";
    public const string TwinMindName = "llama3.1";

    public const long HearingBytes = 250L * 1024 * 1024;
    public const long MindBytes = 8L * 1024 * 1024 * 1024;
    public const long PictureBytes = 12L * 1024 * 1024 * 1024;
    public const long WhisperMinBytes = 50L * 1024 * 1024;

    public static HttpClient CreateDownloadClient()
    {
        var handler = new SocketsHttpHandler
        {
            AllowAutoRedirect = true,
            AutomaticDecompression = DecompressionMethods.All,
            PooledConnectionLifetime = TimeSpan.FromMinutes(5),
        };
        var http = new HttpClient(handler)
        {
            Timeout = TimeSpan.FromHours(3),
        };
        http.DefaultRequestHeaders.UserAgent.ParseAdd("Heirloom/0.4.0");
        http.DefaultRequestHeaders.Accept.Add(new MediaTypeWithQualityHeaderValue("*/*"));
        return http;
    }

    public static SetupDiskPlan PlanForPath(string path)
    {
        try
        {
            var full = Path.GetFullPath(string.IsNullOrWhiteSpace(path) ? AppPaths.DefaultVaultPath : path);
            var root = Path.GetPathRoot(full);
            if (string.IsNullOrWhiteSpace(root))
            {
                return PlanForFreeSpace(0, "this computer");
            }

            var drive = new DriveInfo(root);
            return PlanForFreeSpace(drive.AvailableFreeSpace, drive.Name.TrimEnd('\\'));
        }
        catch
        {
            return PlanForFreeSpace(0, "this computer");
        }
    }

    public static SetupDiskPlan PlanForFreeSpace(long freeBytes, string driveName = "this computer")
    {
        var hear = freeBytes >= HearingBytes;
        var think = freeBytes >= MindBytes;
        var picture = freeBytes >= MindBytes + PictureBytes;
        var profile = freeBytes >= 50L * 1024 * 1024 * 1024
            ? "studio"
            : freeBytes >= 20L * 1024 * 1024 * 1024
                ? "full"
                : "lite";
        var disk = FormatBytes(freeBytes) + " free on " + driveName;
        return new SetupDiskPlan(hear, think, picture, profile, disk, freeBytes);
    }

    public static string FormatBytes(long bytes)
    {
        if (bytes < 0)
        {
            return "0 B";
        }

        double n = bytes;
        string[] units = ["B", "KB", "MB", "GB", "TB"];
        var i = 0;
        while (n >= 1024 && i < units.Length - 1)
        {
            n /= 1024;
            i++;
        }

        return i == 0 ? $"{bytes} {units[i]}" : $"{n:0.#} {units[i]}";
    }

    public static string FriendlyDownload(string label, long done, long total)
    {
        if (total <= 0)
        {
            return label + " — " + FormatBytes(done) + " so far";
        }

        var pct = Math.Clamp(100.0 * done / total, 0, 100);
        return label + " — " + FormatBytes(done) + " of " + FormatBytes(total) + " (" + pct.ToString("0") + "%)";
    }

    public static string FriendlyLine(string raw)
    {
        if (string.IsNullOrWhiteSpace(raw))
        {
            return raw;
        }

        var line = FriendlyPullStatus(raw);
        line = line.Replace("LatentSync 1.6", "the talking picture", StringComparison.OrdinalIgnoreCase);
        line = line.Replace("LatentSync", "the talking picture", StringComparison.OrdinalIgnoreCase);
        line = line.Replace("ggml-base.bin", "hearing", StringComparison.OrdinalIgnoreCase);
        line = line.Replace("Whisper.net", "hearing", StringComparison.OrdinalIgnoreCase);
        line = line.Replace("Whisper", "hearing", StringComparison.OrdinalIgnoreCase);
        line = line.Replace("Ollama", "the talking mind helper", StringComparison.OrdinalIgnoreCase);
        line = line.Replace("llama3.1", "the talking mind", StringComparison.OrdinalIgnoreCase);
        line = line.Replace("llava", "picture understanding", StringComparison.OrdinalIgnoreCase);
        line = line.Replace("Provision finished", "Finished", StringComparison.OrdinalIgnoreCase);
        line = line.Replace("Installing ", "Preparing ", StringComparison.OrdinalIgnoreCase);
        line = line.Replace("Fetching ", "Downloading ", StringComparison.OrdinalIgnoreCase);
        line = line.Replace("Pulling ", "Downloading ", StringComparison.OrdinalIgnoreCase);
        return line;
    }

    public static string FriendlyPullStatus(string raw)
    {
        var t = raw.Trim();
        var lower = t.ToLowerInvariant();
        if (lower.Contains("pulling manifest") || lower.Contains("looking up"))
        {
            return "Looking up the talking mind…";
        }

        if (lower.Contains("verifying") || lower.Contains("sha256"))
        {
            return "Checking the download…";
        }

        if (lower.Contains("success") && (lower.Contains("pull") || lower.Contains("status")))
        {
            return "The talking mind is ready.";
        }

        try
        {
            using var doc = JsonDocument.Parse(t);
            var el = doc.RootElement;
            long completed = 0, total = 0;
            if (el.TryGetProperty("completed", out var c) && c.ValueKind is JsonValueKind.Number)
            {
                completed = c.GetInt64();
            }

            if (el.TryGetProperty("total", out var tot) && tot.ValueKind is JsonValueKind.Number)
            {
                total = tot.GetInt64();
            }

            if (total > 0)
            {
                return FriendlyDownload("Talking mind", completed, total);
            }

            if (el.TryGetProperty("error", out var err))
            {
                return HumanOllamaError(err.GetString() ?? t);
            }

            if (el.TryGetProperty("status", out var st))
            {
                return FriendlyPullStatus(st.GetString() ?? t);
            }
        }
        catch (JsonException)
        {
            // plain text
        }

        if (lower.Contains("downloading") || lower.Contains("pulling"))
        {
            return "Downloading the talking mind…";
        }

        return t;
    }

    public static string HumanOllamaError(string raw)
    {
        var lower = raw.ToLowerInvariant();
        if (lower.Contains("disk") || lower.Contains("no space") || lower.Contains("not enough space"))
        {
            return "This computer ran out of space while getting the talking mind ready. Free some room, then tap Try again.";
        }

        if (lower.Contains("connect") || lower.Contains("timeout") || lower.Contains("eof"))
        {
            return "The download paused. Check the internet, then tap Try again.";
        }

        return "The talking mind did not finish downloading. Check the internet, then tap Try again.";
    }

    public static string HumanFault(Exception ex, string doing, CancellationToken cancellationToken = default)
    {
        if (ex is OperationCanceledException && cancellationToken.IsCancellationRequested)
        {
            return "Stopped. Nothing was taken away. Tap Get everything ready when you want to continue.";
        }

        if (ex is TaskCanceledException or TimeoutException or OperationCanceledException)
        {
            return "This is taking too long. Check the internet, then tap Try again.";
        }

        if (ex is UnauthorizedAccessException)
        {
            return "Windows did not allow Heirloom to save a file. Close other programs, then tap Try again.";
        }

        if (ex is IOException io && LooksLikeDiskFull(io))
        {
            return "This computer is nearly out of space. Move some files off it, then tap Try again.";
        }

        if (IsNetwork(ex))
        {
            return "This computer could not reach the internet. Plug in the cable or turn on Wi-Fi, then tap Try again.";
        }

        if (ex is HttpRequestException http)
        {
            return HumanHttp(http);
        }

        var inner = ex.InnerException;
        if (inner is not null && inner != ex)
        {
            var nested = HumanFault(inner, doing, cancellationToken);
            if (!nested.StartsWith("Something didn't finish", StringComparison.Ordinal))
            {
                return nested;
            }
        }

        return "Something didn't finish while " + doing + ". Wait a moment, then tap Try again.";
    }

    public static string HumanHttp(HttpRequestException ex)
    {
        var status = ex.StatusCode;
        if (status is HttpStatusCode.Unauthorized or HttpStatusCode.Forbidden)
        {
            return "The download was refused. Wait a minute, check the internet, then tap Try again.";
        }

        if (status is HttpStatusCode.NotFound)
        {
            return "The download could not be found right now. Wait a few minutes, then tap Try again.";
        }

        if (status is >= HttpStatusCode.InternalServerError)
        {
            return "The download service is having trouble. Wait a few minutes, then tap Try again.";
        }

        if (IsNetwork(ex))
        {
            return "This computer could not reach the internet. Plug in the cable or turn on Wi-Fi, then tap Try again.";
        }

        return "The download did not finish. Check the internet, then tap Try again.";
    }

    public static string HumanHttpStatus(int status) =>
        HumanHttp(new HttpRequestException("HTTP " + status, null, (HttpStatusCode)status));

    public static string HumanInstallerExit(int code) =>
        code switch
        {
            0 => "The helper is installed.",
            1223 or 1602 or 5 => "Windows asked for permission and it was declined. Tap Get everything ready again, and choose Yes.",
            1603 => "The helper did not install. Restart this computer, then tap Get everything ready again.",
            _ => "The helper did not finish. Tap Try again. If Windows asks for permission, choose Yes.",
        };

    public static string LowDiskHearing() =>
        "This computer does not have enough free space to hear you speak. Free about 300 MB, then tap Try again.";

    public static string LowDiskMind() =>
        "This computer needs about 8 GB free for the Twin to think here. Free some room, then tap Try again.";

    public static string SkipPictureDisk() =>
        "We'll skip the talking picture for now — this computer needs more free space. Your Twin can still talk.";

    public static string SkipPictureGpu() =>
        "We'll skip the talking picture for now — it needs a stronger graphics card. Your Twin can still talk.";

    public static string SkipPictureFailed(string detail) =>
        string.IsNullOrWhiteSpace(detail)
            ? "We'll skip the talking picture for now. Your Twin can still talk."
            : "We'll skip the talking picture for now. " + detail + " Your Twin can still talk.";

    public static string DoneHeadline(bool hearing, bool mind, bool picture)
    {
        if (mind)
        {
            return picture ? "You're ready" : "Your Twin is ready";
        }

        if (hearing)
        {
            return "Almost ready";
        }

        return "Your stories folder is ready";
    }

    public static string DoneBody(bool hearing, bool mind, bool picture)
    {
        if (mind)
        {
            var voice = "Your Twin will speak with this computer's voice. A copied voice is optional later, under Settings.";
            var next = "Hold to talk, or record a memory. The Twin only remembers what you file.";
            if (!picture)
            {
                return next + " A talking picture can wait. " + voice;
            }

            return next + " " + voice;
        }

        if (hearing)
        {
            return "Heirloom can hear you, but the Twin cannot think on this computer yet. Connect to the internet (and choose Yes if Windows asks), then tap Try again.";
        }

        return "Your stories will be kept. Tap Try again when this computer is on the internet.";
    }

    public static IReadOnlyList<string> OllamaExeCandidates()
    {
        var local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        var pf = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles);
        var pf86 = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86);
        return
        [
            Path.Combine(local, "Programs", "Ollama", "ollama.exe"),
            Path.Combine(local, "Ollama", "ollama.exe"),
            Path.Combine(pf, "Ollama", "ollama.exe"),
            Path.Combine(pf86, "Ollama", "ollama.exe"),
        ];
    }

    public static string? FindOllamaExe()
    {
        foreach (var path in OllamaExeCandidates())
        {
            if (File.Exists(path))
            {
                return path;
            }
        }

        return null;
    }

    public static bool LooksLikeNvidiaGpu() =>
        File.Exists(@"C:\Windows\System32\nvapi64.dll")
        || File.Exists(@"C:\Windows\System32\nvml.dll")
        || Directory.Exists(@"C:\Program Files\NVIDIA Corporation");

    public static bool WhisperLooksComplete(string path)
    {
        try
        {
            return File.Exists(path) && new FileInfo(path).Length >= WhisperMinBytes;
        }
        catch
        {
            return false;
        }
    }

    public static async Task DownloadToFileAsync(
        HttpClient http,
        string url,
        string destPath,
        string friendlyLabel,
        IProgress<string>? progress,
        CancellationToken cancellationToken)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(destPath) ?? AppPaths.Root);
        var part = destPath + ".part";
        using var request = new HttpRequestMessage(HttpMethod.Get, url);
        using var response = await http.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, cancellationToken).ConfigureAwait(false);
        if (!response.IsSuccessStatusCode)
        {
            throw new HttpRequestException(
                "Download HTTP " + (int)response.StatusCode,
                null,
                response.StatusCode);
        }

        var media = response.Content.Headers.ContentType?.MediaType ?? "";
        if (media.Contains("html", StringComparison.OrdinalIgnoreCase))
        {
            throw new HttpRequestException("The download sent a web page instead of a file.", null, HttpStatusCode.BadGateway);
        }

        var total = response.Content.Headers.ContentLength ?? 0;
        await using var input = await response.Content.ReadAsStreamAsync(cancellationToken).ConfigureAwait(false);
        await using var output = new FileStream(part, FileMode.Create, FileAccess.Write, FileShare.None, 80 * 1024, useAsync: true);
        var buffer = new byte[80 * 1024];
        long done = 0;
        var lastReport = DateTime.UtcNow;
        progress?.Report(FriendlyDownload(friendlyLabel, 0, total));
        while (true)
        {
            var read = await input.ReadAsync(buffer.AsMemory(0, buffer.Length), cancellationToken).ConfigureAwait(false);
            if (read <= 0)
            {
                break;
            }

            await output.WriteAsync(buffer.AsMemory(0, read), cancellationToken).ConfigureAwait(false);
            done += read;
            if ((DateTime.UtcNow - lastReport).TotalMilliseconds >= 400)
            {
                progress?.Report(FriendlyDownload(friendlyLabel, done, total));
                lastReport = DateTime.UtcNow;
            }
        }

        await output.FlushAsync(cancellationToken).ConfigureAwait(false);
        output.Dispose();
        if (File.Exists(destPath))
        {
            File.Delete(destPath);
        }

        File.Move(part, destPath);
        progress?.Report(friendlyLabel + " is ready.");
    }

    private static bool LooksLikeDiskFull(IOException ex)
    {
        var msg = ex.Message;
        return msg.Contains("not enough space", StringComparison.OrdinalIgnoreCase)
            || msg.Contains("disk full", StringComparison.OrdinalIgnoreCase)
            || msg.Contains("there is not enough space", StringComparison.OrdinalIgnoreCase)
            || unchecked((uint)ex.HResult) is 0x80070070 or 0x70;
    }

    private static bool IsNetwork(Exception ex)
    {
        if (ex is SocketException)
        {
            return true;
        }

        if (ex is HttpRequestException http)
        {
            if (http.InnerException is SocketException)
            {
                return true;
            }

            var m = http.Message;
            if (m.Contains("No such host", StringComparison.OrdinalIgnoreCase)
                || m.Contains("Name or service not known", StringComparison.OrdinalIgnoreCase)
                || m.Contains("network is unreachable", StringComparison.OrdinalIgnoreCase)
                || m.Contains("actively refused", StringComparison.OrdinalIgnoreCase)
                || m.Contains("No connection could be made", StringComparison.OrdinalIgnoreCase)
                || m.Contains("Could not resolve", StringComparison.OrdinalIgnoreCase)
                || m.Contains("The remote name could not be resolved", StringComparison.OrdinalIgnoreCase)
                || m.Contains("connection attempt failed", StringComparison.OrdinalIgnoreCase)
                || m.Contains("SSL", StringComparison.OrdinalIgnoreCase)
                || m.Contains("certificate", StringComparison.OrdinalIgnoreCase))
            {
                return true;
            }
        }

        var text = ex.Message;
        return text.Contains("No such host", StringComparison.OrdinalIgnoreCase)
            || text.Contains("network", StringComparison.OrdinalIgnoreCase) && text.Contains("unreachable", StringComparison.OrdinalIgnoreCase);
    }
}
