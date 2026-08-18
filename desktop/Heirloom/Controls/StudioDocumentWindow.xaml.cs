using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;
using Microsoft.UI.Xaml.Markup;
using Windows.Foundation;

namespace Heirloom.Controls;

[ContentProperty(Name = nameof(Body))]
public sealed partial class StudioDocumentWindow : UserControl
{
    private bool _dragging;
    private bool _resizing;
    private Point _pointerStart;
    private double _startLeft;
    private double _startTop;
    private double _startWidth;
    private double _startHeight;
    private double _restoreLeft;
    private double _restoreTop;
    private double _restoreWidth = 820;
    private double _restoreHeight = 560;

    public event RoutedEventHandler? CloseRequested;
    public event RoutedEventHandler? Activated;

    public StudioDocumentWindow()
    {
        InitializeComponent();
        Loaded += (_, _) =>
        {
            if (double.IsNaN(Width) || Width <= 0)
            {
                Width = 840;
            }

            if (double.IsNaN(Height) || Height <= 0)
            {
                Height = 560;
            }

            ApplySlots();
        };
    }

    public string DocumentId
    {
        get => (string)GetValue(DocumentIdProperty);
        set => SetValue(DocumentIdProperty, value);
    }

    public static readonly DependencyProperty DocumentIdProperty =
        DependencyProperty.Register(nameof(DocumentId), typeof(string), typeof(StudioDocumentWindow), new PropertyMetadata(""));

    public string TitleText
    {
        get => (string)GetValue(TitleTextProperty);
        set => SetValue(TitleTextProperty, value);
    }

    public static readonly DependencyProperty TitleTextProperty =
        DependencyProperty.Register(nameof(TitleText), typeof(string), typeof(StudioDocumentWindow), new PropertyMetadata("Document"));

    public string SubtitleText
    {
        get => (string)GetValue(SubtitleTextProperty);
        set => SetValue(SubtitleTextProperty, value);
    }

    public static readonly DependencyProperty SubtitleTextProperty =
        DependencyProperty.Register(nameof(SubtitleText), typeof(string), typeof(StudioDocumentWindow), new PropertyMetadata(""));

    public string StatusText
    {
        get => (string)GetValue(StatusTextProperty);
        set => SetValue(StatusTextProperty, value);
    }

    public static readonly DependencyProperty StatusTextProperty =
        DependencyProperty.Register(nameof(StatusText), typeof(string), typeof(StudioDocumentWindow), new PropertyMetadata(""));

    public UIElement? MenuBarContent
    {
        get => (UIElement?)GetValue(MenuBarContentProperty);
        set => SetValue(MenuBarContentProperty, value);
    }

    public static readonly DependencyProperty MenuBarContentProperty =
        DependencyProperty.Register(nameof(MenuBarContent), typeof(UIElement), typeof(StudioDocumentWindow), new PropertyMetadata(null, OnSlotChanged));

    public UIElement? OptionsContent
    {
        get => (UIElement?)GetValue(OptionsContentProperty);
        set => SetValue(OptionsContentProperty, value);
    }

    public static readonly DependencyProperty OptionsContentProperty =
        DependencyProperty.Register(nameof(OptionsContent), typeof(UIElement), typeof(StudioDocumentWindow), new PropertyMetadata(null, OnSlotChanged));

    public UIElement? Body
    {
        get => (UIElement?)GetValue(BodyProperty);
        set => SetValue(BodyProperty, value);
    }

    public static readonly DependencyProperty BodyProperty =
        DependencyProperty.Register(nameof(Body), typeof(UIElement), typeof(StudioDocumentWindow), new PropertyMetadata(null));

    public bool IsMaximized { get; private set; }

    public void BringToFront(int z)
    {
        Canvas.SetZIndex(this, z);
        Activated?.Invoke(this, new RoutedEventArgs());
    }

    private static void OnSlotChanged(DependencyObject d, DependencyPropertyChangedEventArgs e)
    {
        if (d is StudioDocumentWindow window)
        {
            window.ApplySlots();
        }
    }

