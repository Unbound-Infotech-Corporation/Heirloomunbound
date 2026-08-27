using System.Text.RegularExpressions;

namespace Heirloom.Services;

public enum VideoShotKind
{
    TalkingHead,
    PhotoHold,
    ImageToVideo,
    TextToVideo,
}

public sealed record VideoPreset(
    string Id,
    string Title,
    string Blurb,
    string DefaultScript,
    IReadOnlyList<VideoShotKind> Beats);

public sealed record VideoShotPlan(
    string Id,
    VideoShotKind Kind,
    string Title,
    string Script,
    string? ImagePath,
    int Seconds,
    string ModelId);

public sealed record VideoModelChoice(
    string Id,
    string Title,
    string Job,
    string RecommendFor,
    string Vram,
    string Blurb,
    bool LocalPreferred);

public sealed record VideoJobIntent(
    string Action,
    string PresetId,
    string Script,
    bool UseLastReply,
    string OpeningLine,
    string WorkingLine,
    string DoneLine);

public static class VideoCatalog
{
    public static IReadOnlyList<VideoPreset> Presets { get; } =
    [
        new(
            "kids",
            "Message to my kids",
            "A talking likeness that says one thing you want them to keep.",
            "I love you. I am proud of you. When you miss me, play this and sit with it.",
            [VideoShotKind.TalkingHead]),
        new(
            "story",
            "Tell a life story",
            "You speak, then filed photographs hold while the same voice continues.",
            "Let me tell you how this day still feels in the room.",
            [VideoShotKind.TalkingHead, VideoShotKind.PhotoHold, VideoShotKind.PhotoHold]),
        new(
            "answer",
            "Answer this question on video",
            "The last Twin reply, spoken on the filed face.",
            "",
            [VideoShotKind.TalkingHead]),
        new(
            "memory",
            "Memory video",
            "Photographs from the archive, with your voice over them.",
            "This is how that day still looks to me.",
            [VideoShotKind.PhotoHold, VideoShotKind.PhotoHold, VideoShotKind.TalkingHead]),
        new(
            "greeting",
            "Greeting",
            "A short hello in your voice and face.",
            "Hello. I am glad you opened this.",
            [VideoShotKind.TalkingHead]),
        new(
            "scene",
            "Scene from a picture",
            "Turn a still into motion when Wan or LTX is on this PC; otherwise a living still with voice.",
            "The room as I remember it, light and all.",
            [VideoShotKind.ImageToVideo, VideoShotKind.TalkingHead]),
    ];

    public static IReadOnlyList<VideoModelChoice> Models { get; } =
    [
        new(
            "latentsync",
            "Talking likeness (LatentSync 1.6)",
            "talking",
            "Any film that needs your mouth and cloned voice.",
            "8–12 GB",
            "ByteDance LatentSync on this GPU. Prefers a 1–2 minute sitting of you talking. A strict still is backup. Does not open ComfyUI.",
            true),
        new(
            "ltx",
            "LTX Video (recommended for motion)",
            "i2v-t2v",
            "Fast image-to-video and text-to-video on a single good GPU.",
            "8–16 GB",
            "Lightricks LTX-Video / LTX 2.3 fp8 in ComfyUI. Best everyday motion engine. This studio never shows the graph.",
            true),
        new(
            "wan22-5b",
            "Wan 2.2 TI2V 5B (recommended text-to-video)",
            "t2v",
            "Text-to-video that still fits a serious gaming GPU.",
            "12–16 GB",
            "Alibaba Wan 2.2 combined text+image 5B. Stronger than older 1.3B Wan, lighter than the 14B experts.",
            true),
        new(
            "wan22-i2v",
            "Wan 2.2 I2V A14B (best likeness motion)",
            "i2v",
            "Move a photograph while keeping the person.",
            "16–24 GB",
            "Wan 2.2 image-to-video mixture-of-experts. Use when the still is the owner or a filed memory and the card can hold it.",
            false),
        new(
            "hunyuan",
            "HunyuanVideo 1.5 (cinematic, heavy)",
            "t2v",
            "Longer cinematic shots when this PC has a 24 GB card.",
            "24 GB",
            "Tencent HunyuanVideo. Slow and large. Not the default for a family message.",
            false),
        new(
            "minimax",
            "MiniMax Hailuo / H3 (not local)",
            "cloud",
            "Only if you already run a MiniMax API. Heirloom does not ship it.",
            "cloud",
            "Hailuo-class models are hosted. Local ComfyUI ports usually sit on Wan. Prefer Wan 2.2 on this PC.",
            false),
        new(
            "hold",
            "Living still (always available)",
            "hold",
            "When motion models are not on disk yet.",
            "CPU",
            "The photograph holds, the cloned voice speaks, the film still exports. Honest, not a fake mouth on a stamp.",
            true),
    ];

