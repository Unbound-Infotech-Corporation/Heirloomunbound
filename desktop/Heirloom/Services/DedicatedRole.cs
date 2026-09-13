namespace Heirloom.Services;

/// <summary>
/// Dedicated PC machine role for Heirloom Unbound. Writes install_profile,
/// optional startup, and power-plan consent. Never fights IT policy silently.
/// </summary>
public static class DedicatedRole
{
    public const string ConsentCopy =
        "This PC exists for Heirloom Unbound. It will start with Windows, keep local models warm, and treat the vault drive as the home of the twin.";

    public const string BrandingMark = "Heirloom Unbound · Dedicated";

    public const string AlwaysOnNote =
        "Optional always-on service: Task Scheduler can run Heirloom Unbound at system start if this PC should stay warm when nobody is signed in. Setup does not install a Windows service by default.";

    public static void Apply(AppSettings settings, bool consent, string? vaultDrive = null)
    {
        if (!consent)
        {
            throw new InvalidOperationException("Dedicated PC mode needs consent that this PC exists for Heirloom Unbound.");
        }

        settings.InstallProfile = "dedicated";
        settings.DiskProfile = "dedicated";
        settings.MachineRole = "dedicated";
        settings.DedicatedConsent = true;
        settings.WarmEngines = true;
        settings.LiveListen = true;
        settings.Autostart = true;
        settings.StartWithWindows = true;
        if (!string.IsNullOrWhiteSpace(vaultDrive))
        {
            settings.LibraryPath = vaultDrive;
        }
    }

    public static string OvernightMaintenanceHint() =>
        "Overnight maintenance hook: re-check Ollama, Whisper, Voicebox, Qwen3-TTS, and LatentSync so this dedicated PC stays current. Never Pinokio.";
}
