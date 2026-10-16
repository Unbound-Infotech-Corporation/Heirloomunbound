using System.Text.Json;
using System.Text.Json.Serialization;

namespace Heirloom.Services;

public sealed class AppSettings
{
    public string BackendUrl { get; set; } = "https://voice-clone-hub-20.emergent.host";
    public string RunMode { get; set; } = "";
    public string BoxUrl { get; set; } = "https://192.168.0.111";
    public string BoxCertSha256 { get; set; } = "";
    public string BoxCaPem { get; set; } = "";
    public bool CompanionAutostart { get; set; }
    public bool CompanionToasts { get; set; } = true;
    public bool SetupComplete { get; set; }
    public bool SetupSkipped { get; set; }
    public bool SetupCoachDismissed { get; set; }
    public string DiskProfile { get; set; } = "medium";
    public string InstallProfile { get; set; } = "medium";
    public string MachineRole { get; set; } = "daily";
    public bool DedicatedConsent { get; set; }
    public bool StartWithWindows { get; set; }
    public bool PowerPlanConsent { get; set; }
    public bool WarmEngines { get; set; }
    public bool BrandingDedicated { get; set; }
    public string LibraryPath { get; set; } = "";
    public string ComputeTarget { get; set; } = "local";
    public string AppMode { get; set; } = "owner";
    public int SessionVolume { get; set; } = 80;
    public double InputGain { get; set; } = 1.0;
    public double NoiseGate { get; set; } = 0.08;
    public bool HighPass { get; set; } = true;
    public bool LiveListen { get; set; }
    public string InputDeviceId { get; set; } = "default";
    public string OutputDeviceId { get; set; } = "default";
    public bool Autostart { get; set; }
    public string BuildId { get; set; } = "dev";
    public string TwinPersona { get; set; } = "family";
    public bool GroundedOnly { get; set; } = true;
    public bool SpeakReplies { get; set; } = true;
    public bool VrMode { get; set; }
    public bool VrGaze { get; set; }
    public bool AllowPcControl { get; set; } = true;
    public bool AllowSeeScreen { get; set; }
    public bool AllowSpeak { get; set; } = true;
    public string PersonalityNotes { get; set; } = "";
    public string ValuesNotes { get; set; } = "";
    public string SkipKinds { get; set; } = "";
    public int InputDeviceNumber { get; set; }
    public bool SessionMuted { get; set; }
    public string VendorEmail { get; set; } = "";
    public string ColorScheme { get; set; } = "parchment";
    public string ChromeMode { get; set; } = "iconsAndLabels";
    public string DockEdge { get; set; } = "left";
    public double DockSize { get; set; } = 188;
    public bool DockLocked { get; set; }
    public bool InspectorOpen { get; set; } = true;
    public double InspectorWidth { get; set; } = 292;
    public string AvatarPortraitPath { get; set; } = "";
    public List<string> AvatarPhotoPaths { get; set; } = [];
    public string AvatarSittingPath { get; set; } = "";
    public string AvatarGeneratedPath { get; set; } = "";
    public string AvatarLine { get; set; } = "This is my voice, in this room.";
    public string AvatarEngineRoot { get; set; } = "";
    public string VideoFilmPath { get; set; } = "";
    public string VideoPresetId { get; set; } = "kids";
    public string ComfyUrl { get; set; } = "http://127.0.0.1:8188";
    public bool SourceAllowFiles { get; set; } = true;
    public bool SourceAllowPhotos { get; set; } = true;
    public bool SourceAllowMail { get; set; }
    public bool SourceAllowMessages { get; set; }
}

public static class AppPaths
{
    public static string Root =>
        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Heirloom");

    public static string SettingsPath => Path.Combine(Root, "settings.json");
    public static string ModelsRoot => Path.Combine(Root, "models");
    public static string WhisperModelPath => Path.Combine(ModelsRoot, "whisper", "ggml-base.bin");
    public static string DefaultVaultPath =>
        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments), "HeirloomVault");
    public static string DistMsixPath =>
        Path.Combine(AppContext.BaseDirectory, "Heirloom.msix");
    public static string ChromeRoot => Path.Combine(Root, "chrome");
    public static string ChromeButtons => Path.Combine(ChromeRoot, "buttons");
    public static string AvatarRoot => Path.Combine(Root, "avatar");
    public static string VideoRoot => Path.Combine(AvatarRoot, "films");
    public static string AvatarEngineRoot =>
        ResolveAvatarEngineRoot(Directory.Exists(@"F:\HeirloomModels"));

    /// <summary>
    /// F: is the models disk only when HeirloomModels is already there.
    /// A freshly reset PC can have an empty F: that must not become the engine root.
    /// </summary>
    internal static string ResolveAvatarEngineRoot(bool heirloomModelsPresent) =>
        heirloomModelsPresent
            ? @"F:\HeirloomModels\avatar-engine"
            : Path.Combine(Root, "engines", "avatar");

    public static void EnsureDirectories()
    {
        Directory.CreateDirectory(Root);
        TryCreateDirectory(ModelsRoot);
        TryCreateDirectory(Path.Combine(ModelsRoot, "whisper"));
        TryCreateDirectory(ChromeButtons);
        TryCreateDirectory(AvatarRoot);
        TryCreateDirectory(VideoRoot);
        TryCreateDirectory(AvatarEngineRoot);
    }

    /// <summary>
    /// Engine, chrome, and media folders are optional. A full or read-only drive must not stop settings from loading.
    /// </summary>
    internal static bool TryCreateDirectory(string path)
    {
        try
        {
            Directory.CreateDirectory(path);
            return true;
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or NotSupportedException or ArgumentException)
        {
            return false;
        }
    }
}

public sealed class SettingsStore
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        WriteIndented = true,
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
    };

    public AppSettings Current { get; set; } = new();

    public event Action? Changed;

    public void Load()
    {
        AppPaths.EnsureDirectories();
        if (!File.Exists(AppPaths.SettingsPath))
        {
            Current.LibraryPath = AppPaths.DefaultVaultPath;
            Save();
            return;
        }

        try
        {
            var json = File.ReadAllText(AppPaths.SettingsPath);
            Current = JsonSerializer.Deserialize<AppSettings>(json, JsonOptions) ?? new AppSettings();
            if (string.IsNullOrWhiteSpace(Current.LibraryPath))
            {
                Current.LibraryPath = AppPaths.DefaultVaultPath;
            }
        }
        catch
        {
            Current = new AppSettings { LibraryPath = AppPaths.DefaultVaultPath };
        }
    }

    public void Save()
    {
        AppPaths.EnsureDirectories();
        File.WriteAllText(AppPaths.SettingsPath, JsonSerializer.Serialize(Current, JsonOptions));
        Changed?.Invoke();
    }
}
