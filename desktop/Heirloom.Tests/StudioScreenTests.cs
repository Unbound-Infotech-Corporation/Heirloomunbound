using Heirloom.Services;
using Xunit;

namespace Heirloom.Tests;

public class StudioScreenTests
{
    [Fact]
    public void Setup_hides_the_passphrase_and_refuses_cloud_keys()
    {
        var setup = new SetupCenterModel();
        setup.Load(new SetupSignals(true, false, true, true, false, false, false, "120 GB free"));
        Assert.Contains(setup.Steps, step => step.Title == "Hearing" && step.Status == "Needs you");
        Assert.Contains(setup.Repair(new SetupSignals(true, false, true, true, true, true, false, "")), step => step.Title == "Hearing");
        Assert.True(setup.Select("huggingface"));
        Assert.Equal("https://huggingface.co/settings/tokens", setup.OpenUrl());
        Assert.False(setup.Paste("openai", "sk-live-secret-value", null));
        Assert.DoesNotContain("sk-live-secret-value", setup.PublicSnapshot());
        const string token = "hf_download_token_value";
        Assert.True(setup.Paste("huggingface", token, null));
        Assert.DoesNotContain(token, setup.PublicSnapshot());
        Assert.DoesNotContain("openai", SetupCenterModel.Guides.Select(guide => guide.Id));
        setup.SetPassphrase("correct horse battery staple");
        Assert.DoesNotContain("horse", setup.PublicSnapshot());
        Assert.DoesNotContain("horse", setup.ToString());
        Assert.Equal("correct horse battery staple", setup.ConsumePassphrase());
        Assert.False(setup.HasPassphrase);
    }

    [Fact]
    public void Writing_underlines_a_misspelling_and_paste_waits()
    {
        var writing = new WritingModel();
        writing.Check("Please recieve this.");
        Assert.Contains(writing.Segments, segment => segment.Underline && segment.Suggestion == "receive");
        writing.Check("This is very late.");
        Assert.Equal("This is late.", writing.Rewrite("shorter"));
        Assert.Null(writing.PasteBack());
        Assert.True(writing.ApprovePaste());
        Assert.Equal("This is late.", writing.PasteBack());
        writing.Define("happy");
        Assert.Contains("glad", writing.LookupLine);
    }

    [Fact]
    public void Home_confirms_a_critical_off_and_code_blocks_a_dangerous_command()
    {
        var home = new SmartHomeModel();
        home.Show([new HomeDevice("1", "Hall light", "hue", "light"), new HomeDevice("2", "Kitchen fridge", "kasa", "plug", true)]);
        Assert.Equal("2 found on your network.", home.Status);
        var light = home.Devices[0];
        Assert.False(home.Change(light, "off", approved: false, criticalConfirm: false, alwaysAllow: false));
        Assert.True(home.Change(light, "off", approved: true, criticalConfirm: false, alwaysAllow: false));
        var fridge = home.Devices[1];
        Assert.False(home.Change(fridge, "off", approved: true, criticalConfirm: false, alwaysAllow: true));
        Assert.True(home.Change(fridge, "off", approved: true, criticalConfirm: true, alwaysAllow: false));

        var code = new CodeWorkspaceModel();
        code.Open(["src/main.py", ".env", "notes/odysseus.token"]);
        Assert.Equal(new[] { "src/main.py" }, code.Files);
        code.UseCoder(["gpt-4o", "qwen2.5-coder:7b"]);
        Assert.Contains("qwen2.5-coder:7b", code.Coder);
        code.Propose("alpha", "beta");
        Assert.False(code.Hunks[0].Accepted);
        code.Hunks[0].Accepted = true;
        Assert.Equal("beta", code.ApplyAccepted());
        Assert.False(code.ReviewCommand("rm -rf /", approved: true));
        Assert.False(code.ReviewCommand("pytest -q", approved: false));
        Assert.True(code.ReviewCommand("pytest -q", approved: true));
    }
}
