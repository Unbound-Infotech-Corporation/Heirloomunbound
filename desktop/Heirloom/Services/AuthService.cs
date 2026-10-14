using Heirloom.BoxCore;
using Windows.System;

namespace Heirloom.Services;

public sealed class AuthService
{
    private readonly SettingsStore _settings;
    private readonly CredentialStore _credentials;
    private readonly HeirloomApiClient _api;

    public AuthService(SettingsStore settings, CredentialStore credentials, HeirloomApiClient api)
    {
        _settings = settings;
        _credentials = credentials;
        _api = api;
    }

    public bool IsSignedIn => _credentials.HasDeviceToken || _credentials.HasSession;

    public async Task OpenSignInAsync()
    {
        var current = _settings.Current;
        var url = BoxLink.IsBoxClient(current.RunMode)
            ? BoxLink.WebHome(current.BoxUrl)
            : current.BackendUrl.TrimEnd('/') + "/login";
        await Launcher.LaunchUriAsync(new Uri(url));
    }

    public void LoadBoxSession()
    {
        if (!BoxLink.IsBoxClient(_settings.Current.RunMode))
        {
            return;
        }

        var token = DpapiBoxSession.TryRead(DpapiBoxSession.SessionFile(AppPaths.Root));
        if (!string.IsNullOrWhiteSpace(token))
        {
            _credentials.SessionToken = token;
        }
    }

    public void SetSessionToken(string token)
    {
        var value = token.Trim();
        _credentials.SessionToken = value;
        if (!BoxLink.IsBoxClient(_settings.Current.RunMode) || value.Length == 0)
        {
            return;
        }

        try
        {
            DpapiBoxSession.Save(DpapiBoxSession.SessionFile(AppPaths.Root), value);
        }
        catch (PlatformNotSupportedException)
        {
            // PasswordVault still holds the token on this Windows session.
        }
    }

    public async Task<string?> RegisterDeviceAsync(string name, CancellationToken cancellationToken = default)
    {
        var result = await _api.PostSessionAsync("/companion/register", new { name }, cancellationToken).ConfigureAwait(false);
        if (result is null)
        {
            return null;
        }

        if (result.Value.TryGetProperty("device_token", out var token))
        {
            var value = token.GetString();
            _credentials.DeviceToken = value;
            return value;
        }

        return null;
    }

    public void SetDeviceToken(string token) => _credentials.DeviceToken = token.Trim();

    public void SignOut() => _credentials.Clear();
}
