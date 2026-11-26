# Heirloom on one Windows PC (no Twin Box)

The one-click path for a buyer with just a Windows PC. Everything runs on this PC: the model,
memory search, hearing, voice, the database, and the web app. Nothing is set up to call a cloud
model. The Twin Box remains an optional premium appliance (always on, its own GPU, observer).

## What Setup does

`HeirloomUnboundSetup.exe` → task **Run Heirloom fully on this PC** → `Install-HeirloomLocal.ps1`:

| Step | What | Where |
|---|---|---|
| 1 | Hardware check (GPU, VRAM, RAM, free disk) and the model tier (`model_tiers.py`, same table as `ModelTiers.cs`) | `python -m local_box plan` |
| 2 | Python 3.12 via uv, then the API in its own venv (faster-whisper, CUDA wheels on NVIDIA) | `%LOCALAPPDATA%\HeirloomUnbound\venv` |
| 3 | Portable MongoDB 8.0, bound to 127.0.0.1 | `tools\mongodb`, `data\db` |
| 4 | Ollama: reused if already running, otherwise `OllamaSetup.exe /VERYSILENT` (per user) | |
| 5 | Tier model + `nomic-embed-text` (skipped if already pulled; disk is checked first) | |
| 6 | Chatterbox voice when the tier leaves VRAM for it (torch 2.6/cu124, or 2.7.1/cu128 on RTX 50xx) | `voice\`, 127.0.0.1:8010 |
| 7 | `data\heirloom.env`: local-only settings, all folders inside `data\`, secrets kept on re-runs, hand edits kept | |
| 8 | Owner sign-in (scrypt hash only), shortcuts, then `local_box check --chat` | |

Re-running Setup is safe: it updates the app and keeps data, secrets and the owner sign-in.
Ports shift automatically if 8001 or 27017 are taken. Everything listens on loopback only.

- **Start:** the *Heirloom* shortcut (`Start-Heirloom.ps1`) starts the database, voice and API
  and opens `http://127.0.0.1:8001/` (the API serves the web app; `HEIRLOOM_WEB_DIR`).
- **Stop:** `Stop-Heirloom.ps1` stops only processes inside the install folder. Ollama is left
  running because other apps may use it.
- **Change the owner password:** `Set-HeirloomOwner.ps1 -Email you@example.com`.
- **Desktop app:** First run fills in the local address (`LocalBox.FindUrl`), and a plain-http
  loopback address signs in without a certificate pin. Any other box still needs the pinned https.

## Model tiers

`SetupCore.TwinMindName` (it was `llama3.1`) now comes from `ModelTiers.Choose(Detect())`, the
C# copy of `backend/model_tiers.py`. `tests/test_local_box.py` fails if the two tables drift.

## Tested (BIGDEAL, RTX 5090, sandbox install in a separate folder, alt ports)

| Check | Result |
|---|---|
| Hardware plan | tier xl, gemma4:26b, ~30 GB needed of 195 GB free |
| `local_box check --chat` | api, web, web routes, ollama, model, embed, owner, chat: all true |
| Web app | `/` and `/life-story` served by the API |
| Owner login (`/api/auth/box-login`), cookie, `/api/auth/me` | pass |
| `/api/desktop/chat` | grounded reply in 1.0 s |
| Chatterbox `/speak.wav` | 4.1 s for one sentence |
| faster-whisper on that wav | heard it word for word, 2.5 s (CPU int8) |
| Re-run installer | idempotent, ~15 s |
| Listening sockets | 127.0.0.1 only (8010, 18101, 27181) |

Found and fixed by the live run: `fcntl` import on Windows, `/var/lib/heirloom` defaults,
`$PSScriptRoot` empty in PowerShell 5.1 parameter defaults, the BOM PowerShell adds to piped
text (owner password now passes through the environment), `pkg_resources` for librosa
(`setuptools<81`), Blackwell GPUs needing cu128 torch, and non-ASCII text in `.ps1` files.

## Not covered yet

- Code signing (SmartScreen warns on the unsigned Setup.exe).
- AMD/Intel GPUs run the CPU/small tiers; no ROCm/DirectML path.
- The Twin Box observer (screen/audio capture) is not part of the PC install.
