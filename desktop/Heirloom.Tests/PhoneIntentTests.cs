using Heirloom.Services;
using Xunit;

namespace Heirloom.Tests;

public class PhoneIntentTests
{
    private static readonly PhoneContact[] Family =
    [
        new("Mom", "+15551230000"),
        new("Sam", "+15559870000"),
    ];

    [Fact]
    public void Normalizes_us_and_plus()
    {
        Assert.Equal("+15551234567", PhoneIntent.NormalizeE164("555-123-4567"));
        Assert.Equal("+15551234567", PhoneIntent.NormalizeE164("+1 555 123 4567"));
        Assert.Equal("+442079460958", PhoneIntent.NormalizeE164("+44 20 7946 0958"));
        Assert.Equal("", PhoneIntent.NormalizeE164("abc"));
    }

    [Theory]
    [InlineData("call Mom", "Mom", "+15551230000")]
    [InlineData("Call my mom", "Mom", "+15551230000")]
    [InlineData("please call Sam", "Sam", "+15559870000")]
    [InlineData("dial +1 555 123 0000", "Mom", "+15551230000")]
    [InlineData("give Mom a call", "Mom", "+15551230000")]
    [InlineData("place a call to Sam", "Sam", "+15559870000")]
    [InlineData("phone Mom", "Mom", "+15551230000")]
    public void Parses_family_and_numbers(string utterance, string name, string e164)
    {
        Assert.True(PhoneIntent.TryParse(utterance, Family, out var intent));
        Assert.True(intent.Resolved);
        Assert.Equal(e164, intent.ToE164);
        Assert.Equal(name, intent.ContactName);
        Assert.Contains("Confirm", intent.Summary, StringComparison.Ordinal);
    }

    [Fact]
    public void Unknown_name_is_unresolved_not_ordinary_talk()
    {
        Assert.True(PhoneIntent.TryParse("call Aunt May", Family, out var intent));
        Assert.False(intent.Resolved);
        Assert.Contains("Who may call", intent.Summary, StringComparison.Ordinal);
    }

    [Theory]
    [InlineData("where did you grow up")]
    [InlineData("open notepad")]
    [InlineData("recall the farm")]
    [InlineData("what do you call that")]
    [InlineData("call it a day")]
    [InlineData("ring doorbell")]
    [InlineData("tell me a story")]
    [InlineData("make a video of that")]
    public void Leaves_ordinary_talk_alone(string utterance)
    {
        Assert.False(PhoneIntent.TryParse(utterance, Family, out _));
    }
}
