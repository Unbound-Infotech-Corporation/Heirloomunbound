using System.Text.RegularExpressions;

namespace Heirloom.Services;

public sealed record PhoneContact(string Name, string E164, string HeirId = "");

public sealed record PhoneCallIntent(
    string ToE164,
    string ContactName,
    string Summary,
    bool Resolved);

/// <summary>
/// Owner sitting: “call Mom”, “call +1…”. Never auto-dials — Twin confirms in-document.
/// </summary>
public static class PhoneIntent
{
    public static string NormalizeE164(string? raw, string defaultRegion = "1")
    {
        var text = (raw ?? "").Trim();
        if (text.Length == 0)
        {
            return "";
        }

        if (text.StartsWith('+'))
        {
            var plusDigits = Digits(text);
            return plusDigits.Length >= 8 ? "+" + plusDigits : "";
        }

        var digits = Digits(text);
        if (digits.Length == 0)
        {
            return "";
        }

        if (digits.Length == 10 && defaultRegion.Length > 0)
        {
            return "+" + defaultRegion + digits;
        }

        if (digits.Length == 11 && digits.StartsWith('1'))
        {
            return "+" + digits;
        }

        return digits.Length >= 8 ? "+" + digits : "";
    }

    public static bool TryParse(string? utterance, IReadOnlyList<PhoneContact>? contacts, out PhoneCallIntent intent)
    {
        intent = default!;
        var raw = Strip((utterance ?? "").Trim());
        if (raw.Length == 0)
        {
            return false;
        }

        if (LooksLikeOrdinaryTalk(raw))
        {
            return false;
        }

        var give = Regex.Match(
            raw,
            @"^(?:give)\s+(.+?)\s+a\s+(?:call|ring)$",
            RegexOptions.IgnoreCase);
        var place = Regex.Match(
            raw,
            @"^(?:place\s+a\s+call\s+to|call|dial|phone)\s+(?:up\s+)?(.+)$",
            RegexOptions.IgnoreCase);
        var ring = Regex.Match(
            raw,
            @"^ring\s+(.+)$",
            RegexOptions.IgnoreCase);

        string target;
        var verbIsRing = false;
        if (give.Success)
        {
            target = give.Groups[1].Value.Trim();
        }
        else if (place.Success)
        {
            target = place.Groups[1].Value.Trim();
        }
        else if (ring.Success)
        {
            target = ring.Groups[1].Value.Trim();
            verbIsRing = true;
        }
        else
        {
            return false;
        }

        target = Regex.Replace(target, @"^(?:my|the|a|an)\s+", "", RegexOptions.IgnoreCase).Trim();
        target = target.Trim().Trim('"', '\'', '“', '”');
        if (target.Length == 0)
        {
            return false;
        }

        var e164 = NormalizeE164(target);
        if (e164.Length > 0)
        {
            var named = MatchContact(e164, target, contacts);
            var label = named?.Name is { Length: > 0 } n ? n : e164;
            intent = new PhoneCallIntent(
                e164,
                label,
                "Place a call to " + label + " (" + e164 + "). Confirm in this document.",
                true);
            return true;
        }

        var hit = MatchName(target, contacts);
        if (hit is not null)
        {
            intent = new PhoneCallIntent(
                hit.E164,
                string.IsNullOrWhiteSpace(hit.Name) ? hit.E164 : hit.Name,
                "Place a call to " + (string.IsNullOrWhiteSpace(hit.Name) ? hit.E164 : hit.Name)
                    + " (" + hit.E164 + "). Confirm in this document.",
                true);
            return true;
        }

        if (verbIsRing)
        {
            return false;
        }

        if (NotAPerson(target))
        {
            return false;
        }

        if (!Regex.IsMatch(target, @"^[A-Za-z][A-Za-z .'\-]{1,40}$"))
        {
            return false;
        }

        intent = new PhoneCallIntent(
            "",
            target,
            "“" + target + "” is not on Who may call. Add them in Phone, then ask again.",
            false);
        return true;
    }

    private static bool LooksLikeOrdinaryTalk(string raw)
    {
        var t = raw.ToLowerInvariant();
        if (Regex.IsMatch(t, @"\b(recall|recalled|recalling)\b"))
        {
            return true;
        }

        if (Regex.IsMatch(t, @"\b(what do you call|how do you call|what's it called|whats it called)\b"))
        {
            return true;
        }

        if (Regex.IsMatch(t, @"^call (it|this|that|the sitting|a day)\b"))
        {
            return true;
        }

        if (Regex.IsMatch(t, @"\b(on call|called|calling)\b") && !t.StartsWith("call "))
        {
            return true;
        }

        return false;
    }

    private static bool NotAPerson(string target)
    {
        var key = Collapse(target).ToLowerInvariant();
        return key is "line" or "home" or "number" or "studio" or "sitting" or "archive"
            or "them" or "him" or "her" or "it" or "this" or "that" or "me" or "you";
    }

    private static PhoneContact? MatchContact(string e164, string rawName, IReadOnlyList<PhoneContact>? contacts)
    {
        if (contacts is null)
        {
            return null;
        }

        foreach (var row in contacts)
        {
            if (string.Equals(NormalizeE164(row.E164), e164, StringComparison.Ordinal))
            {
                return row;
            }
        }

        return MatchName(rawName, contacts);
    }

    private static PhoneContact? MatchName(string name, IReadOnlyList<PhoneContact>? contacts)
    {
        if (contacts is null || string.IsNullOrWhiteSpace(name))
        {
            return null;
        }

        var needle = Collapse(name);
        PhoneContact? contains = null;
        var containsCount = 0;
        foreach (var row in contacts)
        {
            var label = Collapse(row.Name);
            if (label.Length == 0)
            {
                continue;
            }

            if (string.Equals(label, needle, StringComparison.OrdinalIgnoreCase))
            {
                return row;
            }

            if (label.Contains(needle, StringComparison.OrdinalIgnoreCase)
                || needle.Contains(label, StringComparison.OrdinalIgnoreCase))
            {
                contains = row;
                containsCount++;
            }
        }

        return containsCount == 1 ? contains : null;
    }

    private static string Strip(string text)
    {
        var t = Regex.Replace(text, @"^(?:please\s+)+", "", RegexOptions.IgnoreCase);
        t = Regex.Replace(t, @"^(?:can you|could you|would you)\s+", "", RegexOptions.IgnoreCase);
        t = Regex.Replace(t, @"\s+(?:please|for me)$", "", RegexOptions.IgnoreCase);
        return Regex.Replace(t.Trim(), @"[\s,.!?]+$", "").Trim();
    }

    private static string Collapse(string name) =>
        string.Join(' ', (name ?? "").Trim().Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries));

    private static string Digits(string text) =>
        Regex.Replace(text ?? "", @"\D+", "");
}
