using System.Net;
using System.Net.Sockets;
using System.Text.Json;

namespace Heirloom.BoxCore;

/// <summary>
/// LAN address check and Ollama GPU residency for the primary brain.
/// Mirrors the box rules: private IPs only, optional bearer token stays out of the URL.
/// </summary>
public static class BrainRoute
{
    public static bool TryNormalizeLanUrl(string? raw, out string normalized, out string error)
    {
        normalized = "";
        error = "";
        var text = (raw ?? "").Trim();
        if (text.Length == 0)
        {
            error = "Brain URL is empty";
            return false;
        }

        if (!Uri.TryCreate(text, UriKind.Absolute, out var uri)
            || (uri.Scheme != "http" && uri.Scheme != "https"))
        {
            error = "Brain URL must be http or https";
            return false;
        }

        if (!string.IsNullOrEmpty(uri.UserInfo))
        {
            error = "Put the token in the header, not the URL";
            return false;
        }

        var hostText = uri.Host.Trim('[', ']');
        if (!IPAddress.TryParse(hostText, out var ip))
        {
            error = "Brain URL must be a LAN IP address";
            return false;
        }

        if (!IsLan(ip))
        {
            error = "Brain URL must stay on the LAN";
            return false;
        }

        var host = ip.ToString();
        if (host is "192.168.0.16" or "192.168.0.19")
        {
            error = "That address is off limits";
            return false;
        }

        var port = uri.IsDefaultPort ? 11434 : uri.Port;
        if (port is < 1 or > 65535)
        {
            error = "Brain URL port is invalid";
            return false;
        }

        var shown = ip.AddressFamily == AddressFamily.InterNetworkV6 ? $"[{host}]" : host;
        normalized = $"{uri.Scheme}://{shown}:{port}";
        return true;
    }

    /// <summary>
    /// LAN IP, or the Odysseus compose service name. Default ports are 7011 and 7000.
    /// </summary>
    public static bool TryNormalizeOdysseusUrl(string? raw, out string normalized, out string error)
    {
        normalized = "";
        error = "";
        var text = (raw ?? "").Trim();
        if (text.Length == 0)
        {
            error = "Odysseus URL is empty";
            return false;
        }

        if (!Uri.TryCreate(text, UriKind.Absolute, out var uri)
            || (uri.Scheme != "http" && uri.Scheme != "https"))
        {
            error = "Odysseus URL must be http or https";
            return false;
        }

        if (!string.IsNullOrEmpty(uri.UserInfo))
        {
            error = "Put the Odysseus token in the secret file, not the URL";
            return false;
        }

        var hostText = uri.Host.Trim('[', ']');
        if (hostText.Equals("odysseus", StringComparison.OrdinalIgnoreCase))
        {
            var servicePort = uri.IsDefaultPort ? 7000 : uri.Port;
            if (servicePort is < 1 or > 65535)
            {
                error = "Odysseus URL port is invalid";
                return false;
            }

            normalized = $"{uri.Scheme}://odysseus:{servicePort}";
            return true;
        }

        if (!IPAddress.TryParse(hostText, out var ip))
        {
            error = "Odysseus URL must be a LAN IP or the odysseus service name";
            return false;
        }

        if (!IsLan(ip))
        {
            error = "Odysseus URL must stay on the LAN";
            return false;
        }

        var host = ip.ToString();
        if (host is "192.168.0.16" or "192.168.0.19")
        {
            error = "That address is off limits";
            return false;
        }

        var port = uri.IsDefaultPort ? 7011 : uri.Port;
        if (port is < 1 or > 65535)
        {
            error = "Odysseus URL port is invalid";
            return false;
        }

        var shown = ip.AddressFamily == AddressFamily.InterNetworkV6 ? $"[{host}]" : host;
        normalized = $"{uri.Scheme}://{shown}:{port}";
        return true;
    }

    public static bool TryNormalizeStrategy(string? raw, out string strategy, out string error)
    {
        var text = (raw ?? "").Trim().ToLowerInvariant();
        if (text.Length == 0)
        {
            strategy = "single";
            error = "";
            return true;
        }

        strategy = text switch
        {
            "single" => "single",
            "single+odysseus_research" or "single_odysseus_research" or "odysseus_research" => "single+odysseus_research",
            "ensemble_synthesis" or "ensemble" => "ensemble_synthesis",
            "judge_pick_best" or "judge" => "judge_pick_best",
            _ => "",
        };
        if (strategy.Length == 0)
        {
            error = "Strategy must be single, single+odysseus_research, ensemble_synthesis, or judge_pick_best.";
            return false;
        }

        error = "";
        return true;
    }

    public static bool LoadedModelsOffGpu(string? json)
    {
        if (string.IsNullOrWhiteSpace(json))
        {
            return false;
        }

        try
        {
            using var doc = JsonDocument.Parse(json);
            if (!doc.RootElement.TryGetProperty("models", out var models) || models.ValueKind != JsonValueKind.Array)
            {
                return false;
            }

            foreach (var model in models.EnumerateArray())
            {
                var size = ReadLong(model, "size");
                var vram = ReadLong(model, "size_vram");
                if (size > 0 && vram < size)
                {
                    return true;
                }
            }
        }
        catch (JsonException)
        {
            return false;
        }

        return false;
    }

    public static bool ProcessorOffGpu(string? ollamaPs)
    {
        var blob = ollamaPs ?? "";
        if (blob.Length == 0)
        {
            return false;
        }

        if (blob.Contains("100% CPU", StringComparison.Ordinal) || blob.Contains("Failed to initialize NVML", StringComparison.Ordinal))
        {
            return true;
        }

        foreach (var line in blob.Split('\n'))
        {
            var lowered = line.Trim().ToLowerInvariant();
            if (lowered.Length == 0 || lowered.StartsWith("name", StringComparison.Ordinal))
            {
                continue;
            }

            if (lowered.Contains("100% gpu", StringComparison.Ordinal))
            {
                continue;
            }

            if (lowered.Contains("cpu", StringComparison.Ordinal) && lowered.Contains('%'))
            {
                return true;
            }
        }

        return false;
    }

    private static bool IsLan(IPAddress ip)
    {
        if (IPAddress.IsLoopback(ip))
        {
            return true;
        }

        if (ip.IsIPv6LinkLocal)
        {
            return true;
        }

        var bytes = ip.GetAddressBytes();
        if (bytes.Length == 4)
        {
            if (bytes[0] == 10)
            {
                return true;
            }

            if (bytes[0] == 172 && bytes[1] >= 16 && bytes[1] <= 31)
            {
                return true;
            }

            if (bytes[0] == 192 && bytes[1] == 168)
            {
                return true;
            }

            if (bytes[0] == 169 && bytes[1] == 254)
            {
                return true;
            }

            return false;
        }

        return bytes.Length == 16 && (bytes[0] & 0xFE) == 0xFC;
    }

    private static long ReadLong(JsonElement model, string name)
    {
        if (!model.TryGetProperty(name, out var node))
        {
            return 0;
        }

        return node.TryGetInt64(out var value) ? value : 0;
    }
}
