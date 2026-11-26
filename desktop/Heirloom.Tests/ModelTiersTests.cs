using Heirloom.BoxCore;
using Heirloom.Services;
using Xunit;

namespace Heirloom.Tests;

public class ModelTiersTests
{
    [Theory]
    [InlineData("nvidia", 32607, 65536, "xl", "gemma4:26b")]
    [InlineData("nvidia", 24576, 65536, "large", "gemma4:12b")]
    [InlineData("nvidia", 16384, 32768, "medium", "gemma4:12b")]
    [InlineData("nvidia", 12288, 32768, "small", "qwen3.5:4b")]
    [InlineData("nvidia", 8192, 16384, "compact", "qwen3.5:4b")]
    [InlineData("none", 0, 16384, "cpu", "gemma4:e4b")]
    [InlineData("none", 0, 8192, "cpu", "gemma4:e2b")]
    [InlineData("intel", 8192, 32768, "cpu", "gemma4:e4b")]
    public void Picks_the_tier_model(string vendor, int vram, int ram, string tier, string model)
    {
        var pick = ModelTiers.Choose(new ModelTiers.Hardware(vendor, "test", vram, ram));
        Assert.Equal(tier, pick.Tier);
        Assert.Equal(model, pick.Model);
    }

    [Fact]
    public void Never_picks_the_old_default_or_a_cloud_model()
    {
        foreach (var m in ModelTiers.AllModels)
        {
            Assert.DoesNotContain("llama3.1", m);
            Assert.DoesNotContain("cloud", m);
        }
    }

    [Fact]
    public void Parses_nvidia_smi_and_keeps_the_biggest_card()
    {
        var (name, mib) = ModelTiers.ParseNvidiaSmi("NVIDIA GeForce RTX 3060, 12288\nNVIDIA GeForce RTX 5090, 32607\n");
        Assert.Equal("NVIDIA GeForce RTX 5090", name);
        Assert.Equal(32607, mib);
        Assert.Equal(0, ModelTiers.ParseNvidiaSmi("").Mib);
    }

    [Fact]
    public void Friendly_line_hides_tier_model_names()
    {
        var line = SetupCopy.FriendlyLine("Pulling gemma4:26b");
        Assert.DoesNotContain("gemma4", line, StringComparison.OrdinalIgnoreCase);
        Assert.Contains("talking mind", line, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public void Local_box_url_comes_from_the_install()
    {
        var dir = Path.Combine(Path.GetTempPath(), "hl-localbox-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(Path.Combine(dir, "data"));
        try
        {
            Assert.Null(LocalBox.FindUrl(dir));
            File.WriteAllText(Path.Combine(dir, "data", "heirloom.env"), "MONGO_URL=x\nHEIRLOOM_API_PORT=18101\n");
            Assert.Equal("http://127.0.0.1:18101", LocalBox.FindUrl(dir));
            Assert.Equal("http://127.0.0.1:18101", BoxLink.Normalize(LocalBox.FindUrl(dir)!));
        }
        finally
        {
            Directory.Delete(dir, true);
        }
    }
}

public class LocalBoxLinkTests
{
    [Theory]
    [InlineData("http://127.0.0.1:8001", true)]
    [InlineData("http://localhost:18101", true)]
    [InlineData("https://127.0.0.1:8001", false)]
    [InlineData("http://192.168.0.111", false)]
    [InlineData("https://192.168.0.111", false)]
    [InlineData("", false)]
    public void Only_plain_loopback_skips_the_pin(string url, bool expected) =>
        Assert.Equal(expected, BoxLink.IsLoopbackHttp(url));
}
