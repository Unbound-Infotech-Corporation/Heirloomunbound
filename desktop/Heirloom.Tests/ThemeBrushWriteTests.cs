using Heirloom.Services;
using Xunit;

namespace Heirloom.Tests;

public class ThemeBrushWriteTests
{
    [Fact]
    public void Assign_replaces_the_entry()
    {
        var resources = new Dictionary<string, string> { ["HeirloomGoldBrush"] = "sealed" };
        var wrote = false;
        var ok = ThemeBrushWrite.Assign(() =>
        {
            resources["HeirloomGoldBrush"] = "fresh";
            wrote = true;
        }, "HeirloomGoldBrush", null);

        Assert.True(ok);
        Assert.True(wrote);
        Assert.Equal("fresh", resources["HeirloomGoldBrush"]);
    }

    [Fact]
    public void Sealed_brush_is_logged_and_the_next_key_still_applies()
    {
        var logged = new List<string>();
        var applied = new List<string>();
        Assert.False(ThemeBrushWrite.Assign(
            () => throw new UnauthorizedAccessException("read-only"),
            "TextFillColorPrimaryBrush",
            (key, _) => logged.Add(key)));
        Assert.False(ThemeBrushWrite.Assign(
            () => throw new InvalidOperationException("wrong thread"),
            "AccentFillColorDefaultBrush",
            (key, _) => logged.Add(key)));
        Assert.True(ThemeBrushWrite.Assign(
            () => applied.Add("HeirloomTextBrush"),
            "HeirloomTextBrush",
            (key, _) => logged.Add(key)));

        Assert.Equal(new[] { "TextFillColorPrimaryBrush", "AccentFillColorDefaultBrush" }, logged);
        Assert.Equal(new[] { "HeirloomTextBrush" }, applied);
    }
}
