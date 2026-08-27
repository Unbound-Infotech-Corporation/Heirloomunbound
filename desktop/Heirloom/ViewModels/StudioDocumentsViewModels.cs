using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using Heirloom.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Media.Imaging;
using Windows.Media.Core;

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
    public ObservableCollection<ArchiveEntry> Recent { get; } = [];

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
        Recent.Clear();
        foreach (var row in _host.Vault.Recent(5))
        {
            Recent.Add(new ArchiveEntry(row.Kind, row.Text, row.Created, row.Kind, row.Tag));
        }
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
            new("humor", "Humor", "What made you laugh, and what jokes did you never tell?"),
            new("speech", "How you spoke", "How did you actually talk — pace, swearing, nicknames, the phrases you repeated?"),
            new("joys", "Joys", "What ordinary thing made a day worth it?"),
            new("regrets", "Regrets", "What do you wish you had said, or not said, while there was time?"),
            new("advice", "Advice", "If they only remember one sentence from you, what is it?"),
            new("instructions", "Family instructions", "What should they do with money, the house, the holidays, and each other — in your words, not a lawyer's?"),
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
        Status = "Filed " + chapter.Title + ". The twin may cite it — it will not invent it.";
        NextChapter();
    }

    public void ApplyChapter()
    {
        var chapter = Chapters[_index];
        ChapterTitle = chapter.Title;
        Prompt = chapter.Prompt;
        var filed = _host.Vault.Recent(80, "interview")
            .Select(r => r.Tag)
            .Where(t => t.Length > 0)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();
        var already = filed.Contains(chapter.Id, StringComparer.OrdinalIgnoreCase) ? " · already filed" : "";
        Progress = $"Chapter {_index + 1} of {Chapters.Count}{already}";
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
    [ObservableProperty] private string _photoPath = "";
    [ObservableProperty] private string _photoLine = "No photograph filed.";
    [ObservableProperty] private BitmapImage? _photoImage;
    [ObservableProperty] private string _question = "What happened just after this was taken?";
    [ObservableProperty] private string _status = "File the photograph, then the three facts. A caption without the picture is still a guess.";

    public bool HasPhoto => File.Exists(PhotoPath);

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
    public async Task FilePhotoAsync()
    {
        if (!_host.CanEdit)
        {
            Status = "Heir mode. Filing is locked.";
            return;
        }

        var destDir = Path.Combine(_host.Vault.RootPath, "photos");
        var path = await StudioPickers.CopyAsync([".jpg", ".jpeg", ".png", ".webp", ".heic"], destDir, DateTime.UtcNow.ToString("yyyyMMdd-HHmmss"), pictures: true).ConfigureAwait(true);
        if (path is null)
        {
            Status = "No photograph picked.";
            return;
        }

        PhotoPath = path;
        PhotoLine = Path.GetFileName(path);
        PhotoImage = new BitmapImage(new Uri(path));
        OnPropertyChanged(nameof(HasPhoto));
        Status = "Photograph filed on this PC. Who, when, and what is true — then File story.";
    }

    [RelayCommand]
    public void FileStory()
    {
        if (!_host.CanEdit)
        {
            Status = "Heir mode. Filing is locked.";
            return;
        }

        if (string.IsNullOrWhiteSpace(Caption))
        {
            Status = "Write what is true in the picture, then File story.";
            return;
        }

        var body = $"Photo: {(string.IsNullOrWhiteSpace(PhotoPath) ? "(none on disk)" : PhotoPath)}\nWho: {Who}\nWhen: {When}\n{Question}\n{Caption.Trim()}";
        _host.Vault.AddCapture("photo_story", body, Who.Trim());
        Caption = "";
        Status = "Story filed. Ask the twin about this day — it can retrieve it.";
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
        if (!_host.CanEdit)
        {
            Status = "Heir mode. Filing is locked.";
            return;
        }

        if (string.IsNullOrWhiteSpace(Draft))
        {
            Status = "Paste the life first, then File into vault.";
            return;
        }

        _host.Vault.AddCapture(Kind, Draft.Trim(), SourceLabel);
        Draft = "";
        Status = "Filed into the local vault. Open Archive or Ask the twin.";
    }

    [RelayCommand]
    public async Task FileFromDiskAsync()
    {
        if (!_host.CanEdit)
        {
            Status = "Heir mode. Filing is locked.";
            return;
        }

        var text = await StudioPickers.ReadTextAsync([".txt", ".md", ".json", ".csv", ".html"]).ConfigureAwait(true);
        if (string.IsNullOrWhiteSpace(text))
        {
            Status = "No file picked, or it was empty.";
            return;
        }

        Draft = text;
        if (string.IsNullOrWhiteSpace(SourceLabel) || SourceLabel == "pasted")
        {
            SourceLabel = "disk";
        }

        Status = "Loaded from disk. File into vault to keep it.";
    }
}

