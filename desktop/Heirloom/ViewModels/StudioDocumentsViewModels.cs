using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using Heirloom.Services;

namespace Heirloom.ViewModels;

public sealed class ArchiveEntry
{
    public ArchiveEntry(string title, string body, string meta, string kind = "", string tag = "")
    {
        Title = title;
        Body = body;
        Meta = meta;
        Kind = kind;
        Tag = tag;
    }

    public string Title { get; }
    public string Body { get; }
    public string Meta { get; }
    public string Kind { get; }
    public string Tag { get; }
    public string Headline => string.IsNullOrWhiteSpace(Tag) ? Title : Title + "  ·  " + Tag;
}

public sealed record KindChoice(string Id, string Label);

public sealed class InterviewChapter
{
    public InterviewChapter(string id, string title, string prompt)
    {
        Id = id;
        Title = title;
        Prompt = prompt;
    }

    public string Id { get; }
    public string Title { get; }
    public string Prompt { get; }
}

public partial class ArchiveViewModel : ObservableObject
{
    private readonly AppHost _host;

    public ObservableCollection<ArchiveEntry> Entries { get; } = [];
    public IReadOnlyList<KindChoice> FilterKinds { get; } =
    [
        new("all", "All kinds"),
        new("note", "Note"),
        new("speech", "Spoken"),
        new("journal", "Journal"),
        new("interview", "Chapter"),
        new("photo_story", "Photo story"),
        new("memoir", "Memoir"),
        new("import", "Import"),
    ];
    public IReadOnlyList<KindChoice> FileKinds { get; } =
    [
        new("note", "Note"),
        new("speech", "Spoken"),
        new("journal", "Journal"),
        new("interview", "Chapter"),
        new("photo_story", "Photo story"),
        new("memoir", "Memoir"),
        new("import", "Import"),
    ];

    [ObservableProperty] private string _query = "";
    [ObservableProperty] private string _draft = "";
    [ObservableProperty] private string _kindFilter = "all";
    [ObservableProperty] private string _captureKind = "note";
    [ObservableProperty] private KindChoice? _selectedFilter;
    [ObservableProperty] private KindChoice? _selectedFileKind;
    [ObservableProperty] private string _status = "";
    [ObservableProperty] private string _completeness = "";
    [ObservableProperty] private string _emptyHint = "File one true sentence. The twin has nothing to stand on until you do.";
    private long _lastFiled;
    private bool _ready;

    public ArchiveViewModel(AppHost host)
    {
        _host = host;
        SelectedFilter = FilterKinds[0];
        SelectedFileKind = FileKinds[0];
        _ready = true;
        Reload();
    }

    partial void OnSelectedFilterChanged(KindChoice? value)
    {
        KindFilter = value?.Id ?? "all";
        if (_ready)
        {
            Reload();
        }
    }

    partial void OnSelectedFileKindChanged(KindChoice? value)
    {
        CaptureKind = value?.Id ?? "note";
    }

    [RelayCommand]
    public void Reload()
    {
        Entries.Clear();
        IReadOnlyList<VaultRow> rows = string.IsNullOrWhiteSpace(Query)
            ? _host.Vault.Recent(80, KindFilter)
            : _host.Vault.Search(Query, KindFilter);
        foreach (var row in rows)
        {
            Entries.Add(new ArchiveEntry(row.Kind, row.Text, row.Created, row.Kind, row.Tag));
        }

        var stats = _host.Vault.Stats();
        Status = $"{stats.Captures} captures  ·  {stats.Letters} letters  ·  {stats.Heirs} heirs";
        Completeness = VaultService.GapLine(stats);
        EmptyHint = Entries.Count == 0
            ? "Nothing here yet. Capture, interview, or import — then the twin can answer from this vault."
            : "";
    }

    [RelayCommand]
    public void SearchNow() => Reload();

    [RelayCommand]
    public void Capture()
    {
        if (!_host.CanEdit)
        {
            Status = "Heir mode. Filing is locked.";
            return;
        }

        if (string.IsNullOrWhiteSpace(Draft))
        {
            Status = "Write one true sentence, then File.";
            return;
        }

        var kind = string.IsNullOrWhiteSpace(CaptureKind) || CaptureKind == "all" ? "note" : CaptureKind;
        _lastFiled = _host.Vault.AddCapture(kind, Draft.Trim());
        Draft = "";
        Reload();
        Status = "Filed. Undo if that was a slip.";
    }

