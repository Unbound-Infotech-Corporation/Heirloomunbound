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
        Refresh();
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
    public void Refresh()
    {
        WhisperStatus = _host.Whisper.Status;
        OllamaStatus = _host.Ollama.Status;
        VaultStatus = _host.Vault.Status;
        DiskLine = ReadDisk();
    }

    [RelayCommand]
    public void SetCompute(string target) => ComputeTarget = target;

    [RelayCommand]
    public void SetRole(string role) => MachineRole = role;

    [RelayCommand]
    public async Task ProvisionAsync(string profileId)
    {
        var profile = DiskProfiles.All.First(p => p.Id == profileId);
        Busy = true;
        var progress = new Progress<string>(m => Progress = m);
        await _host.Provision.ProvisionAsync(profile, progress).ConfigureAwait(true);
        _host.Settings.Current.DiskProfile = profileId;
        _host.Settings.Save();
        Refresh();
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
