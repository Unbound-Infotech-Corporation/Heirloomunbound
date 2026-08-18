using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using Heirloom.Services;

namespace Heirloom.ViewModels;

public sealed record DockItem(string Id, string Label, string Glyph);

public partial class StudioShellViewModel : ObservableObject
{
    private readonly AppHost _host;
    private readonly HashSet<string> _open = new(StringComparer.Ordinal)
    {
        "twin",
        "mixer",
    };

    public StudioShellViewModel(AppHost host)
    {
        _host = host;
        Mixer = new MixerViewModel(host);
        Twin = new TwinViewModel(host, Mixer);
        Models = new ModelsViewModel(host);
        FirstRun = new FirstRunViewModel(host);
        Archive = new ArchiveViewModel(host);
        Today = new TodayViewModel(host);
        Journal = new JournalViewModel(host);
        Interviewer = new InterviewerViewModel(host);
        Photos = new PhotosViewModel(host);
        Import = new ImportViewModel(host);
        Sources = new SourcesViewModel();
        Heirs = new ContinuityViewModel(host);
        Personality = new PersonalityViewModel(host);
        Abilities = new AbilitiesViewModel(host);
        Keys = new KeysViewModel(host);
        Avatar = new AvatarViewModel();
        Settings = new SettingsViewModel(host);
        KitchenSink = new KitchenSinkViewModel();
        Coach = new VendorCoachViewModel(host);
        Skills = new SkillsViewModel(host);
        Library = new LibraryViewModel(host);
        Coach.PropertyChanged += (_, e) =>
        {
            if (e.PropertyName == nameof(VendorCoachViewModel.IsOpen) && !Coach.IsOpen)
            {
                ShowCoach = false;
            }
        };
        host.Poller.CommandExecuted += (_, msg) => UiDispatch.Post(() => StatusLine = msg);
        StatusLine = "Heirloom " + host.Version + "  ·  " + host.BuildId;
        RefreshWindowLine();
    }

    public event EventHandler<string>? DocumentOpened;
    public event EventHandler<string>? DocumentClosed;
    public event EventHandler? LayoutCascadeRequested;
    public event EventHandler? LayoutTileRequested;

    public MixerViewModel Mixer { get; }
    public TwinViewModel Twin { get; }
    public ModelsViewModel Models { get; }
    public FirstRunViewModel FirstRun { get; }
    public ArchiveViewModel Archive { get; }
    public TodayViewModel Today { get; }
    public JournalViewModel Journal { get; }
    public InterviewerViewModel Interviewer { get; }
    public PhotosViewModel Photos { get; }
    public ImportViewModel Import { get; }
    public SourcesViewModel Sources { get; }
    public ContinuityViewModel Heirs { get; }
    public PersonalityViewModel Personality { get; }
    public AbilitiesViewModel Abilities { get; }
    public KeysViewModel Keys { get; }
    public AvatarViewModel Avatar { get; }
    public SettingsViewModel Settings { get; }
    public KitchenSinkViewModel KitchenSink { get; }
    public VendorCoachViewModel Coach { get; }
    public SkillsViewModel Skills { get; }
    public LibraryViewModel Library { get; }

    public IReadOnlyList<DockItem> Dock { get; } =
    [
        new("today", "Today", "\uE706"),
        new("archive", "Archive", "\uE8F1"),
        new("twin", "Twin", "\uE8BD"),
        new("mixer", "Mixer", "\uE767"),
        new("models", "Models", "\uE950"),
        new("journal", "Journal", "\uE70B"),
        new("interviewer", "Interviewer", "\uE8F2"),
        new("photos", "Photos", "\uE91B"),
        new("library", "Library", "\uE8A5"),
        new("import", "Import", "\uE8B5"),
        new("sources", "Sources", "\uE8B7"),
        new("personality", "Portrait", "\uE8D4"),
        new("abilities", "Abilities", "\uE945"),
        new("skills", "Skills", "\uE90F"),
        new("avatar", "Avatar", "\uE8B8"),
        new("heirs", "Heirs", "\uE716"),
        new("letters", "Letters", "\uE715"),
        new("keys", "Keys", "\uE192"),
        new("thismachine", "This PC", "\uE770"),
        new("settings", "Settings", "\uE713"),
        new("kitchensink", "Controls", "\uE790"),
    ];

