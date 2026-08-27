using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using Heirloom.Services;

namespace Heirloom.ViewModels;

public sealed record DockItem(string Id, string Label, string Glyph, bool IsHeader = false);

public partial class StudioShellViewModel : ObservableObject
{
    private readonly AppHost _host;
    private readonly HashSet<string> _open = new(StringComparer.Ordinal)
    {
        "twin",
    };

    public StudioShellViewModel(AppHost host)
    {
        _host = host;
        Mixer = new MixerViewModel(host);
        Twin = new TwinViewModel(host, Mixer);
        Assistant = new AssistantViewModel(host, Mixer);
        Models = new ModelsViewModel(host);
        FirstRun = new FirstRunViewModel(host);
        FirstRun.RequestClose += (_, room) =>
        {
            ShowFirstRun = false;
            if (!string.IsNullOrWhiteSpace(room))
            {
                OpenDocument(room);
            }
        };
        Archive = new ArchiveViewModel(host);
        Today = new TodayViewModel(host);
        Journal = new JournalViewModel(host);
        Interviewer = new InterviewerViewModel(host);
        Photos = new PhotosViewModel(host);
        Import = new ImportViewModel(host);
        Sources = new SourcesViewModel(host);
        Heirs = new ContinuityViewModel(host);
        Personality = new PersonalityViewModel(host);
        Abilities = new AbilitiesViewModel(host);
        Keys = new KeysViewModel(host);
        Avatar = new AvatarViewModel(host);
        Settings = new SettingsViewModel(host);
        Glossary = new GlossaryViewModel();
        KitchenSink = new KitchenSinkViewModel();
        Coach = new VendorCoachViewModel(host);
        Skills = new SkillsViewModel(host);
        Library = new LibraryViewModel(host);
        Phone = new PhoneViewModel(host);
        Twin.Phone = Phone;
        Coach.PropertyChanged += (_, e) =>
        {
            if (e.PropertyName == nameof(VendorCoachViewModel.IsOpen) && !Coach.IsOpen)
            {
                ShowCoach = false;
            }
        };
        host.Poller.CommandExecuted += (_, msg) => UiDispatch.Post(() => StatusLine = msg);
        Twin.PropertyChanged += (_, e) =>
        {
            if (e.PropertyName == nameof(TwinViewModel.Status))
            {
                StatusLine = Twin.Status;
            }
        };
        Assistant.PropertyChanged += (_, e) =>
        {
            if (e.PropertyName == nameof(AssistantViewModel.Status))
            {
                StatusLine = Assistant.Status;
            }
        };
        Twin.Filed += (_, _) => ReloadVaultRooms();
        Twin.VideoStudioRequested += (_, intent) => UiDispatch.Post(() => OpenVideoStudio(intent));
        Assistant.VideoStudioRequested += (_, intent) => UiDispatch.Post(() => OpenVideoStudio(intent));
        Settings.Saved += () =>
        {
            Keys.Refresh();
            ReloadVaultRooms();
        };
        host.VaultPathChanged += () => UiDispatch.Post(() =>
        {
            Settings.LibraryPath = host.Settings.Current.LibraryPath;
            FirstRun.LibraryPath = host.Settings.Current.LibraryPath;
            ReloadVaultRooms();
            StatusLine = "Vault is now " + host.Vault.RootPath;
        });
        host.AppModeChanged += () => UiDispatch.Post(() =>
        {
            Twin.ApplyAudience();
            Phone.ApplyAudience();
            Personality.ReloadFacts();
        });
        Mixer.PropertyChanged += (_, e) =>
        {
            if (e.PropertyName == nameof(MixerViewModel.Status))
            {
                StatusLine = Mixer.Status;
            }
        };
        StatusLine = "Heirloom " + host.Version + "  ·  " + host.BuildId;
        RefreshWindowLine();
    }

    public event EventHandler<string>? DocumentOpened;
    public event EventHandler<string>? DocumentClosed;
    public event EventHandler? LayoutCascadeRequested;
    public event EventHandler? LayoutTileRequested;

    public MixerViewModel Mixer { get; }
    public TwinViewModel Twin { get; }
    public AssistantViewModel Assistant { get; }
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
    public GlossaryViewModel Glossary { get; }
    public KitchenSinkViewModel KitchenSink { get; }
    public VendorCoachViewModel Coach { get; }
    public SkillsViewModel Skills { get; }
    public LibraryViewModel Library { get; }
    public PhoneViewModel Phone { get; }

    public IReadOnlyList<DockItem> Dock { get; } =
    [
        Head("Sit"),
        new("assistant", "Assist", "\uE99A"),
        new("today", "Today", "\uE706"),
        new("mixer", "Mixer", "\uE767"),
        Head("Twin"),
        new("twin", "Sitting", "\uE8BD"),
        new("personality", "Portrait", "\uE8D4"),
        new("abilities", "Abilities", "\uE945"),
        new("skills", "Skills", "\uE90F"),
        new("phone", "Phone", "\uE717"),
        new("avatar", "Avatar", "\uE8B8"),
        Head("File"),
        new("archive", "Archive", "\uE8F1"),
        new("journal", "Journal", "\uE70B"),
        new("interviewer", "Interviewer", "\uE8F2"),
        new("photos", "Photos", "\uE91B"),
        new("import", "Import", "\uE8B5"),
        Head("Keep"),
        new("library", "Library", "\uE8A5"),
        new("sources", "Sources", "\uE8B7"),
        Head("Gift"),
        new("heirs", "Heirs", "\uE716"),
        new("letters", "Letters", "\uE715"),
        Head("Studio"),
        new("models", "Models", "\uE950"),
        new("thismachine", "This PC", "\uE770"),
        new("keys", "Keys", "\uE192"),
        new("settings", "Settings", "\uE713"),
        new("glossary", "Glossary", "\uE82D"),
    ];

