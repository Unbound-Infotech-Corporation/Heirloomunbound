# Heirloom — Digital AI Twin (PRD)

## Original Problem Statement
> "I want to build an app that can make a AI Twin of me. One that i can have running in the background and just speak to when i enter the room. There should be a way to share my facebook and other social media pages with it so it can build a personality profile of me and a way for me to let it listen to me when i speak on Discord so that it gets to know more details about my personality.. i have a beefy computer with a 5090 so it shouldnt be too much of a stress on my hardware."

Follow-up (deciding intent):
> "the end goal is to use the AI twin and develop a massive amount of information on my personality so that when i die, the ai twin can be used by my son or relatives to have something of myself to still speak to when they want."

Follow-up (broader ambition):
> "i would like to be able to have the Ai twin actually use the computer that will be dedicated for it. Like i want to connect it to appliances in the house that have bluetooth or network connectivity and be able to tell the ai twin to complete tasks and actually have it do it."

## Core requirements
- Private archive of one person's voice, memories, beliefs, advice, stories — built slowly over years.
- A digital twin that responds in the user's voice, grounded in the archive, for the user's heirs to speak with after they pass.
- Capture surfaces: an AI interviewer, voice journal, social/text import, structured archive CRUD.
- Skills system: webhook-based commands the twin can invoke (Home Assistant, IFTTT, local scripts).
- Heirs: trusted contacts who one day inherit access.

## User personas
1. **Owner / archivist** — primary user, builds and maintains their archive over time.
2. **Heir** (future) — son / family / partner who eventually sits with the twin.

## Tech architecture (v1, what shipped)
- **Frontend**: React 19 + react-router 7 + Tailwind + shadcn/ui + framer-motion (Cormorant Garamond serif + Manrope sans + IBM Plex Mono).
- **Backend**: FastAPI 0.110 + Motor (Mongo) with a clean `/api/*` router structure.
- **LLM**: Claude Sonnet 4.6 via `emergentintegrations` (`EMERGENT_LLM_KEY`) — streaming SSE for both interviewer and twin.
- **Voice**: OpenAI Whisper STT + OpenAI TTS (voice=onyx) via the same key.
- **Auth**: Emergent-managed Google Auth → `/api/auth/session` + httpOnly `session_token` cookie (7-day expiry).
- **Storage**: MongoDB (`test_database`) — collections: users, user_sessions, entries, conversations, imports, skills, heirs.

## What's been implemented (Feb 25, 2026)
- ✅ Landing page + Google login + Auth callback (Emergent Auth playbook followed verbatim)
- ✅ Sidebar app shell (11 nav routes)
- ✅ Dashboard with stats, completeness % (non-linear heuristic), suggested next topics
- ✅ Archive CRUD (memory / story / value / advice / quote / chapter / voice / import)
- ✅ AI Interviewer with streaming Claude responses + seed questions + save-turn-as-entry
- ✅ Voice journal: MediaRecorder → Whisper STT → archive entry
- ✅ Talk-to-Twin chat: streaming Claude, grounded in archive + skills, optional TTS playback (falls back to OpenAI TTS if no voice clone)
- ✅ Social/text import with Claude-powered extraction into structured entries
- ✅ Skills (webhooks): create / list / edit / invoke / delete, with live test invocation
- ✅ Heirs management
- ✅ Settings page with ElevenLabs voice config + clone-your-own-voice
- ✅ Multi-user isolation verified

### Phase 2 — Feb 25, 2026
- ✅ **Photos**: Emergent object storage integration, upload with caption + taken_at, blob-fetch with Bearer/?auth query, soft-delete
- ✅ **ElevenLabs voice clone**: per-user API key override + app default fallback, list voices, set voice, Instant Voice Clone from samples, TTS via cloned voice. Twin chat falls back to OpenAI TTS automatically.
- ✅ **Local PC Companion v1**: device-token auth, command queue (shell / open_url / open_app / say), pull/poll architecture, voice passthrough (companion uploads audio → Whisper → Twin → reply + skill invocations), downloadable Python script with token + backend URL baked in, device revocation.