public partial class SourcesViewModel : ObservableObject
{
    private readonly AppHost _host;
    private bool _ready;

    public SourcesViewModel(AppHost host)
    {
        _host = host;
        AllowMail = host.Settings.Current.SourceAllowMail;
        AllowPhotos = host.Settings.Current.SourceAllowPhotos;
        AllowMessages = host.Settings.Current.SourceAllowMessages;
        AllowFiles = host.Settings.Current.SourceAllowFiles;
        _ready = true;
        Status = Policy;
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

    partial void OnAllowMailChanged(bool value) => Persist();
    partial void OnAllowPhotosChanged(bool value) => Persist();
    partial void OnAllowMessagesChanged(bool value) => Persist();
    partial void OnAllowFilesChanged(bool value) => Persist();

    private void Persist()
    {
        if (!_ready)
        {
            return;
        }

        _host.Settings.Current.SourceAllowMail = AllowMail;
        _host.Settings.Current.SourceAllowPhotos = AllowPhotos;
        _host.Settings.Current.SourceAllowMessages = AllowMessages;
        _host.Settings.Current.SourceAllowFiles = AllowFiles;
        _host.Settings.Save();
        Status = Policy + "  ·  filed on this PC.";
        OnPropertyChanged(nameof(Policy));
    }
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
        _host.RaiseAppModeChanged();
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
        ReloadFacts();
    }

    public ObservableCollection<ArchiveEntry> Facts { get; } = [];

    [ObservableProperty] private string _notes;
    [ObservableProperty] private string _values;
    [ObservableProperty] private string _persona;
    [ObservableProperty] private string _status = "Portrait the twin must not outrun.";
    [ObservableProperty] private ArchiveEntry? _selectedFact;

    [RelayCommand]
    public void ReloadFacts()
    {
        Facts.Clear();
        foreach (var fact in _host.Vault.ListFacts())
        {
            Facts.Add(new ArchiveEntry(
                fact.Fact,
                fact.Kind + " #" + fact.SourceCaptureId,
                "source capture " + fact.SourceCaptureId,
                fact.Kind,
                fact.Id.ToString()));
        }

        if (Facts.Count == 0)
        {
            Status = "No fact index yet. Rebuild from the vault after you file interviews.";
        }
    }

    [RelayCommand]
    public void RebuildFacts()
    {
        if (!_host.CanEdit)
        {
            Status = "Heir mode. The index is locked.";
            return;
        }

        var n = _host.Vault.RebuildFacts();
        ReloadFacts();
        Status = n == 0
            ? "Nothing durable to index. File an interview or journal first."
            : "Indexed " + n + " facts from filed captures. Each points at a source.";
    }

    [RelayCommand]
    public void DeleteSelectedFact()
    {
        if (!_host.CanEdit)
        {
            Status = "Heir mode. The index is locked.";
            return;
        }

        if (SelectedFact is null || !long.TryParse(SelectedFact.Tag, out var id) || !_host.Vault.DeleteFact(id))
        {
            Status = "Select a fact, then delete it. The source capture stays.";
            return;
        }

        ReloadFacts();
        Status = "Removed that index row. The source capture is still in the vault.";
    }

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
        if (!_host.CanEdit)
        {
            Status = "Heir mode. Permissions stay as the owner left them.";
            return;
        }

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

    [RelayCommand]
    public void Refresh()
    {
        HasSession = !string.IsNullOrWhiteSpace(_host.Credentials.SessionToken);
        HasDevice = !string.IsNullOrWhiteSpace(_host.Credentials.DeviceToken);
        OnPropertyChanged(nameof(SessionLine));
        OnPropertyChanged(nameof(DeviceLine));
    }

    [RelayCommand]
    public async Task TestAsync()
    {
        Refresh();
        var reached = await _host.Api.GetSessionAsync("/health").ConfigureAwait(true)
            ?? await _host.Api.GetAsync("/companion/winui").ConfigureAwait(true);
        Hint = reached is null
            ? "No answer from " + _host.Settings.Current.BackendUrl + ". Check the URL and tokens in Settings."
            : "Reached " + _host.Settings.Current.BackendUrl + ".";
        StatusLineFromHint();
    }

