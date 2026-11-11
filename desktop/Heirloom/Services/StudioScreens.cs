namespace Heirloom.Services;

/// <summary>
/// State for the Setup, Home, Writing, and Code documents.
/// The windows bind to these types. Secrets and the backup passphrase
/// never appear in <see cref="SetupCenterModel.PublicSnapshot"/>.
/// </summary>
public sealed class SetupCenterModel
{
    private string _passphrase = "";

    public static IReadOnlyList<GuidePage> Guides { get; } =
    [
        new("huggingface", "Hugging Face download token", "https://huggingface.co/settings/tokens", true,
            "A key for downloading model files. It does not chat."),
        new("home_assistant", "Home Assistant", "http://homeassistant.local:8123/profile/security", true,
            "Optional bridge. Use the address on your home network."),
        new("resend", "Resend", "https://resend.com/api-keys", true,
            "Optional. Drafts stay here until you approve a send."),
        new("hue", "Philips Hue", "https://account.meethue.com/", false,
            "On your network, press the button on the bridge. The website is optional."),
        new("kasa", "TP-Link Kasa", "https://www.tplinkcloud.com/", false,
            "Kasa plugs are controlled on your home network."),
        new("shelly", "Shelly", "https://control.shelly.cloud/", false,
            "Shelly relays speak on your network. A cloud account is optional."),
        new("wiz", "WiZ", "https://www.wizconnected.com/", false,
            "WiZ lights need no account."),
        new("ollama", "Ollama", "https://ollama.com/download", false,
            "The local program that runs the twin."),
        new("nvidia", "NVIDIA driver", "https://www.nvidia.com/Download/index.aspx", false,
            "Only if Windows has not already installed a driver."),
        new("firewall", "Windows firewall", "ms-settings:network-firewall", false,
            "Allow Heirloom on private networks if Windows asks."),
        new("languagetool", "LanguageTool on this PC", "https://languagetool.org/download/", false,
            "Optional. Heirloom will not send writing to the public site."),
    ];

    public IReadOnlyList<SetupRow> Steps { get; private set; } = [];
    public GuidePage? Selected { get; private set; } = Guides[0];
    public string SecretDetail { get; private set; } = "Paste a key only if a step asks.";
    public string MaskedSecret { get; private set; } = "";
    public string RestoreDetail { get; private set; } = "Point at the backup folder, or at D:\\TwinBackup.";
    public bool HasPassphrase => _passphrase.Length > 0;

    public void Load(SetupSignals signals)
    {
        Steps =
        [
            Row("This PC", signals.HardwareOk ? "Ready" : "Needs you", signals.HardwareLine),
            Row("Hearing", signals.WhisperReady ? "Ready" : "Needs you", "The download resumes if it stops."),
            Row("Talking mind", signals.OllamaReady ? "Ready" : "Needs you", "Local Ollama. No hosted chat model."),
            Row("Voice", signals.VoiceReady ? "Ready" : "Needs you", "Local voice on this PC."),
            Row("Companion", signals.CompanionPaired ? "Ready" : "Needs you", "Paste the device token."),
            Row("Start with Windows", signals.StartupEnabled ? "Ready" : "Needs you", "Optional."),
            Row("Backup", signals.BackupSeen ? "Ready" : "Needs you", "Full backup, then each incremental."),
            Row("Smart home", "Optional", "Lights, plugs, and thermostats on your network."),
            Row("Writing", "Ready", "Spelling and the dictionary work offline."),
        ];
    }

    public IReadOnlyList<SetupRow> Repair(SetupSignals signals)
    {
        var steps = new List<SetupRow>();
        if (!signals.WhisperReady)
        {
            steps.Add(Row("Hearing", "Repair", "Download hearing again. It resumes."));
        }

        if (!signals.OllamaReady)
        {
            steps.Add(Row("Talking mind", "Repair", "Open Ollama on this PC."));
        }

        if (!signals.CompanionPaired)
        {
            steps.Add(Row("Companion", "Repair", "Paste the device token again."));
        }

        if (steps.Count == 0)
        {
            steps.Add(Row("Repair", "Ready", "Nothing to repair."));
        }

        return steps;
    }

    public bool Select(string id)
    {
        Selected = Guides.FirstOrDefault(guide => guide.Id == id);
        return Selected is not null;
    }

    public string? OpenUrl() => string.IsNullOrWhiteSpace(Selected?.Url) ? null : Selected.Url;

