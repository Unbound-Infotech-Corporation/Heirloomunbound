using Microsoft.Data.Sqlite;

namespace Heirloom.Services;

public sealed record LetterRow(long Id, string Title, string Body, string ForPerson, string Trigger, bool Sealed, string Created);
public sealed record HeirRow(long Id, string Name, string Relation, bool Consent, string Created);
public sealed record VaultStats(int Captures, int Letters, int Heirs, IReadOnlyDictionary<string, int> ByKind, int Completeness);

public sealed class VaultService : IDisposable
{
    private readonly SettingsStore _settings;
    private SqliteConnection? _connection;

    public string Status { get; private set; } = "Vault closed";
    public string RootPath { get; private set; } = "";
    public string DbPath => Path.Combine(RootPath, "vault.db");

    public bool CanWrite =>
        !string.Equals(_settings.Current.AppMode, "heir", StringComparison.OrdinalIgnoreCase);

    public VaultService(SettingsStore settings)
    {
        _settings = settings;
    }

    public void Open()
    {
        _connection?.Dispose();
        _connection = null;
        var root = string.IsNullOrWhiteSpace(_settings.Current.LibraryPath)
            ? AppPaths.DefaultVaultPath
            : _settings.Current.LibraryPath;
        Directory.CreateDirectory(root);
        RootPath = root;
        _connection = new SqliteConnection("Data Source=" + Path.Combine(root, "vault.db"));
        _connection.Open();
        using var cmd = _connection.CreateCommand();
        cmd.CommandText =
            """
            CREATE TABLE IF NOT EXISTS captures (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              created_utc TEXT NOT NULL,
              kind TEXT NOT NULL,
              text TEXT NOT NULL,
              tag TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS letters (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              title TEXT NOT NULL,
              body TEXT NOT NULL,
              sealed INTEGER NOT NULL DEFAULT 0,
              created_utc TEXT NOT NULL,
              for_person TEXT NOT NULL DEFAULT '',
              trigger_when TEXT NOT NULL DEFAULT 'after_release'
            );
            CREATE TABLE IF NOT EXISTS heirs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT NOT NULL,
              relation TEXT NOT NULL DEFAULT '',
              consent INTEGER NOT NULL DEFAULT 0,
              created_utc TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS skills (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT NOT NULL,
              webhook_url TEXT NOT NULL,
              triggers TEXT NOT NULL DEFAULT '',
              enabled INTEGER NOT NULL DEFAULT 1,
              created_utc TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS vault_facts (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              fact TEXT NOT NULL,
              kind TEXT NOT NULL,
              source_capture_id INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS capture_vectors (
              capture_id INTEGER PRIMARY KEY,
              model TEXT NOT NULL,
              vector_json TEXT NOT NULL
            );
            """;
        cmd.ExecuteNonQuery();
        EnsureColumn("captures", "tag", "ALTER TABLE captures ADD COLUMN tag TEXT NOT NULL DEFAULT ''");
        EnsureColumn("letters", "for_person", "ALTER TABLE letters ADD COLUMN for_person TEXT NOT NULL DEFAULT ''");
        EnsureColumn("letters", "trigger_when", "ALTER TABLE letters ADD COLUMN trigger_when TEXT NOT NULL DEFAULT 'after_release'");
        EnsureFts();
        ReindexMissingVectors();
        Status = "Vault · " + root;
    }

    public long AddCapture(string kind, string text, string tag = "")
    {
        if (!CanWrite || string.IsNullOrWhiteSpace(text))
        {
            return 0;
        }

        Ensure();
        using var cmd = _connection!.CreateCommand();
        cmd.CommandText = "INSERT INTO captures (created_utc, kind, text, tag) VALUES ($c, $k, $t, $g)";
        cmd.Parameters.AddWithValue("$c", DateTime.UtcNow.ToString("o"));
        cmd.Parameters.AddWithValue("$k", kind);
        cmd.Parameters.AddWithValue("$t", text.Trim());
        cmd.Parameters.AddWithValue("$g", tag);
        cmd.ExecuteNonQuery();
        using var idCmd = _connection.CreateCommand();
        idCmd.CommandText = "SELECT last_insert_rowid()";
        var id = (long)idCmd.ExecuteScalar()!;
        IndexCapture(id, kind, text.Trim(), tag);
        return id;
    }