    [RelayCommand]
    public void UndoLastFile()
    {
        if (!_host.CanEdit)
        {
            Status = "Heir mode. The vault is locked.";
            return;
        }

        if (_lastFiled <= 0 || !_host.Vault.DeleteCapture(_lastFiled))
        {
            Status = "Nothing to take back.";
            return;
        }

        _lastFiled = 0;
        Reload();
        Status = "Took back the last file.";
    }

    [RelayCommand]
    public async Task AskArchiveAsync()
    {
        if (string.IsNullOrWhiteSpace(Query))
        {
            Reload();
            return;
        }

        Reload();
        var result = await _host.Api.PostSessionAsync("/archive/ask", new { q = Query }).ConfigureAwait(true);
        if (result is { } json && json.TryGetProperty("answer", out var a))
        {
            Status = a.GetString() ?? Status;
            return;
        }

        var local = _host.Vault.CitationsFor(Query);
        Status = local.Count == 0
            ? "No cloud answer — and nothing local matched. File it, then ask again."
            : "Local hits only: " + string.Join(" · ", local.Select(c => c.Kind));
    }
}

public partial class TodayViewModel : ObservableObject
{
    private readonly AppHost _host;

    public TodayViewModel(AppHost host)
    {
        _host = host;
        Nudge = "Sit with the twin for five minutes. One true sentence is enough.";
        _ = LoadAsync();
    }

    [ObservableProperty] private string _nudge = "";
    [ObservableProperty] private string _greeting = "Today";
    [ObservableProperty] private string _completeness = "";
    [ObservableProperty] private string _nextChapter = "Childhood";
    [ObservableProperty] private string _streak = "No session yet today.";
    [ObservableProperty] private string _nextActionId = "twin";
    [ObservableProperty] private string _nextActionLabel = "Sit with the twin";
    [ObservableProperty] private string _nextActionGlyph = "\uE8BD";
    [ObservableProperty] private string _nextActionAsset = "action-twin";
    [ObservableProperty] private string _nextWhy = "One true sentence is enough.";

    public async Task LoadAsync()
    {
        Greeting = DateTime.Now.ToString("dddd, MMMM d");
        var stats = _host.Vault.Stats();
        ChooseNext(stats);
        Completeness = _host.Vault.LookBack();
        NextChapter = NextWhy;
        Streak = stats.Captures == 0
            ? "Nothing filed yet"
            : $"{stats.Captures} memories on this PC.";
        var result = await _host.Api.GetSessionAsync("/nudges/today").ConfigureAwait(true);
        if (result is { } json && json.TryGetProperty("body", out var body))
        {
            Nudge = body.GetString() ?? Nudge;
        }
    }

    private void ChooseNext(VaultStats stats)
    {
        if (stats.Captures == 0)
        {
            SetNext("twin", "Sit with the twin", "\uE8BD", "action-twin",
                "One true sentence is enough. Do not open three rooms at once.");
            return;
        }

        if (!stats.ByKind.ContainsKey("interview"))
        {
            SetNext("interviewer", "One chapter", "\uE8F2", "action-interview",
                "A life is easier to gift as chapters. One chapter today — not the whole biography.");
            return;
        }

        SetNext("journal", "Journal today", "\uE70B", "action-journal",
            "Write what today actually was. That is how you notice what the twin still cannot say.");
    }

    private void SetNext(string id, string label, string glyph, string asset, string why)
    {
        NextActionId = id;
        NextActionLabel = label;
        NextActionGlyph = glyph;
        NextActionAsset = asset;
        NextWhy = why;
    }
}

public partial class JournalViewModel : ObservableObject
{
    private readonly AppHost _host;

    public JournalViewModel(AppHost host)
    {
        _host = host;
        Reload();
    }

    public ObservableCollection<ArchiveEntry> Entries { get; } = [];
    public IReadOnlyList<string> Tags { get; } = ["morning", "work", "family", "health", "hard day", "gratitude"];

    [ObservableProperty] private string _draft = "";
    [ObservableProperty] private string _tag = "morning";
    [ObservableProperty] private string _status = "";

