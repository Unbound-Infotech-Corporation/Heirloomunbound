# Heirloom Twin Box

Headless Linux build of Heirloom Unbound for the owner's dedicated lab machine. The owner lives with it daily. The box keeps vault data, lab notes, and backups on local disk, and it records usefulness signals so the paid product can improve.

The Windows studio (`desktop/Heirloom/`) is not part of this box. Product version stays **0.5.1**. The FastAPI app version stays **0.3.0**.

## Hardware

A former game server is the intended machine. Ubuntu Server 24.04 LTS, no monitor after first setup.

| Piece | Need |
|---|---|
| CPU | 4 cores. More helps when Ollama is on CPU. |
| RAM | 16 GB. 32 GB is more comfortable once Mongo, Ollama, and the web stack are up. |
| Disk | 100 GB free under `/var/lib/heirloom` (models, Mongo, vault, backups). |
| GPU | Optional NVIDIA. No GPU means CPU Ollama. The installer skips the driver and the container toolkit when `lspci` and `nvidia-smi` see nothing. |
| Network | Ethernet on the LAN. SSH for a headless login. Ports 22, 80, and 443. |
| HDMI capture | Optional, lab only. See [OBSERVER.md](OBSERVER.md). UVC devices such as the EVGA XR1. Off unless you pass `--observer`. |

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

Do not install XTTS-v2, F5-TTS weights, or LivePortrait bundled face models. Optional speech on the box is Chatterbox (MIT), behind `--with-chatterbox`.

## Install from a fresh Ubuntu USB

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
```

| Flag | What it does |
|---|---|
| `--dry-run` | Writes the plan to the log and changes nothing. |
| `--dev-tools` | git, GitHub CLI, Node.js 22, Python 3.12, uv, Cursor CLI, Claude Code. |
| `--tailscale` | Installs Tailscale. You log in yourself. |
| `--with-chatterbox` | Optional Chatterbox TTS container on `127.0.0.1:8010`. |
| `--observer` | Lab only. Watches a UVC HDMI capture card and writes learned notes. Product installs leave this off. |

The script is idempotent. It uses `set -euo pipefail` and appends to `/var/log/heirloom-box-install.log`. A non-root dry-run that cannot write that path uses `$TMPDIR/heirloom-box-install.log`.

What a real run installs:

- Docker Engine and the Compose plugin, MongoDB 7 as a container (no host port), the API on `127.0.0.1:8001`, and the built web UI behind Caddy.
- Caddy on ports 80 and 443 with an internal CA (`tls internal`). HTTP redirects to HTTPS.
- Ollama on `127.0.0.1:11434`, then `ollama pull` of the VRAM model.
- NVIDIA driver `nvidia-driver-550-server` and the NVIDIA container toolkit only when a GPU is present. If the driver was just installed, reboot and run the installer again before GPU containers start.
- Hardened OpenSSH (public-key only, root login off) only when some `authorized_keys` file is non-empty. A fresh install without a key keeps password login so you are not locked out.
- `unattended-upgrades`.
- `ufw`: deny incoming, allow OpenSSH, `80/tcp`, and `443/tcp`.
- Nightly cron: `03:00` `heirloom-box backup` (Mongo archive + vault tarball, 14 copies), `03:15` `heirloom-box report` (markdown under `/var/lib/heirloom/lab-reports`, 30 files).
- With `--observer`: `ffmpeg`, `v4l-utils`, Tesseract, `heirloom-observer.service`, a udev rule for UVC replug, `HEIRLOOM_OBSERVER=1`, and a `03:20` digest. The marker `/etc/heirloom/observer.enabled` keeps Observer on when you later run the installer without the flag. Wiring, privacy rules, and the vision-model table are in [OBSERVER.md](OBSERVER.md).

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

That prints Compose services, GPU, disk for `/var/lib/heirloom`, the last backup, the last lab report, the Observer section (device, signal, fps, model, pause, notes today, disk), and `GET /api/health`. Health includes `observer` even when it is off.

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

Re-running is safe. It keeps the existing connector secret and rewrites the service env flags. Add `--dev-tools`, `--tailscale`, or `--with-chatterbox` again if you still want those. Observer stays on after the first `--observer` install because `/etc/heirloom/observer.enabled` is still there. A dry-run never creates that file.

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
sudo bash box/install.sh --help
```

## What this environment did not prove

A cloud agent can shellcheck the scripts, unit-test provider selection, the lab fence, and the Observer privacy filter, build the web app, and dry-run the installer. It cannot prove a real NVIDIA GPU, a bare-metal Ubuntu Server install from USB, a Tailscale login, a real UVC capture card, or a vision model answering from GPU VRAM.