    public bool DeleteCapture(long id)
    {
        if (id <= 0 || !CanWrite)
        {
            return false;
        }

        Ensure();
        using (var facts = _connection!.CreateCommand())
        {
            facts.CommandText = "DELETE FROM vault_facts WHERE source_capture_id = $id";
            facts.Parameters.AddWithValue("$id", id);
            facts.ExecuteNonQuery();
        }

        using (var vec = _connection.CreateCommand())
        {
            vec.CommandText = "DELETE FROM capture_vectors WHERE capture_id = $id";
            vec.Parameters.AddWithValue("$id", id);
            vec.ExecuteNonQuery();
        }

        try
        {
            using var fts = _connection.CreateCommand();
            fts.CommandText = "DELETE FROM captures_fts WHERE rowid = $id";
            fts.Parameters.AddWithValue("$id", id);
            fts.ExecuteNonQuery();
        }
        catch (SqliteException)
        {
        }

        using var cmd = _connection.CreateCommand();
        cmd.CommandText = "DELETE FROM captures WHERE id = $id";
        cmd.Parameters.AddWithValue("$id", id);
        return cmd.ExecuteNonQuery() > 0;
    }

    public IReadOnlyList<VaultRow> Recent(int limit = 40, string? kind = null)
    {
        Ensure();
        using var cmd = _connection!.CreateCommand();
        if (string.IsNullOrWhiteSpace(kind) || kind == "all")
        {
            cmd.CommandText = "SELECT id, created_utc, kind, text, IFNULL(tag,'') FROM captures ORDER BY id DESC LIMIT $n";
        }
        else
        {
            cmd.CommandText = "SELECT id, created_utc, kind, text, IFNULL(tag,'') FROM captures WHERE kind = $k ORDER BY id DESC LIMIT $n";
            cmd.Parameters.AddWithValue("$k", kind);
        }

        cmd.Parameters.AddWithValue("$n", limit);
        return ReadCaptures(cmd);
    }

    public VaultRow? GetCapture(long id)
    {
        Ensure();
        using var cmd = _connection!.CreateCommand();
        cmd.CommandText = "SELECT id, created_utc, kind, text, IFNULL(tag,'') FROM captures WHERE id = $id LIMIT 1";
        cmd.Parameters.AddWithValue("$id", id);
        return ReadCaptures(cmd).FirstOrDefault();
    }

    public IReadOnlyList<TwinPassage> Retrieve(string query, int limit = 8)
    {
        Ensure();
        var pool = FtsPool(query, 80);
        if (pool.Count == 0)
        {
            return [];
        }

        var queryVec = TwinEmbed.Vector(query);
        var boost = new Dictionary<long, double>();
        foreach (var row in pool)
        {
            var stored = GetVector(row.Id);
            if (stored.Count == 0)
            {
                stored = TwinEmbed.Vector(row.Kind + " " + row.Tag + " " + row.Text);
            }

            var cos = TwinEmbed.Cosine(queryVec, stored);
            if (cos >= 0.28)
            {
                boost[row.Id] = cos;
            }
        }

        return TwinRetrieve.Rank(pool, query, limit, boost);
    }

    public IReadOnlyList<VaultRow> Search(string query, string? kind = null, int limit = 80)
    {
        if (string.IsNullOrWhiteSpace(query))
        {
            return Recent(limit, kind);
        }

        var hits = Retrieve(query, Math.Clamp(limit, 8, 40));
        IEnumerable<TwinPassage> filtered = hits;
        if (!string.IsNullOrWhiteSpace(kind) && kind != "all")
        {
            filtered = hits.Where(h => string.Equals(h.Kind, kind, StringComparison.OrdinalIgnoreCase));
        }

        return filtered
            .Select(h => new VaultRow(h.Id, h.Created, h.Kind, h.Text, h.Tag))
            .ToList();
    }

