using Windows.Media.Core;
using Windows.Media.Playback;
using Windows.Media.SpeechSynthesis;
using Windows.Storage.Streams;

namespace Heirloom.Services;

public sealed class SpeakService : IDisposable
{
    private readonly HeirloomApiClient _api;
    private readonly MediaPlayer _player = new();
    private SpeechSynthesizer? _synth;

    public SpeakService(HeirloomApiClient api) => _api = api;

    public string LastVoice { get; private set; } = "none";

    public async Task SpeakAsync(string text, CancellationToken cancellationToken = default)
    {
        if (string.IsNullOrWhiteSpace(text))
        {
            return;
        }

        var audio = await _api.PostForBytesAsync("/desktop/speak", new { text }, cancellationToken).ConfigureAwait(false);
        if (audio is { Length: > 64 } && await PlayMpegAsync(audio).ConfigureAwait(false))
        {
            LastVoice = "cloned";
            return;
        }

        await SpeakLocalAsync(text).ConfigureAwait(false);
    }

    public async Task SpeakLocalAsync(string text)
    {
        LastVoice = "windows-sapi";
        try
        {
            _synth ??= new SpeechSynthesizer();
            var stream = await _synth.SynthesizeTextToStreamAsync(text);
            _player.Source = MediaSource.CreateFromStream(stream, stream.ContentType);
            _player.Play();
        }
        catch
        {
            LastVoice = "unavailable";
        }
    }

    public async Task<string> SynthesizeToFileAsync(string text, string destWithoutExtension, CancellationToken cancellationToken = default)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(destWithoutExtension) ?? AppPaths.AvatarRoot);
        var audio = await _api.PostForBytesAsync("/desktop/speak", new { text }, cancellationToken).ConfigureAwait(false);
        if (audio is { Length: > 64 })
        {
            var mp3 = destWithoutExtension + ".mp3";
            await File.WriteAllBytesAsync(mp3, audio, cancellationToken).ConfigureAwait(false);
            LastVoice = "cloned";
            return mp3;
        }

        _synth ??= new SpeechSynthesizer();
        var stream = await _synth.SynthesizeTextToStreamAsync(text);
        var wav = destWithoutExtension + ".wav";
        var size = (uint)stream.Size;
        using var reader = new DataReader(stream.GetInputStreamAt(0));
        await reader.LoadAsync(size);
        var buffer = new byte[size];
        reader.ReadBytes(buffer);
        await File.WriteAllBytesAsync(wav, buffer, cancellationToken).ConfigureAwait(false);
        LastVoice = "windows-sapi";
        return wav;
    }

    private async Task<bool> PlayMpegAsync(byte[] audio)
    {
        try
        {
            var ras = new InMemoryRandomAccessStream();
            using (var writer = new DataWriter(ras.GetOutputStreamAt(0)))
            {
                writer.WriteBytes(audio);
                await writer.StoreAsync();
            }

            ras.Seek(0);
            _player.Source = MediaSource.CreateFromStream(ras, "audio/mpeg");
            _player.Play();
            return true;
        }
        catch
        {
            return false;
        }
    }

    public void Dispose()
    {
        _player.Dispose();
        _synth?.Dispose();
    }
}
