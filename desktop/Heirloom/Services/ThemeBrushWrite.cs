namespace Heirloom.Services;

/// <summary>
/// Puts a new brush into the resource dictionary. Sealed theme brushes throw
/// UnauthorizedAccessException when their Color is changed, so callers replace
/// the entry and keep going if one key refuses the write.
/// </summary>
public static class ThemeBrushWrite
{
    public static bool Assign(Action assign, string key, Action<string, Exception>? log)
    {
        try
        {
            assign();
            return true;
        }
        catch (Exception ex)
        {
            log?.Invoke(key, ex);
            return false;
        }
    }
}
