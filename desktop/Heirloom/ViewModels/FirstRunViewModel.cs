using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using Heirloom.BoxCore;
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
        BoxUrl = string.IsNullOrWhiteSpace(host.Settings.Current.BoxUrl)
            ? BoxLink.DefaultBoxUrl
            : host.Settings.Current.BoxUrl;
        ResetToChoose();
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
    [ObservableProperty] private string _boxUrl = BoxLink.DefaultBoxUrl;
    [ObservableProperty] private string _boxEmail = "";
    [ObservableProperty] private string _boxPassword = "";
    [ObservableProperty] private string _boxFingerprint = "";
    [ObservableProperty] private bool _boxPinned;
    [ObservableProperty] private Visibility _chooseVis = Visibility.Visible;
    [ObservableProperty] private Visibility _boxVis = Visibility.Collapsed;
    [ObservableProperty] private Visibility _welcomeVis = Visibility.Collapsed;
    [ObservableProperty] private Visibility _workingVis = Visibility.Collapsed;
    [ObservableProperty] private Visibility _doneVis = Visibility.Collapsed;
    [ObservableProperty] private Visibility _faultVis = Visibility.Collapsed;
    [ObservableProperty] private Visibility _retryVis = Visibility.Collapsed;
    [ObservableProperty] private Visibility _stopVis = Visibility.Collapsed;

    public string WelcomeBody =>
        "Heirloom Unbound will get what it needs onto this computer. Four install sizes — Small, Medium, Large, Dedicated PC — are chosen from free disk. You do not need to type any codes.\n\n"
        + "Then clone your voice and take three photos of you. That is how the Twin becomes a live, talking picture of you — for sit, video, and a room later.\n\n"
        + "Windows may ask once if a helper can be installed. Choose Yes.\n\n"
        + "If you skip voice or photos, a reminder sits in the top-right. You can close it and reopen it from Help.";

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

    public void ResetToChoose()
    {
        try { _work?.Cancel(); } catch { /* disposed */ }
        Phase = "choose";
        Title = "Where should Heirloom run?";
        Body = "Run Heirloom on this PC, or connect to the Twin Box on your network. Assist on this computer stays here either way. A headset stays off until you turn Room VR on in Settings.";
        Fault = "";
        IsBusy = false;
        BoxPinned = false;
        BoxFingerprint = "";
        _pendingPin = "";
        _pendingPem = null;
        NotifyChrome();
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

        _host.Settings.Current.RunMode = BoxLink.Local;
        _host.Settings.Save();
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
            var profile = DiskProfiles.Resolve(plan.ProfileId);
            _host.Settings.Current.DiskProfile = profile.Id;
            _host.Settings.Current.InstallProfile = profile.Id;
            if (profile.MachineRole)
            {
                DedicatedRole.Apply(_host.Settings.Current, consent: true, vaultDrive: vault);
            }
            else
            {
                _host.Settings.Current.MachineRole = "daily";
            }

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
            _ = _host.Whisper.EnsureAsync();
            _ = _host.Ollama.ProbeAsync();
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

    [RelayCommand]
    public void ChooseThisPc()
    {
        _host.Settings.Current.RunMode = BoxLink.Local;
        _host.Settings.Save();
        Phase = "welcome";
        Title = "Let's get your Twin ready";
        Body = WelcomeBody;
        Fault = "";
        NotifyChrome();
    }

    [RelayCommand]
    public void ChooseBox()
    {
        Phase = "box";
        Title = "Connect to my Twin Box";
        Body = "Type the address printed for the box. Heirloom will show the certificate fingerprint. Pin it only if it matches the box. Then sign in with the owner email and password. This PC will not download models.";
        Fault = "";
        BoxPinned = false;
        BoxFingerprint = "";
        NotifyChrome();
    }

    [RelayCommand]
    public async Task CheckCertificateAsync()
    {
        if (IsBusy)
        {
            return;
        }

        IsBusy = true;
        Fault = "";
        BoxPinned = false;
        try
        {
            var offer = await BoxClient.OfferTrustAsync(BoxUrl).ConfigureAwait(true);
            _pendingPin = offer.PinSha256;
            _pendingPem = offer.CaPem;
            BoxFingerprint = FormatFingerprint(offer.PinSha256);
            Title = "Does this fingerprint match your box?";
        }
        catch (Exception ex)
        {
            _pendingPin = "";
            _pendingPem = null;
            BoxFingerprint = "";
            Fault = "Could not read the box certificate. " + ex.Message;
        }
        finally
        {
            IsBusy = false;
            NotifyChrome();
        }
    }

    [RelayCommand]
    public void ConfirmCertificate()
    {
        if (string.IsNullOrWhiteSpace(_pendingPin))
        {
            Fault = "Show the certificate first, then pin it.";
            return;
        }

        BoxPinned = true;
        Fault = "";
        Body = "Pinned. Sign in with the owner email and password for the box.";
    }

    [RelayCommand]
    public async Task ConnectBoxAsync()
    {
        if (IsBusy)
        {
            return;
        }

        if (!BoxPinned || string.IsNullOrWhiteSpace(_pendingPin))
        {
            Fault = "Pin the box certificate before signing in.";
            return;
        }

        IsBusy = true;
        Fault = "";
        try
        {
            var token = await BoxClient.LoginAsync(BoxUrl, BoxEmail, BoxPassword, _pendingPin, _pendingPem).ConfigureAwait(true);
            if (string.IsNullOrWhiteSpace(token))
            {
                Fault = "The box did not accept that email and password.";
                return;
            }

            var current = _host.Settings.Current;
            current.RunMode = BoxLink.Box;
            current.BoxUrl = BoxLink.Normalize(BoxUrl);
            current.BoxCertSha256 = _pendingPin;
            current.BoxCaPem = _pendingPem ?? "";
            current.SetupComplete = true;
            current.SetupSkipped = false;
            current.VrMode = false;
            current.VrGaze = false;
            _host.Settings.Save();
            BoxPassword = "";
            _host.Auth.SetSessionToken(token);
            RequestClose?.Invoke(this, "twin");
        }
        catch (Exception ex)
        {
            Fault = "Could not sign in to the box. " + ex.Message;
        }
        finally
        {
            IsBusy = false;
            NotifyChrome();
        }
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

    [RelayCommand]
    public void WriteFirstGift() => FinishInto("letters");

    private bool CanGetReady() => !IsBusy;
    private bool CanStop() => IsBusy;
    private bool CanSkip() => !IsBusy && (Phase == "welcome" || Phase == "choose");

    private string _pendingPin = "";
    private string? _pendingPem;

    private static string FormatFingerprint(string hex)
    {
        var clean = CertificatePin.Normalize(hex);
        var parts = new List<string>();
        for (var i = 0; i < clean.Length; i += 2)
        {
            parts.Add(clean.Substring(i, Math.Min(2, clean.Length - i)));
        }

        return string.Join(" ", parts);
    }
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
        ChooseVis = Phase == "choose" ? Visibility.Visible : Visibility.Collapsed;
        BoxVis = Phase == "box" ? Visibility.Visible : Visibility.Collapsed;
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
