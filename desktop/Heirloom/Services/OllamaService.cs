using System.Net.Http.Json;
using System.Text.Json;

namespace Heirloom.Services;

public sealed record OllamaComplete(string? Text, string? Error)
{
    public bool Ok => !string.IsNullOrWhiteSpace(Text);
}

public sealed class OllamaService
{
    private readonly HttpClient _probe = new()
    {
        BaseAddress = new Uri("http://127.0.0.1:11434"),
        Timeout = TimeSpan.FromSeconds(3),
    };

    private readonly HttpClient _generate = new()
    {
        BaseAddress = new Uri("http://127.0.0.1:11434"),
        Timeout = TimeSpan.FromSeconds(50),
    };

    private readonly HttpClient _pull = new()
    {
        BaseAddress = new Uri("http://127.0.0.1:11434"),
        Timeout = TimeSpan.FromHours(3),
    };

    public bool IsReachable { get; private set; }
    public string Status { get; private set; } = "Talking mind helper is off.";
    public string LastError { get; private set; } = "";
    public IReadOnlyList<string> Models { get; private set; } = [];
    public string? ChatModel => ModelPicker.PickGenerate(Models);

    public string? FindExe() => SetupCopy.FindOllamaExe();

    public async Task ProbeAsync(CancellationToken cancellationToken = default)
    {
        try
        {
            using var response = await _probe.GetAsync("/api/tags", cancellationToken).ConfigureAwait(false);
            if (!response.IsSuccessStatusCode)
            {
                IsReachable = false;
                LastError = "Ollama HTTP " + (int)response.StatusCode;
                Status = LastError;
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
            LastError = "";
            Status = ChatModel is null
                ? "Talking mind helper is on, waiting for a mind."
                : "Talking mind is ready.";
        }
        catch (OperationCanceledException)
        {
            IsReachable = false;
            LastError = "Talking mind helper timed out.";
            Status = LastError;
        }
        catch (Exception)
        {
            IsReachable = false;
            LastError = "Talking mind helper is off.";
            Status = LastError;
        }
    }

    public bool TryStartServe()
    {
        var exe = FindExe();
        if (string.IsNullOrWhiteSpace(exe))
        {
            return false;
        }

        try
        {
            System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo
            {
                FileName = exe,
                Arguments = "serve",
                UseShellExecute = false,
                CreateNoWindow = true,
                WindowStyle = System.Diagnostics.ProcessWindowStyle.Hidden,
            });
            return true;
        }
        catch
        {
            return false;
        }
    }

    public async Task<bool> WaitReachableAsync(TimeSpan limit, CancellationToken cancellationToken = default)
    {
        var deadline = DateTime.UtcNow + limit;
        while (DateTime.UtcNow < deadline)
        {
            cancellationToken.ThrowIfCancellationRequested();
            await ProbeAsync(cancellationToken).ConfigureAwait(false);
            if (IsReachable)
            {
                return true;
            }

            await Task.Delay(500, cancellationToken).ConfigureAwait(false);
        }

        await ProbeAsync(cancellationToken).ConfigureAwait(false);
        return IsReachable;
    }

    public async Task<bool> EnsureRunningAsync(IProgress<string>? progress, CancellationToken cancellationToken = default)
    {
        await ProbeAsync(cancellationToken).ConfigureAwait(false);
        if (IsReachable)
        {
            return true;
        }

        if (FindExe() is null)
        {
            return false;
        }

        progress?.Report("Starting the talking mind helper…");
        TryStartServe();
        return await WaitReachableAsync(TimeSpan.FromSeconds(50), cancellationToken).ConfigureAwait(false);
    }

    public async Task<string?> CompleteAsync(string model, string prompt, string? system = null, CancellationToken cancellationToken = default)
    {
        var result = await CompleteDetailedAsync(model, prompt, system, cancellationToken).ConfigureAwait(false);
        return result.Text;
    }

