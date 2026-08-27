using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Media.Imaging;
using Windows.UI;

namespace Heirloom.Services;

public sealed record ChromeChoice(string Id, string Label, string Hint);

public static class ThemeService
{
    public const string ModeIconsAndLabels = "iconsAndLabels";
    public const string ModeIcons = "icons";
    public const string ModeText = "text";

    public static event Action? Changed;

    public static string SchemeId { get; private set; } = "parchment";
    public static string ChromeMode { get; private set; } = ModeIconsAndLabels;
    public static string DockEdge { get; private set; } = "left";
    public static double DockSize { get; private set; } = 188;
    public static bool DockLocked { get; private set; }
    public static bool InspectorOpen { get; private set; } = true;
    public static double InspectorWidth { get; private set; } = 292;
    public static bool ShowIcons { get; private set; } = true;
    public static bool ShowLabels { get; private set; } = true;

    public static IReadOnlyList<ChromeChoice> Schemes { get; } =
    [
        new("parchment", "Parchment", "Warm gold on dark — the default heritage studio."),
        new("ink", "Ink", "Higher-contrast cream on near-black for reading."),
        new("dusk", "Dusk", "Cooler slate and copper if gold feels too warm."),
        new("paper", "Paper", "Light page — dark ink on cream for long archive reading."),
        new("forest", "Forest", "Deep green and gold for long, low-arousal sittings."),
    ];

    public static IReadOnlyList<ChromeChoice> ChromeModes { get; } =
    [
        new(ModeIconsAndLabels, "Icons and labels", "Dual coding. Recommended. Labels are always visible."),
        new(ModeIcons, "Icons only", "Thin rail. Names live in tooltips — experts only."),
        new(ModeText, "Text only", "No pictograms. For people who read first."),
    ];

    public static IReadOnlyList<ChromeChoice> DockEdges { get; } =
    [
        new("left", "Left", "Top-left landmark. Matches how most LTR readers start."),
        new("right", "Right", "Documents first; rail on the pointing-hand side."),
        new("top", "Top", "Ribbon-style. Same item order, horizontal."),
    ];

    public static void Apply(AppSettings settings)
    {
        SchemeId = NormalizeScheme(settings.ColorScheme);
        ChromeMode = NormalizeMode(settings.ChromeMode);
        DockEdge = NormalizeEdge(settings.DockEdge);
        DockSize = Math.Clamp(settings.DockSize <= 0 ? 188 : settings.DockSize, 56, 280);
        DockLocked = settings.DockLocked;
        InspectorOpen = settings.InspectorOpen;
        InspectorWidth = Math.Clamp(settings.InspectorWidth <= 0 ? 292 : settings.InspectorWidth, 220, 480);
        settings.InspectorOpen = InspectorOpen;
        settings.InspectorWidth = InspectorWidth;
        ShowIcons = ChromeMode != ModeText;
        ShowLabels = ChromeMode != ModeIcons;
        settings.ColorScheme = SchemeId;
        settings.ChromeMode = ChromeMode;
        settings.DockEdge = DockEdge;
        settings.DockSize = DockSize;
        EnsureChromeFolder();
        ImageCache.Clear();
        ApplyPalette(SchemeId);
        Changed?.Invoke();
    }

    public static Visibility IconVisibility => ShowIcons ? Visibility.Visible : Visibility.Collapsed;
    public static Visibility LabelVisibility => ShowLabels ? Visibility.Visible : Visibility.Collapsed;

    public static bool ShowDockLabels(double size) =>
        ChromeMode == ModeText || (ChromeMode == ModeIconsAndLabels && size >= 108);

    private static readonly Dictionary<string, BitmapImage?> ImageCache = new(StringComparer.OrdinalIgnoreCase);