    [RelayCommand]
    public void Reload()
    {
        Entries.Clear();
        foreach (var row in _host.Vault.Recent(40, "journal"))
        {
            Entries.Add(new ArchiveEntry(row.Tag.Length == 0 ? "journal" : row.Tag, row.Text, row.Created, row.Kind, row.Tag));
        }

        Status = Entries.Count + " journal entries  ·  tags keep retrieval honest";
    }

    [RelayCommand]
    public void FileEntry()
    {
        if (!_host.CanEdit)
        {
            Status = "Heir mode. Filing is locked.";
            return;
        }

        if (string.IsNullOrWhiteSpace(Draft))
        {
            Status = "Write the day, then File.";
            return;
        }

        _host.Vault.AddCapture("journal", Draft.Trim(), Tag);
        Draft = "";
        Reload();
        Status = "Filed this day.";
    }
}

public partial class InterviewerViewModel : ObservableObject
{
    private readonly AppHost _host;
    private int _index;

    public InterviewerViewModel(AppHost host)
    {
        _host = host;
        Chapters =
        [
            new("childhood", "Childhood", "Where did you grow up, and what did the house smell like?"),
            new("family", "Family", "Who sat at the table, and what did they believe about you?"),
            new("work", "Work", "What did you actually do all day — not the job title, the work."),
            new("love", "Love", "Who did you love, and what would they say you were like?"),
            new("hard", "Hard years", "What almost broke you, and what did you do anyway?"),
            new("beliefs", "Beliefs", "What do you refuse to pretend about?"),
            new("advice", "Advice", "If they only remember one sentence from you, what is it?"),
            new("everyday", "Everyday", "What ordinary thing would you miss if it were gone?"),
        ];
        ApplyChapter();
    }

    public IReadOnlyList<InterviewChapter> Chapters { get; }

    [ObservableProperty] private string _chapterTitle = "";
    [ObservableProperty] private string _prompt = "";
    [ObservableProperty] private string _answer = "";
    [ObservableProperty] private string _progress = "";
    [ObservableProperty] private string _status = "A biographer that already knows you — if you answer.";

    [RelayCommand]
    public void NextChapter()
    {
        _index = (_index + 1) % Chapters.Count;
        ApplyChapter();
    }

    [RelayCommand]
    public void PreviousChapter()
    {
        _index = (_index - 1 + Chapters.Count) % Chapters.Count;
        ApplyChapter();
    }

    [RelayCommand]
    public void Skip()
    {
        var left = Chapters[_index].Title;
        NextChapter();
        Status = "Left " + left + ". Still here for another sitting — not a miss.";
    }

    [RelayCommand]
    public void FileAnswer()
    {
        if (!_host.CanEdit)
        {
            Status = "Heir mode. Filing is locked.";
            return;
        }

        if (string.IsNullOrWhiteSpace(Answer))
        {
            Status = "Write the answer, or Skip.";
            return;
        }

        var chapter = Chapters[_index];
        _host.Vault.AddCapture("interview", $"{chapter.Prompt}\n{Answer.Trim()}", chapter.Id);
        Answer = "";
        Status = "Filed this chapter. The twin may cite it — it will not invent it.";
        NextChapter();
    }

    private void ApplyChapter()
    {
        var chapter = Chapters[_index];
        ChapterTitle = chapter.Title;
        Prompt = chapter.Prompt;
        Progress = $"Chapter {_index + 1} of {Chapters.Count}";
    }
}

public partial class PhotosViewModel : ObservableObject
{
    private readonly AppHost _host;

    public PhotosViewModel(AppHost host)
    {
        _host = host;
        Reload();
    }

    public ObservableCollection<ArchiveEntry> Stories { get; } = [];

    [ObservableProperty] private string _who = "";
    [ObservableProperty] private string _when = "";
    [ObservableProperty] private string _caption = "";
    [ObservableProperty] private string _question = "What happened just after this was taken?";
    [ObservableProperty] private string _status = "Photo → story. Three facts beat a pretty guess.";

    public IReadOnlyList<string> Questions { get; } =
    [
        "What happened just after this was taken?",
        "Who is just out of frame?",
        "If they could hear you now, what would you tell them about this day?",
    ];

    [RelayCommand]
    public void NextQuestion()
    {
        var i = Questions.ToList().IndexOf(Question);
        Question = Questions[(i + 1) % Questions.Count];
    }

