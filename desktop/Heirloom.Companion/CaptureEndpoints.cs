using NAudio.CoreAudioApi;

namespace Heirloom.Companion;

internal static class CaptureEndpoints
{
    public static IReadOnlyList<MicChoice> List()
    {
        var choices = new List<MicChoice> { new("", "Default microphone") };
        try
        {
            using var enumerator = new MMDeviceEnumerator();
            foreach (var device in enumerator.EnumerateAudioEndPoints(DataFlow.Capture, DeviceState.Active))
            {
                var name = string.IsNullOrWhiteSpace(device.FriendlyName) ? device.ID : device.FriendlyName;
                choices.Add(new MicChoice(device.ID, name));
            }
        }
        catch (Exception)
        {
            return choices;
        }

        return choices;
    }

    public static IReadOnlyCollection<string> ActiveIds()
    {
        var ids = new List<string>();
        foreach (var choice in List())
        {
            if (!string.IsNullOrWhiteSpace(choice.Id))
            {
                ids.Add(choice.Id);
            }
        }

        return ids;
    }

    public static MMDevice Open(MMDeviceEnumerator enumerator, string? id)
    {
        if (!string.IsNullOrWhiteSpace(id))
        {
            try
            {
                return enumerator.GetDevice(id);
            }
            catch (Exception)
            {
                // The saved endpoint is gone. The default capture device is the fallback.
            }
        }

        return enumerator.GetDefaultAudioEndpoint(DataFlow.Capture, Role.Multimedia);
    }
}

internal sealed class MicChoice
{
    public MicChoice(string id, string label)
    {
        Id = id;
        Label = label;
    }

    public string Id { get; }

    public string Label { get; }

    public override string ToString() => Label;
}
