using System.IO;
using Heirloom.BoxCore;

namespace Heirloom.Companion;

public sealed class CompanionStore
{
    public string SettingsPath { get; } = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "Heirloom",
        "settings.json");

    public string Root => Path.GetDirectoryName(SettingsPath) ?? ".";

    public string BoxUrl
    {
        get => BoxLink.Normalize(SettingsPatch.ReadString(SettingsPath, SettingsPatch.BoxUrl, BoxLink.DefaultBoxUrl));
        set => Patch(new Dictionary<string, object?> { [SettingsPatch.BoxUrl] = BoxLink.Normalize(value) });
    }

    public string Pin => SettingsPatch.ReadString(SettingsPath, SettingsPatch.BoxCertSha256, "");

    public string CaPem => SettingsPatch.ReadString(SettingsPath, SettingsPatch.BoxCaPem, "");

    public bool Toasts
    {
        get => SettingsPatch.ReadBool(SettingsPath, SettingsPatch.CompanionToasts, true);
        set => Patch(new Dictionary<string, object?> { [SettingsPatch.CompanionToasts] = value });
    }

    public bool Autostart
    {
        get => SettingsPatch.ReadBool(SettingsPath, SettingsPatch.CompanionAutostart, false);
        set => Patch(new Dictionary<string, object?> { [SettingsPatch.CompanionAutostart] = value });
    }

    public bool SystemAudio
    {
        get => SettingsPatch.ReadBool(SettingsPath, SettingsPatch.CompanionAudioSystem, true);
        set => Patch(new Dictionary<string, object?> { [SettingsPatch.CompanionAudioSystem] = value });
    }

    public bool MicAudio
    {
        get => SettingsPatch.ReadBool(SettingsPath, SettingsPatch.CompanionAudioMic, true);
        set => Patch(new Dictionary<string, object?> { [SettingsPatch.CompanionAudioMic] = value });
    }

    public string WakePhrase
    {
        get => SettingsPatch.ReadString(SettingsPath, SettingsPatch.CompanionWakePhrase, "");
        set => Patch(new Dictionary<string, object?> { [SettingsPatch.CompanionWakePhrase] = value.Trim() });
    }

    public string TwinName
    {
        get => SettingsPatch.ReadString(SettingsPath, SettingsPatch.CompanionTwinName, "Twin");
        set => Patch(new Dictionary<string, object?> { [SettingsPatch.CompanionTwinName] = value.Trim() });
    }

    public bool Proactive
    {
        get => SettingsPatch.ReadBool(SettingsPath, SettingsPatch.CompanionProactive, false);
        set => Patch(new Dictionary<string, object?> { [SettingsPatch.CompanionProactive] = value });
    }

    public void SaveTrust(string url, string pin, string? pem)
    {
        Patch(new Dictionary<string, object?>
        {
            [SettingsPatch.BoxUrl] = BoxLink.Normalize(url),
            [SettingsPatch.BoxCertSha256] = pin,
            [SettingsPatch.BoxCaPem] = pem ?? "",
        });
    }

    public string? Session() => DpapiBoxSession.TryRead(DpapiBoxSession.SessionFile(Root));

    public void SaveSession(string token) => DpapiBoxSession.Save(DpapiBoxSession.SessionFile(Root), token);

    private void Patch(IReadOnlyDictionary<string, object?> values) => SettingsPatch.Write(SettingsPath, values);
}