    [RelayCommand]
    public void FileStory()
    {
        if (string.IsNullOrWhiteSpace(Caption) || !_host.CanEdit)
        {
            return;
        }

        var body = $"Who: {Who}\nWhen: {When}\n{Question}\n{Caption.Trim()}";
        _host.Vault.AddCapture("photo_story", body, Who);
        Caption = "";
        Status = "Story filed. The twin can retrieve this photo's truth.";
        Reload();
    }

    [RelayCommand]
    public void Reload()
    {
        Stories.Clear();
        foreach (var row in _host.Vault.Recent(30, "photo_story"))
        {
            Stories.Add(new ArchiveEntry(row.Tag.Length == 0 ? "photo" : row.Tag, row.Text, row.Created, row.Kind, row.Tag));
        }
    }
}

public partial class ImportViewModel : ObservableObject
{
    private readonly AppHost _host;

    public ImportViewModel(AppHost host) => _host = host;

    public IReadOnlyList<string> Kinds { get; } = ["import", "memoir", "note", "letter"];

    [ObservableProperty] private string _draft = "";
    [ObservableProperty] private string _kind = "import";
    [ObservableProperty] private string _sourceLabel = "pasted";
    [ObservableProperty] private string _status = "Paste a life. Tag the source so retrieval stays honest.";

    [RelayCommand]
    public void FilePaste()
    {
        if (string.IsNullOrWhiteSpace(Draft) || !_host.CanEdit)
        {
            return;
        }

        _host.Vault.AddCapture(Kind, Draft.Trim(), SourceLabel);
        Draft = "";
        Status = "Filed into the local vault.";
    }
}

public partial class SourcesViewModel : ObservableObject
{
    public SourcesViewModel()
    {
    }

    [ObservableProperty] private bool _allowMail;
    [ObservableProperty] private bool _allowPhotos = true;
    [ObservableProperty] private bool _allowMessages;
    [ObservableProperty] private bool _allowFiles = true;
    [ObservableProperty] private string _status = "Local vault is always on. Cloud sources are opt-in.";

    public string Policy =>
        "The twin may learn from: "
        + string.Join(", ", new[]
        {
            AllowFiles ? "files" : null,
            AllowPhotos ? "photos" : null,
            AllowMail ? "mail" : null,
            AllowMessages ? "messages" : null,
            "this PC vault",
        }.Where(s => s is not null));
}

public partial class ContinuityViewModel : ObservableObject
{
    private readonly AppHost _host;

    public ContinuityViewModel(AppHost host)
    {
        _host = host;
        Reload();
    }

    public ObservableCollection<ArchiveEntry> Heirs { get; } = [];
    public ObservableCollection<ArchiveEntry> Letters { get; } = [];
    public IReadOnlyList<string> Triggers { get; } = ["after_release", "birthday", "when_ready", "executor_unlock"];

    [ObservableProperty] private string _heirName = "";
    [ObservableProperty] private string _heirRelation = "";
    [ObservableProperty] private bool _heirConsent;
    [ObservableProperty] private string _letterTitle = "";
    [ObservableProperty] private string _letterBody = "";
    [ObservableProperty] private string _letterFor = "";
    [ObservableProperty] private string _letterTrigger = "after_release";
    [ObservableProperty] private string _exportPath = "";
    [ObservableProperty] private bool _heirMode;
    [ObservableProperty] private string _executorNote = "An executor can lock release. Heirs cannot edit the dead.";

    public bool CanEdit => !HeirMode;

    [RelayCommand]
    public void Reload()
    {
        Letters.Clear();
        foreach (var letter in _host.Vault.Letters())
        {
            Letters.Add(new ArchiveEntry(
                letter.Title,
                letter.Body,
                (letter.Sealed ? "sealed" : "draft") + "  ·  " + letter.Trigger + (string.IsNullOrWhiteSpace(letter.ForPerson) ? "" : "  ·  " + letter.ForPerson)));
        }

        Heirs.Clear();
        foreach (var heir in _host.Vault.Heirs())
        {
            Heirs.Add(new ArchiveEntry(
                heir.Name,
                heir.Relation,
                heir.Consent ? "consented" : "awaiting consent"));
        }

        HeirMode = string.Equals(_host.Settings.Current.AppMode, "heir", StringComparison.OrdinalIgnoreCase);
    }

