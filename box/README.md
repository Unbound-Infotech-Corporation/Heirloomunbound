# Heirloom Twin Box

Headless Linux build of Heirloom Unbound for the owner's dedicated lab machine. The owner lives with it daily. The box keeps vault data, lab notes, and backups on local disk, and it records usefulness signals so the paid product can improve.

The Windows studio (`desktop/Heirloom/`) is not part of this box. Product version stays **0.5.1**. The FastAPI app version stays **0.3.0**.

## Hardware

A former game server is the intended machine. Ubuntu Server 24.04 LTS, no monitor after first setup.

| Piece | Need |
|---|---|
| CPU | 4 cores. More helps when Ollama is on CPU. |
| RAM | Reference lab machine: 32 GB. 16 GB still boots the stack; the capture ring stays at 64 MiB so it does not compete with Mongo and Ollama. |
| Disk | 100 GB free under `/var/lib/heirloom` (models, Mongo, vault, backups). |
| GPU | Reference lab card: NVIDIA RTX 3090, 24 GB. No GPU means CPU Ollama. The installer skips the driver, CUDA, and the container toolkit when `lspci` and `nvidia-smi` see nothing. The unattended USB path installs the latest production driver from NVIDIA's CUDA apt repo and refuses to continue until `nvidia-smi` reports the 3090. |
| Network | Ethernet on the LAN. SSH for a headless login. Ports 22, 80, and 443. |
| HDMI capture | Optional, lab only. See [OBSERVER.md](OBSERVER.md). UVC devices such as the EVGA XR1. Off unless you pass `--observer`. |
| USB webcams | Optional, lab only. See [PRESENCE.md](PRESENCE.md). One or more UVC cameras on the box. Off unless you pass `--presence`. |

### Default model from VRAM

The installer sets `OLLAMA_TWIN_MODEL` from the first GPU's VRAM. Qwen2.5 weights are Apache-2.0. A 4–7 GB card stays on 3B so context still fits.

| VRAM | Model |
|---|---|
| under 8 GB | `qwen2.5:3b` |
| 8 GB up to under 12 GB | `qwen2.5:7b` |
| 12 GB up to under 20 GB | `qwen2.5:14b` |
| 20 GB up to under 40 GB | `qwen2.5:32b` |
| 40 GB and above | `qwen2.5:72b` |

No GPU, or a driver that is not answering yet, is 0 MiB and selects `qwen2.5:3b`. Change the model later by editing `/var/lib/heirloom/box.env` and re-running the installer. Leave `OLLAMA_TWIN_MODEL` unset on a non-box process and the code default stays `llama3.1`.

With `--observer` on the reference box (RTX 3090, 24 GB, 32 GB RAM), the chat model is `qwen2.5:14b` and the vision model is `qwen2.5vl:7b`. `qwen2.5:32b` does not leave room for vision. The pair, the 19 GB estimate, and the unload schedule are in [OBSERVER.md](OBSERVER.md).

`--presence` does not change that pair. YuNet and SFace are small. Presence uses the GPU only when at least 512 MiB is free, and otherwise stays on CPU so Ollama keeps the card.

Do not install XTTS-v2, F5-TTS weights, or LivePortrait bundled face models. Optional speech on the box is Chatterbox (MIT), behind `--with-chatterbox`.

## Install from a fresh Ubuntu USB

The unattended path is one USB stick that installs Ubuntu Server 24.04 and Heirloom with no prompts. It erases only the disk whose serial you put in `box/autoinstall/config.env`. Boot that stick only on the Twin Box. The steps, including Secure Boot and how to flash the ISO, are in [AUTOINSTALL.md](AUTOINSTALL.md).

A manual install still works:

1. Write Ubuntu Server 24.04 LTS to a USB stick and install it on the lab machine. Create a normal user. Add that user's SSH public key during the Ubuntu installer if you can.
2. Copy this repo onto the machine, or clone it. `git` is installed by `box/install.sh` so later updates work.
3. From the repo root:

```bash
sudo bash box/install.sh
```

Useful flags, which can be combined:

```bash
sudo bash box/install.sh --dry-run
sudo bash box/install.sh --dev-tools --tailscale --with-chatterbox
sudo bash box/install.sh --observer
sudo bash box/install.sh --observer-audio
sudo bash box/install.sh --presence
sudo bash box/install.sh --presence --with-chatterbox
```

