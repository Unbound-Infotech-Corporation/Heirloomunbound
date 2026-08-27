using System.Text.RegularExpressions;

namespace Heirloom.Services;

public sealed record WebBrowseIntent(
    string Action,
    string Url,
    string Label,
    string OpeningLine,
    string WorkingLine,
    string DoneLine,
    string FailLine,
    string? Query,
    string? Engine,
    string? ThenAction = null,
    string? ThenTarget = null,
    string? ThenText = null)
{
    public bool IsSearch => Action == "search";
    public bool HasFollowOn => !string.IsNullOrWhiteSpace(ThenAction);
}

public static class WebIntent
{
    public const string OpeningBrowser = "Opening browser…";

    private static readonly Dictionary<string, (string Url, string Label)> Sites = new(StringComparer.OrdinalIgnoreCase)
    {
        ["youtube"] = ("https://www.youtube.com", "YouTube"),
        ["you tube"] = ("https://www.youtube.com", "YouTube"),
        ["youtube.com"] = ("https://www.youtube.com", "YouTube"),
        ["youtu.be"] = ("https://www.youtube.com", "YouTube"),
        ["gmail"] = ("https://mail.google.com", "Gmail"),
        ["google mail"] = ("https://mail.google.com", "Gmail"),
        ["googlemail"] = ("https://mail.google.com", "Gmail"),
        ["google"] = ("https://www.google.com", "Google"),
        ["google.com"] = ("https://www.google.com", "Google"),
        ["maps"] = ("https://maps.google.com", "Google Maps"),
        ["google maps"] = ("https://maps.google.com", "Google Maps"),
        ["facebook"] = ("https://www.facebook.com", "Facebook"),
        ["fb"] = ("https://www.facebook.com", "Facebook"),
        ["instagram"] = ("https://www.instagram.com", "Instagram"),
        ["insta"] = ("https://www.instagram.com", "Instagram"),
        ["twitter"] = ("https://twitter.com", "X"),
        ["x.com"] = ("https://x.com", "X"),
        ["amazon"] = ("https://www.amazon.com", "Amazon"),
        ["netflix"] = ("https://www.netflix.com", "Netflix"),
        ["wikipedia"] = ("https://en.wikipedia.org", "Wikipedia"),
        ["wiki"] = ("https://en.wikipedia.org", "Wikipedia"),
        ["github"] = ("https://github.com", "GitHub"),
        ["github.com"] = ("https://github.com", "GitHub"),
        ["reddit"] = ("https://www.reddit.com", "Reddit"),
        ["bing"] = ("https://www.bing.com", "Bing"),
        ["duckduckgo"] = ("https://duckduckgo.com", "DuckDuckGo"),
        ["ddg"] = ("https://duckduckgo.com", "DuckDuckGo"),
        ["outlook"] = ("https://outlook.live.com", "Outlook"),
        ["outlook.com"] = ("https://outlook.live.com", "Outlook"),
        ["hotmail"] = ("https://outlook.live.com", "Outlook"),
        ["yahoo"] = ("https://www.yahoo.com", "Yahoo"),
        ["yahoo mail"] = ("https://mail.yahoo.com", "Yahoo Mail"),
        ["linkedin"] = ("https://www.linkedin.com", "LinkedIn"),
        ["whatsapp"] = ("https://web.whatsapp.com", "WhatsApp"),
        ["google news"] = ("https://news.google.com", "Google News"),
        ["news"] = ("https://news.google.com", "Google News"),
        ["weather"] = ("https://www.google.com/search?q=weather", "weather"),
        ["drive"] = ("https://drive.google.com", "Google Drive"),
        ["google drive"] = ("https://drive.google.com", "Google Drive"),
        ["calendar"] = ("https://calendar.google.com", "Google Calendar"),
        ["google calendar"] = ("https://calendar.google.com", "Google Calendar"),
        ["docs"] = ("https://docs.google.com", "Google Docs"),
        ["google docs"] = ("https://docs.google.com", "Google Docs"),
        ["sheets"] = ("https://sheets.google.com", "Google Sheets"),
        ["translate"] = ("https://translate.google.com", "Google Translate"),
        ["tiktok"] = ("https://www.tiktok.com", "TikTok"),
        ["pinterest"] = ("https://www.pinterest.com", "Pinterest"),
        ["ebay"] = ("https://www.ebay.com", "eBay"),
        ["twitch"] = ("https://www.twitch.tv", "Twitch"),
        ["hulu"] = ("https://www.hulu.com", "Hulu"),
        ["spotify web"] = ("https://open.spotify.com", "Spotify"),
        ["zoom"] = ("https://zoom.us", "Zoom"),
        ["cnn"] = ("https://www.cnn.com", "CNN"),
        ["bbc"] = ("https://www.bbc.com", "BBC"),
        ["nytimes"] = ("https://www.nytimes.com", "The New York Times"),
        ["new york times"] = ("https://www.nytimes.com", "The New York Times"),
    };

