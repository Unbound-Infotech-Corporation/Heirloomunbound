using System.ComponentModel;
using System.Windows;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Animation;
using Heirloom.BoxCore;

namespace Heirloom.Companion;

/// <summary>
/// Compact transcript for the Companion. The Heirloom studio stays closed.
/// </summary>
public partial class TwinLiveWindow : Window
{
    private readonly CompanionStore _store;
    private TwinLiveFrame _frame = TwinLiveFrame.Empty;
    private string _pendingId = "";
    private bool _allowClose;
    private bool _pulsing;

    public TwinLiveWindow(CompanionStore store)
    {
        _store = store;
        InitializeComponent();
        OnTop.Checked -= OnTopChanged;
        OnTop.Unchecked -= OnTopChanged;
        OnTop.IsChecked = store.LiveOnTop;
        Topmost = store.LiveOnTop;
        OnTop.Checked += OnTopChanged;
        OnTop.Unchecked += OnTopChanged;
        PaintStatus();
    }

    public event Action<string>? ConfirmRequested;

    public event Action<string>? DeclineRequested;

    public event Action<string>? TypedRequested;

    public void Reveal()
    {
        if (!IsVisible)
        {
            Show();
        }

        Activate();
    }

    public void Apply(AssistLiveView view, MicTranscript? mic)
    {
        var listening = mic?.Listening ?? view.Listening;
        _frame = TwinLiveBoard.Next(
            _frame,
            listening,
            mic?.Lines,
            view.Caption,
            view.CaptionId,
            view.PendingId);
        _pendingId = view.PendingId;
        Lines.ItemsSource = null;
        Lines.ItemsSource = _frame.Lines;
        Receipts.ItemsSource = view.Receipts;
        PendingLabel.Text = string.IsNullOrWhiteSpace(view.PendingLabel)
            ? "Say yes before this runs."
            : view.PendingLabel;
        var showPending = view.PendingId.Length > 0;
        PendingBox.Visibility = showPending ? Visibility.Visible : Visibility.Collapsed;
        Yes.IsEnabled = _frame.CanAnswer;
        No.IsEnabled = _frame.CanAnswer;
        PaintStatus();
        TranscriptScroll.ScrollToEnd();
    }

    public void Shutdown()
    {
        _allowClose = true;
        Close();
    }

    protected override void OnClosing(CancelEventArgs e)
    {
        if (!_allowClose)
        {
            e.Cancel = true;
            Hide();
            return;
        }

        base.OnClosing(e);
    }

    private void PaintStatus()
    {
        var listening = _frame.Status == "Listening";
        Status.Text = listening ? "Listening" : "Paused";
        var gold = Color.FromRgb(0xD4, 0xA3, 0x73);
        Status.Foreground = new SolidColorBrush(listening ? gold : Color.FromRgb(0xA8, 0xA0, 0x96));
        StatusDot.Fill = new SolidColorBrush(listening ? gold : Color.FromRgb(0x7A, 0x73, 0x6B));
        StatusPill.BorderBrush = new SolidColorBrush(listening ? Color.FromArgb(0x88, 0xD4, 0xA3, 0x73) : Color.FromRgb(0x36, 0x32, 0x2E));
        StatusPill.Background = new SolidColorBrush(listening ? Color.FromArgb(0x26, 0xD4, 0xA3, 0x73) : Color.FromArgb(0x14, 0xFF, 0xFF, 0xFF));
        if (listening == _pulsing)
        {
            return;
        }

        _pulsing = listening;
        if (listening)
        {
            // A slow breath while the mic is open.
            StatusDot.BeginAnimation(OpacityProperty, new DoubleAnimation(1.0, 0.3, TimeSpan.FromSeconds(0.9))
            {
                AutoReverse = true,
                RepeatBehavior = RepeatBehavior.Forever,
                EasingFunction = new SineEase { EasingMode = EasingMode.EaseInOut },
            });
        }
        else
        {
            StatusDot.BeginAnimation(OpacityProperty, null);
            StatusDot.Opacity = 1.0;
        }
    }

    private void OnTopChanged(object sender, RoutedEventArgs e)
    {
        var on = OnTop.IsChecked == true;
        Topmost = on;
        _store.LiveOnTop = on;
    }

    private void OnYes(object sender, RoutedEventArgs e)
    {
        if (_pendingId.Length > 0 && _frame.CanAnswer)
        {
            ConfirmRequested?.Invoke(_pendingId);
        }
    }

    private void OnNo(object sender, RoutedEventArgs e)
    {
        if (_pendingId.Length > 0 && _frame.CanAnswer)
        {
            DeclineRequested?.Invoke(_pendingId);
        }
    }

    private void OnDraftKey(object sender, KeyEventArgs e)
    {
        if (!TwinLiveBoard.EnterSends(e.Key == Key.Enter, Keyboard.Modifiers.HasFlag(ModifierKeys.Shift)))
        {
            return;
        }

        e.Handled = true;
        SubmitDraft();
    }

    private void OnSend(object sender, RoutedEventArgs e) => SubmitDraft();

    private void SubmitDraft()
    {
        var text = (Draft.Text ?? "").Trim();
        if (text.Length == 0)
        {
            return;
        }

        Draft.Text = "";
        _frame = TwinLiveBoard.AppendTyped(_frame, text);
        Lines.ItemsSource = null;
        Lines.ItemsSource = _frame.Lines;
        TranscriptScroll.ScrollToEnd();
        TypedRequested?.Invoke(text);
    }
}
