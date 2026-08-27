using Heirloom.Services;
using Xunit;

namespace Heirloom.Tests;

public class VideoStudioTests
{
    [Fact]
    public void Presets_cover_family_jobs()
    {
        Assert.Contains(VideoCatalog.Presets, p => p.Id == "kids");
        Assert.Contains(VideoCatalog.Presets, p => p.Id == "story");
        Assert.Contains(VideoCatalog.Presets, p => p.Id == "answer");
        Assert.Contains(VideoCatalog.Presets, p => p.Id == "memory");
        Assert.Contains(VideoCatalog.Presets, p => p.Id == "greeting");
        Assert.Contains(VideoCatalog.Presets, p => p.Id == "scene");
    }

    [Theory]
    [InlineData("open video studio", "open", "greeting", false)]
    [InlineData("Open the Video studio", "open", "greeting", false)]
    [InlineData("show avatar studio", "open", "greeting", false)]
    [InlineData("make a video of that", "film", "answer", true)]
    [InlineData("Make a video of this", "film", "answer", true)]
    [InlineData("film that", "film", "answer", true)]
    [InlineData("make a video saying I love you", "film", "kids", false)]
    [InlineData("make a video for my kids", "film", "kids", false)]
    [InlineData("film a life story", "film", "story", false)]
    [InlineData("make a video memory", "film", "memory", false)]
    [InlineData("film a greeting", "film", "greeting", false)]
    public void Parses_studio_and_film_orders(string utterance, string action, string preset, bool last)
    {
        Assert.True(VideoIntent.TryParse(utterance, out var intent));
        Assert.Equal(action, intent.Action);
        Assert.Equal(preset, intent.PresetId);
        Assert.Equal(last, intent.UseLastReply);
    }

    [Fact]
    public void Saying_clause_becomes_the_script()
    {
        Assert.True(VideoIntent.TryParse("make a video saying I am proud of you", out var intent));
        Assert.Equal("I am proud of you", intent.Script);
        Assert.False(intent.UseLastReply);
    }

    [Theory]
    [InlineData("where did you grow up")]
    [InlineData("open notepad")]
    [InlineData("search for tax PDF")]
    [InlineData("tell me a story")]
    [InlineData("create a life story")]
    [InlineData("video")]
    public void Leaves_ordinary_talk_alone(string utterance)
    {
        Assert.False(VideoIntent.TryParse(utterance, out _));
    }

    [Fact]
    public void Timeline_uses_talking_head_then_holds()
    {
        var photos = new[] { @"C:\missing-a.jpg", @"C:\missing-b.jpg" };
        var shots = VideoCatalog.BuildTimeline(
            VideoCatalog.ById("story"),
            "First sentence. Second sentence. Third.",
            photos,
            talkingReady: true,
            ltxReady: false,
            wanReady: false);
        Assert.Equal(3, shots.Count);
        Assert.Equal(VideoShotKind.TalkingHead, shots[0].Kind);
        Assert.Equal("latentsync", shots[0].ModelId);
        Assert.Equal(VideoShotKind.PhotoHold, shots[1].Kind);
        Assert.Equal("hold", shots[1].ModelId);
    }

    [Fact]
    public void Image_to_video_recommends_wan_then_ltx_then_hold()
    {
        Assert.Equal("wan22-i2v", VideoCatalog.Recommend(VideoShotKind.ImageToVideo, true, false, true, false).Id);
        Assert.Equal("ltx", VideoCatalog.Recommend(VideoShotKind.ImageToVideo, true, true, false, false).Id);
        Assert.Equal("hold", VideoCatalog.Recommend(VideoShotKind.ImageToVideo, true, false, false, false).Id);
        Assert.Equal("wan22-5b", VideoCatalog.Recommend(VideoShotKind.TextToVideo, true, false, true, false).Id);
    }

    [Fact]
    public void Recommend_line_is_honest_without_weights()
    {
        var line = VideoCatalog.RecommendLine(true, false, false, false, false);
        Assert.Contains("Talking likeness is ready", line, StringComparison.OrdinalIgnoreCase);
        Assert.Contains("Motion models are not on this PC yet", line, StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain("MiniMax", line, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public void Photo_paths_come_from_photo_stories()
    {
        var dir = Path.Combine(Path.GetTempPath(), "heirloom-video-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(dir);
        var photo = Path.Combine(dir, "day.jpg");
        File.WriteAllBytes(photo, [1, 2, 3]);
        try
        {
            var found = VideoCatalog.PhotoPathsFromStories(["Caption.\nPhoto: " + photo]);
            Assert.Equal(photo, Assert.Single(found));
            Assert.Empty(VideoCatalog.PhotoPathsFromStories(["Photo: (none)"]));
        }
        finally
        {
            Directory.Delete(dir, recursive: true);
        }
    }
}
