using System.Net.Http.Json;
using System.Text.Json;

namespace Heirloom.Services;

public sealed class OllamaService
{
    private readonly HttpClient _http = new()
    {
        BaseAddress = new Uri("http://127.0.0.1:11434"),
        Timeout = TimeSpan.FromMinutes(10),
    };

    public OllamaService()
    {
    }

    public bool IsReachable { get; private set; }
    public string Status { get; private set; } = "Ollama offline";
    public IReadOnlyList<string> Models { get; private set; } = [];

    public async Task ProbeAsync(CancellationToken cancellationToken = default)
    {
        try
        {
            using var response = await _http.GetAsync("/api/tags", cancellationToken).ConfigureAwait(false);
            if (!response.IsSuccessStatusCode)
            {
                IsReachable = false;
                Status = "Ollama HTTP " + (int)response.StatusCode;
                return;
            }

            using var doc = JsonDocument.Parse(await response.Content.ReadAsStringAsync(cancellationToken).ConfigureAwait(false));
            var names = new List<string>();
            if (doc.RootElement.TryGetProperty("models", out var models))
            {
                foreach (var model in models.EnumerateArray())
                {
                    if (model.TryGetProperty("name", out var name))
                    {
                        names.Add(name.GetString() ?? "");
                    }
                }
            }

            Models = names.Where(n => n.Length > 0).ToArray();
            IsReachable = true;
            Status = Models.Count == 0 ? "Ollama up · no models" : $"Ollama up · {Models.Count} models";
        }
        catch
        {
            IsReachable = false;
            Status = "Ollama offline";
        }
    }

    public async Task<string?> CompleteAsync(string model, string prompt, string? system = null, CancellationToken cancellationToken = default)
    {
        try
        {
            object payload = string.IsNullOrWhiteSpace(system)
                ? new { model, prompt, stream = false }
                : new { model, prompt, system, stream = false };
            using var response = await _http.PostAsJsonAsync("/api/generate", payload, cancellationToken).ConfigureAwait(false);
            if (!response.IsSuccessStatusCode)
            {
                return null;
            }

            using var doc = JsonDocument.Parse(await response.Content.ReadAsStringAsync(cancellationToken).ConfigureAwait(false));
            return doc.RootElement.TryGetProperty("response", out var text) ? text.GetString() : null;
        }
        catch
        {
            return null;
        }
    }

    public async Task<string> PullAsync(string model, IProgress<string>? progress, CancellationToken cancellationToken = default)
    {
        progress?.Report("Pulling " + model);
        try
        {
            using var response = await _http.PostAsJsonAsync("/api/pull", new { name = model, stream = false }, cancellationToken).ConfigureAwait(false);
            await ProbeAsync(cancellationToken).ConfigureAwait(false);
            return response.IsSuccessStatusCode ? "Pulled " + model : "Pull failed";
        }
        catch (Exception ex)
        {
            return ex.Message;
        }
    }
}
