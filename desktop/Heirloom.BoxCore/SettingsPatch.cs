using System.Runtime.CompilerServices;
using System.Text.Json;
using System.Text.Json.Nodes;

[assembly: InternalsVisibleTo("Heirloom.Tests")]

namespace Heirloom.BoxCore;

/// <summary>
/// Updates a few keys in settings.json and leaves every other studio field in place.
/// Saves retry while another process holds the file, share the read, and replace
/// the file atomically. A failed save returns false and does not throw.
/// </summary>
public static class SettingsPatch
{
    public const string BoxUrl = "box_url";
    public const string BoxCertSha256 = "box_cert_sha256";
    public const string BoxCaPem = "box_ca_pem";
    public const string CompanionAutostart = "companion_autostart";
    public const string CompanionToasts = "companion_toasts";
    public const string CompanionAudioSystem = "companion_audio_system";
    public const string CompanionAudioMic = "companion_audio_mic";
    public const string CompanionMicDevice = "companion_mic_device";
    public const string CompanionScreen = "companion_screen";
    public const string CompanionWakePhrase = "companion_wake_phrase";
    public const string CompanionTwinName = "companion_twin_name";
    public const string CompanionProactive = "companion_proactive";
    public const string CompanionLiveOnTop = "companion_live_on_top";
    public const string RunMode = "run_mode";

    public static FileShare ShareMode => FileShare.ReadWrite;

    internal static int IoFailuresBeforeSuccess { get; set; }
    internal static int MaxAttempts { get; set; } = 5;
    internal static TimeSpan RetryDelay { get; set; } = TimeSpan.FromMilliseconds(40);

    internal static void ResetTestHooks()
    {
        IoFailuresBeforeSuccess = 0;
        MaxAttempts = 5;
        RetryDelay = TimeSpan.FromMilliseconds(40);
    }

    private static readonly JsonSerializerOptions Json = new() { WriteIndented = true };

    public static bool Write(string path, IReadOnlyDictionary<string, object?> values)
    {
        return Retry(() =>
        {
            var obj = ReadObject(path);
            foreach (var pair in values)
            {
                obj[pair.Key] = pair.Value switch
                {
                    null => null,
                    bool flag => flag,
                    string text => text,
                    _ => pair.Value.ToString(),
                };
            }

            WriteAtomicText(path, obj.ToJsonString(Json));
        });
    }

    public static bool WriteAllText(string path, string contents) =>
        Retry(() => WriteAtomicText(path, contents));

    public static string? ReadAllTextShared(string path)
    {
        if (!File.Exists(path))
        {
            return null;
        }

        try
        {
            using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, ShareMode);
            using var reader = new StreamReader(stream);
            return reader.ReadToEnd();
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            return null;
        }
    }

    public static string ReadString(string path, string key, string fallback)
    {
        var text = ReadAllTextShared(path);
        if (text is null)
        {
            return fallback;
        }

        try
        {
            var parsed = JsonNode.Parse(text) as JsonObject;
            var value = parsed?[key]?.GetValue<string>();
            return string.IsNullOrWhiteSpace(value) ? fallback : value;
        }
        catch (Exception ex) when (ex is JsonException or InvalidOperationException)
        {
            return fallback;
        }
    }

    public static bool ReadBool(string path, string key, bool fallback)
    {
        var text = ReadAllTextShared(path);
        if (text is null)
        {
            return fallback;
        }

        try
        {
            var parsed = JsonNode.Parse(text) as JsonObject;
            var node = parsed?[key];
            if (node is null)
            {
                return fallback;
            }

            return node.GetValue<bool>();
        }
        catch (Exception ex) when (ex is JsonException or InvalidOperationException)
        {
            return fallback;
        }
    }

    private static JsonObject ReadObject(string path)
    {
        if (!File.Exists(path))
        {
            return new JsonObject();
        }

        var text = ReadAllTextShared(path);
        if (text is null)
        {
            throw new IOException("settings.json is in use.");
        }

        try
        {
            return JsonNode.Parse(text) as JsonObject ?? new JsonObject();
        }
        catch (JsonException)
        {
            return new JsonObject();
        }
    }

    private static void WriteAtomicText(string path, string contents)
    {
        if (IoFailuresBeforeSuccess > 0)
        {
            IoFailuresBeforeSuccess--;
            throw new IOException("settings.json is in use.");
        }

        var dir = Path.GetDirectoryName(path);
        if (string.IsNullOrWhiteSpace(dir))
        {
            dir = Path.GetTempPath();
        }

        Directory.CreateDirectory(dir);
        var temp = Path.Combine(dir, Path.GetFileName(path) + "." + Guid.NewGuid().ToString("n") + ".tmp");
        try
        {
            using (var stream = new FileStream(temp, FileMode.Create, FileAccess.Write, ShareMode))
            using (var writer = new StreamWriter(stream))
            {
                writer.Write(contents);
            }

            if (File.Exists(path))
            {
                File.Replace(temp, path, destinationBackupFileName: null, ignoreMetadataErrors: true);
            }
            else
            {
                File.Move(temp, path);
            }
        }
        catch
        {
            try
            {
                if (File.Exists(temp))
                {
                    File.Delete(temp);
                }
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
            {
            }

            throw;
        }
    }

    private static bool Retry(Action action)
    {
        var attempts = Math.Max(1, MaxAttempts);
        for (var attempt = 1; attempt <= attempts; attempt++)
        {
            try
            {
                action();
                return true;
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
            {
                if (attempt >= attempts)
                {
                    return false;
                }

                if (RetryDelay > TimeSpan.Zero)
                {
                    Thread.Sleep(TimeSpan.FromMilliseconds(RetryDelay.TotalMilliseconds * attempt));
                }
            }
        }

        return false;
    }
}
