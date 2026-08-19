using Microsoft.UI.Xaml;

namespace Heirloom.Services;

public static class StudioHelp
{
    public static event Action? Changed;

    private static DispatcherTimer? _hold;
    private static string? _pending;
    private static string? _hover;
    private static string? _pinned;
    private static string? _document;

    public static HelpTopic Current => StudioLexicon.Resolve(ActiveId);
    public static string ModeLabel =>
        !string.IsNullOrEmpty(_hover) ? "Hovering"
        : !string.IsNullOrEmpty(_pinned) ? "Pinned"
        : "Resting";
    public static bool IsPinned => !string.IsNullOrEmpty(_pinned) && _pinned == ActiveId;

    private static string ActiveId =>
        _hover ?? _pinned ?? _document ?? "inspector";

    public static void Hover(string? id)
    {
        _pending = string.IsNullOrWhiteSpace(id) ? null : id.Trim();
        var hold = Timer();
        hold.Stop();
        hold.Start();
    }

    public static void Leave(string? id)
    {
        if (!string.IsNullOrEmpty(id) && string.Equals(_pending, id, StringComparison.OrdinalIgnoreCase))
        {
            _pending = null;
        }

        if (!string.IsNullOrEmpty(id) && string.Equals(_hover, id, StringComparison.OrdinalIgnoreCase))
        {
            _hold?.Stop();
            _hover = null;
            Changed?.Invoke();
        }
    }

    public static void Pin(string? id)
    {
        _pinned = string.IsNullOrWhiteSpace(id) ? null : id.Trim();
        Changed?.Invoke();
    }

    public static void TogglePin()
    {
        if (IsPinned)
        {
            _pinned = null;
        }
        else
        {
            _pinned = ActiveId;
        }

        Changed?.Invoke();
    }

    public static void SetDocument(string? id)
    {
        _document = string.IsNullOrWhiteSpace(id) ? null : id.Trim();
        if (_hover is null && _pinned is null)
        {
            Changed?.Invoke();
        }
    }

    public static void ShowTopic(string id)
    {
        Pin(id);
        Hover(null);
        _pending = null;
        _hover = null;
        Changed?.Invoke();
    }

    private static DispatcherTimer Timer()
    {
        if (_hold is not null)
        {
            return _hold;
        }

        _hold = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(120) };
        _hold.Tick += (_, _) =>
        {
            _hold.Stop();
            _hover = _pending;
            Changed?.Invoke();
        };
        return _hold;
    }
}

public static class StudioHint
{
    public static readonly DependencyProperty TopicProperty =
        DependencyProperty.RegisterAttached(
            "Topic",
            typeof(string),
            typeof(StudioHint),
            new PropertyMetadata(null, OnTopic));

    public static void SetTopic(DependencyObject element, string? value) =>
        element.SetValue(TopicProperty, value);

    public static string? GetTopic(DependencyObject element) =>
        (string?)element.GetValue(TopicProperty);

    private static void OnTopic(DependencyObject d, DependencyPropertyChangedEventArgs e)
    {
        if (d is not FrameworkElement el)
        {
            return;
        }

        el.PointerEntered -= OnEntered;
        el.PointerExited -= OnExited;
        if (e.NewValue is string and { Length: > 0 })
        {
            el.PointerEntered += OnEntered;
            el.PointerExited += OnExited;
        }
    }

    private static void OnEntered(object sender, Microsoft.UI.Xaml.Input.PointerRoutedEventArgs e)
    {
        if (sender is DependencyObject d)
        {
            StudioHelp.Hover(GetTopic(d));
        }
    }

    private static void OnExited(object sender, Microsoft.UI.Xaml.Input.PointerRoutedEventArgs e)
    {
        if (sender is DependencyObject d)
        {
            StudioHelp.Leave(GetTopic(d));
        }
    }
}
