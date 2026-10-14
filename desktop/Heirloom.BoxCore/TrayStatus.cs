using System.Globalization;
using System.Text.Json;

namespace Heirloom.BoxCore;

public enum BoxLamp
{
    Red,
    Amber,
    Green,
}

public sealed record BoxSnapshot(
    BoxLamp Lamp,
    string Address,
    int? LatencyMs,
    bool Reachable,
    bool ObserverPaused,
    string Tooltip);

public static class TrayStatus
{
    public static BoxLamp LampFrom(bool reachable, JsonElement? health)
    {
        if (!reachable || health is null)
        {
            return BoxLamp.Red;
        }

        if (!health.Value.TryGetProperty("observer", out var observer) || observer.ValueKind != JsonValueKind.Object)
        {
            return BoxLamp.Amber;
        }

        var paused = Flag(observer, "paused");
        var signal = Text(observer, "signal");
        var fps = Number(observer, "fps");
        if (!paused && string.Equals(signal, "signal", StringComparison.OrdinalIgnoreCase) && fps > 0)
        {
            return BoxLamp.Green;
        }

        return BoxLamp.Amber;
    }

    public static BoxSnapshot Describe(bool reachable, int? latencyMs, string? address, string? healthJson)
    {
        JsonElement? health = null;
        if (reachable && !string.IsNullOrWhiteSpace(healthJson))
        {
            try
            {
                using var doc = JsonDocument.Parse(healthJson);
                health = doc.RootElement.Clone();
            }
            catch (JsonException)
            {
                health = null;
            }
        }

        var lamp = LampFrom(reachable && health is not null, health);
        if (reachable && health is null)
        {
            lamp = BoxLamp.Amber;
        }

        if (!reachable)
        {
            lamp = BoxLamp.Red;
        }

        var host = string.IsNullOrWhiteSpace(address) ? BoxLink.DefaultBoxUrl : address.Trim();
        var paused = false;
        var lines = new List<string> { Head(host, latencyMs, lamp) };
        if (health is { } body)
        {
            lines.Add(ObserverLine(body, out paused));
            lines.Add(PresenceLine(body));
            var gpu = GpuLine(body);
            if (gpu.Length > 0)
            {
                lines.Add(gpu);
            }
        }
        else if (!reachable)
        {
            lines.Add("The Twin Box did not answer.");
        }
        else
        {
            lines.Add("The Twin Box answered, but Observer did not report a signal.");
        }

        return new BoxSnapshot(lamp, host, latencyMs, reachable && health is not null, paused, string.Join('\n', lines));
    }

    public static string PauseVerb(bool paused) => paused ? "Resume Observer" : "Pause Observer";

    private static string Head(string host, int? latencyMs, BoxLamp lamp)
    {
        var state = lamp switch
        {
            BoxLamp.Green => "connected",
            BoxLamp.Amber => "idle",
            _ => "offline",
        };
        var latency = latencyMs is null ? "" : " · " + latencyMs.Value.ToString(CultureInfo.InvariantCulture) + " ms";
        return "Twin Box " + host + " — " + state + latency;
    }

    private static string ObserverLine(JsonElement health, out bool paused)
    {
        paused = false;
        if (!health.TryGetProperty("observer", out var observer) || observer.ValueKind != JsonValueKind.Object)
        {
            return "Observer: not reported";
        }

        paused = Flag(observer, "paused");
        var signal = Text(observer, "signal");
        if (signal.Length == 0)
        {
            signal = "no signal";
        }

        var fps = Number(observer, "fps");
        var notes = (int)Number(observer, "notes_today");
        var state = paused ? "paused" : signal;
        return "Observer: " + state + ", " + fps.ToString("0.##", CultureInfo.InvariantCulture) + " fps, " + notes.ToString(CultureInfo.InvariantCulture) + " notes today";
    }

    private static string PresenceLine(JsonElement health)
    {
        if (!health.TryGetProperty("presence", out var presence) || presence.ValueKind != JsonValueKind.Object)
        {
            return "Presence: not reported";
        }

        var names = new List<string>();
        if (presence.TryGetProperty("present", out var present) && present.ValueKind == JsonValueKind.Array)
        {
            foreach (var row in present.EnumerateArray())
            {
                var name = row.ValueKind == JsonValueKind.Object ? Text(row, "name") : row.ToString();
                if (name.Length > 0)
                {
                    names.Add(name);
                }
            }
        }

        var cameras = new List<string>();
        if (presence.TryGetProperty("cameras", out var cams) && cams.ValueKind == JsonValueKind.Array)
        {
            foreach (var cam in cams.EnumerateArray())
            {
                var label = CameraLabel(cam);
                if (label.Length > 0)
                {
                    cameras.Add(label);
                }
            }
        }

        var who = names.Count == 0 ? "nobody present" : string.Join(", ", names);
        var eyes = cameras.Count == 0 ? "no cameras" : string.Join(", ", cameras);
        return "Presence: " + who + " · " + eyes;
    }

    private static string GpuLine(JsonElement health)
    {
        var gpu = "";
        var model = "";
        if (health.TryGetProperty("compute", out var compute) && compute.ValueKind == JsonValueKind.Object)
        {
            gpu = Text(compute, "gpu");
            model = Text(compute, "model");
        }

        if (model.Length == 0 && health.TryGetProperty("observer", out var observer))
        {
            model = Text(observer, "model");
        }

        if (gpu.Length == 0 && model.Length == 0)
        {
            return "";
        }

        if (gpu.Length == 0)
        {
            return "Model: " + model;
        }

        if (model.Length == 0)
        {
            return "GPU: " + gpu;
        }

        return "GPU: " + gpu + " · " + model;
    }

    private static string CameraLabel(JsonElement cam)
    {
        if (cam.ValueKind == JsonValueKind.String)
        {
            return cam.GetString() ?? "";
        }

        if (cam.ValueKind != JsonValueKind.Object)
        {
            return "";
        }

        foreach (var key in new[] { "name", "label", "id", "device" })
        {
            var text = Text(cam, key);
            if (text.Length > 0)
            {
                return text;
            }
        }

        return "";
    }

    private static bool Flag(JsonElement obj, string name) =>
        obj.TryGetProperty(name, out var value) &&
        (value.ValueKind == JsonValueKind.True ||
         (value.ValueKind == JsonValueKind.String && string.Equals(value.GetString(), "true", StringComparison.OrdinalIgnoreCase)));

    private static string Text(JsonElement obj, string name)
    {
        if (!obj.TryGetProperty(name, out var value))
        {
            return "";
        }

        return value.ValueKind == JsonValueKind.String ? value.GetString() ?? "" : value.ToString();
    }

    private static double Number(JsonElement obj, string name)
    {
        if (!obj.TryGetProperty(name, out var value))
        {
            return 0;
        }

        if (value.ValueKind == JsonValueKind.Number && value.TryGetDouble(out var number))
        {
            return number;
        }

        if (value.ValueKind == JsonValueKind.String &&
            double.TryParse(value.GetString(), NumberStyles.Float, CultureInfo.InvariantCulture, out var parsed))
        {
            return parsed;
        }

        return 0;
    }
}