    public bool Paste(string flowId, string secret, string? baseUrl)
    {
        if (StudioPolicy.CloudModelKey(flowId))
        {
            SecretDetail = "Cloud model keys stay an owner decision. They are not stored.";
            MaskedSecret = "";
            return false;
        }

        var guide = Guides.FirstOrDefault(item => item.Id == flowId);
        if (guide is null || !guide.Paste)
        {
            SecretDetail = "That page does not take a pasted key.";
            return false;
        }

        if (string.IsNullOrWhiteSpace(secret))
        {
            SecretDetail = "Paste the key first.";
            return false;
        }

        if (flowId == "huggingface" && !secret.Trim().StartsWith("hf_", StringComparison.Ordinal))
        {
            MaskedSecret = StudioPolicy.MaskSecret(secret);
            SecretDetail = "A Hugging Face token usually starts with hf_.";
            return false;
        }

        if (flowId == "home_assistant" && !IsHomeAddress(baseUrl))
        {
            MaskedSecret = StudioPolicy.MaskSecret(secret);
            SecretDetail = "Home Assistant stays on your home network.";
            return false;
        }

        MaskedSecret = StudioPolicy.MaskSecret(secret);
        SecretDetail = "Saved on this PC. The log only says [redacted].";
        return true;
    }

    public void SetPassphrase(string? value) => _passphrase = value ?? "";

    public void ClearPassphrase() => _passphrase = "";

    public string ConsumePassphrase()
    {
        var value = _passphrase;
        _passphrase = "";
        return value;
    }

    public string PublicSnapshot()
    {
        return string.Join(" | ", new[]
        {
            Selected?.Title ?? "",
            MaskedSecret,
            SecretDetail,
            RestoreDetail,
            HasPassphrase ? "passphrase entered" : "no passphrase",
        });
    }

    public override string ToString() => "Setup";

    private static SetupRow Row(string title, string status, string detail) => new(title, status, detail);

    private static bool IsHomeAddress(string? url)
    {
        if (string.IsNullOrWhiteSpace(url))
        {
            return false;
        }

        var host = url.Trim().ToLowerInvariant();
        return host.Contains("127.0.0.1", StringComparison.Ordinal)
            || host.Contains("localhost", StringComparison.Ordinal)
            || host.Contains(".local", StringComparison.Ordinal)
            || host.Contains("192.168.", StringComparison.Ordinal)
            || host.Contains("10.", StringComparison.Ordinal);
    }
}

public sealed record GuidePage(string Id, string Title, string Url, bool Paste, string Plain);

public sealed record SetupRow(string Title, string Status, string Detail);

public sealed record SetupSignals(
    bool HardwareOk,
    bool WhisperReady,
    bool OllamaReady,
    bool VoiceReady,
    bool CompanionPaired,
    bool StartupEnabled,
    bool BackupSeen,
    string HardwareLine);

public sealed record TextSegment(string Text, bool Underline, string Kind, string Suggestion);

public sealed class WritingModel
{
    public string Text { get; private set; } = "";
    public IReadOnlyList<TextSegment> Segments { get; private set; } = [];
    public string LookupLine { get; private set; } = "Select a word.";
    public bool PasteApproved { get; private set; }
    public string Proposal { get; private set; } = "";

    public void Check(string text)
    {
        Text = text ?? "";
        var issues = Find(Text);
        Segments = Slice(Text, issues);
    }

    public string Rewrite(string mode)
    {
        var updated = Text;
        if (mode == "shorter")
        {
            foreach (var word in new[] { "very ", "really ", "just ", "actually ", "basically " })
            {
                updated = Replace(updated, word, "");
            }

            updated = Replace(updated, "in order to", "to");
        }
        else if (mode == "friendlier")
        {
            updated = updated.Replace("do not", "don't", StringComparison.OrdinalIgnoreCase)
                .Replace("I am", "I'm", StringComparison.Ordinal)
                .Replace("I would", "I'd", StringComparison.Ordinal);
        }
        else if (mode == "formal")
        {
            updated = Replace(updated, "gonna", "going to").Replace("wanna", "want to", StringComparison.OrdinalIgnoreCase)
                .Replace("don't", "do not", StringComparison.OrdinalIgnoreCase);
        }

        Proposal = updated.Trim();
        PasteApproved = false;
        return Proposal;
    }

    public bool ApprovePaste()
    {
        PasteApproved = Proposal.Length > 0;
        return PasteApproved;
    }

    public string? PasteBack() => PasteApproved ? Proposal : null;

    public void Define(string word)
    {
        var key = (word ?? "").Trim().ToLowerInvariant();
        LookupLine = key switch
        {
            "happy" => "Happy — feeling glad. Glad, pleased. Opposite: sad.",
            "home" => "Home — the place you live.",
            _ => "No offline entry for that word yet.",
        };
    }

    private static List<(int Start, int End, string Kind, string Suggestion)> Find(string text)
    {
        var issues = new List<(int, int, string, string)>();
        foreach (var pair in new Dictionary<string, string>
        {
            ["recieve"] = "receive",
            ["teh"] = "the",
            ["seperate"] = "separate",
        })
        {
            var at = text.IndexOf(pair.Key, StringComparison.OrdinalIgnoreCase);
            if (at >= 0)
            {
                issues.Add((at, at + pair.Key.Length, "spelling", pair.Value));
            }
        }

        return issues;
    }