    public TwinPack BuildPack(string query, TwinCoreBlock core, bool grounded, string audience, int limit = 8)
    {
        var passages = Retrieve(query, limit);
        var facts = TwinFacts.RelevantTo(ListFacts(), query);
        return new TwinPack
        {
            Core = core,
            Passages = passages,
            Facts = facts,
            CitationLine = TwinRetrieve.CitationLine(passages),
            Grounded = grounded,
            Audience = audience,
        };
    }

    public string GroundedContext(int maxChars = 3500)
    {
        var rows = Recent(80);
        var builder = new System.Text.StringBuilder();
        foreach (var row in rows)
        {
            if (!Allows(row))
            {
                continue;
            }

            var line = $"[{row.Kind}{(string.IsNullOrWhiteSpace(row.Tag) ? "" : "/" + row.Tag)}] {row.Text.Trim()}";
            if (builder.Length + line.Length > maxChars)
            {
                break;
            }

            builder.AppendLine(line);
        }

        return builder.ToString();
    }

    public IReadOnlyList<VaultRow> CitationsFor(string query, int limit = 6)
    {
        if (string.IsNullOrWhiteSpace(query))
        {
            return [];
        }

        return Retrieve(query, limit)
            .Select(h => new VaultRow(h.Id, h.Created, h.Kind, h.Text, h.Tag))
            .ToList();
    }

    public VaultStats Stats()
    {
        Ensure();
        var byKind = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
        using (var cmd = _connection!.CreateCommand())
        {
            cmd.CommandText = "SELECT kind, COUNT(*) FROM captures GROUP BY kind";
            using var reader = cmd.ExecuteReader();
            while (reader.Read())
            {
                byKind[reader.GetString(0)] = reader.GetInt32(1);
            }
        }

        var captures = byKind.Values.Sum();
        var letters = Count("letters");
        var heirs = Count("heirs");
        var completeness = Math.Clamp(
            (captures >= 1 ? 12 : 0)
            + (captures >= 8 ? 18 : captures * 2)
            + (byKind.ContainsKey("speech") ? 10 : 0)
            + (byKind.ContainsKey("journal") ? 10 : 0)
            + (byKind.ContainsKey("interview") ? 12 : 0)
            + (byKind.ContainsKey("photo_story") ? 10 : 0)
            + (letters > 0 ? 10 : 0)
            + (heirs > 0 ? 10 : 0)
            + (byKind.ContainsKey("memoir") ? 8 : 0),
            0,
            100);
        return new VaultStats(captures, letters, heirs, byKind, completeness);
    }

    public string LookBack()
    {
        var last = Recent(1).FirstOrDefault();
        if (last is null)
        {
            return "Nothing filed yet. That is the vault, not a failing.";
        }

        var kind = last.Kind switch
        {
            "speech" => "spoken",
            "interview" => "chapter",
            "journal" => "journal",
            "photo_story" => "photo",
            "import" => "import",
            _ => last.Kind,
        };
        var text = last.Text.Replace('\r', ' ').Replace('\n', ' ').Trim();
        if (text.Length > 88)
        {
            text = text[..88].TrimEnd() + "…";
        }

        return "Last filed · " + kind + ": " + text;
    }

    public static string GapLine(VaultStats stats)
    {
        var missing = new List<string>();
        if (!stats.ByKind.ContainsKey("interview"))
        {
            missing.Add("a chapter");
        }

        if (!stats.ByKind.ContainsKey("journal"))
        {
            missing.Add("a journal day");
        }

        if (!stats.ByKind.ContainsKey("photo_story"))
        {
            missing.Add("a photo story");
        }

        if (stats.Heirs == 0)
        {
            missing.Add("an heir");
        }

        if (stats.Letters == 0)
        {
            missing.Add("a letter");
        }

        if (stats.Captures == 0)
        {
            return "The vault is empty. File one true sentence — then Ask can retrieve it.";
        }

        if (missing.Count == 0)
        {
            return "Speech, chapters, and a gift path are on this PC. Retrieval, not invention.";
        }

        return "Still open: " + string.Join(", ", missing) + ".";
    }

