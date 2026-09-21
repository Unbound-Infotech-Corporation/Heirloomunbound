namespace Heirloom.Services;

public sealed record TwinSetupExample(string Id, string Title, string Caption);

public sealed record TwinSetupStepState(
    string Id,
    string Label,
    string Benefit,
    string Cta,
    string DocumentId,
    bool Critical,
    bool Done,
    int Have,
    int Need,
    IReadOnlyList<TwinSetupExample> Examples);

public sealed record TwinSetupSnapshot(
    IReadOnlyList<TwinSetupStepState> Steps,
    int RemainingCritical,
    bool AllCriticalDone,
    bool Dismissed,
    bool Visible,
    bool YoureSet);

public static class TwinSetupProgress
{
    public const int LikenessNeeded = 3;

    public static readonly TwinSetupExample[] VoiceExamples =
    [
        new("quiet", "1. A quiet room", "Close the door. Phone on the table, not in a pocket."),
        new("speak", "2. Speak for about 30 seconds", "Read something you would actually say."),
        new("ready", "3. That recording is the Twin's voice", "Stock voices stay off once this is done."),
    ];

    public static readonly TwinSetupExample[] LikenessExamples =
    [
        new("front", "1. Straight on", "Head and shoulders, both eyes toward the lens."),
        new("three_quarter", "2. Three-quarter", "Turn a little. Same distance."),
        new("profile", "3. Profile", "Side of the face. Same height."),
    ];

    public static TwinSetupSnapshot Build(
        bool voiceReady,
        int likenessHave,
        bool avatarReady,
        bool dismissed,
        bool heirMode)
    {
        var have = Math.Max(0, likenessHave);
        var likenessReady = have >= LikenessNeeded;
        var remainingCritical = (voiceReady ? 0 : 1) + (likenessReady ? 0 : 1);
        var allCritical = remainingCritical == 0;
        var hide = heirMode || dismissed && !allCritical;
        var steps = new TwinSetupStepState[]
        {
            new(
                "voice",
                "Clone your voice",
                "Your Twin speaks as you — live sit, talking video, and a room sit.",
                "Set up the Twin voice",
                "keys",
                true,
                voiceReady,
                voiceReady ? 1 : 0,
                1,
                VoiceExamples),
            new(
                "likeness",
                "Take likeness photos",
                "A lifelike talking picture of you — video, live sit, and the Heirloom Room.",
                "Take the three photos",
                "avatar",
                true,
                likenessReady,
                have,
                LikenessNeeded,
                LikenessExamples),
            new(
                "avatar",
                "Set a talking-picture source",
                "Play as video uses your face instead of a stock presenter.",
                "Use a photo as the Twin face",
                "avatar",
                false,
                avatarReady,
                avatarReady ? 1 : 0,
                1,
                [new TwinSetupExample("pick", "Pick the front photo", "Choose the straight-on likeness.")]),
        };

        return new TwinSetupSnapshot(
            steps,
            remainingCritical,
            allCritical,
            dismissed && !allCritical && !heirMode,
            Visible: !heirMode && !allCritical && !dismissed,
            YoureSet: !heirMode && allCritical);
    }
}