    private void ApplySlots()
    {
        if (MenuHost is not null)
        {
            MenuHost.Visibility = MenuBarContent is null ? Visibility.Collapsed : Visibility.Visible;
        }

        if (OptionsHost is not null)
        {
            OptionsHost.Visibility = OptionsContent is null ? Visibility.Collapsed : Visibility.Visible;
        }
    }

    private void OnChromePressed(object sender, PointerRoutedEventArgs e)
    {
        Activated?.Invoke(this, new RoutedEventArgs());
        if (Height <= 40)
        {
            RestoreFromMin();
            return;
        }

        CapturePointer(e.Pointer);
        _dragging = true;
        _pointerStart = e.GetCurrentPoint(null).Position;
        _startLeft = Canvas.GetLeft(this);
        _startTop = Canvas.GetTop(this);
        if (double.IsNaN(_startLeft))
        {
            _startLeft = 0;
        }

        if (double.IsNaN(_startTop))
        {
            _startTop = 0;
        }
    }

    private void OnPointerMoved(object sender, PointerRoutedEventArgs e)
    {
        var pos = e.GetCurrentPoint(null).Position;
        if (_dragging && !IsMaximized)
        {
            Canvas.SetLeft(this, Math.Max(0, _startLeft + pos.X - _pointerStart.X));
            Canvas.SetTop(this, Math.Max(0, _startTop + pos.Y - _pointerStart.Y));
        }
        else if (_resizing && !IsMaximized)
        {
            Width = Math.Max(480, _startWidth + pos.X - _pointerStart.X);
            Height = Math.Max(320, _startHeight + pos.Y - _pointerStart.Y);
        }
    }

    private void OnPointerReleased(object sender, PointerRoutedEventArgs e)
    {
        _dragging = false;
        _resizing = false;
        try
        {
            ReleasePointerCapture(e.Pointer);
        }
        catch
        {
            // already released
        }
    }

    private void OnResizePressed(object sender, PointerRoutedEventArgs e)
    {
        e.Handled = true;
        CapturePointer(e.Pointer);
        _resizing = true;
        _pointerStart = e.GetCurrentPoint(null).Position;
        _startWidth = ActualWidth;
        _startHeight = ActualHeight;
    }

    private void OnClose(object sender, RoutedEventArgs e) => CloseRequested?.Invoke(this, e);

    private void OnMin(object sender, RoutedEventArgs e)
    {
        if (ActualHeight > 40)
        {
            _restoreHeight = ActualHeight;
            _restoreWidth = ActualWidth;
        }

        Height = 38;
        BodyHost.Visibility = Visibility.Collapsed;
        MenuHost.Visibility = Visibility.Collapsed;
        OptionsHost.Visibility = Visibility.Collapsed;
    }

    private void OnMax(object sender, RoutedEventArgs e)
    {
        if (Parent is not Canvas canvas)
        {
            return;
        }

        if (!IsMaximized)
        {
            _restoreLeft = Canvas.GetLeft(this);
            _restoreTop = Canvas.GetTop(this);
            _restoreWidth = ActualWidth;
            _restoreHeight = ActualHeight;
            Canvas.SetLeft(this, 0);
            Canvas.SetTop(this, 0);
            Width = Math.Max(480, canvas.ActualWidth);
            Height = Math.Max(320, canvas.ActualHeight);
            IsMaximized = true;
            BodyHost.Visibility = Visibility.Visible;
            MenuHost.Visibility = Visibility.Visible;
        }
        else
        {
            Canvas.SetLeft(this, _restoreLeft);
            Canvas.SetTop(this, _restoreTop);
            Width = _restoreWidth;
            Height = _restoreHeight;
            IsMaximized = false;
        }
    }

    public void RestoreFromMin()
    {
        if (Height <= 40)
        {
            Height = _restoreHeight > 40 ? _restoreHeight : 560;
        }

        BodyHost.Visibility = Visibility.Visible;
        MenuHost.Visibility = Visibility.Visible;
        OptionsHost.Visibility = OptionsContent is null ? Visibility.Collapsed : Visibility.Visible;
    }
}
