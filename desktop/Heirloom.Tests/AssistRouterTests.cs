using Heirloom.Services;
using Xunit;

namespace Heirloom.Tests;

public class AssistRouterTests
{
    private static AssistInventory Inventory(params string[] models) =>
        new(
            OllamaReady: true,
            models,
            "ready",
            LlamaCppReady: false,
            [],
            "llama.cpp server is not running.",
            CloudEnabled: false,
            CloudHasKey: false,
            "",
            "");

    private static AssistSettings Auto(string opinion = "off") =>
        new(
            "auto",
            "ollama",
            "",
            opinion,
            false,
            "",
            "",
            false,
            AssistRouter.DefaultChains);

    [Fact]
    public void Classify_routes_code_research_reasoning_chat_and_vision()
    {
        Assert.Equal("chat", AssistRouter.Classify("hi"));
        Assert.Equal("code", AssistRouter.Classify("refactor the auth middleware"));
        Assert.Equal("reasoning", AssistRouter.Classify("plan the archive layout"));
        Assert.Equal("research", AssistRouter.Classify("what is the latest on local whisper"));
        Assert.Equal("vision", AssistRouter.Classify("look at this screenshot"));
        Assert.Equal("vision", AssistRouter.Classify("hello", hasImage: true));
        Assert.Equal("code", AssistRouter.Classify("plan a refactor of the parser"));
        Assert.Equal("code", AssistRouter.Classify("migrate the auth table"));
        Assert.Equal("code", AssistRouter.Classify("rewrite the payment check"));
    }

    [Fact]
    public void Model_match_is_exact_or_tag_not_a_sibling_family()
    {
        Assert.True(AssistRouter.ModelMatches("qwen2.5-coder", "qwen2.5-coder:32b"));
        Assert.True(AssistRouter.ModelMatches("qwen2.5-coder:7b", "qwen2.5-coder:7b"));
        Assert.False(AssistRouter.ModelMatches("qwen3", "qwen3-coder:30b"));
        Assert.False(AssistRouter.ModelMatches("qwen2.5:3b", "qwen2.5:7b"));
        Assert.False(AssistRouter.ModelMatches("deepseek-coder", "deepseek-coder-v2"));
    }

    [Fact]
    public void Risky_code_requests_a_second_opinion_only_in_auto()
    {
        Assert.True(AssistRouter.WantsSecondOpinion("delete the auth middleware and refactor it", "code", "auto"));
        Assert.False(AssistRouter.WantsSecondOpinion("rename this function", "code", "auto"));
        Assert.True(AssistRouter.WantsSecondOpinion("rename this function", "code", "always"));
        Assert.False(AssistRouter.WantsSecondOpinion("delete the auth middleware", "code", "off"));
        Assert.False(AssistRouter.WantsSecondOpinion("delete the file on the desktop", "chat", "always"));
    }

    [Fact]
    public async Task Auto_names_the_preferred_installed_model()
    {
        var calls = new List<string>();
        var answer = await AssistRouter.RunAsync(
            "refactor parse()",
            "sys",
            Auto(),
            Inventory("qwen3-coder:30b", "qwen2.5-coder:7b", "llama3.1:8b"),
            (backend, model, _, _) =>
            {
                calls.Add(backend + "/" + model);
                return Task.FromResult("preferred");
            },
            CancellationToken.None);

        Assert.Equal("qwen3-coder:30b", answer.Model);
        Assert.Equal("ollama", answer.Backend);
        Assert.Contains("qwen3-coder:30b", answer.Badge);
        Assert.DoesNotContain("fallback", answer.Badge);
        Assert.False(answer.Degraded);
        Assert.Equal(["ollama/qwen3-coder:30b"], calls);
    }

    [Fact]
    public async Task Unsized_spec_prefers_the_larger_installed_tag()
    {
        var settings = Auto() with
        {
            Routes = new Dictionary<string, IReadOnlyList<AssistSlot>>
            {
                ["code"] = [new AssistSlot("ollama", "qwen2.5-coder")],
            },
        };
        var answer = await AssistRouter.RunAsync(
            "refactor parse()",
            "sys",
            settings,
            Inventory("qwen2.5-coder:32b", "qwen2.5-coder:7b", "qwen2.5:3b", "deepseek-r1:14b", "llava:7b"),
            (_, _, _, _) => Task.FromResult("larger"),
            CancellationToken.None);
        Assert.Equal("qwen2.5-coder:32b", answer.Model);
        Assert.False(answer.Degraded);
    }

