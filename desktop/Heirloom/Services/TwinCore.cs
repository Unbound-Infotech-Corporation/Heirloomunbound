using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace Heirloom.Services;

public sealed record VaultRow(long Id, string Created, string Kind, string Text, string Tag);

public sealed record TwinPassage(long Id, string Kind, string Tag, string Created, string Text, double Score);

public sealed record TwinCoreBlock(string Stance, string Portrait, string Values, string Fence);

public sealed record TwinFact(long Id, string Fact, string Kind, long SourceCaptureId);

public sealed class TwinPack
{
    public TwinCoreBlock Core { get; init; } = new("", "", "", "");
    public IReadOnlyList<TwinPassage> Passages { get; init; } = [];
    public string CitationLine { get; init; } = "";
    public bool Grounded { get; init; } = true;
    public string Audience { get; init; } = "owner";
    public IReadOnlyList<TwinFact> Facts { get; init; } = [];

    public bool HasPassages => Passages.Count > 0;

    public object ToWire() => new
    {
        core = new
        {
            stance = Core.Stance,
            portrait = Core.Portrait,
            values = Core.Values,
            fence = Core.Fence,
        },
        passages = Passages.Select(p => new
        {
            id = p.Id.ToString(),
            kind = p.Kind,
            tag = p.Tag,
            created = p.Created,
            text = p.Text,
            score = p.Score,
        }),
        facts = Facts.Where(f => f.SourceCaptureId > 0).Select(f => new
        {
            id = f.Id.ToString(),
            fact = f.Fact,
            kind = f.Kind,
            source_capture_id = f.SourceCaptureId.ToString(),
        }),
        citation_line = CitationLine,
        grounded = Grounded,
        audience = Audience,
    };
}

public static class TwinTokens
{
    public static readonly HashSet<string> Stop = new(StringComparer.OrdinalIgnoreCase)
    {
        "the", "a", "an", "of", "in", "on", "to", "for", "was", "is", "are",
        "what", "where", "when", "who", "why", "how", "my", "me", "i", "did",
        "do", "does", "that", "this", "at", "with", "and", "you", "your",
        "they", "them", "their", "about", "from", "have", "had", "been",
    };

    public static string[] Split(string query)
    {
        var raw = (query ?? "")
            .ToLowerInvariant()
            .Split([' ', '\t', '\n', '\r', ',', '.', '?', '!', ';', ':', '"', '\'', '(', ')', '/', '\\', '-'], StringSplitOptions.RemoveEmptyEntries)
            .Where(t => t.Length > 2 && !Stop.Contains(t))
            .Select(Stem)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .Take(12)
            .ToArray();
        return Expand(raw);
    }

    public static string Stem(string token) => token switch
    {
        "grew" or "growing" => "grow",
        "lived" or "living" => "live",
        "children" or "childhood" or "kids" => "child",
        "worked" or "working" or "career" => "work",
        "remembered" or "remembering" => "remember",
        _ => token,
    };

    public static string[] Expand(string[] tokens)
    {
        var set = new HashSet<string>(tokens, StringComparer.OrdinalIgnoreCase);
        foreach (var token in tokens)
        {
            switch (token)
            {
                case "grow":
                    set.Add("grew");
                    set.Add("growing");
                    break;
                case "live":
                    set.Add("lived");
                    set.Add("living");
                    break;
                case "child":
                    set.Add("children");
                    set.Add("childhood");
                    set.Add("kids");
                    break;
                case "work":
                    set.Add("job");
                    set.Add("career");
                    break;
            }
        }

        return [.. set.Take(16)];
    }

    public static string FtsQuery(string query)
    {
        var tokens = Split(query);
        if (tokens.Length == 0)
        {
            return "";
        }

        return string.Join(" OR ", tokens.Select(t => "\"" + t.Replace("\"", "") + "\""));
    }
}

public static class TwinRetrieve
{
    public static double KindWeight(string kind) => kind switch
    {
        "interview" => 1.35,
        "journal" => 1.25,
        "memoir" => 1.3,
        "photo_story" => 1.15,
        "import" => 1.05,
        "note" => 1.0,
        "speech" => 0.55,
        _ => 1.0,
    };

    public static double TokenScore(string hay, IReadOnlyList<string> tokens)
    {
        if (tokens.Count == 0 || string.IsNullOrEmpty(hay))
        {
            return 0;
        }

        var lower = hay.ToLowerInvariant();
        double score = 0;
        foreach (var token in tokens)
        {
            var idx = 0;
            var n = 0;
            while ((idx = lower.IndexOf(token, idx, StringComparison.Ordinal)) >= 0)
            {
                n++;
                idx += token.Length;
            }

            if (n > 0)
            {
                score += 2 + n;
            }
        }

        return score;
    }

