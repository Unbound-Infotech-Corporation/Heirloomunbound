using System.Collections.ObjectModel;
using System.Text.Json;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using Heirloom.BoxCore;
using Heirloom.Services;

namespace Heirloom.ViewModels;

public partial class CaretakerViewModel : ObservableObject
{
    private readonly AppHost _host;

    public CaretakerViewModel(AppHost host)
    {
        _host = host;
    }

    public ObservableCollection<ChatLine> Lines { get; } = [];
    public ObservableCollection<string> ActionLog { get; } = [];

    [ObservableProperty] private string _draft = "";
    [ObservableProperty] private string _status = "Caretaker checks the box. Safe fixes run. The rest waits.";
    [ObservableProperty] private string _health = "";
    [ObservableProperty] private string _pendingId = "";
    [ObservableProperty] private bool _canConfirm;

    [RelayCommand]
    private async Task AskAsync()
    {
        if (!_host.CanEdit)
        {
            Status = "Heir mode. Caretaker stays with the owner.";
            return;
        }

        var text = (Draft ?? "").Trim();
        if (text.Length == 0)
        {
            return;
        }

        Draft = "";
        var blocked = CaretakerGuard.Block(text);
        if (blocked is not null)
        {
            Lines.Add(new ChatLine("twin", blocked));
            Status = blocked;
            return;
        }

        Lines.Add(new ChatLine("you", text));
        Status = "Checking…";
        var result = await _host.Api.PostSessionAsync("/caretaker/chat", new { text }).ConfigureAwait(true);
        Apply(result);
    }

    [RelayCommand]
    private async Task ConfirmAsync()
    {
        if (!_host.CanEdit || string.IsNullOrWhiteSpace(PendingId))
        {
            return;
        }

        Status = "Confirming…";
        var result = await _host.Api.PostSessionAsync("/caretaker/confirm", new { id = PendingId }).ConfigureAwait(true);
        PendingId = "";
        CanConfirm = false;
        Apply(result);
    }

    [RelayCommand]
    internal async Task RefreshAsync()
    {
        if (!_host.CanEdit)
        {
            Status = "Heir mode. Caretaker stays with the owner.";
            return;
        }

        var result = await _host.Api.GetSessionAsync("/caretaker").ConfigureAwait(true);
        if (result is null)
        {
            Status = string.IsNullOrWhiteSpace(_host.Api.LastFailure) ? "The box did not answer." : _host.Api.LastFailure;
            return;
        }

        Health = ReadHealth(result.Value);
        ReplaceLog(result.Value);
        if (result.Value.TryGetProperty("pending_id", out var pending))
        {
            PendingId = pending.GetString() ?? "";
            CanConfirm = PendingId.Length > 0;
        }

        Status = "Health is read-only. Fans and power limits stay as they are.";
    }

    private void Apply(JsonElement? result)
    {
        if (result is null)
        {
            var failure = string.IsNullOrWhiteSpace(_host.Api.LastFailure) ? "The box did not answer." : _host.Api.LastFailure;
            Lines.Add(new ChatLine("twin", failure));
            Status = failure;
            return;
        }

        var reply = result.Value.TryGetProperty("reply", out var replyNode) ? replyNode.GetString() ?? "" : "";
        if (reply.Length > 0)
        {
            Lines.Add(new ChatLine("twin", reply));
        }

        PendingId = result.Value.TryGetProperty("pending_id", out var pending) ? pending.GetString() ?? "" : "";
        CanConfirm = PendingId.Length > 0;
        Health = ReadHealth(result.Value);
        ReplaceLog(result.Value);
        Status = CanConfirm ? "Something past the safe list is waiting for confirm." : "Logged.";
    }

    private void ReplaceLog(JsonElement result)
    {
        ActionLog.Clear();
        if (!result.TryGetProperty("log", out var log) || log.ValueKind != JsonValueKind.Array)
        {
            return;
        }

        foreach (var row in log.EnumerateArray())
        {
            var action = row.TryGetProperty("action", out var actionNode) ? actionNode.GetString() : "";
            var status = row.TryGetProperty("status", out var statusNode) ? statusNode.GetString() : "";
            var detail = row.TryGetProperty("detail", out var detailNode) ? detailNode.GetString() : "";
            ActionLog.Add($"{action}  {status}  {detail}".Trim());
        }
    }

    private static string ReadHealth(JsonElement result)
    {
        if (!result.TryGetProperty("health", out var health) || health.ValueKind is JsonValueKind.Null or JsonValueKind.Undefined)
        {
            return "";
        }

        var text = health.ToString();
        if (result.TryGetProperty("brain", out var brain) && brain.ValueKind == JsonValueKind.Object)
        {
            var name = brain.TryGetProperty("answered", out var answered) ? answered.GetString() : "";
            var model = brain.TryGetProperty("model_in_use", out var inUse)
                ? inUse.GetString()
                : brain.TryGetProperty("model", out var modelNode) ? modelNode.GetString() : "";
            if (!string.IsNullOrWhiteSpace(name))
            {
                text = string.IsNullOrWhiteSpace(text) ? "" : text + "\n";
                text += string.IsNullOrWhiteSpace(model) ? "Brain " + name : "Brain " + name + " · " + model;
            }
        }

        return text;
    }
}
