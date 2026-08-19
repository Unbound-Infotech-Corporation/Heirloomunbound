namespace Heirloom.Services;

public sealed record HelpTopic(
    string Id,
    string Title,
    string Kind,
    string Summary,
    string Body,
    IReadOnlyList<string> Related);

/// <summary>
/// Plain-language map of Heirloom. Hover inspector and Glossary both read this.
/// Kind: document, action, term, chrome.
/// </summary>
public static class StudioLexicon
{
    public static readonly HelpTopic Resting = new(
        "inspector",
        "Hover inspector",
        "chrome",
        "Point at a button, dock tile, or control. Its name and job appear here.",
        "This panel stays put so you do not hunt tooltips. Hover to preview. Pin to keep a topic while you work. One sitting at a time: Twin opens first; Mixer is in Sit when you need volume. The dock is grouped (Sit, File, Keep, Voice, Gift, Studio). Open the Glossary for every word Heirloom uses. Hide the panel in Settings if you want the canvas full-bleed.",
        ["glossary", "dock", "twin"]);

    public static HelpTopic Resolve(string? id)
    {
        if (string.IsNullOrWhiteSpace(id))
        {
            return Resting;
        }

        var key = id.Trim();
        if (Topics.TryGetValue(key, out var hit))
        {
            return hit;
        }

        if (key.StartsWith("action-", StringComparison.OrdinalIgnoreCase)
            && Topics.TryGetValue(key["action-".Length..], out hit))
        {
            return hit;
        }

        if (key.StartsWith("dock-", StringComparison.OrdinalIgnoreCase)
            && Topics.TryGetValue(key["dock-".Length..], out hit))
        {
            return hit;
        }

        foreach (var topic in Topics.Values)
        {
            if (topic.Title.Equals(key, StringComparison.OrdinalIgnoreCase))
            {
                return topic;
            }
        }

        return Resting with
        {
            Id = key,
            Title = Humanize(key),
            Summary = "A studio control. Open the Glossary if this word is new.",
            Body = "Heirloom did not have a longer note for “" + Humanize(key) + "”. Try the Glossary search, or pin the document’s Help from the ? on its title bar.",
        };
    }

    public static string LayerOf(HelpTopic topic) => topic.Kind switch
    {
        "document" => "Room",
        "action" => "Verb",
        "term" => "Word",
        "chrome" => "Chrome",
        _ => "",
    };

    public static string Place(string? id)
    {
        var topic = Resolve(id);
        var layer = LayerOf(topic);
        var group = GroupOf(topic.Id);
        if (string.IsNullOrEmpty(group))
        {
            return layer;
        }

        var rest = topic.Id.StartsWith("group-", StringComparison.OrdinalIgnoreCase)
            ? group
            : group + "  ·  " + topic.Title;
        return string.IsNullOrEmpty(layer) ? rest : layer + "  ·  " + rest;
    }

    private static string GroupOf(string id) => id.ToLowerInvariant() switch
    {
        "today" or "twin" or "mixer" or "group-sit" or "ptt" or "persona" or "grounded" or "speak" or "sitting"
            or "undo" or "disclose" or "look-back" or "wishful" or "mute"
            => "Sit",
        "archive" or "journal" or "interviewer" or "photos" or "import" or "group-file" or "file" or "ask" or "chapter"
            or "story" or "recognize"
            => "File",
        "library" or "sources" or "group-keep" or "vault"
            => "Keep",
        "personality" or "abilities" or "skills" or "avatar" or "group-voice" or "portrait"
            => "Voice",
        "heirs" or "letters" or "group-gift" or "heir"
            => "Gift",
        "models" or "thismachine" or "keys" or "settings" or "glossary" or "kitchensink" or "group-studio"
            or "dock" or "chrome" or "inspector" or "chunking" or "defaults" or "working-memory" or "schema" or "now"
            or "primary" or "gestalt" or "serial" or "attention" or "environment" or "levels" or "save" or "mark"
            => "Studio",
        _ => "",
    };

    public static IReadOnlyList<HelpTopic> Terms =>
        Topics.Values.Where(t => t.Kind == "term").OrderBy(t => t.Title, StringComparer.OrdinalIgnoreCase).ToList();