    public static IReadOnlyList<TwinPassage> Rank(
        IEnumerable<VaultRow> rows,
        string query,
        int limit = 8,
        IReadOnlyDictionary<long, double>? embedBoost = null)
    {
        var tokens = TwinTokens.Split(query);
        var ranked = rows
            .Select(row =>
            {
                var hay = row.Kind + " " + row.Tag + " " + row.Text;
                var lexical = TokenScore(hay, tokens) * KindWeight(row.Kind);
                var embed = 0d;
                if (lexical > 0 && embedBoost is not null && embedBoost.TryGetValue(row.Id, out var e))
                {
                    embed = e * 8;
                }

                var score = lexical + embed;
                if (tokens.Length == 0)
                {
                    score = KindWeight(row.Kind);
                }

                return new TwinPassage(row.Id, row.Kind, row.Tag, row.Created, Trim(row.Text, 900), score);
            })
            .Where(p => tokens.Length == 0 ? p.Score > 0 : p.Score >= 2.5)
            .OrderByDescending(p => p.Score)
            .ThenByDescending(p => p.Id)
            .Take(Math.Clamp(limit, 1, 12))
            .ToList();

        if (ranked.Count == 0 && tokens.Length > 0)
        {
            return [];
        }

        return ranked;
    }

    public static string CitationLine(IReadOnlyList<TwinPassage> passages) =>
        passages.Count == 0
            ? "Nothing matched this question."
            : string.Join(" · ", passages.Take(4).Select(p =>
                p.Kind + "#" + p.Id + (string.IsNullOrWhiteSpace(p.Tag) ? "" : "/" + p.Tag)));

    public static string MemoriesBlob(IReadOnlyList<TwinPassage> passages)
    {
        if (passages.Count == 0)
        {
            return "";
        }

        var builder = new StringBuilder();
        foreach (var p in passages)
        {
            builder.Append('[').Append(p.Kind.ToUpperInvariant());
            if (!string.IsNullOrWhiteSpace(p.Tag))
            {
                builder.Append('/').Append(p.Tag);
            }

            builder.Append(" #").Append(p.Id).Append("]\n").Append(p.Text.Trim()).Append("\n\n");
        }

        return builder.ToString().Trim();
    }

    private static string Trim(string text, int max) =>
        string.IsNullOrEmpty(text) ? "" : text.Length <= max ? text : text[..max] + "…";
}

public static class TwinPrompt
{
    public static string StanceLine(string persona) => persona switch
    {
        "formal" => "Speak as a composed, precise representative. Short sentences. No slang.",
        "full" => "Speak as the whole person: warmth, humor, and the hard years, if those memories exist.",
        _ => "Speak as family would remember them: warm, plain, and close.",
    };

    public static TwinCoreBlock CoreFrom(string persona, string portrait, string values, string fence = "") =>
        new(StanceLine(persona), Cap(portrait, 2000), Cap(values, 2000), fence);

    public static string System(TwinPack pack, string name)
    {
        var who = string.IsNullOrWhiteSpace(name) ? "this person" : name;
        var heir = string.Equals(pack.Audience, "heir", StringComparison.OrdinalIgnoreCase);
        var grounded = pack.Grounded || heir;
        var builder = new StringBuilder();
        builder.Append("You are the digital twin of ").Append(who)
            .Append(" — a faithful continuation of a filed life, not a chatbot. Speak in first person as them. Never say you are an AI.");
        if (heir)
        {
            builder.Append(" You are speaking with an heir. You cannot file, invent, or take actions.");
        }

        builder.Append('\n');
        if (grounded)
        {
            builder.Append("Answer ONLY from CORE and numbered PASSAGES that actually answer this turn. Ignore leftover facts and passages about a different topic. If the answer is not there, say you don't remember that yet. Never invent biography, dates, names, or advice they did not file. A fluent sentence is not a filing.\n");
        }
        else
        {
            builder.Append("Prefer CORE and PASSAGES. Do not invent facts about their life. If nothing matches, say so.\n");
        }

        builder.Append("PERSONA REGISTER:\n").Append(pack.Core.Stance).Append('\n');
        if (!string.IsNullOrWhiteSpace(pack.Core.Portrait))
        {
            builder.Append("HOW THEY WERE:\n").Append(pack.Core.Portrait).Append('\n');
        }

        if (!string.IsNullOrWhiteSpace(pack.Core.Values))
        {
            builder.Append("WHAT THEY REFUSED TO PRETEND:\n").Append(pack.Core.Values).Append('\n');
        }

        if (!string.IsNullOrWhiteSpace(pack.Core.Fence))
        {
            builder.Append("SAFE-TOPIC FENCE:\n").Append(pack.Core.Fence).Append('\n');
        }

        var sourced = pack.Facts.Where(f => f.SourceCaptureId > 0).Take(40).ToList();
        if (sourced.Count > 0)
        {
            builder.Append("STABLE FACTS (each points at a capture; do not treat unsourced claims as filed):\n");
            foreach (var fact in sourced)
            {
                builder.Append("- ").Append(fact.Fact).Append(" [#").Append(fact.SourceCaptureId).Append("]\n");
            }
        }

        var blob = TwinRetrieve.MemoriesBlob(pack.Passages);
        builder.Append("=== PASSAGES ===\n");
        builder.Append(string.IsNullOrWhiteSpace(blob)
            ? "(nothing retrieved for this turn — say you don't remember if asked for a fact)\n"
            : blob);
        return builder.ToString();
    }

