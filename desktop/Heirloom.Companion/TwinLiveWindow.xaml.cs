using System.ComponentModel;
using System.Windows;
using System.Windows.Media;
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
        Status.Foreground = listening
            ? new SolidColorBrush(Color.FromRgb(30, 110, 60))
            : new SolidColorBrush(Color.FromRgb(140, 90, 20));
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
}