    [ObservableProperty] private string _activeDocumentId = "twin";
    [ObservableProperty] private string _statusLine = "Heirloom";
    [ObservableProperty] private string _windowLine = "";
    [ObservableProperty] private bool _commandPaletteOpen;
    [ObservableProperty] private string _commandQuery = "";
    [ObservableProperty] private bool _showSplash = true;
    [ObservableProperty] private bool _showFirstRun;
    [ObservableProperty] private bool _showCoach;

    public bool IsHeirMode => string.Equals(_host.Settings.Current.AppMode, "heir", StringComparison.OrdinalIgnoreCase);
    public bool IsOpen(string id) => _open.Contains(id);
    public IReadOnlyCollection<string> OpenIds => _open;

    [RelayCommand]
    public void OpenDocument(string id)
    {
        _open.Add(id);
        ActiveDocumentId = id;
        StatusLine = id switch
        {
            "twin" => "Twin  ·  grounded conversation",
            "mixer" => "Mixer  ·  Heirloom WASAPI session",
            "models" => "Models  ·  local brain",
            "interviewer" => "Interviewer  ·  chapters, not chat",
            "archive" => "Archive  ·  retrieval",
            "heirs" => "Heirs  ·  consent and lock",
            "letters" => "Sealed letters",
            "skills" => "Skills  ·  webhooks",
            "library" => "Library  ·  this PC vault",
            "kitchensink" => "Control language  ·  Ferrari kit",
            _ => char.ToUpper(id[0]) + id[1..],
        };
        RefreshWindowLine();
        DocumentOpened?.Invoke(this, id);
    }

    [RelayCommand]
    public void CloseDocument(string id)
    {
        _open.Remove(id);
        if (ActiveDocumentId == id)
        {
            ActiveDocumentId = _open.LastOrDefault() ?? "twin";
        }

        RefreshWindowLine();
        DocumentClosed?.Invoke(this, id);
    }

    [RelayCommand]
    public void CloseAll()
    {
        foreach (var id in _open.ToArray())
        {
            CloseDocument(id);
        }

        OpenDocument("twin");
    }

    [RelayCommand]
    public void CascadeWindows() => LayoutCascadeRequested?.Invoke(this, EventArgs.Empty);

    [RelayCommand]
    public void TileWindows() => LayoutTileRequested?.Invoke(this, EventArgs.Empty);

    [RelayCommand]
    public void CycleWindows()
    {
        var list = _open.ToList();
        if (list.Count == 0)
        {
            OpenDocument("twin");
            return;
        }

        var i = list.IndexOf(ActiveDocumentId);
        OpenDocument(list[(i + 1) % list.Count]);
    }

    [RelayCommand]
    public void TogglePalette()
    {
        CommandPaletteOpen = !CommandPaletteOpen;
        if (CommandPaletteOpen)
        {
            CommandQuery = "";
        }
    }

    [RelayCommand]
    public async Task RunPaletteAsync()
    {
        var q = CommandQuery.Trim().ToLowerInvariant();
        CommandPaletteOpen = false;
        if (q.StartsWith("speak "))
        {
            await Twin.SpeakAsync(CommandQuery[6..]).ConfigureAwait(true);
            return;
        }

        if (q.StartsWith("capture "))
        {
            _host.Vault.AddCapture("note", CommandQuery[8..]);
            Archive.Reload();
            return;
        }

        var hit = Dock.FirstOrDefault(d => d.Id.Contains(q) || d.Label.Contains(q, StringComparison.OrdinalIgnoreCase));
        if (hit is not null)
        {
            OpenDocument(hit.Id);
        }
    }

    [RelayCommand]
    public void ReopenFirstRun()
    {
        Settings.ReopenSetup();
        ShowFirstRun = true;
    }

    public void DismissSplash()
    {
        ShowSplash = false;
        ShowFirstRun = !_host.Settings.Current.SetupComplete && !_host.Settings.Current.SetupSkipped;
        OpenDocument("twin");
        OpenDocument("mixer");
    }

    [RelayCommand]
    public void StartCoach()
    {
        Coach.Start(FirstRun.VendorEmail);
        ShowCoach = Coach.IsOpen;
    }

    private void RefreshWindowLine()
    {
        WindowLine = _open.Count == 0 ? "No documents" : string.Join("  ·  ", _open);
    }
}