    private void StatusLineFromHint()
    {
        OnPropertyChanged(nameof(SessionLine));
        OnPropertyChanged(nameof(DeviceLine));
    }
}

public sealed class VideoShotRow
{
    public VideoShotRow(VideoShotPlan plan)
    {
        Plan = plan;
        BeatLine = VideoCatalog.ShotKindLabel(plan.Kind) + "  ·  " + plan.Seconds + "s  ·  " + plan.Title;
        ScriptLine = string.IsNullOrWhiteSpace(plan.Script) ? "No line on this beat." : plan.Script;
        PhotoLine = string.IsNullOrWhiteSpace(plan.ImagePath)
            ? (plan.Kind is VideoShotKind.PhotoHold or VideoShotKind.ImageToVideo
                ? "Needs a photograph from Photos or this likeness room."
                : "")
            : Path.GetFileName(plan.ImagePath);
        ModelLine = plan.ModelId switch
        {
            "latentsync" => "Talking likeness",
            "ltx" => "LTX when present, else living still",
            "wan22-i2v" or "wan22-5b" => "Wan when present, else living still",
            _ => "Living still",
        };
    }

    public VideoShotPlan Plan { get; }
    public string BeatLine { get; }
    public string ScriptLine { get; }
    public string PhotoLine { get; }
    public string ModelLine { get; }
}

public sealed class AvatarPhotoItem
{
    public AvatarPhotoItem(
        string path,
        BitmapImage image,
        bool usable,
        int shortSide,
        string fit,
        IRelayCommand<AvatarPhotoItem> removeCommand)
    {
        Path = path;
        Image = image;
        Usable = usable;
        ShortSide = shortSide;
        Fit = fit;
        RemoveCommand = removeCommand;
    }

    public string Path { get; }
    public BitmapImage Image { get; }
    public bool Usable { get; }
    public int ShortSide { get; }
    public string Fit { get; }
    public IRelayCommand<AvatarPhotoItem> RemoveCommand { get; }
}

public partial class AvatarViewModel : ObservableObject
{
    private static readonly string[] PhotoTypes = [".jpg", ".jpeg", ".png", ".webp", ".bmp"];
    private static readonly string[] VideoTypes = [".mp4", ".mov", ".mkv", ".webm", ".wmv"];
    private readonly AppHost _host;
    private CancellationTokenSource? _work;

    public AvatarViewModel(AppHost host)
    {
        _host = host;
        AppPaths.EnsureDirectories();
        SittingPath = host.Settings.Current.AvatarSittingPath ?? "";
        GeneratedPath = host.Settings.Current.AvatarGeneratedPath ?? "";
        FilmPath = host.Settings.Current.VideoFilmPath ?? "";
        LineToSpeak = string.IsNullOrWhiteSpace(host.Settings.Current.AvatarLine)
            ? "This is my voice, in this room."
            : host.Settings.Current.AvatarLine;
        SelectedPreset = VideoCatalog.ById(host.Settings.Current.VideoPresetId);
        RefreshStatus();
        RebuildShots();
        _ = RefreshEnginesAsync();
    }

    public ObservableCollection<AvatarPhotoItem> Photos { get; } = [];
    public ObservableCollection<VideoShotRow> Shots { get; } = [];
    public IReadOnlyList<VideoPreset> Presets => VideoCatalog.Presets;
    public IReadOnlyList<VideoModelChoice> Models => VideoCatalog.Models;

    [ObservableProperty] private string _sittingPath = "";
    [ObservableProperty] private string _generatedPath = "";
    [ObservableProperty] private string _lineToSpeak = "";
    [ObservableProperty] private string _status = "";
    [ObservableProperty] private string _engineLine = "";
    [ObservableProperty] private string _sittingLine = "No sitting clip filed.";
    [ObservableProperty] private string _photoLine = "No photos yet.";
    [ObservableProperty] private string _generatedLine = "No live version yet.";
    [ObservableProperty] private bool _isBusy;
    [ObservableProperty] private MediaSource? _sittingSource;
    [ObservableProperty] private MediaSource? _generatedSource;
    [ObservableProperty] private MediaSource? _filmSource;
    [ObservableProperty] private string _filmPath = "";
    [ObservableProperty] private string _filmLine = "No film yet.";
    [ObservableProperty] private string _recommendLine = "";
    [ObservableProperty] private string _shotCountLine = "No shots yet.";
    [ObservableProperty] private VideoPreset _selectedPreset = VideoCatalog.Presets[0];
    [ObservableProperty] private int _paneIndex;
    [ObservableProperty] private bool _canOfferExport;

