using System.Windows.Input;
using Heirloom.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Automation;
using Microsoft.UI.Xaml.Controls;

namespace Heirloom.Controls;

/// <summary>
/// 40px letter/glyph well. The mark is the verb (M = Mute), like a DAW track header.
/// Gold fill means armed — color is state, not mood. Inspector still names it.
/// </summary>
public sealed partial class StudioMark : UserControl
{
    public event RoutedEventHandler? Click;

    public StudioMark()
    {
        InitializeComponent();
        Loaded += (_, _) =>
        {
            ThemeService.Changed += OnThemeChanged;
            Apply();
        };
        Unloaded += (_, _) => ThemeService.Changed -= OnThemeChanged;
    }

    public string Mark
    {
        get => (string)GetValue(MarkProperty);
        set => SetValue(MarkProperty, value);
    }

    public static readonly DependencyProperty MarkProperty =
        DependencyProperty.Register(nameof(Mark), typeof(string), typeof(StudioMark), new PropertyMetadata("", OnVisual));

    public string Label
    {
        get => (string)GetValue(LabelProperty);
        set => SetValue(LabelProperty, value);
    }

    public static readonly DependencyProperty LabelProperty =
        DependencyProperty.Register(nameof(Label), typeof(string), typeof(StudioMark), new PropertyMetadata("", OnVisual));

    public string Glyph
    {
        get => (string)GetValue(GlyphProperty);
        set => SetValue(GlyphProperty, value);
    }

    public static readonly DependencyProperty GlyphProperty =
        DependencyProperty.Register(nameof(Glyph), typeof(string), typeof(StudioMark), new PropertyMetadata("", OnVisual));

    public string AssetId
    {
        get => (string)GetValue(AssetIdProperty);
        set => SetValue(AssetIdProperty, value);
    }

    public static readonly DependencyProperty AssetIdProperty =
        DependencyProperty.Register(nameof(AssetId), typeof(string), typeof(StudioMark), new PropertyMetadata("", OnVisual));

    public bool IsArmed
    {
        get => (bool)GetValue(IsArmedProperty);
        set => SetValue(IsArmedProperty, value);
    }

    public static readonly DependencyProperty IsArmedProperty =
        DependencyProperty.Register(nameof(IsArmed), typeof(bool), typeof(StudioMark), new PropertyMetadata(false, OnVisual));

    public ICommand? Command
    {
        get => (ICommand?)GetValue(CommandProperty);
        set => SetValue(CommandProperty, value);
    }

    public static readonly DependencyProperty CommandProperty =
        DependencyProperty.Register(nameof(Command), typeof(ICommand), typeof(StudioMark), new PropertyMetadata(null, OnVisual));

    private static void OnVisual(DependencyObject d, DependencyPropertyChangedEventArgs e)
    {
        if (d is StudioMark mark)
        {
            mark.Apply();
        }
    }

    private void OnThemeChanged() => DispatcherQueue.TryEnqueue(Apply);

    private void Apply()
    {
        if (Inner is null)
        {
            return;
        }

        var name = string.IsNullOrWhiteSpace(Label) ? Mark : Label;
        AutomationProperties.SetName(Inner, name);
        ToolTipService.SetToolTip(Inner, name);
        Inner.Command = Command;
        Inner.Style = IsArmed
            ? (Style)Application.Current.Resources["StudioButtonPrimary"]
            : (Style)Application.Current.Resources["StudioButtonSecondary"];

        var custom = ThemeService.TryGetButton(AssetId);
        var showIcons = ThemeService.ShowIcons;
        if (custom is not null && showIcons)
        {
            CustomImage.Source = custom;
            CustomImage.Visibility = Visibility.Visible;
            GlyphIcon.Visibility = Visibility.Collapsed;
            Letter.Visibility = Visibility.Collapsed;
        }
        else if (!string.IsNullOrEmpty(Glyph) && showIcons && string.IsNullOrWhiteSpace(Mark))
        {
            CustomImage.Visibility = Visibility.Collapsed;
            GlyphIcon.Glyph = Glyph;
            GlyphIcon.Visibility = Visibility.Visible;
            GlyphIcon.Foreground = IsArmed
                ? (Microsoft.UI.Xaml.Media.Brush)Application.Current.Resources["HeirloomInkBrush"]
                : (Microsoft.UI.Xaml.Media.Brush)Application.Current.Resources["HeirloomGoldBrush"];
            Letter.Visibility = Visibility.Collapsed;
        }
        else
        {
            CustomImage.Visibility = Visibility.Collapsed;
            GlyphIcon.Visibility = Visibility.Collapsed;
            Letter.Text = string.IsNullOrWhiteSpace(Mark) ? "?" : Mark;
            Letter.Visibility = Visibility.Visible;
            Letter.Foreground = IsArmed
                ? (Microsoft.UI.Xaml.Media.Brush)Application.Current.Resources["HeirloomInkBrush"]
                : (Microsoft.UI.Xaml.Media.Brush)Application.Current.Resources["HeirloomGoldBrush"];
        }

        PointerEntered -= OnHelpEnter;
        PointerExited -= OnHelpLeave;
        PointerEntered += OnHelpEnter;
        PointerExited += OnHelpLeave;
    }

    private string HelpKey =>
        !string.IsNullOrWhiteSpace(AssetId) ? AssetId
        : !string.IsNullOrWhiteSpace(Label) ? Label
        : Mark;

    private void OnHelpEnter(object sender, Microsoft.UI.Xaml.Input.PointerRoutedEventArgs e) =>
        StudioHelp.Hover(HelpKey);

    private void OnHelpLeave(object sender, Microsoft.UI.Xaml.Input.PointerRoutedEventArgs e) =>
        StudioHelp.Leave(HelpKey);

    private void OnInnerClick(object sender, RoutedEventArgs e) => Click?.Invoke(this, e);
}
