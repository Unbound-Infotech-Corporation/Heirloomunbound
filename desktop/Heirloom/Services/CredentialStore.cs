using Heirloom.BoxCore;
using Windows.Security.Credentials;

namespace Heirloom.Services;

public sealed class CredentialStore
{
    private const string Resource = "UnboundInfotech.Heirloom";

    public string? SessionToken
    {
        get => Read("session");
        set => Write("session", value);
    }

    public string? DeviceToken
    {
        get => Read("device");
        set => Write("device", value);
    }

    public bool HasDeviceToken => !string.IsNullOrWhiteSpace(DeviceToken);
    public bool HasSession => !string.IsNullOrWhiteSpace(SessionToken);

    public void Clear()
    {
        Write("session", null);
        Write("device", null);
    }

    /// <summary>
    /// Credential Locker entry for a BYO API key. The name is one of
    /// <see cref="ByoKeyFile.Names"/>. The password is not written to settings.json.
    /// </summary>
    public void SaveByoKey(string name, string? secret)
    {
        ByoKeyFile.RequireKnown(name);
        Write("byo-" + name, secret);
    }

    public string? ReadByoKey(string name)
    {
        ByoKeyFile.RequireKnown(name);
        return Read("byo-" + name);
    }

    private static string? Read(string name)
    {
        try
        {
            var vault = new PasswordVault();
            var cred = vault.Retrieve(Resource, name);
            cred.RetrievePassword();
            return string.IsNullOrWhiteSpace(cred.Password) ? null : cred.Password;
        }
        catch
        {
            return null;
        }
    }

    private static void Write(string name, string? value)
    {
        var vault = new PasswordVault();
        try
        {
            var existing = vault.Retrieve(Resource, name);
            vault.Remove(existing);
        }
        catch
        {
            // none stored
        }

        if (string.IsNullOrWhiteSpace(value))
        {
            return;
        }

        vault.Add(new PasswordCredential(Resource, name, value));
    }
}