### Phase 3 — Feb 26, 2026 (this update)
- ✅ **Windows installer experience**: New `/api/companion/windows-package` returns a `.zip` containing `Heirloom.bat` (one-click launcher that installs deps + runs the script — no terminal needed), `Build-Exe.bat` (PyInstaller one-shot to produce a standalone `HeirloomCompanion.exe`), `heirloom_companion.py` (with system-tray icon support via pystray that degrades gracefully if missing), and `README.txt`. The Companion page now shows two download buttons: Windows package (primary) and `.py` only (Mac/Linux).
- ✅ **Wake-word mode** (push-to-talk OR "Hey Twin"): companion supports `--wake-word` / `--ptt` flags + `HEIRLOOM_WAKE_WORD` env var, using `openwakeword` (falls back to PTT automatically if not installed).
- ✅ **Sealed Letters**: full CRUD at `/api/letters` with three triggers — `on_release`, `on_date`, `on_age`. Letters can be sealed (locked from edits) and unsealed before delivery. Cannot be deleted after delivery.
- ✅ **Heir Release workflow**: extended Heirs with `release_on` date trigger and `inactivity_days` trigger. Owner endpoints: `/heirs/check-in` resets inactivity clock, `/heirs/check-releases` sweeps + mints tokens, `/heirs/<id>/release-now` manual override, `/heirs/<id>/revoke-release`, `/heirs/<id>/release-link`. Release tokens are never exposed in the list endpoint.
- ✅ **Public Heir Portal** at `/heir/<token>` (no auth, just the token): standalone page (no AppLayout) with four tabs — Welcome (heir.note + counts), Letters (only unlocked + auto-marks delivered on first read), Archive (read-only browse), Talk to them (real Claude chat grounded in owner's archive). Auto-rejects invalid/revoked tokens with a friendly error screen.

### Phase 4 — Feb 26, 2026 (research-driven feature pack)
Researched competitor matrix (HereAfter AI, Eternos, Replika 2026, Personal AI, StoryFile, Project December) and closed five real gaps:
- ✅ **Structured Personality Profile** (`/personality` page) — Claude auto-extracts Big Five (OCEAN with per-trait reasons), top values, voice tone description + signature phrases, life themes, key relationships, and a 3-4 sentence portrait summary. Cached for 7 days or until archive entry count changes. Manual refresh button. Closes the "what does my twin know about me?" gap that all competitors expose.
- ✅ **Proactive Daily Nudges** (`/api/nudges/today` + Today dashboard widget) — Claude generates a personal, archive-grounded nudge each UTC day: title, body, action_prompt. Idempotent per (user_id, date). User can act on it (deep-links to /interviewer pre-filled) or dismiss. History endpoint preserves them. Replika 2026 parity.
- ✅ **Ask-the-Archive Q&A** (`/api/archive/ask` + Library Ask toggle) — StoryFile-style cited answers. Keyword-scored retrieval over up to 400 entries, top 12 fed to Claude, returns answer + citation cards with snippets.
- ✅ **Safe-Topic Fence** (Settings → safe-topic-fence) — owner adds topics to politely decline. Applied to `_build_twin_system` so both `/twin/chat` AND the public heir portal respect the fence.
- ✅ **TTS language preference** scaffold (`/api/auth/me/preferences` accepts `tts_language`) — wiring ready for ElevenLabs Multilingual v2 selector.

### Phase 5 — Feb 26, 2026 (long-term memory + music control)
- ✅ **Long-term memory architecture** (`routers/memory.py`): identity facts (stable claims auto-extracted from the archive via Claude, cached, refresh when archive grows by 5+ entries) AND episodic summaries (twin auto-summarises a conversation after 12+ messages and stores it). Both are injected into the twin's system prompt BEFORE the per-turn archive excerpts — the twin no longer dumps the whole archive each turn.
- ✅ **What I Hold Onto** UI on `/personality` — each fact is removable (X button), instantly stops appearing in the twin's prompt. Closes the Vellum/OpenClaw/Replika-2026 memory gap.
- ✅ **Music control via the twin**: `routers/music.py` with 9 deep-link providers (YouTube Music, YouTube, Spotify, Apple Music, Amazon Music, Tidal, Deezer, Pandora, SoundCloud) + deterministic intent detection (`play X`, `put on X`, `queue up X`, `play song X`, `play music video of X`) that short-circuits before the LLM. When triggered, queues an `open_url` command on the user's active companion PC so playback opens in their browser/app. Twin replies with an inline music chip rendered on the chat page. User picks default provider in Settings.

### Phase 6 — Feb 26, 2026 (competitor-feature pack: multilingual + brand + personas)
Researched Zoice, Gemelo, Synthesia, Veed.io, Kapwing. Shipped 3 features that strengthen Heirloom WITHOUT pivoting into Synthesia-style commercial content (which would dilute the legacy/companion moat):
- ✅ **Multilingual cloned voice** (Settings → Spoken language) — wired ElevenLabs Multilingual v2 `language_code` parameter; user picks default in 21-language dropdown, and `/voice-clone/tts` accepts per-request `language` override. The cloned voice now speaks any of those languages while preserving timbre.
- ✅ **Brand Kit** (Settings → Brand kit) — `brand_name`, `brand_tagline`, `brand_signoff` fields on the user; injected into the twin's system prompt as a "BRAND VOICE" section so all replies stay consistent.
- ✅ **Personas** (`routers/personas.py` + Settings → Personas) — switchable twin modes ("Family", "Professional", "Customer Support"). Each persona contributes a system_addendum + extra_safe_topics that compose on top of the base prompt. At most one persona active per user; default = none = full archive.

### Phase 7 — Feb 27, 2026 (D-ID talking-head avatar)
- ✅ **Talking-head video avatar** (`routers/avatar.py` + `/api/avatar/*`) — D-ID API integration with async create + poll architecture. `POST /api/avatar/talk` returns a `talk_id` immediately (no blocking on render); `GET /api/avatar/talks/{id}` polls D-ID until ready. Twin chat page shows a "Play as video" button on each assistant message → loading indicator → inline `<video>` player with the rendered .mp4. Voice provider is the user's ElevenLabs cloned voice when available (drops to Microsoft Jenny otherwise). Source photo configured in Settings via public https URL (D-ID requires public-fetchable source).
- ✅ Frontend polling: 60 attempts × 2s = 120s cap, resilient to transient poll errors.

### Phase 28 — Feb, 2026 (Phase 2: Activity Log + Photo→Story)
- ✅ **Companion Activity Log** (2a): GET `/api/companion/activity` — a privacy-redacted feed of every action the twin took on the PC (type_text/clipboard content is redacted to a length/label). Kill switch POST `/api/companion/activity/{cmd_id}/cancel` (409 if finished, 404 if missing); `/companion/result` no longer resurrects a cancelled command. New polished activity section on `/companion` with icons, status badges, relative time, and a "Stop" button. Replaced the old raw-JSON command history.
- ✅ **Photo → Story** (2d): new `photo_story.py` router — upload a photo → Claude vision describes it + asks 3 tailored questions → answers composed into a first-person memory filed in the archive (`db.entries`, type=story, source=photo_story). New `/photo-story` page (drag/drop → questions → story) + nav link. Image stored/served privately per photo_story_id.
- ℹ️ **Time-Capsule Letters** (2g): already existed as **Sealed Letters** (`letters.py` — deliver on_date / on_age / on_release to heirs). Not rebuilt.
- ✅ Tested: iteration_27.json — 5/5 backend pytest + full frontend E2E for both features. 100%.

### Phase 27 — Feb, 2026 (Tester mode — free access for invited testers)
- ✅ **Tester mode** (`lib/tester.js`): browser-local flag `heirloom_tester`. New public `/test` route (`TesterEntry.jsx`) sets the flag and invites Google sign-in — full free access, no payment.
- ✅ **Buy CTAs gated** for testers only (real sales funnel untouched for normal visitors): Landing nav Buy link hidden; `/buy` shows a free "No payment needed" panel instead of Stripe; TwinLive footer "$79, lifetime" link hidden.
- ✅ Confirmed there is NO functional paywall anywhere — `/auth/session` accepts any Google sign-in (no allowlist/purchase check), no feature route gates on payment, companion download only needs login. `$79` is purely marketing.
- ✅ Tested: iteration_26.json — 6/6 frontend checks pass, no hook-order/console errors.
- 📌 **Stripe (owner's live key) setup** — the app uses `emergentintegrations StripeCheckout` (create + get_checkout_status) + webhook `/api/webhook/stripe`. A standard secret key works; for a restricted key: Checkout Sessions=Write, Customers=Write, Products/Prices=Read, Payment Links=Read, PaymentIntents/Charges=Read, rest None. Webhook events: checkout.session.completed, charge.refunded, charge.dispute.created, charge.dispute.funds_withdrawn. Env: STRIPE_API_KEY, STRIPE_WEBHOOK_SECRET, STRIPE_PAYMENT_LINK_URL, STRIPE_PAYMENT_LINK_ID.
- ⚠️ Deployment: production build previously failed — likely `litellm` pinned to a URL wheel in requirements.txt. Not yet fixed (preview link works for testing).

### Phase 26 — Feb, 2026 (Abilities framework — Heirloom becomes a platform)
Phase 1 of the "go big" build. Introduced **Abilities**: modular, togglable capabilities the owner switches on for their twin, each with browser-style permission grants. Only enabled abilities inject their tools into the twin, keeping the model lean.
- ✅ **Framework** (`abilities.py`): catalog of 6 first-party abilities + `user_abilities` state collection; `enabled_tool_names`, `build_abilities_prompt`, `set_state`. The 4 memory tools (search_archive/save_memory/set_reminder/list_recent_memories) are always-on CORE, not abilities.
- ✅ **Abilities**: Web & Weather, Music, Smart Home & Skills, PC Control, Screen Vision (all on by default), Terminal Access (off by default — most powerful). Migrated existing capabilities into this rail.
- ✅ **API** (`routers/abilities.py`): GET /api/abilities (catalog + per-user state + companion_connected), POST /{id}/enable (validates all required permissions granted, else 400), POST /{id}/disable.
- ✅ **Twin gating** (`twin.py`): tool schemas filtered to enabled abilities; music + auto-skill short-circuits gated on their abilities; system prompt's capability section built dynamically from enabled abilities.
- ✅ **UI** (`Abilities.jsx` + nav): cards grouped by category with a permission-grant dialog on enable, one-tap disable. New "Abilities" sidebar link.
- ✅ Tested: iteration_25.json — 8/8 backend pytest (`test_iteration25_abilities.py`, gating + prompt), toggle/permission/404/400 API, twin SSE gating, frontend page + dialog. 100%.

### Phase 25 — Feb, 2026 (Twin can use your computer — 11 PC-control tools)
Big usefulness upgrade: the Twin (Claude) can now DO things on the user's connected companion PC via function-calling. Tools queue commands to the PC (like music's open_url) and, when useful, wait for the result to return. Tool registry grew 8 → 19.
- ✅ **New tools** (`twin_tools.py`): `open_on_pc` (app/website), `control_media`, `set_volume`, `power_action` (lock/sleep/shutdown/restart), `notify_on_pc` (desktop toast), `type_text`, `clipboard` (get/set), `see_screen` (screenshot + Claude vision), `system_status` (CPU/RAM/GPU incl. NVIDIA/disk/battery), `run_command` (shell), `find_file`.
- ✅ **Safety**: destructive actions (shutdown/restart + run_command) are gated behind `confirmed=true` — the Twin must explain and get an explicit yes first, then call again. Lock/sleep run immediately. Device-awake check (120s heartbeat window) → friendly "open your desktop app" note when offline.
- ✅ **see_screen vision**: new `POST /companion/screenshot` (device-auth) stores a downscaled JPEG (base64) keyed by cmd_id; the tool runs Claude vision (ImageContent + claude-sonnet-4-6 via Emergent key) then deletes the image (never retained).
- ✅ **Two runtimes upgraded**: (a) the self-updating single-file companion script (`COMPANION_TEMPLATE` in companion.py, version → 2026.02.28.1) — auto-ships to the .bat/.zip/.py downloads; (b) NEW `companion_desktop/heirloom/commands.py` `CommandPoller` QThread wired into the Elite PySide6 GUI (`main_window.py`), then rebaked via `build_desktop_data.py`. Installer now also pip-installs `psutil` + `mss`.
- ✅ **UI**: `Twin.jsx` TOOL_META chips for all 11 new tools.
- ✅ Tested: iteration_24.json — pytest `test_iteration24_pc_tools.py` (full queue→execute→result round-trip incl. live see_screen vision) PASS; /companion/screenshot endpoint PASS (200 + doc created, 401 unauthorized); frontend loads clean. 100% backend + frontend.

### Phase 24 — Feb, 2026 (heuristic refinement + conversation persistence + Avatar Studio fixes)
- ✅ **search_archive heuristic refined** (`routers/twin.py` `_build_twin_system`) — the twin no longer calls `search_archive` for greetings, small talk, or opinion questions ("what do you think about life?" = 0 tool calls); it still fires ONE focused call for owner-past factual questions ("where did you grow up"). Verified live.
- ✅ **/twin conversation persistence** — `Twin.jsx` stores `twin_conv_id` in localStorage and passes it to `POST /twin/start` on mount, restoring the full feed (incl. persisted `tool_trace` chips) across reloads. New header button `twin-new-conversation` starts a fresh conversation.
- ✅ **Avatar Studio beautify FIXED** — fal.ai model `fal-ai/gfpgan` does not exist; switched to `fal-ai/codeformer` (fidelity=0.7). Changed fal error HTTPExceptions 502→400 so error details pass through Cloudflare (502s were swallowed into an HTML error page). NOTE: user's fal.ai account balance is currently EXHAUSTED — enhance returns a clean 400 with the balance message until topped up at fal.ai/dashboard/billing.
- ✅ **Avatar Studio drag & drop** — tiles now accept click-or-drop uploads (`avatar-dropzone-<angle>`), with hover highlight.
- ✅ Tested: iteration_23.json — 9/9 backend pytest PASS, all frontend flows PASS (reload-restore, new conversation, upload → Use as twin → Active, beautify error toast).

### Phase 20 — Feb 27, 2026 (Stripe checkout product image)
- ✅ **Composed `public/stripe-checkout-image.jpg`** — 1024×1024 square, 228KB JPG. Layout: dark library bookshelf+chandelier bg with strong vignette, cyan Unbound "U" centered, "AN UNBOUND INFOTECH PRODUCT" accent overline, serif "Heirloom" wordmark, "a continuation of you" tagline, and a gold "$79 · LIFETIME · ONE-TIME" pill at the bottom. Scales gracefully down to Stripe's ~150×150 sidebar display.
- ✅ Compose script saved at `/app/frontend/scripts/build_stripe_image.py` for future re-runs / tweaks.
- ✅ Lives at: `https://voice-clone-hub-20.preview.emergentagent.com/stripe-checkout-image.jpg` (preview) — operator uploads it to Stripe Dashboard once.

### Phase 19 — Feb 27, 2026 (Stripe webhook hardening for production)
Three real production gaps closed:

- ✅ **Event-level idempotency** (`stripe_events` collection with unique-by-event_id index). Stripe retries the same webhook event many times across hours — every retry is now a fast 200 with `{duplicate: true}` instead of re-running provisioning. Closes a real risk of double-emails / double-account-creates under network blips.
- ✅ **Refund + dispute handling** — listening to `charge.refunded`, `charge.dispute.created`, `charge.dispute.funds_withdrawn`. On any of these: sets `users.account_status = "refunded"`, sets `refunded_at`, revokes EVERY companion device (`revoked: true`, `revoked_reason: "refunded"`), deletes active sessions. **Archive is preserved** in case the refund was a mistake — restorable by one `$unset` on `account_status`.
- ✅ **Companion poll honors the revocation**: refunded accounts get HTTP 403 `account_inactive` instead of commands — the local PC quietly stops working without crashing.
- ✅ **Dashboard-setup helper**: `GET /api/billing/webhook-info` returns the exact URL + event list to paste into the Stripe Dashboard. No more guessing.
- ✅ **`DEPLOY.md` Stripe production-setup section** added — 4 numbered steps the operator does in the Stripe Dashboard, plus an explanation of the refund/dispute behaviour and how to restore an account if needed.
- ✅ New `stripe_events.event_id` unique index. Audit script + 10/10 isolation fuzz tests still GREEN.

What's **explicitly NOT done** (needs dashboard work first): Stripe Tax automatic-tax in checkout (toggle in dashboard, then one line in `billing.py`). Live-key swap (needs you to activate live mode in your Stripe account).

### Phase 18 — Feb 27, 2026 (GitHub OAuth)
Second OAuth provider — slotted into the existing scaffold in ~80 lines of new code:

- ✅ `/api/oauth/github/connect` + `/api/oauth/github/callback` — Authorization Code flow with state-token CSRF guard, scopes `read:user user:email`. GitHub tokens are non-expiring by default, so no refresh dance — we store with a 5-year expiry to satisfy the unified token-expiry contract.
- ✅ **Auto-imported personality signals on first connect**:
  - Pulls user's `/user/repos?sort=updated&affiliation=owner` — most recent 15 repos
  - Aggregates top 5 languages by repo count
  - Writes one archive entry titled "What I'm building (from GitHub)" with: bio (if set), public_repos/followers count, top languages, recent 6 repos with one-line descriptions
  - Sets `primary_languages` long-term identity fact
- ✅ `connections` endpoint now returns BOTH providers. Frontend's connected-accounts UI is fully generic — provider-agnostic `connectProvider(slug)` and `useEffect` callback handler now iterate over `["spotify", "github"]` for the success/error toast.
- ✅ Re-verified: static audit GREEN, 10/10 isolation fuzz tests still pass.

### Phase 17 — Feb 27, 2026 (OAuth account linking — Spotify)
First "Connect your account" integration; pattern is provider-agnostic and reusable for future providers (Google, GitHub, YouTube).

- ✅ **`routers/oauth.py`** — provider-agnostic OAuth router. Endpoints: `GET /api/oauth/connections` (lists all providers + per-user connection state), `GET /api/oauth/{provider}/connect` (returns authorize URL), `GET /api/oauth/{provider}/callback` (exchanges code → tokens → seeds personality signals → redirects to `/settings?{provider}=connected`), `DELETE /api/oauth/{provider}` (disconnect).
- ✅ **Spotify wired end-to-end**: registered app credentials in env, Authorization Code flow with state-token CSRF guard, full scope set (`user-read-recently-played user-top-read user-library-read playlist-read-private user-read-playback-state user-modify-playback-state`), auto-refresh helper (`get_fresh_spotify_token`) that handles token expiry transparently for downstream callers (music.py etc).
- ✅ **Auto-seeded personality signal on first connect**: pulls user's top 10 artists, top 10 tracks, recent 20 plays, and aggregated top 6 genres, then writes ONE summary archive entry titled "What I'm listening to (from Spotify)" + sets a long-term `musical_taste` identity fact. Customer's Twin instantly knows their musical taste with zero typing.
- ✅ **`settings-oauth-section`** UI — provider cards with status, profile name, Connect/Disconnect buttons. Each card auto-greys when not configured server-side; clean toast feedback on redirect-back.
- ✅ **Isolation re-verified post-change**: static audit script GREEN (every Mongo read still user-scoped, oauth_connections + oauth_states properly filter); 10/10 fuzz tests still pass.

Future providers slot in as branches under the existing flow — Google Drive / GitHub / YouTube each ~30–60 min of provider-specific code once their respective developer-console apps are registered.

### Phase 16 — Feb 27, 2026 (user-isolation hardening)
Anchored on the question *"will Heirloom respond to everyone with Logan as their child?"* — a categorical "no" needed audit-grade proof.

**1. Static audit (`/app/backend/scripts/audit_user_filters.py`)**
Walks every router file and flags any `db.X.find/find_one/update_one/delete_one/count_documents` whose first-arg filter dict doesn't mention `user_id`. Found **21 latent risk patterns** (every one was technically safe because of a prior user-scoped read, but the pattern was fragile — a future refactor could silently break isolation). All 21 fixed in this round:
- `letters.py` — 6 sites: every update/find/delete now includes `user_id` in the filter
- `twin.py` — 3 sites: conversation update_one now filters by user_id
- `interviewer.py`, `memory.py`, `companion.py` — conversation/reminder updates now user-scoped
- `personas.py`, `reminders.py`, `skills.py` — follow-up `find_one`s after update now user-scoped
- `sources.py` — both source updates now user-scoped
- `avatar.py` — D-ID talk update now user-scoped
- Two genuine false positives (variable-passed filters, token-authenticated heir-portal) explicitly allowlisted with rationale
Re-running the script now reports: *"OK — every Mongo read in /app/backend filters by user_id (or is in the allowlist)."* CI-grade: exit code 1 if any new query forgets the filter.

**2. End-to-end fuzz test (`/app/backend/tests/test_user_isolation_fuzz.py`)**
Seeds **5 fake users** with deeply distinctive markers (made-up names like *Olwyn Rasmussen-Quill*, child names *Pinkerley/Tessaroon/Quintabel/Mosswick/Wyndham*, made-up cities, hobbies, fears, comfort foods). Then runs **10 isolation tests** at three layers:
- *Data layer*: direct DB query returns 6 entries for each user, never another user's content.
- *Context-builder layer*: `_archive_blob()` — the exact string passed to Claude — contains only the requesting user's markers, never another's.
- *HTTP layer*: `/api/archive`, `/api/archive?q=<other_user_marker>`, `/api/memory/facts`, `/api/heirs`, `/api/auth/me` all return only the session-owner's data.
- *Attack-surface*: PATCH/DELETE another user's entry by guessed id → 404. Release another user's heir → 404. Each test asserts the EXACT marker that would have leaked is absent — so if a future bug ever exposes "Pinkerley" to the wrong user, the test will print *which* marker leaked, in *which* endpoint, for *which* user.

**Result: 10/10 fuzz tests PASS in 24 seconds. Audit script: GREEN. Zero leaks at any layer.**

The product-level promise — *your Logan stays your Logan; nobody else's Twin will ever know* — now has a CI test that proves it on every code change.

### Phase 15 — Feb 27, 2026 (Resend transactional email)
The last operational blocker to selling. Without this, paying customers complete Stripe checkout and never receive their magic link.

- ✅ **`email_service.py`** — async wrapper around the Resend Python SDK using `asyncio.to_thread` so FastAPI never blocks. Two production templates:
  - `send_magic_link_email(to, name, login_url, download_url, backend_url)` — sent after Stripe checkout, includes signin link + Windows download
  - `send_heir_release_email(to, heir_name, owner_name, portal_url)` — sent when an heir is released
- ✅ Both templates use inline-CSS + table-based dark-library aesthetic that renders consistently across Gmail, Outlook, Apple Mail, and mobile clients.
- ✅ **Wired into `_provision_after_payment`** in `billing.py` — fires the welcome email immediately after Stripe webhook completion. Non-blocking; if Resend is down, the user still sees the in-page magic link on `/buy/success`.
- ✅ **Wired into `_do_release`** in `heirs.py` — fires the heir-release email both for manual `release-now` and automatic `check-releases` triggers.
- ✅ `POST /api/email/test` + `GET /api/email/status` — owner-only endpoints. Settings page renders a `[data-testid=settings-email-section]` block showing connection state, sender, test-mode warning (when using `onboarding@resend.dev`), and a "Send a test welcome email" button.
- ✅ **Live verified end-to-end**: real Resend send to the account-owner email returned id `689a8291…` (welcome) and `e544e41e…` (heir release). Quota usage tracked: 8 of 10 daily remaining on test-mode shared sender.

**To unlock real customer email**: Verify a domain at resend.com/domains, then change `SENDER_EMAIL` in `backend/.env` from `onboarding@resend.dev` to e.g. `noreply@heirloom.app`. While in test-mode, only the account-owner inbox receives emails.

### Phase 14 — Feb 27, 2026 (pre-sale hardening + mobile sweep)
This phase makes Heirloom legally and operationally ready to charge real customers, and usable on a phone.

**Legal & trust pages**
- ✅ `/privacy`, `/terms`, `/refunds`, `/support` — full markup-styled pages with unique `<title>` and `<meta description>` via `usePageMeta`. Each page has the same dark-library aesthetic and a "back to Heirloom" link.
- ✅ **Site-wide footer** (`components/SiteFooter.jsx`) appears on every authenticated route + Landing — links to Privacy, Terms, Refunds, Support, and `mailto:support@heirloom.app`.

**Account & data ownership**
- ✅ `DELETE /api/auth/me?confirm=DELETE` — hard-deletes the user document and **every artifact across 20 collections** (entries, conversations, photos, companion_devices, companion_commands, skills, heirs, letters, memories, identity_facts, personas, reminders, nudges, imports, sources, elevenlabs_settings, avatar_talks, magic_links, checkout_sessions, user_sessions). Writes a `deletion_log` entry for fraud/tax retention. Session cookie cleared. Without the `confirm=DELETE` query param → 400.
- ✅ **Settings → Danger Zone** UI: `prompt()` asks the user to type `DELETE` before calling the endpoint. After success, redirect to `/`. Other test users remain untouched (isolation verified).

**Business-model: BYO API key**
- ✅ `PUT /api/avatar/api-key` saves a user's personal D-ID key to `users.d_id_api_key`, returns a masked preview. `DELETE /api/avatar/api-key` clears it. `GET /api/avatar/me` now reports `has_personal_key` + `masked_key`.
- ✅ `avatar.py::_user_d_id_key()` helper — uses the user's personal key when present, falls back to the platform default. Means D-ID render costs come out of the customer's account, protecting our margin on the $79 lifetime.
- ✅ Settings → "Bring your own D-ID key" section with a password input, masked-key display, and Remove button.

**Companion auto-update**
- ✅ `/api/companion/poll` response now includes `script_version`. `_build_companion_script` injects a `SCRIPT_VERSION` constant. The companion's `poll_loop` calls `_check_and_self_update()` on every cycle — if the server version differs, it re-downloads `/public-script`, writes itself to disk, and `os.execv`s into the new script. Customers on old installs auto-upgrade within minutes of a deploy. Backup `.bak` is kept for safety.

**Mobile responsiveness**
- ✅ **AppLayout rewritten** with a slide-in mobile drawer. Desktop sidebar uses `hidden lg:flex`. Mobile shows a sticky top bar with hamburger button + brand + user avatar. Tapping the hamburger opens a `translate-x-0` drawer; tapping the scrim, pressing Escape, tapping the X button, or selecting a nav link all close it. ESC keypress wired; route-change auto-closes.
- ✅ **19 pages updated**: all `px-10 lg:px-16` patterns rewritten to `px-4 sm:px-8 lg:px-16` (16px mobile / 32px tablet / 64px desktop) so phones don't waste 40px of padding on each side.
- ✅ Mobile-tested: `/`, `/login`, `/buy`, `/twin`, `/dashboard` all show 0px horizontal overflow at 390×844 viewport.

**Removed**
- ✅ Emergent's default PostHog tracker stripped from `index.html` (was sending analytics to Emergent's account, not ours).

