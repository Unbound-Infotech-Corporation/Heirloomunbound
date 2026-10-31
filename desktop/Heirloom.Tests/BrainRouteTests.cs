using Heirloom.BoxCore;
using Xunit;

namespace Heirloom.Tests;

public class BrainRouteTests
{
    [Theory]
    [InlineData("http://192.168.0.50:11434", "http://192.168.0.50:11434")]
    [InlineData("http://192.168.0.50", "http://192.168.0.50:11434")]
    [InlineData("http://10.1.2.3:11434", "http://10.1.2.3:11434")]
    public void Lan_urls_normalize(string raw, string expected)
    {
        Assert.True(BrainRoute.TryNormalizeLanUrl(raw, out var normalized, out var error), error);
        Assert.Equal(expected, normalized);
    }

    [Theory]
    [InlineData("http://8.8.8.8:11434")]
    [InlineData("http://bigdeal.example:11434")]
    [InlineData("http://192.168.0.16:11434")]
    [InlineData("http://user:secret@192.168.0.50:11434")]
    [InlineData("")]
    public void Public_names_and_secrets_are_refused(string raw)
    {
        Assert.False(BrainRoute.TryNormalizeLanUrl(raw, out _, out var error));
        Assert.False(string.IsNullOrWhiteSpace(error));
    }

    [Fact]
    public void Partial_vram_is_not_a_full_gpu()
    {
        const string partial = """{"models":[{"name":"qwen2.5:14b","size":100,"size_vram":40}]}""";
        const string full = """{"models":[{"name":"qwen2.5:14b","size":100,"size_vram":100}]}""";
        Assert.True(BrainRoute.LoadedModelsOffGpu(partial));
        Assert.False(BrainRoute.LoadedModelsOffGpu(full));
        Assert.False(BrainRoute.LoadedModelsOffGpu("""{"models":[]}"""));
    }

    [Fact]
    public void Processor_column_must_be_all_gpu()
    {
        const string full = "NAME ID SIZE PROCESSOR\nqwen abc 8GB 100% GPU\n";
        const string split = "NAME ID SIZE PROCESSOR\nqwen abc 8GB 60%/40% CPU/GPU\n";
        Assert.False(BrainRoute.ProcessorOffGpu(full));
        Assert.True(BrainRoute.ProcessorOffGpu(split));
        Assert.True(BrainRoute.ProcessorOffGpu("qwen  100% CPU"));
    }
}
