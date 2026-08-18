using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using Heirloom.Services;
using Microsoft.UI.Xaml;

namespace Heirloom.ViewModels;

public partial class FirstRunViewModel : ObservableObject
{
    private readonly AppHost _host;

    public FirstRunViewModel(AppHost host)
    {
        _host = host;
        SelectedProfileId = host.Settings.Current.DiskProfile;
        MachineRole = host.Settings.Current.MachineRole;
        LibraryPath = host.Settings.Current.LibraryPath;
        BackendUrl = host.Settings.Current.BackendUrl;
        DeviceToken = host.Credentials.DeviceToken ?? "";
        SessionToken = host.Credentials.SessionToken ?? "";
        VendorEmail = host.Settings.Current.VendorEmail;
        NotifyStep();
    }

    public IReadOnlyList<DiskProfile> Profiles => DiskProfiles.All;

    [ObservableProperty] private int _step;
    [ObservableProperty] private string _selectedProfileId;
    [ObservableProperty] private string _machineRole;
    [ObservableProperty] private string _libraryPath;
    [ObservableProperty] private string _backendUrl;
    [ObservableProperty] private string _sessionToken;
    [ObservableProperty] private string _deviceToken;
    [ObservableProperty] private string _vendorEmail = "";
    [ObservableProperty] private string _progress = "";
    [ObservableProperty] private Visibility _roleVis = Visibility.Visible;
    [ObservableProperty] private Visibility _diskVis = Visibility.Collapsed;
    [ObservableProperty] private Visibility _pairVis = Visibility.Collapsed;
    [ObservableProperty] private Visibility _keysVis = Visibility.Collapsed;

    public string StepTitle => Step switch
    {
        0 => "This machine",
        1 => "Disk for the brain",
        2 => "Sign in & pair",
        3 => "Cloud keys",
        _ => "Ready",
    };

    public string StepCaption => $"Step {Step + 1} of 4";

    partial void OnStepChanged(int value) => NotifyStep();

    [RelayCommand]
    public void Next()
    {
        Step = Math.Min(3, Step + 1);
    }

    [RelayCommand]
    public void Back()
    {
        Step = Math.Max(0, Step - 1);
    }

    [RelayCommand]
    public void ChooseRole(string role) => MachineRole = role;

    [RelayCommand]
    public void ChooseProfile(string id) => SelectedProfileId = id;

    [RelayCommand]
    public async Task OpenSignInAsync() => await _host.Auth.OpenSignInAsync();

    [RelayCommand]
    public async Task PairAsync()
    {
        _host.Settings.Current.BackendUrl = BackendUrl.Trim();
        _host.Settings.Save();
        if (!string.IsNullOrWhiteSpace(SessionToken))
        {
            _host.Auth.SetSessionToken(SessionToken);
            DeviceToken = await _host.Auth.RegisterDeviceAsync(Environment.MachineName) ?? DeviceToken;
        }

        if (!string.IsNullOrWhiteSpace(DeviceToken))
        {
            _host.Auth.SetDeviceToken(DeviceToken);
        }
    }

    [RelayCommand]
    public async Task FinishAsync()
    {
        _host.Settings.Current.DiskProfile = SelectedProfileId;
        _host.Settings.Current.MachineRole = MachineRole;
        _host.Settings.Current.LibraryPath = LibraryPath;
        _host.Settings.Current.VendorEmail = VendorEmail.Trim().ToLowerInvariant();
        _host.Settings.Current.SetupComplete = true;
        _host.Settings.Save();
        _host.Vault.Open();
        var profile = DiskProfiles.All.First(p => p.Id == SelectedProfileId);
        var progress = new Progress<string>(m => Progress = m);
        await _host.Provision.ProvisionAsync(profile, progress).ConfigureAwait(true);
    }

    [RelayCommand]
    public void Skip()
    {
        _host.Settings.Current.SetupSkipped = true;
        _host.Settings.Save();
    }

    private void NotifyStep()
    {
        RoleVis = Step == 0 ? Visibility.Visible : Visibility.Collapsed;
        DiskVis = Step == 1 ? Visibility.Visible : Visibility.Collapsed;
        PairVis = Step == 2 ? Visibility.Visible : Visibility.Collapsed;
        KeysVis = Step == 3 ? Visibility.Visible : Visibility.Collapsed;
        OnPropertyChanged(nameof(StepTitle));
        OnPropertyChanged(nameof(StepCaption));
    }
}