| Flag | What it does |
|---|---|
| `--dry-run` | Writes the plan to the log and changes nothing. |
| `--unattended` | Answers apt, debconf, and package prompts automatically. Ollama pulls stay non-interactive. If the NVIDIA driver needs a reboot, the script exits 75 before containers start. |
| `--dev-tools` | git, GitHub CLI, Node.js 22, Python 3.12, uv, Cursor CLI, Claude Code. |
| `--tailscale` | Installs Tailscale. You log in yourself. |
| `--with-chatterbox` | Optional Chatterbox TTS container on `127.0.0.1:8010`. |
| `--observer` | Lab only. Watches a UVC HDMI capture card, its HDMI audio, and a microphone, and writes learned notes. Product installs leave this off. |
| `--observer-audio` | Same as `--observer`. Names the audio install directly. |
| `--presence` | Lab only. Watches USB webcams and greets people the owner has taught. Product installs leave this off. |

The script is idempotent. It uses `set -euo pipefail` and appends to `/var/log/heirloom-box-install.log`. A non-root dry-run that cannot write that path uses `$TMPDIR/heirloom-box-install.log`.

What a real run installs:

- Docker Engine and the Compose plugin, MongoDB 7 as a container (no host port), the API on `127.0.0.1:8001`, and the built web UI behind Caddy.
- Caddy on ports 80 and 443 with an internal CA (`tls internal`). HTTP redirects to HTTPS.
- Ollama on `127.0.0.1:11434`, then `ollama pull` of the VRAM model.
- The latest production NVIDIA driver from the official CUDA apt repository (`cuda-keyring`, package `nvidia-open`) when a GPU is present, plus the CUDA toolkit, cuDNN, `nvtop`, and the NVIDIA container toolkit. `NVIDIA_DRIVER_BRANCH=latest` is the default. A branch such as `580` installs `nvidia-driver-pinning-580` first. The RTX 3090 uses the open kernel modules. `ubuntu-drivers` is not used. If `nvidia-smi` does not answer yet, reboot and run the installer again before GPU containers start. Later upgrades: `sudo heirloom-box update-drivers`.
- Hardened OpenSSH (public-key only, root login off) only when some `authorized_keys` file is non-empty. A fresh install without a key keeps password login so you are not locked out.
- `unattended-upgrades`.
- `ufw`: deny incoming, allow OpenSSH, `80/tcp`, and `443/tcp`.
- Nightly cron: `03:00` `heirloom-box backup` (Mongo archive + vault tarball, 14 copies), `03:15` `heirloom-box report` (markdown under `/var/lib/heirloom/lab-reports`, 30 files).
- With `--observer` or `--observer-audio`: `ffmpeg`, `v4l-utils`, Tesseract, `alsa-utils`, a venv with faster-whisper plus `nvidia-cublas-cu12` and `nvidia-cudnn-cu12`, `heirloom-observer.service` (restarted after `box.env` is written), a udev rule for UVC replug, `HEIRLOOM_OBSERVER=1`, `OBSERVER_AUDIO=1`, and a `03:20` digest. The marker `/etc/heirloom/observer.enabled` keeps Observer on when you later run the installer without the flag. Wiring, the two audio streams, privacy rules, and the vision-model table are in [OBSERVER.md](OBSERVER.md).
- Screen can come from the Windows companion instead of the EVGA HDMI box. `OBSERVER_SOURCE` in `box.env` is `auto`, `network`, or `capture` (the installer writes `auto`). `auto` uses a companion JPEG when one arrived in the last few seconds (`OBSERVER_NETWORK_FRESH_S`, default 3) and otherwise opens `/dev/video0`. The JPEG is posted to the box on the home LAN with the same sign-in and certificate pin as the microphone. `GET /api/health` reports `observer.source` and `observer.signal` (`ok` when the network picture is fresh). The frame still goes through the privacy filter, `qwen2.5vl:7b` when that is the vision tag, and the same retention cap. The companion sends the primary display at `OBSERVER_SAMPLE_FPS` (default 2), scaled to about 1920 wide, while the source is `auto` or `network`. Screen is on until you turn it off. Pause sends nothing. `capture` keeps the HDMI card.
- With `--presence`: `python3-opencv`, `v4l-utils`, `ffmpeg`, YuNet (MIT) and SFace (Apache-2.0), `heirloom-presence.service`, and a udev rule. The marker `/etc/heirloom/presence.enabled` keeps Presence on later. Cameras, consent, and the GPU budget are in [PRESENCE.md](PRESENCE.md). `--with-chatterbox` turns on spoken greetings. Unknown-face thumbnails stay off.

