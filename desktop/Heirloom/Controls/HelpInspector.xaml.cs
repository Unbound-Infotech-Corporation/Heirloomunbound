using Heirloom.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace Heirloom.Controls;

public sealed partial class HelpInspector : UserControl
{
    public event EventHandler? GlossaryRequested;
    public event EventHandler? HideRequested;
    public event EventHandler<string>? TopicRequested;

    public HelpInspector()
    {
        InitializeComponent();
        Loaded += (_, _) =>
        {
            StudioHelp.Changed += OnHelp;
            Refresh();
        };
        Unloaded += (_, _) => StudioHelp.Changed -= OnHelp;
    }

    private void OnHelp() => DispatcherQueue.TryEnqueue(Refresh);

    private void Refresh()
    {
        var topic = StudioHelp.Current;
        ModeText.Text = StudioHelp.ModeLabel;
        TitleText.Text = topic.Title;
        PlaceText.Text = StudioLexicon.Place(topic.Id);
        PlaceText.Visibility = string.IsNullOrEmpty(PlaceText.Text) ? Visibility.Collapsed : Visibility.Visible;
        SummaryText.Text = topic.Summary;
        BodyText.Text = topic.Body;
        RelatedList.ItemsSource = StudioLexicon.Related(topic);
        PinButton.Content = StudioHelp.IsPinned ? "Unpin" : "Pin this";
    }

    private void OnPin(object sender, RoutedEventArgs e) => StudioHelp.TogglePin();

    private void OnGlossary(object sender, RoutedEventArgs e) =>
        GlossaryRequested?.Invoke(this, EventArgs.Empty);

    private void OnHide(object sender, RoutedEventArgs e) =>
        HideRequested?.Invoke(this, EventArgs.Empty);

    private void OnRelatedClick(object sender, RoutedEventArgs e)
    {
        if (sender is FrameworkElement { Tag: string id })
        {
            StudioHelp.ShowTopic(id);
            TopicRequested?.Invoke(this, id);
        }
    }
}
