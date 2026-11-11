using System.Text.Json;
using Heirloom.BoxCore;
using Heirloom.Services;
using Xunit;

namespace Heirloom.Tests;

public class BuyerRuntimeTests
{
    [Fact]
    public void Restart_releases_the_instance_before_the_child_starts()
    {
        var order = new List<string>();
        InstanceHandoff.Restart(
            () => order.Add("release"),
            () => order.Add("start"),
            () => order.Add("shutdown"));
        Assert.Equal(new[] { "release", "start", "shutdown" }, order);
    }

    [Fact]
    public async Task Health_pass_does_not_touch_sta_objects_from_the_pool()
    {
        var gate = new StaAffinity();
        Action? posted = null;
        await Task.Run(async () =>
        {
            await CompanionHealthPass.RunAsync(
                async cancellationToken => await Task.Yield(),
                () => gate.Touch(),
                () => false,
                action => posted = action,
                CancellationToken.None);
        });

        Assert.NotNull(posted);
        Assert.Equal(0, gate.Touches);
    }

    [Fact]
    public void Health_log_names_reachable_sign_in_and_lamp()
    {
        var line = HealthLog.Line(reachable: true, signedIn: true, BoxLamp.Green);
        Assert.Contains("reachable=yes", line, StringComparison.Ordinal);
        Assert.Contains("signed-in=yes", line, StringComparison.Ordinal);
        Assert.Contains("lamp=green", line, StringComparison.Ordinal);
        var start = DateTimeOffset.Parse("2026-11-11T20:00:00Z");
        Assert.True(HealthLog.ShouldWrite(null, start, changed: false));
        Assert.False(HealthLog.ShouldWrite(start, start.AddMinutes(1), changed: false));
        Assert.True(HealthLog.ShouldWrite(start, start.AddMinutes(1), changed: true));
        Assert.True(HealthLog.ShouldWrite(start, start.Add(HealthLog.Heartbeat), changed: false));
    }

    [Fact]
    public void Autostart_writes_one_run_value_and_drops_the_legacy_name()
    {
        var plan = CompanionAutostart.Build(true, @"C:\Heirloom\Companion\Heirloom.Companion.exe");
        Assert.Equal(CompanionAutostart.ValueName, plan.WriteName);
        Assert.Equal(@"""C:\Heirloom\Companion\Heirloom.Companion.exe""", plan.WriteValue);
        Assert.Contains("HeirloomCompanion", plan.Delete);
        Assert.DoesNotContain(CompanionAutostart.ValueName, plan.Delete);
        Assert.DoesNotContain("Heirloom", plan.Delete);

        var off = CompanionAutostart.Build(false, @"C:\Heirloom\Companion\Heirloom.Companion.exe");
        Assert.Null(off.WriteName);
        Assert.Null(off.WriteValue);
        Assert.Contains(CompanionAutostart.ValueName, off.Delete);
        Assert.Contains("HeirloomCompanion", off.Delete);
    }

    [Fact]
    public void Session_bundle_keeps_a_legacy_token_and_a_refresh_pair()
    {
        var legacy = BoxSessionBundle.Parse("sess-legacy");
        Assert.NotNull(legacy);
        Assert.Equal("sess-legacy", legacy!.Session);
        Assert.False(legacy.HasRefresh);

        var encoded = new BoxSessionBundle("sess-new", "refresh-new", "2026-11-18T20:01:00+00:00").Encode();
        var parsed = BoxSessionBundle.Parse(encoded);
        Assert.NotNull(parsed);
        Assert.Equal("sess-new", parsed!.Session);
        Assert.Equal("refresh-new", parsed.Refresh);
        Assert.Equal("2026-11-18T20:01:00+00:00", parsed.ExpiresAt);

        using var doc = JsonDocument.Parse("""
            {"session_token":"sess-api","refresh_token":"refresh-api","expires_at":"2026-11-18T20:01:00+00:00"}
            """);
        var fromApi = BoxSessionBundle.FromApi(doc.RootElement);
        Assert.Equal("sess-api", fromApi!.Session);
        Assert.Equal("refresh-api", fromApi.Refresh);
    }

    [Fact]
    public void Session_clock_renews_before_expiry_and_after_it()
    {
        var now = DateTimeOffset.Parse("2026-11-11T20:00:00Z");
        Assert.True(SessionClock.ShouldRenew(now.AddDays(6), now, hasRefresh: false));
        Assert.False(SessionClock.ShouldRenew(now.AddDays(6), now, hasRefresh: true));
        Assert.True(SessionClock.ShouldRenew(now.AddHours(12), now, hasRefresh: true));
        Assert.True(SessionClock.ShouldRenew(now.AddHours(-1), now, hasRefresh: true));
        Assert.False(SessionClock.AttemptDue(now, now.AddMinutes(5)));
        Assert.True(SessionClock.AttemptDue(now, now.Add(SessionClock.RetrySpacing)));
        Assert.True(ChatWait.BoxReply > ChatWait.ColdLoadSeen);
        Assert.True(ChatWait.HttpClient > ChatWait.BoxReply);
        Assert.True(ChatWait.LocalModel > ChatWait.ColdLoadSeen);
    }

    [Fact]
    public void Title_uses_the_assembly_product_version()
    {
        Assert.Equal("Heirloom  0.5.1+0dd47adc7372430b6f2005741e64be71e7369a32", ProductStamp.Title("0.5.1+0dd47adc7372430b6f2005741e64be71e7369a32"));
        Assert.Equal("0.5.1", ProductStamp.Display(null));
        Assert.DoesNotContain("dev", ProductStamp.Title("0.5.1+0dd47ad"), StringComparison.Ordinal);
    }

    [Fact]
    public void Expired_session_and_cold_model_are_not_a_provisioning_reply()
    {
        Assert.Equal(
            TwinFailure.SessionExpired,
            TwinFailure.HonestReply(null, "Cloud HTTP 401: {\"detail\":\"Session expired\"}"));
        Assert.Equal(
            TwinFailure.ModelNotReady,
            TwinFailure.HonestReply(null, "Cloud HTTP 502: Local twin (Ollama) failed: the local model is still loading"));
        Assert.Equal(
            TwinFailure.ModelNotReady,
            TwinFailure.HonestReply("Ollama generate timed out (qwen2.5:14b).", null));
        Assert.Null(TwinFailure.HonestReply(null, null));
        Assert.Contains("Sign in", TwinFailure.SessionExpired, StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain("provision Models", TwinFailure.SessionExpired, StringComparison.Ordinal);
        Assert.DoesNotContain("provision Models", TwinFailure.ModelNotReady, StringComparison.Ordinal);
    }
}
