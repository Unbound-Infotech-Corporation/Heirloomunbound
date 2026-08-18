using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using Heirloom.Services;

namespace Heirloom.ViewModels;

public partial class MixerViewModel : ObservableObject
{
    private readonly AppHost _host;

    public MixerViewModel(AppHost host)
    {
        _host = host;
        SessionVolume = host.Mixer.SessionVolume;
        InputGain = host.Settings.Current.InputGain;
        NoiseGate = host.Settings.Current.NoiseGate;
        HighPass = host.Settings.Current.HighPass;
        LiveListen = host.Settings.Current.LiveListen;
        Muted = host.Settings.Current.SessionMuted;
        RefreshDevices();
    }

    public ObservableCollection<string> Inputs { get; } = [];
    public ObservableCollection<string> Outputs { get; } = [];

    [ObservableProperty] private int _sessionVolume;
    [ObservableProperty] private double _inputGain;
    [ObservableProperty] private double _noiseGate;
    [ObservableProperty] private bool _highPass;
    [ObservableProperty] private bool _liveListen;
    [ObservableProperty] private bool _muted;
    [ObservableProperty] private string _selectedInput = "";
    [ObservableProperty] private string _selectedOutput = "";
    [ObservableProperty] private string _inputSummary = "Default microphone";
    [ObservableProperty] private string _outputSummary = "Default speakers";
    [ObservableProperty] private string _status = "Session: Heirloom";

    partial void OnSessionVolumeChanged(int value) => _host.Mixer.SessionVolume = value;
    partial void OnInputGainChanged(double value)
    {
        _host.Settings.Current.InputGain = value;
        _host.Settings.Save();
    }

    partial void OnNoiseGateChanged(double value)
    {
        _host.Settings.Current.NoiseGate = value;
        _host.Settings.Save();
    }

    partial void OnHighPassChanged(bool value)
    {
        _host.Settings.Current.HighPass = value;
        _host.Settings.Save();
    }

    partial void OnLiveListenChanged(bool value)
    {
        _host.Settings.Current.LiveListen = value;
        _host.Settings.Save();
        Status = value ? "Live listen on — you will hear yourself in the Heirloom session." : "Heirloom session";
    }

    partial void OnMutedChanged(bool value) => _host.Mixer.SetMuted(value);

    partial void OnSelectedInputChanged(string value)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            return;
        }

        var devices = _host.Capture.ListWaveInDevices();
        var index = devices.ToList().FindIndex(n => n == value);
        if (index >= 0)
        {
            _host.Settings.Current.InputDeviceNumber = index;
            _host.Settings.Save();
            InputSummary = value;
        }
    }

    partial void OnSelectedOutputChanged(string value)
    {
        var match = _host.Mixer.Outputs.FirstOrDefault(d => d.Name == value);
        if (match is not null)
        {
            _host.Mixer.SetOutputDevice(match.Id);
            OutputSummary = match.Name;
        }
    }

    [RelayCommand]
    public void RefreshDevices()
    {
        _host.Mixer.RefreshDevices();
        Inputs.Clear();
        foreach (var name in _host.Capture.ListWaveInDevices())
        {
            Inputs.Add(name);
        }

        Outputs.Clear();
        foreach (var device in _host.Mixer.Outputs)
        {
            Outputs.Add(device.Name);
        }

        if (Inputs.Count > 0)
        {
            var index = Math.Clamp(_host.Settings.Current.InputDeviceNumber, 0, Inputs.Count - 1);
            SelectedInput = Inputs[index];
        }

        SelectedOutput = _host.Mixer.Outputs.FirstOrDefault(d => d.IsDefault)?.Name
            ?? Outputs.FirstOrDefault()
            ?? "Speakers";
        InputSummary = SelectedInput.Length == 0 ? "Microphone" : SelectedInput;
        OutputSummary = SelectedOutput;
        Status = Muted
            ? "Heirloom session muted"
            : $"Heirloom session  ·  {SessionVolume}%  ·  {Outputs.Count} outputs";
    }

    [RelayCommand]
    public void ToggleMute() => Muted = !Muted;
}