    public bool HasPhotos => Photos.Count > 0;
    public bool NeedsPhotos => Photos.Count == 0;
    public bool HasUsablePhoto => Photos.Any(p => p.Usable);
    public bool HasSitting => File.Exists(SittingPath);
    public bool HasGenerated => File.Exists(GeneratedPath);
    public bool NeedsLikeness => !HasGenerated;
    public bool HasFilm => File.Exists(FilmPath);
    public bool HasShots => Shots.Count > 0;
    public Visibility LikenessVis => PaneIndex == 0 ? Visibility.Visible : Visibility.Collapsed;
    public Visibility FilmVis => PaneIndex == 1 ? Visibility.Visible : Visibility.Collapsed;
    public Visibility EnginesVis => PaneIndex == 2 ? Visibility.Visible : Visibility.Collapsed;

    private IEnumerable<string> PhotoCandidates =>
        Photos.OrderByDescending(p => p.Usable).ThenByDescending(p => p.ShortSide).Select(p => p.Path).Where(File.Exists);

    partial void OnIsBusyChanged(bool value)
    {
        GenerateCommand.NotifyCanExecuteChanged();
        EnsureEngineCommand.NotifyCanExecuteChanged();
        StopWorkCommand.NotifyCanExecuteChanged();
        MakeFilmCommand.NotifyCanExecuteChanged();
        ExportFilmCommand.NotifyCanExecuteChanged();
    }

    partial void OnPaneIndexChanged(int value)
    {
        OnPropertyChanged(nameof(LikenessVis));
        OnPropertyChanged(nameof(FilmVis));
        OnPropertyChanged(nameof(EnginesVis));
        if (value == 2)
        {
            _ = RefreshEnginesAsync();
        }
    }

    partial void OnSelectedPresetChanged(VideoPreset value)
    {
        if (value is null)
        {
            return;
        }

        _host.Settings.Current.VideoPresetId = value.Id;
        _host.Settings.Save();
        if (string.IsNullOrWhiteSpace(LineToSpeak) || LineToSpeak == "This is my voice, in this room.")
        {
            LineToSpeak = value.DefaultScript;
        }

        RebuildShots();
    }

    partial void OnLineToSpeakChanged(string value)
    {
        _host.Settings.Current.AvatarLine = value ?? "";
        GenerateCommand.NotifyCanExecuteChanged();
        if (!IsBusy)
        {
            RebuildShots();
        }
    }

    public void Reload()
    {
        RefreshStatus();
        RebuildShots();
        _ = RefreshEnginesAsync();
    }

    [RelayCommand]
    public async Task FilePhotosAsync()
    {
        try
        {
            var destDir = Path.Combine(AppPaths.AvatarRoot, "photos");
            var paths = await StudioPickers.CopyManyAsync(PhotoTypes, destDir, pictures: true).ConfigureAwait(true);
            if (paths.Count == 0)
            {
                Status = "No photo picked. If a dialog did not open, try Add photos of you again.";
                return;
            }

            foreach (var dest in paths)
            {
                if (Photos.Count >= 24)
                {
                    break;
                }

                Photos.Add(ItemFrom(dest));
            }

            PersistPhotos();
            RefreshStatus();
            var usable = Photos.Count(p => p.Usable);
            Status = usable == 0
                ? $"{Photos.Count} photo(s) filed, but none are a face-on original yet. See WHAT TO FILE — chat thumbs, group shots, and far landscapes will not lock a mouth."
                : usable == Photos.Count
                    ? $"{Photos.Count} photos filed. Write a line and Make live version."
                    : $"{usable} of {Photos.Count} look large enough. Remove the others or add a head-and-shoulders original of you alone.";
        }
        catch (Exception ex)
        {
            Status = "Could not add photos: " + ex.Message;
        }
    }

    [RelayCommand]
    public void RemovePhoto(AvatarPhotoItem? item)
    {
        if (item is null)
        {
            return;
        }

        Photos.Remove(item);
        TryDeleteOwned(item.Path);
        PersistPhotos();
        RefreshStatus();
    }

    [RelayCommand]
    public async Task FileSittingAsync()
    {
        SittingSource?.Dispose();
        SittingSource = null;
        var paths = await StudioPickers.CopyManyAsync(VideoTypes, AppPaths.AvatarRoot, pictures: false).ConfigureAwait(true);
        if (paths.Count == 0)
        {
            RefreshStatus();
            return;
        }

        SittingPath = paths[0];
        _host.Settings.Current.AvatarSittingPath = SittingPath;
        _host.Settings.Save();
        RefreshStatus();
    }

