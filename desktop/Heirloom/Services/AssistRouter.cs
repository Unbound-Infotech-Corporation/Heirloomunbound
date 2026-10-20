using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace Heirloom.Services;

/// <summary>
/// Assist task router for Heirloom Unbound. Mirrors backend/assist_router.py:
/// classify, pick a local model, fall back loudly, optional second opinion.
/// Twin routing stays in the twin path and is not used here.
/// </summary>
public static class AssistDevModels
{
    public static IReadOnlyList<string> Small { get; } = [];

    public static IReadOnlyList<string> Medium { get; } =
        ["qwen2.5-coder:7b", "qwen2.5:3b"];

    public static IReadOnlyList<string> Large { get; } =
    [
        "qwen2.5-coder:7b",
        "qwen2.5-coder:32b",
        "deepseek-r1:14b",
        "qwen2.5:3b",
        "qwen2.5vl:7b",
    ];

    public static IReadOnlyList<string> Dedicated { get; } =
    [
        "qwen2.5-coder:7b",
        "qwen2.5-coder:32b",
        "qwen3-coder",
        "deepseek-coder-v2",
        "deepseek-r1:14b",
        "deepseek-r1:32b",
        "qwen2.5:3b",
        "qwen2.5vl:7b",
    ];
}

public sealed class AssistRouteException : Exception
{
    public AssistRouteException(string message, string category, string badge, IReadOnlyList<AssistAttempt> attempts)
        : base(message)
    {
        Category = category;
        Badge = badge;
        Attempts = attempts;
    }

    public string Category { get; }
    public string Badge { get; }
    public IReadOnlyList<AssistAttempt> Attempts { get; }
}

public sealed record AssistAttempt(string Backend, string Model, string Status, string Reason);

public sealed record AssistSlot(string Backend, string Model);

public sealed record AssistTurn(string Role, string Content);

public sealed record AssistDraft(string Backend, string Model, string Text);

public sealed record AssistCandidate(string Backend, string Model, string Requested, IReadOnlyList<AssistAttempt> PriorMisses);

public sealed record AssistInventory(
    bool OllamaReady,
    IReadOnlyList<string> OllamaModels,
    string OllamaReason,
    bool LlamaCppReady,
    IReadOnlyList<string> LlamaCppModels,
    string LlamaCppReason,
    bool CloudEnabled,
    bool CloudHasKey,
    string CloudBaseUrl,
    string CloudModel)
{
    public static AssistInventory FromOllama(
        bool reachable,
        IReadOnlyList<string> models,
        string? reason,
        AssistSettings settings)
    {
        var names = models.Where(m => !string.IsNullOrWhiteSpace(m)).Select(m => m.Trim()).ToArray();
        return new AssistInventory(
            reachable || names.Length > 0,
            names,
            string.IsNullOrWhiteSpace(reason) ? "Ollama is not running." : reason,
            LlamaCppReady: false,
            LlamaCppModels: [],
            LlamaCppReason: "llama.cpp server is not running.",
            settings.CloudEnabled,
            settings.CloudHasKey,
            settings.CloudBaseUrl,
            settings.CloudModel);
    }
}

