using System.Diagnostics;
using System.Linq;

namespace Heirloom.Services;

public sealed class ProvisionService
{
    private static readonly HttpClient DownloadHttp = SetupCopy.CreateDownloadClient();

    private readonly OllamaService _ollama;
    private readonly WhisperService _whisper;
    private readonly AvatarEngineService _avatar;

    public ProvisionService(OllamaService ollama, WhisperService whisper, AvatarEngineService avatar)
    {
        _ollama = ollama;
        _whisper = whisper;
        _avatar = avatar;
    }

    public string LastMessage { get; private set; } = "";

    public async Task ProvisionAsync(DiskProfile profile, IProgress<string> progress, CancellationToken cancellationToken = default) =>
        await ProvisionAsync(profile, progress, allowInstall: false, cancellationToken).ConfigureAwait(false);

    public async Task ProvisionAsync(
        DiskProfile profile,
        IProgress<string> progress,
        bool allowInstall,
        CancellationToken cancellationToken = default)
    {
        IProgress<string> mapped = new Progress<string>(m => progress.Report(SetupCopy.FriendlyLine(m)));
        mapped.Report("Heirloom Unbound · " + profile.Label);
        mapped.Report("No Pinokio. Official downloads only. Engine failure coaches and continues.");
        Directory.CreateDirectory(AppPaths.ModelsRoot);

        if (profile.ProvisionFeatures.Contains("stt"))
        {
            try
            {
                await _whisper.DownloadAndEnsureAsync(mapped, cancellationToken).ConfigureAwait(false);
                mapped.Report(_whisper.Status);
            }
            catch (Exception ex)
            {
                mapped.Report(SetupCopy.HumanFault(ex, "getting hearing ready", cancellationToken));
                if (profile.Id == "small")
                {
                    LastMessage = mapped is null ? "Hearing paused" : LastMessage;
                }
            }
        }

        var needsMind = profile.ProvisionFeatures.Contains("twin") || profile.ProvisionFeatures.Contains("vision");
        if (needsMind)
        {
            try
            {
                await EnsureMindAsync(allowInstall, pullVision: profile.ProvisionFeatures.Contains("vision"), mapped, cancellationToken).ConfigureAwait(false);
            }
            catch (Exception ex)
            {
                mapped.Report(SetupCopy.HumanFault(ex, "getting the talking mind ready", cancellationToken));
            }
        }
        else
        {
            mapped.Report("Small install: the talking mind stays a cloud Auto fallback. Ollama is not required.");
        }

        if (profile.ProvisionFeatures.Any(f => f is "voicebox" or "qwen3_tts" or "latentsync" or "voice_clone" or "avatar"))
        {
            mapped.Report("Voicebox: official MSI or Docker, then Probe. Setup continues if it is not listening.");
            mapped.Report("Qwen3-TTS: pip or Docker, OpenAI-compatible /v1/models. Setup continues if it is not listening.");
            mapped.Report("LatentSync: start the local HTTP engine. MuseTalk only when the license allows. Never Pinokio.");
        }

        if (profile.MachineRole)
        {
            mapped.Report("Dedicated PC: write install_profile so Models Studio and Terminal know this role.");
            mapped.Report(DedicatedRole.OvernightMaintenanceHint());
        }

        LastMessage = "Finished";
        mapped.Report(LastMessage);
    }

