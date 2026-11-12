using System.Text.Json;

namespace Heirloom.BoxCore;

public sealed record BoxSessionBundle(string Session, string Refresh, string ExpiresAt)
{
    public bool HasRefresh => !string.IsNullOrWhiteSpace(Refresh);

    public string Encode() =>
        JsonSerializer.Serialize(new
        {
            v = 2,
            session = Session ?? "",
            refresh = Refresh ?? "",
            expires_at = ExpiresAt ?? "",
        });

    public static BoxSessionBundle? Parse(string? text)
    {
        var raw = (text ?? "").Trim();
        if (raw.Length == 0)
        {
            return null;
        }

        if (!raw.StartsWith('{'))
        {
            return new BoxSessionBundle(raw, "", "");
        }

        try
        {
            using var doc = JsonDocument.Parse(raw);
            var root = doc.RootElement;
            var session = Read(root, "session");
            if (session.Length == 0)
            {
                session = Read(root, "session_token");
            }

            if (session.Length == 0)
            {
                return null;
            }

            var refresh = Read(root, "refresh");
            if (refresh.Length == 0)
            {
                refresh = Read(root, "refresh_token");
            }

            return new BoxSessionBundle(session, refresh, Read(root, "expires_at"));
        }
        catch (JsonException)
        {
            return null;
        }
    }

    public static BoxSessionBundle? FromApi(JsonElement root)
    {
        if (root.ValueKind != JsonValueKind.Object)
        {
            return null;
        }

        var session = Read(root, "session_token");
        if (session.Length == 0)
        {
            return null;
        }

        return new BoxSessionBundle(session, Read(root, "refresh_token"), Read(root, "expires_at"));
    }

    private static string Read(JsonElement root, string name) =>
        root.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String
            ? (value.GetString() ?? "").Trim()
            : "";
}

public static class OwnerSession
{
    public const string SignedOutSignInAgain = "Signed out, sign in again";

    public static bool IsRejected(int statusCode) => statusCode == 401;

    public static void DeleteFile(string path)
    {
        try
        {
            if (!string.IsNullOrWhiteSpace(path) && File.Exists(path))
            {
                File.Delete(path);
            }
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
        }
    }
}
