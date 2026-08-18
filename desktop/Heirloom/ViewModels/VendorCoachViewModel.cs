using System.Diagnostics;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using Heirloom.Services;
using Microsoft.UI.Xaml;

namespace Heirloom.ViewModels;

public partial class VendorCoachViewModel : ObservableObject
{
    private readonly AppHost _host;
    private IReadOnlyList<VendorService> _queue = [];
    private int _svc;
    private int _step;
    private CancellationTokenSource? _watch;

    public VendorCoachViewModel(AppHost host) => _host = host;

    [ObservableProperty] private bool _isOpen;
    [ObservableProperty] private string _overline = "Vendor guide";
    [ObservableProperty] private string _title = "";
    [ObservableProperty] private string _body = "";
    [ObservableProperty] private string _bullets = "";
    [ObservableProperty] private string _cta = "Continue";
    [ObservableProperty] private string _skipCta = "";
    [ObservableProperty] private string _hint = "You click Create account, I'm not a robot, and Verify. Heirloom never drives their page.";
    [ObservableProperty] private string _draftKey = "";
    [ObservableProperty] private bool _isPasteStep;
    [ObservableProperty] private Visibility _pasteVis = Visibility.Collapsed;
    [ObservableProperty] private string _placeholder = "";

    partial void OnIsPasteStepChanged(bool value) =>
        PasteVis = value ? Visibility.Visible : Visibility.Collapsed;

    public void Start(string email)
    {
        _host.Settings.Current.VendorEmail = email.Trim().ToLowerInvariant();
        _host.Settings.Save();
        _queue = VendorCatalog.ServicesFor(_host.Settings.Current.VendorEmail);
        _svc = 0;
        _step = 0;
        IsOpen = _queue.Count > 0;
        Render(openPage: true);
        StartWatch();
    }

    public void Stop()
    {
        _watch?.Cancel();
        IsOpen = false;
    }

    [RelayCommand]
    public async Task ContinueAsync()
    {
        if (IsPasteStep)
        {
            await SaveKeyAsync().ConfigureAwait(true);
        }

        Advance();
    }

    [RelayCommand]
    public void Skip() => Advance();

    [RelayCommand]
    public void ReopenPage()
    {
        var step = CurrentStep();
        if (step is { OpenUrl.Length: > 0 })
        {
            Process.Start(new ProcessStartInfo(step.OpenUrl) { UseShellExecute = true });
        }
    }

    private async Task SaveKeyAsync()
    {
        if (string.IsNullOrWhiteSpace(DraftKey) || CurrentService() is not { } svc)
        {
            return;
        }

        await _host.Api.PostSessionAsync(svc.SavePath, new { api_key = DraftKey.Trim() }).ConfigureAwait(true);
        DraftKey = "";
        Hint = "Key stored in Heirloom. Next vendor.";
    }

    private void Advance()
    {
        if (CurrentService() is { } svc && _step + 1 < svc.Steps.Count)
        {
            _step++;
            Render(openPage: true);
            return;
        }

        if (_svc + 1 < _queue.Count)
        {
            _svc++;
            _step = 0;
            Render(openPage: true);
            return;
        }

        Stop();
    }

    private void Render(bool openPage)
    {
        var svc = CurrentService();
        var step = CurrentStep();
        if (svc is null || step is null)
        {
            Stop();
            return;
        }

        Overline = $"{svc.Label}  ·  {svc.Powers}";
        Title = step.Title;
        Body = step.Body;
        Bullets = string.Join("\n", step.Bullets.Select(b => "·  " + b));
        Cta = step.Cta;
        SkipCta = step.SkipCta;
        IsPasteStep = step.Kind == "paste";
        Placeholder = step.Placeholder;
        if (!string.IsNullOrWhiteSpace(step.Copy))
        {
            ClipboardService.CopyText(step.Copy);
            Hint = "Email copied. Paste it if their box is empty.";
        }

        if (openPage && step.AutoOpen && !string.IsNullOrWhiteSpace(step.OpenUrl))
        {
            Process.Start(new ProcessStartInfo(step.OpenUrl) { UseShellExecute = true });
        }
    }

    private void StartWatch()
    {
        _watch?.Cancel();
        _watch = new CancellationTokenSource();
        var token = _watch.Token;
        _ = Task.Run(async () =>
        {
            try
            {
                while (!token.IsCancellationRequested)
                {
                    await Task.Delay(4000, token).ConfigureAwait(false);
                    await ObserveAsync(token).ConfigureAwait(false);
                }
            }
            catch (OperationCanceledException)
            {
            }
        }, token);
    }

    private async Task ObserveAsync(CancellationToken cancellationToken)
    {
        if (!_host.Settings.Current.AllowSeeScreen || CurrentService() is not { } svc || CurrentStep() is not { } step)
        {
            return;
        }

        var b64 = _host.Screen.CaptureJpegBase64();
        if (string.IsNullOrWhiteSpace(b64))
        {
            return;
        }

        var result = await _host.Api.PostSessionAsync("/studio/first-run/coach/observe", new
        {
            service_id = svc.Id,
            current_step = step.Id,
            image_b64 = b64,
        }, cancellationToken).ConfigureAwait(false);
        if (result is not { } json)
        {
            return;
        }

        var hint = json.TryGetProperty("hint", out var h) ? h.GetString() : null;
        var advance = json.TryGetProperty("advance_to_step", out var a) ? a.GetString() : null;
        UiDispatch.Post(() =>
        {
            if (!string.IsNullOrWhiteSpace(hint))
            {
                Hint = hint!;
            }

            if (!string.IsNullOrWhiteSpace(advance) && CurrentService() is { } live)
            {
                var idx = live.Steps.ToList().FindIndex(s => s.Id == advance);
                if (idx > _step)
                {
                    _step = idx;
                    Render(openPage: true);
                }
            }
        });
    }

    private VendorService? CurrentService() =>
        _svc >= 0 && _svc < _queue.Count ? _queue[_svc] : null;

    private CoachStep? CurrentStep()
    {
        var svc = CurrentService();
        if (svc is null || _step < 0 || _step >= svc.Steps.Count)
        {
            return null;
        }

        return svc.Steps[_step];
    }
}
