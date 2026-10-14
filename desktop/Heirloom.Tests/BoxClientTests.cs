using System.Net.Security;
using Xunit;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.Text.Json;
using Heirloom.BoxCore;

namespace Heirloom.Tests;

public class BoxClientTests
{
    [Theory]
    [InlineData(false, null, BoxLamp.Red)]
    [InlineData(true, """{"observer":{"paused":false,"signal":"signal","fps":12.5,"notes_today":3}}""", BoxLamp.Green)]
    [InlineData(true, """{"observer":{"paused":true,"signal":"signal","fps":12.5,"notes_today":1}}""", BoxLamp.Amber)]
    [InlineData(true, """{"observer":{"paused":false,"signal":"no-signal","fps":0,"notes_today":0}}""", BoxLamp.Amber)]
    [InlineData(true, """{"observer":{"paused":false,"signal":"paused","fps":0,"notes_today":0}}""", BoxLamp.Amber)]
    [InlineData(true, """{"status":"ok"}""", BoxLamp.Amber)]
    public void Lamp_follows_health(bool reachable, string? json, BoxLamp expected)
    {
        JsonElement? health = null;
        if (json is not null)
        {
            using var doc = JsonDocument.Parse(json);
            health = doc.RootElement.Clone();
        }

        Assert.Equal(expected, TrayStatus.LampFrom(reachable, health));
    }

    [Fact]
    public void Describe_names_people_cameras_and_gpu()
    {
        const string json = """
            {
              "observer": {"paused": false, "signal": "signal", "fps": 2, "notes_today": 4, "model": "qwen2.5vl"},
              "presence": {"present": [{"name": "Ada"}], "cameras": [{"name": "porch"}]},
              "compute": {"gpu": "RTX 3090", "model": "llama3.1"}
            }
            """;
        var snap = TrayStatus.Describe(true, 18, "https://192.168.0.111", json);
        Assert.Equal(BoxLamp.Green, snap.Lamp);
        Assert.Contains("18 ms", snap.Tooltip);
        Assert.Contains("Ada", snap.Tooltip);
        Assert.Contains("porch", snap.Tooltip);
        Assert.Contains("RTX 3090", snap.Tooltip);
        Assert.Contains("llama3.1", snap.Tooltip);
        Assert.Contains("4 notes today", snap.Tooltip);
        Assert.Equal("Pause Observer", TrayStatus.PauseVerb(snap.ObserverPaused));
    }

    [Fact]
    public void Unreachable_and_bad_json_are_red_and_amber()
    {
        var down = TrayStatus.Describe(false, null, "https://192.168.0.111", null);
        Assert.Equal(BoxLamp.Red, down.Lamp);
        Assert.Contains("did not answer", down.Tooltip);

        var odd = TrayStatus.Describe(true, 4, "https://192.168.0.111", "not-json");
        Assert.Equal(BoxLamp.Amber, odd.Lamp);
    }

    [Fact]
    public void Api_base_switches_with_run_mode()
    {
        Assert.Equal(
            "https://192.168.0.111",
            BoxLink.ApiBase(BoxLink.Box, "192.168.0.111", "https://voice-clone-hub-20.emergent.host"));
        Assert.Equal(
            "https://voice-clone-hub-20.emergent.host",
            BoxLink.ApiBase(BoxLink.Local, "https://192.168.0.111", "https://voice-clone-hub-20.emergent.host"));
        Assert.Equal("https://192.168.0.111", BoxLink.ApiBase(BoxLink.Box, "  ", null));
        Assert.False(BoxLink.StartsLocalModels(BoxLink.Box));
        Assert.True(BoxLink.StartsLocalModels(BoxLink.Local));
        Assert.True(BoxLink.TwinUsesRemoteApi(BoxLink.Box));
        Assert.False(BoxLink.AssistCloudFallback(BoxLink.Box));
        Assert.True(BoxLink.AssistCloudFallback(""));
        Assert.True(BoxLink.UsesOwnerSession(BoxLink.Box, "/api/desktop/chat"));
        Assert.False(BoxLink.UsesOwnerSession(BoxLink.Box, "/api/companion/poll"));
        Assert.False(BoxLink.UsesOwnerSession(BoxLink.Local, "/api/desktop/chat"));
        Assert.Equal("https://192.168.0.111/", BoxLink.WebHome("192.168.0.111"));
    }