    public static BitmapImage? TryGetButton(string assetId)
    {
        if (string.IsNullOrWhiteSpace(assetId))
        {
            return null;
        }

        if (ImageCache.TryGetValue(assetId, out var cached))
        {
            return cached;
        }

        BitmapImage? found = null;
        foreach (var ext in new[] { ".png", ".jpg", ".jpeg", ".webp" })
        {
            var path = Path.Combine(AppPaths.ChromeButtons, assetId + ext);
            if (!File.Exists(path))
            {
                continue;
            }

            try
            {
                found = new BitmapImage(new Uri(path, UriKind.Absolute));
            }
            catch
            {
                found = null;
            }

            break;
        }

        ImageCache[assetId] = found;
        return found;
    }

    public static void EnsureChromeFolder()
    {
        Directory.CreateDirectory(AppPaths.ChromeButtons);
        var readme = Path.Combine(AppPaths.ChromeButtons, "README.txt");
        if (File.Exists(readme))
        {
            return;
        }

        File.WriteAllText(readme, """
            Heirloom custom buttons
            =======================
            Drop square PNG files here (128×128 or 256×256, simple silhouettes).
            Names are the action or dock id:

              dock-twin.png
              dock-mixer.png
              dock-archive.png
              dock-settings.png
              action-new.png
              action-file.png
              action-mute.png
              action-refresh.png
              action-import.png

            Keep the shape simple. Detailed photos slow visual search.
            Restart or press Save in Settings after adding files.
            Labels still show unless Chrome is set to Icons only.
            """);
    }

    public static string NormalizeScheme(string? id) =>
        Schemes.Any(s => s.Id == id) ? id! : "parchment";

    public static string NormalizeMode(string? id) =>
        ChromeModes.Any(s => s.Id == id) ? id! : ModeIconsAndLabels;

    public static string NormalizeEdge(string? id) =>
        DockEdges.Any(s => s.Id == id) ? id! : "left";

    private static void ApplyPalette(string id)
    {
        if (Application.Current?.Resources is not { } res)
        {
            return;
        }

        var p = Palette(id);
        SetColor(res, "HeirloomBgBase", p.BgBase);
        SetColor(res, "HeirloomBgSurface", p.BgSurface);
        SetColor(res, "HeirloomBgElevated", p.BgElevated);
        SetColor(res, "HeirloomText", p.Text);
        SetColor(res, "HeirloomTextSecondary", p.TextSecondary);
        SetColor(res, "HeirloomTextMuted", p.TextMuted);
        SetColor(res, "HeirloomGold", p.Gold);
        SetColor(res, "HeirloomGoldHover", p.GoldHover);
        SetColor(res, "HeirloomGoldPressed", p.GoldPressed);
        SetColor(res, "HeirloomGoldDeep", p.GoldDeep);
        SetColor(res, "HeirloomDanger", p.Danger);
        SetColor(res, "HeirloomBorder", p.Border);
        SetColor(res, "HeirloomInk", p.Ink);
        SetColor(res, "HeirloomHighlight", p.Highlight);

        SetBrush(res, "HeirloomBgBaseBrush", p.BgBase);
        SetBrush(res, "HeirloomBgSurfaceBrush", p.BgSurface);
        SetBrush(res, "HeirloomBgElevatedBrush", p.BgElevated);
        SetBrush(res, "HeirloomTextBrush", p.Text);
        SetBrush(res, "HeirloomTextSecondaryBrush", p.TextSecondary);
        SetBrush(res, "HeirloomTextMutedBrush", p.TextMuted);
        SetBrush(res, "HeirloomGoldBrush", p.Gold);
        SetBrush(res, "HeirloomGoldHoverBrush", p.GoldHover);
        SetBrush(res, "HeirloomGoldPressedBrush", p.GoldPressed);
        SetBrush(res, "HeirloomGoldDeepBrush", p.GoldDeep);
        SetBrush(res, "HeirloomDangerBrush", p.Danger);
        SetBrush(res, "HeirloomBorderBrush", p.Border);
        SetBrush(res, "HeirloomInkBrush", p.Ink);
        SetBrush(res, "HeirloomGoldMutedBrush", WithAlpha(p.Gold, 0x26));
        SetBrush(res, "HeirloomGlassBrush", WithAlpha(p.BgSurface, 0xF2));
        SetBrush(res, "HeirloomChromeBrush", WithAlpha(p.BgSurface, 0xE8));
        SetBrush(res, "HeirloomDockBrush", WithAlpha(p.BgSurface, 0xF4));
        SetBrush(res, "HeirloomStatusBrush", WithAlpha(p.BgBase, 0xF0));
        SetBrush(res, "HeirloomMenuStripBrush", WithAlpha(p.BgSurface, 0xE8));
        SetBrush(res, "HeirloomOptionsStripBrush", WithAlpha(p.BgBase, 0xCC));
        SetBrush(res, "HeirloomDocTitleBrush", WithAlpha(p.BgElevated, 0xF0));
        SetBrush(res, "HeirloomScrimBrush", WithAlpha(p.BgBase, 0xB8));
        SetBrush(res, "HeirloomYouBubbleBrush", WithAlpha(p.Gold, 0x22));
        SetBrush(res, "HeirloomTwinBubbleBrush", WithAlpha(p.BgElevated, 0xE8));
        SetBrush(res, "HeirloomDangerFillBrush", WithAlpha(p.Danger, 0x28));
        SetBrush(res, "HeirloomDangerTextBrush", Lighten(p.Danger, 80));
        SetBrush(res, "HeirloomMeterTrackBrush", WithAlpha(p.Border, 0xCC));

        SetGoldFill(res, "StudioGoldFill", p.GoldHover, p.Gold, p.GoldPressed);
        SetGoldFill(res, "StudioGoldFillHover", Lighten(p.GoldHover, 18), p.GoldHover, p.Gold);
        SetGoldFill(res, "StudioGoldFillPressed", p.GoldPressed, p.GoldDeep, p.GoldDeep);
        ApplyControlChrome(res, p);
    }

