# PASTE THIS INTO EMERGENT CHAT (whole block)

```
You are updating the live Heirloom app from GitHub. Do not invent features. Do not rewrite product code. Follow every step exactly.

GOAL
Ship Heirloom desktop stamp 0.5.0 from GitHub onto this Emergent app (preview first, then promote to production).

SOURCE OF TRUTH
- GitHub: https://github.com/Unbound-Infotech-Corporation/Heirloomunbound
- Sync EXACTLY: tag v0.5.0
- Zip if git sync is broken: https://github.com/Unbound-Infotech-Corporation/Heirloomunbound/archive/refs/tags/v0.5.0.zip
- Operator notes in-repo after sync: EMERGENT_HANDOFF.md and EMERGENT_PASTE_THIS.md

DO THIS NOW
1) Sync / pull / replace the Emergent workspace with GitHub tag v0.5.0. Prefer a full tree sync over cherry-picking files. If your Git tool fails, unpack the tag zip over the app tree.
2) Keep all existing production .env secrets. Do NOT clear EMERGENT_LLM_KEY, MONGO_URL, Stripe keys, ElevenLabs, D-ID, Resend, etc.
3) Confirm these files exist after sync:
   - EMERGENT_HANDOFF.md
   - EMERGENT_PASTE_THIS.md
   - backend/companion_desktop_data.py (non-empty)
   - backend/companion_desktop/heirloom/__init__.py containing __version__ = "0.5.0"
   - desktop/Heirloom/ (WinUI studio)
4) If companion_desktop_data.py is missing or empty, run: cd backend && python build_desktop_data.py
5) Restart backend (supervisorctl restart backend or platform equivalent). Restart frontend if needed.
6) Verify:
   - GET /api/ returns ok for digital-heirloom
   - GET /api/build → desktop_version MUST be "0.5.0"
   - features should include studio, first-run, vendor-coach, winui-native
7) Product rules you must NOT regress:
   - Primary Windows product is WinUI at desktop/Heirloom/
   - Customer download: /api/companion/winui-package (HeirloomWinUI.zip)
   - Legacy fallback only: /api/companion/desktop-package (HeirloomDesktop.zip)
   - WinUI pairs via pasted device token in Settings (Credential Locker). Do not bake config.py for WinUI.
   - Assist = PC copilot. Twin = vault-grounded first person. Twin never gets pc_control/screen_vision/terminal.
8) When preview smoke is green, promote/deploy preview to production in the Emergent UI.
9) Reply with: synced git commit SHA (must be the v0.5.0 tag tip), the full /api/build JSON, whether production promote succeeded, and any file that failed to sync.

If sync tools are broken, tell me the exact Emergent UI path to connect GitHub tag v0.5.0 and redeploy, then stop. Do not partially apply a half-update.
```

---

## After you paste (your 30-second check)

1. Open preview: https://voice-clone-hub-20.preview.emergentagent.com/api/build
2. Confirm `"desktop_version":"0.5.0"`
3. In Emergent UI → **Deploy / Promote** to production
4. Open prod: https://voice-clone-hub-20.emergent.host/api/build
5. Confirm `"desktop_version":"0.5.0"` again

If preview is still old after they “synced”, they did not pull tag **v0.5.0**. Paste the block again and demand the tag tip SHA in their reply.

## Links

- Paste file on GitHub: https://github.com/Unbound-Infotech-Corporation/Heirloomunbound/blob/v0.5.0/EMERGENT_PASTE_THIS.md
- Tag zip: https://github.com/Unbound-Infotech-Corporation/Heirloomunbound/archive/refs/tags/v0.5.0.zip
- Main: https://github.com/Unbound-Infotech-Corporation/Heirloomunbound/tree/main