    public async Task<OllamaComplete> CompleteDetailedAsync(string model, string prompt, string? system = null, CancellationToken cancellationToken = default)
    {
        try
        {
            object payload = string.IsNullOrWhiteSpace(system)
                ? new { model, prompt, stream = false }
                : new { model, prompt, system, stream = false };
            using var response = await _generate.PostAsJsonAsync("/api/generate", payload, cancellationToken).ConfigureAwait(false);
            if (!response.IsSuccessStatusCode)
            {
                LastError = "Ollama generate HTTP " + (int)response.StatusCode + " (" + model + ")";
                return new OllamaComplete(null, LastError);
            }

            using var doc = JsonDocument.Parse(await response.Content.ReadAsStringAsync(cancellationToken).ConfigureAwait(false));
            var text = doc.RootElement.TryGetProperty("response", out var r) ? r.GetString() : null;
            if (string.IsNullOrWhiteSpace(text))
            {
                LastError = "Ollama returned an empty reply (" + model + ").";
                return new OllamaComplete(null, LastError);
            }

            LastError = "";
            return new OllamaComplete(text, null);
        }
        catch (OperationCanceledException)
        {
            LastError = "Ollama generate timed out (" + model + ").";
            return new OllamaComplete(null, LastError);
        }
        catch (Exception ex)
        {
            LastError = "Ollama generate failed: " + ex.Message;
            return new OllamaComplete(null, LastError);
        }
    }

    public async Task<string?> CompleteVisionAsync(string model, string prompt, byte[] jpeg, CancellationToken cancellationToken = default)
    {
        try
        {
            var payload = new
            {
                model,
                prompt,
                images = new[] { Convert.ToBase64String(jpeg) },
                stream = false,
            };
            using var response = await _generate.PostAsJsonAsync("/api/generate", payload, cancellationToken).ConfigureAwait(false);
            if (!response.IsSuccessStatusCode)
            {
                LastError = "Ollama vision HTTP " + (int)response.StatusCode;
                return null;
            }

            using var doc = JsonDocument.Parse(await response.Content.ReadAsStringAsync(cancellationToken).ConfigureAwait(false));
            return doc.RootElement.TryGetProperty("response", out var text) ? text.GetString() : null;
        }
        catch (OperationCanceledException)
        {
            LastError = "Ollama vision timed out.";
            return null;
        }
        catch (Exception ex)
        {
            LastError = "Ollama vision failed: " + ex.Message;
            return null;
        }
    }

    public async Task<string> PullAsync(string model, IProgress<string>? progress, CancellationToken cancellationToken = default)
    {
        progress?.Report("Downloading the talking mind…");
        try
        {
            using var request = new HttpRequestMessage(HttpMethod.Post, "/api/pull")
            {
                Content = JsonContent.Create(new { name = model, stream = true }),
            };
            using var response = await _pull.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, cancellationToken).ConfigureAwait(false);
            if (!response.IsSuccessStatusCode)
            {
                await ProbeAsync(cancellationToken).ConfigureAwait(false);
                return SetupCopy.HumanHttpStatus((int)response.StatusCode);
            }

            await using var stream = await response.Content.ReadAsStreamAsync(cancellationToken).ConfigureAwait(false);
            using var reader = new StreamReader(stream);
            var lastError = "";
            while (await reader.ReadLineAsync(cancellationToken).ConfigureAwait(false) is { } line)
            {
                if (string.IsNullOrWhiteSpace(line))
                {
                    continue;
                }

                progress?.Report(SetupCopy.FriendlyPullStatus(line));
                try
                {
                    using var doc = JsonDocument.Parse(line);
                    if (doc.RootElement.TryGetProperty("error", out var err))
                    {
                        lastError = err.GetString() ?? lastError;
                    }
                }
                catch (JsonException)
                {
                    // keep going
                }
            }

            await ProbeAsync(cancellationToken).ConfigureAwait(false);
            if (!string.IsNullOrWhiteSpace(lastError))
            {
                return SetupCopy.HumanOllamaError(lastError);
            }

            return ChatModel is not null
                ? "The talking mind is ready."
                : "The talking mind did not finish downloading. Check the internet, then tap Try again.";
        }
        catch (Exception ex)
        {
            return SetupCopy.HumanFault(ex, "downloading the talking mind", cancellationToken);
        }
    }
}
