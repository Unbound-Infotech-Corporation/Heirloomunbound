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
}