    public async Task<SetupReport> PrepareThisPcAsync(
        SetupDiskPlan plan,
        IProgress<SetupProgress> progress,
        CancellationToken cancellationToken = default)
    {
        var vaultOk = true;
        var hearingOk = false;
        var mindOk = false;
        var pictureOk = false;

        progress.Report(new SetupProgress(SetupTasks.Vault, "working", "Opening your stories folder…"));
        try
        {
            AppPaths.EnsureDirectories();
            progress.Report(new SetupProgress(SetupTasks.Vault, "ready", "Stories are kept in Documents."));
        }
        catch (Exception ex)
        {
            vaultOk = false;
            progress.Report(new SetupProgress(
                SetupTasks.Vault,
                "failed",
                SetupCopy.HumanFault(ex, "opening your stories folder", cancellationToken)));
            return Finish(false, false, false, false);
        }

        if (!plan.CanHear)
        {
            progress.Report(new SetupProgress(SetupTasks.Hearing, "failed", SetupCopy.LowDiskHearing()));
        }
        else
        {
            progress.Report(new SetupProgress(SetupTasks.Hearing, "working", "Getting ready to hear you speak…"));
            try
            {
                await _whisper.DownloadAndEnsureAsync(
                    new Progress<string>(m => progress.Report(new SetupProgress(SetupTasks.Hearing, "working", m))),
                    cancellationToken).ConfigureAwait(false);
                hearingOk = _whisper.IsReady;
                progress.Report(new SetupProgress(
                    SetupTasks.Hearing,
                    hearingOk ? "ready" : "failed",
                    hearingOk ? "Heirloom can hear you." : _whisper.Status));
            }
            catch (Exception ex)
            {
                progress.Report(new SetupProgress(
                    SetupTasks.Hearing,
                    "failed",
                    SetupCopy.HumanFault(ex, "getting hearing ready", cancellationToken)));
            }
        }

        if (!plan.CanThink)
        {
            progress.Report(new SetupProgress(SetupTasks.Mind, "failed", SetupCopy.LowDiskMind()));
        }
        else
        {
            progress.Report(new SetupProgress(
                SetupTasks.Mind,
                "working",
                "Windows may ask once if a helper can be installed. Choose Yes."));
            try
            {
                var mindProgress = new Progress<string>(m =>
                    progress.Report(new SetupProgress(SetupTasks.Mind, "working", SetupCopy.FriendlyLine(m))));
                mindOk = await EnsureMindAsync(allowInstall: true, pullVision: false, mindProgress, cancellationToken).ConfigureAwait(false);
                progress.Report(new SetupProgress(
                    SetupTasks.Mind,
                    mindOk ? "ready" : "failed",
                    mindOk
                        ? "The Twin can think on this computer."
                        : string.IsNullOrWhiteSpace(LastMessage)
                            ? SetupCopy.LowDiskMind()
                            : LastMessage));
            }
            catch (Exception ex)
            {
                progress.Report(new SetupProgress(
                    SetupTasks.Mind,
                    "failed",
                    SetupCopy.HumanFault(ex, "getting the talking mind ready", cancellationToken)));
            }
        }

        if (!mindOk)
        {
            progress.Report(new SetupProgress(
                SetupTasks.Picture,
                "skipped",
                "We'll skip the talking picture until the Twin can think here."));
        }
        else if (!plan.CanPicture)
        {
            progress.Report(new SetupProgress(SetupTasks.Picture, "skipped", SetupCopy.SkipPictureDisk()));
        }
        else if (!SetupCopy.LooksLikeNvidiaGpu())
        {
            progress.Report(new SetupProgress(SetupTasks.Picture, "skipped", SetupCopy.SkipPictureGpu()));
        }
        else
        {
            progress.Report(new SetupProgress(SetupTasks.Picture, "working", "Preparing the talking picture. This can take a while."));
            try
            {
                var pictureProgress = new Progress<string>(m =>
                    progress.Report(new SetupProgress(SetupTasks.Picture, "working", SetupCopy.FriendlyLine(m))));
                var probe = await _avatar.EnsureAsync(pictureProgress, cancellationToken).ConfigureAwait(false);
                pictureOk = probe.Ready;
                progress.Report(new SetupProgress(
                    SetupTasks.Picture,
                    pictureOk ? "ready" : "skipped",
                    pictureOk
                        ? "The talking picture is ready in Video studio."
                        : SetupCopy.SkipPictureFailed("It did not finish this time.")));
            }
            catch (Exception ex)
            {
                progress.Report(new SetupProgress(
                    SetupTasks.Picture,
                    "skipped",
                    SetupCopy.SkipPictureFailed(SetupCopy.HumanFault(ex, "preparing the talking picture", cancellationToken))));
            }
        }

        return Finish(vaultOk, hearingOk, mindOk, pictureOk);

        static SetupReport Finish(bool vault, bool hearing, bool mind, bool picture) =>
            new(
                vault,
                hearing,
                mind,
                picture,
                SetupCopy.DoneHeadline(hearing, mind, picture),
                SetupCopy.DoneBody(hearing, mind, picture));
    }

