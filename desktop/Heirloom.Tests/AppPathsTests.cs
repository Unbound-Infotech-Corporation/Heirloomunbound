using System.Text.Json;
using Heirloom.Services;
using Xunit;

namespace Heirloom.Tests;

public class AppPathsTests
{
    [Fact]
    public void Avatar_engine_uses_f_only_when_the_models_folder_exists()
    {
        Assert.Equal(@"F:\HeirloomModels\avatar-engine", AppPaths.ResolveAvatarEngineRoot(true));
        var local = AppPaths.ResolveAvatarEngineRoot(false);
        Assert.EndsWith(Path.Combine("Heirloom", "engines", "avatar"), local);
        Assert.DoesNotContain(@"F:\HeirloomModels", local);
    }

    [Fact]
    public void Optional_directory_failure_does_not_throw()
    {
        var file = Path.Combine(Path.GetTempPath(), "heirloom-not-a-dir-" + Guid.NewGuid().ToString("n"));
        File.WriteAllText(file, "x");
        try
        {
            Assert.False(AppPaths.TryCreateDirectory(Path.Combine(file, "avatar-engine")));
        }
        finally
        {
            File.Delete(file);
        }
    }

    [Fact]
    public void Save_merge_keeps_companion_keys_the_app_does_not_own()
    {
        var existing = """{"backend_url":"https://old.example","companion_mic_device":"Yeti","companion_proactive":true,"companion_audio_mic":false,"session_volume":40}""";
        var current = new AppSettings
        {
            BackendUrl = "https://new.example",
            SessionVolume = 80,
        };
        var merged = SettingsStore.MergePreservingUnknown(existing, current);
        Assert.Contains("Yeti", merged);
        Assert.Contains("companion_proactive", merged);
        Assert.Contains("companion_audio_mic", merged);
        Assert.Contains("https://new.example", merged);
        Assert.DoesNotContain("https://old.example", merged);
        using var doc = JsonDocument.Parse(merged);
        Assert.Equal(80, doc.RootElement.GetProperty("session_volume").GetInt32());
        Assert.True(doc.RootElement.GetProperty("companion_proactive").GetBoolean());
        Assert.False(doc.RootElement.GetProperty("companion_audio_mic").GetBoolean());
    }
}
