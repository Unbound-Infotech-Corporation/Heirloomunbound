using System.Net.Http;
using System.Security.Cryptography.X509Certificates;
using Heirloom.BoxCore;
using Microsoft.Extensions.DependencyInjection;

namespace Heirloom.Services;

public sealed class AppHost : IDisposable
{
    public static AppHost Current { get; private set; } = null!;

    public IServiceProvider Services { get; }
    public SettingsStore Settings { get; }
    public CredentialStore Credentials { get; }
    public MixerSessionService Mixer { get; }
    public CaptureService Capture { get; }
    public WhisperService Whisper { get; }
    public OllamaService Ollama { get; }
    public VaultService Vault { get; }
    public CommandPoller Poller { get; }
    public PcToolkit Pc { get; }
    public SpeakService Speak { get; }
    public AvatarEngineService AvatarEngine { get; }
    public VideoEngineService VideoEngine { get; }
    public AuthService Auth { get; }
    public HeirloomApiClient Api { get; }
    public ProvisionService Provision { get; }
    public ScreenCaptureService Screen { get; }

    public string Version => "0.5.1";
    public string BuildId => Settings.Current.BuildId;
    public bool CanEdit =>
        !string.Equals(Settings.Current.AppMode, "heir", StringComparison.OrdinalIgnoreCase);

    public AppHost()
    {
        NativeMethods.SetAppIdentity();
        Settings = new SettingsStore();
        Settings.Load();
        Credentials = new CredentialStore();

        var services = new ServiceCollection();
        services.AddSingleton(Settings);
        services.AddSingleton(Credentials);
        services.AddHttpClient<HeirloomApiClient>(client =>
        {
            client.Timeout = TimeSpan.FromSeconds(60);
        }).ConfigurePrimaryHttpMessageHandler(() =>
        {
            var handler = new HttpClientHandler();
            handler.ServerCertificateCustomValidationCallback = (message, cert, chain, errors) =>
            {
                var current = Settings.Current;
                var boxHost = "";
                try
                {
                    boxHost = new Uri(BoxLink.ApiBase(current.RunMode, current.BoxUrl, current.BackendUrl)).Host;
                }
                catch (UriFormatException)
                {
                    boxHost = "";
                }

                X509Certificate2? leaf = cert is null ? null : new X509Certificate2(cert);
                try
                {
                    return CertificatePin.Validate(
                        BoxLink.IsBoxClient(current.RunMode),
                        boxHost,
                        current.BoxCertSha256,
                        current.BoxCaPem,
                        message.RequestUri?.Host,
                        leaf,
                        chain,
                        errors);
                }
                finally
                {
                    leaf?.Dispose();
                }
            };
            return handler;
        });
        services.AddSingleton<OllamaService>();
        services.AddSingleton<MixerSessionService>();
        services.AddSingleton<CaptureService>();
        services.AddSingleton<WhisperService>();
        services.AddSingleton<VaultService>();
        services.AddSingleton<ScreenCaptureService>();
        services.AddSingleton<SpeakService>();
        services.AddSingleton<AvatarEngineService>();
        services.AddSingleton<VideoEngineService>();
        services.AddSingleton<AuthService>();
        services.AddSingleton<ProvisionService>();
        services.AddSingleton<PcToolkit>();
        services.AddSingleton<CommandPoller>();
        Services = services.BuildServiceProvider();

        Api = Services.GetRequiredService<HeirloomApiClient>();
        Mixer = Services.GetRequiredService<MixerSessionService>();
        Capture = Services.GetRequiredService<CaptureService>();
        Whisper = Services.GetRequiredService<WhisperService>();
        Ollama = Services.GetRequiredService<OllamaService>();
        Vault = Services.GetRequiredService<VaultService>();
        Speak = Services.GetRequiredService<SpeakService>();
        AvatarEngine = Services.GetRequiredService<AvatarEngineService>();
        VideoEngine = Services.GetRequiredService<VideoEngineService>();
        Auth = Services.GetRequiredService<AuthService>();
        Provision = Services.GetRequiredService<ProvisionService>();
        Screen = Services.GetRequiredService<ScreenCaptureService>();
        Pc = Services.GetRequiredService<PcToolkit>();
        Poller = Services.GetRequiredService<CommandPoller>();
        Current = this;
    }

    public event Action? VaultPathChanged;
    public event Action? AppModeChanged;

    public void RaiseAppModeChanged() => AppModeChanged?.Invoke();

    public void SetVaultPath(string path)
    {
        var root = Path.GetFullPath(path.Trim());
        Directory.CreateDirectory(root);
        Settings.Current.LibraryPath = root;
        Settings.Save();
        Vault.Open();
        VaultPathChanged?.Invoke();
    }

    public async Task StartAsync()
    {
        Mixer.Start();
        Vault.Open();
        AutostartService.Apply(Settings.Current.Autostart);
        Auth.LoadBoxSession();
        Poller.Start();
        var pending = !Settings.Current.SetupComplete && !Settings.Current.SetupSkipped;
        if (BoxLink.StartsLocalModels(Settings.Current.RunMode) && !pending)
        {
            _ = Whisper.EnsureAsync();
            _ = Ollama.ProbeAsync();
        }

        await Task.CompletedTask;
    }

    public void Dispose()
    {
        Poller.Dispose();
        Pc.Dispose();
        Capture.Dispose();
        Mixer.Dispose();
        Whisper.Dispose();
        Vault.Dispose();
        Speak.Dispose();
    }
}
