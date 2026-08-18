using Windows.ApplicationModel.DataTransfer;

namespace Heirloom.Services;

public static class ClipboardService
{
    public static void CopyText(string text)
    {
        if (string.IsNullOrEmpty(text))
        {
            return;
        }

        UiDispatch.Post(() =>
        {
            var package = new DataPackage();
            package.SetText(text);
            Clipboard.SetContent(package);
        });
    }
}