    public static bool NeedsPageControl(string utterance)
    {
        var t = (utterance ?? "").ToLowerInvariant();
        return Regex.IsMatch(t, @"\b(click|tap|press|type|enter|fill|scroll|select|hover|check the box|submit|go back|reload|refresh)\b");
    }

    public static bool TrySite(string name, out string url, out string label)
    {
        url = "";
        label = "";
        var key = Collapse(name);
        if (key.Length == 0)
        {
            return false;
        }

        key = Regex.Replace(key, @"^(the |website |site |page )+", "", RegexOptions.IgnoreCase).Trim();
        if (Sites.TryGetValue(key, out var hit))
        {
            url = hit.Url;
            label = hit.Label;
            return true;
        }

        if (key.StartsWith("www.", StringComparison.OrdinalIgnoreCase))
        {
            key = key[4..];
            if (Sites.TryGetValue(key, out hit))
            {
                url = hit.Url;
                label = hit.Label;
                return true;
            }
        }

        return false;
    }

    public static bool TryParse(string? utterance, out WebBrowseIntent intent)
    {
        intent = default!;
        var raw = StripLead(StripTail((utterance ?? "").Trim()));
        if (raw.Length == 0)
        {
            return false;
        }

        var lower = raw.ToLowerInvariant();
        if (IsAppOrder(lower))
        {
            return false;
        }

        var (head, thenAction, thenTarget, thenText) = SplitFollowOn(raw);

        if (TrySearch(head, out intent))
        {
            intent = WithFollowOn(intent, thenAction, thenTarget, thenText);
            return true;
        }

        if (TryOpen(head, out intent))
        {
            intent = WithFollowOn(intent, thenAction, thenTarget, thenText);
            return true;
        }

        if (string.IsNullOrWhiteSpace(thenAction) && TryPageOnly(raw, out intent))
        {
            return true;
        }

        return false;
    }

    public static bool LooksDestructive(string target)
    {
        var t = (target ?? "").ToLowerInvariant();
        return Regex.IsMatch(t, @"\b(delete|remove permanently|destroy|wipe|purchase|buy now|pay now|place order|confirm order|transfer|wire|send payment|empty trash|factory reset|unsubscribe all)\b");
    }

    public static bool LooksSecretField(string target) =>
        Regex.IsMatch(target ?? "", @"\b(password|passwd|pin|ssn|social security|cvv|card number)\b", RegexOptions.IgnoreCase);

    public static string NavigatingLine(string label) => "Navigating to " + label + "…";

    public static string SearchingLine(string label, string query) =>
        "Searching " + label + " for “" + query + "”…";

    public static string DoneOpenLine(string label) => "Done — " + label + " is open.";

    public static string DoneSearchLine(string label, string query) =>
        "Done — searched " + label + " for “" + query + "”.";

    public static string FailOpenLine(string label) =>
        "Could not open " + label + ". Check that this computer allows Heirloom to start a browser.";

    public static string FailSearchLine(string label, string query) =>
        "Could not search " + label + " for “" + query + "”. Check that this computer allows Heirloom to start a browser.";