    public static VideoPreset ById(string id) =>
        Presets.FirstOrDefault(p => p.Id.Equals(id, StringComparison.OrdinalIgnoreCase)) ?? Presets[0];

    public static VideoModelChoice Recommend(
        VideoShotKind kind,
        bool talkingReady,
        bool ltxReady,
        bool wanReady,
        bool hunyuanReady)
    {
        return kind switch
        {
            VideoShotKind.TalkingHead => talkingReady ? Models[0] : Models[0],
            VideoShotKind.ImageToVideo when wanReady => Models.First(m => m.Id == "wan22-i2v"),
            VideoShotKind.ImageToVideo when ltxReady => Models.First(m => m.Id == "ltx"),
            VideoShotKind.ImageToVideo => Models.First(m => m.Id == "hold"),
            VideoShotKind.TextToVideo when wanReady => Models.First(m => m.Id == "wan22-5b"),
            VideoShotKind.TextToVideo when ltxReady => Models.First(m => m.Id == "ltx"),
            VideoShotKind.TextToVideo when hunyuanReady => Models.First(m => m.Id == "hunyuan"),
            VideoShotKind.TextToVideo => Models.First(m => m.Id == "hold"),
            _ => Models.First(m => m.Id == "hold"),
        };
    }

    public static string RecommendLine(bool talkingReady, bool ltxReady, bool wanReady, bool hunyuanReady, bool comfyUp)
    {
        var talking = talkingReady
            ? "Talking likeness is ready on this PC."
            : "Talking likeness still needs Fetch engine (LatentSync 1.6).";
        var motion = wanReady
            ? "Wan 2.2 is on disk — use it for picture motion."
            : ltxReady
                ? "LTX is on disk — use it for fast motion."
                : hunyuanReady
                    ? "Hunyuan is on disk — cinematic, slow."
                    : comfyUp
                        ? "ComfyUI is running. This studio will use it when Wan or LTX nodes are present, without opening the graph."
                        : "Motion models are not on this PC yet. Films still export: you speak, photographs hold.";
        return talking + " " + motion;
    }

    public static IReadOnlyList<VideoShotPlan> BuildTimeline(
        VideoPreset preset,
        string script,
        IReadOnlyList<string> photos,
        bool talkingReady,
        bool ltxReady,
        bool wanReady)
    {
        var line = string.IsNullOrWhiteSpace(script) ? preset.DefaultScript : script.Trim();
        var shots = new List<VideoShotPlan>();
        var photoIx = 0;
        for (var i = 0; i < preset.Beats.Count; i++)
        {
            var kind = preset.Beats[i];
            string? image = null;
            if (kind is VideoShotKind.PhotoHold or VideoShotKind.ImageToVideo)
            {
                if (photos.Count > 0)
                {
                    image = photos[photoIx % photos.Count];
                    photoIx++;
                }
            }

            var model = Recommend(kind, talkingReady, ltxReady, wanReady, hunyuanReady: false);
            var title = kind switch
            {
                VideoShotKind.TalkingHead => "You speaking",
                VideoShotKind.PhotoHold => "Photograph with your voice",
                VideoShotKind.ImageToVideo => "Picture into motion",
                VideoShotKind.TextToVideo => "Scene from words",
                _ => "Beat",
            };
            var seconds = kind == VideoShotKind.TalkingHead
                ? Math.Clamp(8 + (line.Length / 18), 8, 28)
                : 6;
            var beatScript = kind == VideoShotKind.TalkingHead || i == 0
                ? line
                : BeatLine(line, i);
            shots.Add(new VideoShotPlan(
                Guid.NewGuid().ToString("N")[..10],
                kind,
                title,
                beatScript,
                image,
                seconds,
                model.Id));
        }

        return shots;
    }