    private static void ApplyControlChrome(ResourceDictionary res, PaletteSpec p)
    {
        res["SystemAccentColor"] = p.Gold;
        SetBrush(res, "SystemAccentColorLight2", Lighten(p.Gold, 24));
        SetBrush(res, "AccentFillColorDefaultBrush", p.Gold);
        SetBrush(res, "AccentFillColorSecondaryBrush", Lighten(p.Gold, 18));
        SetBrush(res, "AccentFillColorTertiaryBrush", p.GoldPressed);
        SetBrush(res, "AccentFillColorDisabledBrush", WithAlpha(p.Gold, 0x55));
        SetBrush(res, "ControlFillColorDefaultBrush", p.BgElevated);
        SetBrush(res, "ControlFillColorSecondaryBrush", p.BgSurface);
        SetBrush(res, "ControlFillColorTertiaryBrush", p.BgElevated);
        SetBrush(res, "ControlFillColorInputActiveBrush", p.BgElevated);
        SetBrush(res, "ControlStrokeColorDefaultBrush", p.Border);
        SetBrush(res, "ControlStrokeColorOnAccentDefaultBrush", p.GoldDeep);
        SetBrush(res, "ControlStrokeColorFocusedBrush", p.Gold);
        SetBrush(res, "FocusStrokeColorOuterBrush", p.Gold);
        SetBrush(res, "TextFillColorPrimaryBrush", p.Text);
        SetBrush(res, "TextFillColorSecondaryBrush", p.TextSecondary);
        SetBrush(res, "TextFillColorTertiaryBrush", p.TextMuted);
        SetBrush(res, "TextControlBackground", p.BgElevated);
        SetBrush(res, "TextControlBackgroundPointerOver", p.BgElevated);
        SetBrush(res, "TextControlBackgroundFocused", p.BgElevated);
        SetBrush(res, "TextControlForeground", p.Text);
        SetBrush(res, "TextControlForegroundPointerOver", p.Text);
        SetBrush(res, "TextControlForegroundFocused", p.Text);
        SetBrush(res, "TextControlBorderBrush", p.Border);
        SetBrush(res, "TextControlBorderBrushPointerOver", p.Gold);
        SetBrush(res, "TextControlBorderBrushFocused", p.Gold);
        SetBrush(res, "TextControlPlaceholderForeground", p.TextMuted);
        SetBrush(res, "TextControlPlaceholderForegroundPointerOver", p.TextMuted);
        SetBrush(res, "TextControlPlaceholderForegroundFocused", p.TextSecondary);
        SetBrush(res, "ComboBoxBackground", p.BgElevated);
        SetBrush(res, "ComboBoxBackgroundPointerOver", p.BgElevated);
        SetBrush(res, "ComboBoxBackgroundPressed", p.BgSurface);
        SetBrush(res, "ComboBoxBackgroundFocused", p.BgElevated);
        SetBrush(res, "ComboBoxBorderBrush", p.Border);
        SetBrush(res, "ComboBoxBorderBrushPointerOver", p.Gold);
        SetBrush(res, "ComboBoxBorderBrushFocused", p.Gold);
        SetBrush(res, "ComboBoxForeground", p.Text);
        SetBrush(res, "ComboBoxPlaceHolderForeground", p.TextMuted);
        SetBrush(res, "ComboBoxDropDownBackground", p.BgSurface);
        SetBrush(res, "ComboBoxDropDownBorderBrush", p.Border);
        SetBrush(res, "ProgressBarForeground", p.Gold);
        SetBrush(res, "ProgressBarBackground", p.Border);
        SetBrush(res, "SliderTrackFill", p.Border);
        SetBrush(res, "SliderTrackValueFill", p.Gold);
        SetBrush(res, "SliderThumbBackground", p.Gold);
        SetBrush(res, "ToggleSwitchFillOn", p.Gold);
        SetBrush(res, "ToggleSwitchFillOnPointerOver", Lighten(p.Gold, 18));
        SetBrush(res, "ToggleSwitchFillOnPressed", p.GoldPressed);
        SetBrush(res, "ToggleSwitchKnobFillOn", p.Ink);
        SetBrush(res, "ToggleSwitchFillOff", p.BgElevated);
        SetBrush(res, "ToggleSwitchStrokeOff", p.Border);
        SetBrush(res, "ToggleSwitchStrokeOn", p.GoldDeep);
        SetBrush(res, "MenuBarItemBackgroundSelected", WithAlpha(p.Gold, 0x22));
        SetBrush(res, "MenuBarItemBackgroundPointerOver", WithAlpha(p.Gold, 0x18));
        SetBrush(res, "MenuFlyoutPresenterBackground", p.BgSurface);
        SetBrush(res, "MenuFlyoutPresenterBorderBrush", p.Border);
        SetBrush(res, "MenuFlyoutItemBackgroundPointerOver", WithAlpha(p.Gold, 0x22));
        SetBrush(res, "MenuFlyoutItemForeground", p.Text);
        SetBrush(res, "ScrollBarThumbFill", WithAlpha(p.Gold, 0x66));
        SetBrush(res, "ScrollBarThumbFillPointerOver", p.Gold);
        SetBrush(res, "ScrollBarTrackFill", WithAlpha(p.BgBase, 0x66));
    }

