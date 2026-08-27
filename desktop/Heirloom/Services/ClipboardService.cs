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

    public static async Task<string> GetTextAsync()
    {
        var tcs = new TaskCompletionSource<string>(TaskCreationOptions.RunContinuationsAsynchronously);
        UiDispatch.Post(() => _ = ReadAsync(tcs));
        try
        {
            return await tcs.Task.WaitAsync(TimeSpan.FromSeconds(3)).ConfigureAwait(false);
        }
        catch (TimeoutException)
        {
            return "";
        }
    }

    private static async Task ReadAsync(TaskCompletionSource<string> tcs)
    {
        try
        {
            var content = Clipboard.GetContent();
            if (content.Contains(StandardDataFormats.Text))
            {
                tcs.TrySetResult(await content.GetTextAsync());
                return;
            }

            tcs.TrySetResult("");
        }
        catch (Exception ex)
        {
            tcs.TrySetResult("(clipboard unread: " + ex.Message + ")");
        }
    }
}
