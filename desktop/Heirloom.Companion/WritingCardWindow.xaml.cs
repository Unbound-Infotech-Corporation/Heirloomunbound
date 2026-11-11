using System.Windows;
using Heirloom.BoxCore;

namespace Heirloom.Companion;

public partial class WritingCardWindow : Window
{
    private readonly WritingPaste _card;

    public WritingCardWindow(string selected)
    {
        InitializeComponent();
        _card = WritingPaste.Propose(selected, "shorter");
        Before.Text = _card.Before.Length == 0 ? "Highlight some words, then press Ctrl+Alt+H again." : _card.Before;
        After.Text = _card.After;
    }

    private void OnNo(object sender, RoutedEventArgs e) => Close();

    private void OnYes(object sender, RoutedEventArgs e)
    {
        _card.Approve();
        var text = _card.PasteBack();
        if (text is not null)
        {
            try
            {
                Clipboard.SetText(text);
            }
            catch
            {
                // The card stays open if the clipboard is busy.
                return;
            }
        }

        Close();
    }
}