### Phase 11 — Aug 3, 2026 (Semantic Memory Search — Session D)
- ✅ **Backend semantic search stack**: new `services/embeddings.py` (provider-agnostic OpenAI-compat embeddings client + numpy cosine), semantic endpoints appended to `routers/memory.py` — GET `/api/memory/search/status`, POST `/api/memory/search/embed` (background) and `/embed/sync`, POST `/api/memory/search`. Vectors persisted in `archive_embeddings` with content-hash idempotency so re-embed skips unchanged entries. `MIN_SCORE=0.20` filters noise; anything below falls back to keyword regex.
- ✅ **Twin retrieval upgrade**: `twin_tools.exec_search_archive` now tries semantic first (via `semantic_lookup` helper), falls back to keyword when no provider or no vectors. Twin's `search_archive` tool description unchanged — quality lift is transparent.
- ✅ **Library UI**: new semantic-status ribbon (data-testid=`semantic-status`) shows "X of Y memories indexed" when provider on, or a Settings link when off. Enter key now triggers `POST /api/memory/search` (was `GET /api/archive?q=`). Rebuild-index button appears when provider on.
- ✅ **DB indexes**: two new compound indexes on `archive_embeddings` for fast per-user + per-model lookups.
- ✅ **Testing**: 2/2 my regressions (`test_iteration32_semantic.py`) + 6/6 testing-subagent coverage (`test_iteration32_semantic_extra.py`) + Playwright frontend green. Full 8/8 backend pass. No adjacent regressions (providers, archive, agent, roadmap, auth all still 200).
- **Note**: Emergent Universal Key does NOT cover embeddings (confirmed via integration playbook). By design there is no hosted fallback — users configure their own OpenAI key OR run local Ollama/LM Studio via the Providers system.

