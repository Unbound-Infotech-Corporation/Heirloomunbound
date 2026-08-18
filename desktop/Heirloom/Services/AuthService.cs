using System.Diagnostics;
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
        var url = _settings.Current.BackendUrl.TrimEnd('/') + "/login";
        await Launcher.LaunchUriAsync(new Uri(url));
    }

    public void SetSessionToken(string token) => _credentials.SessionToken = token.Trim();

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
