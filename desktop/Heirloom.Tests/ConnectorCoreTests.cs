using Heirloom.Services;
using Xunit;

namespace Heirloom.Tests;

public class ConnectorCoreTests
{
    [Fact]
    public void Connector_paths_are_owner_session_routes()
    {
        Assert.Equal("/connectors", ConnectorCore.ListPath);
        Assert.Equal("/connectors/status", ConnectorCore.StatusPath);
        Assert.False(ConnectorCore.GmailEnabled);
        Assert.Contains("Settings > Connectors", ConnectorCore.NotConnected, StringComparison.Ordinal);
    }
}
