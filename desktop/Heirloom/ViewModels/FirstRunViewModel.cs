using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using Heirloom.Services;
using Microsoft.UI.Xaml;

namespace Heirloom.ViewModels;

public partial class FirstRunViewModel : ObservableObject
{
    private readonly AppHost _host;
    private CancellationTokenSource? _work;

    public FirstRunViewModel(AppHost host)
    {
        _host = host;
        LibraryPath = host.Settings.Current.LibraryPath;
        ResetToWelcome();
    }

    public event EventHandler<string>? RequestClose;

    [ObservableProperty] private string _phase = "welcome";
    [ObservableProperty] private string _libraryPath = "";
    [ObservableProperty] private string _title = "Let's get your Twin ready";
    [ObservableProperty] private string _body = "";
    [ObservableProperty] private string _fault = "";
    [ObservableProperty] private string _summary = "";
    [ObservableProperty] private bool _isBusy;
    [ObservableProperty] private bool _hearingOk;
    [ObservableProperty] private bool _mindOk;
    [ObservableProperty] private string _vaultState = "Waiting";
    [ObservableProperty] private string _vaultDetail = "A folder for your stories";
    [ObservableProperty] private string _hearingState = "Waiting";
    [ObservableProperty] private string _hearingDetail = "So Hold to talk can hear you";
    [ObservableProperty] private string _mindState = "Waiting";
    [ObservableProperty] private string _mindDetail = "So your Twin can answer as you";
    [ObservableProperty] private string _pictureState = "Waiting";
    [ObservableProperty] private string _pictureDetail = "A moving likeness, if this computer can do it";
    [ObservableProperty] private Visibility _welcomeVis = Visibility.Visible;
    [ObservableProperty] private Visibility _workingVis = Visibility.Collapsed;
    [ObservableProperty] private Visibility _doneVis = Visibility.Collapsed;
    [ObservableProperty] private Visibility _faultVis = Visibility.Collapsed;
    [ObservableProperty] private Visibility _retryVis = Visibility.Collapsed;
    [ObservableProperty] private Visibility _stopVis = Visibility.Collapsed;

    public string WelcomeBody =>
        "Heirloom will get what it needs onto this computer. You do not need to pick anything or type any codes.\n\n"
        + "Windows may ask once if a helper can be installed. Choose Yes.\n\n"
        + "The first time can take a while. You can leave this window open.";

    partial void OnPhaseChanged(string value) => NotifyChrome();

    partial void OnIsBusyChanged(bool value)
    {
        NotifyChrome();
        GetReadyCommand.NotifyCanExecuteChanged();
        StopCommand.NotifyCanExecuteChanged();
        SkipCommand.NotifyCanExecuteChanged();
        RetryCommand.NotifyCanExecuteChanged();
    }

    partial void OnFaultChanged(string value)
    {
        FaultVis = string.IsNullOrWhiteSpace(value) ? Visibility.Collapsed : Visibility.Visible;
        NotifyChrome();
        RetryCommand.NotifyCanExecuteChanged();
    }

    public void ResetToWelcome()
    {
        try { _work?.Cancel(); } catch { /* disposed */ }
        Phase = "welcome";
        Title = "Let's get your Twin ready";
        Body = WelcomeBody;
        Fault = "";
        Summary = "";
        IsBusy = false;
        HearingOk = false;
        MindOk = false;
        SetTask(SetupTasks.Vault, "Waiting", "A folder for your stories");
        SetTask(SetupTasks.Hearing, "Waiting", "So Hold to talk can hear you");
        SetTask(SetupTasks.Mind, "Waiting", "So your Twin can answer as you");
        SetTask(SetupTasks.Picture, "Waiting", "A moving likeness, if this computer can do it");
        NotifyChrome();
    }