    [RelayCommand]
    public void AddHeir()
    {
        if (string.IsNullOrWhiteSpace(HeirName) || HeirMode)
        {
            return;
        }

        var name = HeirName.Trim();
        var consented = HeirConsent;
        _host.Vault.AddHeir(name, HeirRelation.Trim(), consented);
        HeirName = "";
        HeirRelation = "";
        HeirConsent = false;
        Reload();
        ExecutorNote = consented
            ? name + " filed. Consent is on."
            : name + " filed. Consent is off — they have not agreed to receive this.";
    }

    [RelayCommand]
    public void AddLetter()
    {
        if (string.IsNullOrWhiteSpace(LetterTitle) || HeirMode)
        {
            return;
        }

        var title = LetterTitle.Trim();
        _host.Vault.AddLetter(title, LetterBody.Trim(), sealedLetter: true, LetterFor.Trim(), LetterTrigger);
        LetterTitle = "";
        LetterBody = "";
        LetterFor = "";
        Reload();
        ExecutorNote = "Sealed “" + title + "”. It is not a draft.";
    }

    [RelayCommand]
    public void Export()
    {
        ExportPath = _host.Vault.ExportArchive();
        ExecutorNote = string.IsNullOrWhiteSpace(ExportPath)
            ? "Export did not write a file."
            : "Copied the vault to " + ExportPath + ".";
    }

    [RelayCommand]
    public void ToggleHeirMode()
    {
        _host.Settings.Current.AppMode = HeirMode ? "owner" : "heir";
        HeirMode = !HeirMode;
        _host.Settings.Save();
        OnPropertyChanged(nameof(CanEdit));
        ExecutorNote = HeirMode
            ? "Heir mode. Talk, listen, read. You cannot edit what they left."
            : "Owner studio. You are still writing the life model.";
    }
}

public partial class PersonalityViewModel : ObservableObject
{
    private readonly AppHost _host;

    public PersonalityViewModel(AppHost host)
    {
        _host = host;
        Notes = host.Settings.Current.PersonalityNotes;
        Values = host.Settings.Current.ValuesNotes;
        Persona = host.Settings.Current.TwinPersona;
    }

    [ObservableProperty] private string _notes;
    [ObservableProperty] private string _values;
    [ObservableProperty] private string _persona;
    [ObservableProperty] private string _status = "Portrait the twin must not outrun.";

    [RelayCommand]
    public void Save()
    {
        if (!_host.CanEdit)
        {
            Status = "Heir mode. Portrait is already filed.";
            return;
        }

        _host.Settings.Current.PersonalityNotes = Notes;
        _host.Settings.Current.ValuesNotes = Values;
        _host.Settings.Current.TwinPersona = Persona;
        _host.Settings.Save();
        if (!string.IsNullOrWhiteSpace(Notes))
        {
            _host.Vault.AddCapture("memoir", "Personality: " + Notes.Trim(), "portrait");
        }

        if (!string.IsNullOrWhiteSpace(Values))
        {
            _host.Vault.AddCapture("memoir", "Values: " + Values.Trim(), "values");
        }

        Status = "Portrait filed. Grounded replies will prefer this.";
    }
}

public partial class AbilitiesViewModel : ObservableObject
{
    private readonly AppHost _host;

    public AbilitiesViewModel(AppHost host)
    {
        _host = host;
        AllowPc = host.Settings.Current.AllowPcControl;
        AllowSee = host.Settings.Current.AllowSeeScreen;
        AllowSpeak = host.Settings.Current.AllowSpeak;
    }

    [ObservableProperty] private bool _allowPc;
    [ObservableProperty] private bool _allowSee;
    [ObservableProperty] private bool _allowSpeak;
    [ObservableProperty] private string _status = "Each ability is a permission, not a default.";

    [RelayCommand]
    public void Save()
    {
        _host.Settings.Current.AllowPcControl = AllowPc;
        _host.Settings.Current.AllowSeeScreen = AllowSee;
        _host.Settings.Current.AllowSpeak = AllowSpeak;
        _host.Settings.Save();
        Status = "Permissions saved on this PC.";
    }
}

public partial class KeysViewModel : ObservableObject
{
    private readonly AppHost _host;

