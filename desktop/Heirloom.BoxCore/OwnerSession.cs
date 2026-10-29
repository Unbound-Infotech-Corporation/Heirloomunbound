namespace Heirloom.BoxCore;

public static class OwnerSession
{
    public const string SignedOutSignInAgain = "Signed out, sign in again";

    public static bool IsRejected(int statusCode) => statusCode == 401;

    public static void DeleteFile(string path)
    {
        try
        {
            if (!string.IsNullOrWhiteSpace(path) && File.Exists(path))
            {
                File.Delete(path);
            }
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
        }
    }
}