    private bool CanGenerate() => !IsBusy;

    [RelayCommand(CanExecute = nameof(CanGenerate))]
    public async Task GenerateAsync()
    {
        if (string.IsNullOrWhiteSpace(LineToSpeak))
        {
            Status = "Write the line the twin should speak, then Make live version.";
            return;
        }

        _work?.Cancel();
        _work = new CancellationTokenSource();
        IsBusy = true;
        var progress = new Progress<string>(msg => Status = msg);
        try
        {
            var visual = await PickVisualAsync(progress, _work.Token).ConfigureAwait(true);
            if (visual is null)
            {
                return;
            }

            var path = await _host.AvatarEngine.GenerateAsync(visual, LineToSpeak, progress, _work.Token).ConfigureAwait(true);
            GeneratedPath = path;
            _host.Settings.Current.AvatarGeneratedPath = path;
            _host.Settings.Current.AvatarLine = LineToSpeak;
            _host.Settings.Save();
            RefreshStatus();
            Status = HasSitting
                ? "Live version filed from your sitting. Twin shows this face; Ask still speaks in Mixer and does not re-lipsync this take."
                : "Live version filed from your photos. Twin shows this face; Ask still speaks in Mixer and does not re-lipsync this take.";
        }
        catch (OperationCanceledException)
        {
            Status = "Stopped.";
        }
        catch (Exception ex)
        {
            Status = ex.Message;
        }
        finally
        {
            IsBusy = false;
        }
    }

    public void ApplyTwinOffer(string script, string presetId)
    {
        PaneIndex = 1;
        if (!string.IsNullOrWhiteSpace(script))
        {
            LineToSpeak = script.Trim();
        }

        SelectedPreset = VideoCatalog.ById(string.IsNullOrWhiteSpace(presetId) ? "answer" : presetId);
        RebuildShots();
        Status = "Film laid out from the Twin. Make film when you are ready. This does not file a memory.";
    }

    [RelayCommand]
    public void ShowFilmPane() => PaneIndex = 1;

    [RelayCommand]
    public void ShowLikenessPane() => PaneIndex = 0;

    [RelayCommand]
    public void ShowEnginesPane() => PaneIndex = 2;

    private bool CanMakeFilm() => !IsBusy && _host.CanEdit;

    [RelayCommand(CanExecute = nameof(CanMakeFilm))]
    public async Task MakeFilmAsync()
    {
        if (!_host.CanEdit)
        {
            Status = "Heir sitting cannot make a new film. Play what was already filed.";
            return;
        }

        RebuildShots();
        if (Shots.Count == 0)
        {
            Status = "Choose a preset first.";
            return;
        }

        _work?.Cancel();
        _work = new CancellationTokenSource();
        IsBusy = true;
        var progress = new Progress<string>(msg => Status = msg);
        try
        {
            Status = "Opening the film…";
            var visual = await PickVisualAsync(progress, _work.Token).ConfigureAwait(true);
            if (visual is null && Shots.Any(s => s.Plan.Kind == VideoShotKind.TalkingHead))
            {
                return;
            }

            var path = await _host.VideoEngine.RenderFilmAsync(
                Shots.Select(s => s.Plan).ToList(),
                visual ?? "",
                progress,
                _work.Token).ConfigureAwait(true);
            FilmPath = path;
            _host.Settings.Current.VideoFilmPath = path;
            _host.Settings.Save();
            RefreshStatus();
            PaneIndex = 1;
            Status = "Done — the film is ready. Export copies it out of Heirloom.";
        }
        catch (OperationCanceledException)
        {
            Status = "Stopped.";
        }
        catch (Exception ex)
        {
            Status = ex.Message;
        }
        finally
        {
            IsBusy = false;
        }
    }

    private bool CanExportFilm() => !IsBusy && HasFilm;

    [RelayCommand(CanExecute = nameof(CanExportFilm))]
    public async Task ExportFilmAsync()
    {
        if (!HasFilm)
        {
            Status = "Make the film first, then Export.";
            return;
        }

        try
        {
            var dest = await StudioPickers.PickSaveMp4Async(SelectedPreset.Id + "-heirloom").ConfigureAwait(true);
            if (string.IsNullOrWhiteSpace(dest))
            {
                Status = "Export cancelled.";
                return;
            }

            File.Copy(FilmPath, dest, overwrite: true);
            Status = "Copied the film to " + dest + ".";
        }
        catch (Exception ex)
        {
            Status = "Could not export: " + ex.Message;
        }
    }

