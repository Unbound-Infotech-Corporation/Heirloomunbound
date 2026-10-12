# Observer

Observer is the Twin Box watching the owner's HDMI picture and turning it into notes. It is off unless this machine was installed with `--observer`. Product builds do not set `HEIRLOOM_OBSERVER`.

The raw stream is not stored. The ring buffer lives in `/run/heirloom-observer` (tmpfs). Notes are text. Short highlight clips exist only when `OBSERVER_CLIPS=1`, and they expire.

## Wiring

The owner's Windows PC (the RTX 5090 machine) keeps its monitor. HDMI leaves that PC, goes through a splitter, and splits:

```text
owner PC HDMI
    │
    ▼
 splitter
    ├── HDMI ──► monitor
    └── HDMI ──► EVGA XR1 or XR1 Pro
                      │
                      USB
                      ▼
                 Twin Box (headless Ubuntu 24.04)
                 appears as /dev/video*
```

The capture card is a UVC device. `v4l2-ctl --list-devices` should show it after the USB cable is in. The daemon prefers a name containing `xr1`, `evga`, `uvc`, `usb video`, or `capture`, and it skips metadata nodes.

Supported cards are UVC devices that show up as `/dev/video*`. Internal Elgato 4K60 Pro cards are Windows-only. They do not enumerate as UVC on Linux, so this box cannot open them.

A replug is picked up two ways: the daemon re-scans `/sys/class/video4linux` every loop, and `box/observer/99-heirloom-observer.rules` asks systemd to start `heirloom-observer.service` when a video4linux device is added. The unit uses `Restart=on-failure`.

No signal (PC asleep, cable out, black frame) is logged as idle time and does not become a note full of empty frames. When the picture returns, the idle stretch is one observation.

## What it samples

| Knob | Default | Meaning |
|---|---|---|
| `OBSERVER_SAMPLE_FPS` | `2` | Gray thumbnails while the picture is calm. |
| `OBSERVER_BURST_FPS` | `8` | Sampling when the scene change is high (games, fast motion). |
| Analysis | 15 s calm, 4 s burst | OCR and the vision model. They do not run at the sample rate. |
| Resolution | 1080p, then 720p | `ffmpeg` / v4l2 MJPEG grab. The stored analysis frame is scaled to 640×360 in RAM and deleted. |
| `OBSERVER_OLLAMA_URL` | `http://127.0.0.1:11434` | Host Ollama. The daemon does not call a cloud vision API. |

Scene change is the fraction of gray pixels that differ from the previous thumbnail. At or above `0.35`, the sampler bursts.

## Reference machine

The lab Twin Box is an NVIDIA RTX 3090 (24 GB VRAM, `nvidia-smi` reports 24576 MiB) and 32 GB of system RAM. `--observer` tunes the pair for that card. Sizes below are the Ollama library card sizes rounded up to MiB, not a measurement taken on this machine.

| Role | Tag | Weights | License |
|---|---|---|---|
| Chat | `qwen2.5:14b` | 9216 MiB (about 9 GB) | Apache-2.0 |
| Vision | `qwen2.5vl:7b` | 6144 MiB (about 6 GB) | Apache-2.0 |
| Headroom | KV cache, the vision pass, CUDA | 4096 MiB (4 GB) | |
| Expected while both are resident | | **19456 MiB (about 19 GB)** | |
| Left on the 3090 | | about 5 GB | |

`qwen2.5:32b` is the chat default for a 24 GB card when Observer is off, and it is about 20 GB (20480 MiB). 20480 + 6144 + 4096 is 30720 MiB, which is more than 24576. That pair does not fit. The installer therefore switches the chat model to `qwen2.5:14b` when `--observer` is on and logs that the 32B tag was too big to sit beside vision.

Schedule, so a later override cannot fill the card:

- `OLLAMA_MAX_LOADED_MODELS=2` and `OLLAMA_KEEP_ALIVE=30m` on the Ollama container (it reads `/var/lib/heirloom/box.env`). The chat model stays warm for half an hour.
- Each vision request sends `keep_alive` of `45s` (`OBSERVER_VISION_KEEP_ALIVE`). A burst reuses the vision weights, then Ollama drops them.
- If the configured tags do not fit (for example chat forced back to `qwen2.5:32b`), the daemon lists `/api/ps` and unloads the chat model with `keep_alive: 0` before the vision call. The vision request then uses `keep_alive: 0`, so it does not stay loaded. The next chat loads the chat model again. That path is exclusive: one model on the GPU at a time.

System RAM stays mostly for Ubuntu, Docker, Mongo, and any Ollama spill. The capture ring is not a framebuffer:

| Knob | Reference value |
|---|---|
| `OBSERVER_RING_SLOTS` | `4` gray thumbnails (160×90). The cap is 8. |
| `OBSERVER_RAM_BUDGET_BYTES` | `67108864` (64 MiB) under `/run/heirloom-observer`. Values above 256 MiB are clamped. |
| Analysis frame | One 640×360 JPEG in that directory, deleted after the privacy check. |
| Highlight | Only when clips are on. Encoded in the same RAM directory, then moved or deleted. |

## Vision model

The installer writes the pair from `heirloom_observer_residency_for_vram_mib` / `observer_pair_for_vram_mib`, plus `OBSERVER_VRAM_MIB`. On the 3090 that is the table above. Smaller cards step down to the strongest Apache-2.0 pair that still fits with the 4 GB headroom (`qwen2.5:7b` + `qwen2.5vl:7b`, then 7B + `qwen2.5vl:3b`, then 3B + `qwen2.5vl:3b`, then 3B + `moondream`). If nothing fits together, Observer loads one model at a time. No GPU selects OCR.