    public KeysViewModel(AppHost host)
    {
        _host = host;
        HasSession = !string.IsNullOrWhiteSpace(host.Credentials.SessionToken);
        HasDevice = !string.IsNullOrWhiteSpace(host.Credentials.DeviceToken);
    }

    [ObservableProperty] private bool _hasSession;
    [ObservableProperty] private bool _hasDevice;
    [ObservableProperty] private string _hint = "Paste keys into Settings. Heirloom never reads keys off a screenshot or solves a captcha.";

    public string SessionLine => HasSession ? "Owner session on this PC" : "No owner session";
    public string DeviceLine => HasDevice ? "Device paired" : "Not paired yet";
}

public partial class AvatarViewModel : ObservableObject
{
    [ObservableProperty] private string _presence = "listening";
    [ObservableProperty] private string _status = "Presence is the PTT, not a cartoon. Breathing when armed, waveform when capturing.";

    public IReadOnlyList<string> Presences { get; } = ["listening", "thinking", "speaking", "rest"];

    [RelayCommand]
    public void SetPresence(string value)
    {
        Presence = value;
        Status = "Presence · " + value;
    }
}

public partial class SettingsViewModel : ObservableObject
{
    private readonly AppHost _host;
    private bool _applying;

    public SettingsViewModel(AppHost host)
    {
        _host = host;
        _applying = true;
        BackendUrl = host.Settings.Current.BackendUrl;
        Autostart = host.Settings.Current.Autostart;
        LibraryPath = host.Settings.Current.LibraryPath;
        VersionLine = $"Heirloom {host.Version}  ·  {host.BuildId}  ·  Unbound Infotech";
        SelectedScheme = ThemeService.Schemes.First(s => s.Id == ThemeService.NormalizeScheme(host.Settings.Current.ColorScheme));
        SelectedChrome = ThemeService.ChromeModes.First(s => s.Id == ThemeService.NormalizeMode(host.Settings.Current.ChromeMode));
        SelectedDockEdge = ThemeService.DockEdges.First(s => s.Id == ThemeService.NormalizeEdge(host.Settings.Current.DockEdge));
        DockSize = host.Settings.Current.DockSize <= 0 ? 188 : host.Settings.Current.DockSize;
        DockLocked = host.Settings.Current.DockLocked;
        InspectorOpen = host.Settings.Current.InspectorOpen;
        InspectorWidth = host.Settings.Current.InspectorWidth <= 0 ? 292 : host.Settings.Current.InspectorWidth;
        ChromeFolder = AppPaths.ChromeButtons;
        ChromeHint = SelectedScheme.Hint;
        _applying = false;
    }

    public IReadOnlyList<ChromeChoice> Schemes => ThemeService.Schemes;
    public IReadOnlyList<ChromeChoice> ChromeModes => ThemeService.ChromeModes;
    public IReadOnlyList<ChromeChoice> DockEdges => ThemeService.DockEdges;

    [ObservableProperty] private string _backendUrl;
    [ObservableProperty] private string _libraryPath;
    [ObservableProperty] private bool _autostart;
    [ObservableProperty] private string _versionLine;
    [ObservableProperty] private string _sessionToken = "";
    [ObservableProperty] private string _deviceToken = "";
    [ObservableProperty] private ChromeChoice _selectedScheme;
    [ObservableProperty] private ChromeChoice _selectedChrome;
    [ObservableProperty] private ChromeChoice _selectedDockEdge;
    [ObservableProperty] private double _dockSize;
    [ObservableProperty] private bool _dockLocked;
    [ObservableProperty] private bool _inspectorOpen;
    [ObservableProperty] private double _inspectorWidth;
    [ObservableProperty] private string _chromeFolder;
    [ObservableProperty] private string _chromeHint;

    partial void OnSelectedSchemeChanged(ChromeChoice value) => LiveApply();
    partial void OnSelectedChromeChanged(ChromeChoice value) => LiveApply();
    partial void OnSelectedDockEdgeChanged(ChromeChoice value) => LiveApply();
    partial void OnDockSizeChanged(double value) => LiveApply();
    partial void OnDockLockedChanged(bool value) => LiveApply();
    partial void OnInspectorOpenChanged(bool value) => LiveApply();
    partial void OnInspectorWidthChanged(double value) => LiveApply();

