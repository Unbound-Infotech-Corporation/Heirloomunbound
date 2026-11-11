using System.Security.Cryptography;
using System.Text;

namespace Heirloom.BoxCore;

/// <summary>
/// Local BYO API keys. The WinUI app stores them in Credential Locker
/// (<c>CredentialStore.SaveByoKey</c>). This type is the DPAPI file copy for
/// a path that is not <c>settings.json</c>. Neither store is available to
/// this library on Linux: <see cref="Save"/> throws and writes nothing.
/// </summary>
public static class ByoKeyFile
{
    private static readonly byte[] Entropy = Encoding.UTF8.GetBytes("Heirloom.ByoKey.v1");

    public static readonly string[] Names =
    [
        "elevenlabs",
        "did",
        "fal",
        "openai",
        "resend",
        "huggingface",
    ];

    public static void RequireKnown(string name)
    {
        if (!Names.Contains(name, StringComparer.Ordinal))
        {
            throw new ArgumentException("Unknown BYO key name.");
        }
    }

    public static string ForLog(string? secret)
    {
        _ = secret;
        return "[redacted]";
    }

    public static bool SettingsContain(string? settingsJson, string? secret)
    {
        var raw = (secret ?? "").Trim();
        if (raw.Length < 8)
        {
            return false;
        }

        return (settingsJson ?? "").Contains(raw, StringComparison.Ordinal);
    }

    public static void Save(string directory, string name, string secret)
    {
        RequireKnown(name);
        if (!OperatingSystem.IsWindows())
        {
            throw new PlatformNotSupportedException(
                "BYO keys on this PC are stored with Windows DPAPI or Credential Locker.");
        }

        var raw = Encoding.UTF8.GetBytes(secret ?? "");
        var protectedBytes = ProtectedData.Protect(raw, Entropy, DataProtectionScope.CurrentUser);
        Directory.CreateDirectory(directory);
        File.WriteAllBytes(Path.Combine(directory, name + ".bin"), protectedBytes);
    }

    public static string? TryRead(string directory, string name)
    {
        RequireKnown(name);
        var path = Path.Combine(directory, name + ".bin");
        if (!OperatingSystem.IsWindows() || !File.Exists(path))
        {
            return null;
        }

        try
        {
            var protectedBytes = File.ReadAllBytes(path);
            var raw = ProtectedData.Unprotect(protectedBytes, Entropy, DataProtectionScope.CurrentUser);
            var secret = Encoding.UTF8.GetString(raw).Trim();
            return secret.Length == 0 ? null : secret;
        }
        catch (CryptographicException)
        {
            return null;
        }
    }
}
