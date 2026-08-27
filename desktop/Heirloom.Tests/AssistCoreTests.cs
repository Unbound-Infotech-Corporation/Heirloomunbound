using Heirloom.Services;
using Xunit;

namespace Heirloom.Tests;

public class PathGuardTests
{
    [Fact]
    public void Profile_root_is_under_itself()
    {
        var home = Path.GetFullPath(Path.Combine(Path.GetTempPath(), "heirloom-home"));
        Directory.CreateDirectory(home);
        Assert.True(PathGuard.IsUnder(home, home));
        Assert.True(PathGuard.IsUnder(Path.Combine(home, "Documents", "a.txt"), home));
    }

    [Fact]
    public void Neighbor_profile_is_not_under_home()
    {
        var root = Path.GetFullPath(Path.Combine(Path.GetTempPath(), "heirloom-users"));
        var home = Path.Combine(root, "akind");
        var evil = Path.Combine(root, "akind.evil", "steal.txt");
        Directory.CreateDirectory(home);
        Assert.False(PathGuard.IsUnder(evil, home));
    }
}

public class LaunchTargetTests
{
    [Theory]
    [InlineData("notepad", LaunchTarget.Kind.App, "notepad")]
    [InlineData("Visual Studio Code", LaunchTarget.Kind.App, "code")]
    [InlineData("google chrome", LaunchTarget.Kind.App, "chrome")]
    [InlineData("settings", LaunchTarget.Kind.Url, "ms-settings:")]
    [InlineData("https://example.com", LaunchTarget.Kind.Url, "https://example.com")]
    [InlineData("github.com", LaunchTarget.Kind.Url, "https://github.com")]
    [InlineData("youtube", LaunchTarget.Kind.Url, "https://www.youtube.com")]
    [InlineData("Gmail", LaunchTarget.Kind.Url, "https://mail.google.com")]
    public void Resolves_known_targets(string input, LaunchTarget.Kind kind, string value)
    {
        var resolved = LaunchTarget.Resolve(input);
        Assert.Equal(kind, resolved.Kind);
        Assert.Equal(value, resolved.Value);
    }

    [Fact]
    public void Multi_word_unknown_app_is_not_a_google_search()
    {
        var resolved = LaunchTarget.Resolve("visual studio");
        Assert.Equal(LaunchTarget.Kind.App, resolved.Kind);
        Assert.Equal("visual studio", resolved.Value);
        Assert.DoesNotContain("google.com", resolved.Value, StringComparison.OrdinalIgnoreCase);
    }
}

public class AssistPlannerTests
{
    [Fact]
    public void Tool_wins_when_json_also_has_reply()
    {
        var plan = AssistPlanner.Parse("""{"tool":"open_app","name":"notepad","reply":"Opening notepad"}""");
        Assert.NotNull(plan);
        Assert.Equal("open_app", plan!.Tool);
        Assert.Equal("notepad", plan.Arg("name"));
        Assert.Null(plan.Reply);
    }

    [Fact]
    public void Reply_only_json_finishes()
    {
        var plan = AssistPlanner.Parse("""{"reply":"Done."}""");
        Assert.NotNull(plan);
        Assert.Equal("", plan!.Tool);
        Assert.Equal("Done.", plan.Reply);
    }

    [Fact]
    public void Power_lock_does_not_need_confirm()
    {
        Assert.False(AssistPlanner.NeedsConfirm("power", new Dictionary<string, string> { ["action"] = "lock" }));
        Assert.True(AssistPlanner.NeedsConfirm("power", new Dictionary<string, string> { ["action"] = "shutdown" }));
        Assert.True(AssistPlanner.NeedsConfirm("shell", new Dictionary<string, string> { ["command"] = "dir" }));
        Assert.False(AssistPlanner.NeedsConfirm("open_app", new Dictionary<string, string> { ["name"] = "notepad" }));
        Assert.False(AssistPlanner.NeedsConfirm("browse", new Dictionary<string, string> { ["action"] = "open", ["url"] = "https://www.youtube.com" }));
        Assert.True(AssistPlanner.NeedsConfirm("browse", new Dictionary<string, string> { ["action"] = "click", ["target"] = "Buy now" }));
        Assert.True(AssistPlanner.NeedsConfirm("browse", new Dictionary<string, string> { ["action"] = "type", ["target"] = "password" }));
        Assert.False(AssistPlanner.NeedsConfirm("browse", new Dictionary<string, string> { ["action"] = "click", ["target"] = "Search" }));
    }
}

