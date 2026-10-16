using System.Net.Security;
using System.Security.Authentication;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.Text;

namespace Heirloom.BoxCore;

public static class CertificatePin
{
    public const string CheckFailed = "Certificate check failed.";

    public static string Sha256Hex(byte[] der)
    {
        var hash = SHA256.HashData(der);
        return Convert.ToHexString(hash);
    }

    public static string Normalize(string fingerprint)
    {
        var chars = (fingerprint ?? "").Where(Uri.IsHexDigit).ToArray();
        return new string(chars).ToUpperInvariant();
    }

    public static bool PresentedMatches(string? pinnedFingerprint, X509Certificate2? leaf, X509Chain? chain)
    {
        var want = Normalize(pinnedFingerprint ?? "");
        if (want.Length == 0 || leaf is null)
        {
            return false;
        }

        if (string.Equals(Sha256Hex(leaf.RawData), want, StringComparison.Ordinal))
        {
            return true;
        }

        if (chain is null)
        {
            return false;
        }

        foreach (var element in chain.ChainElements)
        {
            if (string.Equals(Sha256Hex(element.Certificate.RawData), want, StringComparison.Ordinal))
            {
                return true;
            }
        }

        return false;
    }

    public static bool IsValidationFailure(Exception? error)
    {
        for (var current = error; current is not null; current = current.InnerException)
        {
            if (current is AuthenticationException)
            {
                return true;
            }

            var message = current.Message ?? "";
            if (message.Contains("certificate", StringComparison.OrdinalIgnoreCase) &&
                (message.Contains("invalid", StringComparison.OrdinalIgnoreCase) ||
                 message.Contains("untrusted", StringComparison.OrdinalIgnoreCase) ||
                 message.Contains("validation", StringComparison.OrdinalIgnoreCase)))
            {
                return true;
            }
        }

        return false;
    }

    public static bool BuildsWithPinnedRoot(
        string? pinnedFingerprint,
        string? caPem,
        X509Certificate2? leaf,
        X509Chain? presented = null)
    {
        var want = Normalize(pinnedFingerprint ?? "");
        if (want.Length == 0 || leaf is null || string.IsNullOrWhiteSpace(caPem))
        {
            return false;
        }

        X509Certificate2 root;
        try
        {
            root = X509Certificate2.CreateFromPem(caPem);
        }
        catch (Exception ex) when (ex is CryptographicException or ArgumentException)
        {
            return false;
        }

        using (root)
        {
            if (!string.Equals(Sha256Hex(root.RawData), want, StringComparison.Ordinal))
            {
                return false;
            }

            using var chain = new X509Chain();
            chain.ChainPolicy.RevocationMode = X509RevocationMode.NoCheck;
            chain.ChainPolicy.DisableCertificateDownloads = true;
            chain.ChainPolicy.TrustMode = X509ChainTrustMode.CustomRootTrust;
            chain.ChainPolicy.CustomTrustStore.Add(root);
            if (presented is not null)
            {
                foreach (var element in presented.ChainElements)
                {
                    var extra = element.Certificate;
                    if (SameCert(extra, leaf) || SameCert(extra, root))
                    {
                        continue;
                    }

                    chain.ChainPolicy.ExtraStore.Add(extra);
                }
            }

            return chain.Build(leaf);
        }
    }

    private static bool SameCert(X509Certificate2 left, X509Certificate2 right) =>
        string.Equals(left.Thumbprint, right.Thumbprint, StringComparison.OrdinalIgnoreCase);

    /// <summary>
    /// App-wide check. An empty pin never accepts a TLS error. This does not return true for every host.
    /// </summary>
    public static bool Validate(
        bool boxMode,
        string? boxHost,
        string? pinnedFingerprint,
        string? caPem,
        string? requestHost,
        X509Certificate2? cert,
        X509Chain? chain,
        SslPolicyErrors errors)
    {
        if (!boxMode)
        {
            return errors == SslPolicyErrors.None;
        }

        if (errors == SslPolicyErrors.None)
        {
            return true;
        }

        if (string.IsNullOrWhiteSpace(boxHost) ||
            !string.Equals(requestHost, boxHost, StringComparison.OrdinalIgnoreCase))
        {
            return false;
        }

        return PresentedMatches(pinnedFingerprint, cert, chain) ||
               BuildsWithPinnedRoot(pinnedFingerprint, caPem, cert, chain);
    }
}

public static class DpapiBoxSession
{
    private static readonly byte[] Entropy = Encoding.UTF8.GetBytes("Heirloom.BoxSession.v1");

    public static string SessionFile(string root) => Path.Combine(root, "box-session.bin");

    public static void Save(string path, string token)
    {
        if (!OperatingSystem.IsWindows())
        {
            throw new PlatformNotSupportedException("The box session token is stored with Windows DPAPI.");
        }

        var raw = Encoding.UTF8.GetBytes(token ?? "");
        var protectedBytes = ProtectedData.Protect(raw, Entropy, DataProtectionScope.CurrentUser);
        Directory.CreateDirectory(Path.GetDirectoryName(path) ?? ".");
        File.WriteAllBytes(path, protectedBytes);
    }

    public static string? TryRead(string path)
    {
        if (!OperatingSystem.IsWindows() || !File.Exists(path))
        {
            return null;
        }

        try
        {
            var protectedBytes = File.ReadAllBytes(path);
            var raw = ProtectedData.Unprotect(protectedBytes, Entropy, DataProtectionScope.CurrentUser);
            var token = Encoding.UTF8.GetString(raw).Trim();
            return token.Length == 0 ? null : token;
        }
        catch (CryptographicException)
        {
            return null;
        }
    }
}