### Phase 10 — Aug 3, 2026 (Local AI foundation + public roadmap + mission)
- ✅ **Landing "Built with you" section**: honest positioning that Heirloom is in active development, we want early owners in the room. Amber-tinted card mid-page with three columns (what's live / on the workbench / what stays true) + dual CTAs (See the roadmap / Email the founders). Early-access badge added to the hero.
- ✅ **Public `/roadmap` page** (`/app/frontend/src/pages/Roadmap.jsx`): unauthenticated route listing every feature on the plan in three buckets (Already yours / On the workbench / Coming after). Spinning Loader2 icons signal "in-build", check marks signal shipped. Dual CTAs (Suggest a feature via mailto, Send feedback via /support). Copies the exact language from user's mission ("timeless gift handed down generation after generation").
- ✅ **Backend Providers CRUD** (`/api/providers`): 5 subsystems (chat, tts, stt, image, embeddings), per-user config persisted to `db.user_providers`. GET returns defaults for new users, PUT replaces, POST /reset wipes. `provider_type` supports `openai_compat` and `comfyui`. Enables the entire Local AI feature stack in future sessions.
- ✅ **Desktop "Local AI" Settings tab**: `settings_dialog.py` refactored into a QTabWidget with Vault + Local AI tabs. Local AI tab shows 5 provider rows (enable/URL/api key/model + Test button per row), with chips linking to Pinokio / Ollama / LM Studio / ComfyUI. Test button probes the local endpoint directly without leaking the Heirloom device token. Baked into `companion_desktop_data.py`.
- ✅ **Testing**: 8/8 backend green (`iteration_31.json`), Playwright frontend green, no regressions on adjacent routes.

### Backlog — Local AI feature sessions (queued in order)
- **Session A** — Wire desktop chat routing to local LLM when `chat.enabled=true`
- **Session B** — Wire desktop TTS + STT routing to local providers
- **Session C** — Photo restoration via ComfyUI (uses the Image provider)
- **Session D** — Semantic memory search (index archive via `embeddings` provider, `/api/memory/search`)
- **Session E** — LivePortrait avatar (replaces D-ID for talking-head videos)
- **Session F** — Speaker-diarized family-video import (WhisperX + pyannote)
- **Session G** — Handwriting OCR for old letters/journals
- **Session H** — Old-audio cleanup (Resemble Enhance)
- **Session I** — Emotion-aware TTS (Bark / StyleTTS 2)
- **Session J** — LoRA personality fine-tuning (unsloth on user's archive)
- **Session K** — Twilio phone calling (inbound + outbound)
- **Session L** — Desktop theme refactor (contrast + Recent redesign + Appearance picker)

## Backend test results
- iteration_15.json: **100% (10/10 + frontend all green)** — pre-sale hardening + mobile sweep regression. Account-deletion cascade across 20 collections + isolation, BYO D-ID key roundtrip + masking, companion script_version + auto-update mechanism, all 4 legal pages, footer rendering, mobile-drawer open/scrim-close/ESC-close/nav-tap-close, desktop sidebar regression. Zero open issues.
- iteration_14.json: 52 / 52 PRE-LAUNCH REGRESSION tests pass + 15 / 15 SPA routes load with zero console errors.
- iteration_13.json: 11 / 11 D-ID avatar backend tests pass + frontend Twin "Play as video" green.
- iteration_12.json: 18 / 18 Stripe checkout + auto-skill trigger tests pass.

### Phase 13 — Feb 27, 2026 (branded OG image)
- ✅ **Custom 1200×630 OG image** at `/og-image.jpg` (139KB). Composed via Pillow: dark library photograph + warm gradient overlay + the cyan Unbound "U" logo (black background extracted to alpha so it sits cleanly on the gradient) + accent overline ("AN UNBOUND INFOTECH PRODUCT · est. 2026 · heirloom.app") + Liberation-Serif "Heirloom" wordmark + two-line accent-colored tagline + sub-description + a measured-to-fit "$79 · LIFETIME · NO SUBSCRIPTION" pill chip.
- ✅ **Full OG + Twitter card meta** in `index.html`: `og:image`, `og:image:width=1200`, `og:image:height=630`, `og:image:alt`, `twitter:image`. JSON-LD `SoftwareApplication.image` already pointed here — now the file exists.
- ✅ Compose script saved to `/app/frontend/scripts/build_og_image.py` for future iterations.

### Phase 12 — Feb 27, 2026 (JSON-LD structured data)
- ✅ Added a 3-entity `@graph` JSON-LD block to `index.html` head: `Organization` (Unbound Infotech), `WebSite` (Heirloom), and `SoftwareApplication` (Heirloom) with full `Offer` ($79 USD lifetime), 7 `featureList` items, `applicationCategory`, and operating systems. All three entities are cross-referenced via `@id`. Makes Heirloom eligible for Google rich results (price snippet, software-app card, knowledge-graph entity for "Unbound Infotech"). No synthetic `aggregateRating` (would violate Google's structured-data policy).

### Phase 14 — Mar 1, 2026 (Live-stream twin + desktop promotion)

**Live-stream twin** — public, opt-in broadcasting of the twin
- ✅ Public route at `/twin/live/<handle>` — viewers see the twin avatar (D-ID talking head when speaking, static portrait when idle) + a live, auto-updating transcript of the last 15 turns
- ✅ Server-Sent Events stream at `GET /api/live/<handle>/stream` — pushes new turns + avatar render URLs in real time as the owner chats. In-process pub/sub bus (process-local for current single-worker setup; trivial Redis swap later)
- ✅ Owner controls in Settings → Live Broadcast: claim handle, copy public + OBS URLs, toggle broadcasting on/off, "private mode" kill-switch for sensitive chats
- ✅ Handle validation: 3-30 chars, a-z/0-9/_/-, no leading/trailing separators, ~50 reserved handles blocked (admin/api/www/etc.), 409 on collision, idempotent for the owner
- ✅ `?obs=1` query mode strips chrome — avatar fills the screen with transparent background, perfect for OBS "Browser Source" overlay for streamers
- ✅ Privacy by default — broadcasting OFF until owner explicitly enables. publish_turn silently no-ops if disabled or in private mode
- ✅ Cross-user isolation verified — user A's broadcast subscribers never see user B's turns
- ✅ Web (`/twin` `kind=twin`) AND desktop (`kind=companion_twin`) AND voice chat all route through publish hooks — one shared broadcast surface regardless of where the owner is chatting

**Desktop promotion**
- ✅ Landing page Windows section rewritten — "A real desktop app. Not a chatbot." hero plus 5-bullet feature list (avatar panel, cloned-voice TTS, push-to-talk, OBS pop-out, Local Vault)
- ✅ New "Three storage tiers" explainer card side-by-side with the desktop feature copy — explains Full / Partial / Lite plus the nightly compaction promise ("chat actually grows your twin")

**Desktop deploy path fix**
- ✅ Migrated `/app/companion_desktop/` → `/app/backend/companion_desktop/` so the source ships with production deploys. Fixes user-reported "Desktop app source missing" 500 in production
- ✅ `build_desktop_app_zip_bytes` now tries in-backend path first with dev fallback — clean migration, no behaviour change

**Tests (iteration 20)**
- ✅ `/app/backend/tests/test_iteration20_live.py` — **33/33 PASS**. Handle validation (all edge cases), claim idempotency + collision (409), settings PATCH semantics (enabled, private_mode, both, empty body), reserved-handle blocking (admin/api/www/twin/etc.), case normalization, public profile/recent endpoints (404 when disabled, 200 when enabled), SSE hello receipt over real HTTP, publish_turn pub/sub semantics (enabled+private_mode+cross-user isolation), and desktop zip rebuild from new in-backend path
- ✅ **Regression**: iter19 voice/exe 12/12, iter18 vault 9/9, iter17 desktop 12/12, iter16 Stripe 8/8. Path expectations updated to dual-look (in-backend first, dev fallback). **73/73 total.**

User pushed back hard: chat conversations were being saved but not making the twin
*smarter*. They wanted a "hardcore real twin program, not bullshit gimmicks". So we
built a proper personality archive that grows from every conversation.

**Local-first storage with three tiers**
- ✅ **New SQLite + filesystem vault** at the user's chosen folder (default `~/HeirloomVault` on Mac/Linux, `Documents/HeirloomVault` on Windows). Every chat turn — text and voice — is captured into `vault.db` with the raw WAV stored under `raw/<YYYY-MM-DD>/audio/<turn_id>.wav`.
- ✅ **Three storage tiers** (selectable in the new Settings dialog):
  - **Full** — keep all turns + audio forever. True legacy archive.
  - **Partial** (default) — keep audio 30 days then delete the WAV but keep the transcript. ~10× smaller.
  - **Lite** — once a day is compacted, delete its raw turns + audio, keep only the daily summary + extracted facts.
- ✅ Each tier ALWAYS uploads extracted facts to the cloud — local pruning never affects what the twin remembers.

**Daily compaction**
- ✅ New `POST /api/vault/compact` ships a date's transcript to Claude with a strict extraction prompt → returns `{facts:[{fact, kind}], summary, themes, turns_seen}`. Bounded to last 240 turns / 30k chars / 1500 chars per turn — safe context budget.
- ✅ New `POST /api/vault/facts/ingest` writes facts into `memory_facts` with `source='desktop_compaction'`. **Idempotent** by lower-cased fact text dedupe (within-batch + against existing).
- ✅ New `GET /api/vault/status` returns `{total_facts, facts_from_vault, total_archive_entries, last_compaction_at, last_compaction_date}` for the Settings UI.
- ✅ **Facts flow directly into the twin's system prompt** because they live in the same `memory_facts` collection the twin already reads. So things you say in chat actually become things your twin knows forever. Closes the gap.
- ✅ Per-day journal markdown written to `<vault>/journals/<date>.md` (human-readable record of what the twin learned that day).
- ✅ Full audit log table in `vault.db` for every append + compaction + policy-prune action.

**Maintenance scheduling (user-pickable)**
- ✅ **On quit** (default): when the user truly quits the app (tray Quit), `aboutToQuit` fires the compaction in a worker thread.
- ✅ **3 AM daily**: a `QTimer` arms for the next 3 AM local time, fires the compaction, then re-arms for tomorrow.
- ✅ **Manual only**: user clicks "Run maintenance now" in Settings to fire ad-hoc.
- ✅ Settings dialog also shows storage usage (bytes + file count + turn count) and last-compaction summary + cloud fact count.

**Frontend additions**
- ✅ `⚙` gear button on the desktop titlebar opens the Settings dialog.
- ✅ Vault folder picker, tier selector with descriptions, schedule selector, "Run maintenance now" button, live log of compaction progress, storage usage indicator.

**Tests (iteration 18)**
- ✅ `/app/backend/tests/test_iteration18_vault.py` — **9/9 PASS**. Live Claude compaction extracts ≥1 valid fact from a Vermont/Elias transcript; empty-turns short-circuit; auth 401s; ingest idempotency by lower-cased fact text; cross-user isolation; status counts only `desktop_compaction` facts; full SQLite vault unit test (append → turns_for_day → record_compaction → tier policies Full/Partial/Lite all verified).
- ✅ **Regression**: iter17 desktop 12/12, iter16 Stripe 8/8, user_isolation_fuzz 10/10. **39/39 total.**

**Stripe Payment Link wired into production**
- ✅ User's live Payment Link `https://buy.stripe.com/dRm9AT87I9Ky7C82MZdQQ00` (ID `plink_1TnP5pGsA7WZDU3uyECbEDm5`) is now the primary checkout path. `Buy.jsx` shows the price card + branded QR code side-by-side; clicking "Pay $79 with Stripe" opens the live link with `?prefilled_email=` baked in for cleaner post-purchase provisioning. The QR is for desktop visitors who want to scan with their phone.
- ✅ Webhook handler (`/api/webhook/stripe`) now parses `customer_details.email` from the raw Stripe payload so purchases coming through the static Payment Link (no `client_reference_id`, no `metadata.email`) still auto-provision: user row, companion device, magic-link email via Resend, one-time `.zip` download token. Tagged with `source="payment_link"`. Defense-in-depth: warns if a `payment_link` ID arrives that isn't the configured one.
- ✅ `_provision_after_payment` is fully idempotent (calling with same `session_id` returns existing artifacts, never duplicates). `stripe_events` event-level dedupe still catches retries.
- ✅ Webhook never raises — exceptions are caught and logged so Stripe doesn't enter a retry storm if D-ID/Resend hiccups during fulfillment. Idempotency means the next retry just succeeds.
- ✅ Tests: `/app/backend/tests/test_iteration16_payment_link.py` — **8/8 PASS**.

**Heirloom Desktop — full PySide6 Windows GUI** (replaces the background-only companion as the headline experience)
- ✅ New full desktop app at `/app/companion_desktop/` — a real native Qt window. Layout: titlebar with brand + status pill + push-to-talk button → 3-pane resizable splitter: left = Memories sidebar (recent archive entries, auto-refreshes when you Quick Capture), center = Avatar panel over Conversation thread, right = Quick Capture form. System tray icon keeps it alive when the window is closed.
- ✅ **Avatar panel** shows the user's portrait when idle, swaps to D-ID talking-head MP4 when the twin replies, and an animated waveform-ring when the user holds push-to-talk. Toggle between "D-ID" and "Waveform" modes via a header button — D-ID mode renders a real talking head every reply (costs ~$0.04), Waveform mode just pulses the ring (free, faster).
- ✅ **OBS pop-out**: "Pop out for OBS ↗" detaches the avatar to a frameless, transparent-background, always-on-top window titled "Heirloom Twin — Broadcast". OBS picks it up via Window Capture so users can stream their twin. Drag-to-move, geometry persists across launches.
- ✅ **Conversation thread**: bubble layout (Telegram-style) or flat layout (Slack-style vertical-rule) — toggle preserved in `%LOCALAPPDATA%/Heirloom/settings.json`. Enter to send, Shift+Enter for newline. History shared with the web `/twin` page via a single `kind="companion_twin"` conversation document — chat from anywhere, see it everywhere.
- ✅ **Push-to-talk**: hold Ctrl+Space (or click the titlebar button) to record. Mic level drives the waveform ring in real-time. Release → uploads 16kHz mono WAV to `/api/companion/voice` (existing endpoint), which transcribes + replies in one round-trip. Reply text is then sent through the avatar speak path.
- ✅ **Quick Capture**: title + type (note/memory/belief/story) + body + Save → POST `/api/desktop/capture` → entry appears in the Memories sidebar instantly. Tagged with `source="desktop"` for downstream attribution.
- ✅ **Distribution**: `GET /api/companion/desktop-package?token=<device_token>` returns `HeirloomDesktop.zip` with the full PySide6 source, a `Heirloom.bat` launcher, `requirements.txt`, and a README. First run on Windows: the bat creates a venv at `%LOCALAPPDATA%/Heirloom/venv`, pip-installs PySide6 + audio deps, then launches `pythonw -m heirloom` (no console window). Token + backend URL are baked into `heirloom/config.py` at zip-build time — zero sign-in required. No PyInstaller .exe yet (per user request to skip SmartScreen signing for now).
- ✅ **Backend endpoints (8 new)** under `/api/desktop/*` — all device-token-authed: `GET me`, `GET conversation`, `POST chat`, `POST avatar/talk`, `GET avatar/talk/{id}`, `POST capture`, `GET memories/recent`. Cross-user isolation verified (B's data cannot leak to A's token).
- ✅ Companion page now offers four download buttons, with **Heirloom Desktop (full app)** as the new primary CTA.
- ✅ Tests: `/app/backend/tests/test_iteration17_desktop.py` — **12/12 PASS**. Plus full regression: iter16 8/8 + user_isolation_fuzz 10/10 still green.
After Semrush audit (Health 78/100) flagged duplicate titles/descriptions, bad robots.txt format, low word count on /login, and a missing sitemap, fixed all code-level issues:
- ✅ **Per-route titles + meta descriptions** via lightweight `usePageMeta` hook (no React-Helmet dependency). Three unique titles now exist for the indexable surface: `/`, `/login`, `/buy`. Each restores the previous values on unmount.
- ✅ **Real `/robots.txt`** (plain text) with Allow/Disallow rules for every route and a `Sitemap:` directive. Previously CRA was returning the SPA HTML fallback.
- ✅ **`/sitemap.xml`** with the three public URLs (landing, login, buy) and proper priority/changefreq.
- ✅ **`/llms.txt`** with clean markdown — what Heirloom is, who it's for, core features, brand, privacy posture. Helps LLM crawlers correctly describe the product.
- ✅ **`index.html` default meta**: New `<title>`, real `<meta name="description">`, OpenGraph + Twitter cards, canonical link, theme-color updated to brand palette.
- ✅ **Login page word count**: 56 → 128 words. Added a descriptive paragraph explaining what Heirloom is so search engines no longer flag it as thin content.

### Phase 10 — Feb 27, 2026 (truly one-click Windows install)
- ✅ **Single-file `.bat` installer** (`GET /api/companion/easy-installer?token=...`) — downloads a 4.5KB self-contained Windows batch file. Double-click → does everything in ~60 seconds: silently installs Python 3.12 via `winget` if missing (`--scope user`, no UAC), downloads the personalized companion script, pip-installs deps to user-site, writes a VBS launcher that runs the python script HIDDEN (no flashing console), drops a shortcut in the Startup folder for auto-start on every Windows sign-in, and launches immediately. Tray icon appears. Done. End-user never sees a terminal, never types a command, never installs Python by hand.
- ✅ **Public companion-script route** (`GET /api/companion/public-script?token=...`) — needed because the `.bat` running on the user's PC has no browser cookie. Authentication is by device_token (a strong 256-bit random secret that already authorizes commands, so reading the script is no escalation).
- ✅ **Companion page UX**: reduced from "3 steps" to "2 steps" (Issue token → Double-click). Primary CTA is "Easy install (Windows, 1 file)" in accent color; old .zip and .py downloads remain as secondary/tertiary options for power users.
- ✅ VBS launcher uses `Chr(34)` for embedded quotes — keeps the Python `r"""..."""` template clean and avoids cmd.exe escaping hell.

### Phase 9 — Feb 27, 2026 (first-run welcome tour)
- ✅ **4-step Tour overlay** (`components/TourOverlay.jsx`) shown on first login after the user completes onboarding. Steps: "Capture in seconds" → "Sit with the biographer" → "Speak to your Twin" → "Leave it for them". Each step has a serif headline, body copy, animated step-counter dots, "Skip the tour" link, and a primary "Next" / final-step CTA that navigates the user to the corresponding page (Library/Interviewer/Twin/Heirs).
- ✅ **Persistence**: New `POST /api/auth/me/tour-complete` (idempotent, simple) sets `users.tour_completed = true`. `/auth/me` now returns this flag so the SPA shows the tour at most once. Dismissing via the X, "Skip the tour", or finishing all 4 steps all persist completion.
- ✅ **Verified end-to-end** via Playwright: tour renders on first visit, Next/Skip advance + dismiss correctly, tour does not reappear after page reload.

### Phase 11 — Feb 28, 2026 (Setup / Keys Wizard — BYO API keys + Avatar Studio finalized)
- ✅ **Avatar Studio finished + wired**: `/avatar-studio` route registered (was scaffolded but unreachable), Settings page now links to it via `[data-testid=avatar-studio-link]`. Three-angle upload + identity-preserving fal.ai Beautify slider (0–85%) + side-by-side preview before commit all working.
- ✅ **`/setup/keys` BYO wizard** (`pages/SetupKeys.jsx`): one card per provider (fal.ai, ElevenLabs, D-ID) with status badge (`using your key` / `using shared default` / `missing`), direct-to-dashboard deeplink, 4-step text walkthrough, password-masked input with reveal toggle, **live Verify button** (hits each provider's auth endpoint), Save, and Remove. OAuth section reuses existing Spotify/GitHub `/api/oauth/{svc}/login` endpoints. Read-only cards surface Resend + Stripe status. Settings has a prominent accent-bordered card linking to it.
- ✅ **Hybrid per-user override**: fal.ai now reads `user.fal_api_key` first then env `FAL_KEY` (matching the pattern already in place for ElevenLabs and D-ID). User keys take over without breaking shared-default UX. New backend endpoints: `GET /api/user-keys/status`, `POST /api/user-keys/verify`, `PUT /api/avatar-studio/api-key`, `DELETE /api/avatar-studio/api-key`. Added `PUT/DELETE /api/voice-clone/api-key` aliases so the wizard uses a uniform REST shape across all three providers.
- ✅ **Live verification logic**:
   - fal.ai → `GET https://api.fal.ai/v1/serverless/usage` (200 / 403 = valid, 401 = invalid)
   - ElevenLabs → `GET /v1/user` with `xi-api-key`
   - D-ID → `GET /credits` with Basic auth
   - Resend → `GET /domains` with Bearer token
- ✅ **Testing**: 13/13 backend tests pass (`test_iteration21_user_keys.py`). Playwright UI sweep confirmed all data-testids present, save/verify/clear flow works in the browser, and the hybrid override is wired through to `/avatar-studio/enhance`. User-supplied fal.ai key validated against the live fal.ai endpoint.



### Phase 8 — Feb 27, 2026 (pre-launch hardening for tester rollout)
- ✅ **MongoDB performance indexes**: New `db_indexes.py` creates 26 idempotent indexes at startup on every hot-path collection — `user_sessions.session_token` (every request), `users.user_id` (every request), `entries.user_id+created_at`, `companion_devices.token` (every 2s poll), `heirs.release_token` (public portal), `avatar_talks.talk_id`, and 20 more. Pruned legacy `token: null` rows and made the two token-unique indexes sparse-unique so they cleanly rebuild on cold start.
- ✅ **Settings.jsx runtime fix**: `CheckCircle2` symbol was used but not imported — would crash the ElevenLabs section when a cloned voice was set. Added to lucide-react imports.
- ✅ **Photos.jsx React refactor**: `PhotoCard` was defined inside the parent's render, so every parent state change destroyed the entire subtree and recreated all blob URLs. Extracted to a top-level component with `onRemove` prop — thumbnails are now stable and the page no longer re-fetches every photo on every render.
- ✅ **Production build verified**: `yarn build` passes cleanly (194KB gzipped main.js, 11KB CSS, 0 errors). App is deploy-ready.

### Phase 9 — Feb 28, 2026 (Focus/Agent mode + deploy fix)
- ✅ **Focus/Agent Mode** (`/api/agent/*` + `/agent` page): the twin plans multi-step actions across the owner's enabled Abilities, they approve the plan in one click, and the executor drives the PC companion via the existing `companion_commands` queue. Steps are either `companion` (queued to the desktop) or `notify` (informational). Sequential execution with 45s per-step timeout, live poll from the frontend, one-click cancel that also drops in-flight companion commands. LLM planner is constrained to the actual companion command kinds and the abilities the owner has toggled on — so shutdown/restart require an explicit `notify` warning first, and no-companion users still get a runnable notes-only plan.
- ✅ **litellm deploy blocker resolved**: swapped the URL-wheel pin (`litellm @ https://…/litellm-1.80.0-py3-none-any.whl`) in `backend/requirements.txt` for the plain `litellm==1.80.0` PyPI version. Production build no longer stalls on the internal-asset URL.
- ✅ **Stripe wiring verified**: all endpoints (`/api/billing/payment-link`, checkout session, `/api/webhook/stripe`) confirmed already complete via `emergentintegrations`. User just plugs in `STRIPE_API_KEY=sk_live_…` and `STRIPE_WEBHOOK_SECRET=whsec_…` in production env.
- ✅ **Testing**: 8/8 backend tests green (`test_iteration29_agent.py` + testing-subagent regression suite). Frontend E2E green — nav entry, plan input, suggestion chips, active-run timeline, approve/cancel controls, and history list all verified with the correct data-testids. No adjacent regressions (twin, letters, abilities, companion, photo-story all still 200).

## Backend test results
- iteration_12.json: 18 / 18 backend tests pass for Stripe checkout + auto-skill triggers.
- iteration_13.json: 11 / 11 D-ID avatar backend tests pass (real D-ID render completed in ~95s with valid .mp4). Frontend Twin "Play as video" + Settings avatar URL + 6 regression pages all green.
- **iteration_14.json: 52 / 52 PRE-LAUNCH REGRESSION tests pass + 15 / 15 SPA routes load with zero console errors.** Auth, archive, interviewer, twin, avatar, voice-clone, photos, companion, skills, heirs, letters, personas, memory, nudges, personality, music, Stripe — all covered. App is ship-ready for testers.
- Phase-6 smoke test: 8 / 8 endpoints green (brand kit save+load, persona create/activate/list/deactivate/delete, tts_language save). Frontend lint clean.
- **iteration_36.json: 19 / 19 backend + full frontend tests pass for Multi-Provider AI Router + Usage Tracking (Feb 2026).** Covered: catalog (7 providers, 6 tasks), BYOK key non-leakage (has_key boolean only), key preservation on empty-string PUT, task-route persistence, real Emergent Claude call with token+cost logging, fallback chain when BYOK key missing, verify endpoint 401 on bad OpenAI key, aggregate + per-event usage endpoints, resolve endpoint, 400 validation on unknown task/provider.

## Phase 37 — Feb 2026 (Provider Health Checks)
- ✅ **`services/provider_health.py`** — probes every enabled BYOK provider with a cheap `GET /v1/models` (Gemini adds `?key=` per its OpenAI-compat quirk). Emergent path validates the Universal Key + SDK import. Latency captured per probe. Records upserted into `provider_health` keyed on (user_id, provider) — no growing history.
- ✅ **Hourly background loop** — `health_loop()` sleeps 30s on boot, then refreshes every user with a `routing_configs` doc every 3600s. Registered on FastAPI startup as `app.state.provider_health_task`, cancelled on shutdown alongside the letter delivery loop.
- ✅ **`GET /api/routing/health`** — returns per-provider status filtered to currently-enabled providers. Stale rows from providers that were later disabled are surfaced as `status=unknown, error=disabled` so the UI never lies.
- ✅ **`POST /api/routing/health/check?provider=<id>`** — on-demand refresh (all providers if no query param). Returns the same shape as GET (no `user_id` leak).
- ✅ **Frontend** — every provider card in `/routing` now shows a colored dot (green/red/muted grey), the `checked HH:MM · Xms` timestamp/latency in the sub-line, and the truncated error inline when red. Header has a "Check provider health" button that triggers a fresh sweep.
- ✅ **Tested** — iteration_38.json: initially 13/14 backend + 100% frontend; two minor consistency nits (user_id leak on POST + stale rows for disabled providers) fixed in-line, no retest needed.

## Phase 36 — Feb 2026 (Photo Restoration + Local Chat + Auto-Detect + Budget Alerts)
- ✅ **Photo Restoration** — `/api/restoration/*` endpoints (create/list/get/result/fail). Restoration runs on the user's PC through the desktop companion: cloud enqueues a `restore_photo` command with the source photo URL + workflow hint; desktop calls the user's local ComfyUI (or any OpenAI-compat image API), uploads the result back, and the cloud stores it as a new photo entry (`is_restoration=true`). Three kinds: restore / colorize / upscale. UI: Wand2 button on each photo card in `/photos` opens a menu of restoration options; job status polled every 4s until complete.
- ✅ **Desktop `restore_photo` command handler** — `commands.py`: downloads source, ships to `/upload/image` → `/prompt` → polls `/history/{id}` → downloads output via `/view` → uploads back. Ships with a default GFPGAN workflow the user can override in Settings. Fails cleanly with a bubbled-up reason if ComfyUI isn't running or a node is missing.
- ✅ **Local Chat Routing** — `conversation.py` on the desktop now checks the user's `providers.chat` config and, when enabled, POSTs directly to `<base_url>/v1/chat/completions` from 127.0.0.1. Auto-falls back to cloud on failure so the user is never stuck.
- ✅ **Desktop Auto-Detect** — `settings_dialog.py` pings 127.0.0.1 on the well-known ports for Ollama (11434), LM Studio (1234), Kokoro-FastAPI (8880), Whisper.cpp (9000) and ComfyUI (8188) when the Local AI tab opens. Any empty provider URL that responds gets pre-filled with an "auto-detected · click enable" status.
- ✅ **Budget Alert Emails** — `_log_usage` hooks into `_maybe_send_budget_alert` which fires an 80%- and 100%-tier email (via Resend) when a routed provider crosses its monthly cap. Idempotency guarded by `budget_alerts` collection keyed on (user_id, provider, YYYY-MM, tier) so the owner is never spammed.
- ✅ **Test hygiene** — iteration_37.json: 17/17 backend + all restoration UI flows green. One cosmetic minor (unreachable manual `kind` check) removed post-report.

## Phase 35 — Feb 2026 (Multi-Provider AI Router + Usage Tracking)

- ✅ **`services/llm_router.py`** — unified router across 7 providers (emergent, openai, anthropic, gemini, groq, xai, deepseek). Non-emergent providers use `openai.AsyncOpenAI(base_url=..., api_key=...)` — Groq/xAI/DeepSeek are OpenAI-compatible out of the box. Emergent path uses `emergentintegrations.LlmChat` transparently.
- ✅ **Task-based routing** with per-task overrides — chat, interview, tools, cheap, long_context, embeddings. `resolve_provider()` walks a fallback chain skipping providers that are disabled, missing BYOK keys, or over their monthly budget cap.
- ✅ **Usage tracking** — every call logs to `usage_events` with prompt_tokens, completion_tokens, model, task, cost_usd (estimated from a per-model USD/1M pricing table).
- ✅ **Budget-aware auto-fallback** — when a provider crosses its monthly_budget_usd, the router transparently routes to the next viable provider in the chain (Emergent is the ultimate fallback so the app never bricks).
- ✅ **`/api/routing/*` endpoints** — catalog, config (GET+PUT with key redaction), chat, chat/stream (SSE), usage, usage/events, verify (live BYOK key check), resolve.
- ✅ **Frontend `/routing` page** — per-task dropdown table, provider cards (enable/model/key/verify/budget), live test-a-call panel, 30-day usage-by-provider and by-task tables, recent events log.
- ✅ **BYOK-strict** — API keys never sent back to the client (only a `has_key` boolean).
- ✅ **Hygiene** — dashboard word-count query now capped at 500 most-recent entries so large archives can't stall the dashboard.


## Prioritized backlog (next phases)

### P1 — Ship-ready
- **Stripe live-key rollover**: paste `STRIPE_API_KEY=sk_live_…` + `STRIPE_WEBHOOK_SECRET=whsec_…` into production env. Code already complete.

### P2 — Depth on existing pillars
- **Focus mode v2**: parallel steps, retries on failure, editable plan (drag to reorder / edit param).
- **Discord ingestion**: bot pulls DM/channel history to enrich the personality archive (bot token required).
- **Home Assistant local integration**: control lights/plugs/scenes via HA REST API (HA URL + long-lived token required).
- **Yearbook PDF generation**: printable "life yearbook" from archive entries.

### P3 — Legacy & community
- Family-tree graph linking memories to people.
- Export full archive as PDF memoir + JSON.

## Known limitations (transparent to user)
- Cloud-hosted: cannot directly control local devices without a webhook endpoint or local companion.
- Discord voice channel listening is not feasible via Discord's API — replaced with chat log import.
- Always-on "in the room" mic requires the local companion (P0 next).
