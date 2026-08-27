using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
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
        var profile = DiskProfiles.All.First(p => p.Id == profileId);
        Busy = true;
        var progress = new Progress<string>(m => Progress = SetupCopy.FriendlyLine(m));
        await _host.Provision.ProvisionAsync(profile, progress, allowInstall: true).ConfigureAwait(true);
        _host.Settings.Current.DiskProfile = profileId;
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
