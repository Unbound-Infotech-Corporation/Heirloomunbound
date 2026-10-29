using Heirloom.BoxCore;

namespace Heirloom.Companion;

internal static class CompanionSession
{
    public static async Task SignOutAsync(CompanionStore store, CancellationToken cancellationToken = default)
    {
        var token = store.Session();
        store.ClearSession();
        if (string.IsNullOrWhiteSpace(token))
        {
            return;
        }

        try
        {
            await BoxClient.LogoutAsync(store.BoxUrl, store.Pin, store.CaPem, token, cancellationToken).ConfigureAwait(false);
        }
        catch (Exception)
        {
            // The box may be offline. The session file is already gone.
        }
    }
}
