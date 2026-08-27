using Microsoft.Playwright;

namespace Heirloom.Services;

public sealed class BrowserSession : IDisposable
{
    private readonly SemaphoreSlim _gate = new(1, 1);
    private IPlaywright? _playwright;
    private IBrowserContext? _context;
    private IPage? _page;
    private bool _disposed;

    public async Task<ToolResult> RunAsync(
        string action,
        string url,
        string target,
        string text,
        string amount,
        CancellationToken cancellationToken)
    {
        await _gate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            return action switch
            {
                "goto" or "open" or "navigate" => await GotoAsync(url, cancellationToken).ConfigureAwait(false),
                "newtab" or "new_tab" => await NewTabAsync(url, cancellationToken).ConfigureAwait(false),
                "click" or "tap" => await ClickAsync(target, cancellationToken).ConfigureAwait(false),
                "type" or "fill" => await TypeAsync(target, text, cancellationToken).ConfigureAwait(false),
                "scroll" => await ScrollAsync(amount.Length > 0 ? amount : target, cancellationToken).ConfigureAwait(false),
                "back" => await BackAsync(cancellationToken).ConfigureAwait(false),
                "reload" or "refresh" => await ReloadAsync(cancellationToken).ConfigureAwait(false),
                "snapshot" or "read" => await SnapshotAsync(cancellationToken).ConfigureAwait(false),
                "close" => await CloseAsync().ConfigureAwait(false),
                _ => new ToolResult(false, "Browse action must be open, click, type, scroll, back, reload, snapshot, or close."),
            };
        }
        catch (OperationCanceledException)
        {
            return new ToolResult(false, "Stopped before the page finished.");
        }
        catch (TimeoutException)
        {
            return new ToolResult(false, "The page took too long. It may still be loading — try again in a moment.");
        }
        catch (PlaywrightException ex)
        {
            return new ToolResult(false, Humanize(ex.Message));
        }
        catch (Exception ex)
        {
            FaultLog.Write("browse", ex.Message);
            return new ToolResult(false, Humanize(ex.Message));
        }
        finally
        {
            _gate.Release();
        }
    }

    public void Dispose()
    {
        if (_disposed)
        {
            return;
        }

        _disposed = true;
        try
        {
            _context?.CloseAsync().GetAwaiter().GetResult();
        }
        catch
        {
            // Best-effort.
        }

        try
        {
            _playwright?.Dispose();
        }
        catch
        {
            // Best-effort.
        }

        _context = null;
        _page = null;
        _playwright = null;
        _gate.Dispose();
    }

    private async Task<ToolResult> GotoAsync(string url, CancellationToken cancellationToken)
    {
        if (string.IsNullOrWhiteSpace(url) || !Uri.TryCreate(url, UriKind.Absolute, out var uri) || uri.Scheme is not ("http" or "https"))
        {
            return new ToolResult(false, "Need a web address to open.");
        }

        var page = await EnsurePageAsync(cancellationToken).ConfigureAwait(false);
        if (page is null)
        {
            return DriverMissing(url);
        }

        await page.GotoAsync(uri.ToString(), new PageGotoOptions
        {
            WaitUntil = WaitUntilState.DOMContentLoaded,
            Timeout = 25_000,
        }).ConfigureAwait(false);
        try
        {
            await page.WaitForLoadStateAsync(LoadState.Load, new PageWaitForLoadStateOptions { Timeout = 8_000 }).ConfigureAwait(false);
        }
        catch
        {
            // DOM is enough to click or type.
        }

        var title = await SafeTitleAsync(page).ConfigureAwait(false);
        return new ToolResult(true, "Opened " + (string.IsNullOrWhiteSpace(title) ? uri.Host : title) + " in a Heirloom browser window. That window may not be signed into your usual accounts.");
    }

    private async Task<ToolResult> NewTabAsync(string url, CancellationToken cancellationToken)
    {
        var page = await EnsurePageAsync(cancellationToken).ConfigureAwait(false);
        if (page is null || _context is null)
        {
            return string.IsNullOrWhiteSpace(url)
                ? new ToolResult(false, "I could not open a new tab. Microsoft Edge was not available.")
                : DriverMissing(url);
        }

        try
        {
            _page = await _context.NewPageAsync().ConfigureAwait(false);
            _page.SetDefaultTimeout(12_000);
            _page.SetDefaultNavigationTimeout(25_000);
        }
        catch (Exception ex)
        {
            return new ToolResult(false, Humanize(ex.Message));
        }

        if (string.IsNullOrWhiteSpace(url))
        {
            return new ToolResult(true, "Opened a new tab.");
        }

        return await GotoAsync(url, cancellationToken).ConfigureAwait(false);
    }

    private async Task<ToolResult> ClickAsync(string target, CancellationToken cancellationToken)
    {
        if (string.IsNullOrWhiteSpace(target))
        {
            return new ToolResult(false, "Say what to click — a button or link name.");
        }

        var page = await RequirePageAsync(cancellationToken).ConfigureAwait(false);
        if (page is null)
        {
            return new ToolResult(false, "No Heirloom browser window is open. Open a site first, then click.");
        }

        if (LooksLikeFirstHit(target))
        {
            foreach (var first in FirstHitLocators(page, target))
            {
                try
                {
                    if (await first.CountAsync().ConfigureAwait(false) == 0)
                    {
                        continue;
                    }

                    await first.First.ClickAsync(new LocatorClickOptions { Timeout = 8_000 }).ConfigureAwait(false);
                    return new ToolResult(true, "Clicked the first " + FirstHitNoun(target) + ".");
                }
                catch (PlaywrightException)
                {
                    // Try the next locator.
                }
                catch (TimeoutException)
                {
                    // Try the next locator.
                }
            }
        }

        var locators = CandidateLocators(page, StripClickFlavor(target));
        foreach (var locator in locators)
        {
            try
            {
                if (await locator.CountAsync().ConfigureAwait(false) == 0)
                {
                    continue;
                }

                await locator.First.ClickAsync(new LocatorClickOptions { Timeout = 8_000 }).ConfigureAwait(false);
                return new ToolResult(true, "Clicked “" + target.Trim() + "”.");
            }
            catch (TimeoutException)
            {
                // Try the next locator.
            }
            catch (PlaywrightException)
            {
                // Try the next locator.
            }
        }

        return new ToolResult(false, "I could not find “" + target.Trim() + "” on this page. The page may still be loading, or that control uses a different name.");
    }

    private async Task<ToolResult> TypeAsync(string target, string text, CancellationToken cancellationToken)
    {
        if (string.IsNullOrEmpty(text))
        {
            return new ToolResult(false, "Nothing to type.");
        }

        var page = await RequirePageAsync(cancellationToken).ConfigureAwait(false);
        if (page is null)
        {
            return new ToolResult(false, "No Heirloom browser window is open. Open a site first, then type.");
        }

        if (!string.IsNullOrWhiteSpace(target))
        {
            var field = StripClickFlavor(target);
            IReadOnlyList<ILocator> fields = LooksLikeSearchBox(field)
                ? SearchBoxLocators(page)
                : CandidateLocators(page, field);
            foreach (var locator in fields)
            {
                try
                {
                    if (await locator.CountAsync().ConfigureAwait(false) == 0)
                    {
                        continue;
                    }

                    await locator.First.FillAsync(text, new LocatorFillOptions { Timeout = 8_000 }).ConfigureAwait(false);
                    await MaybeSubmitSearchAsync(locator.First, field).ConfigureAwait(false);
                    return new ToolResult(true, "Typed into “" + target.Trim() + "”.");
                }
                catch (PlaywrightException)
                {
                    // Try the next locator.
                }
                catch (TimeoutException)
                {
                    // Try the next locator.
                }
            }

            return new ToolResult(false, "I could not find a field named “" + target.Trim() + "” on this page.");
        }

        foreach (var box in SearchBoxLocators(page))
        {
            try
            {
                if (await box.CountAsync().ConfigureAwait(false) == 0)
                {
                    continue;
                }

                await box.First.FillAsync(text, new LocatorFillOptions { Timeout = 8_000 }).ConfigureAwait(false);
                await MaybeSubmitSearchAsync(box.First, "search").ConfigureAwait(false);
                return new ToolResult(true, "Typed into the search box.");
            }
            catch (PlaywrightException)
            {
                // Try the next field.
            }
            catch (TimeoutException)
            {
                // Try the next field.
            }
        }

        await page.Keyboard.TypeAsync(text, new KeyboardTypeOptions { Delay = 15 }).ConfigureAwait(false);
        return new ToolResult(true, "Typed " + text.Length + " characters into the page.");
    }

    private async Task<ToolResult> BackAsync(CancellationToken cancellationToken)
    {
        var page = await RequirePageAsync(cancellationToken).ConfigureAwait(false);
        if (page is null)
        {
            return new ToolResult(false, "No Heirloom browser window is open.");
        }

        await page.GoBackAsync(new PageGoBackOptions { Timeout = 12_000, WaitUntil = WaitUntilState.DOMContentLoaded }).ConfigureAwait(false);
        return new ToolResult(true, "Went back.");
    }

    private async Task<ToolResult> ReloadAsync(CancellationToken cancellationToken)
    {
        var page = await RequirePageAsync(cancellationToken).ConfigureAwait(false);
        if (page is null)
        {
            return new ToolResult(false, "No Heirloom browser window is open.");
        }

        await page.ReloadAsync(new PageReloadOptions { Timeout = 20_000, WaitUntil = WaitUntilState.DOMContentLoaded }).ConfigureAwait(false);
        return new ToolResult(true, "Reloaded the page.");
    }

    private async Task<ToolResult> ScrollAsync(string amount, CancellationToken cancellationToken)
    {
        var page = await RequirePageAsync(cancellationToken).ConfigureAwait(false);
        if (page is null)
        {
            return new ToolResult(false, "No Heirloom browser window is open.");
        }

        var dy = ParseScroll(amount);
        await page.EvaluateAsync("dy => window.scrollBy(0, dy)", dy).ConfigureAwait(false);
        return new ToolResult(true, dy >= 0 ? "Scrolled down." : "Scrolled up.");
    }

    private async Task<ToolResult> SnapshotAsync(CancellationToken cancellationToken)
    {
        var page = await RequirePageAsync(cancellationToken).ConfigureAwait(false);
        if (page is null)
        {
            return new ToolResult(false, "No Heirloom browser window is open.");
        }

        var title = await SafeTitleAsync(page).ConfigureAwait(false);
        var url = page.Url;
        string body;
        try
        {
            body = await page.InnerTextAsync("body", new PageInnerTextOptions { Timeout = 8_000 }).ConfigureAwait(false);
        }
        catch
        {
            body = "";
        }

        body = System.Text.RegularExpressions.Regex.Replace(body ?? "", @"\s+", " ").Trim();
        if (body.Length > 1500)
        {
            body = body[..1500] + "…";
        }

        var line = (string.IsNullOrWhiteSpace(title) ? "Page" : title) + " — " + url;
        return new ToolResult(true, string.IsNullOrWhiteSpace(body) ? line : line + "\n" + body);
    }

    private async Task<ToolResult> CloseAsync()
    {
        try
        {
            if (_context is not null)
            {
                await _context.CloseAsync().ConfigureAwait(false);
            }
        }
        catch
        {
            // Best-effort.
        }

        _context = null;
        _page = null;
        return new ToolResult(true, "Closed the Heirloom browser window. Your everyday browser is unchanged.");
    }

    private async Task<IPage?> EnsurePageAsync(CancellationToken cancellationToken)
    {
        if (_page is { } open && !_page.IsClosed)
        {
            return open;
        }

        try
        {
            _playwright ??= await Playwright.CreateAsync().ConfigureAwait(false);
        }
        catch (Exception ex)
        {
            FaultLog.Write("browse-create", ex.Message);
            return null;
        }

        var profile = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "Heirloom",
            "browser-profile");
        Directory.CreateDirectory(profile);

        var options = new BrowserTypeLaunchPersistentContextOptions
        {
            Channel = "msedge",
            Headless = false,
            ViewportSize = new ViewportSize { Width = 1280, Height = 800 },
            IgnoreHTTPSErrors = false,
            Timeout = 25_000,
        };

        try
        {
            _context = await _playwright.Chromium.LaunchPersistentContextAsync(profile, options).ConfigureAwait(false);
        }
        catch (PlaywrightException)
        {
            options.Channel = "chrome";
            try
            {
                _context = await _playwright.Chromium.LaunchPersistentContextAsync(profile, options).ConfigureAwait(false);
            }
            catch (Exception ex)
            {
                FaultLog.Write("browse-launch", ex.Message);
                return null;
            }
        }

        cancellationToken.ThrowIfCancellationRequested();
        _page = _context.Pages.Count > 0 ? _context.Pages[0] : await _context.NewPageAsync().ConfigureAwait(false);
        _page.SetDefaultTimeout(12_000);
        _page.SetDefaultNavigationTimeout(25_000);
        return _page;
    }

    private async Task<IPage?> RequirePageAsync(CancellationToken cancellationToken)
    {
        if (_page is { } open && !_page.IsClosed)
        {
            return open;
        }

        return await EnsurePageAsync(cancellationToken).ConfigureAwait(false);
    }

    private static IReadOnlyList<ILocator> CandidateLocators(IPage page, string target)
    {
        var name = target.Trim();
        var list = new List<ILocator>
        {
            page.GetByRole(AriaRole.Button, new() { Name = name, Exact = false }),
            page.GetByRole(AriaRole.Link, new() { Name = name, Exact = false }),
            page.GetByRole(AriaRole.Tab, new() { Name = name, Exact = false }),
            page.GetByLabel(name, new() { Exact = false }),
            page.GetByPlaceholder(name),
            page.GetByText(name, new() { Exact = false }),
        };
        if (name.StartsWith('#') || name.StartsWith('.') || name.StartsWith('['))
        {
            list.Insert(0, page.Locator(name));
        }

        return list;
    }

    private static IReadOnlyList<ILocator> FirstHitLocators(IPage page, string target)
    {
        var noun = FirstHitNoun(target);
        var list = new List<ILocator>();
        if (noun is "video" or "result")
        {
            list.Add(page.Locator("a#video-title"));
            list.Add(page.Locator("ytd-video-renderer a#video-title-link"));
            list.Add(page.Locator("a[href*='watch?v=']"));
        }

        list.Add(page.Locator("a[href]").First);
        list.Add(page.GetByRole(AriaRole.Link));
        return list;
    }

    private static IReadOnlyList<ILocator> SearchBoxLocators(IPage page) =>
    [
        page.GetByRole(AriaRole.Searchbox),
        page.Locator("input[name='q']"),
        page.Locator("input[name='search_query']"),
        page.Locator("input[type='search']"),
        page.Locator("input#search"),
        page.Locator("textarea[name='q']"),
    ];

    private static bool LooksLikeFirstHit(string target) =>
        System.Text.RegularExpressions.Regex.IsMatch(target ?? "", @"\b(first|top)\b.*\b(link|video|result|hit)\b|\b(link|video|result)\b.*\b(first|top)\b", System.Text.RegularExpressions.RegexOptions.IgnoreCase);

    private static string FirstHitNoun(string target)
    {
        var t = (target ?? "").ToLowerInvariant();
        if (t.Contains("video"))
        {
            return "video";
        }

        if (t.Contains("result") || t.Contains("hit"))
        {
            return "result";
        }

        return "link";
    }

    private static async Task MaybeSubmitSearchAsync(ILocator field, string name)
    {
        if (!LooksLikeSearchBox(name))
        {
            return;
        }

        try
        {
            await field.PressAsync("Enter", new LocatorPressOptions { Timeout = 2_000 }).ConfigureAwait(false);
        }
        catch
        {
            // Fill is enough when Enter is not a search submit.
        }
    }

    private static bool LooksLikeSearchBox(string target) =>
        System.Text.RegularExpressions.Regex.IsMatch(target ?? "", @"\b(search|query|find|google|youtube)\b", System.Text.RegularExpressions.RegexOptions.IgnoreCase);

    private static string StripClickFlavor(string target) =>
        System.Text.RegularExpressions.Regex.Replace(target ?? "", @"^(the |a |an |button |link |first |top )+", "", System.Text.RegularExpressions.RegexOptions.IgnoreCase).Trim();

    private static async Task<string> SafeTitleAsync(IPage page)
    {
        try
        {
            return await page.TitleAsync().ConfigureAwait(false);
        }
        catch
        {
            return "";
        }
    }

    private static int ParseScroll(string amount)
    {
        var t = (amount ?? "").Trim().ToLowerInvariant();
        if (t is "up" or "top")
        {
            return -800;
        }

        if (t is "down" or "page" or "pagedown" or "")
        {
            return 800;
        }

        if (int.TryParse(t, out var px))
        {
            return px;
        }

        return 800;
    }

    private static ToolResult DriverMissing(string url) =>
        new(false, "I could not start a Heirloom browser window (Edge or Chrome). I can still open " + url + " in your usual browser.");

    private static string Humanize(string message)
    {
        var m = (message ?? "").Trim();
        if (m.Contains("Timeout", StringComparison.OrdinalIgnoreCase)
            || m.Contains("exceeded", StringComparison.OrdinalIgnoreCase))
        {
            return "The page took too long. It may still be loading — try again in a moment.";
        }

        if (m.Contains("closed", StringComparison.OrdinalIgnoreCase)
            || m.Contains("Target page", StringComparison.OrdinalIgnoreCase))
        {
            return "The Heirloom browser window closed. Open the site again, then retry.";
        }

        if (m.Contains("Executable doesn't exist", StringComparison.OrdinalIgnoreCase)
            || m.Contains("browserType.launch", StringComparison.OrdinalIgnoreCase)
            || m.Contains("chromium", StringComparison.OrdinalIgnoreCase))
        {
            return "Microsoft Edge was not available for in-page clicks. Sites still open in your usual browser.";
        }

        if (m.Contains("Access is denied", StringComparison.OrdinalIgnoreCase)
            || m.Contains("permission", StringComparison.OrdinalIgnoreCase))
        {
            return "This PC blocked the Heirloom browser window. Check that Heirloom may open Edge.";
        }

        return m.Length > 240 ? m[..240] + "…" : m;
    }
}
