using System.Text.Json;
using Heirloom.BoxCore;
using Xunit;

namespace Heirloom.Tests;

public class LocalZoneTests
{
    [Theory]
    [InlineData("Pacific Standard Time", "America/Los_Angeles")]
    [InlineData("Eastern Standard Time", "America/New_York")]
    [InlineData("Central Standard Time", "America/Chicago")]
    [InlineData("America/Denver", "America/Denver")]
    [InlineData(" Europe/London ", "Europe/London")]
    public void Windows_and_iana_ids_become_iana(string id, string expected)
    {
        Assert.Equal(expected, LocalZone.Iana(id));
    }

    [Theory]
    [InlineData("")]
    [InlineData("   ")]
    [InlineData(null)]
    [InlineData("Not A Real Zone")]
    public void Unknown_ids_send_nothing(string? id)
    {
        Assert.Null(LocalZone.Iana(id));
    }

    [Fact]
    public void This_pc_has_a_zone_the_box_can_read()
    {
        var zone = LocalZone.Iana();
        Assert.False(string.IsNullOrWhiteSpace(zone));
        Assert.Contains('/', zone!);
        Assert.NotNull(TimeZoneInfo.FindSystemTimeZoneById(zone!));
    }

    [Fact]
    public void Companion_turns_carry_the_zone()
    {
        using var ptt = JsonDocument.Parse(AssistLiveBodies.Ptt(true));
        Assert.True(ptt.RootElement.GetProperty("held").GetBoolean());
        Assert.Equal(LocalZone.Iana(), ptt.RootElement.GetProperty("timezone").GetString());
        using var say = JsonDocument.Parse(AssistLiveBodies.Say("Remind me to call mom tomorrow at 9am"));
        Assert.Equal("Remind me to call mom tomorrow at 9am", say.RootElement.GetProperty("text").GetString());
        Assert.Equal(LocalZone.Iana(), say.RootElement.GetProperty("timezone").GetString());
    }
}