    private void RebuildShots()
    {
        var photos = PhotoCandidates.ToList();
        foreach (var story in _host.Vault.Recent(20, "photo_story"))
        {
            foreach (var path in VideoCatalog.PhotoPathsFromStories([story.Text]))
            {
                if (!photos.Contains(path, StringComparer.OrdinalIgnoreCase))
                {
                    photos.Add(path);
                }
            }
        }

        var probe = _host.VideoEngine.Probe();
        var plans = VideoCatalog.BuildTimeline(
            SelectedPreset ?? VideoCatalog.Presets[0],
            LineToSpeak,
            photos,
            probe.TalkingReady,
            probe.LtxReady,
            probe.WanReady);
        Shots.Clear();
        foreach (var plan in plans)
        {
            Shots.Add(new VideoShotRow(plan));
        }

        ShotCountLine = Shots.Count == 0
            ? "No shots yet."
            : Shots.Count + " shot" + (Shots.Count == 1 ? "" : "s") + " on this film.";
        OnPropertyChanged(nameof(HasShots));
        RecommendLine = probe.RecommendLine;
    }

    private async Task RefreshEnginesAsync()
    {
        try
        {
            var probe = await _host.VideoEngine.ProbeAsync(CancellationToken.None).ConfigureAwait(true);
            RecommendLine = probe.RecommendLine;
            EngineLine = probe.TalkingReady
                ? "Talking likeness ready. " + probe.RecommendLine
                : probe.RecommendLine;
        }
        catch
        {
            RecommendLine = VideoCatalog.RecommendLine(false, false, false, false, false);
        }
    }

    private bool CanStopWork() => IsBusy;

    [RelayCommand(CanExecute = nameof(CanStopWork))]
    public void StopWork()
    {
        _work?.Cancel();
        Status = "Stopping this take.";
    }

    private bool CanEnsureEngine() => !IsBusy;

    [RelayCommand(CanExecute = nameof(CanEnsureEngine))]
    public async Task EnsureEngineAsync()
    {
        _work?.Cancel();
        _work = new CancellationTokenSource();
        IsBusy = true;
        var progress = new Progress<string>(msg => Status = msg);
        try
        {
            await _host.AvatarEngine.EnsureAsync(progress, _work.Token).ConfigureAwait(true);
            RefreshStatus();
            Status = EngineLine;
        }
        catch (OperationCanceledException)
        {
            Status = "Stopped.";
        }
        catch (Exception ex)
        {
            Status = ex.Message;
        }
        finally
        {
            IsBusy = false;
        }
    }

    private void RefreshStatus()
    {
        ReloadPhotosFromDisk();
        OnPropertyChanged(nameof(HasPhotos));
        OnPropertyChanged(nameof(NeedsPhotos));
        OnPropertyChanged(nameof(HasUsablePhoto));
        OnPropertyChanged(nameof(HasSitting));
        OnPropertyChanged(nameof(HasGenerated));
        OnPropertyChanged(nameof(NeedsLikeness));
        OnPropertyChanged(nameof(HasFilm));
        GenerateCommand.NotifyCanExecuteChanged();
        StopWorkCommand.NotifyCanExecuteChanged();
        MakeFilmCommand.NotifyCanExecuteChanged();
        ExportFilmCommand.NotifyCanExecuteChanged();
        PhotoLine = !HasPhotos
            ? "No photos yet."
            : HasUsablePhoto
                ? $"{Photos.Count(p => p.Usable)} of {Photos.Count} look large enough. Remove tiny crops and group shots."
                : $"{Photos.Count} filed — none are a face-on original yet.";
        SittingLine = HasSitting
            ? Path.GetFileName(SittingPath)
            : "Stronger than stills: 1–2 minutes of you talking in a real room, face filling the frame, looking at the lens.";
        GeneratedLine = HasGenerated ? Path.GetFileName(GeneratedPath) : "No live version yet.";
        SittingSource?.Dispose();
        SittingSource = HasSitting ? MediaSource.CreateFromUri(new Uri(SittingPath)) : null;
        GeneratedSource?.Dispose();
        GeneratedSource = HasGenerated ? MediaSource.CreateFromUri(new Uri(GeneratedPath)) : null;
        FilmLine = HasFilm ? Path.GetFileName(FilmPath) : "No film yet.";
        FilmSource?.Dispose();
        FilmSource = HasFilm ? MediaSource.CreateFromUri(new Uri(FilmPath)) : null;
        CanOfferExport = HasFilm;
        var probe = _host.AvatarEngine.Probe();
        EngineLine = probe.Engine + " — " + probe.Line;
        if (IsBusy)
        {
            return;
        }

        Status = HasGenerated
            ? "Live version is on file. Twin shows this face. Ask speaks in Mixer and does not re-lipsync this take."
            : HasSitting || HasUsablePhoto
                ? probe.Ready
                    ? "Write a line and Make live version. That is the talking likeness."
                    : "A usable picture is filed. Fetch engine once, then Make live version."
                : HasPhotos
                    ? "Those pictures will not lock a mouth. File a face-on camera original of you alone — head and shoulders filling the frame."
                    : "File a face-on camera original of you alone. Head and shoulders, both eyes toward the lens, about 720px or more on the short side.";
    }

