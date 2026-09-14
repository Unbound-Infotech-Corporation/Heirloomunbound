# Emergent handoff — Heirloom **0.5.1**

> **Owner shortcut:** open [`EMERGENT_PASTE_THIS.md`](EMERGENT_PASTE_THIS.md), copy the fenced block, paste into Emergent chat. Done.

**GitHub (already pushed):**  
https://github.com/Unbound-Infotech-Corporation/Heirloomunbound/tree/v0.5.1  
**Tag:** `v0.5.1` (use the tag — do not chase commit SHAs)  
**Tree zip:** https://github.com/Unbound-Infotech-Corporation/Heirloomunbound/archive/refs/tags/v0.5.1.zip

**Audience:** Emergent operators / agents promoting this GitHub tree to preview + production  
**Date:** 2026-09-14  
**Previous production stamp:** `0.5.0` (git `0dc1270`)  
**This release:** Same WinUI owner studio; stamp + main work since `v0.5.0` (four Unbound install sizes, Dedicated PC, Models Studio local voice)

---

## What you must do (checklist)

1. **Pull / sync this repo** onto the Emergent app from tag **`v0.5.1`** (or unpack the tag zip).
2. Confirm `backend/companion_desktop_data.py` is present (baked PySide zip). If you only copied loose files and that module is missing, run:
   ```bash
   cd backend && python build_desktop_data.py
   ```
3. Restart backend (`supervisorctl restart backend` or platform equivalent).
4. Smoke:
   - `GET /api/` → ok  
   - `GET /api/build` → `desktop_version: "0.5.1"`, features include `studio`, `first-run`, `vendor-coach`, `winui-native`
   - `GET /api/companion/winui` (authed) → `"version": "0.5.1"`
   - Web `/companion` copy mentions **0.5.1**
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
- **Assist** (`AssistantViewModel` + `PcToolkit`): copilot on this PC — never first-person as the owner.
- **Twin**: vault-grounded, likeness; cloud chat `mode=twin` strips `pc_control` / `screen_vision` / `terminal`. Heirs inherit Twin, not Assist.

---

## What changed since 0.5.0 (why this is 0.5.1)

From GitHub `main` after tag `v0.5.0` (do not invent beyond this tree):

- **Four Unbound install sizes** replace the old lite/full/max labels. First-run, Models Studio, companion wizard, and WinUI provision plan against those sizes.
- **Dedicated PC** role on the companion / first-run path so local voice can live on a selected machine.
- **Models Studio local voice:** Voicebox / Qwen3-TTS / LatentSync routing, support tickets with redaction, Voice and Terminal MDI windows with local probes.
- **Heirloom Unbound Setup** Inno sources (`desktop/installer/`) for the native Windows installer.
- Trust fences: heir writes stay off device-token rails; portal chat pins to the heir session; web Twin still strips PC tools.
- Owner Sit rail (Do vs Ask without a mode picker), Assist action receipts / Sit plan and Did chips, owner-only Memory Studio, standing Twin routines, First Gift letters, owner pairing prefs baked into Assist and Twin prompts.

Product rules from 0.5.0 are unchanged: WinUI is primary; PySide zip is fallback; Assist is the PC copilot; Twin is vault first-person.

---

## Version stamps (must all say 0.5.1 after sync)

| Location | Field |
| --- | --- |
| `backend/companion_desktop/heirloom/__init__.py` | `__version__` |
| `backend/companion_desktop_data.py` | baked `__init__.py` + `DESKTOP_BUILD` SHA |
| `backend/server.py` | `/api/build` fallback + features |
| `backend/routers/companion.py` | `GET /api/companion/winui` → `version` |
| `desktop/Heirloom/Heirloom.csproj` | `<Version>` |
| `desktop/Heirloom/Package.appxmanifest` | `Identity Version="0.5.1.0"` |
| `desktop/Heirloom/Services/AppHost.cs` | `Version` |
| `desktop/installer/HeirloomUnbound.iss` | `MyAppVersion` |
| Titlebar / settings (legacy + WinUI) | shows `0.5.1` + build id |

Legacy script auto-update still uses `COMPANION_SCRIPT_VERSION` in `routers/companion.py` (separate from app `0.5.1`). Only bump that when `_build_companion_script` changes.

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
# expect desktop_version 0.5.1
```

Manual: sign in → Companion → confirm bake text → (optional) re-download WinUI or legacy zip → Twin message → one companion `say` if a device is paired.

Full ops runbook: `DEPLOY.md`. Agent product rules: `AGENTS.md`.
