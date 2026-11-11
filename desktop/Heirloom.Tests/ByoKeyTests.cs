using Heirloom.BoxCore;
using Xunit;

namespace Heirloom.Tests;

public class ByoKeyTests
{
    [Fact]
    public void Log_line_and_settings_do_not_contain_the_key()
    {
        const string secret = "sk_live_desktop_key_should_not_log";
        var line = $"saved elevenlabs={ByoKeyFile.ForLog(secret)}";
        Assert.DoesNotContain(secret, line);
        Assert.Contains("[redacted]", line);
        var settings = """{"BackendUrl":"https://example.invalid","VendorEmail":"owner@example.com"}""";
        Assert.False(ByoKeyFile.SettingsContain(settings, secret));
        Assert.True(ByoKeyFile.SettingsContain($"{{\"api_key\":\"{secret}\"}}", secret));
    }

    [Fact]
    public void Dpapi_save_on_this_runtime_does_not_write_the_key()
    {
        const string secret = "sk_live_desktop_key_should_not_log";
        var directory = Path.Combine(Path.GetTempPath(), "heirloom-byo-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(directory);
        try
        {
            if (OperatingSystem.IsWindows())
            {
                ByoKeyFile.Save(directory, "fal", secret);
                var stored = System.Text.Encoding.UTF8.GetString(
                    File.ReadAllBytes(Path.Combine(directory, "fal.bin")));
                Assert.DoesNotContain(secret, stored);
                Assert.Equal(secret, ByoKeyFile.TryRead(directory, "fal"));
                return;
            }

            var error = Assert.Throws<PlatformNotSupportedException>(() => ByoKeyFile.Save(directory, "fal", secret));
            Assert.DoesNotContain(secret, error.Message);
            Assert.Null(ByoKeyFile.TryRead(directory, "fal"));
            foreach (var file in Directory.EnumerateFiles(directory, "*", SearchOption.AllDirectories))
            {
                Assert.DoesNotContain(secret, File.ReadAllText(file));
            }
        }
        finally
        {
            if (Directory.Exists(directory))
            {
                Directory.Delete(directory, recursive: true);
            }
        }
    }
}
