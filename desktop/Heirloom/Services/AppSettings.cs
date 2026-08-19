using System.Text.Json;
using System.Text.Json.Serialization;

namespace Heirloom.Services;

public sealed class AppSettings
{
    public string BackendUrl { get; set; } = "https://voice-clone-hub-20.emergent.host";
    public bool SetupComplete { get; set; }
    public bool SetupSkipped { get; set; }
    public string DiskProfile { get; set; } = "full";
    public string MachineRole { get; set; } = "daily";
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
    public bool AllowPcControl { get; set; } = true;
    public bool AllowSeeScreen { get; set; }
    public bool AllowSpeak { get; set; } = true;
    public string PersonalityNotes { get; set; } = "";
    public string ValuesNotes { get; set; } = "";
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

    public static void EnsureDirectories()
    {
        Directory.CreateDirectory(Root);
        Directory.CreateDirectory(ModelsRoot);
        Directory.CreateDirectory(Path.Combine(ModelsRoot, "whisper"));
        Directory.CreateDirectory(ChromeButtons);
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

    public AppSettings Current { get; private set; } = new();

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
    }
}
