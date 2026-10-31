using System.Text.Json;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using Heirloom.BoxCore;
using Heirloom.Services;

namespace Heirloom.ViewModels;

public partial class ModelsViewModel : ObservableObject
{
    private readonly AppHost _host;

    public ModelsViewModel(AppHost host)
    {
        _host = host;
        ComputeTarget = host.Settings.Current.ComputeTarget;
        MachineRole = host.Settings.Current.MachineRole;
        _ = RefreshAsync();
    }

    public IReadOnlyList<DiskProfile> Profiles => DiskProfiles.All;

    [ObservableProperty] private string _whisperStatus = "";
    [ObservableProperty] private string _ollamaStatus = "";
    [ObservableProperty] private string _vaultStatus = "";
    [ObservableProperty] private string _diskLine = "";
    [ObservableProperty] private string _computeTarget;
    [ObservableProperty] private string _machineRole;
    [ObservableProperty] private string _progress = "";
    [ObservableProperty] private bool _busy;
    [ObservableProperty] private string _guide =
        "If you already tapped Get everything ready, you can leave this page. These buttons are extra controls.";
    [ObservableProperty] private string _brainUrl = "";
    [ObservableProperty] private string _brainModel = "llama3.3:70b";
    [ObservableProperty] private string _brainToken = "";
    [ObservableProperty] private string _brainLine = "Local box brain until a LAN address is saved.";

    partial void OnComputeTargetChanged(string value)
    {
        _host.Settings.Current.ComputeTarget = value;
        _host.Settings.Save();
    }

    partial void OnMachineRoleChanged(string value)
    {
        _host.Settings.Current.MachineRole = value;
        _host.Settings.Save();
    }

    [RelayCommand]
    public async Task RefreshAsync()
    {
        await _host.Ollama.ProbeAsync().ConfigureAwait(true);
        WhisperStatus = SetupCopy.FriendlyLine(_host.Whisper.Status);
        OllamaStatus = SetupCopy.FriendlyLine(_host.Ollama.Status);
        VaultStatus = _host.Vault.Status;
        DiskLine = ReadDisk();
        await LoadBrainAsync().ConfigureAwait(true);
    }

    [RelayCommand]
    public async Task SaveBrainAsync()
    {
        if (!_host.CanEdit)
        {
            BrainLine = "Heir mode. Brain routing stays with the owner.";
            return;
        }

        var url = (BrainUrl ?? "").Trim();
        if (url.Length > 0)
        {
            if (!BrainRoute.TryNormalizeLanUrl(url, out var normalized, out var error))
            {
                BrainLine = error;
                return;
            }

            BrainUrl = normalized;
            url = normalized;
        }

        var model = string.IsNullOrWhiteSpace(BrainModel) ? "llama3.3:70b" : BrainModel.Trim();
        var result = await _host.Api.PutSessionAsync("/brain", new
        {
            url,
            model,
            token = BrainToken ?? "",
        }).ConfigureAwait(true);
        if (result is null)
        {
            BrainLine = string.IsNullOrWhiteSpace(_host.Api.LastFailure)
                ? "The box did not save the brain."
                : _host.Api.LastFailure;
            return;
        }

        BrainToken = "";
        ApplyBrain(result.Value);
    }

    private async Task LoadBrainAsync()
    {
        if (!_host.CanEdit)
        {
            BrainLine = "Heir mode. Brain routing stays with the owner.";
            return;
        }

        var brain = await _host.Api.GetSessionAsync("/brain").ConfigureAwait(true);
        if (brain is not null)
        {
            ApplyBrain(brain.Value);
        }

        var health = await _host.Api.GetSessionAsync("/health").ConfigureAwait(true);
        if (health is null || !health.Value.TryGetProperty("brain", out var block))
        {
            return;
        }

        var answered = block.TryGetProperty("answered", out var name) ? name.GetString() : "";
        var model = block.TryGetProperty("model_in_use", out var inUse) ? inUse.GetString() : "";
        if (!string.IsNullOrWhiteSpace(answered))
        {
            BrainLine = string.IsNullOrWhiteSpace(model)
                ? "Last answer: " + answered
                : "Last answer: " + answered + " · " + model;
        }
    }

    private void ApplyBrain(JsonElement brain)
    {
        if (brain.TryGetProperty("url", out var url))
        {
            BrainUrl = url.GetString() ?? "";
        }

        if (brain.TryGetProperty("model", out var model) && !string.IsNullOrWhiteSpace(model.GetString()))
        {
            BrainModel = model.GetString() ?? BrainModel;
        }

        var tokenSet = brain.TryGetProperty("token_set", out var flag) && flag.ValueKind == JsonValueKind.True;
        var answered = brain.TryGetProperty("answered", out var name) ? name.GetString() : "";
        BrainLine = tokenSet
            ? "LAN brain saved. A token is set. Last answer: " + (string.IsNullOrWhiteSpace(answered) ? "none yet" : answered)
            : "LAN brain saved. Last answer: " + (string.IsNullOrWhiteSpace(answered) ? "none yet" : answered);
    }

    [RelayCommand]
    public void SetCompute(string target) => ComputeTarget = target;

    [RelayCommand]
    public void SetRole(string role) => MachineRole = role;

    [RelayCommand]
    public async Task GetReadyAsync()
    {
        Busy = true;
        Progress = "Getting this computer ready…";
        var plan = SetupCopy.PlanForPath(_host.Settings.Current.LibraryPath);
        var progress = new Progress<SetupProgress>(p => Progress = p.Detail);
        try
        {
            await _host.Provision.PrepareThisPcAsync(plan, progress).ConfigureAwait(true);
        }
        catch (Exception ex)
        {
            Progress = SetupCopy.HumanFault(ex, "getting Heirloom ready");
        }

        await RefreshAsync().ConfigureAwait(true);
        Busy = false;
    }

    [RelayCommand]
    public async Task ProvisionAsync(string profileId)
    {
        var profile = DiskProfiles.Resolve(profileId);
        Busy = true;
        var progress = new Progress<string>(m => Progress = SetupCopy.FriendlyLine(m));
        await _host.Provision.ProvisionAsync(profile, progress, allowInstall: true).ConfigureAwait(true);
        _host.Settings.Current.DiskProfile = profile.Id;
        _host.Settings.Current.InstallProfile = profile.Id;
        if (profile.MachineRole)
        {
            DedicatedRole.Apply(_host.Settings.Current, consent: true, vaultDrive: _host.Settings.Current.LibraryPath);
        }

        _host.Settings.Save();
        await RefreshAsync().ConfigureAwait(true);
        Busy = false;
    }

    private string ReadDisk()
    {
        try
        {
            var root = Path.GetPathRoot(_host.Settings.Current.LibraryPath);
            if (string.IsNullOrWhiteSpace(root))
            {
                return "Disk unknown";
            }

            var drive = new DriveInfo(root);
            var free = drive.AvailableFreeSpace / 1_000_000_000d;
            var total = drive.TotalSize / 1_000_000_000d;
            return $"{free:0} GB free of {total:0} GB on {drive.Name.TrimEnd('\\')}";
        }
        catch
        {
            return "Disk unknown";
        }
    }
}