    public void AddLetter(string title, string body, bool sealedLetter, string forPerson = "", string trigger = "after_release")
    {
        if (!CanWrite)
        {
            return;
        }

        Ensure();
        using var cmd = _connection!.CreateCommand();
        cmd.CommandText = "INSERT INTO letters (title, body, sealed, created_utc, for_person, trigger_when) VALUES ($t, $b, $s, $c, $p, $w)";
        cmd.Parameters.AddWithValue("$t", title);
        cmd.Parameters.AddWithValue("$b", body);
        cmd.Parameters.AddWithValue("$s", sealedLetter ? 1 : 0);
        cmd.Parameters.AddWithValue("$c", DateTime.UtcNow.ToString("o"));
        cmd.Parameters.AddWithValue("$p", forPerson);
        cmd.Parameters.AddWithValue("$w", trigger);
        cmd.ExecuteNonQuery();
    }

    public IReadOnlyList<LetterRow> Letters()
    {
        Ensure();
        using var cmd = _connection!.CreateCommand();
        cmd.CommandText = "SELECT id, title, body, IFNULL(for_person,''), IFNULL(trigger_when,'after_release'), sealed, created_utc FROM letters ORDER BY id DESC";
        var rows = new List<LetterRow>();
        using var reader = cmd.ExecuteReader();
        while (reader.Read())
        {
            rows.Add(new LetterRow(
                reader.GetInt64(0),
                reader.GetString(1),
                reader.GetString(2),
                reader.GetString(3),
                reader.GetString(4),
                reader.GetInt32(5) == 1,
                reader.GetString(6)));
        }

        return rows;
    }

    public void AddHeir(string name, string relation, bool consent)
    {
        if (!CanWrite)
        {
            return;
        }

        Ensure();
        using var cmd = _connection!.CreateCommand();
        cmd.CommandText = "INSERT INTO heirs (name, relation, consent, created_utc) VALUES ($n, $r, $c, $t)";
        cmd.Parameters.AddWithValue("$n", name);
        cmd.Parameters.AddWithValue("$r", relation);
        cmd.Parameters.AddWithValue("$c", consent ? 1 : 0);
        cmd.Parameters.AddWithValue("$t", DateTime.UtcNow.ToString("o"));
        cmd.ExecuteNonQuery();
    }

    public void AddSkill(string name, string url, string triggers)
    {
        if (!CanWrite)
        {
            return;
        }

        Ensure();
        using var cmd = _connection!.CreateCommand();
        cmd.CommandText = "INSERT INTO skills (name, webhook_url, triggers, enabled, created_utc) VALUES ($n, $u, $t, 1, $c)";
        cmd.Parameters.AddWithValue("$n", name);
        cmd.Parameters.AddWithValue("$u", url);
        cmd.Parameters.AddWithValue("$t", triggers);
        cmd.Parameters.AddWithValue("$c", DateTime.UtcNow.ToString("o"));
        cmd.ExecuteNonQuery();
    }

    public IReadOnlyList<(long Id, string Name, string Url, string Triggers, bool Enabled)> Skills()
    {
        Ensure();
        using var cmd = _connection!.CreateCommand();
        cmd.CommandText = "SELECT id, name, webhook_url, triggers, enabled FROM skills ORDER BY id DESC";
        var rows = new List<(long, string, string, string, bool)>();
        using var reader = cmd.ExecuteReader();
        while (reader.Read())
        {
            rows.Add((reader.GetInt64(0), reader.GetString(1), reader.GetString(2), reader.GetString(3), reader.GetInt32(4) == 1));
        }

        return rows;
    }