    [Fact]
    public async Task Missing_preferred_model_falls_back_loudly()
    {
        var answer = await AssistRouter.RunAsync(
            "refactor parse()",
            "sys",
            Auto(),
            Inventory("qwen2.5-coder:7b"),
            (_, _, _, _) => Task.FromResult("smaller coder"),
            CancellationToken.None);
        Assert.Equal("qwen2.5-coder:7b", answer.Model);
        Assert.True(answer.Degraded);
        Assert.Contains("fallback", answer.Badge);
        Assert.Contains("qwen3-coder", answer.Badge);
        Assert.Contains("not installed", answer.Badge);
    }

    [Fact]
    public async Task Http_failure_tries_the_next_model_and_records_it()
    {
        var answer = await AssistRouter.RunAsync(
            "refactor parse()",
            "sys",
            Auto(),
            Inventory("qwen2.5-coder:32b", "qwen2.5-coder:7b", "qwen2.5:3b", "deepseek-r1:14b", "llava:7b"),
            (_, model, _, _) => model == "qwen2.5-coder:32b"
                ? throw new InvalidOperationException("connection reset")
                : Task.FromResult("recovered"),
            CancellationToken.None);
        Assert.Equal("recovered", answer.Reply);
        Assert.Equal("qwen2.5-coder:7b", answer.Model);
        Assert.Contains(answer.Attempts, row => row.Status == "failed" && row.Model == "qwen2.5-coder:32b");
        Assert.Contains("connection reset", answer.Badge);
    }

    [Fact]
    public async Task Exhausted_chain_raises_and_does_not_substitute()
    {
        var calls = 0;
        var ex = await Assert.ThrowsAsync<AssistRouteException>(() => AssistRouter.RunAsync(
            "refactor parse()",
            "sys",
            Auto(),
            new AssistInventory(false, [], "Ollama is not running.", false, [], "llama.cpp server is not running.", false, false, "", ""),
            (_, _, _, _) =>
            {
                calls++;
                return Task.FromResult("nope");
            },
            CancellationToken.None));
        Assert.Contains("Nothing else was substituted.", ex.Message);
        Assert.Contains("did not run", ex.Message);
        Assert.Equal(0, calls);
    }

    [Fact]
    public async Task Manual_override_does_not_fall_back()
    {
        var settings = Auto() with { Picker = "manual", ManualBackend = "ollama", ManualModel = "missing-coder" };
        var calls = 0;
        var ex = await Assert.ThrowsAsync<AssistRouteException>(() => AssistRouter.RunAsync(
            "refactor parse()",
            "sys",
            settings,
            Inventory("qwen2.5-coder:7b"),
            (_, _, _, _) =>
            {
                calls++;
                return Task.FromResult("nope");
            },
            CancellationToken.None));
        Assert.Contains("missing-coder", ex.Message);
        Assert.Equal(0, calls);
    }

    [Fact]
    public async Task Cloud_slot_is_skipped_until_opt_in_and_key()
    {
        var routes = new Dictionary<string, IReadOnlyList<AssistSlot>>(AssistRouter.DefaultChains)
        {
            ["code"] =
            [
                new AssistSlot("cloud", "cloud-coder"),
                new AssistSlot("ollama", "qwen2.5-coder:7b"),
            ],
        };
        var off = Auto() with { Routes = routes };
        var answer = await AssistRouter.RunAsync(
            "refactor parse()",
            "sys",
            off,
            Inventory("qwen2.5-coder:7b"),
            (backend, _, _, _) =>
            {
                Assert.NotEqual("cloud", backend);
                return Task.FromResult("local");
            },
            CancellationToken.None);
        Assert.Equal("ollama", answer.Backend);
        Assert.Contains("Cloud opt-in is off.", answer.Badge);

        var on = off with
        {
            CloudEnabled = true,
            CloudHasKey = true,
            CloudBaseUrl = "https://example.invalid/v1",
            CloudModel = "cloud-coder",
            Routes = new Dictionary<string, IReadOnlyList<AssistSlot>>
            {
                ["code"] = [new AssistSlot("cloud", "cloud-coder")],
            },
        };
        var cloudInv = new AssistInventory(false, [], "down", false, [], "down", true, true, "https://example.invalid/v1", "cloud-coder");
        var cloud = await AssistRouter.RunAsync(
            "refactor parse()",
            "sys",
            on,
            cloudInv,
            (_, model, _, _) => Task.FromResult(model == "cloud-coder" ? "from the cloud" : "nope"),
            CancellationToken.None);
        Assert.Equal("from the cloud", cloud.Reply);
        Assert.Equal("cloud", cloud.Backend);
    }

