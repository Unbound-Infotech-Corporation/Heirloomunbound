using Microsoft.UI.Dispatching;

namespace Heirloom;

internal static class UiDispatch
{
    public static void Post(Action action)
    {
        var queue = App.DispatcherQueue;
        if (queue is null || queue.HasThreadAccess)
        {
            action();
            return;
        }

        queue.TryEnqueue(DispatcherQueuePriority.Normal, () => action());
    }
}