    public static IReadOnlyList<TextSegment> Slice(string text, IReadOnlyList<(int Start, int End, string Kind, string Suggestion)> issues)
    {
        var ordered = issues.OrderBy(issue => issue.Start).ToList();
        var segments = new List<TextSegment>();
        var cursor = 0;
        foreach (var issue in ordered)
        {
            if (issue.Start < cursor || issue.End > text.Length)
            {
                continue;
            }

            if (issue.Start > cursor)
            {
                segments.Add(new TextSegment(text[cursor..issue.Start], false, "", ""));
            }

            segments.Add(new TextSegment(text[issue.Start..issue.End], true, issue.Kind, issue.Suggestion));
            cursor = issue.End;
        }

        if (cursor < text.Length)
        {
            segments.Add(new TextSegment(text[cursor..], false, "", ""));
        }

        return segments;
    }

    private static string Replace(string text, string oldValue, string newValue) =>
        text.Replace(oldValue, newValue, StringComparison.OrdinalIgnoreCase);
}

public sealed class SmartHomeModel
{
    public List<HomeDevice> Devices { get; } = [];
    public string Status { get; private set; } = "Press Scan. Heirloom looks on your home network.";
    public string Pending { get; private set; } = "";

    public void Show(IEnumerable<HomeDevice> devices)
    {
        Devices.Clear();
        Devices.AddRange(devices);
        Status = Devices.Count == 0
            ? "Nothing answered yet. You can type an address."
            : Devices.Count + " found on your network.";
    }

    public bool Change(HomeDevice device, string action, bool approved, bool criticalConfirm, bool alwaysAllow, double? value = null)
    {
        var critical = device.Critical || StudioPolicy.IsCritical(device.Name, device.Role);
        var off = action is "off" or "thermostat_off";
        if (off && !StudioPolicy.MayTurnOff(critical, approved, criticalConfirm, alwaysAllow, device.Kind == "thermostat" && action == "thermostat_off"))
        {
            Pending = critical || device.Kind == "thermostat"
                ? "This looks important. Confirm before turning it off."
                : "Waiting for Confirm.";
            return false;
        }

        if (device.Kind == "thermostat" && value is not null && action is "set_heat" or "set_cool")
        {
            var clamped = StudioPolicy.ClampSetpoint(action == "set_heat" ? "heat" : "cool", value.Value);
            Pending = clamped.Limited ? clamped.Reason : "Set to " + clamped.Applied + "°.";
            return approved || alwaysAllow;
        }

        if (!approved && !alwaysAllow)
        {
            Pending = "Waiting for Confirm.";
            return false;
        }

        Pending = action == "off" ? "Turned off." : "Turned on.";
        return true;
    }
}

public sealed record HomeDevice(string Id, string Name, string Vendor, string Kind, bool Critical = false, string Role = "");

public sealed class CodeWorkspaceModel
{
    public List<string> Files { get; } = [];
    public string Editor { get; set; } = "";
    public string Coder { get; private set; } = "No local coder yet. Pull qwen2.5-coder in Ollama.";
    public List<CodeHunk> Hunks { get; } = [];
    public string CommandDetail { get; private set; } = "Commands wait for Confirm.";
    public bool CommandAllowed { get; private set; }
    public string GitDetail { get; private set; } = "Git status appears here.";
    public List<string> AgentSteps { get; } = ["Read the files.", "Propose edits.", "Run tests after you confirm.", "Tell you what changed."];

    public void Open(IEnumerable<string> files)
    {
        Files.Clear();
        foreach (var file in files)
        {
            var name = Path.GetFileName(file);
            if (name is ".env" or "odysseus.token" or "box.env")
            {
                continue;
            }

            Files.Add(file);
        }
    }

    public void UseCoder(IEnumerable<string> tags)
    {
        var picked = StudioPolicy.PickCoder(tags);
        Coder = picked is null
            ? "No local coder yet. Pull qwen2.5-coder in Ollama. The twin's brain is left alone."
            : "Local coder: " + picked;
    }

    public void Propose(string before, string after)
    {
        Hunks.Clear();
        if (before == after)
        {
            return;
        }

        Hunks.Add(new CodeHunk("h1", before, after, false));
    }

    public string ApplyAccepted()
    {
        var text = Hunks.Count == 0 ? Editor : Hunks[0].Before;
        foreach (var hunk in Hunks.Where(item => item.Accepted))
        {
            text = hunk.After;
        }

        Editor = text;
        return text;
    }

    public bool ReviewCommand(string command, bool approved)
    {
        if (StudioPolicy.CommandBlocked(command))
        {
            CommandAllowed = false;
            CommandDetail = "That command can damage this PC. Heirloom will not run it.";
            return false;
        }

        if (!approved)
        {
            CommandAllowed = false;
            CommandDetail = "Waiting for Confirm before running this command.";
            return false;
        }

        CommandAllowed = true;
        CommandDetail = "Confirmed. The terminal may run it on this PC.";
        return true;
    }

    public void ShowGit(IEnumerable<string> lines)
    {
        GitDetail = string.Join("\n", lines);
    }
}

public sealed record CodeHunk(string Id, string Before, string After, bool Accepted)
{
    public bool Accepted { get; set; } = Accepted;
}