A vision-only ladder remains in `vision_model_for_vram_mib` for callers that are not sharing the GPU with chat: under 6 GB `moondream`, under 12 GB `qwen2.5vl:3b`, otherwise `qwen2.5vl:7b`. The installer does not use that ladder when `--observer` is set.

Qwen2.5-VL 32B and Qwen3-VL are not pulled automatically. Set `OLLAMA_OBSERVER_MODEL` yourself if you want one of those, and only if the license on the weights you pull is one you can use. A tag that is not in the weight table is treated as too big to share the GPU, so the daemon unloads chat before it runs. Llama-based LLaVA is not selected: the Llama community license is not an unrestricted commercial license.

No GPU, or a driver that is not answering, selects OCR (Tesseract, English) plus the activity heuristics. PaddleOCR is not installed.

OCR and the model see a frame only after the privacy filter allows it.

## What becomes a note

Observations are grouped into sessions. Ten minutes of silence starts a new session. Idle rows close a session and are not sessions themselves.

Notes are timestamped, `source=observer`, and start as `pending` with a confidence:

- workflow — several distinct work titles in one session, written as steps
- habit — the same app repeated
- preference — a long focus streak
- decision style — a game session: risk, patience, exploration versus the objective, reaction to failure, retries
- vocabulary — phrasing attributed to the owner's own typing when the observation carries it

Games are named when the title or window matches a known game, and the decision summary is built from words in the allowed text (failure, retry, risk, patience, explore, objective). The box is not told a watch-list of apps. The classes above are how notes are shaped, not a list of things to hunt.

Accepted notes, and the owner's pending notes at confidence `0.75` or higher, are background in the Twin prompt. They sit under owner-recorded vault passages. If a reply relies on them, the source label is `from what I've watched`.

## Owner loop

Nightly, when Observer is on:

- `03:15` `heirloom-box report` embeds the digest in the lab report
- `03:20` `heirloom-box observer digest` writes `/var/lib/heirloom/observer/digests/observer-digest-YYYY-MM-DD.md`

`/lab` and `/observer` show **What I learned about you**. Each note has **That's me**, **Not me**, and **Never learn this**.

- That's me — the note stays and can enter the Twin prompt.
- Not me — the note is removed and a similar future note is suppressed.
- Never learn this — the note is removed and the same kind of topic stays suppressed.

Heirs do not get this page. `/api/observer/*` is 404 for an heir or a caller. The heir Twin may use notes the owner has accepted. It never receives pending notes, clips, or frames.

## Privacy

Before OCR text is stored and before Ollama is called, the frame is dropped when the text or the device name looks like:

- a password manager (1Password, Bitwarden, LastPass, KeePass, Dashlane, NordPass, RoboForm, Enpass)
- a password, sign-in, or master-password field (a line of code that assigns `password` is not a field)
- banking or payment (PayPal, Venmo, card, routing, IBAN, a bank name with an account context)
- a one-time code, 2FA, authenticator, or passcode
- someone else's private messages (Slack, Discord, WhatsApp, iMessage, Telegram, Teams, Messenger, and the other chat names in `observer_privacy.py`)

A drop stores a timestamp and a reason code (`password_manager`, `password_field`, `banking`, `otp`, `chat`). It does not store the OCR text. The model callback is not invoked.

Pause stops understanding:

- **That's a pause:** `/lab` and `/observer` (Pause / Resume), or `heirloom-box observer pause` and `heirloom-box observer resume`
- **Hotkey:** put the phrase `HEIRLOOM PAUSE` on screen (change it with `OBSERVER_HOTKEY_PHRASE`). That latches until resume.
- **Schedule:** `OBSERVER_QUIET_HOURS=23:00-07:00` (comma-separated spans, midnight wrap allowed). Quiet hours pause only inside the window. They do not latch.

Nothing in this path leaves the box. There is no cloud vision call and no clip download route.

## Clips and disk

`OBSERVER_CLIPS=0` by default. Set it to `1` to keep short highlights.

| Knob | Default |
|---|---|
| `OBSERVER_CLIP_SECONDS` | `8` |
| `OBSERVER_CLIP_MAX_MINUTES_PER_DAY` | `10` |
| `OBSERVER_CLIP_TTL_DAYS` | `7` |
| `OBSERVER_DISK_CAP_BYTES` | `536870912` (512 MiB) |

A highlight is encoded only after a frame passed the privacy filter, only while the scene is changing quickly, and only with no audio track. It is written under `/run` first. It moves into `/var/lib/heirloom/observer/clips/` after the day budget allows it. Expired clips are deleted. If the tree is still over the cap, the oldest clips go next. Notes are kept. Observation lines are trimmed only after clips are gone and the tree is still over the cap.

A screen that turns into a password page during those few seconds is not re-checked frame by frame. Leave clips off unless you want that tradeoff.

## Status

`heirloom-box status` includes an observer section: enabled, device, signal, fps, model, paused, notes today, disk used. `GET /api/health` includes the same facts under `observer`.

```bash
heirloom-box observer status
heirloom-box observer pause
heirloom-box observer resume
heirloom-box observer digest
```

## Install

```bash
sudo bash box/install.sh --observer
```

That installs `ffmpeg`, `v4l-utils`, and `tesseract-ocr`, writes `/etc/heirloom/observer.enabled`, enables `heirloom-observer.service`, and pulls the vision tag when VRAM selected one. A later `sudo bash box/install.sh` without the flag keeps Observer on while that marker file exists. A dry-run does not create the marker.

`--dry-run --observer` prints the plan and does not install packages, write the marker, or start the service.
