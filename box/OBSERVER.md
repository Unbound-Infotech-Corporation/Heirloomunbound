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

## Network screen

The HDMI splitter is optional. Heirloom Companion on the Windows PC (BIGDEAL) can send the primary display to the Twin Box over the home LAN. The post is `POST /api/observer/screen` with the same owner session and certificate pin as the microphone. The JPEG stays in `/run/heirloom-observer/screen` on the Twin Box until the daemon reads it.

| `OBSERVER_SOURCE` | Picture |
|---|---|
| `auto` | A companion frame that arrived within `OBSERVER_NETWORK_FRESH_S` (default 3 seconds). Otherwise `/dev/video0`. This is what `install.sh` writes. |
| `network` | Companion frames only. No capture card. |
| `capture` | The UVC card, same as before. The companion leaves the display on this PC. |

The companion captures the primary display at `OBSERVER_SAMPLE_FPS` (default 2), scales the long side to about 1920, and JPEG-encodes it. Screen is on until you turn it off in Companion Settings or the tray. While Observer is paused, the PC sends nothing and the box refuses the post.

A fresh network picture is the same pipeline as HDMI: the privacy filter, then `qwen2.5vl:7b` when that is the configured vision tag (`OLLAMA_OBSERVER_MODEL`), then the same note retention. `GET /api/health` reports `observer.source` (`network` or `capture`) and `observer.signal`. Signal is `ok` while network frames are fresh. `observer.mode` is the configured choice (`auto`, `network`, or `capture`).

Set the three keys in `box.env` or re-run `sudo bash box/install.sh --observer`. The API container and `heirloom-observer.service` both read that file. The spool directory is on the tmpfs mount both of them already share.

Supported cards are UVC devices that show up as `/dev/video*`. Internal Elgato 4K60 Pro cards are Windows-only. They do not enumerate as UVC on Linux, so this box cannot open them.

A replug is picked up two ways: the daemon re-scans `/sys/class/video4linux` every loop, and `box/observer/99-heirloom-observer.rules` asks systemd to start `heirloom-observer.service` when a video4linux device is added. The unit uses `Restart=on-failure`.

No signal (PC asleep, cable out, a flat frame, or a picture that does not change after the grab stalls) is logged as idle time and does not become a note full of empty frames. The daemon asks the card for 1280×720 YUYV. A negotiated 720×480 frame is no signal. When the picture returns, the idle stretch is one observation.

A still picture that repeats the latest sentence is not written again. A sequence that alternates, such as a death and then a retry, still counts.

## What it samples

| Knob | Default | Meaning |
|---|---|---|
| `OBSERVER_SAMPLE_FPS` | `2` | Gray thumbnails while the picture is calm. |
| `OBSERVER_BURST_FPS` | `8` | Sampling when the scene change is high (games, fast motion). |
| Analysis | 15 s calm, 4 s burst | OCR and the vision model. They do not run at the sample rate. |
| Resolution | 1280×720 YUYV | Requested explicitly. With no HDMI lock the XR1 Lite falls back to 720×480, and that size is no signal. The stored analysis frame is scaled to 640×360 in RAM and deleted. |
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

## VR gaze (owner, opt-in)

This is separate from the capture card. When the owner turns on eye tracking in the Room and a runtime actually provides gaze, the browser posts one summary to `POST /api/observer/vr-gaze`. The note is `source=vr_gaze`, kind `attention`, and lists areas (twin, seat, room, floor, elsewhere) with dwell time. Raw rays, origins, and pupil samples are not stored. Dwells under 400 ms are dropped.

A paused Observer writes nothing. If Observer is off, the route refuses and does not create a lab file. Heirs get 404. These notes stay out of the Twin prompt and out of heir-visible notes, including after "That's me".