    private static bool TrySearch(string raw, out WebBrowseIntent intent)
    {
        intent = default!;

        var openAndSearch = Regex.Match(
            raw,
            @"^(?:open|launch|go to|visit|navigate to|browse(?: to)?|take me to)\s+(?:(?:a |the |my )?(?:web )?browser(?:\s+and)?\s+(?:go to\s+)?)?(google|youtube|bing|duckduckgo|amazon|wikipedia|maps)(?:\.com)?\s+and\s+(?:then\s+)?(?:search|look up|find)(?:\s+for)?\s+(.+)$",
            RegexOptions.IgnoreCase);
        if (openAndSearch.Success)
        {
            intent = Search(openAndSearch.Groups[1].Value, openAndSearch.Groups[2].Value, LabelForEngine(openAndSearch.Groups[1].Value));
            return true;
        }

        var youtube = Regex.Match(
            raw,
            @"^(?:search(?:\s+on)?\s+youtube(?:\s+for)?|youtube\s+(?:search(?:\s+for)?|for)|find on youtube(?:\s+for)?|look up on youtube(?:\s+for)?)\s+(.+)$",
            RegexOptions.IgnoreCase);
        if (youtube.Success)
        {
            intent = Search("youtube", youtube.Groups[1].Value, "YouTube");
            return true;
        }

        var onEngine = Regex.Match(
            raw,
            @"^(?:search(?:\s+the web)?(?:\s+for)?|look up|find)\s+(.+?)\s+on\s+(google|youtube|bing|duckduckgo|amazon|wikipedia|maps)\s*$",
            RegexOptions.IgnoreCase);
        if (onEngine.Success)
        {
            intent = Search(onEngine.Groups[2].Value, onEngine.Groups[1].Value, LabelForEngine(onEngine.Groups[2].Value));
            return true;
        }

        var googleSearch = Regex.Match(
            raw,
            @"^(?:google search(?:\s+for)?|search google(?:\s+for)?|search the web(?:\s+for)?|search online(?:\s+for)?|look up)\s+(.+)$",
            RegexOptions.IgnoreCase);
        if (googleSearch.Success)
        {
            intent = Search("google", googleSearch.Groups[1].Value, "Google");
            return true;
        }

        var google = Regex.Match(raw, @"^google\s+(?!chrome\b)(.+)$", RegexOptions.IgnoreCase);
        if (google.Success)
        {
            intent = Search("google", google.Groups[1].Value, "Google");
            return true;
        }

        var bing = Regex.Match(raw, @"^bing\s+(.+)$", RegexOptions.IgnoreCase);
        if (bing.Success)
        {
            intent = Search("bing", bing.Groups[1].Value, "Bing");
            return true;
        }

        return false;
    }

    private static bool TryOpen(string raw, out WebBrowseIntent intent)
    {
        intent = default!;
        var opened = Regex.Match(
            raw,
            @"^(?:open|launch|start|go to|visit|navigate to|browse(?: to)?|take me to|show me)(?:\s+(?:up|a|the|my|this))?(?:\s+(?:web\s*)?browser|\s+new\s+(?:tab|window)|\s+(?:tab|window))?(?:\s+and)?(?:\s+(?:go to|open|visit|navigate to|browse(?: to)?|load))?\s+(.+)$",
            RegexOptions.IgnoreCase);
        var target = opened.Success ? opened.Groups[1].Value.Trim() : raw.Trim();
        target = StripBrowserFlavor(target);
        if (target.Length == 0 || Regex.IsMatch(target, @"^(?:a |the |my )?(?:web )?browser$|^(?:a |the )?(?:new )?(?:tab|window)$", RegexOptions.IgnoreCase))
        {
            if (Regex.IsMatch(raw, @"\b(browser|tab|window)\b", RegexOptions.IgnoreCase)
                && !Regex.IsMatch(raw, @"\b(click|type|fill|scroll)\b", RegexOptions.IgnoreCase))
            {
                intent = Open("https://www.google.com", "your browser");
                return true;
            }

            return false;
        }

        if (LaunchTarget.TryKnown(target, out var mapped)
            && !mapped.StartsWith("http", StringComparison.OrdinalIgnoreCase)
            && !mapped.StartsWith("ms-", StringComparison.OrdinalIgnoreCase))
        {
            return false;
        }

        if (target.StartsWith("http://", StringComparison.OrdinalIgnoreCase)
            || target.StartsWith("https://", StringComparison.OrdinalIgnoreCase))
        {
            intent = Open(target, HostLabel(target));
            return true;
        }

        if (TrySite(target, out var url, out var label))
        {
            intent = Open(url, label);
            return true;
        }

        var resolved = LaunchTarget.Resolve(target);
        if (resolved.Kind == LaunchTarget.Kind.Url)
        {
            intent = Open(resolved.Value, HostLabel(resolved.Value));
            return true;
        }

        return false;
    }