    public void DeleteSkill(long id)
    {
        if (!CanWrite)
        {
            return;
        }

        Ensure();
        using var cmd = _connection!.CreateCommand();
        cmd.CommandText = "DELETE FROM skills WHERE id = $i";
        cmd.Parameters.AddWithValue("$i", id);
        cmd.ExecuteNonQuery();
    }

    public IReadOnlyList<HeirRow> Heirs()
    {
        Ensure();
        using var cmd = _connection!.CreateCommand();
        cmd.CommandText = "SELECT id, name, relation, consent, created_utc FROM heirs ORDER BY id DESC";
        var rows = new List<HeirRow>();
        using var reader = cmd.ExecuteReader();
        while (reader.Read())
        {
            rows.Add(new HeirRow(
                reader.GetInt64(0),
                reader.GetString(1),
                reader.GetString(2),
                reader.GetInt32(3) == 1,
                reader.GetString(4)));
        }

        return rows;
    }

    public IReadOnlyList<TwinFact> ListFacts()
    {
        Ensure();
        using var cmd = _connection!.CreateCommand();
        cmd.CommandText = """
            SELECT f.id, f.fact, f.kind, f.source_capture_id
            FROM vault_facts f
            INNER JOIN captures c ON c.id = f.source_capture_id
            ORDER BY f.id DESC
            """;
        using var reader = cmd.ExecuteReader();
        var facts = new List<TwinFact>();
        while (reader.Read())
        {
            facts.Add(new TwinFact(reader.GetInt64(0), reader.GetString(1), reader.GetString(2), reader.GetInt64(3)));
        }

        return facts;
    }

    public int RebuildFacts()
    {
        if (!CanWrite)
        {
            return 0;
        }

        Ensure();
        using (var wipe = _connection!.CreateCommand())
        {
            wipe.CommandText = "DELETE FROM vault_facts";
            wipe.ExecuteNonQuery();
        }

        var proposed = TwinFacts.Propose(Recent(10_000));
        var n = 0;
        foreach (var (fact, kind, sourceId) in proposed)
        {
            using var cmd = _connection.CreateCommand();
            cmd.CommandText = "INSERT INTO vault_facts (fact, kind, source_capture_id) VALUES ($f, $k, $s)";
            cmd.Parameters.AddWithValue("$f", fact);
            cmd.Parameters.AddWithValue("$k", kind);
            cmd.Parameters.AddWithValue("$s", sourceId);
            cmd.ExecuteNonQuery();
            n++;
        }

        return n;
    }

    public bool DeleteFact(long id)
    {
        if (id <= 0 || !CanWrite)
        {
            return false;
        }

        Ensure();
        using var cmd = _connection!.CreateCommand();
        cmd.CommandText = "DELETE FROM vault_facts WHERE id = $id";
        cmd.Parameters.AddWithValue("$id", id);
        return cmd.ExecuteNonQuery() > 0;
    }

    public string ExportArchive()
    {
        Ensure();
        var dest = Path.Combine(
            _settings.Current.LibraryPath,
            $"heirloom-export-{DateTime.UtcNow:yyyyMMdd}.json");
        var captures = Recent(10_000);
        var letters = Letters();
        var heirs = Heirs();
        var facts = ListFacts().Where(f => f.SourceCaptureId > 0).ToList();
        var json =
            $$"""
            {"exported_utc":"{{DateTime.UtcNow:o}}","captures":[{{string.Join(",", captures.Select(c => $"{{\"id\":{c.Id},\"kind\":{System.Text.Json.JsonSerializer.Serialize(c.Kind)},\"tag\":{System.Text.Json.JsonSerializer.Serialize(c.Tag)},\"text\":{System.Text.Json.JsonSerializer.Serialize(c.Text)}}}"))}}],"facts":[{{string.Join(",", facts.Select(f => $"{{\"id\":{f.Id},\"kind\":{System.Text.Json.JsonSerializer.Serialize(f.Kind)},\"source_capture_id\":{f.SourceCaptureId},\"fact\":{System.Text.Json.JsonSerializer.Serialize(f.Fact)}}}"))}}],"letters":[{{string.Join(",", letters.Select(l => $"{{\"id\":{l.Id},\"title\":{System.Text.Json.JsonSerializer.Serialize(l.Title)},\"for\":{System.Text.Json.JsonSerializer.Serialize(l.ForPerson)},\"trigger\":{System.Text.Json.JsonSerializer.Serialize(l.Trigger)},\"sealed\":{l.Sealed.ToString().ToLowerInvariant()},\"body\":{System.Text.Json.JsonSerializer.Serialize(l.Body)}}}"))}}],"heirs":[{{string.Join(",", heirs.Select(h => $"{{\"id\":{h.Id},\"name\":{System.Text.Json.JsonSerializer.Serialize(h.Name)},\"relation\":{System.Text.Json.JsonSerializer.Serialize(h.Relation)},\"consent\":{h.Consent.ToString().ToLowerInvariant()}}}"))}}]}
            """;
        File.WriteAllText(dest, json);
        return dest;
    }

