using Heirloom.BoxCore;
using Xunit;

namespace Heirloom.Tests;

public class WritingPasteTests
{
    [Fact]
    public void Hotkey_paste_waits_for_approval()
    {
        var card = WritingPaste.Propose("This is very long.", "shorter");
        Assert.Null(card.PasteBack());
        card.Approve();
        Assert.Equal("This is long.", card.PasteBack());
    }
}