    public static string MissReply(bool grounded) =>
        grounded
            ? "I don't remember that yet. Nothing filed matches this, and I will not invent it."
            : "Nothing filed matches this. I will not treat a guess as a memory.";

    private static string Cap(string text, int max)
    {
        var t = (text ?? "").Trim();
        return t.Length <= max ? t : t[..max];
    }
}

public static class TwinFacts
{
    private static readonly HashSet<string> Durable = new(StringComparer.OrdinalIgnoreCase)
    {
        "interview", "journal", "memoir", "photo_story", "import", "note",
    };

    public static IReadOnlyList<(string Fact, string Kind, long SourceId)> Propose(IEnumerable<VaultRow> rows)
    {
        var facts = new List<(string, string, long)>();
        foreach (var row in rows)
        {
            if (!Durable.Contains(row.Kind))
            {
                continue;
            }

            var sentence = FirstSentence(row.Text);
            if (sentence.Length < 12)
            {
                continue;
            }

            facts.Add((sentence, row.Kind, row.Id));
            if (facts.Count >= 80)
            {
                break;
            }
        }

        return facts;
    }

    public static IReadOnlyList<TwinFact> RelevantTo(IEnumerable<TwinFact> facts, string query, int limit = 20)
    {
        var sourced = facts.Where(f => f.SourceCaptureId > 0).ToList();
        var tokens = TwinTokens.Split(query);
        if (tokens.Length == 0)
        {
            return sourced.Take(limit).ToList();
        }

        return sourced
            .Select(f => (Fact: f, Score: TwinRetrieve.TokenScore(f.Fact + " " + f.Kind, tokens)))
            .Where(x => x.Score >= 2)
            .OrderByDescending(x => x.Score)
            .Take(limit)
            .Select(x => x.Fact)
            .ToList();
    }

    public static string FirstSentence(string text)
    {
        var t = (text ?? "").Replace('\r', ' ').Replace('\n', ' ').Trim();
        if (t.Length == 0)
        {
            return "";
        }

        var cut = t.IndexOfAny(['.', '!', '?']);
        var sentence = cut is >= 12 and < 220 ? t[..(cut + 1)].Trim() : t;
        return sentence.Length <= 220 ? sentence : sentence[..220].TrimEnd() + "…";
    }
}

public static class TwinEmbed
{
    public const string Model = "tf-token-v1";

    public static Dictionary<string, float> Vector(string text)
    {
        var counts = new Dictionary<string, float>(StringComparer.OrdinalIgnoreCase);
        foreach (var token in TwinTokens.Split(text))
        {
            counts[token] = counts.GetValueOrDefault(token) + 1f;
        }

        var norm = MathF.Sqrt(counts.Values.Sum(v => v * v));
        if (norm <= 0)
        {
            return counts;
        }

        foreach (var key in counts.Keys.ToList())
        {
            counts[key] /= norm;
        }

        return counts;
    }

    public static double Cosine(IReadOnlyDictionary<string, float> a, IReadOnlyDictionary<string, float> b)
    {
        if (a.Count == 0 || b.Count == 0)
        {
            return 0;
        }

        var small = a.Count < b.Count ? a : b;
        var large = ReferenceEquals(small, a) ? b : a;
        double dot = 0;
        foreach (var kv in small)
        {
            if (large.TryGetValue(kv.Key, out var other))
            {
                dot += kv.Value * other;
            }
        }

        return dot;
    }

    public static string Serialize(IReadOnlyDictionary<string, float> vector) =>
        JsonSerializer.Serialize(vector);

    public static Dictionary<string, float> Deserialize(string json)
    {
        try
        {
            return JsonSerializer.Deserialize<Dictionary<string, float>>(json)
                   ?? new Dictionary<string, float>(StringComparer.OrdinalIgnoreCase);
        }
        catch
        {
            return new Dictionary<string, float>(StringComparer.OrdinalIgnoreCase);
        }
    }
}

public static class TwinPackJson
{
    private static readonly JsonSerializerOptions Options = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
    };

    public static string Serialize(TwinPack pack) => JsonSerializer.Serialize(pack.ToWire(), Options);
}