    private void EnsureFts()
    {
        if (_connection is null)
        {
            return;
        }

        try
        {
            using var cmd = _connection.CreateCommand();
            cmd.CommandText = """
                CREATE VIRTUAL TABLE IF NOT EXISTS captures_fts USING fts5(
                  text, tag, kind, content='captures', content_rowid='id'
                );
                """;
            cmd.ExecuteNonQuery();
        }
        catch (SqliteException)
        {
            return;
        }

        using var count = _connection.CreateCommand();
        count.CommandText = "SELECT COUNT(*) FROM captures_fts";
        long ftsCount;
        try
        {
            ftsCount = Convert.ToInt64(count.ExecuteScalar() ?? 0L);
        }
        catch (SqliteException)
        {
            return;
        }

        using var cap = _connection.CreateCommand();
        cap.CommandText = "SELECT COUNT(*) FROM captures";
        var capCount = Convert.ToInt64(cap.ExecuteScalar() ?? 0L);
        if (ftsCount == capCount)
        {
            return;
        }

        try
        {
            using var rebuild = _connection.CreateCommand();
            rebuild.CommandText = "INSERT INTO captures_fts(captures_fts) VALUES('rebuild')";
            rebuild.ExecuteNonQuery();
        }
        catch (SqliteException)
        {
        }
    }

    private List<VaultRow> FtsPool(string query, int limit)
    {
        var fts = TwinTokens.FtsQuery(query);
        if (string.IsNullOrWhiteSpace(fts))
        {
            return Recent(limit).Where(Allows).ToList();
        }

        try
        {
            using var cmd = _connection!.CreateCommand();
            cmd.CommandText = """
                SELECT c.id, c.created_utc, c.kind, c.text, IFNULL(c.tag,'')
                FROM captures_fts
                JOIN captures c ON c.id = captures_fts.rowid
                WHERE captures_fts MATCH $q
                LIMIT $n
                """;
            cmd.Parameters.AddWithValue("$q", fts);
            cmd.Parameters.AddWithValue("$n", limit);
            return ReadCaptures(cmd).Where(Allows).ToList();
        }
        catch (SqliteException)
        {
            return Recent(Math.Min(400, limit * 5)).Where(Allows).ToList();
        }
    }

    private void IndexCapture(long id, string kind, string text, string tag)
    {
        try
        {
            using var fts = _connection!.CreateCommand();
            fts.CommandText = "INSERT INTO captures_fts(rowid, text, tag, kind) VALUES ($id, $text, $tag, $kind)";
            fts.Parameters.AddWithValue("$id", id);
            fts.Parameters.AddWithValue("$text", text);
            fts.Parameters.AddWithValue("$tag", tag);
            fts.Parameters.AddWithValue("$kind", kind);
            fts.ExecuteNonQuery();
        }
        catch (SqliteException)
        {
        }

        UpsertVector(id, kind + " " + tag + " " + text);
    }