    private static PaletteSpec Palette(string id) => id switch
    {
        "ink" => new(
            Hex(0xFF0A0A0B), Hex(0xFF141416), Hex(0xFF1E1E22),
            Hex(0xFFF7F4EE), Hex(0xFFB8B3A8), Hex(0xFF8A857C),
            Hex(0xFFE0B07A), Hex(0xFFF0C792), Hex(0xFFC89655), Hex(0xFF8A6238),
            Hex(0xFFC45C5C), Hex(0xFF3A3836), Hex(0xFF0A0A0B), Hex(0x33FFFFFF)),
        "dusk" => new(
            Hex(0xFF10141A), Hex(0xFF171D26), Hex(0xFF202834),
            Hex(0xFFE8EEF6), Hex(0xFF9AA8B8), Hex(0xFF6E7C8C),
            Hex(0xFFC9A27A), Hex(0xFFDDB592), Hex(0xFFB0865C), Hex(0xFF7A5A3A),
            Hex(0xFFB85A5A), Hex(0xFF2C3644), Hex(0xFF10141A), Hex(0x33FFFFFF)),
        "paper" => new(
            Hex(0xFFF4EFE6), Hex(0xFFEBE4D6), Hex(0xFFE0D6C4),
            Hex(0xFF1C1916), Hex(0xFF5C564E), Hex(0xFF7A736B),
            Hex(0xFF8A5A2A), Hex(0xFFA46C34), Hex(0xFF704820), Hex(0xFF5A3A18),
            Hex(0xFFA33A3A), Hex(0xFFC9BFAE), Hex(0xFFF4EFE6), Hex(0x22000000)),
        "forest" => new(
            Hex(0xFF0E1410), Hex(0xFF161E18), Hex(0xFF1E2820),
            Hex(0xFFE8F0E6), Hex(0xFFA8B8A6), Hex(0xFF7A8A78),
            Hex(0xFFC4A36A), Hex(0xFFD8B882), Hex(0xFFA88848), Hex(0xFF6E5A28),
            Hex(0xFFB85A4A), Hex(0xFF2A362C), Hex(0xFF0E1410), Hex(0x33FFFFFF)),
        _ => new(
            Hex(0xFF121110), Hex(0xFF1C1A18), Hex(0xFF262320),
            Hex(0xFFF2EFE9), Hex(0xFFA8A096), Hex(0xFF7A736B),
            Hex(0xFFD4A373), Hex(0xFFE5B98E), Hex(0xFFC08D5C), Hex(0xFF8A6238),
            Hex(0xFFA64D4D), Hex(0xFF36322E), Hex(0xFF121110), Hex(0x33FFFFFF)),
    };