    public void SetDockEdge(string edge)
    {
        _applying = true;
        var next = ThemeService.NormalizeEdge(edge);
        SelectedDockEdge = ThemeService.DockEdges.First(s => s.Id == next);
        if (next == "top" && DockSize > 96)
        {
            DockSize = 72;
        }
        else if (next != "top" && DockSize < 120)
        {
            DockSize = 188;
        }

        _applying = false;
        LiveApply();
    }

    public void SetDockSize(double size)
    {
        _applying = true;
        DockSize = Math.Clamp(size, 56, 280);
        _applying = false;
        LiveApply();
    }

    private void LiveApply()
    {
        if (_applying || SelectedScheme is null || SelectedChrome is null || SelectedDockEdge is null)
        {
            return;
        }

        ChromeHint = SelectedScheme.Hint + "  ·  " + SelectedChrome.Hint;
        WriteChrome();
        ThemeService.Apply(_host.Settings.Current);
        QueueSave();
    }

    private void WriteChrome()
    {
        _host.Settings.Current.ColorScheme = SelectedScheme.Id;
        _host.Settings.Current.ChromeMode = SelectedChrome.Id;
        _host.Settings.Current.DockEdge = SelectedDockEdge.Id;
        _host.Settings.Current.DockSize = DockSize;
        _host.Settings.Current.DockLocked = DockLocked;
        _host.Settings.Current.InspectorOpen = InspectorOpen;
        _host.Settings.Current.InspectorWidth = InspectorWidth;
    }

    public void SetInspectorWidth(double width)
    {
        _applying = true;
        InspectorWidth = Math.Clamp(width, 220, 480);
        _applying = false;
        LiveApply();
    }

    public void SetInspectorOpen(bool open)
    {
        _applying = true;
        InspectorOpen = open;
        _applying = false;
        LiveApply();
    }

    private void QueueSave()
    {
        UiDispatch.Post(() => _host.Settings.Save());
    }

    [RelayCommand]
    public void Save()
    {
        _host.Settings.Current.BackendUrl = BackendUrl.Trim();
        _host.Settings.Current.LibraryPath = LibraryPath.Trim();
        _host.Settings.Current.Autostart = Autostart;
        WriteChrome();
        _host.Settings.Save();
        ThemeService.Apply(_host.Settings.Current);
        AutostartService.Apply(Autostart);
        if (!string.IsNullOrWhiteSpace(SessionToken))
        {
            _host.Auth.SetSessionToken(SessionToken);
        }

        if (!string.IsNullOrWhiteSpace(DeviceToken))
        {
            _host.Auth.SetDeviceToken(DeviceToken);
        }
    }

    [RelayCommand]
    public void OpenChromeFolder()
    {
        ThemeService.EnsureChromeFolder();
        System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo(AppPaths.ChromeButtons)
        {
            UseShellExecute = true,
        });
    }

    [RelayCommand]
    public void SignOut() => _host.Auth.SignOut();

    [RelayCommand]
    public void ReopenSetup()
    {
        _host.Settings.Current.SetupComplete = false;
        _host.Settings.Current.SetupSkipped = false;
        _host.Settings.Save();
    }
}

public sealed class KitchenSinkViewModel
{
    public string Hero => "Every control in the kit. If it looks cheap here, it ships cheap.";
}

public partial class GlossaryViewModel : ObservableObject
{
    public GlossaryViewModel()
    {
        Results = [.. StudioLexicon.Terms];
    }

    public IReadOnlyList<string> Kinds { get; } = ["All", "Terms", "Documents", "Actions", "Chrome"];

    [ObservableProperty] private string _query = "";
    [ObservableProperty] private string _kind = "Terms";
    [ObservableProperty] private HelpTopic? _selected;
    [ObservableProperty] private string _status = "Words this studio uses. Search or click a row.";

    public ObservableCollection<HelpTopic> Results { get; }

    public string SelectedTitle => Selected?.Title ?? "Pick a word";
    public string SelectedSummary => Selected?.Summary ?? "Search or click the list.";
    public string SelectedBody => Selected?.Body ?? "Hover still updates the right inspector. Pin a topic there if you want it to stay.";