public sealed record AssistSettings(
    string Picker,
    string ManualBackend,
    string ManualModel,
    string SecondOpinion,
    bool CloudEnabled,
    string CloudBaseUrl,
    string CloudModel,
    bool CloudHasKey,
    IReadOnlyDictionary<string, IReadOnlyList<AssistSlot>> Routes)
{
    public static AssistSettings From(AppSettings settings)
    {
        var picker = settings.AssistPicker == "manual" ? "manual" : "auto";
        var manualBackend = settings.AssistManualBackend is "llamacpp" or "cloud" ? settings.AssistManualBackend : "ollama";
        var opinion = settings.AssistSecondOpinion is "off" or "always" ? settings.AssistSecondOpinion : "auto";
        var cloudUrl = (settings.AssistCloudBaseUrl ?? "").Trim();
        if (cloudUrl.Length > 0 && !cloudUrl.StartsWith("http://", StringComparison.OrdinalIgnoreCase)
            && !cloudUrl.StartsWith("https://", StringComparison.OrdinalIgnoreCase))
        {
            cloudUrl = "";
        }

        var cloudModel = SanitizeModel(settings.AssistCloudModel);
        return new AssistSettings(
            picker,
            manualBackend,
            SanitizeModel(settings.AssistManualModel),
            opinion,
            settings.AssistCloudEnabled,
            cloudUrl,
            cloudModel,
            CloudHasKey: !string.IsNullOrWhiteSpace(settings.AssistCloudApiKey),
            new Dictionary<string, IReadOnlyList<AssistSlot>>(StringComparer.Ordinal)
            {
                ["code"] = AssistRouter.ResolveChain(settings.AssistCodeChain, "code"),
                ["reasoning"] = AssistRouter.ResolveChain(settings.AssistReasoningChain, "reasoning"),
                ["research"] = AssistRouter.ResolveChain(settings.AssistResearchChain, "research"),
                ["chat"] = AssistRouter.ResolveChain(settings.AssistChatChain, "chat"),
                ["vision"] = AssistRouter.ResolveChain(settings.AssistVisionChain, "vision"),
            });
    }

    private static string SanitizeModel(string? raw)
    {
        var model = (raw ?? "").Trim();
        if (model.Length == 0 || model.Length > 80 || model.Any(char.IsWhiteSpace))
        {
            return "";
        }

        return model;
    }
}

public sealed class AssistAnswer
{
    public required string Reply { get; init; }
    public required string Badge { get; init; }
    public required string Category { get; init; }
    public required string Backend { get; init; }
    public required string Model { get; init; }
    public required bool Degraded { get; init; }
    public required IReadOnlyList<AssistAttempt> Attempts { get; init; }
    public AssistDraft? Primary { get; init; }
    public AssistDraft? Second { get; init; }
    public string? Error { get; init; }
    public bool SecondOpinion { get; init; }
}

public static class AssistRouter
{
    private static readonly Regex SizeRe = new(@"(\d+(?:\.\d+)?)b", RegexOptions.IgnoreCase | RegexOptions.Compiled);

    private static readonly string[] CodeNeedles =
    [
        "```", ".py", ".cs", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".cpp", ".java",
        "refactor", "compile", "traceback", "stack trace", "pull request", "implement", "debug",
        "unit test", "code review", "git diff", "function", "method", "class ", "bug", "patch",
        "repository", "migrate", "migration", "rewrite", "schema", "middleware", "endpoint", "parser", "diff ",
    ];

    private static readonly string[] ResearchNeedles =
    [
        "look up", "search for", "what is the latest", "what is", "cite", "sources", "research",
        "according to", "news about", "find out",
    ];

    private static readonly string[] ReasoningNeedles =
    [
        "plan", "tradeoff", "trade-off", "architecture", "why should", "why ", "think through",
        "design", "pros and cons", "strategy", "compare",
    ];

    private static readonly string[] VisionNeedles =
    [
        "screenshot", "look at the screen", "look at this image", "look at this picture",
        "what's on my screen", "what is on my screen", "what's on the screen", "see the screen",
        "this image", "this picture", "see_screen",
    ];

    private static readonly string[] RiskNeedles =
    [
        "delete", "drop table", "drop column", "migration", "migrate", "auth", "password", "secret",
        "credential", "api key", "production", "force push", "rm -rf", "rewrite", "payment", "billing",
        "sudo ", "chmod ", "security", "deploy",
    ];

    public static IReadOnlyDictionary<string, string> Labels { get; } = new Dictionary<string, string>
    {
        ["code"] = "Code",
        ["reasoning"] = "Reasoning",
        ["research"] = "Research",
        ["chat"] = "Quick chat",
        ["vision"] = "Vision",
    };

