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

### Phase 11 — Feb 27, 2026 (SEO hardening for public launch)
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

### Phase 8 — Feb 27, 2026 (pre-launch hardening for tester rollout)
- ✅ **MongoDB performance indexes**: New `db_indexes.py` creates 26 idempotent indexes at startup on every hot-path collection — `user_sessions.session_token` (every request), `users.user_id` (every request), `entries.user_id+created_at`, `companion_devices.token` (every 2s poll), `heirs.release_token` (public portal), `avatar_talks.talk_id`, and 20 more. Pruned legacy `token: null` rows and made the two token-unique indexes sparse-unique so they cleanly rebuild on cold start.
- ✅ **Settings.jsx runtime fix**: `CheckCircle2` symbol was used but not imported — would crash the ElevenLabs section when a cloned voice was set. Added to lucide-react imports.
- ✅ **Photos.jsx React refactor**: `PhotoCard` was defined inside the parent's render, so every parent state change destroyed the entire subtree and recreated all blob URLs. Extracted to a top-level component with `onRemove` prop — thumbnails are now stable and the page no longer re-fetches every photo on every render.
- ✅ **Production build verified**: `yarn build` passes cleanly (194KB gzipped main.js, 11KB CSS, 0 errors). App is deploy-ready.

## Backend test results
- iteration_12.json: 18 / 18 backend tests pass for Stripe checkout + auto-skill triggers.
- iteration_13.json: 11 / 11 D-ID avatar backend tests pass (real D-ID render completed in ~95s with valid .mp4). Frontend Twin "Play as video" + Settings avatar URL + 6 regression pages all green.
- **iteration_14.json: 52 / 52 PRE-LAUNCH REGRESSION tests pass + 15 / 15 SPA routes load with zero console errors.** Auth, archive, interviewer, twin, avatar, voice-clone, photos, companion, skills, heirs, letters, personas, memory, nudges, personality, music, Stripe — all covered. App is ship-ready for testers.
- Phase-6 smoke test: 8 / 8 endpoints green (brand kit save+load, persona create/activate/list/deactivate/delete, tts_language save). Frontend lint clean.

## Prioritized backlog (next phases)

### P1 — Polish on existing pillars
- **Companion TTS playback with cloned voice**: stream the twin's reply audio back to the on-PC speaker (currently uses local OS TTS — `say`/`espeak`/SAPI). Wire to ElevenLabs for in-room presence.
- **Email notifications**: when an heir is released, auto-email them the portal link (currently the owner must copy the link manually).
- **Long-conversation memory compaction** — summarize old turns so Claude context never overflows.
- **Photo linking** — attach photos to archive entries so the Twin can reference them by description.

### P2 — Legacy & community
- Discord bot (text channels) for passive personality capture.
- Family-tree graph linking memories to people.
- Export full archive as PDF "memoir" + JSON.

## Known limitations (transparent to user)
- Cloud-hosted: cannot directly control local devices without a webhook endpoint or local companion.
- Discord voice channel listening is not feasible via Discord's API — replaced with chat log import.
- Always-on "in the room" mic requires the local companion (P0 next).
