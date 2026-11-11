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
        Assert.Equal("", SelectionCapture.AfterCopy(false, "old clipboard", "highlighted words"));
        Assert.Equal("", SelectionCapture.AfterCopy(true, "old clipboard", "old clipboard"));
        Assert.Equal("highlighted words", SelectionCapture.AfterCopy(true, "old clipboard", "highlighted words"));
        var chord = CopyChord.Sequence();
        var altUp = chord.ToList().FindIndex(step => step.Key == CopyChord.VkMenu && !step.Down);
        var cDown = chord.ToList().FindIndex(step => step.Key == CopyChord.VkC && step.Down);
        Assert.True(altUp >= 0 && cDown > altUp);
    }
}