    private static DockItem Head(string label) => new("group-" + label.ToLowerInvariant(), label, "", true);

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
        if (string.IsNullOrWhiteSpace(id) || Dock.Any(d => d.Id == id && d.IsHeader))
        {
            return;
        }

        _open.Add(id);
        ActiveDocumentId = id;
        StudioHelp.SetDocument(id);
        switch (id)
        {
            case "archive":
                Archive.Reload();
                break;
            case "library":
                Library.Reload();
                break;
            case "journal":
                Journal.Reload();
                break;
            case "photos":
                Photos.Reload();
                break;
            case "skills":
                Skills.Reload();
                break;
            case "phone":
                _ = Phone.ReloadAsync();
                break;
            case "heirs":
            case "letters":
                Heirs.Reload();
                break;
            case "keys":
                Keys.Refresh();
                break;
            case "avatar":
                Avatar.Reload();
                break;
            case "models":
            case "thismachine":
                _ = Models.RefreshAsync();
                break;
            case "today":
                _ = Today.LoadAsync();
                break;
        }

        StatusLine = id switch
        {
            "assistant" => "Assist  ·  work on this PC",
            "twin" => "Twin  ·  grounded conversation",
            "mixer" => "Mixer  ·  Heirloom WASAPI session",
            "models" => "Models  ·  local brain",
            "interviewer" => "Interviewer  ·  chapters, not chat",
            "archive" => "Archive  ·  retrieval",
            "heirs" => "Heirs  ·  consent and lock",
            "letters" => "Sealed letters",
            "skills" => "Skills  ·  webhooks",
            "phone" => "Phone  ·  family line",
            "library" => "Library  ·  this PC vault",
            "glossary" => "Glossary  ·  words this studio uses",
            "kitchensink" => "Control language  ·  Ferrari kit",
            _ => char.ToUpper(id[0]) + id[1..],
        };
        RefreshWindowLine();
        DocumentOpened?.Invoke(this, id);
    }

    private void ReloadVaultRooms()
    {
        Archive.Reload();
        Journal.Reload();
        Library.Reload();
        Photos.Reload();
        Heirs.Reload();
        Skills.Reload();
        _ = Today.LoadAsync();
    }

    [RelayCommand]
    public void CloseDocument(string id)
    {
        _open.Remove(id);
        if (ActiveDocumentId == id)
        {
            ActiveDocumentId = _open.LastOrDefault() ?? "assistant";
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

        OpenDocument("assistant");
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
            OpenDocument("assistant");
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
        if (q is "video" or "film" or "likeness" || q.Contains("video studio") || q.Contains("avatar"))
        {
            OpenDocument("avatar");
            return;
        }

        if (q.StartsWith("speak "))
        {
            await Twin.SpeakAsync(CommandQuery[6..]).ConfigureAwait(true);
            return;
        }

        if (q.StartsWith("do "))
        {
            await Assistant.TalkAsync(CommandQuery[3..]).ConfigureAwait(true);
            return;
        }

        if (q.StartsWith("capture "))
        {
            if (!_host.CanEdit)
            {
                StatusLine = "Heir mode. Filing is locked.";
                return;
            }

            _host.Vault.AddCapture("note", CommandQuery[8..]);
            Archive.Reload();
            return;
        }

        var hit = Dock.FirstOrDefault(d =>
            !d.IsHeader && (d.Id.Contains(q) || d.Label.Contains(q, StringComparison.OrdinalIgnoreCase)));
        if (hit is not null)
        {
            OpenDocument(hit.Id);
        }
    }

    [RelayCommand]
    public void ReopenFirstRun()
    {
        Settings.ReopenSetup();
        FirstRun.ResetToWelcome();
        ShowFirstRun = true;
    }

    public void DismissSplash()
    {
        ShowSplash = false;
        ShowFirstRun = !_host.Settings.Current.SetupComplete && !_host.Settings.Current.SetupSkipped;
        OpenDocument("twin");
    }

    [RelayCommand]
    public void StartCoach()
    {
        Coach.Start(_host.Settings.Current.VendorEmail);
        ShowCoach = Coach.IsOpen;
    }

    private void OpenVideoStudio(VideoJobIntent intent)
    {
        var script = intent.UseLastReply ? Twin.LastOfferScript : intent.Script;
        Avatar.ApplyTwinOffer(script, intent.PresetId);
        OpenDocument("avatar");
        StatusLine = intent.DoneLine;
    }

    private void RefreshWindowLine()
    {
        WindowLine = _open.Count == 0 ? "No documents" : string.Join("  ·  ", _open);
    }
}
