using Heirloom.BoxCore;
using Windows.System;

namespace Heirloom.Services;

public sealed class AuthService
{
    private readonly SettingsStore _settings;
    private readonly CredentialStore _credentials;
    private readonly HeirloomApiClient _api;
    private BoxSessionBundle _bundle = new("", "", "");

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

        var bundle = DpapiBoxSession.TryReadBundle(DpapiBoxSession.SessionFile(AppPaths.Root));
        if (bundle is null || string.IsNullOrWhiteSpace(bundle.Session))
        {
            return;
        }

        _bundle = bundle;
        _credentials.SessionToken = bundle.Session;
    }

    public void Remember(BoxSessionBundle bundle)
    {
        _bundle = bundle;
        _credentials.SessionToken = bundle.Session ?? "";
        if (!BoxLink.IsBoxClient(_settings.Current.RunMode) || string.IsNullOrWhiteSpace(bundle.Session))
        {
            return;
        }

        try
        {
            DpapiBoxSession.SaveBundle(DpapiBoxSession.SessionFile(AppPaths.Root), bundle);
        }
        catch (PlatformNotSupportedException)
        {
            // PasswordVault still holds the access token on this Windows session.
        }
    }

    public void SetSessionToken(string token)
    {
        Remember(new BoxSessionBundle(token.Trim(), _bundle.Refresh, _bundle.ExpiresAt));
    }

    public async Task EnsureFreshAsync(CancellationToken cancellationToken = default)
    {
        if (!BoxLink.IsBoxClient(_settings.Current.RunMode))
        {
            return;
        }

        PullDisk();
        if (string.IsNullOrWhiteSpace(_credentials.SessionToken) && string.IsNullOrWhiteSpace(_bundle.Session))
        {
            return;
        }

        var expires = SessionClock.Parse(_bundle.ExpiresAt);
        if (_bundle.HasRefresh && expires is null)
        {
            expires = await ReadExpiryAsync(cancellationToken).ConfigureAwait(false);
            if (expires is null && TwinFailure.IsSessionExpired(_api.LastFailure))
            {
                await TryRenewAsync(cancellationToken).ConfigureAwait(false);
                return;
            }

            if (expires is not null)
            {
                _bundle = _bundle with { ExpiresAt = expires.Value.ToString("o") };
                TrySaveBundle();
            }
        }

        if (!SessionClock.ShouldRenew(expires, DateTimeOffset.UtcNow, _bundle.HasRefresh))
        {
            return;
        }

        await TryRenewAsync(cancellationToken).ConfigureAwait(false);
    }

    public async Task<bool> TryRenewAsync(CancellationToken cancellationToken = default)
    {
        if (!BoxLink.IsBoxClient(_settings.Current.RunMode))
        {
            return false;
        }

        PullDisk();
        var session = string.IsNullOrWhiteSpace(_bundle.Session) ? _credentials.SessionToken : _bundle.Session;
        if (string.IsNullOrWhiteSpace(session) && !_bundle.HasRefresh)
        {
            return false;
        }

        var result = await _api.PostSessionAsync(
            "/auth/refresh",
            new { refresh_token = _bundle.Refresh ?? "" },
            cancellationToken).ConfigureAwait(false);
        if (result is null)
        {
            var before = session;
            PullDisk();
            return !string.IsNullOrWhiteSpace(_credentials.SessionToken)
                && !string.Equals(_credentials.SessionToken, before, StringComparison.Ordinal);
        }

        var next = BoxSessionBundle.FromApi(result.Value);
        if (next is null)
        {
            return false;
        }

        Remember(next);
        return true;
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

    public void SignOut()
    {
        _bundle = new BoxSessionBundle("", "", "");
        _credentials.Clear();
    }

    private async Task<DateTimeOffset?> ReadExpiryAsync(CancellationToken cancellationToken)
    {
        var me = await _api.GetSessionAsync("/auth/me", cancellationToken).ConfigureAwait(false);
        return me is { } body ? SessionClock.ReadExpiry(body) : null;
    }

    private void PullDisk()
    {
        if (!BoxLink.IsBoxClient(_settings.Current.RunMode))
        {
            return;
        }

        BoxSessionBundle? disk;
        try
        {
            disk = DpapiBoxSession.TryReadBundle(DpapiBoxSession.SessionFile(AppPaths.Root));
        }
        catch (PlatformNotSupportedException)
        {
            return;
        }

        if (disk is null || string.IsNullOrWhiteSpace(disk.Session))
        {
            return;
        }

        _bundle = disk;
        _credentials.SessionToken = disk.Session;
    }

    private void TrySaveBundle()
    {
        if (!BoxLink.IsBoxClient(_settings.Current.RunMode) || string.IsNullOrWhiteSpace(_bundle.Session))
        {
            return;
        }

        try
        {
            DpapiBoxSession.SaveBundle(DpapiBoxSession.SessionFile(AppPaths.Root), _bundle);
        }
        catch (PlatformNotSupportedException)
        {
        }
    }
}
