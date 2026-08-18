using Whisper.net;

namespace Heirloom.Services;

public sealed class WhisperService : IDisposable
{
    private WhisperFactory? _factory;
    private WhisperProcessor? _processor;

    public bool IsReady => _processor is not null;
    public string Status { get; private set; } = "Whisper not provisioned";

    public async Task EnsureAsync(CancellationToken cancellationToken = default)
    {
        var path = AppPaths.WhisperModelPath;
        if (!File.Exists(path))
        {
            Status = "Missing ggml-base.bin — provision in Models";
            return;
        }

        try
        {
            _processor?.Dispose();
            _factory?.Dispose();
            _factory = WhisperFactory.FromPath(path);
            _processor = _factory.CreateBuilder().WithLanguage("auto").Build();
            Status = "Ready (base)";
            await Task.CompletedTask.WaitAsync(cancellationToken).ConfigureAwait(false);
        }
        catch (Exception ex)
        {
            Status = "Load failed: " + ex.Message;
        }
    }

    public async Task<string> TranscribeAsync(byte[] wavBytes, CancellationToken cancellationToken = default)
    {
        if (_processor is null)
        {
            await EnsureAsync(cancellationToken).ConfigureAwait(false);
        }

        if (_processor is null)
        {
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
        catch (Exception ex)
        {
            Status = "Transcribe failed: " + ex.Message;
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