    private static void SetColor(ResourceDictionary res, string key, Color color) => res[key] = color;

    private static void SetBrush(ResourceDictionary res, string key, Color color)
    {
        if (res.TryGetValue(key, out var existing) && existing is SolidColorBrush brush)
        {
            brush.Color = color;
            return;
        }

        res[key] = new SolidColorBrush(color);
    }

    private static void SetGoldFill(ResourceDictionary res, string key, Color top, Color mid, Color bottom)
    {
        if (res.TryGetValue(key, out var existing) && existing is LinearGradientBrush fill && fill.GradientStops.Count >= 2)
        {
            fill.GradientStops[0].Color = top;
            if (fill.GradientStops.Count > 1)
            {
                fill.GradientStops[1].Color = mid;
            }

            if (fill.GradientStops.Count > 2)
            {
                fill.GradientStops[^1].Color = bottom;
            }

            return;
        }

        res[key] = new LinearGradientBrush
        {
            StartPoint = new Windows.Foundation.Point(0, 0),
            EndPoint = new Windows.Foundation.Point(0, 1),
            GradientStops =
            {
                new GradientStop { Offset = 0, Color = top },
                new GradientStop { Offset = 0.45, Color = mid },
                new GradientStop { Offset = 1, Color = bottom },
            },
        };
    }

    private static Color Hex(uint argb) =>
        Color.FromArgb((byte)(argb >> 24), (byte)(argb >> 16), (byte)(argb >> 8), (byte)argb);

    private static Color WithAlpha(Color color, byte alpha) =>
        Color.FromArgb(alpha, color.R, color.G, color.B);

    private static Color Lighten(Color color, int amount)
    {
        static byte Lift(byte channel, int delta) => (byte)Math.Clamp(channel + delta, 0, 255);
        return Color.FromArgb(color.A, Lift(color.R, amount), Lift(color.G, amount), Lift(color.B, amount));
    }

    private readonly record struct PaletteSpec(
        Color BgBase,
        Color BgSurface,
        Color BgElevated,
        Color Text,
        Color TextSecondary,
        Color TextMuted,
        Color Gold,
        Color GoldHover,
        Color GoldPressed,
        Color GoldDeep,
        Color Danger,
        Color Border,
        Color Ink,
        Color Highlight);
}
