using Heirloom.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace Heirloom.Controls;

public sealed partial class WritingAssistView : UserControl
{
    private readonly WritingModel _model = new();

    public WritingAssistView()
    {
        InitializeComponent();
        Definition.Text = "Hover a suggestion, or type a word.";
    }

    private void OnText(object sender, TextChangedEventArgs e)
    {
        _model.Check(Draft.Text);
        Underlines.ItemsSource = _model.Segments.Select(segment => new UnderlineRow(segment)).ToList();
    }

    private void OnFix(object sender, RoutedEventArgs e)
    {
        var next = string.Concat(_model.Segments.Select(segment => segment.Suggestion.Length > 0 ? segment.Suggestion : segment.Text));
        Draft.Text = next;
    }

    private void OnShorter(object sender, RoutedEventArgs e) => ShowRewrite("shorter");

    private void OnFriendlier(object sender, RoutedEventArgs e) => ShowRewrite("friendlier");

    private void OnFormal(object sender, RoutedEventArgs e) => ShowRewrite("formal");

    private void ShowRewrite(string mode)
    {
        _model.Check(Draft.Text);
        PasteLine.Text = _model.Rewrite(mode) + "  ·  Approve before it is pasted anywhere.";
    }

    private void OnApprove(object sender, RoutedEventArgs e)
    {
        if (_model.ApprovePaste())
        {
            var text = _model.PasteBack();
            if (text is not null)
            {
                Draft.Text = text;
            }

            PasteLine.Text = "Pasted into this document.";
        }
    }

    private void OnWord(object sender, TextChangedEventArgs e)
    {
        _model.Define(Word.Text);
        Definition.Text = _model.LookupLine;
    }

    private sealed class UnderlineRow
    {
        public UnderlineRow(TextSegment segment)
        {
            Text = segment.Text;
            Decoration = segment.Underline ? Windows.UI.Text.TextDecorations.Underline : Windows.UI.Text.TextDecorations.None;
        }

        public string Text { get; }
        public Windows.UI.Text.TextDecorations Decoration { get; }
    }
}
