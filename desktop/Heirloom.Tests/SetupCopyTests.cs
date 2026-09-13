using System.Net.Http;
using System.Net.Sockets;
using Heirloom.Services;
using Xunit;

namespace Heirloom.Tests;

public class SetupCopyTests
{
    [Fact]
    public void Tiny_disk_cannot_hear()
    {
        var plan = SetupCopy.PlanForFreeSpace(80L * 1024 * 1024, "C:");
        Assert.False(plan.CanHear);
        Assert.False(plan.CanThink);
        Assert.False(plan.CanPicture);
        Assert.Equal("small", plan.ProfileId);
        Assert.Contains("C:", plan.DiskLine);
    }

    [Fact]
    public void Nine_gig_is_small_and_does_not_require_a_local_mind()
    {
        var plan = SetupCopy.PlanForFreeSpace(9L * 1024 * 1024 * 1024, "C:");
        Assert.True(plan.CanHear);
        Assert.False(plan.CanThink);
        Assert.False(plan.CanPicture);
        Assert.Equal("small", plan.ProfileId);
    }

    [Fact]
    public void Medium_disk_is_picked_at_fifty_five_gig()
    {
        var plan = SetupCopy.PlanForFreeSpace(55L * 1024 * 1024 * 1024, "D:");
        Assert.True(plan.CanHear);
        Assert.True(plan.CanThink);
        Assert.False(plan.CanPicture);
        Assert.Equal("medium", plan.ProfileId);
    }

    [Fact]
    public void Large_disk_is_picked_at_one_twenty_gig()
    {
        var plan = SetupCopy.PlanForFreeSpace(120L * 1024 * 1024 * 1024, "D:");
        Assert.True(plan.CanHear);
        Assert.True(plan.CanThink);
        Assert.True(plan.CanPicture);
        Assert.Equal("large", plan.ProfileId);
    }

    [Fact]
    public void Dedicated_disk_is_picked_only_when_huge()
    {
        var almost = SetupCopy.PlanForFreeSpace(170L * 1024 * 1024 * 1024, "E:");
        Assert.Equal("large", almost.ProfileId);
        var huge = SetupCopy.PlanForFreeSpace(200L * 1024 * 1024 * 1024, "E:");
        Assert.Equal("dedicated", huge.ProfileId);
    }

    [Fact]
    public void Disk_profile_aliases_map_legacy_ids()
    {
        Assert.Equal("small", DiskProfiles.Resolve("lite").Id);
        Assert.Equal("medium", DiskProfiles.Resolve("full").Id);
        Assert.Equal("large", DiskProfiles.Resolve("max").Id);
        Assert.Equal("large", DiskProfiles.Resolve("studio").Id);
        Assert.Equal("medium", DiskProfiles.Resolve("nope").Id);
        Assert.Equal("dedicated", DiskProfiles.Resolve("dedicated").Id);
    }

    [Fact]
    public void Dedicated_role_writes_install_profile()
    {
        var settings = new AppSettings();
        DedicatedRole.Apply(settings, consent: true, vaultDrive: @"D:\HeirloomVault");
        Assert.Equal("dedicated", settings.InstallProfile);
        Assert.Equal("dedicated", settings.DiskProfile);
        Assert.Equal("dedicated", settings.MachineRole);
        Assert.True(settings.DedicatedConsent);
        Assert.True(settings.LiveListen);
        Assert.Equal(@"D:\HeirloomVault", settings.LibraryPath);
    }

    [Fact]
    public void Network_error_tells_them_to_use_wifi()
    {
        var ex = new HttpRequestException("No such host is known", new SocketException());
        var line = SetupCopy.HumanFault(ex, "downloading hearing");
        Assert.Contains("internet", line, StringComparison.OrdinalIgnoreCase);
        Assert.Contains("Try again", line, StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain("HttpRequest", line);
        Assert.DoesNotContain("Socket", line);
    }

    [Fact]
    public void Disk_full_tells_them_to_free_room()
    {
        var line = SetupCopy.HumanFault(new IOException("There is not enough space on the disk."), "saving hearing");
        Assert.Contains("space", line, StringComparison.OrdinalIgnoreCase);
        Assert.Contains("Try again", line, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public void User_stop_is_calm()
    {
        using var cts = new CancellationTokenSource();
        cts.Cancel();
        var line = SetupCopy.HumanFault(new OperationCanceledException(), "getting Heirloom ready", cts.Token);
        Assert.Contains("Stopped", line);
        Assert.Contains("Get everything ready", line);
    }

    [Fact]
    public void Declined_permission_asks_for_yes()
    {
        var line = SetupCopy.HumanInstallerExit(1223);
        Assert.Contains("Yes", line);
        Assert.DoesNotContain("1223", line);
    }

    [Fact]
    public void Pull_json_hides_model_names()
    {
        var line = SetupCopy.FriendlyPullStatus("""{"status":"downloading","completed":1024,"total":2048}""");
        Assert.Contains("Talking mind", line);
        Assert.DoesNotContain("llama", line, StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain("digest", line, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public void Friendly_line_strips_jargon()
    {
        var line = SetupCopy.FriendlyLine("Pulling llama3.1");
        Assert.Contains("talking mind", line, StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain("llama3.1", line, StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain("Pulling", line);
    }

    [Fact]
    public void Done_copy_never_asks_for_keys()
    {
        var body = SetupCopy.DoneBody(true, true, false);
        Assert.Contains("file", body, StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain("API", body, StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain("token", body, StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain("Ollama", body, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public void Forbidden_http_is_human()
    {
        var line = SetupCopy.HumanHttpStatus(403);
        Assert.Contains("Try again", line);
        Assert.DoesNotContain("403", line);
        Assert.DoesNotContain("Forbidden", line);
    }

    [Fact]
    public void Ollama_paths_are_local_or_program_files()
    {
        var paths = SetupCopy.OllamaExeCandidates();
        Assert.NotEmpty(paths);
        Assert.All(paths, p => Assert.EndsWith("ollama.exe", p, StringComparison.OrdinalIgnoreCase));
    }

    [Fact]
    public void Byte_format_uses_gb()
    {
        Assert.Equal("1 GB", SetupCopy.FormatBytes(1024L * 1024 * 1024));
        Assert.Contains("MB", SetupCopy.FormatBytes(150L * 1024 * 1024));
    }
}