    public static IReadOnlyList<HelpTopic> All =>
        Topics.Values.OrderBy(t => t.Title, StringComparer.OrdinalIgnoreCase).ToList();

    public static IReadOnlyList<HelpTopic> Search(string query)
    {
        var q = query.Trim();
        if (q.Length == 0)
        {
            return Terms;
        }

        return All
            .Where(t =>
                t.Title.Contains(q, StringComparison.OrdinalIgnoreCase)
                || t.Summary.Contains(q, StringComparison.OrdinalIgnoreCase)
                || t.Body.Contains(q, StringComparison.OrdinalIgnoreCase)
                || t.Id.Contains(q, StringComparison.OrdinalIgnoreCase))
            .ToList();
    }

    public static IReadOnlyList<HelpTopic> Related(HelpTopic topic) =>
        topic.Related.Select(Resolve).DistinctBy(t => t.Id).ToList();

    private static string Humanize(string id)
    {
        var s = id.Replace("action-", "", StringComparison.OrdinalIgnoreCase)
            .Replace("dock-", "", StringComparison.OrdinalIgnoreCase)
            .Replace('-', ' ');
        return string.Concat(s[0].ToString().ToUpperInvariant(), s.AsSpan(1));
    }

    private static readonly Dictionary<string, HelpTopic> Topics = Build();

