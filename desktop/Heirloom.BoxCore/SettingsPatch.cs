using System.Text.Json;
using System.Text.Json.Nodes;

namespace Heirloom.BoxCore;

/// <summary>
/// Updates a few keys in settings.json and leaves every other studio field in place.
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
    public const string CompanionScreen = "companion_screen";
    public const string CompanionWakePhrase = "companion_wake_phrase";
    public const string CompanionTwinName = "companion_twin_name";
    public const string CompanionProactive = "companion_proactive";
    public const string CompanionLiveOnTop = "companion_live_on_top";
    public const string RunMode = "run_mode";

    private static readonly JsonSerializerOptions Json = new() { WriteIndented = true };

    public static void Write(string path, IReadOnlyDictionary<string, object?> values)
    {
        JsonObject obj;
        if (File.Exists(path))
        {
            var parsed = JsonNode.Parse(File.ReadAllText(path));
            obj = parsed as JsonObject ?? new JsonObject();
        }
        else
        {
            obj = new JsonObject();
        }

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

        var dir = Path.GetDirectoryName(path);
        if (!string.IsNullOrWhiteSpace(dir))
        {
            Directory.CreateDirectory(dir);
        }

        File.WriteAllText(path, obj.ToJsonString(Json));
    }

    public static string ReadString(string path, string key, string fallback)
    {
        if (!File.Exists(path))
        {
            return fallback;
        }

        try
        {
            var parsed = JsonNode.Parse(File.ReadAllText(path)) as JsonObject;
            var value = parsed?[key]?.GetValue<string>();
            return string.IsNullOrWhiteSpace(value) ? fallback : value;
        }
        catch (Exception ex) when (ex is JsonException or InvalidOperationException or IOException)
        {
            return fallback;
        }
    }

    public static bool ReadBool(string path, string key, bool fallback)
    {
        if (!File.Exists(path))
        {
            return fallback;
        }

        try
        {
            var parsed = JsonNode.Parse(File.ReadAllText(path)) as JsonObject;
            var node = parsed?[key];
            if (node is null)
            {
                return fallback;
            }

            return node.GetValue<bool>();
        }
        catch (Exception ex) when (ex is JsonException or InvalidOperationException or IOException)
        {
            return fallback;
        }
    }
}