PSVR2 on PC does not currently expose eye tracking (`XR_EXT_eye_gaze_interaction` is not available through Sony's adapter and SteamVR). The usual result is that nothing is sent. See `docs/VR.md`.

## Owner loop

Nightly, when Observer is on:

- `03:15` `heirloom-box report` embeds the digest in the lab report
- `03:20` `heirloom-box observer digest` writes `/var/lib/heirloom/observer/digests/observer-digest-YYYY-MM-DD.md`

`/lab` and `/observer` show **What I learned about you**. Each note has **That's me**, **Not me**, and **Never learn this**.

- That's me — the note stays and can enter the Twin prompt.
- Not me — the note is removed and a similar future note is suppressed.
- Never learn this — the note is removed and the same kind of topic stays suppressed.

Heirs do not get this page. `/api/observer/*` is 404 for an heir or a caller. The heir Twin may use notes the owner has accepted. It never receives pending notes, clips, or frames.

## Audio

Two streams, labeled by where they came from. They are never mixed into one transcript.

| Stream | First source | Fallback |
|---|---|---|
| System audio | ALSA capture whose name contains `XR1` (`arecord -l`) | The companion sends WASAPI loopback of the default speakers |
| Microphone | A Logitech C920 on the box, when it is plugged in | The companion sends the default WASAPI microphone |

A mic window that matches the system window (correlation and energy) is dropped as speaker bleed. Silence is skipped before Whisper. The box runs faster-whisper (`medium` on a 20 GB-class GPU, otherwise `small`) on CUDA, with the model's VAD as well as the energy check. The installer puts `nvidia-cublas-cu12` and `nvidia-cudnn-cu12` (9.x) in the observer venv and points `LD_LIBRARY_PATH` at them, because a CUDA 13 driver does not provide `libcublas.so.12`. A failed transcription stays `error` on `GET /api/health` until a later window succeeds.

The capture card's own name (for example `EVGA XR1 Lite Capture Box Video`) is not an app. Habit notes do not say "Often in" that device, and a habit is not written again on every analysis.

Notes are labeled `User said` for the microphone and `Watching/heard` for system audio. Both join the same observation timeline and the same note memory as the vision notes.

What is stored is the transcript. PCM lives in `/run/heirloom-observer/audio` only until the window is read, then it is deleted. Files older than 30 seconds are deleted too.

Each stream has its own switch:

- `/observer` checkboxes, `PUT /api/observer/audio`
- The companion tray menu and the companion Settings window

`GET /api/health` reports both under `observer.audio` (`source`, `status`, `device`). The companion shows those lines and sends a stream only when the box is waiting on that PC. The same health object reports the picture `source`, `mode`, and `signal` (`ok` when a companion screen frame is fresh).

The privacy filter and the shared pause switch apply to transcripts. A paused Observer discards audio instead of transcribing it. Pause also stops Assist from listening: no wake, no push-to-talk, and no computer action.

## Assist in the room

Transcripts stay context until the owner addresses the twin on the **microphone**. System audio cannot wake it and cannot say yes. The wake phrase defaults to `hey <twin name>` (Companion Settings, or `PUT /api/assist/live/settings`). `Ctrl+Shift+Space` on BIGDEAL arms the mic for 8 seconds.

A reply goes through `twin_runtime` with `local_only`, so the crisis check and the identity-honesty prompt run, and a missing local model does not fall through to the cloud. Chatterbox (`http://127.0.0.1:8010/speak.wav`) speaks it. The Companion shows a caption and plays the wav. Raw video is never stored. PCM is still deleted after the window is read.

Proactive asides are off until the owner turns them on. They are at most one every 10 minutes and three an hour, mute from the tray or by saying "mute" on the mic, and they stay quiet during a call or a fullscreen game.

Every computer action waits for a spoken yes, the tray **Yes, do that**, or **Yes** in the Companion **Twin Live** window. **No** leaves the action unrun. Reboot, shutdown, boot settings, format, wipe, `192.168.0.16`, `192.168.0.19`, and owner passwords are refused even after yes. Sends, purchases, and deletes need an explicit yes. Heirs and family get 404 on `/api/assist/live`. Posthumous memorial mode answers with no screen and no observer context. Each action leaves an Assist receipt.

`GET /api/assist/live/mic` is owner-only. It reads microphone lines already in `observations.jsonl` and returns the words. System audio is left out. While Observer is paused the response says `listening: false`. The route does not write a transcript, a frame, or audio. Twin Live is a Companion window (tray **Twin Live**). The Heirloom studio does not have to be open. The window shows those mic words as **You**, captions as **Twin**, the pending action with Yes and No, receipts, and Listening or Paused. Always on top is off until the owner checks it.

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
sudo bash box/install.sh --observer-audio
```

`--observer-audio` is the same switch as `--observer`. Both install `ffmpeg`, `v4l-utils`, `tesseract-ocr`, `alsa-utils`, a Python venv with faster-whisper plus the CUDA 12 cublas/cudnn wheels, `/etc/heirloom/observer.enabled`, and `heirloom-observer.service`, and pull the vision tag when VRAM selected one. Audio settings are written to `box.env` before the service is restarted, so a daemon that was already running picks them up. A later `sudo bash box/install.sh` without the flag keeps Observer on while that marker file exists. A dry-run does not create the marker.

On the Windows PC, OBS sends the main monitor to the EVGA HDMI input with desktop audio on that output. The companion tray is signed in. System audio and Microphone in the tray are the two switches. HDMI audio is used while `arecord -l` shows the XR1. The companion sends speaker loopback only when that device is absent, and it sends the microphone when the box has no C920.

`--dry-run --observer` prints the plan and does not install packages, write the marker, or start the service.