Data lives under `/var/lib/heirloom` (mongo, ollama, vault, lab JSONL, reports, backups, Caddy). The env file is `/var/lib/heirloom/box.env` mode `600`. The installer generates a local `CONNECTOR_SECRET_KEY` once. It never writes a GitHub token, mailbox password, or vendor key.

The box turns these on in `box.env`:

- `HEIRLOOM_LLM_PROVIDER=ollama` (OpenAI-compatible `/v1/chat/completions`, no silent cloud fallback)
- `HEIRLOOM_LAB_MODE=1` and `HEIRLOOM_BOX=1`
- `HEIRLOOM_AI_DISCLOSURE=1` so send/post approval cards include the disclosure sentence before anything is sent

Unset, those flags stay off. Windows, the public web app, and the existing Emergent / Anthropic / OpenAI path keep working.

## First login

From the machine itself, or from SSH. The installer adds the user who ran `sudo` to the `docker` group. Open a new login so that group applies, then:

```bash
heirloom-box status
```

That prints Compose services, GPU, disk for `/var/lib/heirloom`, the last backup, the last lab report, the Observer section (device, signal, fps, model, pause, notes today, disk), the Presence section (cameras, fps, enrolled, who is here, pause), and `GET /api/health`. Health includes `observer` and `presence` even when they are off.

Create the owner account in the web UI (the same signup the public app uses). Lab controls appear only for that owner session. Heirs and callers get 404 from `/api/lab/*` and do not see the Lab dock item.

If you passed `--dev-tools`, sign in yourself. The installer does not store credentials:

```bash
gh auth login
agent login
claude
```

`agent login` is the Cursor CLI. Some installs name the binary `cursor-agent`. In Claude Code, run `/login`.

Optional GitHub filing of the nightly report stays off until you set both `GITHUB_TOKEN` and `HEIRLOOM_LAB_GITHUB_REPO=owner/name` in `box.env` (an `owner/name` slug, not a URL). Issues are labeled `lab-report`.

## Reaching it from other PCs

On the LAN, open `https://<box-ip>/`. The installer logs the first address from `hostname -I`.

Caddy's certificate is from its local CA. After the first real start, copy this file to the other PC and trust it:

```text
/var/lib/heirloom/caddy/caddy/pki/authorities/local/root.crt
```

The API is not published on the LAN except through Caddy (`/api/*` → `api:8001`). Ollama and Mongo stay on the box.

Tailscale, if you installed it:

```bash
sudo tailscale up
```

Then use the Tailscale name or address the same way. The installer does not log in for you.

## Updating

From the repo root on the box:

```bash
git pull
sudo bash box/install.sh
```

Re-running is safe. It keeps the existing connector secret and rewrites the service env flags. Add `--dev-tools`, `--tailscale`, or `--with-chatterbox` again if you still want those. Observer stays on after the first `--observer` install because `/etc/heirloom/observer.enabled` is still there. Presence stays on after the first `--presence` install because `/etc/heirloom/presence.enabled` is still there. A dry-run never creates those files.

## Lab signals

Lab mode is owner-only and off unless `HEIRLOOM_LAB_MODE=1`.

- Every Twin, Clone, and Assist reply can take Useful / Not useful plus an optional note.
- Each turn stores route, latency, model, token counts, approvals created / approved / declined, and errors. Message text is not stored. The file is local JSONL under `/var/lib/heirloom/lab`.
- `/lab` in the web UI shows health, counts, and the latest markdown report.
- Approvals still gate send, post, delete, and spend. Lab mode does not bypass them.

## Commands

```bash
heirloom-box status
heirloom-box backup
heirloom-box report
heirloom-box observer status
heirloom-box observer pause
heirloom-box observer resume
heirloom-box observer digest
heirloom-box presence status
heirloom-box presence pause
heirloom-box presence resume
heirloom-box presence forget
sudo heirloom-box update-drivers
sudo bash box/install.sh --help
```

## What this environment did not prove

A cloud agent can shellcheck the scripts, unit-test provider selection, the lab fence, the Observer privacy filter, and Presence (debounce, enrollment purge, unknown faces, the heir fence, thresholds, pause), build the web app, dry-run the installer, and test the autoinstall serial guard. It cannot prove a real NVIDIA GPU, a flashed USB stick in the Twin Box, a Tailscale login, a real UVC capture card, a real webcam, a real face, or a vision model answering from GPU VRAM. QEMU coverage of the autoinstall ISO, when the run produced it, is recorded in the change that added `box/autoinstall/`.
