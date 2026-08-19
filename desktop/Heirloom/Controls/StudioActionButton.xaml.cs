using System.Windows.Input;
using Heirloom.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace Heirloom.Controls;

public sealed partial class StudioActionButton : UserControl
{
    public event RoutedEventHandler? Click;

    public StudioActionButton()
    {
        InitializeComponent();
        Loaded += (_, _) =>
        {
            ThemeService.Changed += OnThemeChanged;
            Apply();
        };
        Unloaded += (_, _) => ThemeService.Changed -= OnThemeChanged;
    }

    public string Label
    {
        get => (string)GetValue(LabelProperty);
        set => SetValue(LabelProperty, value);
    }

    public static readonly DependencyProperty LabelProperty =
        DependencyProperty.Register(nameof(Label), typeof(string), typeof(StudioActionButton), new PropertyMetadata("", OnVisual));

    public string Glyph
    {
        get => (string)GetValue(GlyphProperty);
        set => SetValue(GlyphProperty, value);
    }

    public static readonly DependencyProperty GlyphProperty =
        DependencyProperty.Register(nameof(Glyph), typeof(string), typeof(StudioActionButton), new PropertyMetadata("", OnVisual));

    public string AssetId
    {
        get => (string)GetValue(AssetIdProperty);
        set => SetValue(AssetIdProperty, value);
    }

    public static readonly DependencyProperty AssetIdProperty =
        DependencyProperty.Register(nameof(AssetId), typeof(string), typeof(StudioActionButton), new PropertyMetadata("", OnVisual));

    public string Kind
    {
        get => (string)GetValue(KindProperty);
        set => SetValue(KindProperty, value);
    }

    public static readonly DependencyProperty KindProperty =
        DependencyProperty.Register(nameof(Kind), typeof(string), typeof(StudioActionButton), new PropertyMetadata("Secondary", OnVisual));

    public ICommand? Command
    {
        get => (ICommand?)GetValue(CommandProperty);
        set => SetValue(CommandProperty, value);
    }

    public static readonly DependencyProperty CommandProperty =
        DependencyProperty.Register(nameof(Command), typeof(ICommand), typeof(StudioActionButton), new PropertyMetadata(null, OnVisual));

    public object? CommandParameter
    {
        get => GetValue(CommandParameterProperty);
        set => SetValue(CommandParameterProperty, value);
    }

    public static readonly DependencyProperty CommandParameterProperty =
        DependencyProperty.Register(nameof(CommandParameter), typeof(object), typeof(StudioActionButton), new PropertyMetadata(null, OnVisual));

    private static void OnVisual(DependencyObject d, DependencyPropertyChangedEventArgs e)
    {
        if (d is StudioActionButton button)
        {
            button.Apply();
        }
    }

    private void OnThemeChanged() => DispatcherQueue.TryEnqueue(Apply);

    private void Apply()
    {
        if (Inner is null)
        {
            return;
        }

        Caption.Text = Label;
        GlyphIcon.Glyph = Glyph ?? "";
        Inner.Command = Command;
        Inner.CommandParameter = CommandParameter;
        Inner.Style = Kind switch
        {
            "Primary" => (Style)Application.Current.Resources["StudioButtonPrimary"],
            "Danger" => (Style)Application.Current.Resources["StudioButtonDanger"],
            "Quiet" => (Style)Application.Current.Resources["StudioButtonQuiet"],
            _ => (Style)Application.Current.Resources["StudioButtonSecondary"],
        };

        var custom = ThemeService.TryGetButton(AssetId);
        if (custom is not null && ThemeService.ShowIcons)
        {
            CustomImage.Source = custom;
            CustomImage.Visibility = Visibility.Visible;
            GlyphIcon.Visibility = Visibility.Collapsed;
        }
        else
        {
            CustomImage.Visibility = Visibility.Collapsed;
            GlyphIcon.Visibility = string.IsNullOrEmpty(Glyph) || !ThemeService.ShowIcons
                ? Visibility.Collapsed
                : Visibility.Visible;
        }

        Caption.Visibility = ThemeService.ShowLabels && !string.IsNullOrWhiteSpace(Label)
            ? Visibility.Visible
            : Visibility.Collapsed;
        ToolTipService.SetToolTip(Inner, Label);
        GlyphIcon.Foreground = Kind == "Primary"
            ? (Microsoft.UI.Xaml.Media.Brush)Application.Current.Resources["HeirloomInkBrush"]
            : (Microsoft.UI.Xaml.Media.Brush)Application.Current.Resources["HeirloomGoldBrush"];
        PointerEntered -= OnHelpEnter;
        PointerExited -= OnHelpLeave;
        PointerEntered += OnHelpEnter;
        PointerExited += OnHelpLeave;
    }

    private string HelpKey =>
        !string.IsNullOrWhiteSpace(AssetId) ? AssetId
        : !string.IsNullOrWhiteSpace(Label) ? Label
        : Tag as string ?? "";

    private void OnHelpEnter(object sender, Microsoft.UI.Xaml.Input.PointerRoutedEventArgs e) =>
        StudioHelp.Hover(HelpKey);

    private void OnHelpLeave(object sender, Microsoft.UI.Xaml.Input.PointerRoutedEventArgs e) =>
        StudioHelp.Leave(HelpKey);

    private void OnInnerClick(object sender, RoutedEventArgs e) => Click?.Invoke(this, e);
}