public class ModelPickerTests
{
    [Fact]
    public void Skips_embed_models()
    {
        var picked = ModelPicker.PickGenerate(["nomic-embed-text:latest", "llama3.1:8b", "llava:7b"]);
        Assert.Equal("llama3.1:8b", picked);
    }

    [Fact]
    public void Empty_list_is_null()
    {
        Assert.Null(ModelPicker.PickGenerate([]));
    }

    [Fact]
    public void Prefers_llama_over_llava()
    {
        var picked = ModelPicker.PickGenerate(["llava:latest", "llama3.1:latest"]);
        Assert.Equal("llama3.1:latest", picked);
    }
}

public class FileSearchPatternTests
{
    [Fact]
    public void Spaces_become_wildcards()
    {
        Assert.Equal("*tax*PDF*", FileSearchPattern.Glob("tax PDF"));
        Assert.Equal("*return*", FileSearchPattern.Glob("return"));
    }
}

public class FileHuntTests
{
    [Fact]
    public void Finds_tax_pdf_from_spaced_query()
    {
        var root = Path.Combine(Path.GetTempPath(), "heirloom-hunt-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        var file = Path.Combine(root, "tax_return.pdf");
        File.WriteAllText(file, "x");
        try
        {
            var result = FileHunt.Search([root], "tax PDF", TimeSpan.FromSeconds(3), 20);
            Assert.Contains(result.Hits, h => h.Equals(file, StringComparison.OrdinalIgnoreCase));
            Assert.False(result.TimedOut);
        }
        finally
        {
            try { Directory.Delete(root, true); } catch { /* temp */ }
        }
    }

    [Fact]
    public void Cancelled_search_reports_timeout()
    {
        var root = Path.Combine(Path.GetTempPath(), "heirloom-hunt-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        File.WriteAllText(Path.Combine(root, "a.txt"), "x");
        try
        {
            using var cts = new CancellationTokenSource();
            cts.Cancel();
            var result = FileHunt.Search([root], "a", TimeSpan.FromSeconds(5), 20, cts.Token);
            Assert.True(result.TimedOut || result.Hits.Count == 0);
        }
        finally
        {
            try { Directory.Delete(root, true); } catch { /* temp */ }
        }
    }
}

public class StartMenuHuntTests
{
    [Fact]
    public void Matches_shortcut_tokens()
    {
        var root = Path.Combine(Path.GetTempPath(), "heirloom-start-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        var lnk = Path.Combine(root, "Visual Studio Code.lnk");
        File.WriteAllBytes(lnk, [0]);
        try
        {
            var hit = StartMenuHunt.FindShortcut("visual studio code", TimeSpan.FromSeconds(2), [root]);
            Assert.Equal(lnk, hit);
        }
        finally
        {
            try { Directory.Delete(root, true); } catch { /* temp */ }
        }
    }
}

public class LiveOllamaTests
{
    [Fact]
    public async Task Tags_prefer_llama_over_llava_when_both_present()
    {
        using var http = new HttpClient { Timeout = TimeSpan.FromSeconds(3) };
        HttpResponseMessage response;
        try
        {
            response = await http.GetAsync("http://127.0.0.1:11434/api/tags");
        }
        catch
        {
            return;
        }

        if (!response.IsSuccessStatusCode)
        {
            return;
        }

        var json = await response.Content.ReadAsStringAsync();
        using var doc = System.Text.Json.JsonDocument.Parse(json);
        var names = new List<string>();
        if (doc.RootElement.TryGetProperty("models", out var models))
        {
            foreach (var model in models.EnumerateArray())
            {
                if (model.TryGetProperty("name", out var name) && name.GetString() is { Length: > 0 } n)
                {
                    names.Add(n);
                }
            }
        }

        if (names.Count == 0)
        {
            return;
        }

        var picked = ModelPicker.PickGenerate(names);
        Assert.False(string.IsNullOrWhiteSpace(picked));
        if (names.Any(n => n.Contains("llama3.1", StringComparison.OrdinalIgnoreCase))
            && names.Any(n => n.Contains("llava", StringComparison.OrdinalIgnoreCase)))
        {
            Assert.Contains("llama3.1", picked, StringComparison.OrdinalIgnoreCase);
        }
    }
}

public class WebIntentTests
{
    [Theory]
    [InlineData("open youtube", "https://www.youtube.com", "YouTube")]
    [InlineData("open YouTube", "https://www.youtube.com", "YouTube")]
    [InlineData("open a browser and go to YouTube", "https://www.youtube.com", "YouTube")]
    [InlineData("please open gmail", "https://mail.google.com", "Gmail")]
    [InlineData("go to gmail", "https://mail.google.com", "Gmail")]
    [InlineData("open a new tab and go to YouTube", "https://www.youtube.com", "YouTube")]
    [InlineData("go to github.com", "https://github.com", "GitHub")]
    [InlineData("Go to YouTube", "https://www.youtube.com", "YouTube")]
    [InlineData("take me to YouTube", "https://www.youtube.com", "YouTube")]
    [InlineData("visit reddit", "https://www.reddit.com", "Reddit")]
    [InlineData("navigate to wikipedia", "https://en.wikipedia.org", "Wikipedia")]
    [InlineData("Open a browser and go to YouTube.", "https://www.youtube.com", "YouTube")]
    public void Parses_common_open_requests(string utterance, string url, string label)
    {
        Assert.True(WebIntent.TryParse(utterance, out var intent));
        Assert.Equal("open", intent.Action);
        Assert.Equal(url, intent.Url);
        Assert.Equal(label, intent.Label);
    }

    [Fact]
    public void Search_on_google_is_a_search_url()
    {
        Assert.True(WebIntent.TryParse("search for weather on Google", out var intent));
        Assert.Equal("search", intent.Action);
        Assert.Equal("weather", intent.Query);
        Assert.StartsWith("https://www.google.com/search?q=", intent.Url);
        Assert.Contains("weather", intent.Url);
    }

    [Fact]
    public void Search_youtube_for_query()
    {
        Assert.True(WebIntent.TryParse("Search YouTube for lo-fi piano", out var intent));
        Assert.Equal("search", intent.Action);
        Assert.Equal("YouTube", intent.Label);
        Assert.Equal("lo-fi piano", intent.Query);
        Assert.Contains("youtube.com/results", intent.Url, StringComparison.OrdinalIgnoreCase);
        Assert.Equal(WebIntent.OpeningBrowser, intent.OpeningLine);
        Assert.Equal("Searching YouTube for “lo-fi piano”…", intent.WorkingLine);
        Assert.Equal("Done — searched YouTube for “lo-fi piano”.", intent.DoneLine);
    }

    [Fact]
    public void Open_google_and_search_for_query()
    {
        Assert.True(WebIntent.TryParse("Open Google and search for weather", out var intent));
        Assert.Equal("search", intent.Action);
        Assert.Equal("Google", intent.Label);
        Assert.Equal("weather", intent.Query);
        Assert.StartsWith("https://www.google.com/search?q=", intent.Url);
        Assert.Equal("Searching Google for “weather”…", intent.WorkingLine);
        Assert.Equal("Done — searched Google for “weather”.", intent.DoneLine);
    }

    [Fact]
    public void Open_youtube_and_search_for_query()
    {
        Assert.True(WebIntent.TryParse("open YouTube and search for cats", out var intent));
        Assert.Equal("search", intent.Action);
        Assert.Contains("cats", intent.Url);
        Assert.Contains("youtube.com/results", intent.Url, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public void Status_copy_for_open_youtube()
    {
        Assert.True(WebIntent.TryParse("Open a browser and go to YouTube", out var intent));
        Assert.Equal("Opening browser…", intent.OpeningLine);
        Assert.Equal("Navigating to YouTube…", intent.WorkingLine);
        Assert.Equal("Done — YouTube is open.", intent.DoneLine);
        Assert.Contains("Could not open YouTube", intent.FailLine);
    }

    [Fact]
    public void Open_and_click_keeps_the_site()
    {
        Assert.True(WebIntent.TryParse("open youtube and click the first video", out var intent));
        Assert.Equal("open", intent.Action);
        Assert.Equal("https://www.youtube.com", intent.Url);
        Assert.Equal("click", intent.ThenAction);
        Assert.Contains("first video", intent.ThenTarget, StringComparison.OrdinalIgnoreCase);
        Assert.Contains("Navigating to YouTube", intent.WorkingLine);
    }

    [Fact]
    public void Search_then_click_keeps_the_query()
    {
        Assert.True(WebIntent.TryParse("Search YouTube for cats and click the first video", out var intent));
        Assert.Equal("search", intent.Action);
        Assert.Equal("cats", intent.Query);
        Assert.Equal("click", intent.ThenAction);
        Assert.Contains("first video", intent.ThenTarget, StringComparison.OrdinalIgnoreCase);
        Assert.Contains("Searching YouTube", intent.WorkingLine);
    }

    [Fact]
    public void Google_query_shorthand()
    {
        Assert.True(WebIntent.TryParse("google weather in Austin", out var intent));
        Assert.Equal("search", intent.Action);
        Assert.Equal("Google", intent.Label);
        Assert.Equal("weather in Austin", intent.Query);
    }

    [Fact]
    public void Fill_search_box_is_a_page_action()
    {
        Assert.True(WebIntent.TryParse("fill the search box with hello", out var intent));
        Assert.Equal("type", intent.Action);
        Assert.Equal("hello", intent.ThenText);
        Assert.Equal("Typing into “search box”…", intent.WorkingLine);
        Assert.Equal(intent.OpeningLine, intent.WorkingLine);
    }

    [Fact]
    public void Scroll_back_reload_are_page_actions()
    {
        Assert.True(WebIntent.TryParse("scroll down", out var down));
        Assert.Equal("scroll", down.Action);
        Assert.True(WebIntent.TryParse("go back", out var back));
        Assert.Equal("back", back.Action);
        Assert.True(WebIntent.TryParse("reload the page", out var reload));
        Assert.Equal("reload", reload.Action);
    }

    [Fact]
    public void Click_only_is_a_page_action()
    {
        Assert.True(WebIntent.TryParse("click the first link", out var intent));
        Assert.Equal("click", intent.Action);
        Assert.Contains("first link", intent.ThenTarget, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public void Type_into_search_is_a_page_action()
    {
        Assert.True(WebIntent.TryParse("type hello into the search box", out var intent));
        Assert.Equal("type", intent.Action);
        Assert.Equal("hello", intent.ThenText);
    }

    [Fact]
    public void Youtube_search_stays_on_youtube()
    {
        Assert.True(WebIntent.TryParse("search youtube for cats", out var intent));
        Assert.Contains("youtube.com/results", intent.Url, StringComparison.OrdinalIgnoreCase);
        Assert.Contains("cats", intent.Url);
    }

    [Fact]
    public void Bare_search_for_file_is_not_the_web()
    {
        Assert.False(WebIntent.TryParse("search for tax PDF", out _));
        Assert.False(WebIntent.TryParse("find the file return", out _));
    }

    [Fact]
    public void Open_notepad_stays_an_app()
    {
        Assert.False(WebIntent.TryParse("open notepad", out _));
        Assert.False(WebIntent.TryParse("open visual studio code", out _));
        Assert.False(WebIntent.TryParse("open chrome", out _));
    }

    [Fact]
    public void Open_browser_alone_goes_to_google()
    {
        Assert.True(WebIntent.TryParse("open a browser", out var intent));
        Assert.Equal("https://www.google.com", intent.Url);
    }

    [Fact]
    public void Page_control_words_are_detected()
    {
        Assert.True(WebIntent.NeedsPageControl("open youtube and click the first video"));
        Assert.False(WebIntent.NeedsPageControl("open youtube"));
    }
}

