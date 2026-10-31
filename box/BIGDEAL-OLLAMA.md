# Ollama on BIGDEAL (Windows, LAN only)

BIGDEAL is the Windows PC with the RTX PRO 6000 Blackwell (96 GB). It serves `gpt-oss:120b` to the Twin Box on the LAN. The box still runs its own Ollama (`qwen2.5:14b` and `qwen2.5vl:7b`) and uses that when BIGDEAL does not answer. No cloud model is involved.

`HEIRLOOM_BRAIN_MODEL` changes the tag. The default call passes `think` `low` and `num_predict` 2500. The reply is the `content` field. The `thinking` trace is not shown.

When the 96GB card leaves, use `qwen3:32b` and leave thinking off:

```text
HEIRLOOM_BRAIN_MODEL=qwen3:32b
```

That tag is called with `think` false. `qwen3:32b` is the documented alternate, not a second live default.

Twin Box address used by the firewall rule: `192.168.0.110`.

## 1. Install Ollama and pull the model

Install Ollama for Windows, then in PowerShell:

```powershell
ollama pull gpt-oss:120b
```

## 2. Listen on the LAN interface

Ollama must bind beyond localhost. Set the user environment variable and quit Ollama from the tray so it restarts with the new value:

```powershell
[System.Environment]::SetEnvironmentVariable("OLLAMA_HOST", "0.0.0.0:11434", "User")
```

`0.0.0.0` is the bind address. It is not the address the Twin Box calls.

## 3. Firewall: only the Twin Box

Allow TCP 11434 from `192.168.0.110` and leave every other address blocked:

```powershell
New-NetFirewallRule `
  -DisplayName "Ollama LAN Heirloom Twin Box" `
  -Direction Inbound `
  -Protocol TCP `
  -LocalPort 11434 `
  -RemoteAddress 192.168.0.110 `
  -Action Allow
```

Confirm with `Get-NetFirewallRule -DisplayName "Ollama LAN Heirloom Twin Box"`.

## 4. Point the Twin Box at BIGDEAL

On the Twin Box, pass the BIGDEAL LAN address. Replace the example address with the address BIGDEAL actually has:

```bash
sudo bash box/install.sh --brain-url http://192.168.0.50:11434
```

That writes:

```text
HEIRLOOM_BRAIN_URL=http://192.168.0.50:11434
HEIRLOOM_BRAIN_MODEL=gpt-oss:120b
HEIRLOOM_BRAIN_STRATEGY=single
```

The URL has to be a private LAN IP. A public host is rejected. The owner can change the URL, model, and an optional token in the app (Models on Windows, or `PUT /api/brain`).

The token is sent only as `Authorization: Bearer`. Ollama itself does not check it. Set `HEIRLOOM_BRAIN_TOKEN` only when a proxy on BIGDEAL expects that header. Do not put the token in the URL.

## 5. What the box does with it

Each chat tries BIGDEAL first, with a short connect timeout and a cached health check. If BIGDEAL is quiet, the reply comes from the box model. If `ollama ps` or `/api/ps` shows a loaded box model with `size_vram` smaller than `size` (not 100% GPU), Caretaker restarts the box Ollama container and the turn prefers BIGDEAL.

`/api/health` includes `brain.answered` and the model name. The studio status line shows the same.