    private static bool TryPageOnly(string raw, out WebBrowseIntent intent)
    {
        intent = default!;
        var click = Regex.Match(raw, @"^(?:click|tap|press)(?:\s+on)?(?:\s+the)?\s+(.+)$", RegexOptions.IgnoreCase);
        if (click.Success)
        {
            var target = click.Groups[1].Value.Trim();
            intent = Page("click", target, "Clicking “" + target + "”…", "Done — clicked “" + target + "”.", "Could not click “" + target + "”. The page may still be loading, or that control uses a different name.");
            return true;
        }

        var fill = Regex.Match(raw, @"^(?:type|enter)\s+(.+?)\s+(?:in|into|on)\s+(?:the\s+)?(.+)$", RegexOptions.IgnoreCase);
        if (fill.Success)
        {
            var text = fill.Groups[1].Value.Trim();
            var field = fill.Groups[2].Value.Trim();
            intent = Page("type", field, "Typing into “" + field + "”…", "Done — typed into “" + field + "”.", "Could not find a field named “" + field + "” on this page.") with
            {
                ThenText = text,
            };
            return true;
        }

        var fillWith = Regex.Match(raw, @"^(?:fill)\s+(?:the\s+)?(.+?)\s+with\s+(.+)$", RegexOptions.IgnoreCase);
        if (fillWith.Success)
        {
            var field = fillWith.Groups[1].Value.Trim();
            var text = fillWith.Groups[2].Value.Trim();
            intent = Page("type", field, "Typing into “" + field + "”…", "Done — typed into “" + field + "”.", "Could not find a field named “" + field + "” on this page.") with
            {
                ThenText = text,
            };
            return true;
        }

        var scroll = Regex.Match(raw, @"^scroll(?:\s+(up|down|top|bottom))?$", RegexOptions.IgnoreCase);
        if (scroll.Success)
        {
            var dir = string.IsNullOrWhiteSpace(scroll.Groups[1].Value) ? "down" : scroll.Groups[1].Value;
            intent = Page("scroll", dir, "Scrolling " + dir + "…", "Done — scrolled " + dir + ".", "Could not scroll. Open a page first.");
            return true;
        }

        if (Regex.IsMatch(raw, @"^(?:go back|back)$", RegexOptions.IgnoreCase))
        {
            intent = Page("back", "", "Going back…", "Done — went back.", "Could not go back. No Heirloom browser window is open.");
            return true;
        }

        if (Regex.IsMatch(raw, @"^(?:reload|refresh)(?: the page)?$", RegexOptions.IgnoreCase))
        {
            intent = Page("reload", "", "Reloading the page…", "Done — reloaded the page.", "Could not reload. No Heirloom browser window is open.");
            return true;
        }

        return false;
    }

    private static WebBrowseIntent Open(string url, string label) =>
        new(
            "open",
            url,
            label,
            OpeningBrowser,
            NavigatingLine(label),
            DoneOpenLine(label),
            FailOpenLine(label),
            null,
            null);

