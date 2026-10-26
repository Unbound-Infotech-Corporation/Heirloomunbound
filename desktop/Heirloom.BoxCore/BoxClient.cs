using System.Diagnostics;
using System.Net.Http.Headers;
using System.Net.Security;
using System.Net.Sockets;
using System.Security.Cryptography.X509Certificates;
using System.Text;
using System.Text.Json;

namespace Heirloom.BoxCore;

public sealed record HealthProbe(bool Reachable, int? LatencyMs, string? Body, string? Failure = null);

public sealed record TrustOffer(string Host, string LeafSha256, string PinSha256, string? CaPem);

public static class BoxClient
{
    public static async Task<string> ProbeLeafAsync(string baseUrl, CancellationToken cancellationToken = default)
    {
        var uri = new Uri(BoxLink.Normalize(baseUrl));
        var port = uri.Port > 0 ? uri.Port : 443;
        using var tcp = new TcpClient();
        await tcp.ConnectAsync(uri.Host, port, cancellationToken).ConfigureAwait(false);
        X509Certificate2? captured = null;
        using var ssl = new SslStream(tcp.GetStream(), false, (_, certificate, _, _) =>
        {
            // This callback returns true only so the probe can read the certificate.
            // App traffic uses CertificatePin.Validate and never accepts an unpinned error.
            if (certificate is not null)
            {
                captured = new X509Certificate2(certificate);
            }

            return true;
        });
        await ssl.AuthenticateAsClientAsync(new SslClientAuthenticationOptions
        {
            TargetHost = uri.Host,
        }, cancellationToken).ConfigureAwait(false);
        if (captured is null)
        {
            throw new InvalidOperationException("The box did not present a certificate.");
        }

        using (captured)
        {
            return CertificatePin.Sha256Hex(captured.RawData);
        }
    }

    public static async Task<TrustOffer> OfferTrustAsync(string baseUrl, CancellationToken cancellationToken = default)
    {
        var uri = new Uri(BoxLink.Normalize(baseUrl));
        var leaf = await ProbeLeafAsync(baseUrl, cancellationToken).ConfigureAwait(false);
        string? pem = null;
        try
        {
            using var http = Create(baseUrl, leaf, null, TimeSpan.FromSeconds(15));
            using var response = await http.GetAsync(new Uri(uri, "/api/box/ca"), cancellationToken).ConfigureAwait(false);
            if (response.IsSuccessStatusCode)
            {
                var text = await response.Content.ReadAsStringAsync(cancellationToken).ConfigureAwait(false);
                if (text.Contains("BEGIN CERTIFICATE", StringComparison.Ordinal))
                {
                    pem = text;
                }
            }
        }
        catch (HttpRequestException)
        {
            pem = null;
        }

        var pin = leaf;
        if (!string.IsNullOrWhiteSpace(pem))
        {
            try
            {
                using var root = X509Certificate2.CreateFromPem(pem);
                pin = CertificatePin.Sha256Hex(root.RawData);
            }
            catch (Exception ex) when (ex is System.Security.Cryptography.CryptographicException or ArgumentException)
            {
                pem = null;
                pin = leaf;
            }
        }

        return new TrustOffer(uri.Host, leaf, pin, pem);
    }

    public static async Task<string?> LoginAsync(
        string baseUrl,
        string email,
        string password,
        string pin,
        string? caPem,
        CancellationToken cancellationToken = default)
    {
        using var http = Create(baseUrl, pin, caPem, TimeSpan.FromSeconds(20));
        var payload = JsonSerializer.Serialize(new { email, password });
        using var content = new StringContent(payload, Encoding.UTF8, "application/json");
        using var response = await http.PostAsync(Api(baseUrl, "/api/auth/box-login"), content, cancellationToken).ConfigureAwait(false);
        var text = await response.Content.ReadAsStringAsync(cancellationToken).ConfigureAwait(false);
        if (!response.IsSuccessStatusCode || string.IsNullOrWhiteSpace(text))
        {
            return null;
        }

        using var doc = JsonDocument.Parse(text);
        if (!doc.RootElement.TryGetProperty("session_token", out var token))
        {
            return null;
        }

        var value = token.GetString();
        return string.IsNullOrWhiteSpace(value) ? null : value.Trim();
    }

