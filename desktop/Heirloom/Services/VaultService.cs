using Microsoft.Data.Sqlite;

namespace Heirloom.Services;

public sealed record VaultRow(long Id, string Created, string Kind, string Text, string Tag);
public sealed record LetterRow(long Id, string Title, string Body, string ForPerson, string Trigger, bool Sealed, string Created);
public sealed record HeirRow(long Id, string Name, string Relation, bool Consent, string Created);
public sealed record VaultStats(int Captures, int Letters, int Heirs, IReadOnlyDictionary<string, int> ByKind, int Completeness);

public sealed class VaultService : IDisposable
{
    private readonly SettingsStore _settings;
    private SqliteConnection? _connection;

    public string Status { get; private set; } = "Vault closed";
    public string RootPath { get; private set; } = "";

    public VaultService(SettingsStore settings)
    {
        _settings = settings;
    }

    public void Open()
    {
        var root = string.IsNullOrWhiteSpace(_settings.Current.LibraryPath)
            ? AppPaths.DefaultVaultPath
            : _settings.Current.LibraryPath;
        Directory.CreateDirectory(root);
        RootPath = root;
        var db = Path.Combine(root, "vault.db");
        _connection = new SqliteConnection("Data Source=" + db);
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
            """;
        cmd.ExecuteNonQuery();
        EnsureColumn("captures", "tag", "ALTER TABLE captures ADD COLUMN tag TEXT NOT NULL DEFAULT ''");
        EnsureColumn("letters", "for_person", "ALTER TABLE letters ADD COLUMN for_person TEXT NOT NULL DEFAULT ''");
        EnsureColumn("letters", "trigger_when", "ALTER TABLE letters ADD COLUMN trigger_when TEXT NOT NULL DEFAULT 'after_release'");
        Status = "Vault · " + root;
    }

    public void AddCapture(string kind, string text, string tag = "")
    {
        Ensure();
        using var cmd = _connection!.CreateCommand();
        cmd.CommandText = "INSERT INTO captures (created_utc, kind, text, tag) VALUES ($c, $k, $t, $g)";
        cmd.Parameters.AddWithValue("$c", DateTime.UtcNow.ToString("o"));
        cmd.Parameters.AddWithValue("$k", kind);
        cmd.Parameters.AddWithValue("$t", text);
        cmd.Parameters.AddWithValue("$g", tag);
        cmd.ExecuteNonQuery();
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

    public IReadOnlyList<VaultRow> Search(string query, string? kind = null, int limit = 80)
    {
        Ensure();
        using var cmd = _connection!.CreateCommand();
        var like = "%" + query.Trim() + "%";
        if (string.IsNullOrWhiteSpace(kind) || kind == "all")
        {
            cmd.CommandText = "SELECT id, created_utc, kind, text, IFNULL(tag,'') FROM captures WHERE text LIKE $q OR tag LIKE $q OR kind LIKE $q ORDER BY id DESC LIMIT $n";
        }
        else
        {
            cmd.CommandText = "SELECT id, created_utc, kind, text, IFNULL(tag,'') FROM captures WHERE kind = $k AND (text LIKE $q OR tag LIKE $q) ORDER BY id DESC LIMIT $n";
            cmd.Parameters.AddWithValue("$k", kind);
        }

        cmd.Parameters.AddWithValue("$q", like);
        cmd.Parameters.AddWithValue("$n", limit);
        return ReadCaptures(cmd);
    }

    public string GroundedContext(int maxChars = 3500)
    {
        var rows = Recent(60);
        var builder = new System.Text.StringBuilder();
        foreach (var row in rows)
        {
            var line = $"[{row.Kind}{(string.IsNullOrWhiteSpace(row.Tag) ? "" : "/" + row.Tag)}] {row.Text.Trim()}";
            if (builder.Length + line.Length > maxChars)
            {
                break;
            }

            builder.AppendLine(line);
        }

        return builder.ToString();
    }

    public IReadOnlyList<VaultRow> CitationsFor(string query, int limit = 4)
    {
        if (string.IsNullOrWhiteSpace(query))
        {
            return [];
        }

        return Search(query, null, limit);
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

    public void AddLetter(string title, string body, bool sealedLetter, string forPerson = "", string trigger = "after_release")
    {
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

    public string ExportArchive()
    {
        Ensure();
        var dest = Path.Combine(
            _settings.Current.LibraryPath,
            $"heirloom-export-{DateTime.UtcNow:yyyyMMdd}.json");
        var captures = Recent(10_000);
        var letters = Letters();
        var heirs = Heirs();
        var json =
            $$"""
            {"exported_utc":"{{DateTime.UtcNow:o}}","captures":[{{string.Join(",", captures.Select(c => $"{{\"id\":{c.Id},\"kind\":{System.Text.Json.JsonSerializer.Serialize(c.Kind)},\"tag\":{System.Text.Json.JsonSerializer.Serialize(c.Tag)},\"text\":{System.Text.Json.JsonSerializer.Serialize(c.Text)}}}"))}}],"letters":[{{string.Join(",", letters.Select(l => $"{{\"id\":{l.Id},\"title\":{System.Text.Json.JsonSerializer.Serialize(l.Title)},\"for\":{System.Text.Json.JsonSerializer.Serialize(l.ForPerson)},\"trigger\":{System.Text.Json.JsonSerializer.Serialize(l.Trigger)},\"sealed\":{l.Sealed.ToString().ToLowerInvariant()},\"body\":{System.Text.Json.JsonSerializer.Serialize(l.Body)}}}"))}}],"heirs":[{{string.Join(",", heirs.Select(h => $"{{\"id\":{h.Id},\"name\":{System.Text.Json.JsonSerializer.Serialize(h.Name)},\"relation\":{System.Text.Json.JsonSerializer.Serialize(h.Relation)},\"consent\":{h.Consent.ToString().ToLowerInvariant()}}}"))}}]}
            """;
        File.WriteAllText(dest, json);
        return dest;
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
