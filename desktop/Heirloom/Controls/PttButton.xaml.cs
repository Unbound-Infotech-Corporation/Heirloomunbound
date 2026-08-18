using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;

namespace Heirloom.Controls;

public sealed partial class PttButton : UserControl
{
    public event RoutedEventHandler? Pressed;
    public event RoutedEventHandler? Released;
    public event RoutedEventHandler? Clicked;

    public PttButton()
    {
        InitializeComponent();
    }

    public bool IsArmed
    {
        get => (bool)GetValue(IsArmedProperty);
        set => SetValue(IsArmedProperty, value);
    }

    public static readonly DependencyProperty IsArmedProperty =
        DependencyProperty.Register(nameof(IsArmed), typeof(bool), typeof(PttButton), new PropertyMetadata(false, OnArmed));

    private static void OnArmed(DependencyObject d, DependencyPropertyChangedEventArgs e)
    {
        if (d is PttButton btn)
        {
            btn.Label.Text = (bool)e.NewValue ? "Listening" : "Hold";
            btn.Halo.Opacity = (bool)e.NewValue ? 0.9 : 0.55;
        }
    }

    private void OnPressed(object sender, PointerRoutedEventArgs e)
    {
        IsArmed = true;
        Pressed?.Invoke(this, new RoutedEventArgs());
    }

    private void OnReleased(object sender, PointerRoutedEventArgs e)
    {
        IsArmed = false;
        Released?.Invoke(this, new RoutedEventArgs());
    }

    private void OnClick(object sender, RoutedEventArgs e) => Clicked?.Invoke(this, e);
}