    private void ReindexMissingVectors()
    {
        if (_connection is null)
        {
            return;
        }

        using var cmd = _connection.CreateCommand();
        cmd.CommandText = """
            SELECT c.id, c.kind, c.text, IFNULL(c.tag,'')
            FROM captures c
            LEFT JOIN capture_vectors v ON v.capture_id = c.id AND v.model = $m
            WHERE v.capture_id IS NULL
            LIMIT 400
            """;
        cmd.Parameters.AddWithValue("$m", TwinEmbed.Model);
        using var reader = cmd.ExecuteReader();
        var pending = new List<(long Id, string Kind, string Text, string Tag)>();
        while (reader.Read())
        {
            pending.Add((reader.GetInt64(0), reader.GetString(1), reader.GetString(2), reader.GetString(3)));
        }

        foreach (var row in pending)
        {
            UpsertVector(row.Id, row.Kind + " " + row.Tag + " " + row.Text);
        }
    }

    private void UpsertVector(long id, string text)
    {
        if (_connection is null)
        {
            return;
        }

        var json = TwinEmbed.Serialize(TwinEmbed.Vector(text));
        using var cmd = _connection.CreateCommand();
        cmd.CommandText = """
            INSERT INTO capture_vectors (capture_id, model, vector_json)
            VALUES ($id, $m, $j)
            ON CONFLICT(capture_id) DO UPDATE SET model = $m, vector_json = $j
            """;
        cmd.Parameters.AddWithValue("$id", id);
        cmd.Parameters.AddWithValue("$m", TwinEmbed.Model);
        cmd.Parameters.AddWithValue("$j", json);
        cmd.ExecuteNonQuery();
    }

    private Dictionary<string, float> GetVector(long id)
    {
        if (_connection is null)
        {
            return new Dictionary<string, float>(StringComparer.OrdinalIgnoreCase);
        }

        using var cmd = _connection.CreateCommand();
        cmd.CommandText = "SELECT vector_json FROM capture_vectors WHERE capture_id = $id AND model = $m LIMIT 1";
        cmd.Parameters.AddWithValue("$id", id);
        cmd.Parameters.AddWithValue("$m", TwinEmbed.Model);
        var json = cmd.ExecuteScalar() as string;
        return string.IsNullOrWhiteSpace(json)
            ? new Dictionary<string, float>(StringComparer.OrdinalIgnoreCase)
            : TwinEmbed.Deserialize(json);
    }

    private bool Allows(VaultRow row)
    {
        var skip = (_settings.Current.SkipKinds ?? "")
            .Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
        return skip.Length == 0 || !skip.Contains(row.Kind, StringComparer.OrdinalIgnoreCase);
    }

    private static List<VaultRow> ReadCaptures(SqliteCommand cmd)
    {
        var rows = new List<VaultRow>();
        using var reader = cmd.ExecuteReader();
        while (reader.Read())
        {
            rows.Add(new VaultRow(
                reader.GetInt64(0),
                reader.GetString(1),
                reader.GetString(2),
                reader.GetString(3),
                reader.GetString(4)));
        }

        return rows;
    }

    private int Count(string table)
    {
        using var cmd = _connection!.CreateCommand();
        cmd.CommandText = "SELECT COUNT(*) FROM " + table;
        return Convert.ToInt32(cmd.ExecuteScalar());
    }

    private void EnsureColumn(string table, string column, string alterSql)
    {
        using var cmd = _connection!.CreateCommand();
        cmd.CommandText = "PRAGMA table_info(" + table + ")";
        using var reader = cmd.ExecuteReader();
        while (reader.Read())
        {
            if (string.Equals(reader.GetString(1), column, StringComparison.OrdinalIgnoreCase))
            {
                return;
            }
        }

        reader.Close();
        using var alter = _connection.CreateCommand();
        alter.CommandText = alterSql;
        alter.ExecuteNonQuery();
    }

    private void Ensure()
    {
        if (_connection is null)
        {
            Open();
        }
    }

    public void Dispose() => _connection?.Dispose();
}
