using System.Net.NetworkInformation;
using Microsoft.Win32;
using Heirloom.BoxCore;

namespace Heirloom.Companion;

/// <summary>
/// After sleep or a network change, in-flight polls are cancelled so the next pass opens a new socket.
/// </summary>
internal static class MachineSignals
{
    public static IDisposable Attach(WakeHub hub)
    {
        if (!OperatingSystem.IsWindows())
        {
            return new Subscription();
        }

        PowerModeChangedEventHandler power = (_, args) =>
        {
            if (args.Mode == PowerModes.Resume)
            {
                hub.Raise(WakeReason.SleepResume, DateTimeOffset.UtcNow);
            }
        };
        NetworkAddressChangedEventHandler address = (_, _) =>
            hub.Raise(WakeReason.Network, DateTimeOffset.UtcNow);
        NetworkAvailabilityChangedEventHandler availability = (_, _) =>
            hub.Raise(WakeReason.Network, DateTimeOffset.UtcNow);
        try
        {
            SystemEvents.PowerModeChanged += power;
            NetworkChange.NetworkAddressChanged += address;
            NetworkChange.NetworkAvailabilityChanged += availability;
        }
        catch (Exception)
        {
            return new Subscription();
        }

        return new Subscription(() =>
        {
            SystemEvents.PowerModeChanged -= power;
            NetworkChange.NetworkAddressChanged -= address;
            NetworkChange.NetworkAvailabilityChanged -= availability;
        });
    }

    private sealed class Subscription : IDisposable
    {
        private readonly Action? _dispose;

        public Subscription(Action? dispose = null)
        {
            _dispose = dispose;
        }

        public void Dispose() => _dispose?.Invoke();
    }
}