    public static IReadOnlyDictionary<string, IReadOnlyList<AssistSlot>> DefaultChains { get; } =
        new Dictionary<string, IReadOnlyList<AssistSlot>>
        {
            ["code"] =
            [
                new("ollama", "qwen3-coder"),
                new("ollama", "deepseek-coder-v2"),
                new("ollama", "qwen2.5-coder"),
                new("llamacpp", "qwen3-coder"),
                new("llamacpp", "deepseek-coder"),
            ],
            ["reasoning"] =
            [
                new("ollama", "deepseek-r1"),
                new("ollama", "qwen3"),
                new("llamacpp", "deepseek-r1"),
                new("ollama", "llama3.1"),
            ],
            ["research"] =
            [
                new("ollama", "qwen3"),
                new("ollama", "llama3.1"),
                new("llamacpp", "qwen3"),
            ],
            ["chat"] =
            [
                new("ollama", "qwen2.5:3b"),
                new("ollama", "llama3.2:3b"),
                new("llamacpp", "qwen2.5-3b"),
                new("ollama", "llama3.2"),
            ],
            ["vision"] =
            [
                new("ollama", "qwen2.5vl"),
                new("ollama", "llava"),
                new("llamacpp", "llava"),
            ],
        };

    public static string FormatChain(IReadOnlyList<AssistSlot> slots) =>
        string.Join("\n", slots.Select(s => s.Backend + "/" + s.Model));

    public static IReadOnlyList<AssistSlot> ResolveChain(string? raw, string category)
    {
        if (string.IsNullOrWhiteSpace(raw))
        {
            return DefaultChains[category];
        }

        return ParseChain(raw);
    }

