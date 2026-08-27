using Heirloom.Services;
using Xunit;

namespace Heirloom.Tests;

public class TwinRetrieveTests
{
    [Fact]
    public void Old_interview_outranks_recent_speech()
    {
        var rows = new List<VaultRow>();
        for (var i = 10; i <= 100; i++)
        {
            rows.Add(new VaultRow(i, "2026-08-01", "speech", "hello sitting " + i, ""));
        }

        rows.Add(new VaultRow(2, "2020-04-12", "interview", "I grew up on a farm in Vermont.", "childhood"));
        var ranked = TwinRetrieve.Rank(rows, "where did you grow up?", 4);
        Assert.NotEmpty(ranked);
        Assert.Equal("interview", ranked[0].Kind);
        Assert.Contains("Vermont", ranked[0].Text, StringComparison.OrdinalIgnoreCase);
        Assert.Contains("#2", TwinRetrieve.CitationLine(ranked));
    }

    [Fact]
    public void Unfiled_question_is_a_named_miss()
    {
        var rows = new[]
        {
            new VaultRow(8, "2026-01-01", "journal", "Today I made soup and called home.", "day"),
        };
        var ranked = TwinRetrieve.Rank(rows, "what was the name of your first dog?", 4);
        Assert.Empty(ranked);
        Assert.Equal("Nothing matched this question.", TwinRetrieve.CitationLine(ranked));
        Assert.Contains("don't remember", TwinPrompt.MissReply(true), StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public void Facts_require_a_source_capture()
    {
        var rows = new[]
        {
            new VaultRow(4, "2021-01-01", "interview", "I was born in Rutland. That town still feels like home.", "origin"),
            new VaultRow(5, "2026-08-01", "speech", "This sitting should not become a fact.", ""),
        };
        var facts = TwinFacts.Propose(rows);
        Assert.Contains(facts, f => f.SourceId == 4 && f.Fact.Contains("Rutland"));
        Assert.DoesNotContain(facts, f => f.SourceId == 5);
    }

    [Fact]
    public void Embeddings_keep_source_passages()
    {
        var query = TwinEmbed.Vector("where did you grow up in vermont");
        var hit = TwinEmbed.Vector("interview childhood I grew up on a farm in Vermont");
        var miss = TwinEmbed.Vector("speech hello sitting ninety");
        Assert.True(TwinEmbed.Cosine(query, hit) > TwinEmbed.Cosine(query, miss));
    }

    [Fact]
    public void Embed_cannot_promote_an_unmatched_row()
    {
        var rows = new[]
        {
            new VaultRow(1, "2026-08-01", "speech", "hello sitting ninety", ""),
        };
        var boost = new Dictionary<long, double> { [1] = 0.99 };
        var ranked = TwinRetrieve.Rank(rows, "where did you grow up in vermont", 4, boost);
        Assert.Empty(ranked);
    }

    [Fact]
    public void Facts_for_a_question_drop_unrelated_sentences()
    {
        var facts = new[]
        {
            new TwinFact(1, "I grew up on a farm in Vermont.", "interview", 4),
            new TwinFact(2, "I keep a Saturday walk along the river.", "journal", 9),
        };
        var hit = TwinFacts.RelevantTo(facts, "where did you grow up?");
        Assert.Contains(hit, f => f.Id == 1);
        Assert.DoesNotContain(hit, f => f.Id == 2);
    }
}

public class VaultGroundingTests : IDisposable
{
    private readonly string _dir;
    private readonly VaultService _vault;

    public VaultGroundingTests()
    {
        _dir = Path.Combine(Path.GetTempPath(), "heirloom-vault-" + Guid.NewGuid().ToString("n"));
        Directory.CreateDirectory(_dir);
        var store = new SettingsStore
        {
            Current = new AppSettings { LibraryPath = _dir, AppMode = "owner" },
        };
        _vault = new VaultService(store);
        _vault.Open();
    }

    [Fact]
    public void Retrieve_finds_old_interview_not_the_last_eighty_rows()
    {
        var interviewId = _vault.AddCapture("interview", "I grew up on a farm in Vermont.", "childhood");
        for (var i = 0; i < 90; i++)
        {
            _vault.AddCapture("speech", "recent chatter " + i);
        }

        var hits = _vault.Retrieve("where did you grow up?");
        Assert.Contains(hits, h => h.Id == interviewId && h.Text.Contains("Vermont"));
        Assert.Equal("interview", hits[0].Kind);
    }

    [Fact]
    public void Heir_cannot_add_or_index()
    {
        var heirDir = Path.Combine(Path.GetTempPath(), "heirloom-heir-" + Guid.NewGuid().ToString("n"));
        Directory.CreateDirectory(heirDir);
        var heirStore = new SettingsStore
        {
            Current = new AppSettings { LibraryPath = heirDir, AppMode = "heir" },
        };
        using var heirVault = new VaultService(heirStore);
        heirVault.Open();
        Assert.False(heirVault.CanWrite);
        Assert.Equal(0, heirVault.AddCapture("speech", "heir must not file"));
        Assert.Equal(0, heirVault.RebuildFacts());
        Assert.False(heirVault.DeleteFact(1));
    }

    [Fact]
    public void Rebuild_facts_always_point_at_a_capture()
    {
        var id = _vault.AddCapture("journal", "I keep a Saturday walk along the river.", "habit");
        var n = _vault.RebuildFacts();
        Assert.True(n >= 1);
        Assert.All(_vault.ListFacts(), f => Assert.True(f.SourceCaptureId > 0));
        Assert.Contains(_vault.ListFacts(), f => f.SourceCaptureId == id);
    }

    [Fact]
    public void Retrieve_does_not_fall_back_to_recent_chatter()
    {
        for (var i = 0; i < 20; i++)
        {
            _vault.AddCapture("speech", "recent chatter " + i);
        }

        Assert.Empty(_vault.Retrieve("where did you grow up in vermont"));
    }

    [Fact]
    public void Export_includes_sourced_facts()
    {
        var id = _vault.AddCapture("interview", "I grew up on a farm in Vermont.", "childhood");
        _vault.RebuildFacts();
        var path = _vault.ExportArchive();
        var json = File.ReadAllText(path);
        Assert.Contains("facts", json, StringComparison.Ordinal);
        Assert.Contains("Vermont", json, StringComparison.Ordinal);
        Assert.Contains(id.ToString(), json);
    }

    public void Dispose()
    {
        _vault.Dispose();
        try
        {
            Directory.Delete(_dir, recursive: true);
        }
        catch
        {
            // temp leftovers are not a product failure
        }
    }
}