    partial void OnQueryChanged(string value) => Reload();
    partial void OnKindChanged(string value) => Reload();
    partial void OnSelectedChanged(HelpTopic? value)
    {
        OnPropertyChanged(nameof(SelectedTitle));
        OnPropertyChanged(nameof(SelectedSummary));
        OnPropertyChanged(nameof(SelectedBody));
        if (value is not null)
        {
            StudioHelp.ShowTopic(value.Id);
            Status = value.Kind + "  ·  " + value.Title;
        }
    }

    private void Reload()
    {
        IEnumerable<HelpTopic> source = Kind switch
        {
            "Documents" => StudioLexicon.All.Where(t => t.Kind == "document"),
            "Actions" => StudioLexicon.All.Where(t => t.Kind == "action"),
            "Chrome" => StudioLexicon.All.Where(t => t.Kind == "chrome"),
            "All" => StudioLexicon.Search(Query),
            _ => StudioLexicon.Search(Query).Where(t => t.Kind == "term"),
        };

        if (Kind is not "All" and not "Terms" && Query.Trim().Length > 0)
        {
            source = StudioLexicon.Search(Query).Where(t => Kind switch
            {
                "Documents" => t.Kind == "document",
                "Actions" => t.Kind == "action",
                "Chrome" => t.Kind == "chrome",
                _ => true,
            });
        }

        Results.Clear();
        foreach (var row in source.DistinctBy(t => t.Id).OrderBy(t => t.Title, StringComparer.OrdinalIgnoreCase))
        {
            Results.Add(row);
        }

        Status = Results.Count + " entries";
    }
}

public partial class SkillsViewModel : ObservableObject
{
    private readonly AppHost _host;

    public SkillsViewModel(AppHost host)
    {
        _host = host;
        Reload();
    }

    public ObservableCollection<ArchiveEntry> Items { get; } = [];

    [ObservableProperty] private string _name = "";
    [ObservableProperty] private string _url = "";
    [ObservableProperty] private string _triggers = "";
    [ObservableProperty] private string _status = "Webhooks the twin can fire — porch light, text, OBS scene.";

    [RelayCommand]
    public void Reload()
    {
        Items.Clear();
        foreach (var row in _host.Vault.Skills())
        {
            Items.Add(new ArchiveEntry(row.Name, row.Url, row.Triggers, "skill", row.Id.ToString()));
        }

        Status = Items.Count == 0
            ? "No skills yet. A skill is a URL the twin may call when you say the trigger."
            : Items.Count + " skills on this PC";
    }

    [RelayCommand]
    public void Add()
    {
        if (string.IsNullOrWhiteSpace(Name) || string.IsNullOrWhiteSpace(Url) || !_host.CanEdit)
        {
            return;
        }

        _host.Vault.AddSkill(Name.Trim(), Url.Trim(), Triggers.Trim());
        Name = "";
        Url = "";
        Triggers = "";
        Reload();
    }

    [RelayCommand]
    public async Task InvokeAsync(string? id)
    {
        if (!long.TryParse(id, out var skillId))
        {
            return;
        }

        var skill = _host.Vault.Skills().FirstOrDefault(s => s.Id == skillId);
        if (skill.Url.Length == 0)
        {
            return;
        }

        try
        {
            using var http = new HttpClient { Timeout = TimeSpan.FromSeconds(20) };
            var response = await http.PostAsync(skill.Url, new StringContent("{\"source\":\"heirloom\"}")).ConfigureAwait(true);
            Status = skill.Name + "  ·  HTTP " + (int)response.StatusCode;
        }
        catch (Exception ex)
        {
            Status = skill.Name + "  ·  " + ex.Message;
        }
    }
}

public partial class LibraryViewModel : ObservableObject
{
    private readonly AppHost _host;

    public LibraryViewModel(AppHost host)
    {
        _host = host;
        Reload();
    }

    public ObservableCollection<ArchiveEntry> Items { get; } = [];

    [ObservableProperty] private string _path = "";
    [ObservableProperty] private string _status = "";

    [RelayCommand]
    public void Reload()
    {
        Path = _host.Vault.RootPath;
        Items.Clear();
        foreach (var row in _host.Vault.Recent(30))
        {
            Items.Add(new ArchiveEntry(row.Kind, row.Text, row.Created, row.Kind, row.Tag));
        }

        var stats = _host.Vault.Stats();
        Status = $"{stats.Captures} memories on this PC  ·  {Path}";
    }
}