    public static IReadOnlyList<string> PhotoPathsFromStories(IEnumerable<string> bodies)
    {
        var paths = new List<string>();
        foreach (var body in bodies)
        {
            var match = Regex.Match(body ?? "", @"Photo:\s*(.+)", RegexOptions.IgnoreCase);
            if (!match.Success)
            {
                continue;
            }

            var path = match.Groups[1].Value.Trim();
            if (path.StartsWith("(none", StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }

            if (File.Exists(path))
            {
                paths.Add(path);
            }
        }

        return paths;
    }

    public static string ShotKindLabel(VideoShotKind kind) => kind switch
    {
        VideoShotKind.TalkingHead => "Talking likeness",
        VideoShotKind.PhotoHold => "Living still",
        VideoShotKind.ImageToVideo => "Image to video",
        VideoShotKind.TextToVideo => "Text to video",
        _ => "Shot",
    };

    private static string BeatLine(string script, int index)
    {
        var parts = script.Split(['.', '!', '?'], StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
        if (parts.Length == 0)
        {
            return script;
        }

        return parts[Math.Min(index, parts.Length - 1)].Trim() + ".";
    }
}

public static class VideoIntent
{
    public static bool TryParse(string? utterance, out VideoJobIntent intent)
    {
        intent = default!;
        var raw = (utterance ?? "").Trim().TrimEnd('.', '!', '?');
        if (raw.Length == 0)
        {
            return false;
        }

        var lower = raw.ToLowerInvariant();
        if (Regex.IsMatch(lower, @"^(open |show |go to )(the )?(video studio|avatar studio|likeness studio|video)$")
            || Regex.IsMatch(lower, @"^(the )?(video studio|avatar studio|likeness studio)$"))
        {
            intent = Open("greeting", "");
            return true;
        }

        var saying = Regex.Match(
            raw,
            @"^(?:make|create|film|record)\s+(?:a\s+)?video\s+(?:of\s+me\s+)?(?:saying|that says)\s+(.+)$",
            RegexOptions.IgnoreCase);
        if (saying.Success)
        {
            var script = saying.Groups[1].Value.Trim().Trim('"');
            intent = Film("kids", script, false);
            return true;
        }

        if (Regex.IsMatch(lower, @"\b(make|create|film|record)\s+(a\s+)?video\s+of\s+(that|this|the answer|your answer)\b")
            || lower is "make a video of that" or "film that" or "make a video")
        {
            intent = Film("answer", "", true);
            return true;
        }

        var presetHit = Regex.Match(
            raw,
            @"^(?:film|record)\s+(?:a\s+)?(?:video\s+)?(?:for\s+)?(?:my\s+)?(kids|children|life story|story|memory|greeting|hello)\b|^(?:make|create)\s+(?:a\s+)?video\s+(?:for\s+)?(?:my\s+)?(kids|children|life story|story|memory|greeting|hello)\b",
            RegexOptions.IgnoreCase);
        if (presetHit.Success)
        {
            var key = (presetHit.Groups[1].Success ? presetHit.Groups[1].Value : presetHit.Groups[2].Value).ToLowerInvariant();
            var id = key is "kids" or "children" ? "kids" : key is "life story" or "story" ? "story" : key is "memory" ? "memory" : "greeting";
            intent = Film(id, VideoCatalog.ById(id).DefaultScript, false);
            return true;
        }

        return false;
    }

    private static VideoJobIntent Open(string preset, string script) =>
        new("open", preset, script, false, "Opening Video studio…", "Laying out the film…", "Video studio is open.");

    private static VideoJobIntent Film(string preset, string script, bool last) =>
        new(
            "film",
            preset,
            script,
            last,
            "Opening Video studio…",
            last ? "Using the last Twin answer as the line to speak…" : "Laying out the film…",
            "Video studio is open with that film.");
}