    public static IReadOnlyList<AssistSlot> ParseChain(string raw)
    {
        var slots = new List<AssistSlot>();
        foreach (var part in raw.Split([',', '\n', ';'], StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
        {
            var slash = part.IndexOf('/');
            if (slash <= 0)
            {
                continue;
            }

            var backend = part[..slash].Trim().ToLowerInvariant();
            var model = part[(slash + 1)..].Trim();
            if (backend is not ("ollama" or "llamacpp" or "cloud"))
            {
                continue;
            }

            if (model.Length == 0 || model.Length > 80 || model.Any(char.IsWhiteSpace))
            {
                continue;
            }

            slots.Add(new AssistSlot(backend, model));
            if (slots.Count == 6)
            {
                break;
            }
        }

        return slots;
    }

    public static bool ModelMatches(string spec, string installed)
    {
        var wanted = (spec ?? "").Trim().ToLowerInvariant();
        var name = (installed ?? "").Trim().ToLowerInvariant();
        if (wanted.Length == 0 || name.Length == 0)
        {
            return false;
        }

        return name == wanted || name.StartsWith(wanted + ":", StringComparison.Ordinal);
    }

    public static string Classify(string? text, bool hasImage = false)
    {
        if (hasImage)
        {
            return "vision";
        }

        var blob = (text ?? "").Trim().ToLowerInvariant();
        if (VisionNeedles.Any(n => blob.Contains(n, StringComparison.Ordinal)))
        {
            return "vision";
        }

        if (CodeNeedles.Any(n => blob.Contains(n, StringComparison.Ordinal)))
        {
            return "code";
        }

        if (ResearchNeedles.Any(n => blob.Contains(n, StringComparison.Ordinal)))
        {
            return "research";
        }

        if (ReasoningNeedles.Any(n => blob.Contains(n, StringComparison.Ordinal)))
        {
            return "reasoning";
        }

        return "chat";
    }

    public static bool IsRiskyCode(string? text)
    {
        var blob = (text ?? "").ToLowerInvariant();
        return RiskNeedles.Any(n => blob.Contains(n, StringComparison.Ordinal));
    }

    public static bool WantsSecondOpinion(string? text, string category, string mode)
    {
        if (category != "code" || mode == "off")
        {
            return false;
        }

        if (mode == "always")
        {
            return true;
        }

        return IsRiskyCode(text);
    }

    public static string OpenAiChatUrl(string? baseUrl)
    {
        var raw = (baseUrl ?? "").Trim().TrimEnd('/');
        if (raw.Length == 0)
        {
            return "";
        }

        if (raw.EndsWith("/v1", StringComparison.OrdinalIgnoreCase))
        {
            return raw + "/chat/completions";
        }

        return raw + "/v1/chat/completions";
    }

    public static async Task<AssistAnswer> RunAsync(
        string text,
        string system,
        AssistSettings settings,
        AssistInventory inventory,
        Func<string, string, IReadOnlyList<AssistTurn>, CancellationToken, Task<string>> complete,
        CancellationToken cancellationToken,
        string? judgeSystem = null)
    {
        var category = Classify(text);
        var chain = ChainFor(settings, category);
        if (settings.Picker == "manual" && string.IsNullOrWhiteSpace(settings.ManualModel))
        {
            throw Fail(category, [], "Manual Assist override has no model. Choose one, or switch the picker to Auto.");
        }

        if (chain.Count == 0)
        {
            throw Fail(category, [], "The " + Label(category) + " route is empty.");
        }

        var (candidates, misses) = Expand(chain, inventory);
        var opinion = WantsSecondOpinion(text, category, settings.SecondOpinion);
        var manualNote = "";
        if (settings.Picker == "manual" && opinion)
        {
            opinion = false;
            manualNote = "second opinion skipped: manual override is one model";
        }

        if (opinion && candidates.Count < 2)
        {
            var only = candidates.Count == 0 ? "none" : candidates[0].Model;
            throw Fail(category, misses, "Second opinion needs two different code models. Only " + only + " is available.");
        }

        if (candidates.Count == 0)
        {
            throw Fail(category, misses);
        }

        var messages = new List<AssistTurn> { new("system", system), new("user", text) };
        if (!opinion)
        {
            var pool = settings.Picker == "manual" ? candidates.Take(1).ToList() : candidates;
            var (reply, chosen, attempts) = await RunCandidates(
                pool, [], messages, complete, category, allowFallback: settings.Picker != "manual",  cancellationToken).ConfigureAwait(false);
            var failed = attempts.Where(a => a.Status == "failed").ToList();
            var prior = chosen.PriorMisses.ToList();
            var runs = new[] { new AssistDraft(chosen.Backend, chosen.Model, reply) };
            var badge = FormatBadge(category, runs, prior.Concat(failed).ToList(), null, manualNote);
            return new AssistAnswer
            {
                Reply = reply,
                Badge = badge,
                Category = category,
                Backend = chosen.Backend,
                Model = chosen.Model,
                Degraded = prior.Count > 0 || failed.Count > 0 || manualNote.Length > 0,
                Attempts = prior.Concat(attempts).ToList(),
                Primary = runs[0],
                SecondOpinion = false,
            };
        }

        var collected = new List<(AssistCandidate Candidate, string Reply)>();
        var runtime = new List<AssistAttempt>();
        var pending = candidates.ToList();
        while (pending.Count > 0 && collected.Count < 2)
        {
            var candidate = pending[0];
            pending.RemoveAt(0);
            try
            {
                var reply = await complete(candidate.Backend, candidate.Model, messages, cancellationToken).ConfigureAwait(false);
                runtime.Add(new AssistAttempt(candidate.Backend, candidate.Model, "ran", "answered"));
                collected.Add((candidate, reply));
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                runtime.Add(new AssistAttempt(candidate.Backend, candidate.Model, "failed", ex.Message));
            }
        }

        if (collected.Count < 2)
        {
            var tail = candidates.Count == 0 ? runtime : candidates[^1].PriorMisses.Concat(runtime).ToList();
            throw Fail(category, tail, "Second opinion needs two different code models. A second call did not succeed.");
        }

        var primary = collected[0].Candidate;
        var primaryText = collected[0].Reply;
        var second = collected[1].Candidate;
        var secondText = collected[1].Reply;
        var logged = primary.PriorMisses.Concat(runtime).ToList();
        var judgeChain = settings.Routes.TryGetValue("reasoning", out var reasoning) ? reasoning : DefaultChains["reasoning"];
        var (judgeCandidates, judgeMisses) = Expand(judgeChain, inventory);
        var draftsNote = new AssistDraft(primary.Backend, primary.Model, primaryText);
        var secondDraft = new AssistDraft(second.Backend, second.Model, secondText);
        var runsBoth = new[] { draftsNote, secondDraft };
        if (judgeCandidates.Count == 0)
        {
            var reason = Loud(category: "reasoning", judgeMisses, "No reasoning model is available to judge.");
            return new AssistAnswer
            {
                Reply = Unjudged(draftsNote, secondDraft, reason),
                Badge = FormatBadge(category, runsBoth, logged, null, "judge did not run"),
                Category = category,
                Backend = primary.Backend,
                Model = primary.Model,
                Degraded = true,
                Attempts = logged.Concat(judgeMisses).ToList(),
                Primary = draftsNote,
                Second = secondDraft,
                Error = reason,
                SecondOpinion = true,
            };
        }

        try
        {
            var judgedMessages = new List<AssistTurn>
            {
                new("system", judgeSystem ?? DefaultJudgeSystem),
                new("user", JudgeUser(text, draftsNote, secondDraft)),
            };
            var (judged, judge, judgeAttempts) = await RunCandidates(
                judgeCandidates, judgeMisses, judgedMessages, complete, "reasoning", allowFallback: true, cancellationToken).ConfigureAwait(false);
            var shown = logged.Concat(judgeAttempts).Where(a => a.Status != "ran").ToList();
            return new AssistAnswer
            {
                Reply = judged,
                Badge = FormatBadge(category, runsBoth, shown, new AssistDraft(judge.Backend, judge.Model, judged), ""),
                Category = category,
                Backend = primary.Backend,
                Model = primary.Model,
                Degraded = shown.Count > 0,
                Attempts = logged.Concat(judgeAttempts).ToList(),
                Primary = draftsNote,
                Second = secondDraft,
                SecondOpinion = true,
            };
        }
        catch (AssistRouteException ex)
        {
            return new AssistAnswer
            {
                Reply = Unjudged(draftsNote, secondDraft, ex.Message),
                Badge = FormatBadge(category, runsBoth, logged, null, "judge failed"),
                Category = category,
                Backend = primary.Backend,
                Model = primary.Model,
                Degraded = true,
                Attempts = logged.Concat(ex.Attempts).ToList(),
                Primary = draftsNote,
                Second = secondDraft,
                Error = ex.Message,
                SecondOpinion = true,
            };
        }
    }

    public static async Task<string> CompleteOpenAiAsync(
        HttpClient http,
        string url,
        string model,
        IReadOnlyList<AssistTurn> messages,
        string? apiKey,
        CancellationToken cancellationToken)
    {
        if (string.IsNullOrWhiteSpace(url))
        {
            throw new InvalidOperationException("Cloud base URL is empty.");
        }

        using var request = new HttpRequestMessage(HttpMethod.Post, url);
        if (!string.IsNullOrWhiteSpace(apiKey))
        {
            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", apiKey);
        }

        var payload = JsonSerializer.Serialize(new
        {
            model,
            messages = messages.Select(m => new { role = m.Role, content = m.Content }),
            stream = false,
        });
        request.Content = new StringContent(payload, Encoding.UTF8, "application/json");
        using var response = await http.SendAsync(request, cancellationToken).ConfigureAwait(false);
        var body = await response.Content.ReadAsStringAsync(cancellationToken).ConfigureAwait(false);
        if (!response.IsSuccessStatusCode)
        {
            var snippet = body.Length > 240 ? body[..240] : body;
            throw new InvalidOperationException("HTTP " + (int)response.StatusCode + " (" + model + "): " + snippet.Replace('\n', ' '));
        }

        using var doc = JsonDocument.Parse(body);
        if (!doc.RootElement.TryGetProperty("choices", out var choices) || choices.GetArrayLength() == 0)
        {
            throw new InvalidOperationException("no choices (" + model + ").");
        }

        var content = choices[0].GetProperty("message").GetProperty("content").GetString();
        if (string.IsNullOrWhiteSpace(content))
        {
            throw new InvalidOperationException("empty reply (" + model + ").");
        }

        return content;
    }

    private const string DefaultJudgeSystem =
        "You are the Heirloom Unbound Assist judge. You work for the owner. " +
        "You are not their twin and you do not speak as them. " +
        "Compare the two drafts. Keep the safer change. Do not invent files or biography. " +
        "Return the merged answer the owner should see, then one short note of what you kept from each draft.";

    private static string JudgeUser(string userText, AssistDraft primary, AssistDraft second) =>
        "REQUEST:\n" + userText + "\n\n" +
        "DRAFT A (" + primary.Backend + "/" + primary.Model + "):\n" + primary.Text + "\n\n" +
        "DRAFT B (" + second.Backend + "/" + second.Model + "):\n" + second.Text;

    private static string Unjudged(AssistDraft primary, AssistDraft second, string reason) =>
        "Second opinion did not finish. The judge did not run.\n" + reason + "\n\n" +
        "Primary (" + primary.Backend + "/" + primary.Model + "):\n" + primary.Text + "\n\n" +
        "Second (" + second.Backend + "/" + second.Model + "):\n" + second.Text;

    private static IReadOnlyList<AssistSlot> ChainFor(AssistSettings settings, string category)
    {
        if (settings.Picker == "manual")
        {
            return [new AssistSlot(settings.ManualBackend, settings.ManualModel)];
        }

        return settings.Routes.TryGetValue(category, out var chain) ? chain : [];
    }

    private static (List<AssistCandidate> Candidates, List<AssistAttempt> Misses) Expand(
        IReadOnlyList<AssistSlot> chain,
        AssistInventory inventory)
    {
        var candidates = new List<AssistCandidate>();
        var attempts = new List<AssistAttempt>();
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var slot in chain)
        {
            if (slot.Backend == "cloud")
            {
                if (!inventory.CloudEnabled)
                {
                    attempts.Add(new AssistAttempt("cloud", slot.Model, "skipped", "Cloud opt-in is off."));
                    continue;
                }

                if (!inventory.CloudHasKey)
                {
                    attempts.Add(new AssistAttempt("cloud", slot.Model, "skipped", "Cloud key is missing."));
                    continue;
                }

                if (string.IsNullOrWhiteSpace(inventory.CloudBaseUrl))
                {
                    attempts.Add(new AssistAttempt("cloud", slot.Model, "skipped", "Cloud base URL is empty."));
                    continue;
                }

                if (string.IsNullOrWhiteSpace(inventory.CloudModel))
                {
                    attempts.Add(new AssistAttempt("cloud", slot.Model, "missing", "Cloud model name is empty."));
                    continue;
                }

                if (!ModelMatches(slot.Model, inventory.CloudModel))
                {
                    attempts.Add(new AssistAttempt("cloud", slot.Model, "missing", "Cloud model is " + inventory.CloudModel + ", not " + slot.Model + "."));
                    continue;
                }

                var cloudKey = "cloud/" + inventory.CloudModel;
                if (!seen.Add(cloudKey))
                {
                    continue;
                }

                candidates.Add(new AssistCandidate("cloud", inventory.CloudModel, slot.Model, attempts.ToArray()));
                continue;
            }

            bool ready;
            IReadOnlyList<string> names;
            string why;
            if (slot.Backend == "ollama")
            {
                ready = inventory.OllamaReady;
                names = inventory.OllamaModels;
                why = inventory.OllamaReason;
            }
            else if (slot.Backend == "llamacpp")
            {
                ready = inventory.LlamaCppReady;
                names = inventory.LlamaCppModels;
                why = inventory.LlamaCppReason;
            }
            else
            {
                attempts.Add(new AssistAttempt(slot.Backend, slot.Model, "skipped", "Unknown backend."));
                continue;
            }

            if (!ready)
            {
                attempts.Add(new AssistAttempt(slot.Backend, slot.Model, "unavailable", why));
                continue;
            }

            var matches = names.Where(n => ModelMatches(slot.Model, n)).OrderByDescending(SizeKey).ToList();
            if (matches.Count == 0)
            {
                attempts.Add(new AssistAttempt(slot.Backend, slot.Model, "missing", slot.Model + " is not installed."));
                continue;
            }

            foreach (var name in matches)
            {
                if (!seen.Add(slot.Backend + "/" + name))
                {
                    continue;
                }

                candidates.Add(new AssistCandidate(slot.Backend, name, slot.Model, attempts.ToArray()));
            }
        }

        return (candidates, attempts);
    }

    private static double SizeKey(string name)
    {
        var match = SizeRe.Match(name);
        return match.Success && double.TryParse(match.Groups[1].Value, System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out var size)
            ? size
            : 0;
    }

    private static async Task<(string Reply, AssistCandidate Chosen, List<AssistAttempt> Attempts)> RunCandidates(
        IReadOnlyList<AssistCandidate> candidates,
        IReadOnlyList<AssistAttempt> prior,
        IReadOnlyList<AssistTurn> messages,
        Func<string, string, IReadOnlyList<AssistTurn>, CancellationToken, Task<string>> complete,
        string category,
        bool allowFallback,
        CancellationToken cancellationToken)
    {
        var attempts = prior.ToList();
        var limit = allowFallback ? candidates.Count : Math.Min(1, candidates.Count);
        for (var i = 0; i < limit; i++)
        {
            var candidate = candidates[i];
            try
            {
                var reply = await complete(candidate.Backend, candidate.Model, messages, cancellationToken).ConfigureAwait(false);
                attempts.Add(new AssistAttempt(candidate.Backend, candidate.Model, "ran", "answered"));
                return (reply, candidate, attempts);
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                attempts.Add(new AssistAttempt(candidate.Backend, candidate.Model, "failed", ex.Message));
                if (!allowFallback)
                {
                    break;
                }
            }
        }

        throw Fail(category, attempts);
    }

    public static string FormatBadge(
        string category,
        IReadOnlyList<AssistDraft> runs,
        IReadOnlyList<AssistAttempt> attempts,
        AssistDraft? judge,
        string note)
    {
        var parts = runs.Count == 0
            ? "did not run"
            : string.Join(" + ", runs.Select(r => r.Backend + "/" + r.Model));
        var badge = "Assist · " + Label(category) + " · " + parts;
        if (judge is not null)
        {
            badge += " · judge " + judge.Backend + "/" + judge.Model;
        }

        var misses = attempts.Where(a => a.Status != "ran").ToList();
        if (misses.Count > 0)
        {
            badge += " · fallback (" + string.Join("; ", misses.Select(m => m.Backend + "/" + m.Model + ": " + m.Reason)) + ")";
        }

        if (!string.IsNullOrWhiteSpace(note))
        {
            badge += " · " + note;
        }

        return badge;
    }

    private static string Loud(string category, IReadOnlyList<AssistAttempt> attempts, string? headline = null)
    {
        var lines = new List<string>
        {
            FormatBadge(category, [], attempts, null, ""),
            headline ?? "Assist could not run a " + Label(category) + " model.",
        };
        if (attempts.Count == 0)
        {
            lines.Add("- No models are configured for this category.");
        }
        else
        {
            lines.AddRange(attempts.Select(row => "- " + row.Backend + "/" + row.Model + ": " + row.Status + " — " + row.Reason));
        }

        lines.Add("Nothing else was substituted.");
        return string.Join("\n", lines);
    }

    private static AssistRouteException Fail(string category, IReadOnlyList<AssistAttempt> attempts, string? headline = null)
    {
        var message = Loud(category, attempts, headline);
        var badge = FormatBadge(category, [], attempts, null, "");
        return new AssistRouteException(message, category, badge, attempts);
    }

    private static string Label(string category) =>
        Labels.TryGetValue(category, out var label) ? label : category;
}