    [RelayCommand(CanExecute = nameof(CanGetReady))]
    public async Task GetReadyAsync()
    {
        if (IsBusy)
        {
            return;
        }

        IsBusy = true;
        Fault = "";
        Phase = "working";
        Title = "Getting things ready";
        Body = "This can take a while the first time. You can leave this window open.";
        SetTask(SetupTasks.Vault, "Waiting", "A folder for your stories");
        SetTask(SetupTasks.Hearing, "Waiting", "So Hold to talk can hear you");
        SetTask(SetupTasks.Mind, "Waiting", "So your Twin can answer as you");
        SetTask(SetupTasks.Picture, "Waiting", "A moving likeness, if this computer can do it");

        _work?.Dispose();
        _work = new CancellationTokenSource();
        var ct = _work.Token;
        try
        {
            var vault = string.IsNullOrWhiteSpace(LibraryPath) ? AppPaths.DefaultVaultPath : LibraryPath;
            var plan = SetupCopy.PlanForPath(vault);
            _host.Settings.Current.MachineRole = "daily";
            _host.Settings.Current.DiskProfile = plan.ProfileId;
            _host.Settings.Save();
            _host.SetVaultPath(vault);
            LibraryPath = _host.Settings.Current.LibraryPath;

            var progress = new Progress<SetupProgress>(OnProgress);
            var report = await _host.Provision.PrepareThisPcAsync(plan, progress, ct).ConfigureAwait(true);
            HearingOk = report.HearingOk;
            MindOk = report.MindOk;
            _host.Settings.Current.SetupComplete = report.VaultOk;
            _host.Settings.Current.SetupSkipped = false;
            _host.Settings.Save();
            Title = report.Headline;
            Body = report.Body;
            Summary = CountReady();
            Phase = "done";
        }
        catch (OperationCanceledException) when (ct.IsCancellationRequested)
        {
            Phase = "welcome";
            Title = "Let's get your Twin ready";
            Body = WelcomeBody;
            Fault = SetupCopy.HumanFault(new OperationCanceledException(), "getting Heirloom ready", ct);
        }
        catch (Exception ex)
        {
            Fault = SetupCopy.HumanFault(ex, "getting Heirloom ready", ct);
            Title = "Something paused";
            Body = Fault;
        }
        finally
        {
            IsBusy = false;
            NotifyChrome();
        }
    }

    [RelayCommand(CanExecute = nameof(CanStop))]
    public void Stop()
    {
        try { _work?.Cancel(); } catch { /* disposed */ }
    }

    [RelayCommand(CanExecute = nameof(CanSkip))]
    public void Skip()
    {
        _host.Settings.Current.SetupSkipped = true;
        _host.Settings.Save();
        RequestClose?.Invoke(this, "twin");
    }

    [RelayCommand(CanExecute = nameof(CanRetry))]
    public async Task RetryAsync() => await GetReadyAsync().ConfigureAwait(true);

    [RelayCommand]
    public void Talk() => FinishInto("twin");

    [RelayCommand]
    public void RecordMemory() => FinishInto("interviewer");

    [RelayCommand]
    public void MakeLikeness() => FinishInto("avatar");

    private bool CanGetReady() => !IsBusy;
    private bool CanStop() => IsBusy;
    private bool CanSkip() => !IsBusy && Phase == "welcome";
    private bool CanRetry() => !IsBusy && (Phase == "working" && !string.IsNullOrWhiteSpace(Fault) || Phase == "done" && !MindOk);

    private void FinishInto(string room)
    {
        _host.Settings.Current.SetupComplete = true;
        _host.Settings.Current.SetupSkipped = false;
        _host.Settings.Save();
        RequestClose?.Invoke(this, room);
    }

    private void OnProgress(SetupProgress update)
    {
        SetTask(update.TaskId, TitleCase(update.State), update.Detail);
        Summary = CountReady();
    }

    private void SetTask(string id, string state, string detail)
    {
        switch (id)
        {
            case SetupTasks.Vault:
                VaultState = state;
                VaultDetail = detail;
                break;
            case SetupTasks.Hearing:
                HearingState = state;
                HearingDetail = detail;
                break;
            case SetupTasks.Mind:
                MindState = state;
                MindDetail = detail;
                break;
            case SetupTasks.Picture:
                PictureState = state;
                PictureDetail = detail;
                break;
        }
    }

    private string CountReady()
    {
        var n = 0;
        if (IsReady(VaultState)) n++;
        if (IsReady(HearingState)) n++;
        if (IsReady(MindState)) n++;
        if (IsReady(PictureState)) n++;
        return n + " of 4 ready";
    }

    private static bool IsReady(string state) =>
        state.Equals("Ready", StringComparison.OrdinalIgnoreCase);

    private static string TitleCase(string state) => state.ToLowerInvariant() switch
    {
        "working" => "Working",
        "ready" => "Ready",
        "skipped" => "Later",
        "failed" => "Needs a moment",
        _ => "Waiting",
    };

    private void NotifyChrome()
    {
        WelcomeVis = Phase == "welcome" ? Visibility.Visible : Visibility.Collapsed;
        WorkingVis = Phase == "working" ? Visibility.Visible : Visibility.Collapsed;
        DoneVis = Phase == "done" ? Visibility.Visible : Visibility.Collapsed;
        StopVis = IsBusy ? Visibility.Visible : Visibility.Collapsed;
        RetryVis = !IsBusy && (Phase == "working" && !string.IsNullOrWhiteSpace(Fault) || Phase == "done" && !MindOk)
            ? Visibility.Visible
            : Visibility.Collapsed;
        SkipCommand.NotifyCanExecuteChanged();
        RetryCommand.NotifyCanExecuteChanged();
        StopCommand.NotifyCanExecuteChanged();
        GetReadyCommand.NotifyCanExecuteChanged();
        OnPropertyChanged(nameof(WelcomeBody));
    }
}
