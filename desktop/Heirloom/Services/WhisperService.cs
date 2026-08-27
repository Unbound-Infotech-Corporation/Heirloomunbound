using Whisper.net;

namespace Heirloom.Services;

public sealed class WhisperService : IDisposable
{
    private WhisperFactory? _factory;
    private WhisperProcessor? _processor;

    private static readonly HttpClient DownloadHttp = SetupCopy.CreateDownloadClient();

    public bool IsReady => _processor is not null;
    public string Status { get; private set; } = "Hearing isn't set up yet.";
    public string LastError { get; private set; } = "";

    public async Task EnsureAsync(CancellationToken cancellationToken = default)
    {
        var path = AppPaths.WhisperModelPath;
        if (!SetupCopy.WhisperLooksComplete(path))
        {
            Status = "Hearing isn't set up yet.";
            LastError = Status;
            return;
        }

        try
        {
            _processor?.Dispose();
            _factory?.Dispose();
            _factory = WhisperFactory.FromPath(path);
            _processor = _factory.CreateBuilder().WithLanguage("auto").Build();
            Status = "Hearing is ready.";
            LastError = "";
            await Task.CompletedTask.WaitAsync(cancellationToken).ConfigureAwait(false);
        }
        catch (Exception ex)
        {
            Status = SetupCopy.HumanFault(ex, "preparing hearing", cancellationToken);
            LastError = Status;
        }
    }

    public async Task DownloadAndEnsureAsync(IProgress<string>? progress, CancellationToken cancellationToken = default)
    {
        var path = AppPaths.WhisperModelPath;
        if (!SetupCopy.WhisperLooksComplete(path))
        {
            try
            {
                AppPaths.EnsureDirectories();
                await SetupCopy.DownloadToFileAsync(
                    DownloadHttp,
                    SetupCopy.WhisperUrl,
                    path,
                    "Hearing you speak",
                    progress,
                    cancellationToken).ConfigureAwait(false);
            }
            catch (Exception ex)
            {
                Status = SetupCopy.HumanFault(ex, "getting hearing ready", cancellationToken);
                LastError = Status;
                return;
            }
        }

        await EnsureAsync(cancellationToken).ConfigureAwait(false);
    }

    public async Task<string> TranscribeAsync(byte[] wavBytes, CancellationToken cancellationToken = default)
    {
        if (_processor is null)
        {
            await EnsureAsync(cancellationToken).ConfigureAwait(false);
        }

        if (_processor is null)
        {
            LastError = string.IsNullOrWhiteSpace(Status) ? "Hearing isn't set up yet." : Status;
            return string.Empty;
        }

        var temp = Path.Combine(Path.GetTempPath(), "heirloom-ptt.wav");
        await File.WriteAllBytesAsync(temp, wavBytes, cancellationToken).ConfigureAwait(false);
        try
        {
            var text = new System.Text.StringBuilder();
            await using var stream = File.OpenRead(temp);
            await foreach (var result in _processor.ProcessAsync(stream, cancellationToken))
            {
                text.Append(result.Text);
            }

            return text.ToString().Trim();
        }
        catch (Exception)
        {
            Status = "Hearing didn't catch that. Try once more, a little closer to the microphone.";
            LastError = Status;
            return string.Empty;
        }
        finally
        {
            try { File.Delete(temp); } catch { /* ignore */ }
        }
    }

    public void Dispose()
    {
        _processor?.Dispose();
        _factory?.Dispose();
    }
}
