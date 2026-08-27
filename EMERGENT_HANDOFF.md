# Emergent handoff — Heirloom **0.5.0**

> **Owner shortcut:** open [`EMERGENT_PASTE_THIS.md`](EMERGENT_PASTE_THIS.md), copy the fenced block, paste into Emergent chat. Done.

**GitHub (already pushed):**  
https://github.com/Unbound-Infotech-Corporation/Heirloomunbound/tree/main  
**Commit:** `aa84a4c` · **Tag:** `v0.5.0`  
**Tree zip:** https://github.com/Unbound-Infotech-Corporation/Heirloomunbound/archive/refs/tags/v0.5.0.zip

**Audience:** Emergent operators / agents promoting this GitHub tree to preview + production  
**Date:** 2026-08-27  
**Previous production stamp:** `0.4.0` (legacy PySide first-run bake)  
**This release:** Native WinUI owner studio is the product; PySide zip stays as fallback only

---

## What you must do (checklist)

1. **Pull / sync this repo** onto the Emergent app (prefer tag `v0.5.0` / `main` tip `aa84a4c`).
2. Confirm `backend/companion_desktop_data.py` is present (baked PySide zip). If you only copied loose files and that module is missing, run:
   ```bash
   cd backend && python build_desktop_data.py
   ```
3. Restart backend (`supervisorctl restart backend` or platform equivalent).
4. Smoke:
   - `GET /api/` → ok  
   - `GET /api/build` → `desktop_version: "0.5.0"`, features include `studio`, `first-run`, `vendor-coach`, `winui-native`
   - `GET /api/companion/winui` (authed) → `"version": "0.5.0"`
   - Web `/companion` copy mentions **0.5.0**
5. **Promote preview → production** in the Emergent UI when smoke is green.
6. Website / download CTAs: point Windows owners at the **native** package path below, not only the old PySide zip.

---

## Product split (do not regress)

| Surface | Source of truth | Customer download |
| --- | --- | --- |
| **Owner Windows studio** | `desktop/Heirloom/` (WinUI 3) | `GET /api/companion/winui` + `GET /api/companion/winui-package` → `HeirloomWinUI.zip` |
| **Legacy fallback zip** | `backend/companion_desktop/` baked into `companion_desktop_data.py` | `GET /api/companion/desktop-package` → `HeirloomDesktop.zip` |
| **Web / heirs / marketing** | `frontend/` | Same Emergent host as today |

- WinUI stores the device token in **Windows Credential Locker** (Settings paste). It does **not** bake `config.py`.
- Overlaying `companion_desktop` onto an old install must keep that install’s baked `heirloom/config.py` (token + `BACKEND_URL`).
- Mixer volume = Heirloom WASAPI session, not system master (`desktop/Heirloom/Services/MixerSessionService.cs`).

---

## What changed since 0.4.0 (why this is 0.5.0)

### Native WinUI studio (primary)

- Full owner studio shell: dock groups, Sit → **Assist**, Twin group (Sitting / Portrait / Abilities / Skills / Avatar).
- **Assist** (`AssistantViewModel` + `PcToolkit`): copilot on this PC — never first-person as the owner.
- **Twin**: vault-grounded, likeness; cloud chat `mode=twin` strips `pc_control` / `screen_vision` / `terminal`.
- First-run: one **Get everything ready** button (Whisper, Ollama/llama3.1, talking-picture engine when disk + NVIDIA allow). No tokens / backend URL / vendor email / model SKUs in the overlay.
- Vendor coach is **optional** (Settings / Help → Getting started), never auto-started; no vendor DOM / captchas / screenshot key scraping.
- Studio poller (`cmd_id` results), cloned speak, heir lock, Library/Skills, autostart, sideload zip APIs.
- Chunked dock, named verbs (Ask / File / Save), DAW-style mute marks, hover lexicon.
- Publish locally: `desktop/Publish-Heirloom.ps1` → `desktop/dist/Heirloom/`. Use `desktop/dist/Heirloom-ready` if the live exe is locked.

### Backend / twin / phone

- Twin brain routing: local faster-whisper → local Ollama when provisioned; Claude / ElevenLabs remain fallbacks (`backend/model_router.py`).
- Desktop: `POST /api/desktop/brain-pack`, `POST /api/desktop/chat/local-complete`, `POST /api/desktop/speak`.
- Studio persistence: `GET/PUT /api/studio/audio|models|compute` + provision with `target_device_id`.
- Phone twin inbound / Retell / policy modules (`backend/routers/phone.py`, `phone_*.py`) — keep env vars for phone providers if already configured; no change required for pure web+desktop smoke.

### Web

- Adobe-style studio shell already on `/models` etc.; Companion page now advertises live bake version and warns when Emergent lags GitHub.

---

## Version stamps (must all say 0.5.0 after sync)

| Location | Field |
| --- | --- |
| `backend/companion_desktop/heirloom/__init__.py` | `__version__` |
| `backend/companion_desktop_data.py` | baked `__init__.py` + `DESKTOP_BUILD` SHA |
| `backend/server.py` | `/api/build` fallback + features |
| `backend/routers/companion.py` | `GET /api/companion/winui` → `version` |
| `desktop/Heirloom/Heirloom.csproj` | `<Version>` |
| `desktop/Heirloom/Package.appxmanifest` | `Identity Version="0.5.0.0"` |
| `desktop/Heirloom/Services/AppHost.cs` | `Version` |
| Titlebar / settings (legacy + WinUI) | shows `0.5.0` + build id |

Legacy script auto-update still uses `COMPANION_SCRIPT_VERSION` in `routers/companion.py` (separate from app `0.5.0`). Only bump that when `_build_companion_script` changes.

---

## Env / secrets (unchanged expectations)

Keep existing Emergent `.env` keys. Do **not** clear production secrets on promote.

Critical: `EMERGENT_LLM_KEY`, `MONGO_URL`, Stripe (`STRIPE_API_KEY`, `STRIPE_WEBHOOK_SECRET`, payment link vars), `ELEVENLABS_API_KEY`, `D_ID_API_KEY`, Resend / mail if used.

Phone (only if phone twin is live): Retell / Twilio-related vars already documented in phone modules — leave as-is if unset.

---

## Website copy / download UX

- Prefer: “Download Heirloom for Windows” → authenticated flow that hits **`/api/companion/winui-package`** (or documents paste-token + published build).
- Keep legacy “Desktop (classic)” → `/api/companion/desktop-package` for customers already on PySide until they migrate.
- Production host remains `voice-clone-hub-20.emergent.host` (or custom domain). Preview: `voice-clone-hub-20.preview.emergentagent.com`.

---

## Do not

- Do not delete `companion_desktop_data.py` or empty `companion_desktop/` — production zip bake depends on the generated module.
- Do not make Twin the PC agent; heirs inherit Twin, not Assist.
- Do not auto-launch vendor coach or drive third-party sign-up DOM.
- Do not debug in production — roll back from Emergent dashboard first (see `DEPLOY.md`).

---

## Post-deploy verification (5 minutes)

```text
curl https://<prod>/api/
curl https://<prod>/api/build
# expect desktop_version 0.5.0
```

Manual: sign in → Companion → confirm bake text → (optional) re-download WinUI or legacy zip → Twin message → one companion `say` if a device is paired.

Full ops runbook: `DEPLOY.md`. Agent product rules: `AGENTS.md`.
