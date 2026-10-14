using System.Windows;
using Heirloom.BoxCore;

namespace Heirloom.Companion;

public partial class SettingsWindow : Window
{
    private readonly CompanionStore _store;
    private string _pendingPin = "";
    private string? _pendingPem;

    public SettingsWindow(CompanionStore store)
    {
        _store = store;
        InitializeComponent();
        Address.Text = store.BoxUrl;
        StartAtLogin.IsChecked = store.Autostart;
        Toasts.IsChecked = store.Toasts;
        var pin = store.Pin;
        Fingerprint.Text = string.IsNullOrWhiteSpace(pin)
            ? "Certificate not pinned yet."
            : "Pinned " + CertificatePin.Normalize(pin);
    }

    private async void OnShowCertificate(object sender, RoutedEventArgs e)
    {
        Status.Text = "Reading the certificate…";
        try
        {
            var offer = await BoxClient.OfferTrustAsync(Address.Text).ConfigureAwait(true);
            _pendingPin = offer.PinSha256;
            _pendingPem = offer.CaPem;
            Fingerprint.Text = CertificatePin.Normalize(offer.PinSha256);
            Status.Text = "If that fingerprint is your box, choose This is my box.";
        }
        catch (Exception ex)
        {
            _pendingPin = "";
            _pendingPem = null;
            Status.Text = "Could not read the certificate. " + ex.Message;
        }
    }

    private void OnPin(object sender, RoutedEventArgs e)
    {
        if (string.IsNullOrWhiteSpace(_pendingPin))
        {
            Status.Text = "Show the certificate first.";
            return;
        }

        _store.SaveTrust(Address.Text, _pendingPin, _pendingPem);
        Status.Text = "Certificate pinned. TLS checks still run. Only this fingerprint is accepted.";
    }

    private async void OnSignIn(object sender, RoutedEventArgs e)
    {
        var pin = string.IsNullOrWhiteSpace(_pendingPin) ? _store.Pin : _pendingPin;
        var pem = _pendingPem ?? _store.CaPem;
        if (string.IsNullOrWhiteSpace(pin))
        {
            Status.Text = "Pin the certificate before signing in.";
            return;
        }

        Status.Text = "Signing in…";
        try
        {
            var token = await BoxClient.LoginAsync(Address.Text, Email.Text, Password.Password, pin, pem).ConfigureAwait(true);
            if (string.IsNullOrWhiteSpace(token))
            {
                Status.Text = "The box did not accept that email and password.";
                return;
            }

            _store.SaveTrust(Address.Text, pin, pem);
            _store.SaveSession(token);
            Password.Password = "";
            Status.Text = "Signed in. The password was not saved.";
        }
        catch (Exception ex)
        {
            Status.Text = "Could not sign in. " + ex.Message;
        }
    }

    private void OnSave(object sender, RoutedEventArgs e)
    {
        _store.BoxUrl = Address.Text;
        _store.Autostart = StartAtLogin.IsChecked == true;
        _store.Toasts = Toasts.IsChecked == true;
        TrayController.ApplyAutostart(_store.Autostart);
        Status.Text = "Saved.";
    }
}
