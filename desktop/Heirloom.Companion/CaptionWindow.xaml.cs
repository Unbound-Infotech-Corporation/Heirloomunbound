using System.Windows;

namespace Heirloom.Companion;

/// <summary>
/// On-screen caption. ShowActivated is false so it does not take the keyboard from BIGDEAL.
/// </summary>
public partial class CaptionWindow : Window
{
    public CaptionWindow()
    {
        InitializeComponent();
        Left = SystemParameters.WorkArea.Left + 24;
        Top = SystemParameters.WorkArea.Bottom - 160;
    }

    public void ShowCaption(string text)
    {
        var caption = (text ?? "").Trim();
        if (caption.Length == 0)
        {
            Hide();
            return;
        }

        Caption.Text = caption;
        if (!IsVisible)
        {
            Show();
        }
    }
}