    private void ReloadPhotosFromDisk()
    {
        var stored = _host.Settings.Current.AvatarPhotoPaths ?? [];
        if (stored.Count == 0 && File.Exists(_host.Settings.Current.AvatarPortraitPath))
        {
            stored = [_host.Settings.Current.AvatarPortraitPath];
        }

        var existing = stored.Where(File.Exists).Distinct(StringComparer.OrdinalIgnoreCase).ToList();
        var current = Photos.Select(p => p.Path).ToList();
        if (current.Count == existing.Count && current.SequenceEqual(existing, StringComparer.OrdinalIgnoreCase))
        {
            return;
        }

        Photos.Clear();
        foreach (var path in existing)
        {
            Photos.Add(ItemFrom(path));
        }
    }

    private async Task<string?> PickVisualAsync(IProgress<string> progress, CancellationToken cancellationToken)
    {
        var notes = new List<string>();
        var ready = _host.AvatarEngine.Probe().Ready;
        var ordered = new List<string>();
        if (HasSitting)
        {
            ordered.Add(SittingPath);
        }

        foreach (var path in PhotoCandidates)
        {
            if (!ordered.Contains(path, StringComparer.OrdinalIgnoreCase))
            {
                ordered.Add(path);
            }
        }

        if (ordered.Count == 0)
        {
            Status = "File a face-on camera original of you alone first — head and shoulders filling the frame. Chat thumbs and group shots will not work.";
            return null;
        }

        foreach (var path in ordered)
        {
            var item = Photos.FirstOrDefault(p => string.Equals(p.Path, path, StringComparison.OrdinalIgnoreCase));
            if (item is { Usable: false })
            {
                notes.Add(item.Fit);
                continue;
            }

            if (!ready)
            {
                return path;
            }

            var check = await _host.AvatarEngine.CheckAsync(path, progress, cancellationToken).ConfigureAwait(true);
            if (check.Ok)
            {
                return path;
            }

            notes.Add(check.Line);
        }

        Status = notes.Count == 0
            ? "None of the filed pictures will lock a mouth. See WHAT TO FILE."
            : string.Join(" ", notes.Take(3));
        return null;
    }

    private AvatarPhotoItem ItemFrom(string path)
    {
        var (usable, shortSide, fit) = JudgePhoto(path);
        return new AvatarPhotoItem(path, Thumb(path), usable, shortSide, fit, RemovePhotoCommand);
    }

    private static (bool Usable, int ShortSide, string Fit) JudgePhoto(string path)
    {
        try
        {
            using var stream = File.OpenRead(path);
            using var image = System.Drawing.Image.FromStream(stream, useEmbeddedColorManagement: false, validateImageData: false);
            var w = image.Width;
            var h = image.Height;
            var shortSide = Math.Min(w, h);
            if (shortSide < 480)
            {
                return (false, shortSide, $"Too small ({w}×{h}). Need a camera original, about 720px or more on the short side — not a chat crop.");
            }

            if ((long)w * h < 400_000)
            {
                return (false, shortSide, $"{w}×{h}. Face is likely a speck. Head and shoulders should fill the frame — not a full-body landscape.");
            }

            if (shortSide < 720)
            {
                return (true, shortSide, $"{w}×{h}. Borderline. A larger original will lock the mouth better. You alone, looking at the lens.");
            }

            return (true, shortSide, $"{w}×{h}. Large enough if you are alone and looking at the camera.");
        }
        catch
        {
            return (false, 0, "Could not read this file as a photograph.");
        }
    }

    private void PersistPhotos()
    {
        var paths = Photos.Select(p => p.Path).Where(File.Exists).ToList();
        _host.Settings.Current.AvatarPhotoPaths = paths;
        _host.Settings.Current.AvatarPortraitPath =
            Photos.Where(p => p.Usable).Select(p => p.Path).FirstOrDefault()
            ?? paths.FirstOrDefault()
            ?? "";
        _host.Settings.Save();
    }

