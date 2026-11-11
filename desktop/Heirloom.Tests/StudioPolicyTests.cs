using Heirloom.Services;
using Xunit;

namespace Heirloom.Tests;

public class StudioPolicyTests
{
    [Fact]
    public void Secrets_are_masked_and_logs_stay_redacted()
    {
        const string secret = "hf_live_token_should_never_appear";
        var masked = StudioPolicy.MaskSecret(secret);
        Assert.DoesNotContain(secret, masked);
        Assert.EndsWith("pear", masked);
        Assert.Equal("[redacted]", StudioPolicy.SecretForLog(secret));
        Assert.Equal("••••", StudioPolicy.MaskSecret("short"));
    }

    [Theory]
    [InlineData("openai")]
    [InlineData("gemini")]
    [InlineData("elevenlabs")]
    public void Hosted_model_keys_are_not_collected(string flow)
    {
        Assert.True(StudioPolicy.CloudModelKey(flow));
        Assert.False(StudioPolicy.CloudModelKey("huggingface"));
    }

    [Fact]
    public void Restore_refuses_the_live_linux_root()
    {
        Assert.True(StudioPolicy.IsUnderLinuxLiveRoot("/var/lib/heirloom"));
        Assert.True(StudioPolicy.IsUnderLinuxLiveRoot("/var/lib/heirloom/vault"));
        Assert.False(StudioPolicy.IsUnderLinuxLiveRoot(@"D:\HeirloomVault"));
    }

    [Fact]
    public void Thermostat_extremes_are_clamped_and_critical_off_is_confirmed()
    {
        var heat = StudioPolicy.ClampSetpoint("heat", 95);
        Assert.True(heat.Limited);
        Assert.Equal(74, heat.Applied);
        var cool = StudioPolicy.ClampSetpoint("cool", 50);
        Assert.Equal(68, cool.Applied);
        Assert.True(StudioPolicy.IsCritical("Kitchen fridge", ""));
        Assert.False(StudioPolicy.MayTurnOff(critical: true, approved: true, criticalConfirm: false, alwaysAllow: true, thermostat: false));
        Assert.True(StudioPolicy.MayTurnOff(critical: true, approved: true, criticalConfirm: true, alwaysAllow: false, thermostat: false));
        Assert.False(StudioPolicy.MayTurnOff(critical: false, approved: true, criticalConfirm: false, alwaysAllow: true, thermostat: true));
        Assert.True(StudioPolicy.MayTurnOff(critical: false, approved: false, criticalConfirm: false, alwaysAllow: true, thermostat: false));
    }

    [Fact]
    public void Paste_and_commands_and_coder_stay_local()
    {
        Assert.False(StudioPolicy.MayPaste(false));
        Assert.True(StudioPolicy.MayPaste(true));
        Assert.Equal("Ctrl+Alt+H", StudioPolicy.PasteChord);
        Assert.True(StudioPolicy.CommandBlocked("rm -rf /"));
        Assert.True(StudioPolicy.CommandBlocked("shutdown /s"));
        Assert.False(StudioPolicy.CommandBlocked("pytest -q"));
        Assert.Equal("qwen3-coder:30b", StudioPolicy.PickCoder(["qwen2.5-coder:7b", "qwen3-coder:30b", "gpt-4o"]));
        Assert.Null(StudioPolicy.PickCoder(["gpt-oss:120b", "gemini-2.5"]));
    }
}
