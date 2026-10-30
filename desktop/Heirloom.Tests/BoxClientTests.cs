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
    [InlineData(true, """{"observer":{"paused":false,"signal":"ok","fps":2,"source":"network","notes_today":1}}""", BoxLamp.Green)]
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
        Assert.Equal("System audio: off", TrayStatus.StreamLine("System audio", snap.SystemAudio));
    }

    [Fact]
    public void Screen_scales_a_5120_monitor_and_stays_quiet_while_paused()
    {
        Assert.Equal((1920, 540), ScreenStream.ScaledSize(5120, 1440));
        Assert.Equal((1920, 1080), ScreenStream.ScaledSize(1920, 1080));
        Assert.Equal((1280, 720), ScreenStream.ScaledSize(1280, 720));
        Assert.Equal(TimeSpan.FromMilliseconds(500), ScreenStream.Interval(2));
        Assert.Equal(2d, ScreenStream.SendFps(0, ""));
        Assert.Equal(2d, ScreenStream.SendFps(8, "signal"));
        Assert.Equal(1d, ScreenStream.SendFps(1, "ok"));
        Assert.False(ScreenStream.MaySend(observerPaused: true, enabled: true, reachable: true));
        Assert.False(ScreenStream.MaySend(observerPaused: false, enabled: false, reachable: true));
        Assert.False(ScreenStream.MaySend(observerPaused: false, enabled: true, reachable: false));
        Assert.False(ScreenStream.MaySend(observerPaused: false, enabled: true, reachable: true, mode: "capture"));
        Assert.True(ScreenStream.MaySend(observerPaused: false, enabled: true, reachable: true));
        Assert.True(ScreenStream.MaySend(observerPaused: false, enabled: true, reachable: true, mode: "auto"));
        Assert.True(ScreenStream.MaySend(observerPaused: false, enabled: true, reachable: true, mode: "network"));

        const string json = """
            {"observer":{"paused":false,"signal":"ok","source":"network","mode":"auto","fps":2,"notes_today":1}}
            """;
        var snap = TrayStatus.Describe(true, 9, "https://192.168.0.111", json);
        Assert.Equal(BoxLamp.Green, snap.Lamp);
        Assert.Equal(2d, snap.ObserverFps);
        Assert.Equal("ok", snap.ObserverSignal);
        Assert.Equal("auto", snap.ObserverMode);
        Assert.Contains("network", snap.Tooltip);
        Assert.True(ScreenStream.MaySend(snap.ObserverPaused, enabled: true, snap.Reachable, snap.ObserverMode));
    }

    [Fact]
    public void Audio_lines_name_each_stream_and_the_pc_sends_only_the_fallback()
    {
        const string json = """
            {
              "observer": {
                "paused": false,
                "signal": "signal",
                "fps": 2,
                "notes_today": 1,
                "audio": {
                  "system": {"enabled": true, "source": "xr1", "status": "hearing", "device": "EVGA XR1 Lite"},
                  "mic": {"enabled": true, "source": "waiting", "status": "waiting", "device": ""}
                }
              }
            }
            """;
        var snap = TrayStatus.Describe(true, 12, "https://192.168.0.111", json);
        Assert.Contains("System audio: hearing · EVGA XR1 Lite", snap.Tooltip);
        Assert.Contains("Microphone: waiting", snap.Tooltip);
        Assert.False(TrayStatus.CompanionShouldSend(snap.SystemAudio));
        Assert.True(TrayStatus.CompanionShouldSend(snap.MicAudio));
        Assert.False(AssistLive.MaySend(observerPaused: true, snap.MicAudio));
        Assert.True(AssistLive.MaySend(observerPaused: false, snap.MicAudio));
        var tone = new byte[] { 0, 0, 0x10, 0x3e, 0, 0, 0x10, 0xbe };
        var pcm = PcmConvert.ToS16Mono16k(tone, channels: 2, sampleRate: 16000, ieeeFloat: true);
        Assert.NotEmpty(pcm);
        Assert.Equal(0, pcm.Length % 2);
        Assert.True(PcmConvert.IsIeeeFloat(PcmConvert.WaveFormatIeeeFloat, Guid.Empty));
        Assert.True(PcmConvert.IsIeeeFloat(PcmConvert.WaveFormatExtensible, PcmConvert.IeeeFloatSubFormat));
        Assert.False(PcmConvert.IsIeeeFloat(PcmConvert.WaveFormatExtensible, PcmConvert.PcmSubFormat));
        Assert.False(PcmConvert.IsIeeeFloat(1, Guid.Empty));
        var run = 0;
        Assert.False(PcmSilence.ShouldDrop(new byte[] { 0, 1 }, ref run, out var sustained));
        Assert.False(sustained);
        Assert.Equal(0, run);
        Assert.True(PcmSilence.ShouldDrop(new byte[PcmSilence.SustainBytes - 2], ref run, out sustained));
        Assert.False(sustained);
        Assert.True(PcmSilence.ShouldDrop(new byte[] { 0, 0 }, ref run, out sustained));
        Assert.True(sustained);
        Assert.Equal(PcmSilence.SilentMicStatus, "mic is silent, pick another microphone");
        Assert.Equal("", MicSelection.Resolve(" ", new[] { "{0.0.1.00000000}.{gone}" }));
        Assert.Equal("{0.0.1.00000000}.{mic}", MicSelection.Resolve("{0.0.1.00000000}.{mic}", new[] { "{0.0.1.00000000}.{mic}" }));
        Assert.Equal("", MicSelection.Resolve("{0.0.1.00000000}.{gone}", new[] { "{0.0.1.00000000}.{mic}" }));
    }

    [Fact]
    public void Assist_poll_names_the_caption_and_the_waiting_action()
    {
        const string json = """
            {
              "listening": true,
              "caption": "Say yes to open Notepad.",
              "caption_id": "cap_1",
              "pending": {"id": "act_1", "label": "Open notepad", "explicit": false},
              "receipt": {"status": "waiting_confirm", "summary": "Waiting for yes — Open notepad."},
              "muted": false,
              "proactive": false,
              "wake_phrase": "hey C L",
              "has_audio": true,
              "audio_id": "cap_1"
            }
            """;
        var view = AssistLive.Parse(json);
        Assert.True(view.Listening);
        Assert.Equal("Say yes to open Notepad.", view.Caption);
        Assert.Equal("act_1", view.PendingId);
        Assert.Equal("Open notepad", view.PendingLabel);
        Assert.False(view.ExplicitConfirm);
        Assert.Equal("hey C L", view.WakePhrase);
        Assert.True(view.HasAudio);
        Assert.Equal("Waiting for yes — Open notepad.", view.ReceiptSummary);
        Assert.Equal(AssistLive.DefaultChord, "Ctrl+Shift+Space");
        Assert.Equal(8, AssistLive.PttWindowSeconds);
        Assert.Equal("", AssistLive.Parse("not-json").Caption);
        Assert.Contains("Waiting for yes — Open notepad.", view.Receipts);
    }

    [Fact]
    public void Twin_live_shows_mic_words_and_keeps_them_while_paused()
    {
        const string json = """
            {
              "listening": true,
              "paused": false,
              "lines": [
                {"id": "a", "text": "hey C L open the notes", "ts": "t1"}
              ]
            }
            """;
        var mic = MicTranscript.Parse(json);
        Assert.NotNull(mic);
        Assert.True(mic!.Listening);
        Assert.Equal("hey C L open the notes", mic.Lines[0].Text);
        Assert.Null(MicTranscript.Parse("not-json"));

        var assist = AssistLive.Parse("""
            {
              "listening": true,
              "caption": "Say yes to open Notepad.",
              "caption_id": "cap_1",
              "pending": {"id": "act_1", "label": "Open notepad", "explicit": false}
            }
            """);
        var frame = TwinLiveBoard.Next(TwinLiveFrame.Empty, mic.Listening, mic.Lines, assist.Caption, assist.CaptionId, assist.PendingId);
        Assert.Equal("Listening", frame.Status);
        Assert.Equal(TwinLiveBoard.You, frame.Lines[0].Who);
        Assert.Equal("hey C L open the notes", frame.Lines[0].Text);
        Assert.Equal(TwinLiveBoard.Twin, frame.Lines[1].Who);
        Assert.True(frame.CanAnswer);

        var again = TwinLiveBoard.Next(frame, true, mic.Lines, assist.Caption, assist.CaptionId, assist.PendingId);
        Assert.Equal(2, again.Lines.Count);

        var pausedMic = MicTranscript.Parse("""{"listening": false, "paused": true, "lines": []}""");
        Assert.NotNull(pausedMic);
        Assert.False(pausedMic!.Listening);
        var paused = TwinLiveBoard.Next(again, pausedMic.Listening, pausedMic.Lines, assist.Caption, assist.CaptionId, assist.PendingId);
        Assert.Equal("Paused", paused.Status);
        Assert.False(paused.CanAnswer);
        Assert.Equal(TwinLiveBoard.You, paused.Lines[0].Who);
        Assert.Equal("hey C L open the notes", paused.Lines[0].Text);
    }

    [Fact]
    public void Unreachable_and_bad_json_are_red_and_amber()
    {
        var down = TrayStatus.Describe(false, null, "https://192.168.0.111", null);
        Assert.Equal(BoxLamp.Red, down.Lamp);
        Assert.Contains("did not answer", down.Tooltip);
        Assert.False(down.CertificateFailed);

        var rejected = TrayStatus.Describe(false, null, "https://192.168.0.111", null, CertificatePin.CheckFailed);
        Assert.Equal(BoxLamp.Red, rejected.Lamp);
        Assert.True(rejected.CertificateFailed);
        Assert.Contains(CertificatePin.CheckFailed, rejected.Tooltip);
        Assert.DoesNotContain("did not answer", rejected.Tooltip);

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
    public void Pinned_root_accepts_a_leaf_through_the_presented_intermediate()
    {
        using var rootKey = RSA.Create(2048);
        using var intermediateKey = RSA.Create(2048);
        using var leafKey = RSA.Create(2048);
        using var root = Issue("heirloom-box-root", rootKey, issuer: null, ca: true);
        using var intermediate = Issue("heirloom-box-intermediate", intermediateKey, root, ca: true);
        using var leaf = Issue("heirloom-box-leaf", leafKey, intermediate, ca: false);
        var rootSha = CertificatePin.Sha256Hex(root.RawData);
        var rootPem = root.ExportCertificatePem();

        using var presented = new X509Chain();
        presented.ChainPolicy.RevocationMode = X509RevocationMode.NoCheck;
        presented.ChainPolicy.DisableCertificateDownloads = true;
        presented.ChainPolicy.TrustMode = X509ChainTrustMode.CustomRootTrust;
        presented.ChainPolicy.CustomTrustStore.Add(root);
        presented.ChainPolicy.ExtraStore.Add(intermediate);
        Assert.True(presented.Build(leaf));
        Assert.Contains(presented.ChainElements, element => element.Certificate.Thumbprint == intermediate.Thumbprint);

        Assert.False(CertificatePin.BuildsWithPinnedRoot(rootSha, rootPem, leaf));
        Assert.True(CertificatePin.BuildsWithPinnedRoot(rootSha, rootPem, leaf, presented));
        Assert.False(CertificatePin.BuildsWithPinnedRoot(
            CertificatePin.Sha256Hex(intermediate.RawData),
            rootPem,
            leaf,
            presented));

        var wrapped = new HttpRequestException(
            "The SSL connection could not be established, see inner exception.",
            new System.Security.Authentication.AuthenticationException(
                "The remote certificate is invalid according to the validation procedure."));
        Assert.True(CertificatePin.IsValidationFailure(wrapped));
        Assert.False(CertificatePin.IsValidationFailure(new HttpRequestException("No such host is known.")));
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
    public void Settings_patch_retries_then_saves_without_throwing()
    {
        var path = Path.Combine(Path.GetTempPath(), "heirloom-settings-" + Guid.NewGuid().ToString("n") + ".json");
        File.WriteAllText(path, """{"companion_mic_device":"Yeti","session_volume":40}""");
        SettingsPatch.ResetTestHooks();
        SettingsPatch.RetryDelay = TimeSpan.Zero;
        SettingsPatch.MaxAttempts = 4;
        SettingsPatch.IoFailuresBeforeSuccess = 2;
        try
        {
            Assert.True(SettingsPatch.Write(path, new Dictionary<string, object?>
            {
                [SettingsPatch.CompanionProactive] = true,
            }));
            Assert.Equal(0, SettingsPatch.IoFailuresBeforeSuccess);
            var text = File.ReadAllText(path);
            Assert.Contains("Yeti", text);
            Assert.Contains("true", text);
            Assert.DoesNotContain(".tmp", Directory.GetFiles(Path.GetTempPath(), Path.GetFileName(path) + ".*.tmp").FirstOrDefault() ?? "");
        }
        finally
        {
            SettingsPatch.ResetTestHooks();
            if (File.Exists(path))
            {
                File.Delete(path);
            }
        }
    }

    [Fact]
    public void Settings_patch_gives_up_quietly_when_the_file_stays_busy()
    {
        var path = Path.Combine(Path.GetTempPath(), "heirloom-settings-" + Guid.NewGuid().ToString("n") + ".json");
        File.WriteAllText(path, """{"companion_mic_device":"Yeti"}""");
        SettingsPatch.ResetTestHooks();
        SettingsPatch.RetryDelay = TimeSpan.Zero;
        SettingsPatch.MaxAttempts = 3;
        SettingsPatch.IoFailuresBeforeSuccess = 9;
        try
        {
            var wrote = false;
            var error = Record.Exception(() => wrote = SettingsPatch.Write(path, new Dictionary<string, object?>
            {
                [SettingsPatch.BoxUrl] = "https://192.168.0.111",
            }));
            Assert.Null(error);
            Assert.False(wrote);
            Assert.Equal("""{"companion_mic_device":"Yeti"}""", File.ReadAllText(path));
            Assert.Equal(FileShare.ReadWrite, SettingsPatch.ShareMode);
        }
        finally
        {
            SettingsPatch.ResetTestHooks();
            File.Delete(path);
        }
    }

    [Fact]
    public void Settings_patch_reads_while_another_handle_shares_the_file()
    {
        var path = Path.Combine(Path.GetTempPath(), "heirloom-settings-" + Guid.NewGuid().ToString("n") + ".json");
        File.WriteAllText(path, """{"companion_audio_mic":true}""");
        using var hold = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite);
        Assert.True(SettingsPatch.Write(path, new Dictionary<string, object?>
        {
            [SettingsPatch.CompanionWakePhrase] = "hey twin",
        }));
        Assert.Equal("hey twin", SettingsPatch.ReadString(path, SettingsPatch.CompanionWakePhrase, ""));
        File.Delete(path);
    }

    [Fact]
    public void Companion_push_runs_at_startup_and_reconnect_and_names_always_listening()
    {
        Assert.True(CompanionSync.ShouldPush(signedIn: true, wasReachable: null, reachable: true));
        Assert.False(CompanionSync.ShouldPush(signedIn: true, wasReachable: null, reachable: false));
        Assert.False(CompanionSync.ShouldPush(signedIn: false, wasReachable: null, reachable: true));
        Assert.True(CompanionSync.ShouldPush(signedIn: true, wasReachable: false, reachable: true));
        Assert.False(CompanionSync.ShouldPush(signedIn: true, wasReachable: true, reachable: true));
        Assert.Equal("Always listening: on", CompanionSync.AlwaysListeningLabel(true));
        Assert.Equal("Always listening: off", CompanionSync.AlwaysListeningLabel(false));
        var body = CompanionSync.AssistSettingsBody("Ada", "hey ada", true);
        Assert.Contains("hey ada", body);
        Assert.Contains("true", body);
        Assert.True(CaretakerGuard.WantsRestart("""{"restart":true,"repush":false}"""));
        Assert.True(CaretakerGuard.WantsRepush("""{"restart":false,"repush":true}"""));
        Assert.False(CaretakerGuard.WantsRestart("{}"));
        Assert.Contains("password", CaretakerGuard.Block("what is the owner password"), StringComparison.OrdinalIgnoreCase);
        Assert.Contains("192.168.0.16", CaretakerGuard.Block("touch 192.168.0.16"));
        Assert.Contains("reboot", CaretakerGuard.Block("reboot BIGDEAL"), StringComparison.OrdinalIgnoreCase);
        Assert.Null(CaretakerGuard.Block("the tray is red"));
    }

    [Fact]
    public void Rejected_session_clears_the_file_and_names_sign_in()
    {
        var path = Path.Combine(Path.GetTempPath(), "heirloom-session-" + Guid.NewGuid().ToString("n") + ".bin");
        File.WriteAllText(path, "stale");
        Assert.True(OwnerSession.IsRejected(401));
        Assert.False(OwnerSession.IsRejected(503));
        Assert.Equal("Signed out, sign in again", OwnerSession.SignedOutSignInAgain);
        OwnerSession.DeleteFile(path);
        Assert.False(File.Exists(path));
        OwnerSession.DeleteFile(path);
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
        request.CertificateExtensions.Add(new X509BasicConstraintsExtension(true, false, 0, true));
        return request.CreateSelfSigned(DateTimeOffset.UtcNow.AddDays(-1), DateTimeOffset.UtcNow.AddDays(2));
    }

    private static X509Certificate2 Issue(string name, RSA key, X509Certificate2? issuer, bool ca)
    {
        var request = new CertificateRequest("CN=" + name, key, HashAlgorithmName.SHA256, RSASignaturePadding.Pkcs1);
        request.CertificateExtensions.Add(new X509BasicConstraintsExtension(ca, false, 0, true));
        request.CertificateExtensions.Add(new X509SubjectKeyIdentifierExtension(request.PublicKey, false));
        request.CertificateExtensions.Add(new X509KeyUsageExtension(
            ca ? X509KeyUsageFlags.KeyCertSign | X509KeyUsageFlags.CrlSign : X509KeyUsageFlags.DigitalSignature,
            true));
        if (!ca)
        {
            request.CertificateExtensions.Add(new X509EnhancedKeyUsageExtension(
                new OidCollection { new Oid("1.3.6.1.5.5.7.3.1") },
                false));
        }

        if (issuer is null)
        {
            return request.CreateSelfSigned(DateTimeOffset.UtcNow.AddDays(-2), DateTimeOffset.UtcNow.AddDays(30));
        }

        var serial = RandomNumberGenerator.GetBytes(8);
        serial[0] &= 0x7F;
        var notAfter = DateTimeOffset.UtcNow.AddDays(20);
        if (notAfter > issuer.NotAfter)
        {
            notAfter = issuer.NotAfter;
        }

        using var signed = request.Create(issuer, DateTimeOffset.UtcNow.AddDays(-1), notAfter, serial);
        return signed.CopyWithPrivateKey(key);
    }
}