    private static void TryDeleteOwned(string path)
    {
        try
        {
            var root = Path.GetFullPath(AppPaths.AvatarRoot);
            var full = Path.GetFullPath(path);
            if (full.StartsWith(root, StringComparison.OrdinalIgnoreCase) && File.Exists(full))
            {
                File.Delete(full);
            }
        }
        catch
        {
            // Leave an orphan copy rather than fail the studio.
        }
    }

    private static BitmapImage Thumb(string path)
    {
        var image = new BitmapImage { DecodePixelWidth = 224 };
        image.UriSource = new Uri(path);
        return image;
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
        _host.Settings.Current.Autostart = Autostart;
        WriteChrome();
        _host.Settings.Save();
        ThemeService.Apply(_host.Settings.Current);
        AutostartService.Apply(Autostart);
        var vault = LibraryPath.Trim();
        if (vault.Length > 0 && !string.Equals(_host.Vault.RootPath, vault, StringComparison.OrdinalIgnoreCase))
        {
            _host.SetVaultPath(vault);
            LibraryPath = _host.Vault.RootPath;
        }
        else
        {
            _host.Settings.Current.LibraryPath = vault;
            _host.Settings.Save();
        }

        if (!string.IsNullOrWhiteSpace(SessionToken))
        {
            _host.Auth.SetSessionToken(SessionToken);
        }

        if (!string.IsNullOrWhiteSpace(DeviceToken))
        {
            _host.Auth.SetDeviceToken(DeviceToken);
        }

        Saved?.Invoke();
    }

    public event Action? Saved;

    [RelayCommand]
    public async Task BrowseVaultAsync()
    {
        var picked = await StudioPickers.PickFolderAsync("Choose the vault folder").ConfigureAwait(true);
        if (string.IsNullOrWhiteSpace(picked))
        {
            return;
        }

        _host.SetVaultPath(picked);
        LibraryPath = _host.Vault.RootPath;
        Saved?.Invoke();
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
    public void SignOut()
    {
        _host.Auth.SignOut();
        Saved?.Invoke();
    }

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
    [ObservableProperty] private ArchiveEntry? _selected;

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
        if (!_host.CanEdit)
        {
            Status = "Heir mode. Skills are locked.";
            return;
        }

        if (string.IsNullOrWhiteSpace(Name) || string.IsNullOrWhiteSpace(Url))
        {
            Status = "Name and webhook URL, then Add skill.";
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
        if (string.IsNullOrWhiteSpace(skill.Url))
        {
            Status = "No webhook on that skill.";
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

    [RelayCommand]
    public async Task FireSelectedAsync()
    {
        if (Selected is null || string.IsNullOrWhiteSpace(Selected.Tag))
        {
            Status = "Pick a skill in the list, then Fire.";
            return;
        }

        await InvokeAsync(Selected.Tag).ConfigureAwait(true);
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
        try
        {
            foreach (var file in Directory.EnumerateFiles(Path).OrderByDescending(File.GetLastWriteTimeUtc).Take(40))
            {
                var name = System.IO.Path.GetFileName(file);
                if (name.Equals("vault.db", StringComparison.OrdinalIgnoreCase) || name.EndsWith("-shm", StringComparison.OrdinalIgnoreCase) || name.EndsWith("-wal", StringComparison.OrdinalIgnoreCase))
                {
                    continue;
                }

                var info = new FileInfo(file);
                Items.Add(new ArchiveEntry(name, info.Length + " bytes", info.LastWriteTime.ToString("g"), "file", name));
            }
        }
        catch (Exception ex)
        {
            Status = ex.Message;
        }

        foreach (var row in _host.Vault.Recent(20))
        {
            Items.Add(new ArchiveEntry(row.Kind, row.Text, row.Created, row.Kind, row.Tag));
        }

        var stats = _host.Vault.Stats();
        Status = $"{stats.Captures} memories  ·  {Items.Count} rows  ·  {Path}";
    }

    [RelayCommand]
    public async Task ChangeFolderAsync()
    {
        var picked = await StudioPickers.PickFolderAsync("Choose the vault folder").ConfigureAwait(true);
        if (string.IsNullOrWhiteSpace(picked))
        {
            return;
        }

        _host.SetVaultPath(picked);
        Reload();
        Status = "Vault is now " + Path + ". The previous folder was left as it was.";
    }

    [RelayCommand]
    public void OpenFolder() => StudioPickers.OpenFolder(Path);
}