    [Fact]
    public async Task Second_opinion_runs_two_models_and_a_judge()
    {
        var calls = new List<string>();
        var answer = await AssistRouter.RunAsync(
            "refactor and delete the auth check",
            "sys",
            Auto("auto"),
            Inventory("qwen2.5-coder:32b", "qwen2.5-coder:7b", "qwen2.5:3b", "deepseek-r1:14b", "llava:7b"),
            (_, model, _, _) =>
            {
                calls.Add(model);
                return Task.FromResult(model switch
                {
                    "qwen2.5-coder:32b" => "draft A",
                    "qwen2.5-coder:7b" => "draft B",
                    _ => "merged safely",
                });
            },
            CancellationToken.None);
        Assert.True(answer.SecondOpinion);
        Assert.Equal("merged safely", answer.Reply);
        Assert.Equal("draft A", answer.Primary?.Text);
        Assert.Equal("draft B", answer.Second?.Text);
        Assert.Contains("judge", answer.Badge);
        Assert.Contains("deepseek-r1:14b", answer.Badge);
        Assert.Equal(["qwen2.5-coder:32b", "qwen2.5-coder:7b", "deepseek-r1:14b"], calls);
    }

    [Fact]
    public async Task Second_opinion_fails_loudly_when_only_one_code_model_exists()
    {
        var calls = 0;
        var ex = await Assert.ThrowsAsync<AssistRouteException>(() => AssistRouter.RunAsync(
            "migrate the auth table",
            "sys",
            Auto("always"),
            Inventory("qwen2.5-coder:7b"),
            (_, _, _, _) =>
            {
                calls++;
                return Task.FromResult("only one");
            },
            CancellationToken.None));
        Assert.Contains("two different code models", ex.Message);
        Assert.Equal(0, calls);
    }

    [Fact]
    public async Task Judge_failure_still_shows_both_drafts()
    {
        var answer = await AssistRouter.RunAsync(
            "rewrite the payment check",
            "sys",
            Auto("always"),
            Inventory("qwen2.5-coder:32b", "qwen2.5-coder:7b", "qwen2.5:3b", "deepseek-r1:14b", "llava:7b"),
            (_, model, _, _) => model == "deepseek-r1:14b"
                ? throw new InvalidOperationException("judge down")
                : Task.FromResult(model == "qwen2.5-coder:32b" ? "draft A" : "draft B"),
            CancellationToken.None);
        Assert.False(string.IsNullOrWhiteSpace(answer.Error));
        Assert.Contains("draft A", answer.Reply);
        Assert.Contains("draft B", answer.Reply);
        Assert.Contains("judge failed", answer.Badge);
        Assert.Equal("qwen2.5-coder:32b", answer.Primary?.Model);
    }

    [Fact]
    public void Install_tiers_map_to_assist_dev_models()
    {
        Assert.Null(DiskProfiles.Resolve("small").DevModels);
        Assert.DoesNotContain("assist", DiskProfiles.Resolve("small").ProvisionFeatures);
        Assert.Equal(AssistDevModels.Medium, DiskProfiles.Resolve("medium").DevModels);
        Assert.Contains("assist", DiskProfiles.Resolve("medium").ProvisionFeatures);
        Assert.Equal(AssistDevModels.Large, DiskProfiles.Resolve("large").DevModels);
        Assert.Contains("qwen2.5-coder:32b", DiskProfiles.Resolve("large").DevModels!);
        Assert.Contains("qwen3-coder", DiskProfiles.Resolve("dedicated").DevModels!);
        Assert.Contains("deepseek-coder-v2", DiskProfiles.Resolve("dedicated").DevModels!);
        Assert.True(AssistDevModels.Large.All(tag => AssistDevModels.Dedicated.Contains(tag)));
    }

    [Fact]
    public void OpenAi_base_appends_v1_once()
    {
        Assert.Equal("http://127.0.0.1:11434/v1/chat/completions", AssistRouter.OpenAiChatUrl("http://127.0.0.1:11434"));
        Assert.Equal("http://127.0.0.1:8080/v1/chat/completions", AssistRouter.OpenAiChatUrl("http://127.0.0.1:8080/v1"));
    }
}