    public static async Task<HealthProbe> HealthAsync(
        string baseUrl,
        string? pin,
        string? caPem,
        CancellationToken cancellationToken = default)
    {
        var clock = Stopwatch.StartNew();
        try
        {
            using var http = Create(baseUrl, pin, caPem, TimeSpan.FromSeconds(8));
            using var response = await http.GetAsync(Api(baseUrl, "/api/health"), cancellationToken).ConfigureAwait(false);
            clock.Stop();
            var text = await response.Content.ReadAsStringAsync(cancellationToken).ConfigureAwait(false);
            if (!response.IsSuccessStatusCode || string.IsNullOrWhiteSpace(text))
            {
                return new HealthProbe(false, (int)clock.ElapsedMilliseconds, null);
            }

            return new HealthProbe(true, (int)clock.ElapsedMilliseconds, text);
        }
        catch (Exception ex) when (ex is HttpRequestException or TaskCanceledException or InvalidOperationException or UriFormatException)
        {
            clock.Stop();
            var failure = CertificatePin.IsValidationFailure(ex) ? CertificatePin.CheckFailed : null;
            return new HealthProbe(false, null, null, failure);
        }
    }

    public static async Task<bool> SetObserverPausedAsync(
        string baseUrl,
        string? pin,
        string? caPem,
        string sessionToken,
        bool paused,
        CancellationToken cancellationToken = default)
    {
        if (string.IsNullOrWhiteSpace(sessionToken))
        {
            return false;
        }

        using var http = Create(baseUrl, pin, caPem, TimeSpan.FromSeconds(15));
        using var request = new HttpRequestMessage(HttpMethod.Post, Api(baseUrl, paused ? "/api/observer/pause" : "/api/observer/resume"));
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", sessionToken.Trim());
        request.Content = new StringContent("{}", Encoding.UTF8, "application/json");
        using var response = await http.SendAsync(request, cancellationToken).ConfigureAwait(false);
        return response.IsSuccessStatusCode;
    }

    public static async Task<bool> SetAudioStreamAsync(
        string baseUrl,
        string? pin,
        string? caPem,
        string sessionToken,
        string source,
        bool enabled,
        CancellationToken cancellationToken = default)
    {
        if (string.IsNullOrWhiteSpace(sessionToken))
        {
            return false;
        }

        var payload = source == "mic"
            ? JsonSerializer.Serialize(new { mic = enabled })
            : JsonSerializer.Serialize(new { system = enabled });
        using var http = Create(baseUrl, pin, caPem, TimeSpan.FromSeconds(15));
        using var request = new HttpRequestMessage(HttpMethod.Put, Api(baseUrl, "/api/observer/audio"));
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", sessionToken.Trim());
        request.Content = new StringContent(payload, Encoding.UTF8, "application/json");
        using var response = await http.SendAsync(request, cancellationToken).ConfigureAwait(false);
        return response.IsSuccessStatusCode;
    }

    public static async Task<string?> GetAssistLiveAsync(
        string baseUrl,
        string? pin,
        string? caPem,
        string sessionToken,
        CancellationToken cancellationToken = default)
    {
        if (string.IsNullOrWhiteSpace(sessionToken))
        {
            return null;
        }

        using var http = Create(baseUrl, pin, caPem, TimeSpan.FromSeconds(20));
        using var request = new HttpRequestMessage(HttpMethod.Get, Api(baseUrl, "/api/assist/live"));
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", sessionToken.Trim());
        using var response = await http.SendAsync(request, cancellationToken).ConfigureAwait(false);
        if (!response.IsSuccessStatusCode)
        {
            return null;
        }

        return await response.Content.ReadAsStringAsync(cancellationToken).ConfigureAwait(false);
    }

