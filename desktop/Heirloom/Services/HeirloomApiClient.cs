using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;

namespace Heirloom.Services;

public sealed class HeirloomApiClient
{
    private readonly HttpClient _http;
    private readonly SettingsStore _settings;
    private readonly CredentialStore _credentials;

    public HeirloomApiClient(HttpClient http, SettingsStore settings, CredentialStore credentials)
    {
        _http = http;
        _settings = settings;
        _credentials = credentials;
    }

    public bool HasDeviceToken => !string.IsNullOrWhiteSpace(_credentials.DeviceToken);
    public bool HasSession => !string.IsNullOrWhiteSpace(_credentials.SessionToken);
    public string LastFailure { get; private set; } = "";

    public Task<JsonElement?> GetAsync(string path, CancellationToken cancellationToken = default) =>
        SendAsync(HttpMethod.Get, path, null, useDevice: true, cancellationToken);

    public Task<JsonElement?> PostAsync(string path, object? body, CancellationToken cancellationToken = default) =>
        SendAsync(HttpMethod.Post, path, body, useDevice: true, cancellationToken);

    public Task<JsonElement?> PutAsync(string path, object? body, CancellationToken cancellationToken = default) =>
        SendAsync(HttpMethod.Put, path, body, useDevice: true, cancellationToken);

    public Task<JsonElement?> DeleteAsync(string path, CancellationToken cancellationToken = default) =>
        SendAsync(HttpMethod.Delete, path, null, useDevice: true, cancellationToken);

    public Task<JsonElement?> GetSessionAsync(string path, CancellationToken cancellationToken = default) =>
        SendAsync(HttpMethod.Get, path, null, useDevice: false, cancellationToken);

    public Task<JsonElement?> PostSessionAsync(string path, object? body, CancellationToken cancellationToken = default) =>
        SendAsync(HttpMethod.Post, path, body, useDevice: false, cancellationToken);

    public async Task<JsonElement?> PostMultipartAsync(string path, string fileName, byte[] bytes, string fieldName = "audio", CancellationToken cancellationToken = default)
    {
        using var content = new MultipartFormDataContent();
        var file = new ByteArrayContent(bytes);
        file.Headers.ContentType = new MediaTypeHeaderValue("audio/wav");
        content.Add(file, fieldName, fileName);
        return await SendContentAsync(HttpMethod.Post, path, content, useDevice: true, cancellationToken).ConfigureAwait(false);
    }

    public async Task<JsonElement?> PostScreenshotAsync(string cmdId, byte[] jpeg, CancellationToken cancellationToken = default)
    {
        using var content = new MultipartFormDataContent();
        content.Add(new StringContent(cmdId), "cmd_id");
        var file = new ByteArrayContent(jpeg);
        file.Headers.ContentType = new MediaTypeHeaderValue("image/jpeg");
        content.Add(file, "file", "screen.jpg");
        return await SendContentAsync(HttpMethod.Post, "/companion/screenshot", content, useDevice: true, cancellationToken).ConfigureAwait(false);
    }

    public async Task<byte[]?> PostForBytesAsync(string path, object? body, CancellationToken cancellationToken = default)
    {
        var baseUrl = _settings.Current.BackendUrl.TrimEnd('/');
        if (!path.StartsWith('/'))
        {
            path = "/" + path;
        }

        if (!path.StartsWith("/api", StringComparison.Ordinal))
        {
            path = "/api" + path;
        }

        using var request = new HttpRequestMessage(HttpMethod.Post, baseUrl + path);
        var token = _credentials.DeviceToken;
        if (!string.IsNullOrWhiteSpace(token))
        {
            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token);
        }

        if (body is not null)
        {
            request.Content = new StringContent(JsonSerializer.Serialize(body), Encoding.UTF8, "application/json");
        }

        try
        {
            using var response = await _http.SendAsync(request, cancellationToken).ConfigureAwait(false);
            if (!response.IsSuccessStatusCode)
            {
                LastFailure = "Cloud HTTP " + (int)response.StatusCode + " (binary).";
                return null;
            }

            LastFailure = "";
            return await response.Content.ReadAsByteArrayAsync(cancellationToken).ConfigureAwait(false);
        }
        catch (OperationCanceledException)
        {
            LastFailure = "Cloud request timed out.";
            return null;
        }
        catch (Exception ex)
        {
            LastFailure = "Cloud unreachable: " + ex.Message;
            return null;
        }
    }

    private async Task<JsonElement?> SendAsync(HttpMethod method, string path, object? body, bool useDevice, CancellationToken cancellationToken)
    {
        HttpContent? content = null;
        if (body is not null)
        {
            content = new StringContent(JsonSerializer.Serialize(body), Encoding.UTF8, "application/json");
        }

        return await SendContentAsync(method, path, content, useDevice, cancellationToken).ConfigureAwait(false);
    }

    private async Task<JsonElement?> SendContentAsync(HttpMethod method, string path, HttpContent? content, bool useDevice, CancellationToken cancellationToken)
    {
        var baseUrl = _settings.Current.BackendUrl.TrimEnd('/');
        if (!path.StartsWith('/'))
        {
            path = "/" + path;
        }

        if (!path.StartsWith("/api", StringComparison.Ordinal))
        {
            path = "/api" + path;
        }

        using var request = new HttpRequestMessage(method, baseUrl + path);
        var token = useDevice ? _credentials.DeviceToken : _credentials.SessionToken;
        if (!string.IsNullOrWhiteSpace(token))
        {
            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token);
        }

        request.Headers.Accept.Add(new MediaTypeWithQualityHeaderValue("application/json"));
        request.Content = content;

        try
        {
            using var response = await _http.SendAsync(request, cancellationToken).ConfigureAwait(false);
            var text = await response.Content.ReadAsStringAsync(cancellationToken).ConfigureAwait(false);
            if (!response.IsSuccessStatusCode || string.IsNullOrWhiteSpace(text))
            {
                LastFailure = string.IsNullOrWhiteSpace(text)
                    ? "Cloud HTTP " + (int)response.StatusCode + " with an empty body."
                    : "Cloud HTTP " + (int)response.StatusCode + ": " + Trim(text, 180);
                return null;
            }

            LastFailure = "";
            using var doc = JsonDocument.Parse(text);
            return doc.RootElement.Clone();
        }
        catch (OperationCanceledException)
        {
            LastFailure = "Cloud request timed out.";
            return null;
        }
        catch (Exception ex)
        {
            LastFailure = "Cloud unreachable: " + ex.Message;
            return null;
        }
    }

    private static string Trim(string text, int max) =>
        text.Length <= max ? text : text[..max] + "…";
}