    private static Dictionary<string, HelpTopic> Build()
    {
        HelpTopic T(string id, string title, string kind, string summary, string body, params string[] related) =>
            new(id, title, kind, summary, body, related);

        var list = new[]
        {
            T("heirloom", "Heirloom", "term",
                "The studio on this PC for a voice and a life that should outlast you.",
                "Heirloom Unbound is a digital-twin and legacy archive. The Windows app is the owner studio. The web app is public and heir-facing. This is not a chatbot toy: people set aside tens of gigabytes and mean to gift it after death.",
                "twin", "vault", "heirs"),
            T("twin", "Twin", "document",
                "The conversation that must stay grounded in what you filed.",
                "This is the sitting. One job: talk or file. Mixer stays in Sit until you need volume — it does not open on top of Twin. Grounded mode prefers the archive over invention. New starts a clean thread.",
                "grounded", "archive", "persona", "ptt", "sitting"),
            T("mixer", "Mixer", "document",
                "Heirloom’s own volume — never Windows’ master slider.",
                "The mixer is a dedicated WASAPI session named Heirloom. Twin “set the volume” writes here. Mute, devices, gain, and noise gate all live in this document. If the whole PC goes quiet, you are on the wrong slider.",
                "session", "wasapi", "mute"),
            T("archive", "Archive", "document",
                "The retrieval room. File a true sentence; ask it back later.",
                "The archive is what the twin is allowed to remember. File captures a note. Ask searches what you already stored. Kind filters (note, voice, photo…) keep the pile honest.",
                "file", "vault", "grounded"),
            T("today", "Today", "document",
                "Look at what is filed. Then one next step.",
                "Status is the last thing in the vault. The gold button is the gap. Empty vault → Twin; no chapters → Interviewer; otherwise Journal. This is not a standup, a score, or a retrospective meeting.",
                "twin", "interviewer", "journal", "look-back"),
            T("journal", "Journal", "document",
                "Tagged days the twin can retrieve later.",
                "Write what the day actually was. That is the owner’s reflection — noticing what is still missing — not a team retrospective. Tags (family, work, health) make later Ask useful.",
                "twin", "archive", "file", "metacognition"),
            T("interviewer", "Interviewer", "document",
                "Chapters, not chat. One prompt at a time.",
                "The interviewer walks a life in sections so the vault fills with answers an heir can use. File answer stores this chapter. Skip is allowed. This is not the Twin — it is structured memory.",
                "chapter", "archive", "twin"),
            T("photos", "Photos", "document",
                "Three facts beat a pretty guess: who, when, what is true.",
                "Name the people, the time, and the true sentence in the picture. The twin should not invent relatives. Next prompt asks another concrete question.",
                "archive", "import", "file"),
            T("library", "Library", "document",
                "The vault folder on this PC.",
                "Library is the files Heirloom can see locally. Path is set in Settings. Refresh after you copy material in. Open Archive to search what was filed.",
                "vault", "import", "archive"),
            T("import", "Import", "document",
                "Paste a life — messages, letters, notes — and file it into the vault.",
                "Choose a kind and a source label so later you know where a memory came from. File into vault writes it. This does not scrape other apps by itself.",
                "vault", "sources", "archive"),
            T("sources", "Sources", "document",
                "What the twin is allowed to learn from.",
                "Toggles for files, photos, mail, and messages. The local vault is always on this PC. Turn a source off if that channel should stay out of the twin.",
                "vault", "abilities", "import"),
            T("personality", "Portrait", "document",
                "How the twin should sound and what it values.",
                "Portrait is character, not a filter. Notes on manner and values. File portrait stores them. Heir mode may lock this.",
                "persona", "values", "abilities"),
            T("abilities", "Abilities", "document",
                "Permissions: screen, speak, PC control.",
                "See screen, speak, and PC control are dangerous if left on for an heir. Save permissions writes the lock. The vendor coach uses See screen only to watch setup pages — it does not type, solve captchas, or read keys off the picture.",
                "see-screen", "speak", "heirs"),
            T("skills", "Skills", "document",
                "Named webhooks the twin may fire when you say a trigger.",
                "A skill is a URL plus a spoken trigger (“porch light”). Add skill stores it. The twin should only call what you listed.",
                "twin", "abilities"),
            T("avatar", "Avatar", "document",
                "How the twin looks in the studio.",
                "Optional face for the conversation. It does not change what the twin knows. Open from Twin’s toolbar.",
                "twin", "portrait"),
            T("heirs", "Heirs", "document",
                "Who receives this, and whether they consented.",
                "Add an heir with relation and consent. Heir mode locks editing so the gift cannot be quietly rewritten. Export vault copies the archive off this PC.",
                "heir-mode", "letters", "vault"),
            T("letters", "Letters", "document",
                "Sealed notes that open later — not chat.",
                "A letter is for a named person at a named time. Seal letter stores it. This is not the Twin; it is a bequest.",
                "heirs", "vault"),
            T("keys", "Keys", "document",
                "Whether this PC is signed in and paired.",
                "Session token is browser login. Device token is the companion pairing in Credential Locker. Paste them in Settings. Never put keys in the vault as ordinary notes.",
                "device-token", "settings", "coach"),
            T("thismachine", "This PC", "document",
                "Daily machine or dedicated twin box, and where compute runs.",
                "Machine role and compute target (this PC, network companion, remote Ollama). Open Models to provision. 50 GB is the serious floor for a studio vault.",
                "models", "compute", "studio-50"),
            T("models", "Models", "document",
                "Local brain: Whisper for hearing, Ollama for thought.",
                "Provision Lite / Full / Studio 50GB+ / Dedicated. Compute: this PC, a paired network PC, or a remote Ollama URL. Cloud Claude and ElevenLabs remain fallbacks when local is missing.",
                "whisper", "ollama", "compute"),
            T("settings", "Settings", "document",
                "Look, dock, custom buttons, account, inspector.",
                "Color schemes, icon/text chrome, movable dock, custom PNG buttons, hover inspector, backend URL, library path, tokens, autostart. Save writes to %LOCALAPPDATA%\\Heirloom\\settings.json.",
                "chrome", "dock", "inspector"),
            T("kitchensink", "Control kit", "document",
                "Every button style in one place. Window menu, not the daily dock.",
                "Primary, secondary, quiet, danger, push-to-talk. Decision fatigue: this is a judgment room, not a sitting. Open it from Window → Control kit.",
                "chrome", "ptt", "disclose"),
            T("glossary", "Glossary", "document",
                "Every Heirloom word, searchable.",
                "Terms, documents, and toolbar actions in one list. Hover the inspector while you read, or click a row to pin it.",
                "inspector", "twin", "archive"),
            T("new", "New", "action",
                "Start a clean Twin conversation.",
                "Does not delete the archive. It only clears the current thread so a new sitting does not drag yesterday’s chat into today.",
                "twin", "archive"),
            T("file", "File", "action",
                "Put this into the vault as a memory, not as chat.",
                "File is capture: a sentence, a journal day, a photo story, a pasted import. It is not Settings Save. Asking later only works if you filed.",
                "archive", "vault", "save"),
            T("ask", "Ask", "action",
                "Ask from what was filed. Twin also files the sentence you typed.",
                "The box says Ask; the gold button says Ask. Send would be a chat app. Archive Ask only searches. Twin Ask files, then answers. A miss stays on the line.",
                "twin", "archive", "file"),
            T("save", "Save settings", "action",
                "Write chrome and account to this PC — not a memory.",
                "Dock, colors, inspector, tokens. Device tokens go to Credential Locker. This is not File. Do not use a floppy-disk mental model for the vault.",
                "settings", "file"),
            T("mute", "Mute", "action",
                "M on Mixer. Gold means the Heirloom session is silent.",
                "The letter is the verb, like a DAW track header. It is 40px, not 16. Windows master volume is untouched. Unmute here if Twin went quiet on purpose.",
                "mixer", "session", "mark"),
            T("mark", "Mark", "chrome",
                "A 40px well whose letter is the verb.",
                "M is Mute. Gold fill means armed. Color is state, not mood. The dock still shows names. Hover the inspector if the letter is new to you.",
                "mute", "chrome", "dock"),
            T("refresh", "Refresh / Rescan", "action",
                "Reload devices, vault lists, or the local probe.",
                "Rescan in Mixer picks up a USB mic. Refresh in Archive or Library re-reads the vault. Models refresh re-probes Whisper and Ollama.",
                "mixer", "models"),
            T("import-action", "Import", "action",
                "Open the Import document to paste material.",
                "Same as the dock’s Import tile. Kind + source label + File into vault.",
                "import", "vault"),
            T("portrait", "Portrait", "action",
                "Open the character notes for the twin.",
                "How it should speak and what it holds dear. Not a beauty filter.",
                "personality", "persona"),
            T("next", "Next", "action",
                "Advance one chapter or photo prompt.",
                "In Interviewer: next chapter. In Photos: next question. Does not file unless you already pressed File.",
                "interviewer", "photos"),
            T("skip", "Skip", "action",
                "Leave this chapter unanswered.",
                "Allowed. An heir would rather a hole than a guessed story.",
                "interviewer", "grounded"),
            T("export", "Export vault", "action",
                "Copy the archive off this PC.",
                "Use when you want a spare, or when handing a drive to an executor. Heir mode may still apply.",
                "vault", "heirs"),
            T("heir", "Heir mode", "action",
                "Lock editing so the gift cannot be quietly changed.",
                "Owner studio becomes read-mostly. Turn it off only if you are still the owner and mean to keep writing.",
                "heirs", "abilities"),
            T("folder", "Open buttons folder", "action",
                "Drop your own PNG tiles for dock and toolbar.",
                "Names like dock-twin.png and action-file.png. Simple silhouettes. Then Save in Settings.",
                "chrome", "settings"),
            T("ptt", "Push to talk", "term",
                "Hold to speak. Release to transcribe and answer.",
                "The round Hold control on Twin. Listening is armed only while you hold. The gold bar under it is microphone loudness, not how far through a sitting you are. Uses the Heirloom mic, then Whisper (local if provisioned).",
                "twin", "whisper", "mixer"),
            T("grounded", "Grounded", "term",
                "Answer from what was filed, not from a general model’s guess.",
                "Grounded-only is the default for a twin that will be inherited. The toggle shows the sitting now: Vault only, or May infer. Turn inference off before an heir uses this. Guessing at hidden meaning is how biography gets invented.",
                "archive", "twin", "now"),
            T("vault", "Vault", "term",
                "The local store of filed memory on this PC.",
                "Default under Documents\\HeirloomVault unless you moved it (often to a large drive). Do not put a 50 GB vault on a tiny system disk.",
                "library", "archive", "studio-50"),
            T("session", "Heirloom session", "term",
                "A private Windows audio session named Heirloom.",
                "WASAPI, not the system master. Volume Mixer in Windows should show Heirloom as its own row. That is the slider Twin is allowed to move.",
                "mixer", "wasapi"),
            T("wasapi", "WASAPI", "term",
                "Windows Audio Session API — how Heirloom owns its own volume.",
                "If you change “Speakers” in the system flyout, you are not changing Heirloom. Open Mixer in this app.",
                "mixer", "session"),
            T("persona", "Persona", "term",
                "Which manner the twin uses for this sitting (for example family).",
                "A persona is a speaking stance. Portrait is the deeper character. They work together.",
                "personality", "twin"),
            T("values", "Values", "term",
                "What the twin should refuse to betray.",
                "Stored with the portrait. Heirs inherit the stance, not a random model default.",
                "personality", "heirs"),
            T("whisper", "Whisper", "term",
                "Local speech-to-text (faster-whisper / ggml on this PC).",
                "Lives under LocalAppData\\Heirloom\\models\\whisper. If missing, hearing falls back to the cloud path.",
                "models", "ptt"),
            T("ollama", "Ollama", "term",
                "Local large-language runtime for the twin’s thought.",
                "Models can live on another drive (this studio often uses F:). llama and llava-style packs are provisioned from Models. Cloud remains a fallback.",
                "models", "compute"),
            T("compute", "Compute target", "term",
                "Where the brain runs: this PC, a network companion, or a remote Ollama URL.",
                "Network only runs provision on the machine you pick. Server is a URL you typed. Local is this studio.",
                "models", "thismachine"),
            T("studio-50", "Studio 50GB+", "term",
                "The serious disk floor for a vault you mean to keep.",
                "Lite is a taste. Full is local. Studio 50GB+ is the honest owner pack. Dedicated is a second PC with no cap. Custom / dedicated has no ceiling.",
                "models", "vault"),
            T("device-token", "Device token", "term",
                "Pairs this Windows studio to your Heirloom account.",
                "Paste in Settings. Stored in Windows Credential Locker, not in the chat. The legacy Python zip used a JSON field — native WinUI does not.",
                "keys", "settings"),
            T("session-token", "Session token", "term",
                "Browser sign-in, pasted if the studio must call the API as you.",
                "Separate from the device token. Sign out clears it.",
                "keys", "settings"),
            T("coach", "Vendor coach", "term",
                "A stay-on-top guide for creating vendor accounts and pasting keys.",
                "It can copy the email, open official pages, and watch the screen. You click Create account, captcha, and Verify. Heirloom does not drive the vendor page or OCR keys off a screenshot. Paste the key into the guide.",
                "keys", "see-screen"),
            T("see-screen", "See screen", "term",
                "Permission for the twin or coach to look at a screenshot of this PC.",
                "Off by default for a reason. The coach uses the same capture path. It does not type into other apps.",
                "abilities", "coach"),
            T("speak", "Speak", "term",
                "The twin may talk out loud with the cloned voice, then OS TTS as fallback.",
                "Uses POST /api/desktop/speak before SAPI. Mixer volume still applies.",
                "mixer", "abilities"),
            T("chapter", "Chapter", "term",
                "One interviewer prompt and its answer.",
                "A life is easier to gift as chapters than as an endless chat log.",
                "interviewer", "archive"),
            T("citation", "Citation", "term",
                "Where a Twin answer came from in the vault.",
                "A hit says Grounded in. A miss stays on the line — so a fluent reply cannot pretend it was retrieved. Empty vault and no-match are different sentences.",
                "grounded", "archive", "wishful"),
            T("wishful", "Don’t confirm a guess", "term",
                "A warm sentence is not a memory. Show the miss.",
                "Wishful thinking would treat a fluent twin as proof the vault is full. Status and citation say when nothing matched. Consent off is not consent. Sealed is not a draft. No points, no ‘well done’ — the room tells you what happened.",
                "grounded", "citation", "heir"),
            T("environment", "The room, not a prize", "term",
                "What you can do is what the sitting allows — not a token you earned.",
                "Behaviorism’s usable half: the environment shapes the next act. Twin only on launch, one gold verb, heir mode locks filing. Reject the other half: Pavlov, badges, streaks, unlocking cake after chores.",
                "sitting", "defaults", "heir"),
            T("dock", "Dock", "chrome",
                "The labeled rail of rooms. Grouped, moveable, order-stable.",
                "Six chunks: Sit, File, Keep, Voice, Gift, Studio. Headers are labels, not rooms. Sit bookends Twin and Mixer — first and last are what you keep. Drag ⋮⋮ to snap left, right, or top. Order inside a group does not shuffle.",
                "chrome", "inspector", "chunking", "serial"),
            T("chunking", "Chunking", "term",
                "Group the dock so the brain sees six rooms, not twenty-three choices.",
                "Working memory holds a handful of items. Hick’s law says choice time grows with the number of equal options. Headers (Sit / File / Keep / Voice / Gift / Studio) are landmarks. They are not clickable. Nearby controls are one job: Archive files on one row, asks on the next.",
                "dock", "defaults", "gestalt"),
            T("defaults", "Sensible defaults", "term",
                "The studio starts ready: grounded on, labels on, inspector open, Twin only.",
                "Decision fatigue is real on a first sitting. Grounded-only, icons and labels, parchment, a visible inspector, and one document (Twin) are the owner defaults. Mixer is one Sit click away. Change that in Settings when you mean to.",
                "grounded", "chrome", "inspector", "sitting"),
            T("sitting", "Sitting", "term",
                "One job at a time. Twin is the sitting; other rooms wait until you open them.",
                "Attention is limited. The studio does not dump Mixer, Archive, and Models at once. Open Sit → Mixer when you need the Heirloom WASAPI session. Close what you are not using.",
                "twin", "mixer", "defaults"),
            T("feedback", "Feedback", "term",
                "The status line says what just happened, in plain language.",
                "Recording, transcribing, thinking, answered from X, or nothing matched. Mute says the Heirloom session is muted. No points, no badges — just the loop so you are not guessing.",
                "twin", "ptt", "mute"),
            T("working-memory", "Working memory", "term",
                "You can hold only a handful of things. The studio holds the rest.",
                "Dock groups, one sitting, one next step on Today, and the hover inspector are external memory. Do not keep three rooms and a percentage score in your head at once.",
                "chunking", "today", "sitting", "schema"),
            T("schema", "Where you are", "term",
                "The gold mark on the dock is the room. Room · Sit · Twin is the map.",
                "Switching levels is the job: dock is the studio, the window is the sitting, a verb is File. The inspector path names the layer so you do not hold architecture and the sentence in working memory at once.",
                "dock", "working-memory", "levels"),
            T("levels", "Room, verb, word", "term",
                "The inspector says which layer you are on.",
                "Programmers switch from architecture to a line of code. Here: Room (Twin), Verb (File), Word (Grounded), Chrome (the dock). Decomposition already lives in Interviewer chapters. Do not import burnout coaching, imposter theater, or mindfulness.",
                "schema", "chapter", "working-memory"),
            T("now", "Now", "term",
                "What is true in this sitting, on screen — not a hidden spec.",
                "Mixer mute, grounded on/off, and the last citation are current values, like cells in a spreadsheet. If you have to imagine the session volume, the studio failed. Intuition here means seeing the relation, not guessing the code.",
                "session", "grounded", "citation"),
            T("undo", "Undo file", "action",
                "Take back the last sentence you filed. Chat may still show it until New.",
                "Error recovery for a slip, not a history browser. Heir mode locks this. Mixer, Portrait, and Avatar live on the dock — Twin only keeps New, Archive, and Undo.",
                "file", "archive", "twin"),
            T("disclose", "Progressive disclosure", "term",
                "Show the sitting. Hide the rest until you open that room.",
                "Twin is talk or file. Voice and Mixer are Sit/Voice on the dock. Extra buttons on Twin were extra choices (Hick). Advanced options stay in their own rooms.",
                "twin", "chunking", "sitting"),
            T("primary", "One gold action", "chrome",
                "Each room has one distinctive verb. The rest stay quiet.",
                "Von Restorff: what stands out is remembered. Twin: Send. Interviewer: File answer. Photos: File story. Journal: File entry. Two gold buttons in one cluster make neither one the job.",
                "file", "disclose", "chrome"),
            T("story", "The life, in order", "term",
                "Who, when, what is true — then why it matters to an heir.",
                "Photos ask three facts. Interviewer walks chapters. Journal is the day. This is the gift’s story, not a hook to keep you tapping. Do not tease the next page; finish this chapter.",
                "photos", "interviewer", "journal"),
            T("look-back", "Look back", "term",
                "See what the vault already has, then file the next gap.",
                "The Agile idea worth keeping: reflect, then adjust. Here that is Today’s last-filed line and one gold next step — not a retro, Freud, or a 12-step. Skip a chapter without treating it as failure. Undo a slip. Holes are in the vault, not a grade on the owner.",
                "today", "undo", "metacognition"),
            T("gestalt", "Together", "term",
                "Things that sit together are one job.",
                "Archive: write and File on one row; search and Ask on the next. Dock headers group rooms. Do not mix two jobs in one strip of equal buttons.",
                "archive", "chunking", "dock"),
            T("recognize", "Pick, don’t recall", "term",
                "Choose a named kind. Do not remember photo_story.",
                "File as and Kind are lists: Note, Spoken, Journal, Chapter. Recognition beats typing a vault id. Names and years on Photos stay typed — those are the facts, not a catalog.",
                "archive", "file"),
            T("serial", "First and last", "term",
                "You keep the ends of a list. Put the sitting there.",
                "Sit starts with Twin and ends with Mixer. File starts with Archive and ends with Import. Studio ends with Controls so the junk drawer is where you left it.",
                "dock", "twin", "chunking"),
            T("attention", "Attention", "term",
                "Gold and the talk button are the only grabs. Nothing pops.",
                "No toasts, badges, or push. Selective attention is the inspector and the status line. Do not ping an owner who is filing a life.",
                "primary", "ptt", "feedback"),
            T("metacognition", "Noticing", "term",
                "Stop and see what the vault still cannot say.",
                "Journal is that pause. Interviewer chapters break a life into pieces you can finish. Neither is a performance review. Anxiety and completeness percentages do not fill the archive.",
                "journal", "interviewer", "today"),
            T("group-sit", "Sit", "chrome",
                "Daily sitting: Today, Twin, Mixer.",
                "Where you actually work with the voice. Mixer is the Heirloom WASAPI session, not Windows master volume.",
                "today", "twin", "mixer"),
            T("group-file", "File", "chrome",
                "Capture: Archive, Journal, Interviewer, Photos, Import.",
                "These rooms put memory into the vault. Ask later only works if you filed.",
                "archive", "journal", "import"),
            T("group-keep", "Keep", "chrome",
                "What already lives on this PC: Library and Sources.",
                "Library is the vault on disk. Sources are the channels allowed to feed it.",
                "library", "sources"),
            T("group-voice", "Voice", "chrome",
                "Who the twin is: Portrait, Abilities, Skills, Avatar.",
                "Character and permissions, not the sitting itself.",
                "personality", "abilities", "avatar"),
            T("group-gift", "Gift", "chrome",
                "What an heir receives: Heirs and Letters.",
                "Consent, lock, and sealed notes. This is the posthumous product, not a game.",
                "heirs", "letters"),
            T("group-studio", "Studio", "chrome",
                "Machine and chrome: Models, This PC, Keys, Settings, Glossary, Controls.",
                "Provision, pairing, look, and the word list. Not daily memory work.",
                "models", "settings", "glossary"),
            T("chrome", "Chrome", "chrome",
                "Hairline studio, not a consumer card layout.",
                "Tight 1px seams, letter marks, icon plus short verb on the dock. Icons and labels recommended. Custom PNGs must be silhouettes that are the tool — scissors cut, M mutes — not photos.",
                "dock", "settings", "mark"),
            T("inspector", "Hover inspector", "chrome",
                "Right-side panel that names whatever you point at.",
                "Built so you do not have to memorize icons. Pin a topic. Open Glossary for the full list. Resize the gold seam. Toggle in Settings or Help.",
                "glossary", "dock"),
            T("unbound", "Unbound Infotech", "term",
                "The company that makes Heirloom.",
                "Shown on the Help menu and the Settings version line. Unrelated to CONVEX_AGENT_MODE.",
                "heirloom"),
            T("lite", "Lite", "action",
                "Smallest local provision — a taste, not the vault.",
                "Use Studio 50GB+ when this is a real gift. Lite is for trying hearing and speech on a small disk.",
                "models", "studio-50"),
            T("full", "Full", "action",
                "Provision a complete local brain on this PC.",
                "Whisper plus a working Ollama model. Still respect the disk you actually have.",
                "models", "ollama"),
            T("studio", "Studio 50GB+", "action",
                "The serious owner pack.",
                "Same idea as the first-run Studio profile. 50 GB is the floor, not a metaphor.",
                "studio-50", "models"),
            T("thispc", "This PC", "action",
                "Run compute on the machine you are sitting at.",
                "Opposite of Network companion or remote Ollama URL.",
                "compute", "models"),
            T("network", "Network", "action",
                "Run the brain on a paired companion PC.",
                "Provision commands include a target device id so only that machine downloads.",
                "compute", "models"),
            T("add", "Add", "action",
                "Create a skill, heir, or similar row.",
                "Needs owner edit rights. Heir mode may disable it.",
                "skills", "heirs"),
            T("setup", "First-run", "action",
                "Reopen the setup wizard: role, disk, email, pairing, models.",
                "Also under Settings. Completing setup can start the vendor coach.",
                "coach", "models"),
            T("signout", "Sign out", "action",
                "Clear the session from this studio.",
                "Does not delete the vault. Device pairing may remain until you replace the token.",
                "keys", "settings"),
            T("prev", "Previous", "action",
                "Go back one interviewer chapter.",
                "Does not un-file an answer already stored.",
                "interviewer", "next"),
            T("abilities-action", "Abilities", "action",
                "Open permissions for screen, speak, and PC control.",
                "Same as the Abilities document.",
                "abilities", "see-screen"),
            T("avatar-action", "Avatar", "action",
                "Open the avatar studio.",
                "Looks, not memory.",
                "avatar", "twin"),
            T("sources-action", "Sources", "action",
                "Open source toggles.",
                "What channels may feed the twin.",
                "sources", "vault"),
            T("journal-action", "Journal", "action",
                "Open tagged days.",
                "Or record on Twin if you would rather speak.",
                "journal", "twin"),
            T("interview", "Interview", "action",
                "Open the chapter interviewer.",
                "Structured memory, not free chat.",
                "interviewer", "chapter"),
            T("microphone", "Microphone", "action",
                "Open Mixer to pick the Heirloom input.",
                "Not the system default picker — this app’s session.",
                "mixer", "ptt"),
        };

        var map = new Dictionary<string, HelpTopic>(StringComparer.OrdinalIgnoreCase);
        foreach (var topic in list)
        {
            map[topic.Id] = topic;
        }

        map["action-new"] = map["new"];
        map["action-file"] = map["file"];
        map["action-undo"] = map["undo"];
        map["action-ask"] = map["ask"];
        map["action-mute"] = map["mute"];
        map["action-refresh"] = map["refresh"];
        map["action-import"] = map["import"];
        map["action-mixer"] = map["mixer"];
        map["action-archive"] = map["archive"];
        map["action-portrait"] = map["portrait"];
        map["action-abilities"] = map["abilities"];
        map["action-avatar"] = map["avatar"];
        map["action-twin"] = map["twin"];
        map["action-interview"] = map["interviewer"];
        map["action-journal"] = map["journal"];
        map["action-sources"] = map["sources"];
        map["action-prev"] = map["prev"];
        map["action-next"] = map["next"];
        map["action-skip"] = map["skip"];
        map["action-heir"] = map["heir"];
        map["action-export"] = map["export"];
        map["action-save"] = map["save"];
        map["action-folder"] = map["folder"];
        map["action-signout"] = map["signout"];
        map["action-setup"] = map["setup"];
        map["action-add"] = map["add"];
        map["action-lite"] = map["lite"];
        map["action-full"] = map["full"];
        map["action-studio"] = map["studio"];
        map["action-thispc"] = map["thispc"];
        map["action-network"] = map["network"];
        foreach (var id in new[]
                 {
                     "today", "archive", "twin", "mixer", "models", "journal", "interviewer", "photos",
                     "library", "import", "sources", "personality", "abilities", "skills", "avatar",
                     "heirs", "letters", "keys", "thismachine", "settings", "kitchensink", "glossary",
                 })
        {
            map["dock-" + id] = map[id];
        }

        return map;
    }
}