    private static WebBrowseIntent Search(string engine, string query, string label)
    {
        var q = StripTail(StripLead(query));
        q = Regex.Replace(q, @"^(?:for\s+)+", "", RegexOptions.IgnoreCase).Trim();
        q = q.Trim().Trim('"', '\'', '“', '”');
        var url = engine.ToLowerInvariant() switch
        {
            "youtube" => "https://www.youtube.com/results?search_query=" + Encode(q),
            "bing" => "https://www.bing.com/search?q=" + Encode(q),
            "duckduckgo" or "ddg" => "https://duckduckgo.com/?q=" + Encode(q),
            "amazon" => "https://www.amazon.com/s?k=" + Encode(q),
            "wikipedia" or "wiki" => "https://en.wikipedia.org/w/index.php?search=" + Encode(q),
            "maps" => "https://www.google.com/maps/search/?api=1&query=" + Encode(q),
            _ => "https://www.google.com/search?q=" + Encode(q),
        };
        return new WebBrowseIntent(
            "search",
            url,
            label,
            OpeningBrowser,
            SearchingLine(label, q),
            DoneSearchLine(label, q),
            FailSearchLine(label, q),
            q,
            engine.ToLowerInvariant());
    }

    private static WebBrowseIntent Page(string action, string target, string working, string done, string fail) =>
        new(action, "", "", working, working, done, fail, null, null, action, target, null);

    private static WebBrowseIntent WithFollowOn(
        WebBrowseIntent intent,
        string? thenAction,
        string? thenTarget,
        string? thenText)
    {
        if (string.IsNullOrWhiteSpace(thenAction))
        {
            return intent;
        }

        var working = intent.IsSearch
            ? intent.WorkingLine.TrimEnd('…', '.') + ", then " + FollowVerb(thenAction, thenTarget, thenText)
            : thenAction == "click"
                ? "Navigating to " + intent.Label + ", then clicking “" + thenTarget + "”…"
                : FollowWorking(intent.WorkingLine, thenAction, thenTarget, thenText);

        return intent with
        {
            ThenAction = thenAction,
            ThenTarget = thenTarget,
            ThenText = thenText,
            WorkingLine = working,
            DoneLine = FollowDone(intent.DoneLine, thenAction, thenTarget, thenText),
        };
    }

    private static string FollowVerb(string? action, string? target, string? _) =>
        action switch
        {
            "click" => "clicking “" + target + "”…",
            "type" => "typing into “" + target + "”…",
            "scroll" => "scrolling " + (target ?? "down") + "…",
            _ => "continuing…",
        };

    private static string LabelForEngine(string engine) => engine.ToLowerInvariant() switch
    {
        "youtube" => "YouTube",
        "bing" => "Bing",
        "duckduckgo" or "ddg" => "DuckDuckGo",
        "amazon" => "Amazon",
        "wikipedia" or "wiki" => "Wikipedia",
        "maps" => "Google Maps",
        _ => "Google",
    };

    private static (string Head, string? ThenAction, string? ThenTarget, string? ThenText) SplitFollowOn(string raw)
    {
        var click = Regex.Match(
            raw,
            @"^(.+?)\s+and\s+(?:then\s+)?(?:click|tap|press)(?:\s+on)?(?:\s+the)?\s+(.+)$",
            RegexOptions.IgnoreCase);
        if (click.Success && !LooksLikeGoToJoin(click.Groups[1].Value, click.Groups[2].Value))
        {
            return (click.Groups[1].Value.Trim(), "click", click.Groups[2].Value.Trim(), null);
        }

        var type = Regex.Match(
            raw,
            @"^(.+?)\s+and\s+(?:then\s+)?(?:type|enter|fill)\s+(.+?)\s+(?:in|into|on)\s+(?:the\s+)?(.+)$",
            RegexOptions.IgnoreCase);
        if (type.Success)
        {
            return (type.Groups[1].Value.Trim(), "type", type.Groups[3].Value.Trim(), type.Groups[2].Value.Trim());
        }

        var scroll = Regex.Match(
            raw,
            @"^(.+?)\s+and\s+(?:then\s+)?scroll(?:\s+(up|down))?$",
            RegexOptions.IgnoreCase);
        if (scroll.Success)
        {
            var dir = string.IsNullOrWhiteSpace(scroll.Groups[2].Value) ? "down" : scroll.Groups[2].Value;
            return (scroll.Groups[1].Value.Trim(), "scroll", dir, null);
        }

        return (raw, null, null, null);
    }