    [Fact]
    public void Poll_backs_off_and_resets()
    {
        var once = PollSchedule.Next(PollSchedule.Healthy, ok: false);
        Assert.Equal(TimeSpan.FromSeconds(10), once);
        var capped = PollSchedule.Next(TimeSpan.FromSeconds(40), ok: false);
        Assert.Equal(PollSchedule.Max, capped);
        Assert.Equal(PollSchedule.Healthy, PollSchedule.Next(capped, ok: true));
    }

    [Fact]
    public void Pin_accepts_only_the_box_host()
    {
        using var cert = SelfSigned();
        var sha = CertificatePin.Sha256Hex(cert.RawData);
        var pem = cert.ExportCertificatePem();
        Assert.True(CertificatePin.PresentedMatches(sha, cert, null));
        Assert.True(CertificatePin.BuildsWithPinnedRoot(sha, pem, cert));
        Assert.False(CertificatePin.Validate(
            boxMode: false,
            boxHost: "192.168.0.111",
            pinnedFingerprint: sha,
            caPem: pem,
            requestHost: "192.168.0.111",
            cert: cert,
            chain: null,
            errors: SslPolicyErrors.RemoteCertificateChainErrors));
        Assert.True(CertificatePin.Validate(
            boxMode: true,
            boxHost: "192.168.0.111",
            pinnedFingerprint: sha,
            caPem: pem,
            requestHost: "192.168.0.111",
            cert: cert,
            chain: null,
            errors: SslPolicyErrors.RemoteCertificateChainErrors));
        Assert.False(CertificatePin.Validate(
            boxMode: true,
            boxHost: "192.168.0.111",
            pinnedFingerprint: sha,
            caPem: pem,
            requestHost: "evil.example",
            cert: cert,
            chain: null,
            errors: SslPolicyErrors.RemoteCertificateChainErrors));
        Assert.False(CertificatePin.Validate(
            boxMode: true,
            boxHost: "192.168.0.111",
            pinnedFingerprint: "",
            caPem: null,
            requestHost: "192.168.0.111",
            cert: cert,
            chain: null,
            errors: SslPolicyErrors.RemoteCertificateChainErrors));
    }

    [Fact]
    public void Settings_patch_keeps_other_keys()
    {
        var path = Path.Combine(Path.GetTempPath(), "heirloom-settings-" + Guid.NewGuid().ToString("n") + ".json");
        File.WriteAllText(path, """{"backend_url":"https://keep.example","session_volume":80}""");
        SettingsPatch.Write(path, new Dictionary<string, object?>
        {
            [SettingsPatch.BoxUrl] = "https://192.168.0.111",
            [SettingsPatch.CompanionToasts] = false,
        });
        var text = File.ReadAllText(path);
        Assert.Contains("keep.example", text);
        Assert.Contains("192.168.0.111", text);
        Assert.False(SettingsPatch.ReadBool(path, SettingsPatch.CompanionToasts, true));
        File.Delete(path);
    }

    [Fact]
    public void Dpapi_session_is_windows_only()
    {
        if (OperatingSystem.IsWindows())
        {
            return;
        }

        Assert.Throws<PlatformNotSupportedException>(() => DpapiBoxSession.Save(Path.GetTempFileName(), "token"));
    }

    private static X509Certificate2 SelfSigned()
    {
        using var rsa = RSA.Create(2048);
        var request = new CertificateRequest("CN=heirloom-box-test", rsa, HashAlgorithmName.SHA256, RSASignaturePadding.Pkcs1);
        return request.CreateSelfSigned(DateTimeOffset.UtcNow.AddDays(-1), DateTimeOffset.UtcNow.AddDays(2));
    }
}
