using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using Heirloom.Services;
using Microsoft.UI.Xaml;

namespace Heirloom.ViewModels;

public sealed class SetupReminderItem
{
    public SetupReminderItem(TwinSetupStepState step)
    {
        Id = step.Id;
        Label = step.Label;
        Benefit = step.Id == "likeness"
            ? $"{step.Have} of {step.Need} photos"
            : step.Benefit;
        Cta = step.Cta;
        DocumentId = step.DocumentId;
        ExampleLine = string.Join("  ·  ", step.Examples.Select(e => e.Title));
        Caption = step.Examples.Count > 0 ? step.Examples[0].Caption : step.Benefit;
    }

    public string Id { get; }
    public string Label { get; }
    public string Benefit { get; }
    public string Cta { get; }
    public string DocumentId { get; }
    public string ExampleLine { get; }
    public string Caption { get; }
}

public partial class SetupReminderViewModel : ObservableObject
{
    private readonly AppHost _host;
    private bool _youreSetPulse;
    private int _lastRemaining = -1;

    public SetupReminderViewModel(AppHost host)
    {
        _host = host;
        Items = [];
        RefreshFromLocal();
    }

    public ObservableCollection<SetupReminderItem> Items { get; }

    public event EventHandler? VisibilityChanged;
    public event EventHandler<string>? OpenDocumentRequested;

    [ObservableProperty] private string _title = "Still to do";
    [ObservableProperty] private string _body = "Clone your voice and take three photos so the Twin can look and sound like you.";
    [ObservableProperty] private bool _isVisible;
    [ObservableProperty] private Visibility _listVis = Visibility.Visible;
    [ObservableProperty] private Visibility _setVis = Visibility.Collapsed;

    public void RefreshFromLocal()
    {
        var photos = (_host.Settings.Current.AvatarPhotoPaths ?? [])
            .Count(File.Exists);
        if (photos == 0 && File.Exists(_host.Settings.Current.AvatarPortraitPath))
        {
            photos = 1;
        }

        Apply(
            TwinSetupProgress.Build(
                voiceReady: false,
                likenessHave: photos,
                avatarReady: File.Exists(_host.Settings.Current.AvatarGeneratedPath)
                    || File.Exists(_host.Settings.Current.AvatarPortraitPath),
                dismissed: _host.Settings.Current.SetupCoachDismissed,
                heirMode: !_host.CanEdit));
    }

    public async Task RefreshAsync()
    {
        RefreshFromLocal();
        if (!_host.CanEdit || (!_host.Api.HasSession && !_host.Api.HasDeviceToken))
        {
            return;
        }

        try
        {
            var json = await _host.Api.GetSessionAsync("/studio/first-run/progress").ConfigureAwait(true)
                ?? await _host.Api.GetAsync("/studio/first-run/progress").ConfigureAwait(true);
            if (json is null)
            {
                return;
            }

            var voice = json.Value.TryGetProperty("voice_ready", out var v) && v.GetBoolean();
            var have = json.Value.TryGetProperty("likeness_have", out var h) ? h.GetInt32() : 0;
            var avatar = json.Value.TryGetProperty("avatar_ready", out var a) && a.GetBoolean();
            var dismissed = json.Value.TryGetProperty("coach_dismissed", out var d) && d.GetBoolean();
            var localPhotos = (_host.Settings.Current.AvatarPhotoPaths ?? []).Count(File.Exists);
            Apply(
                TwinSetupProgress.Build(
                    voiceReady: voice,
                    likenessHave: Math.Max(have, localPhotos),
                    avatarReady: avatar || File.Exists(_host.Settings.Current.AvatarGeneratedPath),
                    dismissed: dismissed || _host.Settings.Current.SetupCoachDismissed,
                    heirMode: !_host.CanEdit));
        }
        catch
        {
            /* stay on local snapshot */
        }
    }

    [RelayCommand]
    public async Task DismissAsync()
    {
        if (_youreSetPulse)
        {
            _youreSetPulse = false;
            IsVisible = false;
            VisibilityChanged?.Invoke(this, EventArgs.Empty);
            return;
        }

        _host.Settings.Current.SetupCoachDismissed = true;
        _host.Settings.Save();
        IsVisible = false;
        VisibilityChanged?.Invoke(this, EventArgs.Empty);
        await PersistDismissedAsync(true).ConfigureAwait(true);
    }

    [RelayCommand]
    public async Task ReopenAsync()
    {
        _host.Settings.Current.SetupCoachDismissed = false;
        _host.Settings.Save();
        await PersistDismissedAsync(false).ConfigureAwait(true);
        await RefreshAsync().ConfigureAwait(true);
        if (!IsVisible && Items.Count > 0)
        {
            IsVisible = true;
            VisibilityChanged?.Invoke(this, EventArgs.Empty);
        }
    }

    private async Task PersistDismissedAsync(bool dismissed)
    {
        try
        {
            var body = new { coach_dismissed = dismissed };
            var result = await _host.Api.PutSessionAsync("/studio/first-run", body).ConfigureAwait(true);
            if (result is null)
            {
                await _host.Api.PutAsync("/studio/first-run", body).ConfigureAwait(true);
            }
        }
        catch
        {
            /* local settings.json is the source of truth on this PC */
        }
    }

    [RelayCommand]
    public void OpenStep(string? documentId)
    {
        if (!string.IsNullOrWhiteSpace(documentId))
        {
            OpenDocumentRequested?.Invoke(this, documentId);
        }
    }

    private void Apply(TwinSetupSnapshot snap)
    {
        Items.Clear();
        foreach (var step in snap.Steps.Where(s => s.Critical && !s.Done))
        {
            Items.Add(new SetupReminderItem(step));
        }

        Title = snap.YoureSet ? "You're set" : "Still to do";
        Body = snap.YoureSet
            ? "Voice and likeness are on file. The Twin can sound and look like you."
            : "Clone your voice and take three photos so the Twin can look and sound like you.";
        ListVis = snap.YoureSet ? Visibility.Collapsed : Visibility.Visible;
        SetVis = snap.YoureSet ? Visibility.Visible : Visibility.Collapsed;

        var justCompleted = snap.YoureSet && _lastRemaining > 0;
        _lastRemaining = snap.RemainingCritical;
        if (justCompleted)
        {
            _youreSetPulse = true;
        }

        var show = snap.Visible;
        if (_youreSetPulse && snap.YoureSet)
        {
            show = true;
        }

        if (IsVisible != show)
        {
            IsVisible = show;
            VisibilityChanged?.Invoke(this, EventArgs.Empty);
        }
    }
}