    public static Task<bool> PutAssistSettingsAsync(
        string baseUrl,
        string? pin,
        string? caPem,
        string sessionToken,
        string json,
        CancellationToken cancellationToken = default) =>
        PostAssistAsync(baseUrl, pin, caPem, sessionToken, "/api/assist/live/settings", json, HttpMethod.Put, cancellationToken);

    public static async Task<bool> PostAssistAsync(
        string baseUrl,
        string? pin,
        string? caPem,
        string sessionToken,
        string path,
        string json,
        HttpMethod? method = null,
        CancellationToken cancellationToken = default)
    {
        if (string.IsNullOrWhiteSpace(sessionToken))
        {
            return false;
        }

        using var http = Create(baseUrl, pin, caPem, TimeSpan.FromSeconds(20));
        using var request = new HttpRequestMessage(method ?? HttpMethod.Post, Api(baseUrl, path));
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", sessionToken.Trim());
        request.Content = new StringContent(json, Encoding.UTF8, "application/json");
        using var response = await http.SendAsync(request, cancellationToken).ConfigureAwait(false);
        return response.IsSuccessStatusCode;
    }

    public static async Task<byte[]?> GetAssistAudioAsync(
        string baseUrl,
        string? pin,
        string? caPem,
        string sessionToken,
        string audioId,
        CancellationToken cancellationToken = default)
    {
        if (string.IsNullOrWhiteSpace(sessionToken) || string.IsNullOrWhiteSpace(audioId))
        {
            return null;
        }

        using var http = Create(baseUrl, pin, caPem, TimeSpan.FromSeconds(20));
        using var request = new HttpRequestMessage(HttpMethod.Get, Api(baseUrl, "/api/assist/live/audio/" + Uri.EscapeDataString(audioId)));
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", sessionToken.Trim());
        using var response = await http.SendAsync(request, cancellationToken).ConfigureAwait(false);
        if (!response.IsSuccessStatusCode)
        {
            return null;
        }

        return await response.Content.ReadAsByteArrayAsync(cancellationToken).ConfigureAwait(false);
    }

    public static async Task<bool> PostAudioAsync(
        string baseUrl,
        string? pin,
        string? caPem,
        string sessionToken,
        string source,
        byte[] pcm,
        CancellationToken cancellationToken = default)
    {
        if (string.IsNullOrWhiteSpace(sessionToken) || pcm.Length == 0)
        {
            return false;
        }

        if (source is not ("system" or "mic"))
        {
            return false;
        }

        using var http = Create(baseUrl, pin, caPem, TimeSpan.FromSeconds(15));
        using var request = new HttpRequestMessage(HttpMethod.Post, Api(baseUrl, "/api/observer/audio/" + source));
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", sessionToken.Trim());
        request.Headers.TryAddWithoutValidation("X-Heirloom-Sample-Rate", PcmConvert.TargetRate.ToString(System.Globalization.CultureInfo.InvariantCulture));
        request.Content = new ByteArrayContent(pcm);
        request.Content.Headers.ContentType = new MediaTypeHeaderValue("application/octet-stream");
        using var response = await http.SendAsync(request, cancellationToken).ConfigureAwait(false);
        return response.IsSuccessStatusCode;
    }

    public static HttpClient Create(string baseUrl, string? pin, string? caPem, TimeSpan timeout)
    {
        var host = new Uri(BoxLink.Normalize(baseUrl)).Host;
        var handler = new HttpClientHandler
        {
            ServerCertificateCustomValidationCallback = (message, cert, chain, errors) =>
            {
                X509Certificate2? leaf = cert is null ? null : new X509Certificate2(cert);
                try
                {
                    return CertificatePin.Validate(
                        boxMode: true,
                        boxHost: host,
                        pinnedFingerprint: pin,
                        caPem: caPem,
                        requestHost: message.RequestUri?.Host,
                        cert: leaf,
                        chain: chain,
                        errors: errors);
                }
                finally
                {
                    leaf?.Dispose();
                }
            },
        };
        return new HttpClient(handler, disposeHandler: true) { Timeout = timeout };
    }

    private static Uri Api(string baseUrl, string path) => new(new Uri(BoxLink.Normalize(baseUrl) + "/"), path.TrimStart('/'));
}
