namespace Heirloom.Services;

/// <summary>
/// Owner mailbox connectors. Read-only client paths.
/// The Windows connect form is a follow-up; web Settings is the owner surface.
/// Heirs do not call these routes.
/// </summary>
public static class ConnectorCore
{
    public const string ListPath = "/connectors";
    public const string StatusPath = "/connectors/status";
    public const bool GmailEnabled = false;

    public const string NotConnected =
        "No email is connected. Connect one in Settings > Connectors.";
}