    private async Task<bool> EnsureMindAsync(
        bool allowInstall,
        bool pullVision,
        IProgress<string> progress,
        CancellationToken cancellationToken)
    {
        if (await _ollama.EnsureRunningAsync(progress, cancellationToken).ConfigureAwait(false))
        {
            return await PullMindsAsync(pullVision, progress, cancellationToken).ConfigureAwait(false);
        }

        if (!allowInstall)
        {
            LastMessage = "The talking mind isn't on this computer yet. Open Getting started.";
            progress.Report(LastMessage);
            return false;
        }

        var installed = await InstallOllamaAsync(progress, cancellationToken).ConfigureAwait(false);
        if (!installed)
        {
            return false;
        }

        if (!await _ollama.EnsureRunningAsync(progress, cancellationToken).ConfigureAwait(false))
        {
            LastMessage = "The helper is installed, but it has not started yet. Tap Try again in a moment.";
            progress.Report(LastMessage);
            return false;
        }

        return await PullMindsAsync(pullVision, progress, cancellationToken).ConfigureAwait(false);
    }

    private async Task<bool> PullMindsAsync(bool pullVision, IProgress<string> progress, CancellationToken cancellationToken)
    {
        await _ollama.ProbeAsync(cancellationToken).ConfigureAwait(false);
        if (_ollama.ChatModel is null)
        {
            LastMessage = await _ollama.PullAsync(SetupCopy.TwinMindName, progress, cancellationToken).ConfigureAwait(false);
        }
        else
        {
            LastMessage = "The talking mind is ready.";
            progress.Report(LastMessage);
        }

        if (pullVision && _ollama.IsReachable && !_ollama.Models.Any(m => m.Contains("llava", StringComparison.OrdinalIgnoreCase)))
        {
            await _ollama.PullAsync("llava", progress, cancellationToken).ConfigureAwait(false);
        }

        await _ollama.ProbeAsync(cancellationToken).ConfigureAwait(false);
        return _ollama.ChatModel is not null;
    }

    private async Task<bool> InstallOllamaAsync(IProgress<string> progress, CancellationToken cancellationToken)
    {
        progress.Report("Downloading the talking mind helper…");
        var setup = Path.Combine(Path.GetTempPath(), "Heirloom-OllamaSetup.exe");
        try
        {
            await SetupCopy.DownloadToFileAsync(
                DownloadHttp,
                SetupCopy.OllamaSetupUrl,
                setup,
                "Talking mind helper",
                progress,
                cancellationToken).ConfigureAwait(false);
        }
        catch (Exception ex)
        {
            LastMessage = SetupCopy.HumanFault(ex, "downloading the talking mind helper", cancellationToken);
            progress.Report(LastMessage);
            return false;
        }

        progress.Report("Windows may ask once if a helper can be installed. Choose Yes.");
        try
        {
            using var process = Process.Start(new ProcessStartInfo
            {
                FileName = setup,
                Arguments = "/VERYSILENT /NORESTART /SUPPRESSMSGBOXES",
                UseShellExecute = true,
            });
            if (process is null)
            {
                LastMessage = "Windows did not start the helper. Tap Try again.";
                progress.Report(LastMessage);
                return false;
            }

            using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
            timeout.CancelAfter(TimeSpan.FromMinutes(15));
            try
            {
                await process.WaitForExitAsync(timeout.Token).ConfigureAwait(false);
            }
            catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
            {
                LastMessage = "The helper is taking too long. Tap Try again.";
                progress.Report(LastMessage);
                return false;
            }

            if (process.ExitCode != 0)
            {
                LastMessage = SetupCopy.HumanInstallerExit(process.ExitCode);
                progress.Report(LastMessage);
                return false;
            }
        }
        catch (Exception ex)
        {
            LastMessage = SetupCopy.HumanFault(ex, "installing the talking mind helper", cancellationToken);
            progress.Report(LastMessage);
            return false;
        }

        progress.Report("Starting the talking mind helper…");
        if (await _ollama.WaitReachableAsync(TimeSpan.FromSeconds(20), cancellationToken).ConfigureAwait(false))
        {
            return true;
        }

        _ollama.TryStartServe();
        if (await _ollama.WaitReachableAsync(TimeSpan.FromSeconds(70), cancellationToken).ConfigureAwait(false))
        {
            return true;
        }

        if (_ollama.FindExe() is not null)
        {
            LastMessage = "The helper is installed, but it has not started yet. Tap Try again in a moment.";
            progress.Report(LastMessage);
            return false;
        }

        LastMessage = "The helper finished, but Heirloom cannot find it yet. Tap Try again in a moment.";
        progress.Report(LastMessage);
        return false;
    }
}