    private static bool LooksLikeGoToJoin(string head, string rest)
    {
        var h = head.ToLowerInvariant();
        var r = rest.ToLowerInvariant();
        return h.Contains("browser") && (r.StartsWith("to ") || Regex.IsMatch(r, @"^(youtube|gmail|google|maps)\b"));
    }

    private static string FollowWorking(string current, string? action, string? target, string? _) =>
        action switch
        {
            "click" => "Clicking “" + target + "”…",
            "type" => "Typing into “" + target + "”…",
            "scroll" => "Scrolling " + (target ?? "down") + "…",
            _ => current,
        };

    private static string FollowDone(string current, string? action, string? target, string? _) =>
        action switch
        {
            "click" => "Done — opened the page and clicked “" + target + "”.",
            "type" => "Done — opened the page and typed into “" + target + "”.",
            "scroll" => "Done — opened the page and scrolled.",
            _ => current,
        };

    private static bool IsAppOrder(string lower)
    {
        if (Regex.IsMatch(lower, @"\b(notepad|calculator|explorer|terminal|powershell|vscode|visual studio code|settings|task manager|paint|word|excel|outlook)\b")
            && !Regex.IsMatch(lower, @"\b(gmail|youtube|google|browser|web|tab)\b"))
        {
            return LaunchTarget.TryKnown(StripOpenVerb(lower), out _);
        }

        return false;
    }

    private static string StripOpenVerb(string lower) =>
        Regex.Replace(lower, @"^(open|launch|start|go to)\s+", "").Trim();

    private static string StripBrowserFlavor(string target)
    {
        var t = target.Trim();
        t = Regex.Replace(t, @"^(?:a |the |my )?(?:web )?browser(?:\s+and)?(?:\s+(?:go to|open|visit))?\s+", "", RegexOptions.IgnoreCase);
        t = Regex.Replace(t, @"^(?:a |the |my )?(?:new )?(?:tab|window)(?:\s+and)?(?:\s+(?:go to|open|visit))?\s+", "", RegexOptions.IgnoreCase);
        t = Regex.Replace(t, @"\s+(?:in|with|using)\s+(?:my |the )?(?:default )?browser$", "", RegexOptions.IgnoreCase);
        t = Regex.Replace(t, @"\s+(?:in|with)\s+(?:a |the )?(?:new )?(?:tab|window)$", "", RegexOptions.IgnoreCase);
        t = Regex.Replace(t, @"\s+(?:in|with)\s+(?:google )?chrome$", "", RegexOptions.IgnoreCase);
        t = Regex.Replace(t, @"\s+(?:in|with)\s+(?:microsoft )?edge$", "", RegexOptions.IgnoreCase);
        t = Regex.Replace(t, @"\s+(?:in|with)\s+firefox$", "", RegexOptions.IgnoreCase);
        t = Regex.Replace(t, @"^(?:the |my |a |website |site )+", "", RegexOptions.IgnoreCase);
        return t.Trim().Trim('"');
    }

    private static string StripLead(string text)
    {
        var t = Regex.Replace(text, @"^(?:please\s+)+", "", RegexOptions.IgnoreCase);
        t = Regex.Replace(t, @"^(?:can you|could you|would you)\s+", "", RegexOptions.IgnoreCase);
        t = Regex.Replace(t, @"\s+(?:please|for me)$", "", RegexOptions.IgnoreCase);
        return t.Trim();
    }

    private static string StripTail(string text) =>
        Regex.Replace(text.Trim(), @"[\s,.!?]+$", "").Trim();

    private static string Collapse(string name) =>
        string.Join(' ', (name ?? "").Trim().Trim('"').Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries));

    private static string Encode(string query) => Uri.EscapeDataString(query.Trim());

    private static string HostLabel(string url)
    {
        try
        {
            var host = new Uri(url).Host;
            host = host.StartsWith("www.", StringComparison.OrdinalIgnoreCase) ? host[4..] : host;
            return TrySite(host, out _, out var label) ? label : host;
        }
        catch
        {
            return url;
        }
    }
}
