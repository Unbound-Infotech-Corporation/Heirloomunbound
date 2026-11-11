using System.Diagnostics;
using System.Text.Json;
using Heirloom.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace Heirloom.Controls;

public sealed partial class SetupCenterView : UserControl
{
    private readonly SetupCenterModel _model = new();

    public SetupCenterView()
    {
        InitializeComponent();
        _model.Load(new SetupSignals(
            HardwareOk: true,
            WhisperReady: false,
            OllamaReady: false,
            VoiceReady: false,
            CompanionPaired: false,
            StartupEnabled: false,
            BackupSeen: false,
            HardwareLine: "Disk space picks a starting size."));
        Steps.ItemsSource = _model.Steps;
        Guides.ItemsSource = SetupCenterModel.Guides;
        Guides.SelectedIndex = 0;
        ShowGuide();
    }

    private void OnGuide(object sender, SelectionChangedEventArgs e) => ShowGuide();

    private void ShowGuide()
    {
        if (Guides.SelectedItem is GuidePage guide && _model.Select(guide.Id))
        {
            GuidePlain.Text = guide.Plain;
        }
    }

    private void OnOpen(object sender, RoutedEventArgs e)
    {
        var url = _model.OpenUrl();
        if (string.IsNullOrWhiteSpace(url))
        {
            return;
        }

        Process.Start(new ProcessStartInfo(url) { UseShellExecute = true });
    }

    private void OnPaste(object sender, RoutedEventArgs e)
    {
        if (Guides.SelectedItem is not GuidePage guide)
        {
            return;
        }

        _model.Paste(guide.Id, SecretBox.Password, BaseUrl.Text);
        SecretLine.Text = _model.MaskedSecret.Length == 0
            ? _model.SecretDetail
            : _model.MaskedSecret + "  ·  " + _model.SecretDetail;
        SecretBox.Password = "";
    }

    private void OnPassphrase(object sender, RoutedEventArgs e) => _model.SetPassphrase(Passphrase.Password);

    private void OnRepair(object sender, RoutedEventArgs e)
    {
        Steps.ItemsSource = _model.Repair(new SetupSignals(true, false, false, true, false, false, false, ""));
    }

    private async void OnVerify(object sender, RoutedEventArgs e)
    {
        if (string.IsNullOrWhiteSpace(BackupFolder.Text))
        {
            RestoreLine.Text = "Choose the folder that holds SHA256SUMS and the backup parts.";
            return;
        }

        var result = await App.Host.Api.PostSessionAsync("/api/setup/restore/inspect", new { source = BackupFolder.Text, dest = RestoreDest.Text });
        if (result is null)
        {
            RestoreLine.Text = "Could not read that folder. " + App.Host.Api.LastFailure;
            return;
        }

        var kind = result.Value.TryGetProperty("kind", out var kindEl) ? kindEl.GetString() : "plain";
        var ok = result.Value.TryGetProperty("checksums_ok", out var okEl) && okEl.ValueKind == JsonValueKind.True;
        RestoreLine.Text = kind == "gpg"
            ? (ok ? "Checksums match. Enter the passphrase. It is not saved." : "The checksums do not match. Nothing was opened.")
            : "This is a plain folder. Restore copies it. A passphrase is not required.";
    }

    private async void OnRestore(object sender, RoutedEventArgs e)
    {
        var source = BackupFolder.Text.Trim();
        var dest = RestoreDest.Text.Trim();
        if (source.Length == 0 || dest.Length == 0)
        {
            RestoreLine.Text = "Choose the backup folder and where it should go on this PC.";
            return;
        }

        var passphrase = _model.ConsumePassphrase();
        var encrypted = passphrase.Length > 0;
        var result = await App.Host.Api.PostSessionAsync(
            encrypted ? "/api/setup/restore/encrypted" : "/api/setup/restore/apply",
            encrypted
                ? new { source, dest, passphrase, confirm = true, new_machine = true }
                : (object)new { source, dest, confirm = true, new_machine = true });
        passphrase = "";
        Passphrase.Password = "";
        if (result is null)
        {
            RestoreLine.Text = "Restore did not finish. " + App.Host.Api.LastFailure;
            return;
        }

        var refused = result.Value.TryGetProperty("refused", out var refusedEl) && refusedEl.ValueKind == JsonValueKind.String
            ? refusedEl.GetString()
            : null;
        RestoreLine.Text = string.IsNullOrWhiteSpace(refused)
            ? "Copied onto this PC. The Linux box was not changed, and the passphrase was not saved."
            : refused;
    }
}
