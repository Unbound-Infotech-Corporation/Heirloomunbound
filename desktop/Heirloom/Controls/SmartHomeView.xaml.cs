using System.Text.Json;
using Heirloom.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace Heirloom.Controls;

public sealed partial class SmartHomeView : UserControl
{
    private readonly SmartHomeModel _model = new();
    private string _pendingId = "";
    private string _pendingAction = "";

    public SmartHomeView()
    {
        InitializeComponent();
        Status.Text = _model.Status;
    }

    private async void OnScan(object sender, RoutedEventArgs e)
    {
        Status.Text = "Looking on your home network…";
        var result = await App.Host.Api.PostSessionAsync("/api/smart-home/scan", new { });
        if (result is null)
        {
            Status.Text = "Nothing answered. " + App.Host.Api.LastFailure;
            return;
        }

        var found = new List<HomeDevice>();
        if (result.Value.TryGetProperty("devices", out var devices) && devices.ValueKind == JsonValueKind.Array)
        {
            foreach (var row in devices.EnumerateArray())
            {
                var name = row.TryGetProperty("name", out var nameEl) ? nameEl.GetString() ?? "" : "";
                var vendor = row.TryGetProperty("vendor", out var vendorEl) ? vendorEl.GetString() ?? "" : "";
                var host = row.TryGetProperty("host", out var hostEl) ? hostEl.GetString() ?? "" : "";
                var id = string.IsNullOrWhiteSpace(host) ? name : host;
                if (string.IsNullOrWhiteSpace(id))
                {
                    continue;
                }

                var critical = name.Contains("fridge", StringComparison.OrdinalIgnoreCase)
                    || name.Contains("furnace", StringComparison.OrdinalIgnoreCase);
                found.Add(new HomeDevice(id, string.IsNullOrWhiteSpace(name) ? vendor : name, vendor, "light", critical));
            }
        }

        _model.Show(found);
        Devices.ItemsSource = _model.Devices.ToList();
        Status.Text = _model.Status;
    }

    private void OnDevice(object sender, RoutedEventArgs e) => Act(sender, "on");

    private void OnDeviceOff(object sender, RoutedEventArgs e) => Act(sender, "off");

    private void Act(object sender, string action)
    {
        if (sender is not Button { Tag: string id })
        {
            return;
        }

        var device = _model.Devices.FirstOrDefault(item => item.Id == id);
        if (device is null)
        {
            return;
        }

        var done = _model.Change(device, action, approved: false, criticalConfirm: false, alwaysAllow: false);
        Pending.Text = _model.Pending;
        if (!done)
        {
            _pendingId = id;
            _pendingAction = action;
        }
    }

    private void OnConfirm(object sender, RoutedEventArgs e)
    {
        var device = _model.Devices.FirstOrDefault(item => item.Id == _pendingId);
        if (device is null)
        {
            return;
        }

        var critical = device.Critical || device.Kind == "thermostat";
        _model.Change(device, _pendingAction, approved: true, criticalConfirm: critical, alwaysAllow: false);
        Pending.Text = _model.Pending;
    }
}
